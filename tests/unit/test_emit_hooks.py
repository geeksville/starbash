"""Tests that the core emit seams actually publish events (Phase 0).

These verify the *producers* wire into the event bus.  They assert on the real
payloads observed by a subscriber rather than on a mock "was called".
"""

import io
import logging
import sys
import types
from pathlib import Path
from typing import Any

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


def _tool_log_record(pathname: Path, message: str, level: int = logging.INFO) -> logging.LogRecord:
    """Build a log record that looks like it came from the file ``pathname``.

    A built-in tool logs with the module-level helpers (``logging.info``, as
    GraXpert does), which creates its records *on the root logger* - so the
    emitting file is the only thing that says "this is the tool's output", which
    is what ``tool_run_in_process`` matches on.
    """
    return logging.LogRecord(
        name="root",
        level=level,
        pathname=str(pathname),
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _emit(record: logging.LogRecord) -> None:
    """Deliver a synthetic record to the root logger's handlers."""
    logging.getLogger().handle(record)


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


def _tool_source(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake built-in tool package; return its directory and a module in it."""
    package_dir = tmp_path / "faketool"
    package_dir.mkdir()
    return package_dir, package_dir / "worker.py"


def test_tool_run_in_process_publishes_lifecycle_output_and_progress(tmp_path, recorder):
    """A built-in tool's log records reach observers as tool output events.

    The in-process counterpart of the streaming path: GraXpert's ``api_run`` logs
    through Python's ``logging``, so without this its output never reached the
    bus at all.
    """
    from starbash.tool.base import tool_run_in_process

    package_dir, source_file = _tool_source(tmp_path)
    log_path = tmp_path / "tool.log"

    with log_path.open("w") as log_out:
        with tool_run_in_process(
            "faketool -cmd go", source=str(package_dir), cwd=str(tmp_path), log_out=log_out
        ):
            _emit(_tool_log_record(source_file, "Starting faketool"))
            _emit(_tool_log_record(source_file, "Progress: 42%"))

    started = next(event for event in recorder if event.kind == events.EVENT_TOOL_STARTED)
    assert started.data["cmd"] == "faketool -cmd go"
    assert started.data["cwd"] == str(tmp_path)

    outputs = [event for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert [event.data["line"] for event in outputs] == ["Starting faketool", "Progress: 42%"]
    assert [event.data["stream"] for event in outputs] == ["stdout", "stdout"]

    progress = [event for event in recorder if event.kind == events.EVENT_TOOL_PROGRESS]
    assert [event.data["percent"] for event in progress] == [42]

    finished = next(event for event in recorder if event.kind == events.EVENT_TOOL_FINISHED)
    assert finished.data["success"] is True
    assert finished.data["returncode"] == 0

    # The raw lines are saved for the target's log file, exactly as an external
    # tool's captured stdout is.
    assert log_path.read_text().splitlines() == ["Starting faketool", "Progress: 42%"]


def test_tool_run_in_process_tags_warnings_as_stderr(tmp_path, recorder):
    """Warnings and errors are the tool's stderr, so the log panes colour them red."""
    from starbash.tool.base import tool_run_in_process

    package_dir, source_file = _tool_source(tmp_path)

    with tool_run_in_process("faketool", source=str(package_dir)):
        _emit(_tool_log_record(source_file, "something went wrong", logging.WARNING))

    streams = [event.data["stream"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert streams == ["stderr"]


def test_tool_run_in_process_reports_a_failure(tmp_path, recorder):
    """A tool that raises is announced as failed, and the error still propagates."""
    from starbash.tool.base import tool_run_in_process

    with pytest.raises(RuntimeError, match="boom"):
        with tool_run_in_process("faketool", source=str(tmp_path / "missing")):
            raise RuntimeError("boom")

    finished = next(event for event in recorder if event.kind == events.EVENT_TOOL_FINISHED)
    assert finished.data["success"] is False
    assert finished.data["returncode"] != 0


def test_tool_run_in_process_keeps_the_tools_lines_off_the_console(tmp_path, recorder, caplog):
    """Only the tool's *own* records are rerouted, and Starbash's keep their handlers.

    Drawing the tool's lines on the console would fight the live run display the
    observer owns (see ``doc/plans/cli-live-display.md``), so they are rendered
    from the bus instead - while Starbash's own log messages are untouched.
    """
    from starbash.tool.base import tool_run_in_process

    package_dir, source_file = _tool_source(tmp_path)

    with caplog.at_level(logging.INFO):
        with tool_run_in_process("faketool", source=str(package_dir)):
            _emit(_tool_log_record(source_file, "from the tool"))
            _emit(_tool_log_record(Path(__file__), "from starbash"))

    console_lines = [record.message for record in caplog.records]
    assert "from starbash" in console_lines
    assert "from the tool" not in console_lines

    republished = [
        event.data["line"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT
    ]
    assert republished == ["from the tool"]


def test_tool_run_in_process_restores_the_root_handlers(tmp_path, caplog):
    """The forwarder is removed again, so logging is normal once the tool returns."""
    from starbash.tool.base import tool_run_in_process

    package_dir, source_file = _tool_source(tmp_path)
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    with tool_run_in_process("faketool", source=str(package_dir)):
        assert list(root.handlers) != handlers_before  # the forwarder is installed

    assert list(root.handlers) == handlers_before

    # ...and a record from that tool is back on the console's own handlers.
    with caplog.at_level(logging.INFO):
        _emit(_tool_log_record(source_file, "after the call"))
    assert "after the call" in [record.message for record in caplog.records]


def test_builtin_graxpert_publishes_its_log_output(monkeypatch, tmp_path, recorder):
    """The in-process GraXpert tool reports like any other tool.

    Its ``api_run`` runs inside Starbash (no subprocess), so the wrapper is what
    turns its log records into the same events an external tool's stdout would.
    """
    from starbash.tool.graxpert import GraxpertBuiltinTool

    package_dir = tmp_path / "graxpert"
    package_dir.mkdir()
    api_file = package_dir / "api.py"
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_api_run(argv: list[str], json_prefs: dict[str, Any]) -> None:
        calls.append((argv, json_prefs))
        _emit(_tool_log_record(api_file, "Executing deconvolution"))

    stub = types.ModuleType("graxpert")
    stub.__file__ = str(package_dir / "__init__.py")
    setattr(stub, "api_run", fake_api_run)  # noqa: B010 - a stub module, not a real import
    monkeypatch.setitem(sys.modules, "graxpert", stub)

    commands = ["-cmd", "deconv-obj", "-output", "out.fits", "in.fits"]
    GraxpertBuiltinTool().run(commands, context={}, cwd=str(tmp_path), ai_version="1.0.1")

    # The tool parameters (recipe ``tool.parameters``) still arrive as prefs.
    assert calls == [(commands, {"ai_version": "1.0.1"})]

    started = next(event for event in recorder if event.kind == events.EVENT_TOOL_STARTED)
    assert started.data["cmd"] == "graxpert -cmd deconv-obj -output out.fits in.fits"

    outputs = [event.data["line"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert outputs == ["Executing deconvolution"]

    finished = next(event for event in recorder if event.kind == events.EVENT_TOOL_FINISHED)
    assert finished.data["success"] is True


def test_tool_run_in_process_without_a_source_reroutes_everything(tmp_path, recorder, caplog):
    """A tool whose output is emitted by Starbash's own modules has no source dir.

    The python sandbox logs a script's ``print`` from ``starbash.tool.context``
    (and Siril commands from ``starbash.sim_siril``), so nothing about such a
    record says "this is the tool" - for that call, every record is its output.
    """
    from starbash.tool.base import tool_run_in_process

    with caplog.at_level(logging.INFO):
        with tool_run_in_process("faketool", source=None):
            _emit(_tool_log_record(Path(__file__), "a line from anywhere"))

    assert "a line from anywhere" not in [record.message for record in caplog.records]
    outputs = [event.data["line"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert outputs == ["a line from anywhere"]


def test_tool_run_in_process_nested_runs_publish_each_line_once(tmp_path, recorder):
    """A tool run *inside* another does not send its lines through both.

    The outer call republishes everything (``source=None``), so each line would be
    published twice unless the inner run takes ownership of its own records.
    """
    from starbash.tool.base import tool_run_in_process

    (tmp_path / "outer").mkdir()
    (tmp_path / "inner").mkdir()
    _, outer_file = _tool_source(tmp_path / "outer")
    inner_dir, inner_file = _tool_source(tmp_path / "inner")

    with tool_run_in_process("outer", source=None):
        _emit(_tool_log_record(outer_file, "outer line"))
        with tool_run_in_process("inner", source=str(inner_dir)):
            _emit(_tool_log_record(inner_file, "inner line"))
        _emit(_tool_log_record(inner_file, "outer line about the inner tool"))

    published = [
        (event.data["cmd"], event.data["line"])
        for event in recorder
        if event.kind == events.EVENT_TOOL_OUTPUT
    ]
    assert published == [
        ("outer", "outer line"),
        ("inner", "inner line"),
        ("outer", "outer line about the inner tool"),
    ]


def test_builtin_python_tool_publishes_its_script_output(tmp_path, recorder, caplog):
    """A recipe stage written in python reports its output like any other tool.

    Both ways a script can talk - ``print``, which the sandbox turns into a log
    record via ``MyPrinter``, and the injected ``logger`` - arrive as tool output,
    so the CLI's run tree and the GUI show a python stage's work as it happens.
    """
    from starbash.tool.python import PythonTool

    script = 'print("hello from the script")\nlogger.info("logging from the script")\n'
    with caplog.at_level(logging.INFO):
        PythonTool().run(script, context={}, cwd=str(tmp_path), script_file="demo.py")

    started = next(event for event in recorder if event.kind == events.EVENT_TOOL_STARTED)
    assert started.data["cmd"] == "python demo.py"

    outputs = [event.data["line"] for event in recorder if event.kind == events.EVENT_TOOL_OUTPUT]
    assert "Script print: hello from the script" in outputs
    assert "logging from the script" in outputs
    # The tool's own line is part of that output rather than a console draw, so the
    # CLI's live display is never torn by a record rendered beside it.
    assert all("Executing python script" not in record.message for record in caplog.records)
    assert (
        next(event for event in recorder if event.kind == events.EVENT_TOOL_FINISHED).data[
            "success"
        ]
        is True
    )


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
