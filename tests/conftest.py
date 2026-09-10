"""Shared fixtures for all tests (unit and integration)."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from starbash import doit_types, paths

# Qt tests (marked `gui`) must never need a display.  Set this before any
# QApplication is created so `pytest -m gui` works on headless CI runners.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: What to tell the user when Qt's shared libraries cannot be loaded.  On Linux the
#: wheel links against OS packages it does not ship; on macOS/Windows Qt is bundled,
#: so a load failure there means a broken install.
_QT_SYSTEM_LIBRARY_HINTS = {
    "linux": (
        "These are OS packages, not pip packages:\n"
        "    Debian/Ubuntu: sudo apt-get install -y libegl1 libgl1 libxcb-cursor0 "
        "libxkbcommon-x11-0 libdbus-1-3 libfontconfig1\n"
        "    Fedora/RHEL:   sudo dnf install mesa-libEGL libglvnd-glx libxkbcommon-x11 "
        "libxcb dbus-libs fontconfig\n"
        "    Arch:          sudo pacman -S libgl libxcb libxkbcommon dbus fontconfig"
    ),
    "darwin": (
        "Qt ships inside the PySide6 wheel on macOS, so this looks like a broken\n"
        "install:\n"
        "    poetry install --with dev"
    ),
    "win32": (
        "Qt ships inside the PySide6 wheel on Windows, so this looks like a broken\n"
        "install:\n"
        "    poetry install --with dev"
    ),
}


def _qt_import_failure_hint(error: ImportError) -> str:
    """Explain an ``import PySide6.QtGui`` failure in terms the user can act on."""
    message = str(error)
    looks_like_missing_library = ".so" in message or "cannot open shared object" in message

    if not looks_like_missing_library:
        return (
            f"PySide6 is installed but cannot be imported ({message}).\n"
            "Reinstall the development dependencies:\n"
            "    poetry install --with dev"
        )

    platform_hint = _QT_SYSTEM_LIBRARY_HINTS.get(sys.platform, "")
    return (
        f"PySide6 is installed, but Qt cannot load its system libraries ({message}).\n"
        f"{platform_hint}\n"
        "Why this matters even for non-GUI tests: pytest-qt imports QtGui while\n"
        "pytest is still configuring, so a missing library aborts the whole run\n"
        "(INTERNALERROR) before any test is collected."
    )


def _fail_early_if_qt_cannot_load() -> None:
    """Turn Qt's "missing system library" crash into an actionable message.

    This conftest is imported before pytest-qt's ``pytest_configure`` hook runs, so
    raising here replaces that opaque INTERNALERROR traceback with the fix.
    """
    try:
        import PySide6.QtGui  # noqa: F401
    except ImportError as error:
        raise pytest.UsageError(_qt_import_failure_hint(error)) from error


if os.environ.get("STARBASH_SKIP_QT_LOAD_CHECK") != "1":
    _fail_early_if_qt_cannot_load()


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


@pytest.fixture(scope="session", autouse=True)
def force_no_gui_for_all_tests():
    """Force all tests to run without GUI windows.

    This session-scoped autouse fixture runs once at the beginning of the test session
    and ensures that external tools (Siril, GraXpert, etc.) will not attempt to open
    GUI windows during testing. This is essential for headless CI environments.
    """
    from starbash.tool import base

    # Save original value
    original_value = base.force_no_gui

    # Force no GUI for all tests
    base.force_no_gui = True

    yield

    # Restore original value after all tests complete
    base.force_no_gui = original_value


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
    from starbash.dwarf3 import _reset_monotonic_datetime

    # Reset dwarf3 monotonic counter to prevent test pollution
    _reset_monotonic_datetime()

    # Save original global state
    original_verbose = starbash.verbose_output
    original_force_regen = starbash.force_regen
    original_log_level = starbash.log_filter_level
    original_max_contexts = doit_types.max_contexts

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    documents_dir = tmp_path / "documents"
    state_dir = tmp_path / "state"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    documents_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    # Set the override directories for this test (including cache_dir and documents_dir to prevent writing to real user directories)
    paths.set_test_directories(
        config_dir,
        data_dir,
        cache_dir_override=cache_dir,
        documents_dir_override=documents_dir,
        state_dir_override=state_dir,
    )

    yield {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "documents_dir": documents_dir,
        "state_dir": state_dir,
        "tmp_path": tmp_path,
    }

    # Clean up: reset to None after test
    paths.set_test_directories(None, None, None, None, None)

    # Restore original global state to prevent test pollution
    starbash.verbose_output = original_verbose
    starbash.force_regen = original_force_regen
    starbash.log_filter_level = original_log_level
    doit_types.max_contexts = original_max_contexts


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
