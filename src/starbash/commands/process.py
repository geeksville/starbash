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
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
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
from starbash.rich import log_line_to_text, run_tree_to_rich, runs_to_table, supports_live_display
from starbash.run_state import RunStatus

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


class _LogTail:
    """Show the *bottom* of a log that is taller than its region.

    A run emits thousands of lines, and the interesting one is almost always the
    newest, so this renderable yields only the trailing lines that fit (measured
    with wrapping, so a long line can take several rows) and reports how many
    scrolled off above.  Measuring stops as soon as the region is full, so the
    per-frame cost is proportional to the screen, not to the log length.
    """

    def __init__(self, lines: Sequence[Text], unit: str = "line") -> None:
        self.lines = lines
        self.unit = unit

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        height = options.height or console.height
        if height <= 0:
            return
        # ``reset_height()`` (not ``update_height(None)``, whose parameter is typed
        # ``int``) makes the options unbounded, so a line is measured at its own
        # natural (wrapped) height instead of being cropped to the region.
        unbounded = options.reset_height()
        # Keep one row free for the "earlier lines" note, so the pane does not
        # jump by a line each time a line arrives.
        budget = max(height - 1, 1)
        chosen: list[list[list[Segment]]] = []
        used = 0
        # Always take at least one line, even when a single line wraps past the
        # whole region (its own top is then cropped by the region).
        for line in reversed(list(self.lines)):
            rows = console.render_lines(line, unbounded, pad=True)
            if chosen and used + len(rows) > budget:
                break
            chosen.append(rows)
            used += len(rows)

        hidden = len(self.lines) - len(chosen)
        if hidden:
            plural = "" if hidden == 1 else "s"
            yield Text(f"… {hidden} earlier {self.unit}{plural}", style="dim")
        new_line = Segment.line()
        for rows in reversed(chosen):
            for row in rows:
                yield from row
                yield new_line


class _RunWindow:
    """Show the run tree around the task that is currently building.

    The combined tree of a real run is far taller than its region, and Rich crops
    a too-tall live renderable from the *top* -- exactly the wrong end, since the
    run being worked on is the newest one at the bottom.  This renderable
    measures runs from the newest backwards (stopping as soon as the region is
    full *and* the focus run has been measured), then windows that text so the
    ``⏳`` running task stays on screen, with the stages still to come visible
    below it, and reports the runs that scrolled off above and below.

    Measuring newest-first keeps the per-frame cost proportional to the screen
    rather than to the run count, even with hundreds of ``Master ...`` runs.
    """

    #: Rows of context kept above the anchor row when the pane scrolls, so the
    #: stage header the anchored task belongs to stays visible.
    ANCHOR_CONTEXT = 2

    def __init__(
        self,
        renderables: Sequence[RenderableType],
        index: int | None = None,
        unit: str = "run",
    ) -> None:
        self.renderables = renderables
        #: Index of the run that is currently building, if any.
        self.index = index
        self.unit = unit

    @staticmethod
    def _anchor_row(lines: Sequence[list[Segment]]) -> int | None:
        """The row this pane should keep on screen: the running task's, else progress'.

        The ``⏳`` row wins when something is building.  In the gap between two
        tasks (and right after a run finishes) there is no ``⏳`` at all, so the
        anchor becomes the *last* row that actually ran -- the bottom-most
        ``✓``/``Ø``/``✗``.  Anchoring those on the run's first stage instead is
        what made the pane look frozen: it showed the finished top of a run while
        the work happened hundreds of rows below.

        ``⊘`` (excluded) is deliberately not progress: a target's config usually
        excludes most stages, and those rows sit *below* the work in the tree.
        """
        running = RunStatus.RUNNING.glyph
        for row, segments in enumerate(lines):
            if any(running in segment.text for segment in segments):
                return row
        progress = (
            RunStatus.OK.glyph,
            RunStatus.SKIPPED.glyph,
            RunStatus.FAILED.glyph,
        )
        for row in range(len(lines) - 1, -1, -1):
            if any(marker in segment.text for segment in lines[row] for marker in progress):
                return row
        return None

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        height = options.height or console.height
        if height <= 0 or not self.renderables:
            return
        unbounded = options.reset_height()
        # One row for each of the "earlier runs"/"more runs" notes (see _LogTail
        # for why a row is reserved); a second row is reclaimed below when only
        # one of the two notes is needed.
        budget = max(height - 1, 1)

        # The run the pane follows: the one that is building, or (between tasks) the
        # newest one, where the work is.
        focus = self.index if self.index is not None else len(self.renderables) - 1

        # Measure runs newest-first until the region is full *and* the focus run has
        # been measured, so its anchor row is always inside the window.
        chunks: list[tuple[int, list[list[Segment]]]] = []  # newest-first
        used = 0
        anchor: tuple[int, int] | None = None  # (run index, row within that run)
        for index in range(len(self.renderables) - 1, -1, -1):
            lines = console.render_lines(self.renderables[index], unbounded, pad=True)
            if index == focus:
                row = self._anchor_row(lines)
                if row is not None:
                    anchor = (index, row)
            chunks.append((index, lines))
            used += len(lines)
            if used >= budget and (anchor is not None or index <= focus):
                break

        chunks.reverse()  # oldest of the measured runs first, i.e. display order
        flat: list[list[Segment]] = []
        offsets: dict[int, int] = {}
        for index, lines in chunks:
            offsets[index] = len(flat)
            flat.extend(lines)

        def window(rows: int) -> tuple[list[list[Segment]], int, int]:
            """Pick the visible slice and count the runs hidden above and below it."""
            if anchor is not None and anchor[0] in offsets:
                anchor_at = offsets[anchor[0]] + anchor[1]
                start = max(0, min(anchor_at - self.ANCHOR_CONTEXT, max(0, len(flat) - rows)))
            else:
                # Nothing to anchor on: the focus run has neither a running task nor
                # a finished one (its very first frame).  Show it from its root: the
                # root names the target, and the first stage is about to run there.
                start = offsets[chunks[-1][0]]
                if len(flat) - start <= rows:
                    start = max(0, len(flat) - rows)
            end = min(len(flat), start + rows)

            def run_at(position: int) -> int:
                """The run whose text covers ``position``."""
                index = chunks[0][0]
                for run_index, _ in chunks:
                    if offsets[run_index] > position:
                        break
                    index = run_index
                return index

            above = run_at(start)
            below = len(self.renderables) - 1 - run_at(max(start, end - 1))
            return flat[start:end], above, below

        visible, above_runs, below_runs = window(budget)
        if above_runs and below_runs:
            # A note at each end costs a second row; re-window so it still fits.
            visible, above_runs, below_runs = window(max(height - 2, 1))

        new_line = Segment.line()
        if above_runs:
            plural = "" if above_runs == 1 else "s"
            yield Text(f"… {above_runs} earlier {self.unit}{plural}", style="dim")
        for line in visible:
            yield from line
            yield new_line
        if below_runs:
            plural = "" if below_runs == 1 else "s"
            yield Text(f"… {below_runs} more {self.unit}{plural}", style="dim")


class ProcessingView:
    """A live Rich tree of a processing run, driven by the event bus.

    Owns the single :class:`~rich.live.Live` used during a CLI run -- so the tree,
    the live status line and the progress bar share one render loop -- and renders
    each target's run as ``target -> stage -> task`` with status glyphs, clickable
    links and a live log pane.  It is the CLI counterpart of the GUI's tree.

    Its *only* input is :mod:`starbash.events` (``process.target``, ``run.*``,
    ``task.*``, ``tool.*``, ``reindex.*`` and ``stage.result``).  Neither the core
    nor the tools draw anything: two Rich ``Live`` displays on one console tear
    each other apart, so the one bar on screen is this view's, and it is driven by
    the events rather than by ``Processing`` (see ``doc/plans/cli-live-display.md``).

    The screen is split with a :class:`~rich.layout.Layout`:

    * a *pinned* header on top -- the spinner, the current target/stage/task, the
      tool being run with its percentage, and the phase progress bar (files
      indexed, targets planned, or the tasks of the current doit run);
    * the main body below it, in two panes: a scrolling log of the tools' own
      output on the *left* (stderr and "bad word" lines red), and the run trees
      on the *right*, scrolled so the task that is currently building stays
      visible.

    That split is what keeps the status line on screen.  A full run has hundreds
    of ``Master ...`` runs, so the combined tree is hundreds of lines tall; Rich
    crops a too-tall live renderable from the *top*, so a single ``Group`` used
    to throw away the status line and leave only its red ``...`` overflow marker.

    On a narrow terminal the two body panes stack instead of sitting side by
    side, so neither the log nor the tree is lost.

    When the output is **not** an interactive terminal (a pipe, a file redirect,
    a "dumb" terminal or a test harness), a live tree would render nothing until
    it stops -- and even then it carries no plain status words -- so tools
    watching our output would see no results.  In that case the view skips
    ``Live`` entirely and prints a flat :func:`~starbash.rich.runs_to_table`
    summary on :meth:`finish` instead.
    """

    #: How many tool output lines the log pane keeps (a bounded scrollback, not
    #: just the last few: a run is minutes long and the interesting line is
    #: usually the one that scrolled past).
    LOG_LINES = 500

    #: Below this width the log and the run tree stack instead of sitting side
    #: by side, because two ~30-column panes are unreadable.
    MIN_SIDE_BY_SIDE_WIDTH = 100

    #: Below this terminal height there is no point splitting at all.
    MIN_SPLIT_HEIGHT = 6

    def __init__(self, title: str, console: Console) -> None:
        self.title = title
        self.console = console
        # The header's single progress bar.  The view owns it -- the core
        # publishes events and draws nothing -- and points it at whatever phase
        # is running: files being indexed, targets being planned, or the tasks of
        # the current doit run.  It starts indeterminate (pulsing, "0/?") and
        # every phase that knows its size gives it a total.
        self.progress = Progress(
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            refresh_per_second=4,
        )
        self._bar = self.progress.add_task("Starting...", total=None)
        # What the bar is currently counting; a *change* of phase restarts it.
        self._bar_phase: str | None = None
        # This run's task counts, kept here rather than read back off the bar: a
        # merge phase can sit on the bar for a while (see EVENT_MERGE_PROGRESS)
        # without the run's tasks stopping progressing underneath it.
        self._tasks_done = 0
        self._tasks_total = 0
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
        # The log pane's bounded scrollback: every tool line for the whole run,
        # so a stack that has been running for minutes can still be read back.
        self._log: deque[Text] = deque(maxlen=self.LOG_LINES)
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
            if kind == events.EVENT_PROCESS_TARGET:
                # Planning is measurable in targets: how many we have built task
                # graphs for so far (the run phase then re-points the bar at the
                # tasks of the current target).
                self._set_bar(
                    "planning",
                    "Planning",
                    completed=int(data.get("index") or 1) - 1,
                    total=int(data.get("total") or 0),
                )
        elif kind == events.EVENT_TASKS_PLANNED:
            # The size of the doit run that is about to start.  Exactly this many
            # task.finished events follow (a task that is already up to date, or
            # ignored, reports too), so it is the bar's total.  There is one run
            # per target, so the bar measures the current target while the caption
            # carries the overall "Target 2/5".
            self._tasks_total = int(data.get("tasks") or 0)
            self._tasks_done = 0
            self._set_bar("tasks", "Processing tasks", total=self._tasks_total)
        elif kind == events.EVENT_TASK_STARTED:
            self._note_run(data)
            self._set_status(self._task_caption(data))
        elif kind == events.EVENT_TASK_FINISHED:
            self._note_run(data)
            self._advance_bar()
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
            # The scrollback is kept across tools: it is the run's log, so a tool
            # starting only adds a separator to say whose output follows.
            self._log_separator(self._tool)
        elif kind == events.EVENT_TOOL_OUTPUT:
            stream = str(data.get("stream") or "")
            # Structured streams (e.g. "stdout.json") are protocol frames, not log
            # text; their useful content already arrives as EVENT_TOOL_PROGRESS.
            if not events.is_structured_stream(stream):
                self._add_log_line(str(data.get("line") or ""), is_stderr=stream == "stderr")
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
        elif kind == events.EVENT_REINDEX_PROGRESS:
            # The pre-run index pass (see Processing.reindex_if_needed) reports the
            # same events as `sb repo reindex`, so the caption shows whose files are
            # being scanned rather than a bare "starting up" pause.  The counts go
            # on the bar, not in the caption: otherwise the header's two lines
            # print the same numbers twice.
            repo = str(data.get("repo") or "")
            self._set_status(f"Indexing {repo}")
            self._set_bar(
                f"indexing:{repo}",
                "Indexing files",
                completed=int(data.get("done") or 0),
                total=int(data.get("total") or 0),
            )
        elif kind == events.EVENT_REINDEX_FINISHED:
            self._set_status(f"Indexed {data.get('indexed') or 0} file(s)")
        elif kind == events.EVENT_MERGE_PROGRESS:
            # A stage is collecting its input frames into one merged sequence
            # (recipes' `merge_to`): a symlink per frame, so it can be slow and it
            # reports its own counts.  Only the bar moves -- the caption keeps the
            # running task, which is what the merge is working on.
            self._set_bar(
                f"merge:{data.get('name') or ''}",
                "Collecting inputs",
                completed=int(data.get("done") or 0),
                total=int(data.get("total") or 0),
            )
        elif kind == events.EVENT_MERGE_FINISHED:
            # The merged sequence is ready and the stage's own tool runs next, so
            # hand the bar back to the run's tasks: they are what progresses now,
            # and leaving a full "Collecting inputs" bar up would read as done for
            # the whole (much longer) tool run.
            self._set_bar(
                "tasks",
                "Processing tasks",
                completed=self._tasks_done,
                total=self._tasks_total,
            )

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

    def _set_bar(
        self, phase: str, description: str, completed: int = 0, total: int | None = None
    ) -> None:
        """Point the header's one bar at the phase that is running now.

        ``phase`` names the metric being counted (files indexed, targets planned,
        tasks run).  Repeating a phase only moves the counts, so a phase's clock
        keeps running while its events stream in -- it is a *change* of phase that
        restarts the bar.  Rich cannot move a task back to an unknown total, so a
        phase that reports no total leaves the previous one in place (and the bar
        keeps pulsing until some phase does know its size).
        """
        if not total:
            self.progress.update(self._bar, description=description)
            return
        if phase == self._bar_phase:
            self.progress.update(
                self._bar, description=description, completed=completed, total=total
            )
        else:
            self._bar_phase = phase
            self.progress.reset(
                self._bar, description=description, completed=completed, total=total, start=True
            )

    def _advance_bar(self) -> None:
        """Count one finished task, never past the end of the current run.

        The count lives in the view rather than being read back off the bar: a
        merge phase may be holding the bar while the run's tasks continue (see
        ``EVENT_MERGE_PROGRESS``), so only the *tasks* phase is drawn here.
        """
        if not self._tasks_total:
            # No planned size: an over-full bar would draw past its column, and an
            # indeterminate one has nothing to advance.
            return
        self._tasks_done = min(self._tasks_done + 1, self._tasks_total)
        if self._bar_phase == "tasks":
            self.progress.update(self._bar, completed=self._tasks_done)

    def _clear_tool(self) -> None:
        """Forget the running tool (and its progress) - the log stays visible."""
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

    def _add_log_line(self, line: str, is_stderr: bool) -> None:
        """Append one tool output line to the live log pane."""
        if not line.strip():
            return
        self._log.append(log_line_to_text(line, is_stderr=is_stderr))

    def _log_separator(self, label: str) -> None:
        """Announce a new tool in the log pane, so the scrollback stays readable."""
        self._log.append(Text(f"──── {label} " + "─" * 24, style="dim", no_wrap=True))

    def _render(self) -> RenderableType:
        """The whole view: header on top, the log left and the run tree right.

        Snapshot the mutable state up front: Live's refresh thread may render
        this while the thread folding events mutates it (``list()``/dict lookups
        are atomic).
        """
        title = Text(self.title, style="bold")
        status = self._status_renderable()
        # Measure the header so the body gets exactly the rows left over.  Rich
        # hands a region's renderable its own height, which is what lets the two
        # body panes pick the lines that fit.
        # ``console.options`` carries no height (only ``max_height``), so this
        # measures the header at its natural height.
        header_height = 1 + len(self.console.render_lines(status, self.console.options, pad=False))
        height = self.console.height
        if height < self.MIN_SPLIT_HEIGHT:
            # No room to split: the status is the only thing worth showing.
            return Group(title, status)
        header_height = min(header_height, height - 1)

        labels = [t for t in list(self._order) if t in self._runs]
        log = _LogTail(list(self._log))
        runs = _RunWindow(
            [run_tree_to_rich(self._runs[t]) for t in labels],
            index=self._building_index(labels),
        )

        body = Layout(name="body", ratio=1, minimum_size=1)
        if self.console.width >= self.MIN_SIDE_BY_SIDE_WIDTH:
            body.split_row(
                Layout(log, name="log", ratio=3, minimum_size=20),
                Layout(runs, name="tree", ratio=2, minimum_size=20),
            )
        else:
            # A narrow terminal: stack the panes rather than lose one of them.
            body.split_column(
                Layout(log, name="log", ratio=1, minimum_size=2),
                Layout(runs, name="tree", ratio=1, minimum_size=2),
            )

        layout = Layout()
        layout.split_column(
            Layout(Group(title, status), name="status", size=header_height),
            body,
        )
        return layout

    def _building_index(self, labels: Sequence[str]) -> int | None:
        """Index (into ``labels``) of the run holding the task that is building.

        Drives the right-hand pane's scrolling: while a stage runs the tree should
        show that task, not the (far more numerous) finished ones.  ``None`` when
        nothing is running -- between tasks -- and the pane then follows the newest
        run via its last finished row.

        Newest-first: task events (which now carry the running snapshot) are the
        only source of a ``running`` node, and a run whose last task was never
        recorded can leave one behind -- it must not pin the pane to a stale run.
        """
        for index in range(len(labels) - 1, -1, -1):
            run = self._runs.get(labels[index])
            if not isinstance(run, dict):
                continue
            for stage in run.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                if stage.get("status") == RunStatus.RUNNING:
                    return index
                for task in stage.get("tasks") or []:
                    if isinstance(task, dict) and task.get("status") == RunStatus.RUNNING:
                        return index
        return None

    def __rich__(self) -> RenderableType:
        """Render for :class:`~rich.live.Live`, which re-renders us on each refresh."""
        return self._render()

    def _status_renderable(self) -> RenderableType:
        """The live status line and the phase progress bar (the pinned header)."""
        if self._finished:
            # The frame that stays on screen (Live leaves the last one behind).
            if self._failure:
                head: RenderableType = Text.assemble(("✗", "red"), " ", self._status_text())
            else:
                head = Text.assemble(("✓", "green"), " ", self._status_text())
        else:
            head = Spinner("arc", text=self._status_text(), speed=2.0, style=SPINNER_STYLE)
        return Group(head, self.progress)

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
        with view, Processing(sb) as proc:
            if session_num is not None:
                console.print(
                    f"[red]Session number base filtering not yet implemented: {session_num}...[/red]"
                )
            else:
                proc.reindex_if_needed()
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
        with view, Processing(sb) as proc:
            proc.reindex_if_needed()
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
