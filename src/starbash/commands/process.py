"""Processing commands for automated image processing workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import rich
import typer
from rich.console import Group
from rich.live import Live
from rich.progress import Progress
from rich.text import Text

from starbash import events
from starbash.app import Starbash, copy_images_to_dir
from starbash.commands.select import selection_by_number
from starbash.database import SessionRow
from starbash.paths import get_user_config_path
from starbash.processing import Processing
from starbash.rich import run_tree_to_rich

app = typer.Typer()


@app.command()
def siril(
    session_num: Annotated[
        int,
        typer.Argument(help="Session number to process (from 'select list' output)"),
    ],
    destdir: Annotated[
        str,
        typer.Argument(help="Destination directory for Siril directory tree and processing"),
    ],
    run: Annotated[
        bool,
        typer.Option(
            "--run",
            help="Automatically launch Siril GUI after generating directory tree",
        ),
    ] = False,
) -> None:
    """Generate Siril directory tree and optionally run Siril GUI.

    Creates a properly structured directory tree for Siril processing with
    biases/, darks/, flats/, and lights/ subdirectories populated with the
    session's images (via symlinks when possible).

    If --run is specified, launches the Siril GUI with the generated directory
    structure loaded and ready for processing.
    """
    with Starbash("process.siril") as sb:
        from starbash import console

        console.print(
            f"[yellow]Processing session {session_num} for Siril in {destdir}...[/yellow]"
        )

        # Determine output directory
        output_dir = Path(destdir)

        # Get the selected session (convert from 1-based to 0-based index)
        session = selection_by_number(sb, session_num)

        # Get images for this session

        def session_to_dir(src_session: SessionRow, subdir_name: str) -> None:
            """Copy the images from the specified session to the subdir"""
            img_dir = output_dir / subdir_name
            img_dir.mkdir(parents=True, exist_ok=True)
            images = sb.get_session_images(src_session)
            copy_images_to_dir(images, img_dir)

        # FIXME - pull this dirname from preferences
        lights = "lights"
        session_to_dir(session, lights)

        extras = [
            # FIXME search for BIAS/DARK/FLAT etc... using multiple canonical names
            ("bias", "biases"),
            ("dark", "darks"),
            ("flat", "flats"),
        ]
        for typ, subdir in extras:
            candidates = sb.guess_sessions(session, typ)
            if not candidates:
                console.print(
                    f"[yellow]No candidate sessions found for {typ} calibration frames.[/yellow]"
                )
            else:
                session_to_dir(candidates[0].candidate, subdir)

        # FIXME put a processed-target metadata file in output_dir (with info about what we picked/why)
        # to allow users to override/reprocess with the same settings.
        # Also FIXME, check for the existence of such a file


class ProcessingView:
    """A live Rich tree of a processing run, driven by the event bus.

    Owns the single :class:`~rich.live.Live` used during a CLI run (so the tree
    and the progress bar share one render loop) and renders each target's run as
    ``target -> stage -> task`` with status glyphs, clickable links and a log
    tail.  It is the CLI counterpart of the GUI's processing tree.
    """

    def __init__(self, title: str, console: rich.console.Console) -> None:
        self.title = title
        self.console = console
        self.progress = Progress(console=console, refresh_per_second=4)
        self._runs: dict[str, dict] = {}
        self._order: list[str] = []
        self._subscriber = self._on_event
        self._live = Live(self._render(), console=console, refresh_per_second=4)

    def __enter__(self) -> ProcessingView:
        events.subscribe(self._subscriber)
        self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        events.unsubscribe(self._subscriber)
        self._live.stop()
        return False

    def _on_event(self, event: events.Event) -> None:
        """Fold a core event into the rendered tree."""
        data = event.data if isinstance(event.data, dict) else {}
        if event.kind in (events.EVENT_RUN_STARTED, events.EVENT_PROCESS_TARGET):
            target = data.get("target") or "masters"
            if target not in self._order:
                self._order.append(target)
                self._refresh()
        elif event.kind == events.EVENT_STAGE_RESULT:
            run = data.get("run")
            if isinstance(run, dict):
                target = run.get("target") or "masters"
                if target not in self._order:
                    self._order.append(target)
                self._runs[target] = run
                self._refresh()

    def _render(self) -> Group:
        header = Text(self.title, style="bold")
        trees = [run_tree_to_rich(self._runs[t]) for t in self._order if t in self._runs]
        return Group(header, *trees, self.progress)

    def _refresh(self) -> None:
        try:
            self._live.update(self._render(), refresh=True)
        except Exception:  # noqa: BLE001 - rendering must never break a run
            pass

    def finish(self) -> None:
        """Render the final state once more before the view is closed."""
        self._refresh()


@app.command()
def auto(
    session_num: Annotated[
        int | None,
        typer.Argument(
            help="Session number to process. If not specified, processes all selected sessions."
        ),
    ] = None,
    no_masters: Annotated[
        bool,
        typer.Option(
            "--no-masters",
            help="Don't automatically generated master frames",
        ),
    ] = False,
) -> None:
    """Automatic processing with sensible defaults.

    If session number is specified, processes only that session.
    Otherwise, all currently selected sessions will be processed automatically
    using the configured recipes and default settings.

    This command handles:
    - Automatic master frame selection (bias, dark, flat)
    - Calibration of light frames
    - Registration and stacking
    - Basic post-processing

    The output will be saved according to the configured recipes.
    """
    if no_masters:
        import starbash

        starbash.process_masters = False

    # Users might run "process auto" as their first command without reading any docs...
    if not get_user_config_path().exists():
        from starbash import console

        console.print("[red]No app setup found.[/red]  Please run 'sb user setup'.")
        raise typer.Exit(1)

    with Starbash("process.auto") as sb:
        from starbash import console

        view = ProcessingView("Auto-processing", console)
        with view, Processing(sb, progress=view.progress) as proc:
            if session_num is not None:
                console.print(
                    f"[red]Session number base filtering not yet implemented: {session_num}...[/red]"
                )
            else:
                proc.run_all_stages()
                view.finish()


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    add_help_option=False,
)
def doit(
    ctx: typer.Context,
) -> None:
    """(private) for developer debugging of the underlying 'doit' dependency system.

    You probably don't need to use this - unless you are a starbash developer.
    Arguments are passed directly to doit.  For more information run: sb process doit help"""
    with Starbash("process.doit") as sb:
        with Processing(sb) as proc:
            from starbash import console

            console.print("[red]This command is currently for developers only...[/red]")
            # Build the full task tree so doit subcommands (graph/list/info) have data to show.
            proc.load_tasks_for_inspection()
            proc.doit.run(ctx.args)


@app.command()
def masters() -> None:
    """Generate master flats, darks, and biases from selected raw frames.

    Analyzes the current selection to find all available calibration frames
    (BIAS, DARK, FLAT) and automatically generates master calibration frames
    using stacking recipes.

    Generated master frames are stored in the configured masters directory
    and will be automatically used for future processing operations.
    """
    with Starbash("process.masters") as sb:
        from starbash import console

        view = ProcessingView("Generating master frames", console)
        with view, Processing(sb, progress=view.progress) as proc:
            proc.run_master_stages()
            view.finish()


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """Process images using automated workflows.

    These commands handle calibration, registration, stacking, and
    post-processing of astrophotography sessions.
    """
    if ctx.invoked_subcommand is None:
        from starbash import console

        # No command provided, show help
        console.print(ctx.get_help())
        raise typer.Exit()
