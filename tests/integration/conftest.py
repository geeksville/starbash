"""Shared fixtures for integration tests.

Note: Common fixtures like setup_test_environment and mock_analytics
are defined in tests/conftest.py and shared across all tests.
This file contains only integration-specific fixtures.

IMPORTANT: Integration tests must run sequentially (not in parallel) because
they build upon each other's state. Always use: pytest -m integration -n 0
"""

import logging
import os
from pathlib import Path

import pytest

from starbash import doit


@pytest.fixture(scope="session", autouse=True)
def limit_max_contexts():
    """Override max_contexts to 1 for integration tests to reduce disk space usage.

    This fixture automatically runs for all integration tests and saves/restores
    the original max_contexts value after tests complete.
    """
    original_max_contexts = doit.max_contexts
    doit.max_contexts = 1

    yield

    # Restore original value
    doit.max_contexts = original_max_contexts


@pytest.fixture(scope="session", autouse=True)
def setup_integration_logging():
    """Configure logging for integration tests to write to /tmp/integration-logout.txt.

    This fixture runs automatically for all integration tests (autouse=True) and
    captures all log messages at DEBUG level and higher to a file.
    """
    log_file = Path("/tmp/sb-integration-log.txt")

    # Create a file handler for the log file
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    # Create a formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    # Get the root logger and add our handler
    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    # Also ensure starbash logger is at DEBUG level
    starbash_logger = logging.getLogger("starbash")
    starbash_logger.setLevel(logging.DEBUG)

    yield

    # Clean up: remove the handler and restore original level
    root_logger.removeHandler(file_handler)
    root_logger.setLevel(original_level)
    file_handler.close()


@pytest.fixture(scope="session")
def test_data_dir():
    """Provide path to test data directory.

    Checks if /test-data exists and skips tests if not available.
    Also checks if integration tests are being run in parallel and fails if so.
    This is a session-scoped fixture since the test data location doesn't change.
    """
    # Check for parallel execution (only runs when integration tests are actually executed)
    if "PYTEST_XDIST_WORKER" in os.environ:
        pytest.fail(
            "\n\n"
            "❌ ERROR: Integration tests cannot run in parallel!\n"
            "Integration tests build upon each other's state and must run sequentially.\n"
            "\n"
            "Please use: pytest -m integration -n 0\n"
            "\n"
            "The -n 0 flag disables parallel execution.\n",
            pytrace=False,
        )

    test_data_path = Path("/test-data")

    if not test_data_path.exists():
        pytest.skip(
            "Integration tests require /test-data directory. "
            "See tests/integration/README.md for setup instructions."
        )

    return test_data_path
