"""The optional PySide6 desktop GUI for Starbash (``sb gui``).

Everything underneath this package imports PySide6, which is an *optional*
dependency installed via the ``gui`` extra.  Callers must therefore import this
package lazily (from inside the command) and be ready to handle
:class:`GuiUnavailableError` when Qt is not installed.
"""

from __future__ import annotations

__all__ = [
    "GuiUnavailableError",
    "QTSIDE6_IMPORT_HINT",
    "qt_available",
    "run_gui",
]

#: Friendly, copy-pasteable instructions shown when PySide6 is missing.
QTSIDE6_IMPORT_HINT = (
    "The Starbash desktop GUI needs PySide6, which is an optional dependency.\n"
    "Install it with one of:\n"
    "  pipx install --force 'starbash[gui]'\n"
    "  pip install 'starbash[gui]'\n"
    "  poetry install -E gui        (when working from a git checkout)"
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
