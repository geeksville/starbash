"""Info commands for displaying system and data information."""

import typer
from typing_extensions import Annotated
from rich.table import Table
from collections import Counter

from starbash.app import Starbash
from starbash import console
from starbash.database import Database
from starbash.paths import get_user_config_dir, get_user_data_dir
from starbash.commands import format_duration

app = typer.Typer()


def plural(name: str) -> str:
    """Return the plural form of a given noun (simple heuristic - FIXME won't work with i18n)."""
    if name.endswith("y"):
        return name[:-1] + "ies"
    else:
        return name + "s"


def dump_column(sb: Starbash, human_name: str, column_name: str) -> None:
    # Get all telescopes from the database
    telescopes = sb.db.get_column(Database.SESSIONS_TABLE, column_name)

    if not telescopes:
        console.print(f"[yellow]No {human_name} found in database.[/yellow]")
        return

    # Count occurrences of each telescope
    telescope_counts = Counter(telescopes)

    # Sort by telescope name
    sorted_telescopes = sorted(telescope_counts.items())

    # Create and display table
    table = Table(title=f"{plural(human_name)} ({len(telescope_counts)} found)")
    table.add_column(human_name, style="cyan", no_wrap=False)
    table.add_column("# of sessions", style="cyan", no_wrap=True, justify="right")

    for telescope, count in sorted_telescopes:
        table.add_row(telescope, str(count))

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
    """List all filters found in current selection."""
    with Starbash("info.filter") as sb:
        dump_column(sb, "Filter", Database.FILTER_KEY)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Show user preferences location and other app info.

    This is the default command when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        with Starbash("info") as sb:
            from rich.table import Table

            table = Table(title="Starbash Information")
            table.add_column("Setting", style="cyan", no_wrap=True)
            table.add_column("Value", style="green")

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
