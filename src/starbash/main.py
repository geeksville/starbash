import logging
from tomlkit import table
import typer
from rich.table import Table

from starbash.database import Database

from .app import Starbash
from .commands import repo
from . import console

app = typer.Typer()
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")


@app.command()
def session():
    """List sessions (filtered based on the current selection)"""

    with Starbash() as sb:
        table = Table(title="Sessions (x selected out of y)")

        table.add_column("Date")
        table.add_column("# images")
        table.add_column("Time")
        table.add_column("About")  # type of frames, filter, target
        # table.add_column("Released", justify="right", style="cyan", no_wrap=True)

        sessions = sb.search_session()
        if sessions and isinstance(sessions, list):
            for sess in sessions:
                date = sess.get(Database.START_KEY, "N/A")
                object = sess.get(Database.OBJECT_KEY, "N/A")
                filter = sess.get(Database.FILTER_KEY, "N/A")
                image_type = sess.get(Database.IMAGETYP_KEY, "N/A")
                table.add_row(
                    date,
                    str(sess.get(Database.NUM_IMAGES_KEY, "N/A")),
                    str(sess.get(Database.EXPTIME_TOTAL_KEY, "N/A")),
                    f"{image_type} {filter} {object}",
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
