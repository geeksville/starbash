"""Shared fixtures for all tests (unit and integration)."""

from unittest.mock import MagicMock, patch

import pytest

from starbash import paths


@pytest.fixture
def setup_test_environment(tmp_path):
    """Setup a test environment with isolated config and data directories.

    This fixture is used by both unit and integration tests to provide
    isolated temporary directories for config and data, preventing tests
    from interfering with real user data or with each other.
    """
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
    """Mock analytics functions to avoid Sentry calls during testing.

    This fixture mocks all analytics-related functions to prevent external
    calls to Sentry during test execution. It provides a complete mock context
    that behaves like the real analytics context manager.
    """
    with (
        patch("starbash.app.analytics_setup") as mock_setup,
        patch("starbash.app.analytics_shutdown") as mock_shutdown,
        patch("starbash.app.analytics_start_transaction") as mock_transaction,
        patch("starbash.app.analytics_exception") as mock_exception,
    ):
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
