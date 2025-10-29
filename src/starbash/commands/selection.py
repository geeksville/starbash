"""Selection commands for filtering sessions and targets."""

import typer
from typing_extensions import Annotated
from datetime import datetime
from rich.table import Table

from starbash.app import Starbash
from starbash.database import Database
from starbash import console

app = typer.Typer()


@app.command(name="any")
def clear():
    """Remove any filters on sessions, etc... (select everything)."""
    with Starbash("selection-clear") as sb:
        sb.selection.clear()
        console.print("[green]Selection cleared - now selecting all sessions[/green]")


@app.command()
def target(
    target_name: Annotated[
        str,
        typer.Argument(
            help="Target name to add to the selection (e.g., 'M31', 'NGC 7000')"
        ),
    ],
):
    """Limit the current selection to only the named target."""
    with Starbash("selection-target") as sb:
        # For now, replace existing targets with this one
        # In the future, we could support adding multiple targets
        sb.selection.targets = []
        sb.selection.add_target(target_name)
        console.print(f"[green]Selection limited to target: {target_name}[/green]")


@app.command()
def telescope(
    telescope_name: Annotated[
        str,
        typer.Argument(
            help="Telescope name to add to the selection (e.g., 'Vespera', 'EdgeHD 8')"
        ),
    ],
):
    """Limit the current selection to only the named telescope."""
    with Starbash("selection-telescope") as sb:
        # For now, replace existing telescopes with this one
        # In the future, we could support adding multiple telescopes
        sb.selection.telescopes = []
        sb.selection.add_telescope(telescope_name)
        console.print(
            f"[green]Selection limited to telescope: {telescope_name}[/green]"
        )


@app.command()
def date(
    operation: Annotated[
        str,
        typer.Argument(help="Date operation: 'after', 'before', or 'between'"),
    ],
    date_value: Annotated[
        str,
        typer.Argument(
            help="Date in ISO format (YYYY-MM-DD) or two dates separated by space for 'between'"
        ),
    ],
    end_date: Annotated[
        str | None,
        typer.Argument(help="End date for 'between' operation (YYYY-MM-DD)"),
    ] = None,
):
    """Limit to sessions in the specified date range.

    Examples:
        starbash selection date after 2023-10-01
        starbash selection date before 2023-12-31
        starbash selection date between 2023-10-01 2023-12-31
    """
    with Starbash("selection-date") as sb:
        operation = operation.lower()

        if operation == "after":
            sb.selection.set_date_range(start=date_value, end=None)
            console.print(
                f"[green]Selection limited to sessions after {date_value}[/green]"
            )
        elif operation == "before":
            sb.selection.set_date_range(start=None, end=date_value)
            console.print(
                f"[green]Selection limited to sessions before {date_value}[/green]"
            )
        elif operation == "between":
            if not end_date:
                console.print(
                    "[red]Error: 'between' operation requires two dates[/red]"
                )
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


def format_duration(seconds: int):
    """Format seconds as a human-readable duration string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 120:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"


@app.command(name="list")
def list_sessions():
    """List sessions (filtered based on the current selection)"""

    with Starbash("selection-list") as sb:
        sessions = sb.search_session()
        if sessions and isinstance(sessions, list):
            len_all = sb.db.len_session()
            table = Table(title=f"Sessions ({len(sessions)} selected out of {len_all})")
            sb.analytics.set_data("session.num_selected", len(sessions))
            sb.analytics.set_data("session.num_total", len_all)

            table.add_column("#", style="cyan", no_wrap=True)
            table.add_column("Date", style="cyan", no_wrap=True)
            table.add_column("# images", style="cyan", no_wrap=True)
            table.add_column("Time", style="cyan", no_wrap=True)
            table.add_column("Type/Filter", style="cyan", no_wrap=True)
            table.add_column("Telescope", style="cyan", no_wrap=True)
            table.add_column(
                "About", style="cyan", no_wrap=True
            )  # type of frames, filter, target

            total_images = 0
            total_seconds = 0.0
            filters = set()
            image_types = set()
            telescopes = set()

            for session_index, sess in enumerate(sessions):
                date_iso = sess.get(Database.START_KEY, "N/A")
                # Try to convert ISO UTC datetime to local short date string
                try:
                    dt_utc = datetime.fromisoformat(date_iso)
                    dt_local = dt_utc.astimezone()
                    date = dt_local.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date = date_iso

                object = str(sess.get(Database.OBJECT_KEY, "N/A"))
                filter = sess.get(Database.FILTER_KEY, "N/A")
                filters.add(filter)
                image_type = str(sess.get(Database.IMAGETYP_KEY, "N/A"))
                image_types.add(image_type)
                telescope = str(sess.get(Database.TELESCOP_KEY, "N/A"))
                telescopes.add(telescope)

                # Format total exposure time as integer seconds
                exptime_raw = str(sess.get(Database.EXPTIME_TOTAL_KEY, "N/A"))
                try:
                    exptime_float = float(exptime_raw)
                    total_seconds += exptime_float
                    total_secs = format_duration(int(exptime_float))
                except (ValueError, TypeError):
                    total_secs = exptime_raw

                # Count images
                try:
                    num_images = int(sess.get(Database.NUM_IMAGES_KEY, 0))
                    total_images += num_images
                except (ValueError, TypeError):
                    num_images = sess.get(Database.NUM_IMAGES_KEY, "N/A")

                type_str = image_type
                if image_type.upper() == "LIGHT":
                    image_type = filter
                elif image_type.upper() == "FLAT":
                    image_type = f"{image_type}/{filter}"
                else:  # either bias or dark
                    object = ""  # Don't show meaningless target

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


@app.callback(invoke_without_command=True)
def show_selection(ctx: typer.Context):
    """List information about the current selection.

    This is the default command when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        with Starbash("selection-show") as sb:
            summary = sb.selection.summary()

            if summary["status"] == "all":
                console.print(f"[yellow]{summary['message']}[/yellow]")
            else:
                table = Table(title="Current Selection")
                table.add_column("Criteria", style="cyan")
                table.add_column("Value", style="green")

                for criterion in summary["criteria"]:
                    parts = criterion.split(": ", 1)
                    if len(parts) == 2:
                        table.add_row(parts[0], parts[1])
                    else:
                        table.add_row(criterion, "")

                console.print(table)
