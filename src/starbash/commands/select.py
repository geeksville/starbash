"""Selection commands for filtering sessions and targets."""

import logging
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

import starbash
from starbash import console, to_shortdate
from starbash.app import Starbash, copy_images_to_dir
from starbash.commands import (
    TABLE_COLUMN_STYLE,
    TABLE_HEADER_STYLE,
    TABLE_VALUE_STYLE,
    format_duration,
)
from starbash.database import Database, SessionRow, get_column_name

app = typer.Typer()


def get_column(sb: Starbash, column_name: str) -> Counter:
    # Also do a complete unfiltered search so we can compare for the users
    allsessions = sb.db.search_session([])

    column_name = get_column_name(column_name)
    allfound = [session[column_name] for session in allsessions if session[column_name]]

    # Count occurrences of each telescope
    all_counts = Counter(allfound)

    return all_counts


def complete_date(incomplete: str, column_name: str):
    """calls get_column() and assumes the returned str->count object has iso datetime strings as the keys
    it merges the counts for all dates that are on the same local timezone day.
    in the returned str->count, just include the date portion (YYYY-MM-DD)."""

    # We need to use stderr_logging to prevent confusing the bash completion parser
    starbash.log_filter_level = logging.ERROR  # avoid showing output while doing completion
    with Starbash("select.complete.date", stderr_logging=True) as sb:
        c = get_column(sb, column_name)

        # Merge counts by date (YYYY-MM-DD) in local timezone
        date_counts = Counter()
        for datetime_str, count in c.items():
            # Extract just the date portion (YYYY-MM-DD) from local datetime
            date_only = to_shortdate(datetime_str)
            date_counts[date_only] += count

        # Yield completions matching the incomplete input
        for date, count in sorted(date_counts.items(), reverse=True):
            if date.startswith(incomplete):
                yield (date, f"{count} sessions")


def complete_column(incomplete: str, column_name: str):
    # We need to use stderr_logging to prevent confusing the bash completion parser
    starbash.log_filter_level = logging.ERROR  # avoid showing output while doing completion
    with Starbash("repo.complete.column", stderr_logging=True) as sb:
        c = get_column(sb, column_name)

        for item, count in c.items():
            if item.lower().startswith(incomplete.lower()):
                yield (item, f"{count} sessions")


@app.command(name="any")
def clear():
    """Remove any filters on sessions, etc... (select everything)."""
    with Starbash("selection.clear") as sb:
        sb.selection.clear()
        console.print("[green]Selection cleared - now selecting all sessions[/green]")
        do_list_sessions(sb, brief=not starbash.verbose_output)


@app.command()
def target(
    target_name: Annotated[
        str,
        typer.Argument(
            help="Target name to add to the selection (e.g., 'M31', 'NGC 7000')",
            autocompletion=lambda incomplete: complete_column(incomplete, Database.OBJECT_KEY),
        ),
    ],
):
    """Limit the current selection to only the named target."""
    with Starbash("selection.target") as sb:
        # For now, replace existing targets with this one
        # In the future, we could support adding multiple targets
        sb.selection.targets = []
        sb.selection.add_target(target_name)
        console.print(f"[green]Selection limited to target: {target_name}[/green]")
        do_list_sessions(sb, brief=not starbash.verbose_output)


@app.command()
def telescope(
    telescope_name: Annotated[
        str,
        typer.Argument(
            help="Telescope name to add to the selection (e.g., 'Vespera', 'EdgeHD 8')",
            autocompletion=lambda incomplete: complete_column(incomplete, Database.TELESCOP_KEY),
        ),
    ],
):
    """Limit the current selection to only the named telescope."""
    with Starbash("selection.telescope") as sb:
        # For now, replace existing telescopes with this one
        # In the future, we could support adding multiple telescopes
        sb.selection.telescopes = []
        sb.selection.add_telescope(telescope_name)
        console.print(f"[green]Selection limited to telescope: {telescope_name}[/green]")
        do_list_sessions(sb, brief=not starbash.verbose_output)


def complete_name(incomplete: str, names: list[str]):
    """Return typer style autocompletion from a list of string constants."""
    for name in names:
        if name.startswith(incomplete):
            yield name


@app.command()
def date(
    operation: Annotated[
        str,
        typer.Argument(
            help="Date operation: 'after', 'before', or 'between'",
            autocompletion=lambda incomplete: complete_name(
                incomplete, ["after", "before", "between"]
            ),
        ),
    ],
    date_value: Annotated[
        str,
        typer.Argument(
            help="Date in ISO format (YYYY-MM-DD) or two dates separated by space for 'between'",
            autocompletion=lambda incomplete: complete_date(incomplete, Database.START_KEY),
        ),
    ],
    end_date: Annotated[
        str | None,
        typer.Argument(
            help="End date for 'between' operation (YYYY-MM-DD)",
            autocompletion=lambda incomplete: complete_date(incomplete, Database.START_KEY),
        ),
    ] = None,
):
    """Limit to sessions in the specified date range.

    Examples:
        starbash selection date after 2023-10-01
        starbash selection date before 2023-12-31
        starbash selection date between 2023-10-01 2023-12-31
    """
    with Starbash("selection.date") as sb:
        operation = operation.lower()

        if operation == "after":
            sb.selection.set_date_range(start=date_value, end=None)
            console.print(f"[green]Selection limited to sessions after {date_value}[/green]")
        elif operation == "before":
            sb.selection.set_date_range(start=None, end=date_value)
            console.print(f"[green]Selection limited to sessions before {date_value}[/green]")
        elif operation == "between":
            if not end_date:
                console.print("[red]Error: 'between' operation requires two dates[/red]")
                raise typer.Exit(1)
            sb.selection.set_date_range(start=date_value, end=end_date)
            console.print(
                f"[green]Selection limited to sessions between {date_value} and {end_date}[/green]"
            )
        else:
            console.print(
                f"[red]Error: Unknown operation '{operation}'. Use 'after', 'before', or 'between'[/red]"
            )
            raise typer.Exit(1)

        do_list_sessions(sb, brief=not starbash.verbose_output)


def do_list_sessions(sb: Starbash, brief: bool = False):
    """List sessions (filtered based on the current selection)"""

    sessions = sb.search_session()
    if sessions and isinstance(sessions, list):
        len_all = sb.db.len_table(Database.SESSIONS_TABLE)
        table = Table(
            title=f"Sessions ({len(sessions)} selected out of {len_all})",
            header_style=TABLE_HEADER_STYLE,
        )
        sb.analytics.set_data("session.num_selected", len(sessions))
        sb.analytics.set_data("session.num_total", len_all)

        table.add_column("#", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Date", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("# images", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Time", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Type/Filter", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Telescope", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column(
            "About", style=TABLE_COLUMN_STYLE, no_wrap=True
        )  # type of frames, filter, target

        total_images = 0
        total_seconds = 0.0
        filters = set()
        image_types = set()
        telescopes = set()

        def get_key(k: str, default: Any = "N/A") -> Any:
            """Convert keynames to SQL legal column names"""
            k = get_column_name(k)
            return sess.get(k, default)

        brief_max_rows = 10
        for session_index, sess in enumerate(sessions):
            date_iso = get_key(Database.START_KEY)
            date = to_shortdate(date_iso)

            object = get_key(Database.OBJECT_KEY)
            filter = get_key(Database.FILTER_KEY)
            filters.add(filter)
            image_type = get_key(Database.IMAGETYP_KEY)
            image_types.add(image_type)
            telescope = get_key(Database.TELESCOP_KEY)
            telescopes.add(telescope)

            # Show the non normalized target name
            metadata = sess.get("metadata")
            if metadata:
                long_name = metadata.get("OBJECT")
                if long_name:
                    object = long_name

            # Format total exposure time as integer seconds
            exptime_raw = get_key(Database.EXPTIME_TOTAL_KEY)
            try:
                exptime_float = float(exptime_raw)
                total_seconds += exptime_float
                total_secs = format_duration(int(exptime_float))
            except (ValueError, TypeError):
                total_secs = exptime_raw

            # Count images
            try:
                num_images = int(get_key(Database.NUM_IMAGES_KEY, 0))
                total_images += num_images
            except (ValueError, TypeError):
                num_images = get_key(Database.NUM_IMAGES_KEY)

            if image_type.upper() == "LIGHT":
                image_type = filter
            elif image_type.upper() == "FLAT":
                image_type = f"{image_type}/{filter}"
            else:  # either bias or dark
                object = ""  # Don't show meaningless target

            if brief and session_index == brief_max_rows:
                table.add_row("...", "...", "...", "...", "...", "...", "...")
            elif brief and session_index > brief_max_rows:
                pass  # Show nothing
            else:
                table.add_row(
                    str(session_index + 1),
                    date,
                    str(num_images),
                    total_secs,
                    image_type,
                    telescope,
                    object,
                )

        # Add totals row
        if sessions:
            table.add_row(
                "",
                "",
                f"[bold]{total_images}[/bold]",
                f"[bold]{format_duration(int(total_seconds))}[/bold]",
                "",
                "",
                "",
            )

        console.print(table)

        # FIXME - move these analytics elsewhere so they can be reused when search_session()
        # is used to generate processing lists.
        sb.analytics.set_data("session.total_images", total_images)
        sb.analytics.set_data("session.total_exposure_seconds", int(total_seconds))
        sb.analytics.set_data("session.telescopes", telescopes)
        sb.analytics.set_data("session.filters", filters)
        sb.analytics.set_data("session.image_types", image_types)


@app.command(name="list")
def list_sessions(
    brief: bool = typer.Option(
        False,
        "--brief",
        help="If there are many sessions, show only a few.",
    ),
):
    """List sessions (filtered based on the current selection)"""

    with Starbash("selection.list") as sb:
        do_list_sessions(sb, brief=brief)


def selection_by_number(
    sb: Starbash,
    session_num: int,
) -> SessionRow:
    """Get the session corresponding to the given session number in the current selection."""
    # Get the filtered sessions
    sessions = sb.search_session()

    if not sessions or not isinstance(sessions, list):
        console.print("[red]No sessions found. Check your selection criteria.[/red]")
        raise typer.Exit(1)

    # Validate session number
    if session_num < 1 or session_num > len(sessions):
        console.print(
            f"[red]Error: Session number {session_num} is out of range. "
            f"Valid range is 1-{len(sessions)}.[/red]"
        )
        console.print("[yellow]Use 'select list' to see available sessions.[/yellow]")
        raise typer.Exit(1)

    # Get the selected session (convert from 1-based to 0-based index)
    session = sessions[session_num - 1]
    return session


@app.command()
def export(
    session_num: Annotated[
        int,
        typer.Argument(help="Session number to export (from 'select list' output)"),
    ],
    destdir: Annotated[
        str,
        typer.Argument(help="Directory path to export to (if it doesn't exist it will be created)"),
    ],
):
    """Export the images for the indicated session number.

    Uses symbolic links when possible, otherwise copies files.
    The session number corresponds to the '#' column in 'select list' output.
    """
    with Starbash("selection.export") as sb:
        # Get the selected session (convert from 1-based to 0-based index)
        session = selection_by_number(sb, session_num)

        # Get images for this session
        images = sb.get_session_images(session)
        if not images:
            console.print(f"[red]Error: No images found for session {session_num}.[/red]")
            raise typer.Exit(0)

        # Determine output directory
        output_dir = Path(destdir)

        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        copy_images_to_dir(images, output_dir)


@app.callback(invoke_without_command=True)
def show_selection(ctx: typer.Context):
    """List information about the current selection.

    This is the default command when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        with Starbash("selection.show") as sb:
            summary = sb.selection.summary()

            if summary["status"] == "all":
                console.print(f"[yellow]{summary['message']}[/yellow]")
            else:
                table = Table(title="Current Selection", header_style=TABLE_HEADER_STYLE)
                table.add_column("Criteria", style=TABLE_COLUMN_STYLE)
                table.add_column("Value", style=TABLE_VALUE_STYLE)

                for criterion in summary["criteria"]:
                    parts = criterion.split(": ", 1)
                    if len(parts) == 2:
                        table.add_row(parts[0], parts[1])
                    else:
                        table.add_row(criterion, "")

                console.print(table)
