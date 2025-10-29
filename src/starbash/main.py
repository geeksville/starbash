import logging
import typer

import starbash.url as url

from .app import Starbash, get_user_config_path
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
        if not get_user_config_path().exists():
            with Starbash("app.first") as sb:
                user.do_reinit(sb)
        else:
            # No command provided, show help
            console.print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
