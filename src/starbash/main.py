import logging
import typer

import starbash.url as url

from .app import Starbash
from .commands import repo, select, user
from . import console

app = typer.Typer(
    rich_markup_mode="rich",
    help=f"Starbash - Astrophotography workflows simplified.\n\nFor full instructions and support [link={url.project}]click here[/link].",
)
app.add_typer(user.app, name="user", help="Manage user settings.")
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")
app.add_typer(select.app, name="select", help="Manage session and target selection.")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Main callback for the Starbash application."""
    if ctx.invoked_subcommand is None:
        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()


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
