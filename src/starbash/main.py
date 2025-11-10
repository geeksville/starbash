import logging
import warnings
from typing import Annotated

import typer

import starbash
import starbash.url as url

from . import console
from .analytics import is_development_environment
from .app import Starbash
from .commands import info, process, repo, select, user
from .paths import get_user_config_path

# Suppress deprecation warnings in production mode to provide a cleaner user experience.
# In development mode (VS Code, devcontainer, or SENTRY_ENVIRONMENT=development),
# all warnings are shown to help developers identify potential issues.
# See: is_development_environment() in analytics.py for detection logic.
if not is_development_environment():
    warnings.filterwarnings("ignore", category=DeprecationWarning)

app = typer.Typer(
    rich_markup_mode="rich",
    help=f"Starbash - Astrophotography workflows simplified.\n\nFor full instructions and support [link={url.project}]click here[/link].",
)
app.add_typer(user.app, name="user", help="Manage user settings.")
app.add_typer(repo.app, name="repo", help="Manage Starbash repositories.")
app.add_typer(select.app, name="select", help="Manage session and target selection.")
app.add_typer(info.app, name="info", help="Display system and data information.")
app.add_typer(process.app, name="process", help="Process images using automated workflows.")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug logging output.",
        ),
    ] = False,
    force: bool = typer.Option(
        default=False,
        help="Force reindexing/output file regeneration - even if unchanged.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="When providing responses, include all entries.  Normally long responses are truncated.",
    ),
):
    """Main callback for the Starbash application."""
    # Set the log level based on --debug flag
    if debug:
        starbash.log_filter_level = logging.DEBUG
    if force:
        starbash.force_regen = True
    if verbose:
        starbash.verbose_output = True

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
