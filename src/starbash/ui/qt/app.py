"""Bootstrap and run the Qt application.

Kept separate from :mod:`starbash.ui.qt.__init__` so importing the package never
requires a display or a ``QApplication``.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from starbash.app import Starbash
from starbash.interaction import set_interaction
from starbash.ui.qt.desktop import DESKTOP_FILE_NAME, install_desktop_entry
from starbash.ui.qt.interaction import QtUserInteraction
from starbash.ui.qt.main_window import MainWindow
from starbash.ui.qt.theme import apply_theme, load_app_icon

logger = logging.getLogger(__name__)

__all__ = ["create_application", "run"]

APP_NAME = "Starbash"
ORG_NAME = "Starbash"


def create_application(argv: list[str] | None = None) -> QApplication:
    """Return the process-wide ``QApplication``, creating it if needed."""
    app = cast("QApplication | None", QApplication.instance())
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    apply_theme(app)
    # Shows in the title bar / task switcher; a null icon simply means no icon.
    app.setWindowIcon(load_app_icon())
    # Lets the window join our installed .desktop entry (Wayland app id / WM_CLASS).
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    return app


def run(argv: list[str] | None = None) -> int:
    """Create the window, install the Qt interaction backend, and run the loop.

    Returns:
        The Qt event loop's exit code.
    """
    app = create_application(argv)
    # Best-effort Linux integration so launchers/docks show the name and icon.
    install_desktop_entry()

    sb = Starbash("gui")

    window = MainWindow(sb)
    # From here on, guided commands running inside the GUI prompt with dialogs
    # instead of reading stdin.  Restored on exit so nothing leaks between runs.
    set_interaction(QtUserInteraction(window))
    window.show()

    try:
        return app.exec()
    finally:
        set_interaction(None)
