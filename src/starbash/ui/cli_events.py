"""The CLI's event-bus handlers: what a front end makes of the core's events.

The core never draws to the terminal -- it *publishes* on :mod:`starbash.events`
and a front end renders, so one core path can feed the CLI's live display, the
GUI's widgets and a parsed log alike.

Every CLI handler of that bus is a :class:`CliEventHandler`, which owns the
lifecycle (subscribe/unsubscribe), the *policy* (a live frame is only painted on
a real terminal) and the run model (the ``run`` snapshots the bus carries).  What
differs is what they paint, so the views stay with their own commands:

* :class:`~starbash.ui.cli.ReindexView` -- a bare repo scan's bar;
* :class:`~starbash.commands.process.ProcessingView` -- a processing run's live
  tree (``sb process auto`` / ``sb process masters``);
* :class:`SimpleLoggingEventHandler` (here) -- the fallback for output that cannot
  animate at all, which reports the same run as plain lines on that same console.

:mod:`starbash.ui.qt` is the GUI's counterpart of all of this.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

from rich.console import Console
from rich.live import Live

from starbash import events
from starbash.rich import runs_to_table, supports_live_display

__all__ = ["CliEventHandler", "SimpleLoggingEventHandler"]


class CliEventHandler:
    """What every CLI observer of the core's event bus has in common.

    Subclasses differ in what they *draw* -- one progress bar, a live tree, or
    nothing but log lines -- so this base owns only what they must agree on:

    * the **lifecycle**: subscribe on ``__enter__``, unsubscribe on ``__exit__``,
      and own at most one :class:`~rich.live.Live` for the duration (two live
      displays on one console tear each other apart);
    * the **policy** that a live frame is painted *only* on a real terminal: on a
      pipe, a redirect, a dumb terminal or a test harness Rich's ``Live`` renders
      nothing at all, so :meth:`_make_live` returning ``None`` is what selects the
      subclass's plain fallback;
    * the **run model**: the ``run`` snapshots the bus carries are folded into
      :attr:`_runs` / :attr:`_order` -- the same plain dicts the GUI's run tree
      uses -- from which :meth:`print_summary` renders the flat, scrapeable table.

    Subclasses implement :meth:`_on_event`, and usually :meth:`_on_finish` too.
    :meth:`finish` is idempotent and is called for them when the ``with`` block
    ends, so a handler that never calls it explicitly (a crash, or a command that
    forgot) still settles.
    """

    #: How often a live frame repaints while the handler runs.
    REFRESH_PER_SECOND = 4

    def __init__(self, title: str, console: Console) -> None:
        self.title = title
        self.console = console
        self._subscriber: events.Subscriber = self._on_event
        self._finished = False
        #: Set by ``__exit__`` when the caller's block raised: a view must not
        #: repaint its final frame as "done" for a run that died mid-flight.
        self._aborted = False
        # The run snapshots, in first-seen order: this handler's copy of the tree.
        self._runs: dict[str, dict] = {}
        self._order: list[str] = []
        #: The one Live this handler owns, or None on a sink that cannot animate.
        self._live: Live | None = self._make_live() if supports_live_display(console) else None

    # -- subclass hooks ----------------------------------------------------

    def _make_live(self) -> Live | None:
        """The live frame to paint while running, or ``None`` to paint none.

        Only called for a real terminal.  A view that renders itself returns
        ``Live(self, ...)``, so its own ``__rich__`` is what the refresh thread
        re-renders; a handler whose output is just lines -- the run as it happens,
        a flat table at the end -- keeps the default ``None``.

        Constructing the ``Live`` here is safe: it stores its renderable and does
        not render it until :meth:`__enter__` starts it.
        """
        return None

    def _on_event(self, event: events.Event) -> None:
        """Fold one bus event into this handler's output."""
        raise NotImplementedError

    def _on_finish(self) -> None:
        """Emit the last, static output of a finished run.

        The default does nothing: a live view's final frame *is* its output, and
        setting :attr:`_finished` plus the repaint Rich does as ``Live`` stops is
        all that takes.
        """

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Self:
        events.subscribe(self._subscriber)
        if self._live is not None:
            self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        events.unsubscribe(self._subscriber)
        self._aborted = exc_type is not None
        # Settle *before* the frame stops: Live repaints once more as it stops, so
        # the finished frame (never a bar frozen at whatever percentage the last
        # work reached) is what stays on screen.
        self.finish()
        if self._live is not None:
            self._live.stop()
        return False

    @property
    def interactive(self) -> bool:
        """True while this handler owns a live frame, i.e. on a real terminal."""
        return self._live is not None

    def finish(self) -> None:
        """Mark the run over and emit the final, static output (once)."""
        if self._finished:
            return
        self._finished = True
        self._on_finish()
        self._refresh()

    def _refresh(self) -> None:
        """Repaint the live frame now (a no-op when this handler has none)."""
        if self._live is None:
            return
        try:
            self._live.refresh()
        except Exception:  # noqa: BLE001 - rendering must never break a run
            pass

    @classmethod
    def for_console(cls, title: str, console: Console) -> CliEventHandler:
        """The handler that fits ``console``: a live view, or plain lines.

        A live display renders nothing on a sink that cannot animate (a pipe, a
        redirect, a dumb terminal, a test harness), which used to mean that a
        redirected run lost every line its live view would have shown.  Those
        sinks get :class:`SimpleLoggingEventHandler` instead, and the view's flat
        summary table is printed either way.
        """
        if supports_live_display(console):
            return cls(title, console)
        return SimpleLoggingEventHandler(title, console)

    # -- the run model, shared by the views and the summary ---------------

    def _note_run(self, data: dict) -> None:
        """Fold a payload's run snapshot (or bare target) into the run model."""
        run = data.get("run")
        target: str | None = None
        if isinstance(run, dict):
            target = str(run.get("target") or "masters")
            self._runs[target] = run
        elif data.get("target"):
            target = str(data["target"])
        if target is None:
            return  # nothing to learn (e.g. a stage result with no run snapshot)
        if target not in self._order:
            self._order.append(target)

    def _drop_runs(self, data: dict) -> None:
        """Drop culled master runs (ones no selected target needs) from the tree."""
        for label in data.get("drop", []):
            self._runs.pop(label, None)
            if label in self._order:
                self._order.remove(label)

    def runs(self) -> list[dict]:
        """The run snapshots seen so far, in first-seen order."""
        return [self._runs[t] for t in self._order if t in self._runs]

    def print_summary(self) -> None:
        """Emit the flat, line-oriented table of every known run's tasks.

        A live tree reads well on a terminal but cannot be parsed, and it renders
        nothing at all on a sink that cannot animate -- so this is the CLI's
        stable, scrapeable result (see :func:`starbash.rich.runs_to_table`).
        """
        runs = self.runs()
        if not runs:
            # Nothing observed a run snapshot, so there is no result to tabulate --
            # and an empty table ("No results") under a title would read as a
            # finding rather than as silence.  A repo scan lands here: its output is
            # the per-repo lines it printed as it went (see ReindexView).
            return
        self.console.print(self.title, style="bold")
        self.console.print(runs_to_table(runs))

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


class SimpleLoggingEventHandler(CliEventHandler):
    """A run reported as plain lines, for output that cannot be animated.

    A Rich :class:`~rich.live.Live` only ever repaints a *real* terminal; with a
    pipe, a redirect (``sb process auto > run.log``), a dumb terminal or pytest's
    capture it renders nothing at all, and that is exactly the case where the lines
    matter most -- the redirect *is* the log the user is going to read afterwards.
    Commands therefore pick this handler instead of a live view
    (see :meth:`CliEventHandler.for_console`) and get the same events, written one
    plain line at a time through the console the command already prints on:

    * ``Indexing <repo>`` and ``Indexed N file(s) in <repo>`` -- a repo scan, in the
      very same wording :class:`~starbash.ui.cli.ReindexView` uses;
    * ``Target 2/5: M31`` -- which target the run is building;
    * ``Processing 9 task(s)`` -- the size of the run about to start;
    * one line per finished task -- ``Success stack: Stack lights``, or ``Failed``,
      ``Up-to-date``, ``Ignored`` (the words the summary table's Status column uses,
      so a log and the table read the same);
    * ``Running: <tool cmd>``, then that tool's output: stdout plain, stderr red
      (what the live pane paints red), and a ``stdout.json`` protocol frame skipped
      entirely -- its content arrives as a progress line instead;
    * a tool's progress *message* when it carries one.  Progress that is only a
      percentage is not printed: that would be one line per percent, noise in a file
      nobody can watch paint.

    Lines are written with markup and highlighting off, so a line is exactly the
    text a tool produced: a recipe or tool printing ``[oops]`` must not break the
    render (Rich would read it as markup and could raise) nor lose the brackets, and
    ``grep`` must find it verbatim.

    The run's result is still the flat table the live path falls back to at the end
    (see :meth:`CliEventHandler.print_summary`): the lines above tell the story as it
    happened, the table answers "what came out of this run".
    """

    def __init__(self, title: str, console: Console) -> None:
        super().__init__(title, console)
        #: Repos whose "Indexing <repo>" line has been announced.  A scan reports
        #: progress every few dozen files, so the start of a repo is said once.
        self._indexing: set[str] = set()

    def _line(self, text: str, style: str = "") -> None:
        """Write one plain line to this handler's console.

        ``markup`` and ``highlight`` are off: the text comes from recipes and tools,
        so a ``[`` in it must stay a bracket rather than start markup, and numbers or
        URLs in it must not be restyled (the reader may well be grepping for them).
        """
        self.console.print(text, style=style, markup=False, highlight=False)

    def _on_event(self, event: events.Event) -> None:
        """Write one bus event's human-readable content as a line."""
        data = event.data if isinstance(event.data, dict) else {}
        kind = event.kind
        if kind in (events.EVENT_RUN_STARTED, events.EVENT_PROCESS_TARGET):
            self._note_run(data)
            self._line(self._run_caption(data))
        elif kind == events.EVENT_TASKS_PLANNED:
            self._line(f"Processing {int(data.get('tasks') or 0)} task(s)")
        elif kind == events.EVENT_TASK_STARTED:
            self._note_run(data)
            self._line(self._task_caption(data))
        elif kind == events.EVENT_TASK_FINISHED:
            self._note_run(data)
            self._line(
                f"{self._completion_word(data)} {self._task_caption(data)}",
                style="red" if data.get("success") is False else "",
            )
        elif kind == events.EVENT_STAGE_RESULT:
            self._note_run(data)
        elif kind == events.EVENT_PREFLIGHT_FINISHED:
            self._drop_runs(data)
        elif kind == events.EVENT_TOOL_STARTED:
            self._line(f"Running: {data.get('cmd') or ''}")
        elif kind == events.EVENT_TOOL_OUTPUT:
            self._print_tool_output(data)
        elif kind == events.EVENT_TOOL_PROGRESS:
            message = data.get("message")
            if message:
                # rc-astro reports status text and sometimes a percentage; the text
                # is news, the number is not (it changes dozens of times a second).
                self._line(str(message))
        elif kind == events.EVENT_REINDEX_PROGRESS:
            repo = str(data.get("repo") or "")
            if repo and repo not in self._indexing:
                self._indexing.add(repo)
                self._line(f"Indexing {repo}")
        elif kind == events.EVENT_REINDEX_FINISHED:
            # Deliberately the same sentence ReindexView prints (including the URL
            # form of the repo), so `sb repo reindex` and a run's pre-run scan are
            # indistinguishable in a log file -- and one grep covers both.
            self._line(
                f"Indexed {int(data.get('indexed') or 0)} file(s) in {data.get('repo') or ''}"
            )

    def _print_tool_output(self, data: dict[str, Any]) -> None:
        """Print one line of a tool's own output."""
        stream = str(data.get("stream") or "")
        if events.is_structured_stream(stream):
            # A machine-readable stream (rc-astro's `--json`): protocol frames, not
            # log text.  Their meaning is republished as EVENT_TOOL_PROGRESS, so
            # printing the raw frames here would only bury the log in JSON.
            return
        self._line(
            str(data.get("line") or "").rstrip("\n"), style="red" if stream == "stderr" else ""
        )

    def _completion_word(self, data: dict[str, Any]) -> str:
        """The one word a finished task earns, as the summary table spells it.

        ``success`` is ``False`` for a failure, ``True`` for a task that ran and
        ``None`` for one doit skipped -- either because its outputs were current
        (``reason == "Current"``) or because it was filtered out of this run
        ("Ignored").  The live tree shows those two differently, so the words match
        :data:`starbash.rich._STATUS_WORDS`: ``Failed``/``Success``/``Up-to-date``.
        """
        if data.get("success") is False:
            return "Failed"
        if data.get("success") is None:
            return "Ignored" if data.get("reason") == "Ignored" else "Up-to-date"
        return "Success"

    def _on_finish(self) -> None:
        """Close the log, then report the run's result the same way the live path does.

        The closing line is what makes a captured log self-contained: a scan of a
        long ``run.log`` can tell whether it is looking at a finished run or at one
        that was killed, without parsing the table below it.
        """
        if self._aborted:
            self._line(f"{self.title}: interrupted", style="red")
        else:
            self._line(f"{self.title}: done")
        self.print_summary()
