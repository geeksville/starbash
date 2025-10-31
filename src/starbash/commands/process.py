"""Processing commands for automated image processing workflows."""

import typer
from pathlib import Path
from typing_extensions import Annotated

from starbash.app import Starbash
from starbash import console

app = typer.Typer()


@app.command()
def siril(
    session_num: Annotated[
        int,
        typer.Argument(help="Session number to process (from 'select list' output)"),
    ],
    destdir: Annotated[
        str,
        typer.Argument(
            help="Destination directory for Siril directory tree and processing"
        ),
    ],
    run: Annotated[
        bool,
        typer.Option(
            "--run",
            help="Automatically launch Siril GUI after generating directory tree",
        ),
    ] = False,
):
    """Generate Siril directory tree and optionally run Siril GUI.

    Creates a properly structured directory tree for Siril processing with
    biases/, darks/, flats/, and lights/ subdirectories populated with the
    session's images (via symlinks when possible).

    If --run is specified, launches the Siril GUI with the generated directory
    structure loaded and ready for processing.
    """
    with Starbash("process.siril") as sb:
        console.print(
            f"[yellow]Processing session {session_num} with Siril to {destdir}...[/yellow]"
        )
        console.print(
            "[red]Not yet implemented - see https://github.com/geeksville/starbash/issues[/red]"
        )
        raise typer.Exit(1)


@app.command()
def auto(
    session_num: Annotated[
        int | None,
        typer.Argument(
            help="Session number to process. If not specified, processes all selected sessions."
        ),
    ] = None,
):
    """Automatic processing with sensible defaults.

    If session number is specified, processes only that session.
    Otherwise, all currently selected sessions will be processed automatically
    using the configured recipes and default settings.

    This command handles:
    - Automatic master frame selection (bias, dark, flat)
    - Calibration of light frames
    - Registration and stacking
    - Basic post-processing

    The output will be saved according to the configured recipes.
    """
    with Starbash("process.auto") as sb:
        if session_num is not None:
            console.print(f"[yellow]Auto-processing session {session_num}...[/yellow]")
        else:
            console.print("[yellow]Auto-processing all selected sessions...[/yellow]")

        console.print(
            "[red]Not yet implemented - see https://github.com/geeksville/starbash/issues[/red]"
        )
        raise typer.Exit(1)


@app.command()
def masters():
    """Generate master flats, darks, and biases from selected raw frames.

    Analyzes the current selection to find all available calibration frames
    (BIAS, DARK, FLAT) and automatically generates master calibration frames
    using stacking recipes.

    Generated master frames are stored in the configured masters directory
    and will be automatically used for future processing operations.
    """
    with Starbash("process.masters") as sb:
        console.print(
            "[yellow]Generating master frames from current selection...[/yellow]"
        )
        console.print(
            "[red]Not yet implemented - see https://github.com/geeksville/starbash/issues[/red]"
        )
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Process images using automated workflows.

    These commands handle calibration, registration, stacking, and
    post-processing of astrophotography sessions.
    """
    if ctx.invoked_subcommand is None:
        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()
