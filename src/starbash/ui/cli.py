"""The CLI's own views: observers of the core's event bus.

The core never draws to the terminal -- it *publishes* on :mod:`starbash.events`
and a front end renders, so one core path can feed the CLI's live display, the
GUI's widgets and a parsed log alike.  This module holds the small view the CLI
owns outside a processing run (whose tree is
:class:`~starbash.commands.process.ProcessingView`): the lifecycle, the "live
only on a terminal" policy and the plain-logging fallback every CLI view shares
live in :class:`~starbash.ui.cli_events.CliEventHandler`, and
:mod:`starbash.ui.qt` is the GUI's counterpart of all of it.
"""

from __future__ import annotations

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.progress import Progress, TaskID
from rich.text import Text

from starbash import events
from starbash.ui.cli_events import CliEventHandler

__all__ = ["ReindexView"]


class ReindexView(CliEventHandler):
    """A live progress bar for a repository scan, driven by the event bus.

    ``sb repo reindex`` and ``sb repo add`` (which indexes the folder it was
    handed) are long operations with nothing else on screen, so they show the
    scan: :meth:`Starbash.reindex_repo` publishes ``reindex.progress`` per repo
    -- a first ``0/N`` event plus one every 25 files, so a huge folder does not
    flood the bus -- and a ``reindex.finished`` when that repo is done.  This view
    folds them into a single :class:`~rich.progress.Progress` bar, reset per repo:
    the interesting number is "how far through *this* folder", since folders
    differ wildly in size.

    A finished repo leaves a plain ``Indexed N file(s) in <repo>`` line behind
    (printed as it happens, so Rich keeps it above the live frame).  On a pipe, a
    redirect or a dumb terminal that line is the *only* output there is -- a live
    bar would render nothing at all there -- which is exactly why such sinks get
    :class:`~starbash.ui.cli_events.SimpleLoggingEventHandler` instead (see
    :meth:`CliEventHandler.for_console`).

    While it runs, this view owns the console's one :class:`~rich.live.Live`.
    That is only safe because the core owns no display of its own any more; see
    ``doc/plans/cli-live-display.md``.
    """

    #: A scan reports often and briefly, so it repaints more eagerly than a
    #: processing run does (see :attr:`CliEventHandler.REFRESH_PER_SECOND`).
    REFRESH_PER_SECOND = 8

    def __init__(self, title: str, console: Console) -> None:
        super().__init__(title, console)
        # Rendered inside our own Live (never entered standalone), so this
        # Progress starts no display of its own.
        self._progress = Progress(console=console, refresh_per_second=self.REFRESH_PER_SECOND)
        # The one bar, dropped and re-added as each repo's first event arrives.
        self._task: TaskID | None = None
        self._repo: str | None = None
        self._done = 0
        self._total = 0
        self._repos = 0
        self._files = 0

    def _make_live(self) -> Live | None:
        """Live repaints this view itself -- scanning is the whole display."""
        return Live(self, console=self.console, refresh_per_second=self.REFRESH_PER_SECOND)

    def _on_event(self, event: events.Event) -> None:
        """Fold one bus event into the bar and the per-repo result lines."""
        data = event.data if isinstance(event.data, dict) else {}
        kind = event.kind
        if kind == events.EVENT_REINDEX_PROGRESS:
            self._repo = str(data.get("repo") or "")
            self._total = int(data.get("total") or 0)
            self._done = int(data.get("done") or 0)
            # total 0 (an empty folder) would leave the bar stuck at 0%, so it is
            # reported as "unknown" and Rich pulses it instead.
            total = self._total or None
            if self._task is None:
                self._task = self._progress.add_task(self._repo, total=total)
            self._progress.update(
                self._task, description=self._repo, total=total, completed=self._done
            )
        elif kind == events.EVENT_REINDEX_FINISHED:
            repo = str(data.get("repo") or "")
            indexed = int(data.get("indexed") or 0)
            self._repos += 1
            self._files += indexed
            # Printed as it happens, not just at the end: a cancelled scan still
            # leaves a record of the repos it did get through, and on a pipe this
            # is the whole output.
            self.console.print(f"Indexed {indexed} file(s) in {repo}")
            self._drop_bar()

    def _drop_bar(self) -> None:
        """Forget the finished repo's bar, so the next repo starts from zero."""
        if self._task is not None:
            self._progress.remove_task(self._task)
            self._task = None

    def __rich__(self) -> RenderableType:
        """The live frame: what is being scanned right now, and how far along."""
        if self._finished:
            return Text(
                f"{self.title}: {self._repos} repo(s), {self._files} file(s) indexed",
                style="green",
            )
        if self._repo is None:
            return Text(f"{self.title}...", style="dim")

        caption = Text("Indexing ")
        caption.append(self._repo, style="cyan")
        caption.append(f" — {self._done}/{self._total}")
        return Group(caption, self._progress)
