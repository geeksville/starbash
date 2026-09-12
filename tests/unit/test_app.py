"""Unit tests for the Starbash app module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest
import typer

from starbash import paths
from starbash.app import Starbash, copy_images_to_dir, create_user, setup_logging
from starbash.database import Database, get_column_name
from starbash.selection import Selection


class TestCreateUser:
    """Tests for the create_user function."""

    def test_create_user_creates_config_dir(self, setup_test_environment):
        """Test that create_user creates the user config directory."""
        config_dir = create_user()
        assert config_dir.exists()
        assert config_dir.is_dir()

    def test_create_user_creates_config_file(self, setup_test_environment):
        """Test that create_user creates starbash.toml config file."""
        config_dir = create_user()
        config_file = config_dir / "starbash.toml"
        assert config_file.exists()
        assert config_file.is_file()

    def test_create_user_idempotent(self, setup_test_environment):
        """Test that calling create_user multiple times is safe."""
        config_dir1 = create_user()
        config_dir2 = create_user()
        assert config_dir1 == config_dir2
        assert (config_dir1 / "starbash.toml").exists()


class TestCopyImagesToDir:
    """Tests for the copy_images_to_dir function."""

    def test_copy_images_to_dir_with_symlinks(self, tmp_path, capsys):
        """Test that copy_images_to_dir creates symlinks when possible."""
        # Create source files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file2 = source_dir / "image2.fit"
        file1.write_text("test data 1")
        file2.write_text("test data 2")

        # Create output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata
        images = [
            {"abspath": str(file1)},
            {"abspath": str(file2)},
        ]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify symlinks were created
        dest1 = output_dir / "image1.fit"
        dest2 = output_dir / "image2.fit"
        assert dest1.exists()
        assert dest2.exists()
        assert dest1.is_symlink()
        assert dest2.is_symlink()
        assert dest1.resolve() == file1.resolve()
        assert dest2.resolve() == file2.resolve()

        # Check output messages
        captured = capsys.readouterr()
        assert "Exporting 2 images" in captured.out
        assert "Export complete!" in captured.out
        assert "Linked: 2 files" in captured.out

    @patch("starbash.app.symlink_or_copy")
    def test_copy_images_to_dir_fallback_to_copy(self, mock_symlink_or_copy, tmp_path, capsys):
        """Test that copy_images_to_dir uses symlink_or_copy which handles fallback."""
        # Create source files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file1.write_text("test data 1")

        # Create output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata
        images = [{"abspath": str(file1)}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify symlink_or_copy was called with correct arguments
        mock_symlink_or_copy.assert_called_once_with(
            str(file1.resolve()), str(output_dir / "image1.fit")
        )

        # Check output messages
        captured = capsys.readouterr()
        assert "Exporting 1 images" in captured.out
        assert "Export complete!" in captured.out
        assert "Linked: 1 files" in captured.out

    def test_copy_images_to_dir_missing_source(self, tmp_path, capsys):
        """Test that copy_images_to_dir handles missing source files."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata with non-existent file
        images = [{"abspath": "/nonexistent/file.fit"}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify error was reported
        captured = capsys.readouterr()
        assert "Source file not found" in captured.out
        assert "Errors: 1 files" in captured.out

    def test_copy_images_to_dir_existing_destination(self, tmp_path, capsys):
        """Test that copy_images_to_dir skips existing destination files."""
        # Create source file
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file1.write_text("test data")

        # Create output directory with existing file
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "image1.fit"
        existing.write_text("existing data")

        # Create image metadata
        images = [{"abspath": str(file1)}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify file was not overwritten
        assert existing.read_text() == "existing data"

        # Check output messages
        captured = capsys.readouterr()
        assert "Skipping existing file" in captured.out
        assert "Errors: 1 files" in captured.out

    def test_copy_images_to_dir_mixed_results(self, tmp_path, capsys):
        """Test copy_images_to_dir with a mix of successful and failed operations."""
        # Create some source files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file2 = source_dir / "image2.fit"
        file1.write_text("test data 1")
        file2.write_text("test data 2")

        # Create output directory with one existing file
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "image2.fit"
        existing.write_text("existing")

        # Create image metadata with one good, one existing, one missing
        images = [
            {"abspath": str(file1)},
            {"abspath": str(file2)},
            {"abspath": "/nonexistent/file.fit"},
        ]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify results
        dest1 = output_dir / "image1.fit"
        assert dest1.exists()
        assert dest1.is_symlink()

        # Check output messages
        captured = capsys.readouterr()
        assert "Exporting 3 images" in captured.out
        assert "Linked: 1 files" in captured.out
        assert "Errors: 2 files" in captured.out

    def test_copy_images_to_dir_empty_list(self, tmp_path, capsys):
        """Test copy_images_to_dir with empty image list."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Call with empty list
        copy_images_to_dir([], output_dir)

        # Check output
        captured = capsys.readouterr()
        assert "Exporting 0 images" in captured.out
        assert "Export complete!" in captured.out

    def test_copy_images_to_dir_missing_abspath_key(self, tmp_path, capsys):
        """Test copy_images_to_dir handles images without abspath key."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata without abspath key (empty string path resolves to cwd)
        images = [{"metadata": "some data"}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Check that it handled gracefully (empty path name causes it to skip with existing file message)
        captured = capsys.readouterr()
        assert "Exporting 1 images" in captured.out
        assert "Skipping existing file" in captured.out
        assert "Errors: 1 files" in captured.out


class TestStarbashInit:
    """Tests for Starbash.__init__."""

    def test_init_creates_database(self, setup_test_environment, mock_analytics):
        """Test that Starbash initialization creates a database."""
        with Starbash() as app:
            assert app.db is not None
            assert isinstance(app.db, Database)

    def test_init_creates_repo_manager(self, setup_test_environment, mock_analytics):
        """Test that Starbash initialization creates a repo manager."""
        with Starbash() as app:
            assert app.repo_manager is not None
            assert len(app.repo_manager.repos) > 0

    def test_init_creates_selection(self, setup_test_environment, mock_analytics):
        """Test that Starbash initialization creates a selection."""
        with Starbash() as app:
            assert app.selection is not None
            assert isinstance(app.selection, Selection)

    def test_init_adds_default_repo(self, setup_test_environment, mock_analytics):
        """Test that Starbash adds the pkg://defaults repo."""
        with Starbash() as app:
            # Check that at least one repo is loaded
            assert len(app.repo_manager.repos) >= 1
            # Check that the first repo is the defaults
            assert app.repo_manager.repos[0].url == "pkg://defaults"

    def test_init_adds_user_repo(self, setup_test_environment, mock_analytics):
        """Test that Starbash adds the user config as a repo."""
        with Starbash() as app:
            assert app.user_repo is not None
            assert app.user_repo.is_scheme("file")

    def test_init_loads_max_contexts_from_user_config(self, setup_test_environment, mock_analytics):
        """Test that the processing-context limit is loaded from user preferences."""
        config_path = paths.get_user_config_path()
        config_path.write_text(
            '[repo]\nkind = "preferences"\n\n[config]\nmax_contexts = 7\n',
            encoding="utf-8",
        )

        with Starbash() as app:
            from starbash import doit_types

            assert app.user_repo.get("config.max_contexts") == 7
            assert doit_types.max_contexts == 7

    def test_init_with_analytics_disabled(self, setup_test_environment, mock_analytics):
        """Test initialization when analytics is disabled in user config."""
        # Create user config with analytics disabled
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text("[repo]\n\n[analytics]\nenabled = false\n")

        with Starbash() as app:
            # Analytics setup should not be called
            mock_analytics["setup"].assert_not_called()

    def test_init_with_analytics_enabled(self, setup_test_environment, mock_analytics):
        """Test initialization when analytics is enabled in user config."""
        # Create user config with analytics enabled
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text("[repo]\n\n[analytics]\nenabled = true\n")

        with Starbash() as app:
            # Analytics setup should be called
            mock_analytics["setup"].assert_called_once()

    def test_init_analytics_enabled_by_default(self, setup_test_environment, mock_analytics):
        """Analytics defaults to enabled when the user has not chosen either way."""
        # The freshly-created user config leaves analytics unset (commented out).
        with Starbash() as app:
            mock_analytics["setup"].assert_called_once()

    @patch("starbash.windows.platform.system")
    @patch("starbash.windows.is_under_powershell")
    def test_init_warns_on_windows_without_powershell(
        self,
        mock_is_under_powershell,
        mock_platform_system,
        setup_test_environment,
        mock_analytics,
        caplog,
    ):
        """Test that initialization warns when running on Windows without PowerShell."""
        mock_platform_system.return_value = "Windows"
        mock_is_under_powershell.return_value = False

        with Starbash() as app:
            # Check that warning was logged
            assert any(
                "old school" in record.message and "Powershell" in record.message
                for record in caplog.records
            )

    @patch("starbash.windows.platform.system")
    @patch("starbash.windows.is_under_powershell")
    def test_init_no_warning_on_windows_with_powershell(
        self,
        mock_is_under_powershell,
        mock_platform_system,
        setup_test_environment,
        mock_analytics,
        caplog,
    ):
        """Test that initialization does not warn when running on Windows with PowerShell."""
        mock_platform_system.return_value = "Windows"
        mock_is_under_powershell.return_value = True

        with Starbash() as app:
            # Check that warning was NOT logged
            assert not any(
                "old school" in record.message and "Powershell" in record.message
                for record in caplog.records
            )

    @patch("starbash.windows.platform.system")
    def test_init_no_warning_on_linux(
        self, mock_platform_system, setup_test_environment, mock_analytics, caplog
    ):
        """Test that initialization does not warn on non-Windows systems."""
        mock_platform_system.return_value = "Linux"

        with Starbash() as app:
            # Check that warning was NOT logged
            assert not any(
                "old school" in record.message and "Powershell" in record.message
                for record in caplog.records
            )

    def test_init_with_user_email(self, setup_test_environment, mock_analytics):
        """Test initialization includes user email when configured."""
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text(
            '[repo]\n\n[analytics]\nenabled = true\ninclude_user = true\n[user]\nemail = "test@example.com"\n'
        )

        with Starbash() as app:
            mock_analytics["setup"].assert_called_once_with(
                allowed=True, user_email="test@example.com"
            )

    def test_init_with_cmd_parameter(self, setup_test_environment, mock_analytics):
        """Test initialization with custom command parameter."""
        with Starbash(cmd="test-command") as app:
            # Analytics transaction should use the command name
            mock_analytics["transaction"].assert_called_once_with(
                name="App session", op="test-command"
            )


class TestStarbashLifecycle:
    """Tests for Starbash lifecycle methods."""

    def test_close_shuts_down_analytics(self, setup_test_environment, mock_analytics):
        """Test that close() calls analytics_shutdown."""
        app = Starbash()
        app.close()
        mock_analytics["shutdown"].assert_called_once()

    def test_close_closes_database(self, setup_test_environment, mock_analytics):
        """Test that close() closes the database."""
        app = Starbash()
        with patch.object(app.db, "close") as mock_db_close:
            app.close()
            mock_db_close.assert_called_once()

    def test_context_manager_enter(self, setup_test_environment, mock_analytics):
        """Test that __enter__ returns the app instance."""
        app = Starbash()
        result = app.__enter__()
        assert result is app
        app.close()

    def test_context_manager_exit_no_exception(self, setup_test_environment, mock_analytics):
        """Test that __exit__ handles no exception case."""
        app = Starbash()
        result = app.__exit__(None, None, None)
        # Should not suppress exception (returns False)
        assert result is False or result is None
        mock_analytics["exception"].assert_not_called()

    def test_context_manager_exit_with_exception(self, setup_test_environment, mock_analytics):
        """Test that __exit__ calls analytics_exception on error."""
        mock_analytics["exception"].return_value = True
        app = Starbash()
        exc = ValueError("test error")
        result = app.__exit__(type(exc), exc, None)
        mock_analytics["exception"].assert_called_once_with(exc)

    def test_context_manager_exit_with_typer_exit(self, setup_test_environment, mock_analytics):
        """Test that __exit__ doesn't suppress typer.Exit."""
        app = Starbash()
        exc = typer.Exit(code=0)
        app.__exit__(type(exc), exc, None)
        # Should not call analytics_exception for typer.Exit
        mock_analytics["exception"].assert_not_called()

    def test_with_statement(self, setup_test_environment, mock_analytics):
        """Test using Starbash as a context manager."""
        with Starbash() as app:
            assert app is not None
            assert app.db is not None
        # Should have cleaned up
        mock_analytics["shutdown"].assert_called()


class TestAddSession:
    """Tests for the _add_session method."""

    def test_add_session_with_valid_header(self, setup_test_environment, mock_analytics):
        """Test adding a session with valid FITS header."""
        with Starbash() as app:
            header = {
                Database.ID_KEY: 1,
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.IMAGETYP_KEY: "Light",
                Database.FILTER_KEY: "Ha",
                Database.EXPTIME_KEY: 60.0,
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test Telescope",
            }
            app._add_session(header)

            # Verify session was added to database
            sessions = app.db.search_session()
            assert sessions
            assert len(sessions) == 1
            # Target names are normalized to lowercase when stored
            assert sessions[0][get_column_name(Database.OBJECT_KEY)] == "m31"

    def test_add_session_missing_date(self, setup_test_environment, mock_analytics, caplog):
        """Test adding a session with missing DATE-OBS logs warning."""
        with Starbash() as app:
            header = {
                Database.ID_KEY: 1,
                Database.IMAGETYP_KEY: "Light",
                Database.FILTER_KEY: "Ha",
            }
            app._add_session(header)

            # Should log warning and not add session
            assert "missing either DATE-OBS or IMAGETYP" in caplog.text
            sessions = app.db.search_session()
            assert sessions == []

    def test_add_session_missing_imagetyp(self, setup_test_environment, mock_analytics, caplog):
        """Test adding a session with missing IMAGETYP logs warning."""
        with Starbash() as app:
            header = {
                Database.ID_KEY: 1,
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.FILTER_KEY: "Ha",
            }
            app._add_session(header)

            # Should log warning
            assert "missing either DATE-OBS or IMAGETYP" in caplog.text

    def test_add_session_with_defaults(self, setup_test_environment, mock_analytics):
        """Test that missing optional fields get default values."""
        with Starbash() as app:
            header = {
                Database.ID_KEY: 1,
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.IMAGETYP_KEY: "Light",
                # Missing FILTER, OBJECT, TELESCOP, EXPTIME - all optional here
            }
            app._add_session(header)

            sessions = app.db.search_session()
            assert sessions
            assert len(sessions) == 1
            assert sessions[0][get_column_name(Database.EXPTIME_TOTAL_KEY)] == 0
            # A frame with no TELESCOP header is stored with an unknown (empty)
            # telescope rather than failing the NOT NULL constraint.
            assert sessions[0][get_column_name(Database.TELESCOP_KEY)] == ""


class TestSearchSession:
    """Tests for the search_session method."""

    def test_search_session_empty_selection(self, setup_test_environment, mock_analytics):
        """Test search_session with empty selection returns all sessions."""
        with Starbash() as app:
            # Add some sessions
            for i in range(3):
                session = {
                    get_column_name(Database.START_KEY): f"2023-10-1{i}T20:00:00",
                    get_column_name(Database.END_KEY): f"2023-10-1{i}T22:00:00",
                    get_column_name(Database.FILTER_KEY): "Ha",
                    get_column_name(Database.IMAGETYP_KEY): "Light",
                    get_column_name(Database.OBJECT_KEY): f"Target{i}",
                    get_column_name(Database.TELESCOP_KEY): "Test",
                    get_column_name(Database.NUM_IMAGES_KEY): 10,
                    get_column_name(Database.EXPTIME_TOTAL_KEY): 600.0,
                    get_column_name(Database.EXPTIME_KEY): 120.0,
                    get_column_name(Database.IMAGE_DOC_KEY): i,
                }
                app.db.upsert_session(session)

            results = app.search_session()
            assert results is not None
            assert len(results) == 3

    def test_search_session_with_filters(self, setup_test_environment, mock_analytics):
        """Test search_session with selection filters."""
        with Starbash() as app:
            # Add sessions
            session1 = {
                get_column_name(Database.START_KEY): "2023-10-15T20:00:00",
                get_column_name(Database.END_KEY): "2023-10-15T22:00:00",
                get_column_name(Database.FILTER_KEY): "Ha",
                get_column_name(Database.IMAGETYP_KEY): "Light",
                get_column_name(Database.OBJECT_KEY): "M31",
                get_column_name(Database.TELESCOP_KEY): "Test",
                get_column_name(Database.NUM_IMAGES_KEY): 10,
                get_column_name(Database.EXPTIME_TOTAL_KEY): 600.0,
                get_column_name(Database.EXPTIME_KEY): 120.0,
                get_column_name(Database.IMAGE_DOC_KEY): 1,
            }
            session2 = {
                get_column_name(Database.START_KEY): "2023-10-16T20:00:00",
                get_column_name(Database.END_KEY): "2023-10-16T22:00:00",
                get_column_name(Database.FILTER_KEY): "OIII",
                get_column_name(Database.IMAGETYP_KEY): "Light",
                get_column_name(Database.OBJECT_KEY): "M42",
                get_column_name(Database.TELESCOP_KEY): "Test",
                get_column_name(Database.NUM_IMAGES_KEY): 5,
                get_column_name(Database.EXPTIME_TOTAL_KEY): 300.0,
                get_column_name(Database.EXPTIME_KEY): 120.0,
                get_column_name(Database.IMAGE_DOC_KEY): 2,
            }
            app.db.upsert_session(session1)
            app.db.upsert_session(session2)

            # Filter by target
            app.selection.add_target("M31")
            results = app.search_session()
            assert results is not None
            assert len(results) == 1
            # Target names are normalized to lowercase when stored
            assert results[0][get_column_name(Database.OBJECT_KEY)] == "m31"


class TestGetSessionImages:
    """Tests for the get_session_images method."""

    def test_get_session_images_valid_session(self, setup_test_environment, mock_analytics):
        """Test retrieving images for a valid session."""
        with Starbash() as app:
            # Register a real repo so _add_image_abspath can resolve the path
            repo_dir = setup_test_environment["tmp_path"] / "image_repo"
            repo_dir.mkdir()
            (repo_dir / "starbash.toml").write_text("[repo]\nkind = 'images'\n")
            repo = app.repo_manager.add_repo(f"file://{repo_dir}")

            # Add an image
            image = {
                "path": "image.fit",  # Relative path
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test",
            }
            app.db.upsert_image(image, repo.url)

            # Add a session
            session = {
                get_column_name(Database.START_KEY): "2023-10-15T20:00:00",
                get_column_name(Database.END_KEY): "2023-10-15T22:00:00",
                get_column_name(Database.FILTER_KEY): "Ha",
                get_column_name(Database.IMAGETYP_KEY): "Light",
                get_column_name(Database.OBJECT_KEY): "M31",
                get_column_name(Database.TELESCOP_KEY): "Test",
                get_column_name(Database.NUM_IMAGES_KEY): 1,
                get_column_name(Database.EXPTIME_TOTAL_KEY): 60.0,
                get_column_name(Database.EXPTIME_KEY): 120.0,
                get_column_name(Database.IMAGE_DOC_KEY): 1,
            }
            app.db.upsert_session(session)

            sessions = app.db.search_session()
            assert len(sessions) > 0

            # Get images for this session
            images = app.get_session_images(sessions[0])
            assert len(images) == 1
            assert images[0]["abspath"] == str(repo_dir / "image.fit")

    def test_get_session_images_no_images(self, setup_test_environment, mock_analytics):
        """Test session with no matching images returns empty list."""
        with Starbash() as app:
            # Add a session without any images
            session = {
                get_column_name(Database.START_KEY): "2023-10-15T20:00:00",
                get_column_name(Database.END_KEY): "2023-10-15T22:00:00",
                get_column_name(Database.FILTER_KEY): "Ha",
                get_column_name(Database.IMAGETYP_KEY): "Light",
                get_column_name(Database.OBJECT_KEY): "M31",
                get_column_name(Database.TELESCOP_KEY): "Test",
                get_column_name(Database.NUM_IMAGES_KEY): 0,
                get_column_name(Database.EXPTIME_TOTAL_KEY): 0.0,
                get_column_name(Database.EXPTIME_KEY): 120.0,
                get_column_name(Database.IMAGE_DOC_KEY): 1,
            }
            app.db.upsert_session(session)

            sessions = app.db.search_session()
            assert len(sessions) > 0

            images = app.get_session_images(sessions[0])
            assert images == []


class TestRemoveRepoRef:
    """Tests for the remove_repo_ref method."""

    def test_remove_repo_ref_valid_url(self, setup_test_environment, mock_analytics):
        """Test removing a valid repository reference."""
        with Starbash() as app:
            # Add a repo reference
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'test'\n")

            app.user_repo.add_repo_ref(app.repo_manager, test_repo)

            # Remove it
            app.remove_repo_ref(f"file://{test_repo}")

            # Verify it's gone
            repo_refs = app.user_repo.config.get("repo-ref", [])
            for ref in repo_refs:
                assert ref.get("dir") != str(test_repo)

    def test_remove_repo_ref_not_found(self, setup_test_environment, mock_analytics):
        """Test removing a non-existent repo raises UserHandledError."""
        from starbash.exception import UserHandledError

        with Starbash() as app:
            with pytest.raises(UserHandledError, match="not found in user configuration"):
                app.remove_repo_ref("file:///nonexistent/path")

    def test_remove_repo_ref_no_refs(self, setup_test_environment, mock_analytics):
        """Test removing when no repo-ref list exists raises UserHandledError."""
        from starbash.exception import UserHandledError

        with Starbash() as app:
            # Clear repo-refs if they exist
            if "repo-ref" in app.user_repo.config:
                del app.user_repo.config["repo-ref"]
                app.user_repo.write_config()

            with pytest.raises(UserHandledError, match="not found in user configuration"):
                app.remove_repo_ref("file:///some/path")


class TestReindexRepo:
    """Tests for the reindex_repo method."""

    def test_reindex_repo_skips_non_file_schemes(self, setup_test_environment, mock_analytics):
        """Test that reindex_repo skips repos that aren't file:// scheme."""
        with Starbash() as app:
            # The pkg://defaults repo should be skipped
            pkg_repo = app.repo_manager.repos[0]
            assert pkg_repo.url == "pkg://defaults"

            # This should not raise an error or try to scan files
            app.reindex_repo(pkg_repo)

    def test_reindex_repo_skips_recipe_repos(self, setup_test_environment, mock_analytics):
        """Test that reindex_repo skips recipe repos."""
        with Starbash() as app:
            # Create a recipe repo
            recipe_repo = setup_test_environment["tmp_path"] / "recipe_repo"
            recipe_repo.mkdir()
            (recipe_repo / "starbash.toml").write_text("[repo]\nkind = 'recipe'\n")

            repo = app.repo_manager.add_repo(f"file://{recipe_repo}")

            # Should skip it
            app.reindex_repo(repo)

    def test_reindex_repo_with_fits_files(self, setup_test_environment, mock_analytics):
        """Test reindexing a repo with FITS files."""
        with Starbash() as app:
            # Create a test repo with a FITS file
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            # Create a simple FITS file
            fits_file = test_repo / "test.fit"
            from astropy.io import fits as astropy_fits

            hdu = astropy_fits.PrimaryHDU()
            hdu.header["DATE-OBS"] = "2023-10-15T20:30:00"
            hdu.header["IMAGETYP"] = "Light"
            hdu.header["FILTER"] = "Ha"
            hdu.header["OBJECT"] = "M31"
            astropy_fits.HDUList([hdu]).writeto(fits_file, overwrite=True)

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            # Reindex
            app.reindex_repo(repo)

            # Verify image was added to database
            image = app.db.get_image(f"file://{test_repo}", "test.fit")
            assert image is not None
            assert image["FILTER"] == "Ha"

    def test_reindex_repo_handles_frames_without_telescop(
        self, setup_test_environment, mock_analytics
    ):
        """A frame with no TELESCOP header is indexed, not fatal (regression).

        The sessions table declares ``telescop`` NOT NULL, so a header lacking
        TELESCOP used to abort the whole repo scan with ``sqlite3.IntegrityError``.
        """
        with Starbash() as app:
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            fits_file = test_repo / "notelescope.fit"
            from astropy.io import fits as astropy_fits

            hdu = astropy_fits.PrimaryHDU()
            hdu.header["DATE-OBS"] = "2023-10-15T20:30:00"
            hdu.header["IMAGETYP"] = "Light"
            hdu.header["FILTER"] = "Ha"
            astropy_fits.HDUList([hdu]).writeto(fits_file, overwrite=True)

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            app.reindex_repo(repo)  # used to raise sqlite3.IntegrityError

            assert app.db.get_image(f"file://{test_repo}", "notelescope.fit") is not None
            sessions = app.db.search_session()
            assert len(sessions) == 1
            # An unknown telescope is recorded as "" rather than aborting the scan.
            assert sessions[0][get_column_name(Database.TELESCOP_KEY)] == ""

    def test_reindex_repo_skips_sbignore_paths(
        self, setup_test_environment, mock_analytics, caplog
    ):
        """Test that FITS files whose paths contain .sbignore are skipped."""
        with Starbash() as app:
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            from astropy.io import fits as astropy_fits

            def create_fits_file(path: Path) -> None:
                hdu = astropy_fits.PrimaryHDU()
                hdu.header["DATE-OBS"] = "2023-10-15T20:30:00"
                hdu.header["IMAGETYP"] = "Light"
                astropy_fits.HDUList([hdu]).writeto(path)

            included_file = test_repo / "included.fit"
            ignored_file = test_repo / ".sbignore" / "ignored.fit"
            ignored_file.parent.mkdir()
            create_fits_file(included_file)
            create_fits_file(ignored_file)

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            with caplog.at_level("WARNING"):
                app.reindex_repo(repo)

            assert app.db.get_image(f"file://{test_repo}", "included.fit") is not None
            assert app.db.get_image(f"file://{test_repo}", ".sbignore/ignored.fit") is None
            assert f'Skipping "{ignored_file}"' in caplog.text

    def test_reindex_repo_with_force(self, setup_test_environment, mock_analytics, monkeypatch):
        """Test reindexing with force_regen re-reads existing files."""
        with Starbash() as app:
            # Create a test repo with a FITS file
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            fits_file = test_repo / "test.fit"
            from astropy.io import fits as astropy_fits

            hdu = astropy_fits.PrimaryHDU()
            hdu.header["DATE-OBS"] = "2023-10-15T20:30:00"
            hdu.header["IMAGETYP"] = "Light"
            hdu.header["FILTER"] = "Ha"
            astropy_fits.HDUList([hdu]).writeto(fits_file, overwrite=True)

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            # Index once
            app.reindex_repo(repo)

            # Modify the file
            hdu.header["FILTER"] = "OIII"
            astropy_fits.HDUList([hdu]).writeto(fits_file, overwrite=True)

            # Reindex with force_regen enabled: existing files are re-read
            import starbash

            monkeypatch.setattr(starbash, "force_regen", True)
            app.reindex_repo(repo)

            # Verify the change was picked up
            image = app.db.get_image(f"file://{test_repo}", "test.fit")
            assert image is not None
            assert image["FILTER"] == "OIII"

    def test_reindex_repo_skips_bad_fits(self, setup_test_environment, mock_analytics, caplog):
        """A corrupt FITS file is logged and skipped instead of aborting the scan."""
        with Starbash() as app:
            # Create a test repo with a bad FITS file
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            # Create a corrupt FITS file
            fits_file = test_repo / "bad.fit"
            fits_file.write_text("This is not a FITS file")

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            # The corrupt file is skipped (and logged) rather than aborting the scan
            with caplog.at_level("ERROR"):
                app.reindex_repo(repo)
            assert "bad.fit" in caplog.text


class TestReindexRepos:
    """Tests for the reindex_repos method."""

    def test_reindex_repos_calls_reindex_repo(self, setup_test_environment, mock_analytics):
        """Test that reindex_repos calls reindex_repo for each repo."""
        with Starbash() as app:
            with patch.object(app, "reindex_repo") as mock_reindex:
                app.reindex_repos()

                # Should call reindex_repo for each repo
                assert mock_reindex.call_count == len(app.repo_manager.repos)
