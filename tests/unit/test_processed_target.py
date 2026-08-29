"""Tests for starbash.processed_target module."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import tomlkit
from toml_repo import Repo

from starbash.processed_target import ProcessedTarget
from starbash.stage_utils import (
    find_stage_entry,
    is_excluded,
    mark_excluded,
    mark_used,
    prune_empty_stages,
    upsert_stage,
)


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


class TestStageAotHelpers:
    """Tests for the [[stages]] array-of-tables helpers."""

    def test_upsert_creates_entry_with_description_comment(self):
        container: dict = {}
        stage = {"name": "preprocessing", "description": "Preprocess light frames"}

        entry = upsert_stage(container, stage)

        assert entry["name"] == "preprocessing"
        assert find_stage_entry(container, "preprocessing") is not None

    def test_upsert_is_idempotent(self):
        container: dict = {}
        stage = {"name": "stacking"}
        upsert_stage(container, stage)
        upsert_stage(container, stage)
        assert len(container["stages"]) == 1

    def test_prune_removes_nameless_entries(self):
        import tomlkit

        aot = tomlkit.aot()
        aot.append(tomlkit.table())  # placeholder empty entry (like the template)
        container = {"stages": aot}
        upsert_stage(container, {"name": "real_stage"})

        assert len(container["stages"]) == 2
        prune_empty_stages(container)
        assert [s.get("name") for s in container["stages"]] == ["real_stage"]

    def test_prune_no_op_when_all_named(self):
        container: dict = {}
        upsert_stage(container, {"name": "a"})
        upsert_stage(container, {"name": "b"})
        prune_empty_stages(container)
        assert len(container["stages"]) == 2

    def test_mark_excluded_and_is_excluded(self):
        container: dict = {}
        mark_excluded(container, [{"name": "denoise"}])
        assert is_excluded(container, "denoise") is True

    def test_mark_used_clears_excluded_flag(self):
        container: dict = {}
        upsert_stage(container, {"name": "denoise"}, excluded=True)
        assert is_excluded(container, "denoise") is True

        mark_used(container, [{"name": "denoise"}])
        assert is_excluded(container, "denoise") is False

    def test_is_excluded_unknown_stage(self):
        container: dict = {}
        assert is_excluded(container, "missing") is False


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

    def test_mark_used(self, processed_target):
        """mark_used records each stage as a non-excluded [[stages]] entry."""
        used_stages = [
            {"name": "stage1", "description": "First stage"},
            {"name": "stage2", "description": "Second stage"},
        ]

        test_dict: dict = {}
        mark_used(test_dict, used_stages)

        assert "stages" in test_dict
        assert len(test_dict["stages"]) == 2
        assert is_excluded(test_dict, "stage1") is False

    def test_mark_excluded(self, processed_target):
        """mark_excluded flags each stage as excluded."""
        stages_to_exclude = [
            {"name": "calibration", "description": "Calibrate frames"},
            {"name": "registration"},
        ]

        test_dict: dict = {}
        mark_excluded(test_dict, stages_to_exclude)

        assert len(test_dict["stages"]) == 2
        assert is_excluded(test_dict, "calibration") is True
        assert is_excluded(test_dict, "registration") is True

    def test_is_excluded_reads_flag(self, processed_target):
        """is_excluded reflects the excluded flag on a [[stages]] entry."""
        container: dict = {}
        upsert_stage(container, {"name": "stage1"}, excluded=True)
        upsert_stage(container, {"name": "stage2"}, excluded=False)

        assert is_excluded(container, "stage1") is True
        assert is_excluded(container, "stage2") is False

    def test_is_excluded_missing_key(self, processed_target):
        """is_excluded returns False when there is no stages entry."""
        assert is_excluded({"stages": tomlkit.aot()}, "anything") is False


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

        existing = tomlkit.aot()
        upsert_stage({"stages": existing}, {"name": "stage1"}, excluded=True)

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            def mock_get(*args, **kwargs):
                if args[0] == "stages":
                    return existing
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # The pre-existing exclusion survives and isn't flipped.
            assert is_excluded(pt.default_stages, "stage1") is True

    def test_user_exclusions_from_toml_are_retained(
        self, mock_processing_like, temp_processing_dir
    ):
        """Regression: exclusions read from the target's starbash.toml must survive init.

        Previously __init__ reset self.default_stages to {} *after* _init_from_toml()
        populated it, so user-added exclusions (e.g. "stack_osc") were silently dropped
        and the excluded stage would still run.
        """
        mock_processing_like.stages = [
            {"name": "stack_osc"},
            {"name": "stack_single_duo"},
        ]

        existing = tomlkit.aot()
        upsert_stage({"stages": existing}, {"name": "stack_osc"}, excluded=True)

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            def mock_get(*args, **kwargs):
                if args[0] == "stages":
                    return existing
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # The user's exclusion must still be present after construction.
            assert is_excluded(pt.default_stages, "stack_osc") is True

    def test_set_default_stages_with_used_list(self, mock_processing_like, temp_processing_dir):
        """Test that stages already present (used) are not excluded by default."""
        mock_processing_like.stages = [
            {"name": "stage1", "exclude_by_default": True},
        ]

        existing = tomlkit.aot()
        upsert_stage({"stages": existing}, {"name": "stage1"}, excluded=False)

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {}
            mock_repo = MagicMock()

            def mock_get(*args, **kwargs):
                if args[0] == "stages":
                    return existing
                return {}

            mock_repo.get.side_effect = mock_get
            mock_repo_class.return_value = mock_repo

            pt = ProcessedTarget(mock_processing_like, "test")

            # Stage1 already had an entry, so exclude_by_default must not flip it.
            assert is_excluded(pt.default_stages, "stage1") is False


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

    def test_collects_sorted_report_sessions_and_frames(self, mock_processing_like, temp_processing_dir):
        """Report data is sorted and contains the approved metadata only."""
        mock_processing_like.sessions = [
            {"id": 2, "start": "2026-08-10T00:00:00", "end": "2026-08-10T02:00:00", "metadata": {
                "OBJECT": "M42", "FOCALLEN": 600.0, "SITELAT": 1.0, "TELESCOP": "Scope", "INSTRUME": "Camera",
            }},
            {"id": 1, "start": "2026-08-09T00:00:00", "end": "2026-08-09T02:00:00", "metadata": {
                "FOCALLEN": 500.0, "TELESCOP": "Scope", "INSTRUME": "Camera",
            }},
        ]
        images = {
            2: [{"DATE-OBS": "2026-08-10T01:00:00", "DEWPOINT": 2.0, "SITELAT": 3.0},
                {"DATE-OBS": "2026-08-10T00:30:00", "HUMIDITY": 80.0}],
            1: [],
        }
        mock_processing_like.sb.repo_manager.get.side_effect = lambda key, default=None: {
            "repo.metadata_blacklist": ["SITELAT"],
            "equipment": [],
        }.get(key, default)
        mock_processing_like.sb.get_session_images.side_effect = lambda session: images[session["id"]]

        with (
            patch("starbash.processed_target.toml_from_template") as mock_template,
            patch("starbash.processed_target.Repo") as mock_repo_class,
        ):
            mock_template.return_value = {"about": {}}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo
            pt = ProcessedTarget(mock_processing_like, "test")
            pt._collect_sessions_info()

        assert [info.id for info in pt.sessions_info] == [1, 2]
        assert [frame.metadata for frame in pt.sessions_info[1].frames] == [
            {"DATE-OBS": "2026-08-10T00:30:00", "HUMIDITY": 80.0},
            {"DATE-OBS": "2026-08-10T01:00:00", "DEWPOINT": 2.0},
        ]
        assert "SITELAT" not in pt.sessions_info[1].frames[0].metadata
        assert pt.sessions_info[0].metadata == {"FOCALLEN": 500.0}


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
            mock_template.return_value = {"repo": {"kind": "processed-target"}, "about": {}}
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
            mock_template.return_value = {"repo": {"kind": "processed-target"}, "about": {}}
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
            mock_template.return_value = {"repo": {"kind": "processed-target"}, "about": {}}
            mock_repo = MagicMock()
            mock_repo.get.return_value = {}
            mock_repo_class.return_value = mock_repo

            with ProcessedTarget(mock_processing_like, "test") as pt:
                assert pt is not None
                assert pt.config_valid is True

            # After exiting context, close should have been called
            mock_repo.write_config.assert_called()
