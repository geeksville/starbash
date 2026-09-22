"""PyInstaller entry point for the standalone Starbash desktop application."""

from __future__ import annotations

from starbash.ui.qt import run_gui


def main() -> None:
    """Start the desktop application and return Qt's exit status to Windows."""
    raise SystemExit(run_gui())


if __name__ == "__main__":
    main()
