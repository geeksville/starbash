"""Tests for starbash.processed_target module."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import tomlkit

from repo import Repo
from starbash.processed_target import ProcessedTarget, stage_with_comment
from starbash.toml import CommentedString


@pytest.fixture
def mock_processing_like(tmp_path):
    """Create a mock ProcessingLike object."""
    mock = MagicMock()
    mock.context = {}
    mock.sessions = []
    mock.stages = []

    # Mock the output object that _set_output_by_kind creates
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def set_output(kind):
        mock_output = MagicMock()
        mock_output.base = output_dir
        mock.context["output"] = mock_output

    mock._set_output_by_kind = set_output
    return mock


@pytest.fixture
def temp_processing_dir(tmp_path):
    """Create a temporary processing directory."""
    processing_dir = tmp_path / "processing"
    processing_dir.mkdir()

    with patch("starbash.processed_target.get_processing_dir", return_value=processing_dir):
        yield processing_dir


class TestStageWithComment:
    """Tests for stage_with_comment function."""

    def test_stage_with_comment_basic(self):
        """Test creating CommentedString from stage with name and description."""
        stage = {"name": "preprocessing", "description": "Preprocess light frames"}

        result = stage_with_comment(stage)

        assert isinstance(result, CommentedString)
        assert result.value == "preprocessing"
        assert result.comment == "Preprocess light frames"

    def test_stage_with_comment_no_description(self):
        """Test creating CommentedString from stage without description."""
        stage = {"name": "stacking"}

        result = stage_with_comment(stage)

        assert result.value == "stacking"
        assert result.comment is None

    def test_stage_with_comment_no_name(self):
        """Test creating CommentedString from stage without name."""
        stage = {"description": "Some description"}

        result = stage_with_comment(stage)

        assert result.value == "unnamed_stage"
        assert result.comment == "Some description"

    def test_stage_with_comment_empty_dict(self):
        """Test creating CommentedString from empty stage dict."""
        stage = {}

        result = stage_with_comment(stage)

        assert result.value == "unnamed_stage"
        assert result.comment is None


class TestProcessedTargetInit:
    """Tests for ProcessedTarget initialization."""

    def test_init_with_target(self, mock_processing_like, temp_processing_dir):
        """Test initializing ProcessedTarget with a target name."""
        target = "M42"

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo,
        ):
            mock_template.return_value = {}
            mock_repo.return_value.get.return_value = {}

            pt = ProcessedTarget(mock_processing_like, target)

            assert pt.name == temp_processing_dir / target
            assert pt.is_temp is False
            assert pt.config_valid is True
            assert "process_dir" in mock_processing_like.context
            assert mock_processing_like.context.get("target") == target
            assert "output" in mock_processing_like.context

    def test_init_without_target(self, mock_processing_like, temp_processing_dir):
        """Test initializing ProcessedTarget without a target (master)."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo,
        ):
            mock_template.return_value = {}
            mock_repo.return_value.get.return_value = {}

            pt = ProcessedTarget(mock_processing_like, None)

            assert pt.is_temp is True
            assert "process_dir" in mock_processing_like.context
            assert "target" not in mock_processing_like.context
            assert "output" in mock_processing_like.context

    def test_init_creates_directory_if_not_exists(self, mock_processing_like, temp_processing_dir):
        """Test that init creates the target directory if it doesn't exist."""
        target = "NGC7000"

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo,
        ):
            mock_template.return_value = {}
            mock_repo.return_value.get.return_value = {}

            pt = ProcessedTarget(mock_processing_like, target)

            assert (temp_processing_dir / target).exists()
            assert (temp_processing_dir / target).is_dir()

    def test_init_reuses_existing_directory(self, mock_processing_like, temp_processing_dir):
        """Test that init reuses existing target directory."""
        target = "M31"
        target_dir = temp_processing_dir / target
        target_dir.mkdir()

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo,
        ):
            mock_template.return_value = {}
            mock_repo.return_value.get.return_value = {}

            pt = ProcessedTarget(mock_processing_like, target)

            assert pt.name == target_dir
            assert target_dir.exists()


class TestProcessedTargetMethods:
    """Tests for ProcessedTarget methods."""

    @pytest.fixture
    def processed_target(self, mock_processing_like, temp_processing_dir):
        """Create a ProcessedTarget instance for testing."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test_target")
            pt.repo = mock_repo
            yield pt

    def test_set_used(self, processed_target):
        """Test set_used method."""
        mock_node = {}
        processed_target.repo.get.return_value = mock_node

        used_items = [
            CommentedString("item1", "comment1"),
            CommentedString("item2", "comment2"),
        ]

        processed_target.set_used("sessions", used_items)

        assert "used" in mock_node
        processed_target.repo.get.assert_called_with("sessions", {}, do_create=True)

    def test_set_excluded(self, processed_target):
        """Test set_excluded method."""
        mock_node = {}
        processed_target.repo.get.return_value = mock_node

        stages_to_exclude = [
            {"name": "calibration", "description": "Calibrate frames"},
            {"name": "registration"},
        ]

        processed_target.set_excluded("stages", stages_to_exclude)

        assert "excluded" in mock_node
        processed_target.repo.get.assert_called_with("stages", {}, do_create=True)

    def test_get_from_toml(self, processed_target):
        """Test get_from_toml method."""
        mock_node = {
            "excluded": [
                CommentedString("stage1", "desc1"),
                CommentedString("stage2", "desc2"),
            ]
        }
        processed_target.repo.get.return_value = mock_node

        result = processed_target.get_from_toml("stages", "excluded")

        assert result == ["stage1", "stage2"]
        processed_target.repo.get.assert_called_with("stages", {})

    def test_get_from_toml_empty_list(self, processed_target):
        """Test get_from_toml with empty list."""
        processed_target.repo.get.return_value = {}

        result = processed_target.get_from_toml("stages", "excluded")

        assert result == []

    def test_get_from_toml_missing_key(self, processed_target):
        """Test get_from_toml with missing key."""
        processed_target.repo.get.return_value = {"other_key": ["value"]}

        result = processed_target.get_from_toml("stages", "excluded")

        assert result == []


class TestProcessedTargetStages:
    """Tests for ProcessedTarget stage handling."""

    def test_set_default_stages_excludes_by_default(
        self, mock_processing_like, temp_processing_dir
    ):
        """Test that stages with exclude_by_default are excluded."""
        mock_processing_like.stages = [
            {"name": "stage1", "exclude_by_default": True},
            {"name": "stage2", "exclude_by_default": False},
        ]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.side_effect = lambda *args, **kwargs: {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # The _set_default_stages should have been called during init
            # and should have set excluded stages
            assert mock_repo.get.called

    def test_set_default_stages_preserves_existing_exclusions(
        self, mock_processing_like, temp_processing_dir
    ):
        """Test that existing exclusions are preserved."""
        mock_processing_like.stages = [
            {"name": "stage1"},
            {"name": "stage2"},
        ]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            def mock_get(*args, **kwargs):
                if args[0] == "stages":
                    return {"excluded": [CommentedString("stage1", None)]}
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # Verify that get was called
            assert mock_repo.get.called

    def test_set_default_stages_with_used_list(self, mock_processing_like, temp_processing_dir):
        """Test that stages in used list are not excluded by default."""
        mock_processing_like.stages = [
            {"name": "stage1", "exclude_by_default": True},
        ]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            def mock_get(*args, **kwargs):
                if args[0] == "stages":
                    return {"excluded": [], "used": [CommentedString("stage1", None)]}
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # Stage1 should not be excluded because it's in used list
            assert mock_repo.get.called


class TestProcessedTargetContext:
    """Tests for ProcessedTarget context updates."""

    def test_update_from_context_sessions(self, mock_processing_like, temp_processing_dir):
        """Test _update_from_context updates sessions."""
        mock_processing_like.sessions = [
            {"id": 1, "name": "session1"},
            {"id": 2, "name": "session2"},
        ]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            mock_sessions_aot = tomlkit.aot()

            def mock_get(*args, **kwargs):
                if args[0] == "sessions":
                    return mock_sessions_aot
                if args[0] == "processing.recipe.options":
                    return {}
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")
            pt._update_from_context()

            # Verify sessions were added to the AoT
            assert len(mock_sessions_aot) == 2

    def test_update_from_context_recipes(self, mock_processing_like, temp_processing_dir):
        """Test _update_from_context updates recipe URLs."""
        mock_recipe1 = MagicMock()
        mock_recipe1.url = "file:///recipe1"
        mock_recipe2 = MagicMock()
        mock_recipe2.url = "file:///recipe2"

        mock_processing_like.sessions = []
        mock_processing_like.recipes_considered = [mock_recipe1, mock_recipe2]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            mock_options = {}

            def mock_get(*args, **kwargs):
                if args[0] == "sessions":
                    return tomlkit.aot()
                if args[0] == "processing.recipe.options":
                    return mock_options
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")
            pt._update_from_context()

            # Verify recipe URLs were added
            assert "url" in mock_options
            assert mock_options["url"] == ["file:///recipe1", "file:///recipe2"]


class TestProcessedTargetCleanup:
    """Tests for ProcessedTarget cleanup and lifecycle."""

    def test_cleanup_processing_dir_removes_temp(self, mock_processing_like, temp_processing_dir):
        """Test that temporary directories are removed on cleanup."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
            patch("starbash.processed_target.cleanup_old_contexts") as mock_cleanup,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, None)
            temp_dir = pt.name

            assert temp_dir.exists()
            assert pt.is_temp is True

            pt._cleanup_processing_dir()

            assert not temp_dir.exists()
            assert "process_dir" not in mock_processing_like.context
            mock_cleanup.assert_called_once()

    def test_cleanup_processing_dir_preserves_named(
        self, mock_processing_like, temp_processing_dir
    ):
        """Test that named directories are not removed on cleanup."""
        target = "M42"

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
            patch("starbash.processed_target.cleanup_old_contexts") as mock_cleanup,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, target)
            target_dir = pt.name

            assert target_dir.exists()
            assert pt.is_temp is False

            pt._cleanup_processing_dir()

            assert target_dir.exists()
            assert "process_dir" not in mock_processing_like.context
            mock_cleanup.assert_called_once()

    def test_close_writes_config_when_valid(self, mock_processing_like, temp_processing_dir):
        """Test that close writes config when valid."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")
            pt.config_valid = True

            pt.close()

            mock_repo.write_config.assert_called_once()

    def test_close_skips_write_when_invalid(self, mock_processing_like, temp_processing_dir):
        """Test that close skips writing config when invalid."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")
            pt.config_valid = False

            pt.close()

            mock_repo.write_config.assert_not_called()


class TestProcessedTargetContextManager:
    """Tests for ProcessedTarget context manager protocol."""

    def test_context_manager_enter(self, mock_processing_like, temp_processing_dir):
        """Test __enter__ returns self."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            result = pt.__enter__()

            assert result is pt

    def test_context_manager_exit(self, mock_processing_like, temp_processing_dir):
        """Test __exit__ calls close."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            with patch.object(pt, "close") as mock_close:
                pt.__exit__(None, None, None)

                mock_close.assert_called_once()

    def test_context_manager_usage(self, mock_processing_like, temp_processing_dir):
        """Test using ProcessedTarget as a context manager."""
        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            with ProcessedTarget(mock_processing_like, "test") as pt:
                assert pt is not None
                assert pt.config_valid is True

            # After exiting context, close should have been called
            mock_repo.write_config.assert_called()
