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
from starbash.doit import FileInfo
from starbash.paths import get_user_config_path
from starbash.processed_target import ProcessedTarget
from starbash.processing import Processing, ProcessingResult
from starbash.rich import to_rich_link

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
    title: str,
    results: list[ProcessingResult],
    console: rich.console.Console,
    skip_boring: bool = True,
) -> None:
    """Print processing results in a formatted table.

    Args:
        title: Title to display above the table
        results: List of ProcessingResult objects to display
        console: Rich console instance for output
    """
    from rich.table import Table

    if not results:
        console.print(
            f"[yellow]{title}: No results, do you have a target selected?  If this is your first time here run 'sb user setup'[/yellow]"
        )
        return

    table = Table(title=title, show_header=True, header_style=TABLE_HEADER_STYLE)
    table.add_column("Target", style=TABLE_COLUMN_STYLE, no_wrap=True)
    table.add_column("Session", justify="right", style=TABLE_COLUMN_STYLE)
    table.add_column("Status", justify="center", style=TABLE_COLUMN_STYLE)
    table.add_column("Notes (links are clickable!)", style=TABLE_COLUMN_STYLE)

    for result in results:
        if skip_boring and result.success is None and result.is_master:
            # Skip uninteresting master processing results
            continue

        # Format status with color
        if result.success is True:
            status = f"[green]✓ {result.reason or 'Success'}[/green]"
        elif result.success is False:
            status = f"[red]✗ {result.reason or 'Failed'}[/red]"
        else:
            status = f"[yellow]Ø {result.reason or 'Skipped'}[/yellow]"

        # Format notes (truncate if too long)
        notes = ""
        meta: dict | None = result.task.meta
        if result.notes:
            notes = result.notes
            stage = meta and meta.get("stage")
            if stage:
                notes = to_rich_link(stage.source.url, notes)

        # if success or skipped, show outputs generated
        fi: FileInfo | None = result.context.get("output")
        if fi and result.success is not False:
            is_tmp_dir = fi.repo is None
            output_files_str = ", ".join(fi.rich_links)
            if is_tmp_dir:
                output_files_str = f"[dim]{output_files_str}[/dim]"

            toml_url: str | None = None
            # Try to find a toml url
            if meta:
                pt: ProcessedTarget | None = meta.get("processed_target")
                if pt and pt.repo:
                    toml_url = pt.repo.config_url

            link_arrow = to_rich_link(toml_url, "→") if toml_url else "→"

            notes += f" {link_arrow} {output_files_str}"

        output_fi: FileInfo | None = result.context.get("final_output")
        result_str = result.target  # assume we won't be able to add a link
        if output_fi and output_fi.base and result.success is not False:
            output_dir = Path(output_fi.base)
            result_str = to_rich_link(output_dir, result.target)

        # Try to link to source files if we can
        session_link = result.session_desc
        input_files: list[Path] | None = result.context.get("input_files")
        if input_files:
            first_input = input_files[0]
            session_link = to_rich_link(first_input.parent, result.session_desc)

        table.add_row(result_str, session_link, status, notes)

    console.print(table)


@app.command()
def auto(
    session_num: Annotated[
        int | None,
        typer.Argument(
            help="Session number to process. If not specified, processes all selected sessions."
        ),
    ] = None,
    no_masters: Annotated[
        bool,
        typer.Option(
            "--no-masters",
            help="Don't automatically generated master frames",
        ),
    ] = False,
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
    if no_masters:
        import starbash

        starbash.process_masters = False

    # Users might run "process auto" as their first command without reading any docs...
    if not get_user_config_path().exists():
        from starbash import console

        console.print("[red]No app setup found.[/red]  Please run 'sb user setup'.")
        raise typer.Exit(1)

    with Starbash("process.auto") as sb:
        with Processing(sb) as proc:
            from starbash import console

            if session_num is not None:
                console.print(
                    f"[read]Session number base filtering not yet implemented: {session_num}...[/red]"
                )
            else:
                console.print("[yellow]Auto-processing all selected sessions...[/yellow]")

                results = proc.run_all_stages()

                title = "Autoprocessed"

                # Try to show a likely output directory (not perfect but better than nothing)
                if len(results) > 0:
                    last = results[-1]
                    fi: FileInfo = last.context["output"]
                    if fi.repo:
                        title += f" to {fi.repo.resolve_path()}"

                print_results(title, results, console)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    add_help_option=False,
)
def doit(
    ctx: typer.Context,
):
    """(private) for developer debugging of the underlying 'doit' dependency system.

    You probably don't need to use this - unless you are a starbash developer.
    Arguments are passed directly to doit.  For more information run: sb process doit help"""
    with Starbash("process.doit") as sb:
        with Processing(sb) as proc:
            from starbash import console

            console.print("[red]This command is currently for developers only...[/red]")
            proc.doit.run(ctx.args)


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

            print_results("Generated masters", results, console, skip_boring=False)


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
