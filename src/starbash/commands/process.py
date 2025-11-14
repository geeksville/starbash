"""Processing commands for automated image processing workflows."""

from pathlib import Path
from typing import Annotated

import rich
import typer

from starbash.app import Starbash, copy_images_to_dir
from starbash.commands.__init__ import (
    TABLE_COLUMN_STYLE,
    TABLE_HEADER_STYLE,
)
from starbash.commands.select import selection_by_number
from starbash.database import SessionRow
from starbash.processing import Processing, ProcessingResult

app = typer.Typer()


@app.command()
def siril(
    session_num: Annotated[
        int,
        typer.Argument(help="Session number to process (from 'select list' output)"),
    ],
    destdir: Annotated[
        str,
        typer.Argument(help="Destination directory for Siril directory tree and processing"),
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
        from starbash import console

        console.print(
            f"[yellow]Processing session {session_num} for Siril in {destdir}...[/yellow]"
        )

        # Determine output directory
        output_dir = Path(destdir)

        # Get the selected session (convert from 1-based to 0-based index)
        session = selection_by_number(sb, session_num)

        # Get images for this session

        def session_to_dir(src_session: SessionRow, subdir_name: str):
            """Copy the images from the specified session to the subdir"""
            img_dir = output_dir / subdir_name
            img_dir.mkdir(parents=True, exist_ok=True)
            images = sb.get_session_images(src_session)
            copy_images_to_dir(images, img_dir)

        # FIXME - pull this dirname from preferences
        lights = "lights"
        session_to_dir(session, lights)

        extras = [
            # FIXME search for BIAS/DARK/FLAT etc... using multiple canonical names
            ("bias", "biases"),
            ("dark", "darks"),
            ("flat", "flats"),
        ]
        for typ, subdir in extras:
            candidates = sb.guess_sessions(session, typ)
            if not candidates:
                console.print(
                    f"[yellow]No candidate sessions found for {typ} calibration frames.[/yellow]"
                )
            else:
                session_to_dir(candidates[0].candidate, subdir)

        # FIXME put an starbash.toml repo file in output_dir (with info about what we picked/why)
        # to allow users to override/reprocess with the same settings.
        # Also FIXME, check for the existence of such a file


def print_results(
    title: str, results: list[ProcessingResult], console: rich.console.Console
) -> None:
    """Print processing results in a formatted table.

    Args:
        title: Title to display above the table
        results: List of ProcessingResult objects to display
        console: Rich console instance for output
    """
    from rich.table import Table

    if not results:
        console.print(f"[yellow]{title}: No results to display[/yellow]")
        return

    table = Table(title=title, show_header=True, header_style=TABLE_HEADER_STYLE)
    table.add_column("Target", style=TABLE_COLUMN_STYLE, no_wrap=True)
    table.add_column("Sessions", justify="right", style=TABLE_COLUMN_STYLE)
    table.add_column("Status", justify="center", style=TABLE_COLUMN_STYLE)
    table.add_column("Notes", style=TABLE_COLUMN_STYLE)

    for result in results:
        # Format status with color
        if result.success is True:
            status = "[green]✓ Success[/green]"
        elif result.success is False:
            status = "[red]✗ Failed[/red]"
        else:
            status = "[yellow]⊘ Skipped[/yellow]"

        # Format session count
        session_count = str(len(result.sessions))

        # Format notes (truncate if too long)
        notes = result.notes or ""

        table.add_row(result.target, session_count, status, notes)

    console.print(table)


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
        with Processing(sb) as proc:
            from starbash import console

            if session_num is not None:
                console.print(f"[yellow]Auto-processing session {session_num}...[/yellow]")
            else:
                console.print("[yellow]Auto-processing all selected sessions...[/yellow]")

            results = proc.run_all_stages()

            print_results("Autoprocessed", results, console)


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
        with Processing(sb) as proc:
            from starbash import console

            console.print("[yellow]Generating master frames...[/yellow]")
            results = proc.run_master_stages()

            print_results("Generated masters", results, console)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Process images using automated workflows.

    These commands handle calibration, registration, stacking, and
    post-processing of astrophotography sessions.
    """
    if ctx.invoked_subcommand is None:
        from starbash import console

        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()
