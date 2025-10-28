import logging
from datetime import datetime
from tomlkit import table
import typer
from rich.table import Table

from starbash.database import Database
import starbash.url as url

from .app import Starbash
from .commands import repo, user, selection
from . import console

app = typer.Typer(
    rich_markup_mode="rich",
    help=f"Starbash - Astrophotography workflows simplified.\n\nFor full instructions and support [link={url.project}]click here[/link].",
)
app.add_typer(user.app, name="user", help="Manage user settings.")
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")
app.add_typer(
    selection.app, name="selection", help="Manage session and target selection."
)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Main callback for the Starbash application."""
    if ctx.invoked_subcommand is None:
        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()


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


@app.command()
def session():
    """List sessions (filtered based on the current selection)"""

    with Starbash("session") as sb:
        sessions = sb.search_session()
        if sessions and isinstance(sessions, list):
            len_all = sb.db.len_session()
            table = Table(title=f"Sessions ({len(sessions)} selected out of {len_all})")

            table.add_column("Date", style="cyan", no_wrap=True)
            table.add_column("# images", style="cyan", no_wrap=True)
            table.add_column("Time", style="cyan", no_wrap=True)
            table.add_column("Type/Filter", style="cyan", no_wrap=True)
            table.add_column("Telescope", style="cyan", no_wrap=True)
            table.add_column(
                "About", style="cyan", no_wrap=True
            )  # type of frames, filter, target
            # table.add_column("Released", justify="right", style="cyan", no_wrap=True)

            total_images = 0
            total_seconds = 0.0

            for sess in sessions:
                date_iso = sess.get(Database.START_KEY, "N/A")
                # Try to cnvert ISO UTC datetime to local short date string
                try:
                    dt_utc = datetime.fromisoformat(date_iso)
                    dt_local = dt_utc.astimezone()
                    date = dt_local.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date = date_iso

                object = str(sess.get(Database.OBJECT_KEY, "N/A"))
                filter = sess.get(Database.FILTER_KEY, "N/A")
                image_type = str(sess.get(Database.IMAGETYP_KEY, "N/A"))
                telescop = str(sess.get(Database.TELESCOP_KEY, "N/A"))

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
                if image_type.upper() == "FLAT":
                    image_type = f"{image_type}/{filter}"

                table.add_row(
                    date,
                    str(num_images),
                    total_secs,
                    image_type,
                    telescop,
                    object,
                )

            # Add totals row
            if sessions:
                table.add_row(
                    "",
                    f"[bold]{total_images}[/bold]",
                    f"[bold]{format_duration(int(total_seconds))}[/bold]",
                    "",
                    "",
                    "",
                )

            console.print(table)


# @app.command(hidden=True)
# def default_cmd():
#    """Default entry point for the starbash application."""
#
#    with Starbash() as sb:


# @app.command(hidden=True)
# def default_cmd():
#    """Default entry point for the starbash application."""
#
#    with Starbash() as sb:
#        pass
#
#
# @app.callback(invoke_without_command=True)
# def _default(ctx: typer.Context):
#    # If the user didn’t specify a subcommand, run the default
#    if ctx.invoked_subcommand is None:
#        return default_cmd()


if __name__ == "__main__":
    app()
