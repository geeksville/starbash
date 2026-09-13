"""Processing commands for automated image processing workflows."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.padding import Padding
from rich.progress import Progress
from rich.segment import Segment
from rich.spinner import Spinner
from rich.text import Text

from starbash import events
from starbash.app import Starbash, copy_images_to_dir
from starbash.commands import SPINNER_STYLE
from starbash.commands.select import selection_by_number
from starbash.database import SessionRow
from starbash.paths import get_user_config_path
from starbash.processing import Processing
from starbash.rich import run_tree_to_rich, runs_to_table, supports_live_display

app = typer.Typer()

#: Programs that merely launch another program, so a tool label should look past
#: them (Siril is normally run as ``flatpak run ... org.siril.Siril``).
_LAUNCHERS = frozenset({"flatpak", "env", "nice", "sudo", "xvfb-run"})


def tool_label(cmd: str) -> str:
    """A short, human label for a tool command line.

    Command lines vary (``/usr/bin/siril-cli -d /tmp/x -s -`` versus ``flatpak run
    --command=siril-cli org.siril.Siril -d /tmp/x -s -``), so skip flags, look past
    a launcher and prefer a reverse-DNS app id, then shorten that to its last
    component (``org.siril.Siril`` -> ``Siril``).
    """
    tokens = [t for t in cmd.split() if not t.startswith("-")]
    if not tokens:
        return cmd
    name = Path(tokens[0]).name
    if name in _LAUNCHERS:
        # "flatpak run org.siril.Siril ...": the app id (or, failing that, the word
        # after the launcher's own subcommand) names the real program.
        rest = [Path(t).name for t in tokens[1:]]
        app_ids = [n for n in rest if n.count(".") >= 2]
        if app_ids:
            name = app_ids[0]
        elif rest:
            name = rest[1] if len(rest) > 1 else rest[0]
    return name.split(".")[-1] if name.count(".") >= 2 else name


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


class _RunTail:
    """Show the *bottom* of a list of run trees that is taller than its region.

    ``Live`` handles a renderable that is too tall for the terminal by keeping
    the top and drawing a red ``...`` over the rest (its ``live.ellipsis``
    style).  A real run has *hundreds* of ``Master ...`` runs, so the whole
    screen became that ``...`` and the status line -- which lived at the bottom
    of the old single ``Group`` -- was cropped away entirely.

    Rather than crop, this renderable measures as many of the *most recent*
    runs as the region can hold, starting from the newest, and reports how many
    scrolled off.  Runs that do not fit are never rendered, which also keeps the
    per-frame cost proportional to the screen instead of to the run count.
    """

    def __init__(self, renderables: Sequence[RenderableType], unit: str = "run") -> None:
        self.renderables = renderables
        self.unit = unit

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        height = options.height or console.height
        if height <= 0:
            return
        # ``reset_height()`` (not ``update_height(None)``, whose parameter is typed
        # ``int``) makes the options unbounded, so each run is measured at its own
        # natural height: a numeric height would crop *and pad* it to that height
        # (``Console.render_lines``), defeating the summing below.
        unbounded = options.reset_height()
        # Keep one row free for the "earlier runs" note, so the region does not
        # jump by a line each time a run appears or is culled.
        budget = max(height - 1, 1)
        chosen: list[list[list[Segment]]] = []
        used = 0
        for renderable in reversed(self.renderables):
            lines = console.render_lines(renderable, unbounded, pad=True)
            # Always take at least one run, even when a single run is taller than
            # the whole region (its own top is then cropped by the region).
            if chosen and used + len(lines) > budget:
                break
            chosen.append(lines)
            used += len(lines)

        hidden = len(self.renderables) - len(chosen)
        if hidden:
            plural = "" if hidden == 1 else "s"
            yield Text(f"… {hidden} earlier {self.unit}{plural}", style="dim")
        new_line = Segment.line()
        for lines in reversed(chosen):
            for line in lines:
                yield from line
                yield new_line


class ProcessingView:
    """A live Rich tree of a processing run, driven by the event bus.

    Owns the single :class:`~rich.live.Live` used during a CLI run -- so the tree,
    the live status line and the progress bars share one render loop -- and renders
    each target's run as ``target -> stage -> task`` with status glyphs, clickable
    links and a log tail.  It is the CLI counterpart of the GUI's processing tree.

    Its *only* input is :mod:`starbash.events` (``process.target``, ``run.*``,
    ``task.*``, ``tool.*`` and ``stage.result``).  Nothing under ``starbash.tool``
    draws to the terminal any more, because two Rich ``Live`` displays on one
    console tear each other apart (see ``doc/plans/cli-live-display.md``).

    The screen is split with a :class:`~rich.layout.Layout`: a *pinned* status
    region on top shows what is happening *now* -- a spinner, the current
    target/stage/task, the tool being run with its percentage, the last few tool
    output lines (stderr red, stdout yellow) and the progress bars -- and the
    run trees get every remaining row below it, showing their newest activity.

    That split is what keeps the status line on screen.  A full run has hundreds
    of ``Master ...`` runs, so the combined tree is hundreds of lines tall; Rich
    crops a too-tall live renderable from the *top*, so a single ``Group`` used
    to throw away the status line and leave only its red ``...`` overflow marker.

    When the output is **not** an interactive terminal (a pipe, a file redirect,
    a "dumb" terminal or a test harness), a live tree would render nothing until
    it stops -- and even then it carries no plain status words -- so tools
    watching our output would see no results.  In that case the view skips
    ``Live`` entirely and prints a flat :func:`~starbash.rich.runs_to_table`
    summary on :meth:`finish` instead.
    """

    #: How many of the most recent tool output lines stay on screen.
    TOOL_TAIL_LINES = 3

    def __init__(self, title: str, console: Console) -> None:
        self.title = title
        self.console = console
        self.progress = Progress(console=console, refresh_per_second=4)
        self._runs: dict[str, dict] = {}
        self._order: list[str] = []
        self._subscriber = self._on_event
        self._interactive = supports_live_display(console)
        self._finished = False
        # The first task that failed, if any: the final frame keeps reporting it
        # (the live caption moves on to whatever runs next).
        self._failure: str | None = None
        # Live status: what is happening right now, folded from bus events.
        self._caption: Text = Text("Starting...", style="dim")
        self._tool: str | None = None
        self._percent: int | None = None
        self._note: str | None = None
        self._tail: deque[Text] = deque(maxlen=self.TOOL_TAIL_LINES)
        # The view renders itself: Live's own refresh thread repaints the current
        # state at a fixed rate.  That keeps a chatty tool (Siril emits thousands of
        # lines) from forcing a re-render per line -- events only mutate a few
        # fields -- and the display cannot outpace the terminal.
        self._live: Live | None = (
            Live(self, console=console, refresh_per_second=4) if self._interactive else None
        )

    def __enter__(self) -> ProcessingView:
        events.subscribe(self._subscriber)
        if self._live is not None:
            self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        events.unsubscribe(self._subscriber)
        if self._live is not None:
            self._live.stop()
        else:
            self.finish()
        return False

    def _on_event(self, event: events.Event) -> None:
        """Fold a core event into the rendered tree and the live status line."""
        data = event.data if isinstance(event.data, dict) else {}
        kind = event.kind
        if kind in (events.EVENT_RUN_STARTED, events.EVENT_PROCESS_TARGET):
            self._note_run(data)
            self._set_status(self._run_caption(data))
        elif kind == events.EVENT_TASK_STARTED:
            self._note_run(data)
            self._set_status(self._task_caption(data))
        elif kind == events.EVENT_TASK_FINISHED:
            self._note_run(data)
            # A finished task leaves the caption alone (its status is in the tree);
            # only a failure is worth calling out where the running task was.
            if data.get("success") is False:
                # Just the task title here: "Failed: stack: Stack lights" would
                # repeat the stage the tree already shows.
                self._failure = str(data.get("title") or data.get("task") or "")
                self._set_status(f"Failed: {self._failure}", style="red")
            self._clear_tool()
        elif kind == events.EVENT_STAGE_RESULT:
            self._note_run(data)
        elif kind == events.EVENT_PREFLIGHT_FINISHED:
            self._drop_runs(data)
        elif kind == events.EVENT_TOOL_STARTED:
            self._clear_tool()
            self._tool = tool_label(str(data.get("cmd") or ""))
            self._tail.clear()
        elif kind == events.EVENT_TOOL_OUTPUT:
            stream = str(data.get("stream") or "")
            # Structured streams (e.g. "stdout.json") are protocol frames, not log
            # text; their useful content already arrives as EVENT_TOOL_PROGRESS.
            if not events.is_structured_stream(stream):
                self._add_tail_line(str(data.get("line") or ""), is_stderr=stream == "stderr")
        elif kind == events.EVENT_TOOL_PROGRESS:
            percent = data.get("percent")
            if percent is not None:
                self._percent = int(percent)
            message = data.get("message")
            if message:
                # rc-astro's status lines carry no percentage, so a message-only
                # update must not wipe the bar (it keeps the last known value).
                self._note = str(message)
        elif kind == events.EVENT_TOOL_FINISHED:
            self._clear_tool()

    def _note_run(self, data: dict) -> None:
        """Fold a payload's run/target labels into the rendered tree."""
        run = data.get("run")
        if isinstance(run, dict):
            target = str(run.get("target") or "masters")
            self._runs[target] = run
        elif data.get("target"):
            target = str(data["target"])
        else:
            return  # nothing to learn (e.g. a stage result with no run snapshot)
        if target not in self._order:
            self._order.append(target)

    def _drop_runs(self, data: dict) -> None:
        """Drop culled master runs (ones no selected target needs) from the tree."""
        for label in data.get("drop", []):
            self._runs.pop(label, None)
            if label in self._order:
                self._order.remove(label)

    def _set_status(self, text: str, style: str = "") -> None:
        """Replace the one-line 'what is happening now' caption.

        The caption is built as literal :class:`~rich.text.Text`, never markup, so
        task titles and tool messages (which come from recipes and from the tools
        themselves) cannot break the render or inject styling.
        """
        self._caption = Text(text, style=style)

    def _clear_tool(self) -> None:
        """Forget the running tool (and its progress) - the tail stays visible."""
        self._tool = None
        self._percent = None
        self._note = None

    @staticmethod
    def _run_caption(data: dict) -> str:
        """Caption for a run/target transition (mirrors the GUI's wording)."""
        label = data.get("target") or "masters"
        index, total = data.get("index"), data.get("total")
        if index is not None and total is not None:
            return f"Target {index}/{total}: {label}"
        return f"Processing {label}"

    @staticmethod
    def _task_caption(data: dict) -> str:
        """Caption for a task transition, e.g. ``stack: Stack lights``."""
        title = str(data.get("title") or data.get("task") or "")
        stage = data.get("stage")
        return f"{stage}: {title}" if stage else title

    def _add_tail_line(self, line: str, is_stderr: bool) -> None:
        """Keep a tool output line for the live tail (one row, ellipsised)."""
        text = line.rstrip("\n")
        if not text.strip():
            return
        self._tail.append(
            Text(
                text,
                style="red" if is_stderr else "yellow",
                no_wrap=True,
                overflow="ellipsis",
            )
        )

    def _render(self) -> RenderableType:
        """The whole view: a pinned status region above the scrolling run trees.

        Snapshot the mutable state up front: Live's refresh thread may render
        this while the thread folding events mutates it (``list()``/dict lookups
        are atomic).
        """
        status = self._status_renderable()
        # Measure the status region so the tree gets exactly the rows left over.
        # Rich hands a region's renderable its own height, which is what lets
        # ``_RunTail`` pick the runs that fit.
        # ``console.options`` carries no height (only ``max_height``), so this
        # measures the status at its natural height.
        status_height = 1 + len(self.console.render_lines(status, self.console.options, pad=False))
        height = self.console.height
        if height < 4:
            # No room to split: the status is the only thing worth showing.
            return Group(Text(self.title, style="bold"), status)
        status_height = min(status_height, height - 1)
        trees = [run_tree_to_rich(self._runs[t]) for t in list(self._order) if t in self._runs]
        layout = Layout()
        layout.split_column(
            Layout(
                Group(Text(self.title, style="bold"), status), name="status", size=status_height
            ),
            Layout(_RunTail(trees), name="runs", ratio=1, minimum_size=1),
        )
        return layout

    def __rich__(self) -> RenderableType:
        """Render for :class:`~rich.live.Live`, which re-renders us on each refresh."""
        return self._render()

    def _status_renderable(self) -> RenderableType:
        """The live status line, the recent tool output lines and the progress bars."""
        if self._finished:
            # The frame that stays on screen (Live leaves the last one behind).
            if self._failure:
                head: RenderableType = Text.assemble(("✗", "red"), " ", self._status_text())
            else:
                head = Text.assemble(("✓", "green"), " ", self._status_text())
        else:
            head = Spinner("arc", text=self._status_text(), speed=2.0, style=SPINNER_STYLE)
        lines = [Padding(line, (0, 0, 0, 4)) for line in list(self._tail)]
        return Group(head, *lines, self.progress)

    def _status_text(self) -> Text:
        """The 'what is happening now' text: phase, tool, percentage and message."""
        text = self._caption.copy()
        if self._tool:
            text.append(" · ", style="dim")
            text.append(self._tool, style="bold")
        if self._percent is not None:
            text.append(f" {self._percent}%", style="dim")
        if self._note:
            text.append(f" · {self._note}", style="dim")
        return text

    def _refresh(self) -> None:
        """Repaint now; Live's own refresh thread also repaints periodically."""
        if self._live is None:
            return  # non-interactive sinks get the flat table on finish() only
        try:
            self._live.refresh()
        except Exception:  # noqa: BLE001 - rendering must never break a run
            pass

    def finish(self) -> None:
        """Render the final state once more before the view is closed."""
        if self._finished:
            return
        self._finished = True
        self._clear_tool()
        if self._failure:
            # Keep reporting the failure: it is the thing a user needs to see last.
            self._set_status(f"Failed: {self._failure}", style="red")
        else:
            self._set_status(f"{self.title}: done")
        if self._live is not None:
            self._refresh()
        else:
            self._print_table()

    def _print_table(self) -> None:
        """Emit the simplified, line-oriented summary used for dumb sinks."""
        runs = [self._runs[t] for t in self._order if t in self._runs]
        self.console.print(self.title, style="bold")
        if runs:
            self.console.print(runs_to_table(runs))


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
