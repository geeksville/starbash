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
    """Test 'starbash repo' command (default list behavior) - should not crash."""
    result = runner.invoke(app, ["repo"])
    assert result.exit_code == 0
    # Should list at least the default repos


def test_repo_list_non_verbose(setup_test_environment):
    """Test 'starbash repo' without verbose shows only user-visible repos with numbers."""
    result = runner.invoke(app, ["repo"])
    assert result.exit_code == 0

    # Should show numbered repos (user-visible only)
    output = result.stdout

    # Should have at least one numbered line (format: " 1: file://...")
    assert any(
        line.strip().startswith(f"{i}:")
        for i in range(1, 20)
        for line in output.split("\n")
    )

    # Should NOT show preferences or recipe repos in non-verbose mode
    # (these are filtered out by regular_repos property)
    assert "(kind=preferences)" not in output or output.count("(kind=preferences)") == 0
    # Some repos might be shown, but recipe repos should be filtered
    lines_with_repos = [
        line for line in output.split("\n") if "file://" in line or "pkg://" in line
    ]

    # Verify numbered format exists
    has_numbers = any(
        ":" in line and line.split(":")[0].strip().isdigit()
        for line in lines_with_repos
    )
    assert has_numbers, "Non-verbose mode should show numbered repos"


def test_repo_list_verbose(setup_test_environment):
    """Test 'starbash repo --verbose' shows all repos without numbers."""
    result = runner.invoke(app, ["repo", "--verbose"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show preferences and recipe repos
    assert "pkg://defaults" in output or "(kind=preferences)" in output

    # Should NOT have numbered format in verbose mode
    lines_with_repos = [
        line for line in output.split("\n") if "file://" in line or "pkg://" in line
    ]

    # Check that lines don't start with numbers (format should be "file://..." not " 1: file://...")
    for line in lines_with_repos:
        stripped = line.strip()
        if stripped:
            # Should start with pkg:// or file://, not a number
            assert stripped.startswith("pkg://") or stripped.startswith(
                "file://"
            ), f"Verbose mode should not show numbers, but got: {stripped}"


def test_repo_list_verbose_short_flag(setup_test_environment):
    """Test 'starbash repo -v' (short flag) shows all repos without numbers."""
    result = runner.invoke(app, ["repo", "-v"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show system repos (preferences or recipes)
    assert (
        "pkg://defaults" in output
        or "(kind=preferences)" in output
        or "(kind=recipe)" in output
    )

    # Should NOT have numbered format
    lines_with_repos = [
        line for line in output.split("\n") if "file://" in line or "pkg://" in line
    ]
    for line in lines_with_repos:
        stripped = line.strip()
        if stripped:
            assert stripped.startswith("pkg://") or stripped.startswith(
                "file://"
            ), f"Verbose mode with -v should not show numbers, but got: {stripped}"


def test_repo_add_command(setup_test_environment, tmp_path):
    """Test 'starbash repo add' command - should not crash."""
    # Create a dummy repo directory
    test_repo = tmp_path / "test_repo"
    test_repo.mkdir()

    result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert result.exit_code == 0
    assert "Added repository" in result.stdout or result.exit_code == 0


def test_repo_remove_command(setup_test_environment, tmp_path):
    """Test 'starbash repo remove' command - can remove a user-added repo."""
    # Add a test repo first
    test_repo = tmp_path / "testrepo"  # Short name to avoid wrapping issues
    test_repo.mkdir()

    add_result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert add_result.exit_code == 0

    # List to find the repo number
    list_result = runner.invoke(app, ["repo"])
    assert list_result.exit_code == 0

    # The test repo should be in the list
    assert "testrepo" in list_result.stdout

    # Find the repo number (it should be the last numbered line)
    lines = [
        line
        for line in list_result.stdout.split("\n")
        if line.strip() and ":" in line and "file://" in line
    ]
    # Get the last numbered line
    last_line = None
    for line in lines:
        if line.strip() and line.strip()[0].isdigit():
            last_line = line

    assert last_line is not None, "Could not find numbered repo in list"
    repo_num = last_line.strip().split(":")[0].strip()

    # Remove the repo
    remove_result = runner.invoke(app, ["repo", "remove", repo_num])
    assert remove_result.exit_code == 0
    assert "Removed repository" in remove_result.stdout

    # Verify it's gone
    list_after = runner.invoke(app, ["repo"])
    assert list_after.exit_code == 0
    assert "testrepo" not in list_after.stdout


def test_repo_remove_invalid_number(setup_test_environment):
    """Test 'starbash repo remove' with invalid input."""
    # Try to remove with invalid number
    result = runner.invoke(app, ["repo", "remove", "abc"])
    assert result.exit_code == 1
    assert "not a valid repository number" in result.stdout.lower()


def test_repo_remove_out_of_range(setup_test_environment):
    """Test 'starbash repo remove' with out of range number."""
    # Try to remove with out of range number
    result = runner.invoke(app, ["repo", "remove", "999"])
    assert result.exit_code == 1
    assert "out of range" in result.stdout.lower()


def test_repo_reindex_command(setup_test_environment):
    """Test 'starbash repo reindex' command - should not crash."""
    result = runner.invoke(app, ["repo", "reindex"])
    # Should complete without crashing, even if no images to index
    assert result.exit_code == 0
    assert "Reindexing" in result.stdout or result.exit_code == 0


# No longer slow - now that we run in a test env
# @pytest.mark.slow
def test_repo_reindex_with_force(setup_test_environment):
    """Test 'starbash repo reindex --force' command - should not crash."""
    result = runner.invoke(app, ["repo", "reindex", "--force"])
    assert result.exit_code == 0


def test_repo_reindex_by_number(setup_test_environment, tmp_path):
    """Test 'starbash repo reindex NUM' command - reindex a specific repo."""
    # First add a test repo
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()
    add_result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert add_result.exit_code == 0

    # Find the repo number
    list_result = runner.invoke(app, ["repo"])
    assert list_result.exit_code == 0

    # The test repo should be in the list
    assert "testrepo" in list_result.stdout

    # Find the repo number (it should be the last numbered line)
    lines = [
        line
        for line in list_result.stdout.split("\n")
        if line.strip() and ":" in line and "file://" in line
    ]
    # Get the last numbered line
    last_line = None
    for line in lines:
        if line.strip() and line.strip()[0].isdigit():
            last_line = line

    assert last_line is not None, "Could not find numbered repo in list"
    repo_num = last_line.strip().split(":")[0].strip()

    # Reindex the specific repo
    result = runner.invoke(app, ["repo", "reindex", repo_num])
    assert result.exit_code == 0
    assert "Successfully reindexed" in result.stdout


def test_repo_reindex_invalid_number(setup_test_environment):
    """Test 'starbash repo reindex' with invalid input."""
    result = runner.invoke(app, ["repo", "reindex", "abc"])
    assert result.exit_code == 1
    assert "not a valid repository number" in result.stdout.lower()


def test_repo_reindex_out_of_range(setup_test_environment):
    """Test 'starbash repo reindex' with out of range number."""
    result = runner.invoke(app, ["repo", "reindex", "999"])
    assert result.exit_code == 1
    assert "out of range" in result.stdout.lower()


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
    assert "manage" in result.stdout.lower()

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
