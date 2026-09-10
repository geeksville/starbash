"""Launch the desktop GUI (``sb gui``)."""

from __future__ import annotations

import typer

__all__ = ["gui"]


def gui() -> None:
    """Launch the Starbash desktop GUI.

    PySide6 is a normal dependency, so this normally just works.  If it cannot be
    imported the installation is incomplete or broken, and we say so plainly
    rather than dumping an ``ImportError`` traceback.
    """
    from starbash import console
    from starbash.ui.qt import GuiUnavailableError, run_gui

    try:
        run_gui()
    except GuiUnavailableError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
