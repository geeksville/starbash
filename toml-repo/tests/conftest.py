"""Shared fixtures for toml-repo tests."""

import pytest

from toml_repo import set_config_suffix


@pytest.fixture(autouse=True)
def _reset_config_suffix():
    """Ensure each test starts with a clean config suffix and resets after."""
    # Many tests use starbash.toml as their config suffix to match test data
    # that was written for the original starbash repo module.
    set_config_suffix("starbash.toml")
    yield
    # Reset to package default
    set_config_suffix("repo.toml")
