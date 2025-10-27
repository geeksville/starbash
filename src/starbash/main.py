import logging
import typer

from .app import Starbash
from .commands import repo

app = typer.Typer()
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")


@app.command(hidden=True)
def default_cmd():
    """Default entry point for the starbash application."""

    with Starbash() as sb:
        pass


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context):
    # If the user didn’t specify a subcommand, run the default
    if ctx.invoked_subcommand is None:
        return default_cmd()


if __name__ == "__main__":
    app()
