"""Unit tests for the Starbash app module."""

import json
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
import pytest
import typer

from starbash.app import Starbash, create_user, setup_logging, copy_images_to_dir
from starbash.database import Database
from starbash.selection import Selection
from starbash import paths


@pytest.fixture
def setup_test_environment(tmp_path):
    """Setup a test environment with isolated config and data directories."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Set the override directories for this test
    paths.set_test_directories(config_dir, data_dir)

    yield {"config_dir": config_dir, "data_dir": data_dir, "tmp_path": tmp_path}

    # Clean up: reset to None after test
    paths.set_test_directories(None, None)


@pytest.fixture
def mock_analytics():
    """Mock analytics functions to avoid Sentry calls."""
    with patch("starbash.app.analytics_setup") as mock_setup, patch(
        "starbash.app.analytics_shutdown"
    ) as mock_shutdown, patch(
        "starbash.app.analytics_start_transaction"
    ) as mock_transaction, patch(
        "starbash.app.analytics_exception"
    ) as mock_exception:

        # Make transaction return a NopAnalytics-like mock
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_transaction.return_value = mock_context

        yield {
            "setup": mock_setup,
            "shutdown": mock_shutdown,
            "transaction": mock_transaction,
            "exception": mock_exception,
            "context": mock_context,
        }


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
            {"path": str(file1)},
            {"path": str(file2)},
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

    @patch("pathlib.Path.symlink_to")
    def test_copy_images_to_dir_fallback_to_copy(self, mock_symlink, tmp_path, capsys):
        """Test that copy_images_to_dir falls back to copy when symlink fails."""
        # Create source files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file1.write_text("test data 1")

        # Create output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock symlink to raise OSError
        mock_symlink.side_effect = OSError("Symlink not supported")

        # Create image metadata
        images = [{"path": str(file1)}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify file was copied instead
        dest1 = output_dir / "image1.fit"
        assert dest1.exists()
        assert not dest1.is_symlink()
        assert dest1.read_text() == "test data 1"

        # Check output messages
        captured = capsys.readouterr()
        assert "Exporting 1 images" in captured.out
        assert "Export complete!" in captured.out
        assert "Copied: 1 files" in captured.out

    def test_copy_images_to_dir_missing_source(self, tmp_path, capsys):
        """Test that copy_images_to_dir handles missing source files."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata with non-existent file
        images = [{"path": "/nonexistent/file.fit"}]

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
        images = [{"path": str(file1)}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Verify file was not overwritten
        assert existing.read_text() == "existing data"

        # Check output messages
        captured = capsys.readouterr()
        assert "Skipping existing file" in captured.out
        assert "Errors: 1 files" in captured.out

    @patch("shutil.copy2")
    @patch("pathlib.Path.symlink_to")
    def test_copy_images_to_dir_copy_failure(
        self, mock_symlink, mock_copy, tmp_path, capsys
    ):
        """Test that copy_images_to_dir handles copy failures."""
        # Create source file
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        file1 = source_dir / "image1.fit"
        file1.write_text("test data")

        # Create output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock symlink to fail, then copy to fail
        mock_symlink.side_effect = OSError("Symlink not supported")
        mock_copy.side_effect = PermissionError("Permission denied")

        # Create image metadata
        images = [{"path": str(file1)}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Check output messages
        captured = capsys.readouterr()
        assert "Error copying" in captured.out
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
            {"path": str(file1)},
            {"path": str(file2)},
            {"path": "/nonexistent/file.fit"},
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

    def test_copy_images_to_dir_missing_path_key(self, tmp_path, capsys):
        """Test copy_images_to_dir handles images without path key."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create image metadata without path key
        images = [{"metadata": "some data"}]

        # Call the function
        copy_images_to_dir(images, output_dir)

        # Check that it handled gracefully
        captured = capsys.readouterr()
        assert "Exporting 1 images" in captured.out
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

    def test_init_with_analytics_disabled(self, setup_test_environment, mock_analytics):
        """Test initialization when analytics is disabled in user config."""
        # Create user config with analytics disabled
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text("[analytics]\nenabled = false\n")

        with Starbash() as app:
            # Analytics setup should not be called
            mock_analytics["setup"].assert_not_called()

    def test_init_with_analytics_enabled(self, setup_test_environment, mock_analytics):
        """Test initialization when analytics is enabled in user config."""
        # Create user config with analytics enabled
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text("[analytics]\nenabled = true\n")

        with Starbash() as app:
            # Analytics setup should be called
            mock_analytics["setup"].assert_called_once()

    def test_init_with_user_email(self, setup_test_environment, mock_analytics):
        """Test initialization includes user email when configured."""
        config_dir = setup_test_environment["config_dir"]
        config_file = config_dir / "starbash.toml"
        config_file.write_text(
            "[analytics]\nenabled = true\ninclude_user = true\n"
            '[user]\nemail = "test@example.com"\n'
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

    def test_context_manager_exit_no_exception(
        self, setup_test_environment, mock_analytics
    ):
        """Test that __exit__ handles no exception case."""
        app = Starbash()
        result = app.__exit__(None, None, None)
        # Should not suppress exception (returns False)
        assert result is False or result is None
        mock_analytics["exception"].assert_not_called()

    def test_context_manager_exit_with_exception(
        self, setup_test_environment, mock_analytics
    ):
        """Test that __exit__ calls analytics_exception on error."""
        mock_analytics["exception"].return_value = True
        app = Starbash()
        exc = ValueError("test error")
        result = app.__exit__(type(exc), exc, None)
        mock_analytics["exception"].assert_called_once_with(exc)

    def test_context_manager_exit_with_typer_exit(
        self, setup_test_environment, mock_analytics
    ):
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

    def test_add_session_with_valid_header(
        self, setup_test_environment, mock_analytics
    ):
        """Test adding a session with valid FITS header."""
        with Starbash() as app:
            header = {
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.IMAGETYP_KEY: "Light",
                Database.FILTER_KEY: "Ha",
                Database.EXPTIME_KEY: 60.0,
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test Telescope",
            }
            app._add_session("/path/to/image.fit", 1, header)

            # Verify session was added to database
            sessions = app.db.search_session()
            assert sessions
            assert len(sessions) == 1
            assert sessions[0][Database.OBJECT_KEY] == "M31"

    def test_add_session_missing_date(
        self, setup_test_environment, mock_analytics, caplog
    ):
        """Test adding a session with missing DATE-OBS logs warning."""
        with Starbash() as app:
            header = {
                Database.IMAGETYP_KEY: "Light",
                Database.FILTER_KEY: "Ha",
            }
            app._add_session("/path/to/image.fit", 1, header)

            # Should log warning and not add session
            assert "missing either DATE-OBS or IMAGETYP" in caplog.text
            sessions = app.db.search_session()
            assert sessions
            assert len(sessions) == 0

    def test_add_session_missing_imagetyp(
        self, setup_test_environment, mock_analytics, caplog
    ):
        """Test adding a session with missing IMAGETYP logs warning."""
        with Starbash() as app:
            header = {
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.FILTER_KEY: "Ha",
            }
            app._add_session("/path/to/image.fit", 1, header)

            # Should log warning
            assert "missing either DATE-OBS or IMAGETYP" in caplog.text

    def test_add_session_with_defaults(self, setup_test_environment, mock_analytics):
        """Test that missing optional fields get default values."""
        with Starbash() as app:
            header = {
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.IMAGETYP_KEY: "Light",
                # Missing FILTER, OBJECT, TELESCOP, EXPTIME
            }
            app._add_session("/path/to/image.fit", 1, header)

            sessions = app.db.search_session()
            assert sessions
            assert len(sessions) == 1
            assert sessions[0][Database.FILTER_KEY] == "unspecified"
            assert sessions[0][Database.OBJECT_KEY] == "unspecified"
            assert sessions[0][Database.TELESCOP_KEY] == "unspecified"
            assert sessions[0][Database.EXPTIME_TOTAL_KEY] == 0


class TestSearchSession:
    """Tests for the search_session method."""

    def test_search_session_empty_selection(
        self, setup_test_environment, mock_analytics
    ):
        """Test search_session with empty selection returns all sessions."""
        with Starbash() as app:
            # Add some sessions
            for i in range(3):
                session = {
                    Database.START_KEY: f"2023-10-1{i}T20:00:00",
                    Database.END_KEY: f"2023-10-1{i}T22:00:00",
                    Database.FILTER_KEY: "Ha",
                    Database.IMAGETYP_KEY: "Light",
                    Database.OBJECT_KEY: f"Target{i}",
                    Database.TELESCOP_KEY: "Test",
                    Database.NUM_IMAGES_KEY: 10,
                    Database.EXPTIME_TOTAL_KEY: 600.0,
                    Database.IMAGE_DOC_KEY: i,
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
                Database.START_KEY: "2023-10-15T20:00:00",
                Database.END_KEY: "2023-10-15T22:00:00",
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test",
                Database.NUM_IMAGES_KEY: 10,
                Database.EXPTIME_TOTAL_KEY: 600.0,
                Database.IMAGE_DOC_KEY: 1,
            }
            session2 = {
                Database.START_KEY: "2023-10-16T20:00:00",
                Database.END_KEY: "2023-10-16T22:00:00",
                Database.FILTER_KEY: "OIII",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M42",
                Database.TELESCOP_KEY: "Test",
                Database.NUM_IMAGES_KEY: 5,
                Database.EXPTIME_TOTAL_KEY: 300.0,
                Database.IMAGE_DOC_KEY: 2,
            }
            app.db.upsert_session(session1)
            app.db.upsert_session(session2)

            # Filter by target
            app.selection.add_target("M31")
            results = app.search_session()
            assert results is not None
            assert len(results) == 1
            assert results[0][Database.OBJECT_KEY] == "M31"


class TestGetSessionImages:
    """Tests for the get_session_images method."""

    def test_get_session_images_valid_session(
        self, setup_test_environment, mock_analytics
    ):
        """Test retrieving images for a valid session."""
        with Starbash() as app:
            # Add an image
            image = {
                "path": "/path/to/image.fit",
                Database.DATE_OBS_KEY: "2023-10-15T20:30:00",
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test",
            }
            app.db.upsert_image(image)

            # Add a session
            session = {
                Database.START_KEY: "2023-10-15T20:00:00",
                Database.END_KEY: "2023-10-15T22:00:00",
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test",
                Database.NUM_IMAGES_KEY: 1,
                Database.EXPTIME_TOTAL_KEY: 60.0,
                Database.IMAGE_DOC_KEY: 1,
            }
            app.db.upsert_session(session)

            # Get the session ID
            sessions = app.db.search_session()
            assert sessions is not None
            assert len(sessions) > 0
            session_id = sessions[0]["id"]

            # Get images for this session
            images = app.get_session_images(session_id)
            assert len(images) == 1
            assert images[0]["path"] == "/path/to/image.fit"

    def test_get_session_images_invalid_session(
        self, setup_test_environment, mock_analytics
    ):
        """Test that invalid session ID raises ValueError."""
        with Starbash() as app:
            with pytest.raises(ValueError, match="Session with id 999 not found"):
                app.get_session_images(999)

    def test_get_session_images_no_images(self, setup_test_environment, mock_analytics):
        """Test session with no matching images returns empty list."""
        with Starbash() as app:
            # Add a session without any images
            session = {
                Database.START_KEY: "2023-10-15T20:00:00",
                Database.END_KEY: "2023-10-15T22:00:00",
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "Light",
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "Test",
                Database.NUM_IMAGES_KEY: 0,
                Database.EXPTIME_TOTAL_KEY: 0.0,
                Database.IMAGE_DOC_KEY: 1,
            }
            app.db.upsert_session(session)

            sessions = app.db.search_session()
            assert sessions is not None
            assert len(sessions) > 0
            session_id = sessions[0]["id"]

            images = app.get_session_images(session_id)
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

            app.user_repo.add_repo_ref(Path(test_repo))

            # Remove it
            app.remove_repo_ref(f"file://{test_repo}")

            # Verify it's gone
            repo_refs = app.user_repo.config.get("repo-ref", [])
            for ref in repo_refs:
                assert ref.get("dir") != str(test_repo)

    def test_remove_repo_ref_not_found(self, setup_test_environment, mock_analytics):
        """Test removing a non-existent repo raises ValueError."""
        with Starbash() as app:
            with pytest.raises(ValueError, match="not found in user configuration"):
                app.remove_repo_ref("file:///nonexistent/path")

    def test_remove_repo_ref_no_refs(self, setup_test_environment, mock_analytics):
        """Test removing when no repo-ref list exists raises ValueError."""
        with Starbash() as app:
            # Clear repo-refs if they exist
            if "repo-ref" in app.user_repo.config:
                del app.user_repo.config["repo-ref"]
                app.user_repo.write_config()

            with pytest.raises(ValueError, match="No repository references found"):
                app.remove_repo_ref("file:///some/path")


class TestReindexRepo:
    """Tests for the reindex_repo method."""

    def test_reindex_repo_skips_non_file_schemes(
        self, setup_test_environment, mock_analytics
    ):
        """Test that reindex_repo skips repos that aren't file:// scheme."""
        with Starbash() as app:
            # The pkg://defaults repo should be skipped
            pkg_repo = app.repo_manager.repos[0]
            assert pkg_repo.url == "pkg://defaults"

            # This should not raise an error or try to scan files
            app.reindex_repo(pkg_repo)

    def test_reindex_repo_skips_recipe_repos(
        self, setup_test_environment, mock_analytics
    ):
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
            image = app.db.get_image(str(fits_file))
            assert image is not None
            assert image["FILTER"] == "Ha"

    def test_reindex_repo_with_force(self, setup_test_environment, mock_analytics):
        """Test reindexing with force=True re-reads existing files."""
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
            app.reindex_repo(repo, force=False)

            # Modify the file
            hdu.header["FILTER"] = "OIII"
            astropy_fits.HDUList([hdu]).writeto(fits_file, overwrite=True)

            # Reindex with force
            app.reindex_repo(repo, force=True)

            # Verify the change was picked up
            image = app.db.get_image(str(fits_file))
            assert image is not None
            assert image["FILTER"] == "OIII"

    def test_reindex_repo_handles_bad_fits(
        self, setup_test_environment, mock_analytics, caplog
    ):
        """Test that reindex_repo handles corrupt FITS files gracefully."""
        with Starbash() as app:
            # Create a test repo with a bad FITS file
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

            # Create a corrupt FITS file
            fits_file = test_repo / "bad.fit"
            fits_file.write_text("This is not a FITS file")

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            # Should not raise, but should log warning
            app.reindex_repo(repo)

            assert "Failed to read FITS header" in caplog.text


class TestReindexRepos:
    """Tests for the reindex_repos method."""

    def test_reindex_repos_calls_reindex_repo(
        self, setup_test_environment, mock_analytics
    ):
        """Test that reindex_repos calls reindex_repo for each repo."""
        with Starbash() as app:
            with patch.object(app, "reindex_repo") as mock_reindex:
                app.reindex_repos()

                # Should call reindex_repo for each repo
                assert mock_reindex.call_count == len(app.repo_manager.repos)

    def test_reindex_repos_with_force(self, setup_test_environment, mock_analytics):
        """Test that reindex_repos passes force parameter."""
        with Starbash() as app:
            with patch.object(app, "reindex_repo") as mock_reindex:
                app.reindex_repos(force=True)

                # All calls should have force=True
                for call_args in mock_reindex.call_args_list:
                    assert call_args[1]["force"] is True


class TestProcessing:
    """Tests for processing-related methods."""

    def test_start_session_initializes_context(
        self, setup_test_environment, mock_analytics
    ):
        """Test that start_session initializes the context dict."""
        with Starbash() as app:
            app.start_session()

            assert hasattr(app, "context")
            assert isinstance(app.context, dict)
            assert "process_dir" in app.context
            assert "masters" in app.context

    def test_run_stage_missing_tool(self, setup_test_environment, mock_analytics):
        """Test that run_stage raises error for missing tool."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "when": "test",
            }

            with pytest.raises(ValueError, match="missing a 'tool' definition"):
                app.run_stage(stage)

    def test_run_stage_unknown_tool(self, setup_test_environment, mock_analytics):
        """Test that run_stage raises error for unknown tool."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "tool": "nonexistent-tool",
                "when": "test",
            }

            with pytest.raises(ValueError, match="not found"):
                app.run_stage(stage)

    def test_run_stage_disabled_skips(
        self, setup_test_environment, mock_analytics, caplog
    ):
        """Test that disabled stages are skipped."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "tool": "python",
                "disabled": True,
                "script": "print('hello')",
            }

            app.run_stage(stage)

            assert "Skipping disabled stage" in caplog.text

    def test_run_stage_missing_script(self, setup_test_environment, mock_analytics):
        """Test that run_stage raises error when no script provided."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "tool": "python",
                "when": "test",
            }

            with pytest.raises(ValueError, match="missing a 'script' or 'script-file'"):
                app.run_stage(stage)

    def test_run_stage_with_script(self, setup_test_environment, mock_analytics):
        """Test running a stage with inline script."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "context['test'] = 'value'",
            }

            app.run_stage(stage)

            # Check that the script ran and modified context
            assert app.context.get("test") == "value"

    def test_run_stage_with_script_file(self, setup_test_environment, mock_analytics):
        """Test running a stage with script-file."""
        with Starbash() as app:
            app.start_session()

            # Create a test repo with a script file
            test_repo = setup_test_environment["tmp_path"] / "test_repo"
            test_repo.mkdir()
            (test_repo / "starbash.toml").write_text("[repo]\nkind = 'recipe'\n")
            script_file = test_repo / "test_script.py"
            script_file.write_text("context['from_file'] = 'loaded'")

            repo = app.repo_manager.add_repo(f"file://{test_repo}")

            stage = {
                "description": "Test stage",
                "tool": "python",
                "script-file": "test_script.py",
            }
            # Monkeypatch the source attribute
            stage["source"] = repo  # type: ignore

            app.run_stage(stage)

            assert app.context.get("from_file") == "loaded"

    def test_run_stage_updates_context(self, setup_test_environment, mock_analytics):
        """Test that run_stage updates context from stage.context."""
        with Starbash() as app:
            app.start_session()
            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "pass",
                "context": {"stage_var": "stage_value"},
            }

            app.run_stage(stage)

            assert app.context["stage_var"] == "stage_value"

    def test_run_stage_with_input_files(self, setup_test_environment, mock_analytics):
        """Test run_stage with input file configuration."""
        with Starbash() as app:
            app.start_session()

            # Create some test files
            tmp_path = setup_test_environment["tmp_path"]
            (tmp_path / "input1.txt").write_text("test")
            (tmp_path / "input2.txt").write_text("test")

            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "pass",
                "input": {
                    "path": str(tmp_path / "*.txt"),
                    "required": True,
                },
            }

            app.run_stage(stage)

            # Check that input files were found
            assert "input_files" in app.context
            assert len(app.context["input_files"]) == 2

    def test_run_stage_input_required_missing(
        self, setup_test_environment, mock_analytics
    ):
        """Test that run_stage raises error when required inputs are missing."""
        with Starbash() as app:
            app.start_session()

            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "pass",
                "input": {
                    "path": "/nonexistent/*.fit",
                    "required": True,
                },
            }

            with pytest.raises(RuntimeError, match="No input files found"):
                app.run_stage(stage)

    def test_run_stage_input_optional_missing(
        self, setup_test_environment, mock_analytics
    ):
        """Test that run_stage succeeds when optional inputs are missing."""
        with Starbash() as app:
            app.start_session()

            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "pass",
                "input": {
                    "path": "/nonexistent/*.fit",
                    "required": False,
                },
            }

            # Should not raise
            app.run_stage(stage)
            assert app.context["input_files"] == []

    def test_run_stage_clears_previous_input_files(
        self, setup_test_environment, mock_analytics
    ):
        """Test that run_stage clears input_files from previous stages."""
        with Starbash() as app:
            app.start_session()

            # Set input_files from previous stage
            app.context["input_files"] = ["old_file.fit"]

            stage = {
                "description": "Test stage",
                "tool": "python",
                "script": "pass",
            }

            app.run_stage(stage)

            # input_files should be removed
            assert "input_files" not in app.context

    def test_run_all_stages_executes_stages(
        self, setup_test_environment, mock_analytics
    ):
        """Test that run_all_stages executes stages in priority order."""
        with Starbash() as app:
            # Mock the repo manager to return valid stage definitions
            app.repo_manager.merged = MagicMock()
            app.repo_manager.merged.getall.side_effect = [
                # First call for stages definitions
                [
                    [
                        {"name": "stage1", "priority": 1},
                        {"name": "stage2", "priority": 2},
                    ]
                ],
                # Second call for stage tasks
                [
                    [
                        {
                            "when": "stage1",
                            "tool": "python",
                            "script": "context['s1'] = 1",
                        },
                        {
                            "when": "stage2",
                            "tool": "python",
                            "script": "context['s2'] = 2",
                        },
                    ]
                ],
            ]

            app.run_all_stages()

            # Check that stages were executed
            assert app.context.get("s1") == 1
            assert app.context.get("s2") == 2

    def test_run_all_stages_missing_priority(
        self, setup_test_environment, mock_analytics
    ):
        """Test that run_all_stages raises error for stages missing priority."""
        with Starbash() as app:
            # Mock the repo manager to return invalid stage definitions
            app.repo_manager.merged = MagicMock()
            app.repo_manager.merged.getall.return_value = [
                [{"name": "stage1"}]  # Missing priority
            ]

            with pytest.raises(ValueError, match="missing the required 'priority' key"):
                app.run_all_stages()

    def test_run_all_stages_missing_name(self, setup_test_environment, mock_analytics):
        """Test that run_all_stages raises error for stages missing name."""
        with Starbash() as app:
            # Mock the repo manager to return invalid stage definitions
            app.repo_manager.merged = MagicMock()
            app.repo_manager.merged.getall.return_value = [
                [{"priority": 1}]  # Missing name
            ]

            with pytest.raises(ValueError, match="missing 'name' key"):
                app.run_all_stages()
