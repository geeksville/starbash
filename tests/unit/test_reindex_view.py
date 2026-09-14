"""Tests for the CLI's ReindexView, the observer of the ``reindex.*`` events."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from starbash import events
from starbash.ui.cli import ReindexView

REPO_A = "file:///images/lights"
REPO_B = "file:///images/masters"


def _console(*, terminal: bool = False) -> Console:
    """A console backed by a string: a terminal when ``terminal``, else a pipe."""
    return Console(
        file=StringIO(), width=100, no_color=True, force_terminal=terminal, legacy_windows=False
    )


def _render(renderable: object) -> str:
    console = Console(file=StringIO(), width=200, no_color=True)
    console.print(renderable)  # type: ignore[arg-type]
    return console.file.getvalue()  # type: ignore[union-attr]


def _progress(repo: str, done: int, total: int) -> events.Event:
    return events.Event(events.EVENT_REINDEX_PROGRESS, {"repo": repo, "done": done, "total": total})


def _finished(repo: str, indexed: int) -> events.Event:
    return events.Event(events.EVENT_REINDEX_FINISHED, {"repo": repo, "indexed": indexed})


class TestReindexView:
    """The scan reports through the bus; this is the CLI's half of that."""

    def test_shows_which_repo_is_being_scanned_and_how_far_along(self):
        view = ReindexView("Re-indexing repositories", _console(terminal=True))
        text = ""

        with view:
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": 0, "total": 40})
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": 15, "total": 40})

            text = _render(view)

        assert REPO_A in text
        assert "15/40" in text

    def test_the_bar_restarts_for_each_repo(self):
        """Repos differ wildly in size, so the bar is per folder, not a running sum."""
        view = ReindexView("Re-indexing repositories", _console(terminal=True))
        text = ""
        tasks = 0

        with view:
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": 5, "total": 5})
            events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_A, "indexed": 5})
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_B, "done": 1, "total": 4})

            text = _render(view)
            tasks = len(view._progress.tasks)

        assert REPO_B in text
        assert "1/4" in text
        assert REPO_A not in text  # the finished repo's bar is gone, not left at 100%
        assert tasks == 1

    def test_each_finished_repo_leaves_a_result_line(self):
        sio = StringIO()
        view = ReindexView("Re-indexing repositories", Console(file=sio, no_color=True, width=100))

        with view:
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": 0, "total": 7})
            events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_A, "indexed": 7})

        assert "Indexed 7 file(s) in file:///images/lights" in sio.getvalue()

    def test_a_pipe_gets_plain_lines_and_no_live_bar(self):
        """A live bar renders nothing on a pipe, so it is skipped entirely."""
        sio = StringIO()
        view = ReindexView("Re-indexing repositories", Console(file=sio, no_color=True, width=100))
        assert view._live is None

        with view:
            for repo, total in ((REPO_A, 7), (REPO_B, 0)):
                events.publish(
                    events.EVENT_REINDEX_PROGRESS, {"repo": repo, "done": 0, "total": total}
                )
                events.publish(events.EVENT_REINDEX_FINISHED, {"repo": repo, "indexed": total})

        out = sio.getvalue()
        # Plain, stable text: one line per repo, the same wording the GUI shows.
        assert out.splitlines() == [
            "Indexed 7 file(s) in file:///images/lights",
            "Indexed 0 file(s) in file:///images/masters",
        ]
        assert "\x1b" not in out  # no cursor control, no bar glyphs

    def test_the_last_frame_reports_what_was_indexed(self):
        """``finish()`` replaces the bar (frozen at some %) with the totals."""
        view = ReindexView("Re-indexing repositories", _console(terminal=True))
        text = ""

        with view:
            events.publish(events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": 1, "total": 9})
            events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_A, "indexed": 9})
            view.finish()

            text = _render(view)

        assert "Re-indexing repositories" in text
        assert "1 repo(s), 9 file(s) indexed" in text
        assert REPO_A not in text  # the bar is gone

    def test_stops_observing_once_the_scan_is_over(self):
        sio = StringIO()
        view = ReindexView("Re-indexing repositories", Console(file=sio, no_color=True, width=100))

        with view:
            events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_A, "indexed": 1})

        events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_B, "indexed": 1})

        assert "file:///images/masters" not in sio.getvalue()

    def test_ignores_unrelated_events(self):
        sio = StringIO()
        view = ReindexView("Re-indexing repositories", Console(file=sio, no_color=True, width=100))

        with view:
            events.publish(events.EVENT_TOOL_STARTED, {"cmd": "siril-cli"})

        assert sio.getvalue() == ""
