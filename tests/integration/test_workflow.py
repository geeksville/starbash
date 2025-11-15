"""Integration tests for starbash workflow.

These tests run through a complete workflow:
1. Add multiple test data repositories
2. Verify data is indexed and accessible
3. Generate master calibration frames
4. Process images automatically

Tests are marked with @pytest.mark.integration and require /test-data to be available.
Run with: pytest -m integration tests/integration/ -n 0
Note: These tests must run sequentially (not in parallel) to build upon each other's state.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from starbash.main import app

# Configure CliRunner to disable Rich formatting
runner = CliRunner(env={"NO_COLOR": "1"})

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="class")
def workflow_environment(tmp_path_factory, test_data_dir):
    """Shared environment for the entire workflow test sequence.

    This class-scoped fixture allows tests to build upon each other's state.
    Each test class will have access to the same starbash environment
    with accumulated data from previous operations.
    """
    from starbash import paths

    # Create a persistent test directory for the entire workflow
    test_root = tmp_path_factory.mktemp("workflow")
    config_dir = test_root / "config"
    data_dir = test_root / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Set the override directories
    paths.set_test_directories(config_dir, data_dir)

    yield {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "test_data_dir": test_data_dir,
        "test_root": test_root,
    }

    # Clean up after all tests in the class
    paths.set_test_directories(None, None)


@pytest.mark.usefixtures("mock_analytics")
class TestRepoAddWorkflow:
    """Test adding repositories and verifying data is indexed.

    These tests run in sequence and each builds on the previous one.
    If an early test fails, later tests may also fail.
    """

    def _add_test_data_repo(self, workflow_environment, repo_name: str):
        """Helper to add a test data repository.

        Args:
            workflow_environment: The workflow fixture providing test paths
            repo_name: Name of the subdirectory under /test-data (e.g., 'dwarf3', 'asiair')
        """
        test_data = workflow_environment["test_data_dir"]
        repo_path = test_data / repo_name

        # Skip if this specific test data doesn't exist
        if not repo_path.exists():
            pytest.skip(f"Test data not found: {repo_path}")

        result = runner.invoke(app, ["repo", "add", str(repo_path)])
        assert result.exit_code == 0, f"Failed to add {repo_name} repo: {result.stdout}"
        # Check for success messages (either adding or already added)
        output_lower = result.stdout.lower()
        assert "adding repository" in output_lower or "already added" in output_lower, (
            f"Unexpected output: {result.stdout}"
        )

    def test_add_dwarf3_repo(self, workflow_environment):
        """Add dwarf3 test data repository."""
        self._add_test_data_repo(workflow_environment, "dwarf3")

    def test_add_asiair_repo(self, workflow_environment):
        """Add asiair test data repository."""
        self._add_test_data_repo(workflow_environment, "asiair")

    def test_add_nina_repo(self, workflow_environment):
        """Add nina test data repository."""
        self._add_test_data_repo(workflow_environment, "nina")

    def test_add_seestar_repo(self, workflow_environment):
        """Add seestar test data repository."""
        self._add_test_data_repo(workflow_environment, "seestar")

    def test_verify_info_after_repo_add(self, workflow_environment):
        """Verify 'sb info' shows indexed data from added repos."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0, f"'sb info' failed: {result.stdout}"

        # Verify expected output contains meaningful data
        output = result.stdout
        assert len(output) > 0, "Info command should produce output"

        # Check for expected metrics from indexed test data
        assert "Total Repositories" in output, "Should show total repositories"
        assert "Sessions Indexed" in output, "Should show sessions indexed"
        assert "Images Indexed" in output, "Should show images indexed"
        assert "Total image time" in output, "Should show total image time"

        # Verify we have substantial data indexed (based on test data in /test-data)
        # Total Repositories should be >12 (package defaults + test data repos)
        # Sessions should be >40, Images >500, Total time >4h
        import re

        repos_match = re.search(r"Total Repositories\s+│\s+(\d+)", output)
        assert repos_match, "Could not find Total Repositories value"
        total_repos = int(repos_match.group(1))
        assert total_repos > 12, f"Expected >12 repos, got {total_repos}"

        sessions_match = re.search(r"Sessions Indexed\s+│\s+(\d+)", output)
        assert sessions_match, "Could not find Sessions Indexed value"
        sessions = int(sessions_match.group(1))
        assert sessions > 40, f"Expected >40 sessions, got {sessions}"

        images_match = re.search(r"Images Indexed\s+│\s+(\d+)", output)
        assert images_match, "Could not find Images Indexed value"
        images = int(images_match.group(1))
        assert images > 500, f"Expected >500 images, got {images}"

        time_match = re.search(r"Total image time\s+│\s+(\d+)h", output)
        assert time_match, "Could not find Total image time value"
        hours = int(time_match.group(1))
        assert hours >= 4, f"Expected >=4 hours, got {hours}h"

    def test_verify_select_list_after_repo_add(self, workflow_environment):
        """Verify 'sb select list --brief' shows sessions from added repos."""
        result = runner.invoke(app, ["select", "list", "--brief"])
        assert result.exit_code == 0, f"'sb select list --brief' failed: {result.stdout}"

        output = result.stdout
        assert len(output) > 0, "Select list should produce output"

        # Check for "Sessions (X selected out of Y)" header with X and Y > 40
        import re

        sessions_header_match = re.search(r"Sessions \((\d+) selected out of (\d+)\)", output)
        assert sessions_header_match, (
            f"Could not find 'Sessions (X selected out of Y)' header in output:\n{output}"
        )

        selected_count = int(sessions_header_match.group(1))
        total_count = int(sessions_header_match.group(2))
        assert selected_count > 40, f"Expected >40 selected sessions, got {selected_count}"
        assert total_count > 40, f"Expected >40 total sessions, got {total_count}"

        # Check for at least 4 numbered table rows (format: "│ N   │ ...")
        table_row_matches = re.findall(r"│\s+(\d+)\s+│", output)
        assert len(table_row_matches) >= 4, (
            f"Expected at least 4 table rows, found {len(table_row_matches)}"
        )

    def test_verify_repo_list_shows_added_repos(self, workflow_environment):
        """Verify all added repos appear in 'sb repo list'."""
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0, f"'sb repo list' failed: {result.stdout}"

        # At least some of our test data repos should be in the list
        # (checking for any one is sufficient to know repos were added)
        output = result.stdout.lower()
        has_test_data = (
            "dwarf3" in output or "asiair" in output or "nina" in output or "seestar" in output
        )
        assert has_test_data, f"No test data repos found in output:\n{result.stdout}"


@pytest.mark.usefixtures("mock_analytics")
class TestProcessMastersWorkflow:
    """Test generating master calibration frames.

    These tests depend on repos being added in TestRepoAddWorkflow.
    They use the same workflow_environment fixture to access the accumulated state.
    """

    def test_process_masters_executes(self, workflow_environment):
        """Run 'sb process masters' and verify it completes without error."""
        result = runner.invoke(app, ["process", "masters"])

        # The command should complete (exit code 0) even if no masters are generated
        # (depends on whether calibration frames exist in test data)
        assert result.exit_code == 0, f"'sb process masters' failed: {result.stdout}"

        # Should show some output about processing or results
        assert len(result.stdout) > 0, "Process masters should produce output"

    def test_process_masters_output_messages(self, workflow_environment):
        """Verify 'sb process masters' produces expected output messages."""
        result = runner.invoke(app, ["process", "masters"])
        assert result.exit_code == 0, f"'sb process masters' failed: {result.stdout}"

        # Should mention generating masters or show results
        # (exact message depends on whether calibration frames were found)
        output = result.stdout.lower()
        has_master_output = (
            "generating" in output
            or "master" in output
            or "generated" in output
            or "no results" in output
        )
        assert has_master_output, f"Expected master-related output:\n{result.stdout}"

    def test_database_updated_after_masters(self, workflow_environment):
        """Verify database has been updated (sessions may have been processed)."""
        from starbash.database import Database

        data_dir = workflow_environment["data_dir"]
        db_path = data_dir / "db.sqlite3"

        # Database should exist after processing
        assert db_path.exists(), "Database file should exist after processing"

        # Can open and query database without errors
        with Database(base_dir=data_dir) as db:
            # Just verify we can query sessions (result may be empty)
            sessions = db.search_session()
            # No assertion on count - depends on test data content


@pytest.mark.usefixtures("mock_analytics")
class TestProcessAutoWorkflow:
    """Test automatic processing workflow.

    These tests depend on repos being added and masters being processed
    in previous test classes. They use the same workflow_environment fixture.
    """

    def test_process_auto_executes(self, workflow_environment):
        """Run 'sb process auto' and verify it completes without error."""
        result = runner.invoke(app, ["process", "auto"])

        # Command should complete (may not process anything if no suitable data)
        assert result.exit_code == 0, f"'sb process auto' failed: {result.stdout}"

        # Should produce some output
        assert len(result.stdout) > 0, "Process auto should produce output"

    def test_process_auto_output_messages(self, workflow_environment):
        """Verify 'sb process auto' produces expected output messages."""
        result = runner.invoke(app, ["process", "auto"])
        assert result.exit_code == 0, f"'sb process auto' failed: {result.stdout}"

        # Should mention auto-processing or show results
        output = result.stdout.lower()
        has_processing_output = (
            "auto-processing" in output
            or "processing" in output
            or "autoprocessed" in output
            or "no results" in output
        )
        assert has_processing_output, f"Expected processing-related output:\n{result.stdout}"

    def test_workflow_completion(self, workflow_environment):
        """Verify the complete workflow has run successfully.

        This is a final sanity check that the entire sequence completed:
        - Repos were added
        - Database was created and populated
        - Processing commands executed without errors
        """
        data_dir = workflow_environment["data_dir"]
        db_path = data_dir / "db.sqlite3"

        # Database should exist
        assert db_path.exists(), "Database should exist after complete workflow"

        # Can query repos
        result = runner.invoke(app, ["repo", "list"])
        assert result.exit_code == 0, "Should be able to list repos"

        # Can query sessions
        result = runner.invoke(app, ["select", "list"])
        assert result.exit_code == 0, "Should be able to list sessions"

        # Workflow environment should have the expected structure
        assert workflow_environment["config_dir"].exists()
        assert workflow_environment["data_dir"].exists()
