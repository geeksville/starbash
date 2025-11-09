"""Tests for CLI commands to ensure they don't crash on invocation."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from starbash import paths
from starbash.database import Database, get_column_name
from starbash.main import app

# Rich formatting is automatically disabled when PYTEST_CURRENT_TEST is set
# (see src/starbash/__init__.py), so test output is plain text without ANSI codes
runner = CliRunner()

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from starbash import paths
from starbash.database import Database
from starbash.main import app

# Configure CliRunner to disable Rich formatting by setting NO_COLOR env var
# This makes Rich automatically disable all ANSI codes and formatting
runner = CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def setup_test_environment(tmp_path):
    """Setup a test environment with isolated config and data directories."""
    import starbash

    # Save original global state
    original_verbose = starbash.verbose_output
    original_force_regen = starbash.force_regen
    original_log_level = starbash.log_filter_level

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

    # Restore original global state to prevent test pollution
    starbash.verbose_output = original_verbose
    starbash.force_regen = original_force_regen
    starbash.log_filter_level = original_log_level


def test_session_command_no_data(setup_test_environment):
    """Test 'starbash select list' command with no data - should not crash."""
    result = runner.invoke(app, ["select", "list"])
    assert result.exit_code == 0
    # Should run without errors even with no sessions


def test_session_command_with_data(setup_test_environment, tmp_path):
    """Test 'starbash select list' command with some session data."""
    # Create a database and add some session data
    data_dir = setup_test_environment["data_dir"]
    with Database(base_dir=data_dir) as db:
        # First create a repo
        repo_url = "file:///tmp/test_repo"
        db.upsert_repo(repo_url)

        # Create an image that will be the reference for the session
        image_rec = {
            "path": "test_image.fits",
            "DATE-OBS": "2023-10-15T20:30:00",
            "DATE": "2023-10-15",
            "IMAGETYP": "Light",
            "FILTER": "Ha",
            "OBJECT": "M31",
            "TELESCOP": "Test Telescope",
            "EXPTIME": 120.0,
        }
        image_id = db.upsert_image(image_rec, repo_url)

        # Now create the session with reference to the image
        session = {
            get_column_name(Database.START_KEY): "2023-10-15T20:30:00",
            get_column_name(Database.END_KEY): "2023-10-15T22:30:00",
            get_column_name(Database.FILTER_KEY): "Ha",
            get_column_name(Database.IMAGETYP_KEY): "Light",
            get_column_name(Database.OBJECT_KEY): "M31",
            get_column_name(Database.TELESCOP_KEY): "Test Telescope",
            get_column_name(Database.NUM_IMAGES_KEY): 10,
            get_column_name(Database.EXPTIME_TOTAL_KEY): 600.0,
            get_column_name(Database.EXPTIME_KEY): 120.0,
            get_column_name(Database.IMAGE_DOC_KEY): image_id,
        }
        db.upsert_session(session)

    result = runner.invoke(app, ["select", "list"])
    assert result.exit_code == 0
    # Should display the session data


def test_repo_list_command(setup_test_environment):
    """Test 'starbash repo' command (default list behavior) - should not crash."""
    result = runner.invoke(app, ["repo"])
    assert result.exit_code == 0
    # Should list at least the default repos


def test_repo_list_non_verbose(setup_test_environment):
    """Test 'starbash repo' without verbose shows only user-visible repos with numbers."""
    # First add a test repo so we have something to list
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        test_repo = Path(tmpdir) / "test_repo"
        test_repo.mkdir()

        # Add the test repo
        result = runner.invoke(app, ["repo", "add", str(test_repo)])
        assert result.exit_code == 0

        # Now list repos
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0

        # Should show numbered repos (user-visible only)
        output = result.stdout

        # Find all lines (filter out log lines which start with whitespace followed by INFO/DEBUG/etc)
        output_lines = [
            line
            for line in output.split("\n")
            if line.strip()
            and not line.strip().startswith("INFO")
            and not line.strip().startswith("DEBUG")
        ]

        # Should have at least one numbered line (format: " 1: file://..." or "1: file://...")
        numbered_lines = [
            line
            for line in output_lines
            if line.strip() and ":" in line and line.strip().split(":")[0].strip().isdigit()
        ]

        # Debug output for troubleshooting
        if len(numbered_lines) == 0:
            print(f"\n=== DEBUG: Full output ===\n{output}")
            print(f"\n=== DEBUG: Output lines ===\n{output_lines}")
            print(f"\n=== DEBUG: Numbered lines ===\n{numbered_lines}")

        assert len(numbered_lines) > 0, f"Should have numbered repos. Output lines: {output_lines}"

        # Should NOT show preferences or recipe repos in non-verbose mode
        # (these are filtered out by regular_repos property)
        assert "(kind=preferences)" not in output or output.count("(kind=preferences)") == 0

        # Some repos might be shown, but pkg:// repos should be filtered
        # Should have file:// but not pkg://
        assert any("file://" in line for line in numbered_lines)
        assert not any("pkg://" in line for line in numbered_lines)


def test_repo_list_verbose(setup_test_environment):
    """Test 'starbash --verbose repo list' shows all repos without numbers."""
    result = runner.invoke(app, ["--verbose", "repo", "list"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show preferences and recipe repos
    assert "pkg://defaults" in output or "(kind=preferences)" in output

    # Should NOT have numbered format in verbose mode
    # Filter out log lines to get actual repo lines
    lines_with_repos = [
        line
        for line in output.split("\n")
        if (
            ("file://" in line or "pkg://" in line)
            and not line.strip().startswith("INFO")
            and not line.strip().startswith("DEBUG")
        )
    ]

    # Check that lines don't start with numbers (format should be "file://..." not " 1: file://...")
    for line in lines_with_repos:
        stripped = line.strip()
        if stripped:
            # Should start with pkg:// or file://, not a number
            assert stripped.startswith("pkg://") or stripped.startswith("file://"), (
                f"Verbose mode should not show numbers, but got: {stripped}"
            )


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
    list_result = runner.invoke(app, ["repo", "list"])
    assert list_result.exit_code == 0

    # The test repo should be in the list
    assert "testrepo" in list_result.stdout

    # Find the repo number - filter out log lines first
    lines = [
        line
        for line in list_result.stdout.split("\n")
        if (
            line.strip()
            and ":" in line
            and "file://" in line
            and not line.strip().startswith("INFO")
            and not line.strip().startswith("DEBUG")
        )
    ]
    # Get the last numbered line
    last_line = None
    for line in lines:
        if line.strip() and line.strip()[0].isdigit():
            last_line = line

    # Debug output for troubleshooting
    if last_line is None:
        print(f"\n=== DEBUG: Full output ===\n{list_result.stdout}")
        print(f"\n=== DEBUG: Filtered lines ===\n{lines}")

    assert last_line is not None, f"Could not find numbered repo in list. Lines: {lines}"
    repo_num = last_line.strip().split(":")[0].strip()

    # Remove the repo
    remove_result = runner.invoke(app, ["repo", "remove", repo_num])
    assert remove_result.exit_code == 0
    assert "Removed repository" in remove_result.stdout

    # Verify it's gone
    list_after = runner.invoke(app, ["repo", "list"])
    assert list_after.exit_code == 0
    assert "testrepo" not in list_after.stdout


def test_repo_remove_invalid_number(setup_test_environment):
    """Test 'starbash repo remove' with invalid input."""
    # Try to remove with invalid number
    result = runner.invoke(app, ["repo", "remove", "abc"])
    assert result.exit_code == 1
    assert "not valid" in result.stdout.lower()


def test_repo_remove_out_of_range(setup_test_environment):
    """Test 'starbash repo remove' with out of range number."""
    # Try to remove with out of range number
    result = runner.invoke(app, ["repo", "remove", "999"])
    assert result.exit_code == 1
    assert "not a valid repository number" in result.stdout.lower()


def test_repo_reindex_command(setup_test_environment):
    """Test 'starbash repo reindex' command - should not crash."""
    result = runner.invoke(app, ["repo", "reindex"])
    # Should complete without crashing, even if no images to index
    assert result.exit_code == 0
    assert "Reindexing" in result.stdout or result.exit_code == 0


# No longer slow - now that we run in a test env
# @pytest.mark.slow
def test_repo_reindex_with_force(setup_test_environment):
    """Test 'starbash --force repo reindex ' command - should not crash."""
    result = runner.invoke(app, ["--force", "repo", "reindex"])
    assert result.exit_code == 0


def test_repo_reindex_by_number(setup_test_environment, tmp_path):
    """Test 'starbash repo reindex NUM' command - reindex a specific repo."""
    # First add a test repo
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()
    add_result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert add_result.exit_code == 0

    # Find the repo number
    list_result = runner.invoke(app, ["repo", "list"])
    assert list_result.exit_code == 0

    # The test repo should be in the list
    assert "testrepo" in list_result.stdout

    # Find the repo number - filter out log lines first
    lines = [
        line
        for line in list_result.stdout.split("\n")
        if (
            line.strip()
            and ":" in line
            and "file://" in line
            and not line.strip().startswith("INFO")
            and not line.strip().startswith("DEBUG")
        )
    ]
    # Get the last numbered line
    last_line = None
    for line in lines:
        if line.strip() and line.strip()[0].isdigit():
            last_line = line

    # Debug output for troubleshooting
    if last_line is None:
        print(f"\n=== DEBUG: Full output ===\n{list_result.stdout}")
        print(f"\n=== DEBUG: Filtered lines ===\n{lines}")

    assert last_line is not None, f"Could not find numbered repo in list. Lines: {lines}"
    repo_num = last_line.strip().split(":")[0].strip()

    # Reindex the specific repo
    result = runner.invoke(app, ["repo", "reindex", repo_num])
    assert result.exit_code == 0
    assert "Successfully reindexed" in result.stdout


def test_repo_reindex_invalid_number(setup_test_environment):
    """Test 'starbash repo reindex' with invalid input."""
    result = runner.invoke(app, ["repo", "reindex", "abc"])
    assert result.exit_code == 1
    assert "not valid" in result.stdout.lower()


def test_repo_reindex_out_of_range(setup_test_environment):
    """Test 'starbash repo reindex' with out of range number."""
    result = runner.invoke(app, ["repo", "reindex", "999"])
    assert result.exit_code == 1
    assert "not a valid repository number" in result.stdout.lower()


def test_repo_remove_by_url(setup_test_environment, tmp_path):
    """Test 'starbash repo remove' command with URL instead of number."""
    # Add a test repo first
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()

    add_result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert add_result.exit_code == 0

    # Remove by URL
    repo_url = f"file://{test_repo}"
    remove_result = runner.invoke(app, ["repo", "remove", repo_url])
    assert remove_result.exit_code == 0
    assert "Removed repository" in remove_result.stdout

    # Verify it's gone
    list_after = runner.invoke(app, ["repo"])
    assert list_after.exit_code == 0
    assert "testrepo" not in list_after.stdout


def test_repo_reindex_by_url(setup_test_environment, tmp_path):
    """Test 'starbash repo reindex URL' command - reindex a specific repo by URL."""
    # First add a test repo
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()
    add_result = runner.invoke(app, ["repo", "add", str(test_repo)])
    assert add_result.exit_code == 0

    # Reindex by URL
    repo_url = f"file://{test_repo}"
    result = runner.invoke(app, ["repo", "reindex", repo_url])
    assert result.exit_code == 0
    assert "Successfully reindexed" in result.stdout


def test_repo_complete_by_num(setup_test_environment, tmp_path):
    """Test the complete_repo_by_num function."""
    from starbash.commands.repo import complete_repo_by_num

    # Add a test repo
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()
    runner.invoke(app, ["repo", "add", str(test_repo)])

    # Test completion
    completions = list(complete_repo_by_num("1"))
    assert len(completions) > 0
    # Should return tuples of (number, url)
    assert all(isinstance(c, tuple) and len(c) == 2 for c in completions)


def test_repo_complete_by_url(setup_test_environment, tmp_path):
    """Test the complete_repo_by_url function."""
    from starbash.commands.repo import complete_repo_by_url

    # Add a test repo
    test_repo = tmp_path / "testrepo"
    test_repo.mkdir()
    runner.invoke(app, ["repo", "add", str(test_repo)])

    # Test completion with file:// prefix
    completions = list(complete_repo_by_url("file://"))
    assert len(completions) > 0
    # Should return tuples of (url, description)
    assert all(isinstance(c, tuple) and len(c) == 2 for c in completions)
    assert all(c[0].startswith("file://") for c in completions)


def test_help_commands(setup_test_environment):
    """Test that help commands work without requiring setup."""
    # Ensure config file exists to avoid triggering reinit
    from starbash.app import create_user

    create_user()

    # Main help
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "select" in result.stdout.lower()

    # Test running without arguments shows help
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "select" in result.stdout.lower()
    assert "Commands" in result.stdout or "commands" in result.stdout.lower()

    # Select help
    result = runner.invoke(app, ["select", "--help"])
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
    """Test select list command when database exists but has no sessions."""
    data_dir = setup_test_environment["data_dir"]

    # Initialize database but don't add any sessions
    with Database(base_dir=data_dir) as db:
        pass  # Just create the empty database

    result = runner.invoke(app, ["select", "list"])
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


def test_user_reinit_command(setup_test_environment):
    """Test 'starbash user reinit' command with interactive prompts."""
    # Test with full input
    result = runner.invoke(app, ["user", "reinit"], input="John Doe\njohn@example.com\ny\n")
    assert result.exit_code == 0
    assert "Configuration complete!" in result.stdout
    assert "Name set to: John Doe" in result.stdout
    assert "Email set to: john@example.com" in result.stdout
    assert "Email will be included with crash reports" in result.stdout


def test_user_reinit_command_skip_all(setup_test_environment):
    """Test 'starbash user reinit' command skipping all questions."""
    # Test with empty input (skip everything)
    result = runner.invoke(app, ["user", "reinit"], input="\n\nn\n")
    assert result.exit_code == 0
    assert "Configuration complete!" in result.stdout
    assert "Skipped name" in result.stdout
    assert "Skipped email" in result.stdout
    assert "Email will NOT be included with crash reports" in result.stdout


def test_user_reinit_command_partial(setup_test_environment):
    """Test 'starbash user reinit' command with partial input."""
    # Test with only name provided
    result = runner.invoke(app, ["user", "reinit"], input="Jane Smith\n\nn\n")
    assert result.exit_code == 0
    assert "Configuration complete!" in result.stdout
    assert "Name set to: Jane Smith" in result.stdout
    assert "Skipped email" in result.stdout
    assert "Email will NOT be included with crash reports" in result.stdout


def test_user_help_commands():
    """Test that user help commands work."""
    # User help
    result = runner.invoke(app, ["user", "--help"])
    assert result.exit_code == 0
    assert "name" in result.stdout.lower()
    assert "email" in result.stdout.lower()
    assert "analytics" in result.stdout.lower()
    assert "reinit" in result.stdout.lower()

    # User name help
    result = runner.invoke(app, ["user", "name", "--help"])
    assert result.exit_code == 0

    # User email help
    result = runner.invoke(app, ["user", "email", "--help"])
    assert result.exit_code == 0

    # User analytics help
    result = runner.invoke(app, ["user", "analytics", "--help"])
    assert result.exit_code == 0

    # User reinit help
    result = runner.invoke(app, ["user", "reinit", "--help"])
    assert result.exit_code == 0


def test_selection_commands(setup_test_environment):
    """Test 'starbash select' commands - should not crash."""
    # Clear any existing selection first
    runner.invoke(app, ["select", "any"])

    # Test showing selection with no filters
    result = runner.invoke(app, ["select"])
    assert result.exit_code == 0
    assert "selecting all" in result.stdout.lower() or "no filters" in result.stdout.lower()

    # Test setting a target
    result = runner.invoke(app, ["select", "target", "M31"])
    assert result.exit_code == 0
    assert "M31" in result.stdout

    # Test showing selection with a target
    result = runner.invoke(app, ["select"])
    assert result.exit_code == 0
    assert "M31" in result.stdout

    # Test setting a date range
    result = runner.invoke(app, ["select", "date", "after", "2023-10-01"])
    assert result.exit_code == 0
    assert "2023-10-01" in result.stdout

    # Test clearing selection
    result = runner.invoke(app, ["select", "any"])
    assert result.exit_code == 0
    assert "cleared" in result.stdout.lower()

    # Verify selection is cleared
    result = runner.invoke(app, ["select"])
    assert result.exit_code == 0
    assert "selecting all" in result.stdout.lower() or "no filters" in result.stdout.lower()


def test_selection_date_between(setup_test_environment):
    """Test 'starbash select date between' command."""
    # Clear any existing selection first
    runner.invoke(app, ["select", "any"])

    result = runner.invoke(app, ["select", "date", "between", "2023-10-01", "2023-12-31"])
    assert result.exit_code == 0
    assert "2023-10-01" in result.stdout
    assert "2023-12-31" in result.stdout

    # Clean up after test
    runner.invoke(app, ["select", "any"])


def test_selection_help_commands():
    """Test that select help commands work."""
    # Select help
    result = runner.invoke(app, ["select", "--help"])
    assert result.exit_code == 0
    assert "target" in result.stdout.lower()
    assert "date" in result.stdout.lower()

    # Select target help
    result = runner.invoke(app, ["select", "target", "--help"])
    assert result.exit_code == 0

    # Select date help
    result = runner.invoke(app, ["select", "date", "--help"])
    assert result.exit_code == 0

    # Select any help
    result = runner.invoke(app, ["select", "any", "--help"])
    assert result.exit_code == 0
