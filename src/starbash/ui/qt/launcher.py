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


def main(argv: list[str] | None = None) -> None:
    """Launch the GUI when bare, or dispatch supplied arguments to the CLI."""
    _configure_windows_console()
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        from starbash.main import app

        app(args=arguments, prog_name="starbash")
        return
    raise SystemExit(run_gui())


if __name__ == "__main__":
    main()
