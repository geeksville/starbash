"""Tests for the Rich run-tree renderer and the CLI's live ProcessingView."""

from __future__ import annotations

import re
from io import StringIO

from rich.console import Console

from starbash import events
from starbash.commands.process import ProcessingView, tool_label
from starbash.rich import run_tree_to_rich, runs_to_table, supports_live_display

_RUN = {
    "target": "M31",
    "output_url": "file:///out",
    "stages": [
        {
            "name": "calibrate",
            "status": "ok",
            "excluded": False,
            "dependencies": [],
            "outputs": [{"label": "pp.fits", "url": "file:///out/pp.fits"}],
            "logs": [],
            "tasks": [],
        },
        {
            "name": "stack",
            "status": "ok",
            "excluded": False,
            "dependencies": ["calibrate"],
            "outputs": [{"label": "stack.fits", "url": "file:///out/stack.fits"}],
            "logs": ["working 42%"],
            "tasks": [
                {
                    "name": "stack",
                    "title": "Stack lights",
                    "status": "ok",
                    "session": "2024-01-01:osc",
                    "outputs": [],
                    "logs": [],
                }
            ],
        },
        {"name": "denoise", "status": "excluded", "excluded": True, "tasks": []},
    ],
}


def _render(renderable: object) -> str:
    console = Console(file=StringIO(), width=240, no_color=True)
    console.print(renderable)  # type: ignore[arg-type]
    return console.file.getvalue()  # type: ignore[union-attr]


def _render_at(renderable: object, width: int, height: int) -> list[str]:
    """Render to the exact rows a terminal of this size would show.

    Returns one string per *row* of the screen (never more than ``height``), so
    a test can prove the live view fits instead of overflowing.
    """
    console = Console(
        file=StringIO(), width=width, height=height, force_terminal=True, no_color=True
    )
    lines = console.render_lines(renderable, console.options.update_width(width))  # type: ignore[arg-type]
    return ["".join(segment.text for segment in line).rstrip() for line in lines]


class TestRunTreeToRich:
    def test_renders_stages_tasks_deps_and_links(self):
        text = _render(run_tree_to_rich(_RUN))

        assert "M31" in text
        assert "calibrate" in text
        assert "Stack lights" in text
        assert "stack.fits" in text
        assert "working 42%" in text
        assert "← calibrate" in text  # dependency annotation
        assert "denoise (excluded)" in text

    def test_renders_bracketed_log_lines_literally(self):
        # A tool line containing "[" used to be parsed as markup inside the live
        # display's refresh thread, raising MarkupError and freezing the view.
        run = {**_RUN, "stages": [{**_RUN["stages"][1], "logs": ["loading [oops] frame"]}]}

        assert "loading [oops] frame" in _render(run_tree_to_rich(run))


class TestToolLabel:
    def test_direct_command_uses_its_basename(self):
        assert tool_label("/usr/bin/siril-cli -d /tmp/x -s -") == "siril-cli"

    def test_flatpak_launcher_reports_the_app_not_the_launcher(self):
        cmd = "flatpak run --command=siril-cli org.siril.Siril -d /tmp/abc -s -"

        assert tool_label(cmd) == "Siril"

    def test_plain_command_keeps_its_name(self):
        assert tool_label("rc-astro bxt --output /tmp/x.tif") == "rc-astro"

    def test_unparseable_command_falls_back_to_the_raw_line(self):
        assert tool_label("   ") == "   "

    def test_false_for_captured_non_terminal_output(self):
        assert supports_live_display(Console(file=StringIO(), no_color=True)) is False

    def test_true_for_a_real_terminal(self):
        console = Console(file=StringIO(), force_terminal=True, no_color=True)
        assert supports_live_display(console) is True


class TestRunsToTable:
    def test_lists_plain_status_words_and_stage_outputs(self):
        text = _render(runs_to_table([_RUN], title="Results"))

        assert "Results" in text
        assert "Success" in text  # the stable word tools scrape for
        assert "Excluded" in text
        assert "Stack lights" in text
        assert "pp.fits" in text  # a stage with no tasks still shows its outputs
        assert "✓" not in text  # no live-tree glyphs in the flat table

    def test_empty_runs_render_a_placeholder(self):
        assert "No results" in _render(runs_to_table([]))

    def test_ignores_non_dict_runs(self):
        assert "No results" in _render(runs_to_table([None, "nope", 3]))


class TestProcessingView:
    def test_accumulates_runs_from_events(self):
        view = ProcessingView("Test run", Console(file=StringIO(), no_color=True))

        view._on_event(events.Event(events.EVENT_RUN_STARTED, {"target": "M31"}))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))

        assert view._order == ["M31"]
        assert "M31" in view._runs

    def test_ignores_stage_results_without_a_run_snapshot(self):
        view = ProcessingView("Test run", Console(file=StringIO(), no_color=True))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": None}))
        assert view._order == []
        assert view._runs == {}

    def test_render_includes_every_known_target(self):
        view = ProcessingView("Live", Console(file=StringIO(), no_color=True))
        view._on_event(events.Event(events.EVENT_RUN_STARTED, {"target": "M31"}))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))

        text = _render(view._render())
        assert "Live" in text
        assert "M31" in text

    def test_preflight_finished_drops_unneeded_master_runs(self):
        view = ProcessingView("Test run", Console(file=StringIO(), no_color=True))
        view._on_event(events.Event(events.EVENT_RUN_STARTED, {"target": "Master bias"}))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))
        view._on_event(events.Event(events.EVENT_RUN_STARTED, {"target": "Master flat"}))
        view._on_event(
            events.Event(events.EVENT_STAGE_RESULT, {"run": {**_RUN, "target": "Master flat"}})
        )
        assert set(view._runs) == {"M31", "Master flat"}

        view._on_event(events.Event(events.EVENT_PREFLIGHT_FINISHED, {"drop": ["Master flat"]}))

        assert "Master flat" not in view._runs
        assert "Master flat" not in view._order
        assert "M31" in view._runs

    def test_preflight_finished_with_unknown_label_is_harmless(self):
        view = ProcessingView("Test run", Console(file=StringIO(), no_color=True))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))

        view._on_event(events.Event(events.EVENT_PREFLIGHT_FINISHED, {"drop": ["Nope"]}))

        assert "M31" in view._runs

    def test_dumb_sink_skips_live_and_prints_a_flat_table(self):
        sio = StringIO()
        view = ProcessingView("Auto-processing", Console(file=sio, no_color=True, width=200))
        assert view._live is None  # a pipe/capture cannot drive a live display

        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))
        with view:
            view.finish()

        out = sio.getvalue()
        assert "Auto-processing" in out
        assert "Success" in out  # stable word tools scrape for
        assert "Stack lights" in out
        assert "✓" not in out  # no live-tree glyphs when we cannot animate

    def test_finish_prints_the_dumb_table_exactly_once(self):
        sio = StringIO()
        view = ProcessingView("Test run", Console(file=sio, no_color=True, width=200))
        view._on_event(events.Event(events.EVENT_STAGE_RESULT, {"run": _RUN}))

        with view:
            view.finish()  # the command finishes explicitly ...
        # ... then __exit__ finishes again; the guard must not double-print.

        assert sio.getvalue().count("Success") == 2  # calibrate + stack rows

    def test_terminal_sink_still_uses_a_live_tree(self):
        console = Console(file=StringIO(), force_terminal=True, no_color=True)
        view = ProcessingView("Live", console)
        assert view._live is not None


class TestLiveStatusLine:
    """The one status line that replaced the per-tool Rich Live displays."""

    def _view(self) -> ProcessingView:
        return ProcessingView("Live", Console(file=StringIO(), no_color=True))

    def _tool_started(self, view: ProcessingView, cmd: str = "siril-cli -d /tmp -s -") -> None:
        view._on_event(events.Event(events.EVENT_TOOL_STARTED, {"cmd": cmd}))

    def test_shows_the_running_task_the_tool_and_the_percentage(self):
        view = self._view()
        view._on_event(
            events.Event(
                events.EVENT_TASK_STARTED,
                {"task": "stack", "title": "Stack lights", "stage": "stack"},
            )
        )
        self._tool_started(view, "flatpak run --command=siril-cli org.siril.Siril -d /tmp -s -")
        view._on_event(events.Event(events.EVENT_TOOL_PROGRESS, {"cmd": "c", "percent": 42}))

        text = _render(view._render())

        assert "stack: Stack lights" in text
        assert "Siril" in text  # the tool label, not the whole command line
        assert "42%" in text

    def test_message_only_progress_keeps_the_last_percentage(self):
        view = self._view()
        self._tool_started(view, "rc-astro")
        view._on_event(events.Event(events.EVENT_TOOL_PROGRESS, {"percent": 70}))
        # rc-astro's status events carry no percentage: it must not reset the bar.
        view._on_event(events.Event(events.EVENT_TOOL_PROGRESS, {"message": "Denoising"}))

        text = _render(view._render())

        assert "70%" in text
        assert "Denoising" in text

    def test_failed_task_is_called_out_where_the_task_was(self):
        view = self._view()
        view._on_event(
            events.Event(events.EVENT_TASK_STARTED, {"task": "stack", "title": "Stack lights"})
        )
        view._on_event(
            events.Event(events.EVENT_TASK_FINISHED, {"title": "Stack lights", "success": False})
        )

        text = _render(view._render())

        assert "Failed: Stack lights" in text

    def test_successful_task_leaves_the_running_caption_alone(self):
        view = self._view()
        view._on_event(events.Event(events.EVENT_TASK_STARTED, {"title": "Calibrate"}))
        view._on_event(
            events.Event(events.EVENT_TASK_FINISHED, {"title": "Calibrate", "success": True})
        )

        assert "Failed" not in _render(view._render())

    def test_tool_output_keeps_only_the_last_few_lines(self):
        view = self._view()
        self._tool_started(view)
        for i in range(5):
            view._on_event(
                events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": f"line {i}"})
            )

        text = _render(view._render())

        assert "line 4" in text
        assert "line 1" not in text  # only ProcessingView.TOOL_TAIL_LINES stay visible

    def test_stderr_lines_render_red_and_stdout_lines_yellow(self):
        view = self._view()
        self._tool_started(view)
        view._on_event(events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stderr", "line": "bad"}))
        view._on_event(events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "good"}))

        assert {str(line): line.style for line in view._tail} == {"bad": "red", "good": "yellow"}

    def test_skips_structured_protocol_frames(self):
        view = self._view()
        self._tool_started(view, "rc-astro")
        view._on_event(
            events.Event(
                events.EVENT_TOOL_OUTPUT,
                {"stream": "stdout.json", "line": '{"event": "progress"}'},
            )
        )

        assert '{"event"' not in _render(view._render())

    def test_starting_a_tool_clears_the_previous_tool_tail(self):
        view = self._view()
        self._tool_started(view, "siril-cli")
        view._on_event(
            events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "old output"})
        )

        self._tool_started(view, "rc-astro")  # a new tool starts

        assert "old output" not in _render(view._render())

    def test_finish_reports_done_and_drops_the_tool(self):
        view = self._view()
        self._tool_started(view, "siril-cli")
        view.finish()

        text = _render(view._render())

        assert "Live: done" in text
        assert "siril-cli" not in text  # nothing is running any more

    def test_finish_keeps_reporting_a_failure(self):
        view = self._view()
        view._on_event(events.Event(events.EVENT_TASK_STARTED, {"title": "Calibrate"}))
        view._on_event(
            events.Event(events.EVENT_TASK_FINISHED, {"title": "Calibrate", "success": False})
        )
        view.finish()

        text = _render(view._render())

        # The last frame is what the user walks away with, so it must not claim the
        # run was fine just because a later task ran.
        assert "Failed: Calibrate" in text
        assert "done" not in text


class TestLiveLayout:
    """The status region must survive a run tree that is hundreds of lines tall.

    A real ``sb process auto`` run accumulates hundreds of ``Master ...`` runs,
    so the combined tree far exceeds the terminal.  Rich crops a too-tall live
    renderable from the *top* and marks the cut with a red ``...`` (its
    ``live.ellipsis`` style) -- which used to delete the status line, leaving
    users staring at three red dots.  The view now splits the screen so the
    status keeps its own rows and the tree region shows its newest activity.
    """

    def _view(self, runs: int, width: int = 80, height: int = 24) -> ProcessingView:
        console = Console(
            file=StringIO(), width=width, height=height, force_terminal=True, no_color=True
        )
        view = ProcessingView("Auto-processing", console)
        for i in range(runs):
            target = f"Master {i}"
            view._on_event(events.Event(events.EVENT_RUN_STARTED, {"target": target}))
            view._on_event(
                events.Event(events.EVENT_STAGE_RESULT, {"run": {**_RUN, "target": target}})
            )
        return view

    def _running(self, view: ProcessingView) -> ProcessingView:
        view._on_event(
            events.Event(events.EVENT_TASK_STARTED, {"title": "Stack lights", "stage": "stack"})
        )
        view._on_event(events.Event(events.EVENT_TOOL_STARTED, {"cmd": "rc-astro"}))
        view._on_event(events.Event(events.EVENT_TOOL_PROGRESS, {"percent": 42}))
        return view

    def test_never_renders_more_rows_than_the_terminal_has(self):
        for height in (10, 24, 50):
            for runs in (0, 1, 3, 200):
                view = self._running(self._view(runs, height=height))
                rows = _render_at(view._render(), 80, height)

                assert len(rows) == height, f"{runs} runs overflowed a {height}-row terminal"

    def test_no_overflow_ellipsis_is_drawn(self):
        # Rich's crop marker: what the users actually saw instead of the status.
        view = self._running(self._view(200))
        rows = _render_at(view._render(), 80, 24)

        assert not any("..." in row for row in rows)

    def test_status_line_and_progress_stay_pinned_with_hundreds_of_runs(self):
        view = self._running(self._view(200))
        rows = _render_at(view._render(), 80, 24)
        text = "\n".join(rows)

        # The status lives in the top region, so a tall tree cannot push it off.
        assert rows[0] == "Auto-processing"
        assert "stack: Stack lights" in text
        assert "rc-astro" in text
        assert "42%" in text

    def test_shows_the_newest_runs_and_summarises_the_rest(self):
        view = self._running(self._view(200))
        text = "\n".join(_render_at(view._render(), 80, 24))

        assert "Master 199" in text  # the most recent run is on screen ...
        assert "Master 0" not in text  # ... the oldest scrolled away ...
        assert re.search(r"… \d+ earlier runs", text)  # ... and is accounted for

    def test_a_run_list_that_fits_is_not_summarised(self):
        view = self._running(self._view(1))
        text = "\n".join(_render_at(view._render(), 80, 24))

        assert "Master 0" in text
        assert "earlier" not in text

    def test_one_run_taller_than_its_region_still_renders(self):
        # Degenerate sizing: one run alone is taller than the region, but the
        # region must still render *something* rather than collapse to nothing.
        view = self._running(self._view(1, height=10))
        rows = _render_at(view._render(), 80, 10)

        assert len(rows) == 10
        assert any("Master 0" in row for row in rows)
