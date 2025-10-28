"""Tests for CLI commands to ensure they don't crash on invocation."""

from pathlib import Path
from typer.testing import CliRunner
import pytest

from starbash.main import app
from starbash.database import Database
from starbash import paths

runner = CliRunner()


@pytest.fixture
def setup_test_environment(tmp_path):
    """Setup a test environment with isolated config and data directories."""
    # Create isolated directories for testing
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Set the override directories for this test
    paths.set_test_directories(config_dir, data_dir)

    yield {"config_dir": config_dir, "data_dir": data_dir}

    # Clean up: reset to None after test
    paths.set_test_directories(None, None)


def test_session_command_no_data(setup_test_environment):
    """Test 'starbash session' command with no data - should not crash."""
    result = runner.invoke(app, ["session"])
    assert result.exit_code == 0
    # Should run without errors even with no sessions


def test_session_command_with_data(setup_test_environment, tmp_path):
    """Test 'starbash session' command with some session data."""
    # Create a database and add some session data
    data_dir = setup_test_environment["data_dir"]
    with Database(base_dir=data_dir) as db:
        session = {
            Database.START_KEY: "2023-10-15T20:30:00",
            Database.END_KEY: "2023-10-15T22:30:00",
            Database.FILTER_KEY: "Ha",
            Database.IMAGETYP_KEY: "Light",
            Database.OBJECT_KEY: "M31",
            Database.NUM_IMAGES_KEY: 10,
            Database.EXPTIME_TOTAL_KEY: 600.0,
            Database.IMAGE_DOC_KEY: 1,
        }
        db.upsert_session(session)

    result = runner.invoke(app, ["session"])
    assert result.exit_code == 0
    # Should display the session data


def test_repo_list_command(setup_test_environment):
    """Test 'starbash repo list' command - should not crash."""
    result = runner.invoke(app, ["repo", "list"])
    assert result.exit_code == 0
    # Should list at least the default repos


def test_repo_add_command(setup_test_environment, tmp_path):
    """Test 'starbash repo add' command - should not crash."""
    # Create a dummy repo directory
    test_repo = tmp_path / "test_repo"
    test_repo.mkdir()

    result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert result.exit_code == 0
    assert "Added repository" in result.stdout or result.exit_code == 0


def test_repo_reindex_command(setup_test_environment):
    """Test 'starbash repo reindex' command - should not crash."""
    result = runner.invoke(app, ["repo", "reindex"])
    # Should complete without crashing, even if no images to index
    assert result.exit_code == 0
    assert "Reindexing" in result.stdout or result.exit_code == 0


@pytest.mark.slow
def test_repo_reindex_with_force(setup_test_environment):
    """Test 'starbash repo reindex --force' command - should not crash."""
    result = runner.invoke(app, ["repo", "reindex", "--force"])
    assert result.exit_code == 0


def test_repo_remove_command_not_implemented(setup_test_environment):
    """Test 'starbash repo remove' command - currently not implemented."""
    result = runner.invoke(app, ["repo", "remove", "somerepo"])
    # Should raise but not crash unexpectedly
    # The command raises, so we expect a non-zero exit code
    assert result.exit_code != 0 or "NotImplementedError" in str(result.exception)


def test_help_commands():
    """Test that help commands work without requiring setup."""
    # Main help
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "session" in result.stdout.lower()

    # Test running without arguments shows help
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "session" in result.stdout.lower()
    assert "Commands" in result.stdout or "commands" in result.stdout.lower()

    # Session help
    result = runner.invoke(app, ["session", "--help"])
    assert result.exit_code == 0

    # Repo help
    result = runner.invoke(app, ["repo", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout.lower()

    # Repo list help
    result = runner.invoke(app, ["repo", "list", "--help"])
    assert result.exit_code == 0

    # Repo add help
    result = runner.invoke(app, ["repo", "add", "--help"])
    assert result.exit_code == 0

    # Repo reindex help
    result = runner.invoke(app, ["repo", "reindex", "--help"])
    assert result.exit_code == 0


def test_invalid_command():
    """Test that invalid commands provide helpful error messages."""
    result = runner.invoke(app, ["nonexistent"])
    assert result.exit_code != 0
    # Should show an error about unknown command


def test_session_command_empty_database(setup_test_environment):
    """Test session command when database exists but has no sessions."""
    data_dir = setup_test_environment["data_dir"]

    # Initialize database but don't add any sessions
    with Database(base_dir=data_dir) as db:
        pass  # Just create the empty database

    result = runner.invoke(app, ["session"])
    assert result.exit_code == 0
    # Should handle empty database gracefully


def test_user_name_command(setup_test_environment):
    """Test 'starbash user name' command - should not crash."""
    result = runner.invoke(app, ["user", "name", "Test User"])
    assert result.exit_code == 0
    assert "User name set to: Test User" in result.stdout


def test_user_email_command(setup_test_environment):
    """Test 'starbash user email' command - should not crash."""
    result = runner.invoke(app, ["user", "email", "test@example.com"])
    assert result.exit_code == 0
    assert "User email set to: test@example.com" in result.stdout


def test_user_analytics_command(setup_test_environment):
    """Test 'starbash user analytics' command - should not crash."""
    # Test enabling analytics
    result = runner.invoke(app, ["user", "analytics", "true"])
    assert result.exit_code == 0
    assert "enabled" in result.stdout.lower()

    # Test disabling analytics
    result = runner.invoke(app, ["user", "analytics", "false"])
    assert result.exit_code == 0
    assert "disabled" in result.stdout.lower()


def test_user_help_commands():
    """Test that user help commands work."""
    # User help
    result = runner.invoke(app, ["user", "--help"])
    assert result.exit_code == 0
    assert "name" in result.stdout.lower()
    assert "email" in result.stdout.lower()
    assert "analytics" in result.stdout.lower()

    # User name help
    result = runner.invoke(app, ["user", "name", "--help"])
    assert result.exit_code == 0

    # User email help
    result = runner.invoke(app, ["user", "email", "--help"])
    assert result.exit_code == 0

    # User analytics help
    result = runner.invoke(app, ["user", "analytics", "--help"])
    assert result.exit_code == 0


def test_selection_commands(setup_test_environment):
    """Test 'starbash selection' commands - should not crash."""
    # Clear any existing selection first
    runner.invoke(app, ["selection", "any"])

    # Test showing selection with no filters
    result = runner.invoke(app, ["selection"])
    assert result.exit_code == 0
    assert (
        "selecting all" in result.stdout.lower()
        or "no filters" in result.stdout.lower()
    )

    # Test setting a target
    result = runner.invoke(app, ["selection", "target", "M31"])
    assert result.exit_code == 0
    assert "M31" in result.stdout

    # Test showing selection with a target
    result = runner.invoke(app, ["selection"])
    assert result.exit_code == 0
    assert "M31" in result.stdout

    # Test setting a date range
    result = runner.invoke(app, ["selection", "date", "after", "2023-10-01"])
    assert result.exit_code == 0
    assert "2023-10-01" in result.stdout

    # Test clearing selection
    result = runner.invoke(app, ["selection", "any"])
    assert result.exit_code == 0
    assert "cleared" in result.stdout.lower()

    # Verify selection is cleared
    result = runner.invoke(app, ["selection"])
    assert result.exit_code == 0
    assert (
        "selecting all" in result.stdout.lower()
        or "no filters" in result.stdout.lower()
    )


def test_selection_date_between(setup_test_environment):
    """Test 'starbash selection date between' command."""
    # Clear any existing selection first
    runner.invoke(app, ["selection", "any"])

    result = runner.invoke(
        app, ["selection", "date", "between", "2023-10-01", "2023-12-31"]
    )
    assert result.exit_code == 0
    assert "2023-10-01" in result.stdout
    assert "2023-12-31" in result.stdout

    # Clean up after test
    runner.invoke(app, ["selection", "any"])


def test_selection_help_commands():
    """Test that selection help commands work."""
    # Selection help
    result = runner.invoke(app, ["selection", "--help"])
    assert result.exit_code == 0
    assert "target" in result.stdout.lower()
    assert "date" in result.stdout.lower()

    # Selection target help
    result = runner.invoke(app, ["selection", "target", "--help"])
    assert result.exit_code == 0

    # Selection date help
    result = runner.invoke(app, ["selection", "date", "--help"])
    assert result.exit_code == 0

    # Selection any help
    result = runner.invoke(app, ["selection", "any", "--help"])
    assert result.exit_code == 0
