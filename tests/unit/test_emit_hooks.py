"""Tests that the core emit seams actually publish events (Phase 0).

These verify the *producers* wire into the event bus.  They assert on the real
payloads observed by a subscriber rather than on a mock "was called".
"""

import io

import pytest
from doit.task import Task

from starbash import events
from starbash.doit import MyReporter


@pytest.fixture(autouse=True)
def _clean_bus():
    """Every test gets a pristine event bus."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


@pytest.fixture
def recorder():
    """Return a list plus a helper to collect every published event into it."""
    captured: list[events.Event] = []
    events.subscribe(captured.append)
    return captured


def _kinds(captured: list[events.Event]) -> list[str]:
    return [event.kind for event in captured]


def test_tool_run_streaming_publishes_lifecycle_output_and_progress(tmp_path, recorder):
    """Running an external tool emits start/finish, per-line output, and progress."""
    from starbash.tool.base import tool_run_streaming

    tool_run_streaming("echo 'working 42%'", str(tmp_path))

    kinds = _kinds(recorder)
    assert events.EVENT_TOOL_STARTED in kinds
    assert events.EVENT_TOOL_FINISHED in kinds

    output_lines = [
        event.data["line"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT
    ]
    assert any("42%" in line for line in output_lines)

    progress = [event for event in recorder if event.kind == events.EVENT_TOOL_PROGRESS]
    assert progress, "a percentage in the output should produce a progress event"
    assert progress[0].data["percent"] == 42

    finished = next(event for event in recorder if event.kind == events.EVENT_TOOL_FINISHED)
    assert finished.data["returncode"] == 0
    assert finished.data["success"] is True


def test_tool_run_streaming_captures_stderr_separately(tmp_path, recorder):
    """stderr lines are still published, tagged with their stream name."""
    from starbash.tool.base import tool_run_streaming

    tool_run_streaming("echo oops 1>&2", str(tmp_path))

    stderr_lines = [
        event.data["line"]
        for event in recorder
        if event.kind == events.EVENT_TOOL_OUTPUT and event.data["stream"] == "stderr"
    ]
    assert any("oops" in line for line in stderr_lines)


def test_my_reporter_publishes_task_started_and_finished(recorder):
    """doit task transitions are observable so a GUI can drive a live task tree."""
    reporter = MyReporter(outstream=io.StringIO(), options={})
    reporter.processing = None
    task = Task("stack_lights", [])

    reporter.execute_task(task)
    reporter.add_success(task)

    started = [event for event in recorder if event.kind == events.EVENT_TASK_STARTED]
    finished = [event for event in recorder if event.kind == events.EVENT_TASK_FINISHED]

    assert started and started[0].data["task"] == "stack_lights"
    assert finished and finished[0].data["success"] is True
    assert finished[0].data["task"] == "stack_lights"


def test_reindex_repo_publishes_progress_and_finished(setup_test_environment, mock_analytics, recorder):
    """Indexing a repo reports coarse progress and a final count."""
    from starbash.app import Starbash

    with Starbash() as app:
        repo_dir = setup_test_environment["tmp_path"] / "img_repo"
        repo_dir.mkdir()
        (repo_dir / "starbash.toml").write_text("[repo]\nkind = 'images'\n")

        repo = app.user_repo.add_repo_ref(app.repo_manager, repo_dir)
        assert repo is not None

        recorder.clear()  # ignore any events from app construction
        app.reindex_repo(repo)

    kinds = _kinds(recorder)
    assert events.EVENT_REINDEX_PROGRESS in kinds
    assert events.EVENT_REINDEX_FINISHED in kinds

    progress = next(event for event in recorder if event.kind == events.EVENT_REINDEX_PROGRESS)
    assert progress.data["total"] == 0  # empty repo: no FITS files
    finished = next(event for event in recorder if event.kind == events.EVENT_REINDEX_FINISHED)
    assert finished.data["indexed"] == 0
