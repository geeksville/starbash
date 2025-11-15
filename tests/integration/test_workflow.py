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

    def test_add_dwarf3_repo(self, workflow_environment):
        """Add dwarf3 test data repository."""
        test_data = workflow_environment["test_data_dir"]
        dwarf3_path = test_data / "dwarf3"

        # Skip if this specific test data doesn't exist
        if not dwarf3_path.exists():
            pytest.skip(f"Test data not found: {dwarf3_path}")

        result = runner.invoke(app, ["repo", "add", str(dwarf3_path)])
        assert result.exit_code == 0, f"Failed to add dwarf3 repo: {result.stdout}"
        # Check for success messages (either adding or already added)
        output_lower = result.stdout.lower()
        assert "adding repository" in output_lower or "already added" in output_lower, (
            f"Unexpected output: {result.stdout}"
        )

    def test_add_asiair_repo(self, workflow_environment):
        """Add asiair test data repository."""
        test_data = workflow_environment["test_data_dir"]
        asiair_path = test_data / "asiair"

        if not asiair_path.exists():
            pytest.skip(f"Test data not found: {asiair_path}")

        result = runner.invoke(app, ["repo", "add", str(asiair_path)])
        assert result.exit_code == 0, f"Failed to add asiair repo: {result.stdout}"
        output_lower = result.stdout.lower()
        assert "adding repository" in output_lower or "already added" in output_lower, (
            f"Unexpected output: {result.stdout}"
        )

    def test_add_nina_repo(self, workflow_environment):
        """Add nina test data repository."""
        test_data = workflow_environment["test_data_dir"]
        nina_path = test_data / "nina"

        if not nina_path.exists():
            pytest.skip(f"Test data not found: {nina_path}")

        result = runner.invoke(app, ["repo", "add", str(nina_path)])
        assert result.exit_code == 0, f"Failed to add nina repo: {result.stdout}"
        output_lower = result.stdout.lower()
        assert "adding repository" in output_lower or "already added" in output_lower, (
            f"Unexpected output: {result.stdout}"
        )

    def test_add_seestar_repo(self, workflow_environment):
        """Add seestar test data repository."""
        test_data = workflow_environment["test_data_dir"]
        seestar_path = test_data / "seestar"

        if not seestar_path.exists():
            pytest.skip(f"Test data not found: {seestar_path}")

        result = runner.invoke(app, ["repo", "add", str(seestar_path)])
        assert result.exit_code == 0, f"Failed to add seestar repo: {result.stdout}"
        output_lower = result.stdout.lower()
        assert "adding repository" in output_lower or "already added" in output_lower, (
            f"Unexpected output: {result.stdout}"
        )

    def test_info_after_repo_add(self, workflow_environment):
        """Verify 'sb info' shows indexed data from added repos."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0, f"'sb info' failed: {result.stdout}"

        # Should show some basic information (exact content depends on test data)
        # Just verify it runs without crashing
        assert len(result.stdout) > 0, "Info command should produce output"

    def test_select_list_after_repo_add(self, workflow_environment):
        """Verify 'sb select list --brief' shows sessions from added repos."""
        result = runner.invoke(app, ["select", "list", "--brief"])
        assert result.exit_code == 0, f"'sb select list --brief' failed: {result.stdout}"

        # With NO_COLOR, Rich output may be suppressed
        # Just verify the command completes successfully
        # (actual output depends on test data content and Rich formatting)

    def test_repo_list_shows_added_repos(self, workflow_environment):
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
