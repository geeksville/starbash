"""PyInstaller entry point for the standalone Starbash desktop application."""

from __future__ import annotations

import sys

from starbash.ui.qt import run_gui


def _configure_windows_console() -> None:
    """Prevent diagnostic console logs from failing on legacy Windows code pages."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main() -> None:
    """Start the desktop application and return Qt's exit status to Windows."""
    _configure_windows_console()
    raise SystemExit(run_gui())


if __name__ == "__main__":
    main()
