"""Shared fixtures for integration tests.

Note: Common fixtures like setup_test_environment and mock_analytics
are defined in tests/conftest.py and shared across all tests.
This file contains only integration-specific fixtures.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def test_data_dir():
    """Provide path to test data directory.

    Checks if /test-data exists and skips tests if not available.
    This is a session-scoped fixture since the test data location doesn't change.
    """
    test_data_path = Path("/test-data")

    if not test_data_path.exists():
        pytest.skip(
            "Integration tests require /test-data directory. "
            "See tests/integration/README.md for setup instructions."
        )

    return test_data_path
