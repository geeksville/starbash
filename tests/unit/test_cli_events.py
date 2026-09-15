"""Tests for the CLI's shared event-bus handlers (``ui/cli_events.py``).

The bug these lock down: a Rich :class:`~rich.live.Live` renders nothing to a pipe,
a redirect or a dumb terminal, so ``sb process auto > run.log`` used to lose every
line its live view would have shown -- in exactly the file a user reads afterwards
to find out what went wrong.  :meth:`CliEventHandler.for_console` picks
:class:`SimpleLoggingEventHandler` for such a sink; these tests pin down what that
handler writes: plain, literal lines as the run happens, then the same flat summary
table the live path falls back to.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from starbash import events
from starbash.commands.process import ProcessingView
from starbash.ui.cli import ReindexView
from starbash.ui.cli_events import CliEventHandler, SimpleLoggingEventHandler

REPO_A = "file:///images/lights"

#: One plain run snapshot, the shape ``RunTree.to_plain()`` hands the bus.
_RUN = {
    "target": "M31",
    "stages": [
        {
            "name": "stack",
            "status": "ok",
            "tasks": [
                {"title": "Stack lights", "status": "ok", "outputs": []},
            ],
        }
    ],
}


def _console(*, terminal: bool = False) -> Console:
    """A console backed by a string: a terminal when ``terminal``, else a pipe."""
    return Console(
        file=StringIO(), width=100, no_color=True, force_terminal=terminal, legacy_windows=False
    )


def _output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[union-attr]


def _lines(console: Console) -> list[str]:
    """The output as lines, with the blank separator rows dropped."""
    return [line for line in _output(console).splitlines() if line.strip()]


class TestForConsole:
    """Which handler a command gets is decided by what the sink can draw."""

    def test_a_terminal_gets_the_command_s_own_live_view(self):
        # Each command's view renders itself, so `for_console` must hand back the
        # subclass it was called on -- not the base class.
        for cls in (ReindexView, ProcessingView):
            console = _console(terminal=True)
            handler = cls.for_console("A run", console)

            assert isinstance(handler, cls)
            assert handler._live is not None
            assert handler.interactive

    def test_a_pipe_gets_the_plain_fallback(self):
        for cls in (ReindexView, ProcessingView):
            console = _console()
            handler = cls.for_console("A run", console)

            assert type(handler) is SimpleLoggingEventHandler
            assert handler._live is None
            assert not handler.interactive


class TestSimpleLoggingEventHandler:
    """Every line a live view would have painted, as text."""

    def test_a_run_is_reported_as_lines_while_it_happens(self):
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(events.EVENT_TASKS_PLANNED, {"tasks": 9})
            events.publish(events.EVENT_PROCESS_TARGET, {"target": "M31", "index": 2, "total": 5})
            events.publish(events.EVENT_TASK_STARTED, {"title": "Stack lights", "stage": "stack"})
            events.publish(events.EVENT_TOOL_STARTED, {"cmd": "siril-cli -s -"})
            events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "stacking\n"})
            events.publish(events.EVENT_TOOL_PROGRESS, {"percent": 42, "message": "Denoising"})
            events.publish(
                events.EVENT_TASK_FINISHED,
                {"title": "Stack lights", "stage": "stack", "success": True},
            )

        assert _lines(console) == [
            "Processing 9 task(s)",
            "Target 2/5: M31",
            "stack: Stack lights",
            "Running: siril-cli -s -",
            "stacking",
            "Denoising",
            "Success stack: Stack lights",
            # No run snapshot reached this handler (a real target run publishes one
            # via run.started/task.started), so there is no table -- just the close.
            "Auto-processing: done",
        ]

    def test_task_status_words_match_the_summary_table(self):
        # A log and the table beneath it are read together, so doit's `success`/
        # `reason` pairs must come out as the words the Status column uses.
        for success, reason, word in (
            (True, None, "Success"),
            (None, "Current", "Up-to-date"),
            (None, "Ignored", "Ignored"),
            (False, None, "Failed"),
        ):
            console = _console()
            with SimpleLoggingEventHandler("Auto-processing", console):
                events.publish(
                    events.EVENT_TASK_FINISHED,
                    {
                        "title": "Stack lights",
                        "stage": "stack",
                        "success": success,
                        "reason": reason,
                    },
                )

            assert f"{word} stack: Stack lights" in _lines(console)

    def test_stderr_is_written_like_stdout(self):
        """A log file holds the tool's errors too -- the live pane's colour is extra."""
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stderr", "line": "cannot open\n"})

        assert _lines(console) == ["cannot open", "Auto-processing: done"]

    def test_tool_output_is_literal_text(self):
        """A ``[`` in tool output must stay a bracket -- Rich would read it as markup."""
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(
                events.EVENT_TOOL_OUTPUT,
                {"stream": "stdout", "line": "log: [oops] check 1/2 of file:///a\n"},
            )

        out = _output(console)
        assert "log: [oops] check 1/2 of file:///a" in out
        assert "\x1b" not in out  # nothing re-styled, nothing to strip before grepping

    def test_a_structured_stream_is_not_echoed(self):
        """``stdout.json`` frames are protocol; their content arrives as progress."""
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(
                events.EVENT_TOOL_OUTPUT, {"stream": "stdout.json", "line": '{"percent": 42}'}
            )

        assert '{"percent": 42}' not in _output(console)

    def test_a_bare_percentage_is_not_a_line(self):
        """A percentage changes dozens of times a second: that is noise in a file."""
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(events.EVENT_TOOL_PROGRESS, {"percent": 42})

        # The percentage itself earned no line; only the run's close was written.
        assert _output(console) == "Auto-processing: done\n"

    def test_the_run_ends_with_the_flat_summary_table(self):
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(
                events.EVENT_PROCESS_TARGET, {"target": "M31", "run": _RUN, "index": 1, "total": 1}
            )

        lines = _lines(console)
        assert lines[0] == "Target 1/1: M31"
        assert lines[1] == "Auto-processing: done"
        assert lines[2] == "Auto-processing"  # the table's title
        # ...and the table itself: one row per task, in the summary's own columns.
        assert lines[3].startswith("\u250f")  # the top border of a Rich table
        assert lines[-1].startswith("\u2514")  # ...and its bottom border
        row = next(line for line in lines if "Stack lights" in line)
        assert "M31" in row and "Success" in row

    def test_an_interrupted_run_says_so(self):
        console = _console()
        handler = SimpleLoggingEventHandler("Auto-processing", console)

        try:
            with handler:
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert "Auto-processing: interrupted" in _lines(console)
        assert "Auto-processing: done" not in _lines(console)

    def test_a_repo_scan_prints_its_lines_and_no_table(self):
        """A scan observes no run snapshots, so it has no result to tabulate."""
        console = _console()
        with SimpleLoggingEventHandler("Re-indexing repositories", console):
            for done in (0, 25):
                events.publish(
                    events.EVENT_REINDEX_PROGRESS, {"repo": REPO_A, "done": done, "total": 40}
                )
            events.publish(events.EVENT_REINDEX_FINISHED, {"repo": REPO_A, "indexed": 40})

        assert _lines(console) == [
            f"Indexing {REPO_A}",  # announced once, not once per progress event
            f"Indexed 40 file(s) in {REPO_A}",
            "Re-indexing repositories: done",
        ]

    def test_the_table_of_a_run_that_planned_nothing_is_omitted(self):
        """An empty table's "No results" row would read as a finding, not as silence."""
        console = _console()
        with SimpleLoggingEventHandler("Auto-processing", console):
            events.publish(events.EVENT_TASKS_PLANNED, {"tasks": 0})

        assert _lines(console) == ["Processing 0 task(s)", "Auto-processing: done"]

    def test_stops_observing_once_the_run_is_over(self):
        console = _console()
        handler = SimpleLoggingEventHandler("Auto-processing", console)

        with handler:
            pass

        events.publish(events.EVENT_TASKS_PLANNED, {"tasks": 3})

        assert "Processing 3 task(s)" not in _output(console)


class TestPrintSummary:
    """The summary is the base class's, shared by the fallback and the live views."""

    def test_nothing_is_printed_before_a_run_snapshot_is_seen(self):
        console = _console()
        handler = CliEventHandler("A run", console)

        handler.print_summary()

        assert _output(console) == ""
