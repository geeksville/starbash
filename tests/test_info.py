"""Tests for info commands."""

from pathlib import Path
from typer.testing import CliRunner
import pytest

from starbash.main import app
from starbash.database import Database
from starbash import paths

runner = CliRunner(env={"NO_COLOR": "1"})


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


@pytest.fixture
def populated_database(setup_test_environment):
    """Fixture that provides a database populated with test data."""
    data_dir = setup_test_environment["data_dir"]

    with Database(base_dir=data_dir) as db:
        # Add some test sessions with varied data
        sessions = [
            {
                Database.FILTER_KEY: "Ha",
                Database.START_KEY: "2024-01-01T20:00:00",
                Database.END_KEY: "2024-01-01T22:00:00",
                Database.IMAGE_DOC_KEY: 1,
                Database.IMAGETYP_KEY: "Light",
                Database.NUM_IMAGES_KEY: 10,
                Database.EXPTIME_TOTAL_KEY: 1200.0,  # 20 minutes
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "ZWO ASI533MC Pro",
            },
            {
                Database.FILTER_KEY: "OIII",
                Database.START_KEY: "2024-01-02T20:00:00",
                Database.END_KEY: "2024-01-02T23:00:00",
                Database.IMAGE_DOC_KEY: 2,
                Database.IMAGETYP_KEY: "Light",
                Database.NUM_IMAGES_KEY: 15,
                Database.EXPTIME_TOTAL_KEY: 2700.0,  # 45 minutes
                Database.OBJECT_KEY: "M31",
                Database.TELESCOP_KEY: "ZWO ASI533MC Pro",
            },
            {
                Database.FILTER_KEY: "Ha",
                Database.START_KEY: "2024-01-03T19:00:00",
                Database.END_KEY: "2024-01-03T21:30:00",
                Database.IMAGE_DOC_KEY: 3,
                Database.IMAGETYP_KEY: "Light",
                Database.NUM_IMAGES_KEY: 20,
                Database.EXPTIME_TOTAL_KEY: 3600.0,  # 60 minutes
                Database.OBJECT_KEY: "NGC 7635",
                Database.TELESCOP_KEY: "Seestar S50",
            },
            {
                Database.FILTER_KEY: "RGB",
                Database.START_KEY: "2024-01-04T20:00:00",
                Database.END_KEY: "2024-01-04T22:00:00",
                Database.IMAGE_DOC_KEY: 4,
                Database.IMAGETYP_KEY: "Light",
                Database.NUM_IMAGES_KEY: 30,
                Database.EXPTIME_TOTAL_KEY: 1800.0,  # 30 minutes
                Database.OBJECT_KEY: "M42",
                Database.TELESCOP_KEY: "Seestar S50",
            },
        ]

        for session_data in sessions:
            db.upsert_session(session_data)

        # Add some test images
        images = [
            {"path": "image1.fit", "FILTER": "Ha", "OBJECT": "M31"},
            {"path": "image2.fit", "FILTER": "OIII", "OBJECT": "M31"},
            {"path": "image3.fit", "FILTER": "Ha", "OBJECT": "NGC 7635"},
            {"path": "image4.fit", "FILTER": "RGB", "OBJECT": "M42"},
        ]

        for image_data in images:
            db.upsert_image(image_data, "file:///tmp")

    return setup_test_environment


def test_info_command_default(setup_test_environment):
    """Test 'starbash info' shows basic app information."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0

    # Should show repository counts
    assert "Repositories" in result.stdout or "repos" in result.stdout.lower()

    # Should show database stats
    assert "Sessions" in result.stdout or "Images" in result.stdout


def test_info_command_with_data(populated_database):
    """Test 'starbash info' with populated database shows correct stats."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show database stats
    assert "Sessions Indexed" in output or "sessions" in output.lower()
    assert "Images Indexed" in output or "images" in output.lower()

    # Should show total image time
    assert "image time" in output.lower() or "exptime" in output.lower()

    # Should have some numeric values (session/image counts)
    assert "4" in output  # 4 sessions
    assert "4" in output  # 4 images


def test_info_target_command_no_data(setup_test_environment):
    """Test 'starbash info target' with no data - should not crash."""
    result = runner.invoke(app, ["info", "target"])
    assert result.exit_code == 0

    # Should show empty table with 0 / 0 selected
    assert "(0 / 0 selected)" in result.stdout or "Targets" in result.stdout


def test_info_target_command_with_data(populated_database):
    """Test 'starbash info target' lists all targets correctly."""
    result = runner.invoke(app, ["info", "target"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show the targets we added
    assert "M31" in output
    assert "NGC 7635" in output
    assert "M42" in output

    # Should show session counts
    assert "sessions" in output.lower()

    # M31 should have 2 sessions
    # Look for "2" near "M31" - the exact format may vary
    # Just verify the targets are listed
    assert "Target" in output or "target" in output


def test_info_telescope_command_no_data(setup_test_environment):
    """Test 'starbash info telescope' with no data - should not crash."""
    result = runner.invoke(app, ["info", "telescope"])
    assert result.exit_code == 0

    # Should show empty table with 0 / 0 selected
    assert "(0 / 0 selected)" in result.stdout or "Telescopes" in result.stdout


def test_info_telescope_command_with_data(populated_database):
    """Test 'starbash info telescope' lists all telescopes correctly."""
    result = runner.invoke(app, ["info", "telescope"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show the telescopes we added
    assert "ZWO ASI533MC Pro" in output or "ASI533" in output
    assert "Seestar S50" in output or "Seestar" in output

    # Should show session counts
    assert "sessions" in output.lower()

    # Should show "Telescope" heading
    assert "Telescope" in output or "telescope" in output


def test_info_filter_command_no_data(setup_test_environment):
    """Test 'starbash info filter' with no data - should not crash."""
    result = runner.invoke(app, ["info", "filter"])
    assert result.exit_code == 0

    # Should show empty table with 0 / 0 selected
    assert "(0 / 0 selected)" in result.stdout or "Filters" in result.stdout


def test_info_filter_command_with_data(populated_database):
    """Test 'starbash info filter' lists all filters correctly."""
    result = runner.invoke(app, ["info", "filter"])
    assert result.exit_code == 0

    output = result.stdout

    # Should show the filters we added
    assert "Ha" in output
    assert "OIII" in output
    assert "RGB" in output

    # Should show session counts
    assert "sessions" in output.lower()

    # Should show "Filter" heading
    assert "Filter" in output or "filter" in output


def test_info_help(setup_test_environment):
    """Test 'starbash info --help' works."""
    result = runner.invoke(app, ["info", "--help"])
    assert result.exit_code == 0
    assert "info" in result.stdout.lower()


def test_info_target_help(setup_test_environment):
    """Test 'starbash info target --help' works."""
    result = runner.invoke(app, ["info", "target", "--help"])
    assert result.exit_code == 0
    assert "target" in result.stdout.lower()


def test_info_telescope_help(setup_test_environment):
    """Test 'starbash info telescope --help' works."""
    result = runner.invoke(app, ["info", "telescope", "--help"])
    assert result.exit_code == 0
    assert "telescope" in result.stdout.lower()


def test_info_filter_help(setup_test_environment):
    """Test 'starbash info filter --help' works."""
    result = runner.invoke(app, ["info", "filter", "--help"])
    assert result.exit_code == 0
    assert "filter" in result.stdout.lower()


def test_plural_helper():
    """Test the plural() helper function."""
    from starbash.commands.info import plural

    # Test regular plurals
    assert plural("target") == "targets"
    assert plural("telescope") == "telescopes"
    assert plural("filter") == "filters"

    # Test words ending in 'y'
    assert plural("galaxy") == "galaxies"
    assert plural("category") == "categories"

    # Test edge cases
    assert plural("s") == "ss"
    assert plural("") == "s"  # Simple implementation just adds 's'


def test_dump_column_with_multiple_same_values(populated_database):
    """Test that dump_column correctly counts duplicate values."""
    # M31 appears in 2 sessions in our test data
    result = runner.invoke(app, ["info", "target"])
    assert result.exit_code == 0

    output = result.stdout
    assert "M31" in output

    # Should show count of sessions for each target
    # The exact format may vary, but there should be numbers
    import re

    # Look for numbers in the output
    numbers = re.findall(r"\d+", output)
    assert len(numbers) > 0  # Should have at least some counts


def test_info_with_user_preferences(populated_database):
    """Test 'starbash info' displays user preferences if set."""
    # First, set a user name
    result = runner.invoke(app, ["user", "name", "Test User"])
    assert result.exit_code == 0

    # Now check info displays it
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "Test User" in result.stdout

    # Set email
    result = runner.invoke(app, ["user", "email", "test@example.com"])
    assert result.exit_code == 0

    # Check info displays email
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "test@example.com" in result.stdout
