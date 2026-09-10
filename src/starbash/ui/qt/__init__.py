"""The PySide6 desktop GUI for Starbash (``sb gui``).

PySide6 is a normal dependency of Starbash — the GUI is a first-class way to drive
the app, and users who prefer the CLI simply never open it.  Imports here are still
kept lazy so a plain CLI run never pays for loading Qt.

Callers should therefore import this package lazily (from inside the command) and
handle :class:`GuiUnavailableError`, which means the local install is broken rather
than that an optional feature is missing.
"""

from __future__ import annotations

__all__ = [
    "GuiUnavailableError",
    "QTSIDE6_IMPORT_HINT",
    "qt_available",
    "run_gui",
]

#: Shown when PySide6 cannot be imported, i.e. the installation is incomplete.
QTSIDE6_IMPORT_HINT = (
    "The Starbash GUI could not load PySide6. PySide6 is a normal dependency of\n"
    "starbash, so this usually means the installation is incomplete or broken.\n"
    "Reinstall it with one of:\n"
    "  pipx install --force starbash\n"
    "  pip install --force-reinstall starbash\n"
    "  poetry install --with dev        (when working from a git checkout)"
)


class GuiUnavailableError(RuntimeError):
    """Raised when the GUI is requested but PySide6 is not installed."""


def qt_available() -> bool:
    """Return ``True`` if PySide6 can be imported in this environment."""
    try:
        import PySide6.QtWidgets  # noqa: F401  (import is the point)
    except ImportError:
        return False
    return True


def run_gui(argv: list[str] | None = None) -> int:
    """Launch the desktop GUI and return Qt's process exit code.

    Raises:
        GuiUnavailableError: if PySide6 is not installed.
    """
    if not qt_available():
        raise GuiUnavailableError(QTSIDE6_IMPORT_HINT)

    # Imported here (not at module import time) so `import starbash.ui.qt` itself
    # never hard-requires Qt.
    from starbash.ui.qt.app import run

    return run(argv)
