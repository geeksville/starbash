"""Launch the optional desktop GUI (``sb gui``)."""

from __future__ import annotations

import typer

__all__ = ["gui"]


def gui() -> None:
    """Launch the Starbash desktop GUI.

    The GUI needs PySide6, which ships in the optional ``gui`` extra:

        pipx install --force 'starbash[gui]'
        poetry install -E gui        # from a source checkout
    """
    from starbash import console
    from starbash.ui.qt import GuiUnavailableError, run_gui

    try:
        run_gui()
    except GuiUnavailableError as exc:
        # PySide6 is not installed: explain how to fix it rather than traceback.
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
