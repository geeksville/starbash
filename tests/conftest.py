"""Shared fixtures for tests."""

from unittest.mock import patch

import pytest

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
    with (
        patch("starbash.app.analytics_setup") as mock_setup,
        patch("starbash.app.analytics_shutdown") as mock_shutdown,
        patch("starbash.app.analytics_start_transaction") as mock_transaction,
        patch("starbash.app.analytics_exception") as mock_exception,
    ):
        yield {
            "setup": mock_setup,
            "shutdown": mock_shutdown,
            "transaction": mock_transaction,
            "exception": mock_exception,
        }
