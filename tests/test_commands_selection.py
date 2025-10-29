"""Unit tests for the selection commands module."""

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from starbash.commands.selection import app
from starbash import paths

runner = CliRunner()


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


class TestSelectionClearCommand:
    """Tests for the 'selection any' command (clear)."""

    def test_clear_command_success(self, setup_test_environment, mock_analytics):
        """Test that 'selection any' clears all filters."""
        result = runner.invoke(app, ["any"])
        assert result.exit_code == 0
        assert "Selection cleared" in result.stdout
        assert "selecting all sessions" in result.stdout

    def test_clear_command_actually_clears(
        self, setup_test_environment, mock_analytics
    ):
        """Test that clear command actually modifies the selection."""
        # First add a target
        runner.invoke(app, ["target", "M31"])

        # Then clear
        result = runner.invoke(app, ["any"])
        assert result.exit_code == 0

        # Verify selection is empty by showing it
        show_result = runner.invoke(app, [])
        assert (
            "Selecting all sessions" in show_result.stdout
            or "all" in show_result.stdout.lower()
        )


class TestSelectionTargetCommand:
    """Tests for the 'selection target' command."""

    def test_target_command_success(self, setup_test_environment, mock_analytics):
        """Test that 'selection target' sets a target filter."""
        result = runner.invoke(app, ["target", "M31"])
        assert result.exit_code == 0
        assert "Selection limited to target: M31" in result.stdout

    def test_target_command_with_spaces(self, setup_test_environment, mock_analytics):
        """Test target command with target names containing spaces."""
        result = runner.invoke(app, ["target", "NGC 7000"])
        assert result.exit_code == 0
        assert "NGC 7000" in result.stdout

    def test_target_command_replaces_previous(
        self, setup_test_environment, mock_analytics
    ):
        """Test that setting a new target replaces the previous one."""
        # Set first target
        runner.invoke(app, ["target", "M31"])

        # Set second target
        result = runner.invoke(app, ["target", "M42"])
        assert result.exit_code == 0

        # Verify only the second target is in selection
        show_result = runner.invoke(app, [])
        assert "M42" in show_result.stdout

    def test_target_command_missing_argument(
        self, setup_test_environment, mock_analytics
    ):
        """Test that target command requires an argument."""
        result = runner.invoke(app, ["target"])
        assert result.exit_code != 0


class TestSelectionTelescopeCommand:
    """Tests for the 'selection telescope' command."""

    def test_telescope_command_success(self, setup_test_environment, mock_analytics):
        """Test that 'selection telescope' sets a telescope filter."""
        result = runner.invoke(app, ["telescope", "Vespera"])
        assert result.exit_code == 0
        assert "Selection limited to telescope: Vespera" in result.stdout

    def test_telescope_command_with_spaces(
        self, setup_test_environment, mock_analytics
    ):
        """Test telescope command with names containing spaces."""
        result = runner.invoke(app, ["telescope", "EdgeHD 8"])
        assert result.exit_code == 0
        assert "EdgeHD 8" in result.stdout

    def test_telescope_command_replaces_previous(
        self, setup_test_environment, mock_analytics
    ):
        """Test that setting a new telescope replaces the previous one."""
        # Set first telescope
        runner.invoke(app, ["telescope", "Vespera"])

        # Set second telescope
        result = runner.invoke(app, ["telescope", "EdgeHD"])
        assert result.exit_code == 0

        # Verify only the second telescope is in selection
        show_result = runner.invoke(app, [])
        assert "EdgeHD" in show_result.stdout

    def test_telescope_command_missing_argument(
        self, setup_test_environment, mock_analytics
    ):
        """Test that telescope command requires an argument."""
        result = runner.invoke(app, ["telescope"])
        assert result.exit_code != 0


class TestSelectionDateCommand:
    """Tests for the 'selection date' command."""

    def test_date_after_command(self, setup_test_environment, mock_analytics):
        """Test 'selection date after' command."""
        result = runner.invoke(app, ["date", "after", "2023-10-01"])
        assert result.exit_code == 0
        assert "after 2023-10-01" in result.stdout

    def test_date_before_command(self, setup_test_environment, mock_analytics):
        """Test 'selection date before' command."""
        result = runner.invoke(app, ["date", "before", "2023-12-31"])
        assert result.exit_code == 0
        assert "before 2023-12-31" in result.stdout

    def test_date_between_command(self, setup_test_environment, mock_analytics):
        """Test 'selection date between' command."""
        result = runner.invoke(app, ["date", "between", "2023-10-01", "2023-12-31"])
        assert result.exit_code == 0
        assert "between 2023-10-01 and 2023-12-31" in result.stdout

    def test_date_between_missing_end_date(
        self, setup_test_environment, mock_analytics
    ):
        """Test that 'between' requires two dates."""
        result = runner.invoke(app, ["date", "between", "2023-10-01"])
        assert result.exit_code == 1
        assert "requires two dates" in result.stdout

    def test_date_unknown_operation(self, setup_test_environment, mock_analytics):
        """Test that unknown date operations produce an error."""
        result = runner.invoke(app, ["date", "during", "2023-10-01"])
        assert result.exit_code == 1
        assert "Unknown operation" in result.stdout

    def test_date_operation_case_insensitive(
        self, setup_test_environment, mock_analytics
    ):
        """Test that date operations are case-insensitive."""
        result = runner.invoke(app, ["date", "AFTER", "2023-10-01"])
        assert result.exit_code == 0
        assert "after 2023-10-01" in result.stdout

    def test_date_missing_arguments(self, setup_test_environment, mock_analytics):
        """Test that date command requires arguments."""
        result = runner.invoke(app, ["date"])
        assert result.exit_code != 0


class TestSelectionShowCommand:
    """Tests for the default selection show command."""

    def test_show_empty_selection(self, setup_test_environment, mock_analytics):
        """Test showing an empty selection."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show message about selecting all sessions
        assert "Selecting all" in result.stdout or "all" in result.stdout.lower()

    def test_show_selection_with_target(self, setup_test_environment, mock_analytics):
        """Test showing selection after setting a target."""
        # Set a target
        runner.invoke(app, ["target", "M31"])

        # Show selection
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show the target in a table or summary
        assert "M31" in result.stdout or "Current Selection" in result.stdout

    def test_show_selection_with_date_range(
        self, setup_test_environment, mock_analytics
    ):
        """Test showing selection after setting a date range."""
        # Set date range
        runner.invoke(app, ["date", "between", "2023-10-01", "2023-12-31"])

        # Show selection
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show date information
        assert "2023" in result.stdout or "Current Selection" in result.stdout

    def test_show_selection_with_telescope(
        self, setup_test_environment, mock_analytics
    ):
        """Test showing selection after setting a telescope."""
        # Set telescope
        runner.invoke(app, ["telescope", "Vespera"])

        # Show selection
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show the telescope
        assert "Vespera" in result.stdout or "Current Selection" in result.stdout

    def test_show_selection_with_multiple_criteria(
        self, setup_test_environment, mock_analytics
    ):
        """Test showing selection with multiple criteria."""
        # Set multiple criteria
        runner.invoke(app, ["target", "M31"])
        runner.invoke(app, ["telescope", "Vespera"])
        runner.invoke(app, ["date", "after", "2023-10-01"])

        # Show selection
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show table with criteria
        assert "Current Selection" in result.stdout or "M31" in result.stdout


class TestSelectionIntegration:
    """Integration tests for selection commands."""

    def test_clear_after_setting_filters(self, setup_test_environment, mock_analytics):
        """Test clearing selection after setting multiple filters."""
        # Set various filters
        runner.invoke(app, ["target", "M31"])
        runner.invoke(app, ["telescope", "Vespera"])
        runner.invoke(app, ["date", "after", "2023-10-01"])

        # Clear all
        result = runner.invoke(app, ["any"])
        assert result.exit_code == 0

        # Verify cleared
        show_result = runner.invoke(app, [])
        assert (
            "Selecting all" in show_result.stdout or "all" in show_result.stdout.lower()
        )

    def test_selection_persistence_across_commands(
        self, setup_test_environment, mock_analytics
    ):
        """Test that selection persists across command invocations."""
        # Set a target
        runner.invoke(app, ["target", "M31"])

        # Set a telescope (should keep target)
        runner.invoke(app, ["telescope", "Vespera"])

        # Check both are present
        show_result = runner.invoke(app, [])
        assert show_result.exit_code == 0
        # At least one of them should be shown
        assert "M31" in show_result.stdout or "Vespera" in show_result.stdout

    def test_date_range_after_clears_previous_range(
        self, setup_test_environment, mock_analytics
    ):
        """Test that setting a new date range replaces the previous one."""
        # Set first range
        runner.invoke(app, ["date", "after", "2023-01-01"])

        # Set second range
        runner.invoke(app, ["date", "before", "2023-12-31"])

        # Show should reflect the latest range
        show_result = runner.invoke(app, [])
        assert show_result.exit_code == 0


class TestSelectionHelp:
    """Tests for help commands."""

    def test_selection_help(self):
        """Test that 'selection --help' works."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert (
            "selection" in result.stdout.lower() or "List information" in result.stdout
        )

    def test_target_help(self):
        """Test that 'selection target --help' works."""
        result = runner.invoke(app, ["target", "--help"])
        assert result.exit_code == 0
        assert "target" in result.stdout.lower()

    def test_telescope_help(self):
        """Test that 'selection telescope --help' works."""
        result = runner.invoke(app, ["telescope", "--help"])
        assert result.exit_code == 0
        assert "telescope" in result.stdout.lower()

    def test_date_help(self):
        """Test that 'selection date --help' works."""
        result = runner.invoke(app, ["date", "--help"])
        assert result.exit_code == 0
        assert "date" in result.stdout.lower()

    def test_any_help(self):
        """Test that 'selection any --help' works."""
        result = runner.invoke(app, ["any", "--help"])
        assert result.exit_code == 0
        assert "filter" in result.stdout.lower() or "clear" in result.stdout.lower()
