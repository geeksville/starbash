import logging
import warnings
from typing import Annotated

import typer

import starbash
import starbash.url as url

from . import console
from .analytics import is_development_environment
from .app import Starbash
from .commands import info, process, publish, repo, select, user
from .commands.gui import gui as gui_command
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
app.add_typer(
    publish.app,
    name="publish",
    help="Generate a local Jekyll report site or publish it to GitHub Pages.",
)
app.command(
    name="gui",
    help="Launch the desktop GUI.",
)(gui_command)


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
    no_gui: bool = typer.Option(
        False,
        "--no-gui",
        help="Do not open the desktop GUI for a bare 'sb'; print help instead.",
    ),
) -> None:
    """Main callback for the Starbash application."""
    # Set the log level based on --debug flag
    if debug:
        starbash.log_filter_level = logging.DEBUG
    if force:
        starbash.force_regen = True
    if verbose:
        starbash.verbose_output = True

    if ctx.invoked_subcommand is None:
        # Bare `sb`: on a machine with a desktop session, open the GUI (which
        # shows the setup wizard on a first run).  A headless box - or an explicit
        # --no-gui - keeps today's behaviour, so SSH users are unaffected.
        if not no_gui and _try_launch_gui():
            raise typer.Exit()
        if not get_user_config_path().exists():
            with Starbash("app.first") as sb:
                user.do_reinit(sb)
        else:
            # No command provided, show help
            console.print(ctx.get_help())
        raise typer.Exit()


def _try_launch_gui() -> bool:
    """Open the GUI for a bare ``sb``, or report whether it was worth trying.

    Returns ``True`` once the GUI ran (so the caller should stop), ``False`` when
    there is no display or Qt is unusable, in which case the caller falls back to
    the CLI's own first-run questions / help text.

    ``desktop_session_available()`` is checked *first* and is Qt-free on purpose:
    importing PySide6 on a headless box is slow and can fail on missing shared
    libraries, and that must not turn a simple ``sb`` into a traceback.
    """
    from .ui.qt import GuiUnavailableError, desktop_session_available

    if not desktop_session_available():
        return False

    from .ui.qt import run_gui

    try:
        run_gui()
    except GuiUnavailableError as exc:
        # A broken/partial install: say so, then fall through to the CLI path so
        # the user still gets a working command line.
        console.print(f"[yellow]{exc}[/yellow]")
        return False
    return True


if __name__ == "__main__":
    app()
