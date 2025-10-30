"""Info commands for displaying system and data information."""

import typer
from typing_extensions import Annotated

from starbash.app import Starbash
from starbash import console
from starbash.database import Database
from starbash.paths import get_user_config_dir, get_user_data_dir

app = typer.Typer()


@app.command()
def target():
    """List targets (filtered based on the current selection)."""
    with Starbash("info.target") as sb:
        console.print("[yellow]Not yet implemented[/yellow]")
        console.print(
            "This command will list all unique targets in the current selection."
        )


@app.command()
def telescope():
    """List telescopes/instruments (filtered based on the current selection)."""
    with Starbash("info.telescope") as sb:
        console.print("[yellow]Not yet implemented[/yellow]")
        console.print(
            "This command will list all unique telescopes in the current selection."
        )


@app.command()
def filter():
    """List all filters found in current selection."""
    with Starbash("info.filter") as sb:
        console.print("[yellow]Not yet implemented[/yellow]")
        console.print(
            "This command will list all unique filters in the current selection."
        )


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
            table.add_row("Config Directory", str(get_user_config_dir()))
            table.add_row("Data Directory", str(get_user_data_dir()))

            # Show user preferences if set
            user_name = sb.user_repo.get("user.name")
            if user_name:
                table.add_row("User Name", str(user_name))

            user_email = sb.user_repo.get("user.email")
            if user_email:
                table.add_row("User Email", str(user_email))

            # Show analytics setting
            analytics_enabled = sb.user_repo.get("analytics.enabled", True)
            table.add_row("Analytics", "Enabled" if analytics_enabled else "Disabled")

            # Show number of repos
            table.add_row("Total Repositories", str(len(sb.repo_manager.repos)))
            table.add_row("User Repositories", str(len(sb.repo_manager.regular_repos)))

            # Show database stats
            num_sessions = sb.db.len_table(Database.SESSIONS_TABLE)
            table.add_row("Sessions Indexed", str(num_sessions))

            num_images = sb.db.len_table(Database.IMAGES_TABLE)
            table.add_row("Images Indexed", str(num_images))

            console.print(table)
