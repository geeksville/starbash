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


def test_my_reporter_publishes_the_started_task_as_running(tmp_path, recorder):
    """``task.started`` carries a run snapshot with that task marked running.

    The snapshot published with a stage result is taken when the task has just
    finished, so nothing in it is running; without this one the CLI's live tree
    could never see (or scroll to) the task being worked on.
    """
    from starbash.processed_target import ProcessedTarget

    target = tmp_path / "M31"
    (target / ".starbash").mkdir(parents=True)
    (target / ".starbash" / "main.toml").write_text("[stages]\n", encoding="utf-8")
    pt = ProcessedTarget.open(target)
    reporter = MyReporter(outstream=io.StringIO(), options={})
    reporter.processing = None
    task = Task(
        "stack_lights",
        [],
        meta={"stage": {"name": "stack"}, "processed_target": pt},
    )

    try:
        reporter.execute_task(task)
    finally:
        pt.close()

    started = next(event for event in recorder if event.kind == events.EVENT_TASK_STARTED)
    run = started.data["run"]
    assert isinstance(run, dict)
    stage = next(stage for stage in run["stages"] if stage["name"] == "stack")
    assert stage["status"] == "running"
    assert [task["status"] for task in stage["tasks"]] == ["running"]


def test_my_reporter_enriches_task_events_with_stage_labels(recorder):
    """Task events carry target/stage/is_master so consumers can nest them."""
    reporter = MyReporter(outstream=io.StringIO(), options={})
    reporter.processing = None
    task = Task(
        "stack_lights",
        [],
        meta={
            "context": {"target": "M31"},
            "stage": {"name": "stack"},
            "is_master": False,
        },
    )

    reporter.execute_task(task)
    reporter.add_success(task)

    started = next(event for event in recorder if event.kind == events.EVENT_TASK_STARTED)
    assert started.data["target"] == "M31"
    assert started.data["stage"] == "stack"
    assert started.data["is_master"] is False
    finished = next(event for event in recorder if event.kind == events.EVENT_TASK_FINISHED)
    assert finished.data["target"] == "M31"
    assert finished.data["stage"] == "stack"


def test_publish_tool_progress_clamps_and_includes_message(recorder):
    """The progress helper shapes one canonical payload (percent clamped to 100)."""
    from starbash.tool.base import publish_tool_progress

    publish_tool_progress("cmd", percent=142, message="Finishing")

    event = next(event for event in recorder if event.kind == events.EVENT_TOOL_PROGRESS)
    assert event.data == {"cmd": "cmd", "percent": 100, "message": "Finishing"}


def test_rc_astro_json_progress_is_published_as_tool_progress(monkeypatch, recorder):
    """rc-astro's ``--json`` lines become EVENT_TOOL_PROGRESS events for the GUI.

    The CLI drives its own Rich bar from the same handler, but the GUI only sees
    the bus, so structured progress/status must be published there.
    """
    import tempfile

    from starbash.tool.base import Tool
    from starbash.tool.rcastro import RCAstroTool

    def fake_stream(cmd, cwd, on_line, timeout=None, log_out=None, stdout_mime=None):
        on_line('{"event":"progress","done":37.0,"eta":12.0}')
        on_line('{"event":"status","phase":"saving","message":"Saving"}')
        on_line('{"event":"info","topic":"version","cliVersion":"1.1.3"}')
        on_line("plain diagnostic")

    monkeypatch.setattr("starbash.tool.rcastro.tool_run_streaming", fake_stream)
    monkeypatch.setattr(Tool, "Preferences", {"rc-astro": {"path": "/usr/bin/rc-astro"}})

    with tempfile.TemporaryDirectory() as temp_dir:
        RCAstroTool().run(["bxt", "in.fits"], context={}, cwd=temp_dir)

    progress = [event for event in recorder if event.kind == events.EVENT_TOOL_PROGRESS]
    assert [event.data["percent"] for event in progress if "percent" in event.data] == [37]
    assert [event.data["message"] for event in progress if "message" in event.data] == [
        "Processing",
        "Saving",
    ]


def test_tool_run_streaming_tags_structured_stdout_with_its_mime(tmp_path, recorder):
    """A tool that declares its stdout mime publishes it as e.g. ``stdout.json``.

    Log renderers key off that name to drop protocol frames, while log_out still
    receives the raw lines and the generic percentage scan is unaffected.
    """
    from starbash.tool.base import tool_run_streaming

    log_path = tmp_path / "tool.log"
    with log_path.open("w") as log_out:
        tool_run_streaming(
            'echo \'{"event":"progress","done":1}\'',
            str(tmp_path),
            log_out=log_out,
            stdout_mime="json",
        )

    streams = [event.data["stream"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert streams == ["stdout.json"]
    # The raw protocol line is preserved for debugging.
    assert '{"event":"progress","done":1}' in log_path.read_text()


def test_tool_run_streaming_leaves_plain_stdout_untagged(tmp_path, recorder):
    """Without a declared mime, stdout keeps its plain ``stdout`` stream name."""
    from starbash.tool.base import tool_run_streaming

    tool_run_streaming('echo \'{"event":"progress"}\'', str(tmp_path))

    streams = [event.data["stream"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert streams == ["stdout"]


def test_rc_astro_declares_its_stdout_is_json(monkeypatch, tmp_path):
    """rc-astro always passes ``--json``, so it tells the runner stdout is json."""
    from starbash.tool.base import Tool
    from starbash.tool.rcastro import RCAstroTool

    seen: dict = {}

    def fake_stream(cmd, cwd, on_line, timeout=None, log_out=None, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("starbash.tool.rcastro.tool_run_streaming", fake_stream)
    monkeypatch.setattr(Tool, "Preferences", {"rc-astro": {"path": "/usr/bin/rc-astro"}})

    RCAstroTool().run(["bxt", "in.fits"], context={}, cwd=str(tmp_path))

    assert seen["stdout_mime"] == "json"


def test_reindex_repo_publishes_progress_and_finished(
    setup_test_environment, mock_analytics, recorder
):
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
