"""Info commands for displaying system and data information."""

from collections import Counter
from typing import Annotated

import typer
from rich.table import Table

from starbash.app import Starbash
from starbash.commands import (
    TABLE_COLUMN_STYLE,
    TABLE_HEADER_STYLE,
    TABLE_VALUE_STYLE,
    format_duration,
)
from starbash.database import Database, get_column_name

app = typer.Typer()


def plural(name: str) -> str:
    """Return the plural form of a given noun (simple heuristic - FIXME won't work with i18n)."""
    if name.endswith("y"):
        return name[:-1] + "ies"
    else:
        return name + "s"


def dump_column(sb: Starbash, human_name: str, column_name: str) -> None:
    # Get all telescopes from the database
    sessions = sb.search_session()

    # Also do a complete unfiltered search so we can compare for the users
    allsessions = sb.db.search_session([])

    column_name = get_column_name(column_name)
    found = [session[column_name] for session in sessions if session[column_name]]
    allfound = [session[column_name] for session in allsessions if session[column_name]]

    # Count occurrences of each telescope
    found_counts = Counter(found)
    all_counts = Counter(allfound)

    # Sort by telescope name
    sorted_list = sorted(found_counts.items())

    # Create and display table
    table = Table(
        header_style=TABLE_HEADER_STYLE,
        title=f"{plural(human_name)} ({len(found_counts)} / {len(all_counts)} selected)",
    )
    table.add_column(human_name, style=TABLE_COLUMN_STYLE, no_wrap=False)
    table.add_column("# of sessions", style=TABLE_COLUMN_STYLE, no_wrap=True, justify="right")

    for i, count in sorted_list:
        table.add_row(i, str(count))

    from starbash import console

    console.print(table)


@app.command()
def target():
    """List targets (filtered based on the current selection)."""
    with Starbash("info.target") as sb:
        dump_column(sb, "Target", Database.OBJECT_KEY)


@app.command()
def telescope():
    """List telescopes/instruments (filtered based on the current selection)."""
    with Starbash("info.telescope") as sb:
        dump_column(sb, "Telescope", Database.TELESCOP_KEY)


@app.command()
def filter():
    """List all filters (filtered based on the current selection)."""
    with Starbash("info.filter") as sb:
        dump_column(sb, "Filter", Database.FILTER_KEY)


kind_arg = typer.Argument(
    help="Optional image type to filter by (e.g., BIAS, DARK, FLAT, LIGHT)",
)


@app.command()
def master(
    kind: Annotated[
        str | None,
        kind_arg,
    ] = None,
):
    """List all precalculated master images (darks, biases, flats)."""
    with Starbash("info.master") as sb:
        from starbash import console

        # Get the master repo
        images = sb.get_master_images(kind)

        if not images:
            kind_msg = f" of type '{kind}'" if kind else ""
            console.print(f"[yellow]No master images{kind_msg} found.[/yellow]")
            return

        # Create table to display results
        title = f"Master Images ({len(images)} total)"
        if kind:
            title = f"Master {kind} Images ({len(images)} total)"
        table = Table(title=title, header_style=TABLE_HEADER_STYLE)
        table.add_column("Date", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Type", style=TABLE_COLUMN_STYLE, no_wrap=True)
        table.add_column("Filename", style=TABLE_VALUE_STYLE, no_wrap=False)

        # Sort by date, then by type
        sorted_images = sorted(
            images,
            key=lambda img: (
                img.get(Database.DATE_OBS_KEY) or img.get(Database.DATE_KEY) or "",
                img.get(Database.IMAGETYP_KEY) or "",
            ),
        )

        for image in sorted_images:
            date = image.get(Database.DATE_OBS_KEY) or image.get(Database.DATE_KEY) or "Unknown"
            # Extract just the date part (YYYY-MM-DD) if it's a full ISO timestamp
            if "T" in date:
                date = date.split("T")[0]

            kind = image.get(Database.IMAGETYP_KEY)
            if kind:
                kind = sb.aliases.normalize(kind)
            filename = image.get("path") or "Unknown"

            table.add_row(date, kind, filename)

        console.print(table)


@app.command(hidden=True)
def masters(
    kind: Annotated[
        str | None,
        kind_arg,
    ] = None,
):
    """Alias for 'info master' command."""
    master(kind)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Show user preferences location and other app info.

    This is the default command when no subcommand is specified.
    """
    from starbash import console

    if ctx.invoked_subcommand is None:
        with Starbash("info") as sb:
            table = Table(title="Starbash Information", header_style=TABLE_HEADER_STYLE)
            table.add_column("Setting", style=TABLE_COLUMN_STYLE, no_wrap=True)
            table.add_column("Value", style=TABLE_VALUE_STYLE)

            # Show config and data directories
            # table.add_row("Config Directory", str(get_user_config_dir()))
            # table.add_row("Data Directory", str(get_user_data_dir()))

            # Show user preferences if set
            user_name = sb.user_repo.get("user.name")
            if user_name:
                table.add_row("User Name", str(user_name))

            user_email = sb.user_repo.get("user.email")
            if user_email:
                table.add_row("User Email", str(user_email))

            # Show number of repos
            table.add_row("Total Repositories", str(len(sb.repo_manager.repos)))
            table.add_row("User Repositories", str(len(sb.repo_manager.regular_repos)))

            # Show database stats
            table.add_row("Sessions Indexed", str(sb.db.len_table(Database.SESSIONS_TABLE)))

            table.add_row("Images Indexed", str(sb.db.len_table(Database.IMAGES_TABLE)))

            total_exptime = sb.db.sum_column(Database.SESSIONS_TABLE, "exptime_total")
            table.add_row(
                "Total image time",
                format_duration(total_exptime),
            )
            console.print(table)
