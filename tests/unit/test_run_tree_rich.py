"""Tests for the Rich run-tree renderer and the CLI's live ProcessingView."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from starbash import events
from starbash.commands.process import ProcessingView
from starbash.rich import run_tree_to_rich

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
