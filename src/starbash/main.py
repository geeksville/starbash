import logging
from datetime import datetime
from tomlkit import table
import typer
from rich.table import Table

from starbash.database import Database

from .app import Starbash
from .commands import repo
from . import console

app = typer.Typer()
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")


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

    with Starbash() as sb:
        sessions = sb.search_session()
        if sessions and isinstance(sessions, list):
            len_all = sb.db.len_session()
            table = Table(title=f"Sessions ({len(sessions)} selected out of {len_all})")

            table.add_column("Date", style="cyan", no_wrap=True)
            table.add_column("# images", style="cyan", no_wrap=True)
            table.add_column("Time", style="cyan", no_wrap=True)
            table.add_column("Type/Filter", style="cyan", no_wrap=True)
            table.add_column(
                "About", style="cyan", no_wrap=True
            )  # type of frames, filter, target
            # table.add_column("Released", justify="right", style="cyan", no_wrap=True)

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

                # Format total exposure time as integer seconds
                exptime_raw = str(sess.get(Database.EXPTIME_TOTAL_KEY, "N/A"))
                try:
                    total_secs = format_duration(int(float(exptime_raw)))
                except (ValueError, TypeError):
                    total_secs = exptime_raw

                type_str = image_type
                if image_type.upper() == "LIGHT":
                    image_type = filter

                table.add_row(
                    date,
                    str(sess.get(Database.NUM_IMAGES_KEY, "N/A")),
                    total_secs,
                    image_type,
                    object,
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
