"""Shared fixtures for all tests (unit and integration)."""

from unittest.mock import MagicMock, patch

import pytest

from starbash import paths


@pytest.fixture(scope="session", autouse=True)
def force_local_recipes_for_all_tests():
    """Force all tests to use local recipe submodule instead of remote recipes.

    This session-scoped autouse fixture runs once at the beginning of the test session
    and ensures that all Starbash instances created during testing will use the local
    starbash-recipes submodule rather than fetching recipes from GitHub.
    """
    from starbash import app

    # Save original value
    original_value = app.force_local_recipes

    # Force use of local recipes for all tests
    app.force_local_recipes = True

    yield

    # Restore original value after all tests complete
    app.force_local_recipes = original_value


@pytest.fixture
def setup_test_environment(tmp_path):
    """Setup a test environment with isolated config and data directories.

    This fixture is used by both unit and integration tests to provide
    isolated temporary directories for config and data, preventing tests
    from interfering with real user data or with each other.

    Also saves and restores global starbash state variables
    (verbose_output, force_regen, log_filter_level) to prevent test pollution.
    """
    import starbash

    # Save original global state
    original_verbose = starbash.verbose_output
    original_force_regen = starbash.force_regen
    original_log_level = starbash.log_filter_level

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    documents_dir = tmp_path / "documents"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    documents_dir.mkdir(parents=True, exist_ok=True)

    # Set the override directories for this test (including cache_dir and documents_dir to prevent writing to real user directories)
    paths.set_test_directories(
        config_dir, data_dir, cache_dir_override=cache_dir, documents_dir_override=documents_dir
    )

    yield {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "documents_dir": documents_dir,
        "tmp_path": tmp_path,
    }

    # Clean up: reset to None after test
    paths.set_test_directories(None, None, None, None)

    # Restore original global state to prevent test pollution
    starbash.verbose_output = original_verbose
    starbash.force_regen = original_force_regen
    starbash.log_filter_level = original_log_level


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
