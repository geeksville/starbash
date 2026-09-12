"""Tests for the Rich run-tree renderer and the CLI's live ProcessingView."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from starbash import events
from starbash.commands.process import ProcessingView
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


class TestSupportsLiveDisplay:
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
