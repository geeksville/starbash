"""Info commands for displaying system and data information."""

import typer
from typing_extensions import Annotated
from rich.table import Table
from collections import Counter

from starbash.app import Starbash
from starbash import console
from starbash.database import Database, get_column_name
from starbash.paths import get_user_config_dir, get_user_data_dir
from starbash.commands import format_duration, TABLE_COLUMN_STYLE, TABLE_VALUE_STYLE

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
    allsessions = sb.db.search_session(("", []))

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
        title=f"{plural(human_name)} ({len(found_counts)} / {len(all_counts)} selected)"
    )
    table.add_column(human_name, style=TABLE_COLUMN_STYLE, no_wrap=False)
    table.add_column(
        "# of sessions", style=TABLE_COLUMN_STYLE, no_wrap=True, justify="right"
    )

    for i, count in sorted_list:
        table.add_row(i, str(count))

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


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Show user preferences location and other app info.

    This is the default command when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        with Starbash("info") as sb:
            table = Table(title="Starbash Information")
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
            table.add_row(
                "Sessions Indexed", str(sb.db.len_table(Database.SESSIONS_TABLE))
            )

            table.add_row("Images Indexed", str(sb.db.len_table(Database.IMAGES_TABLE)))

            total_exptime = sb.db.sum_column(Database.SESSIONS_TABLE, "exptime_total")
            table.add_row(
                "Total image time",
                format_duration(total_exptime),
            )
            console.print(table)
