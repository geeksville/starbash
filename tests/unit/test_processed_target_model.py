"""Tests for the read-only ``ProcessedTarget`` model view and run logging."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import tomlkit

from starbash.doit import FileInfo
from starbash.processed_target import ProcessedTarget
from starbash.run_state import RunStatus


def _write_target(root: Path, name: str, stages: list[tuple[str, bool]]) -> Path:
    """Create a minimal processed-target dir with a ``.starbash/main.toml``."""
    target = root / name
    (target / ".starbash").mkdir(parents=True)
    document = tomlkit.document()
    aot = tomlkit.aot()
    for stage_name, excluded in stages:
        entry = tomlkit.table()
        entry["name"] = stage_name
        if excluded:
            entry["excluded"] = True
        aot.append(entry)
    document["stages"] = aot
    (target / ".starbash" / "main.toml").write_text(tomlkit.dumps(document), encoding="utf-8")
    return target


class FakeTask:
    """A minimal duck-typed doit ``Task`` for feeding the run model."""

    def __init__(self, name: str, stage: str, deps=(), targets=()) -> None:
        self.name = name
        self.meta: dict[str, Any] = {"stage": {"name": stage}}
        self.file_dep = list(deps)
        self.targets = list(targets)

    def title(self) -> str:
        return self.name.title()


def _result(task: FakeTask, *, output: FileInfo | None = None, success: bool = True):
    context: dict[str, Any] = {}
    if output is not None:
        context["output"] = output
        context["final_output"] = output
    return SimpleNamespace(
        task=task,
        success=success,
        reason="processed",
        notes=None,
        context=context,
        session_desc="2024-01-01:osc",
    )


class TestOpenAndDiscover:
    def test_open_is_read_only_and_never_writes(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        config = target / ".starbash" / "main.toml"
        before = config.read_text(encoding="utf-8")

        pt = ProcessedTarget.open(target)

        assert pt.read_only is True
        assert pt.p is None
        assert pt.config_url is not None and pt.config_url.endswith("main.toml")
        pt.close()  # must be a no-op
        assert config.read_text(encoding="utf-8") == before

    def test_discover_finds_only_real_targets(self, tmp_path):
        _write_target(tmp_path, "M31", [("stack", False)])
        _write_target(tmp_path, "NGC7000", [("stack", False)])
        (tmp_path / "not_a_target").mkdir()  # no .starbash/main.toml

        names = [pt.name.name for pt in ProcessedTarget.discover(tmp_path)]
        assert names == ["M31", "NGC7000"]

    def test_stage_counts_and_entries(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("a", False), ("b", False), ("c", True)])
        pt = ProcessedTarget.open(target)

        assert pt.stage_counts() == (2, 1)
        assert pt.stage_entries() == [("a", False), ("b", False), ("c", True)]
class TestStageOptions:
    def test_options_merge_recipe_declarations(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)

        declarations = {
            "stack": {
                "description": "Stack lights",
                "parameters": {"sigma": {"default": 3.0, "description": "Clip sigma"}},
            }
        }
        options = pt.stage_options(declarations)

        assert [o.name for o in options] == ["stack"]
        assert options[0].description == "Stack lights"
        assert options[0].parameters[0].name == "sigma"
        assert options[0].parameters[0].default == 3.0
        assert options[0].parameters[0].is_overridden is False

    def test_save_round_trips_exclusion_and_overrides(self, tmp_path):
        from starbash.processed_target import ParameterOption

        target = _write_target(tmp_path, "M31", [("stack", False), ("denoise", True)])
        pt = ProcessedTarget.open(target)

        options = pt.stage_options({})
        options[0].excluded = True  # exclude 'stack'
        options[1].excluded = False  # include 'denoise'
        options[1].parameters.append(
            ParameterOption(name="strength", description=None, default=0.5, value=0.9)
        )
        pt.save_stage_options(options)

        reopened = ProcessedTarget.open(target)
        assert reopened.stage_counts() == (1, 1)
        round_tripped = {o.name: o for o in reopened.stage_options({})}
        assert round_tripped["stack"].excluded is True
        assert round_tripped["denoise"].excluded is False
        assert round_tripped["denoise"].parameters[0].value == 0.9


class TestRunRecording:
    def test_record_result_builds_tree_with_dependencies(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("calibrate", False), ("stack", False)])
        pt = ProcessedTarget.open(target)

        cal = FakeTask("calibrate", "calibrate", targets=["/out/pp.fits"])
        stack = FakeTask("stack", "stack", deps=["/out/pp.fits"], targets=["/out/s.fits"])

        pt.task_started(cal)
        pt.record_result(
            _result(cal, output=FileInfo(base="/out", full=Path("/out/pp.fits"), relative="pp.fits"))
        )
        pt.task_started(stack)
        pt.record_log("working")
        pt.record_result(
            _result(stack, output=FileInfo(base="/out", full=Path("/out/s.fits"), relative="s.fits"))
        )

        tree = pt.run_tree()
        assert tree is not None
        stages = {s.name: s for s in tree.stages}
        assert stages["stack"].dependencies == ["calibrate"]
        assert stages["stack"].status == RunStatus.OK
        assert [f.label for f in stages["stack"].outputs] == ["s.fits"]
        assert stages["stack"].logs == ["working"]
        # The line is attributed to the task that produced it, too (the GUI groups
        # logs under each subtask).
        tasks = {t.name: t for t in stages["stack"].tasks}
        assert tasks["stack"].logs == ["working"]
        assert tree.output_url is not None

    def test_failed_result_marks_stage_failed(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)
        task = FakeTask("stack", "stack")
        pt.task_started(task)
        pt.record_result(_result(task, success=False))
        assert pt.run_tree().stages[0].status == RunStatus.FAILED


class TestRunLogPersistence:
    def test_save_then_load_latest_run(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)
        # Simulate a writable processing-path target for the run-log write.
        pt.read_only = False

        task = FakeTask("stack", "stack", targets=["/out/s.fits"])
        pt.task_started(task)
        pt.record_result(
            _result(task, output=FileInfo(base="/out", full=Path("/out/s.fits"), relative="s.fits"))
        )
        pt.save_run_log()

        assert (target / ".starbash" / "run-log.toml").exists()
        loaded = ProcessedTarget.open(target).latest_run()
        assert loaded is not None
        assert loaded.target == "M31"
        assert loaded.success is True
        assert loaded.stages[0].name == "stack"
        assert loaded.stages[0].outputs[0].label == "s.fits"

    def test_read_only_target_never_writes_run_log(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)  # read_only stays True
        task = FakeTask("stack", "stack")
        pt.task_started(task)
        pt.record_result(_result(task))
        pt.save_run_log()
        assert not (target / ".starbash" / "run-log.toml").exists()


class TestRunLabels:
    def test_real_target_label_is_the_directory_name(self):
        pt = ProcessedTarget.__new__(ProcessedTarget)
        pt.is_master = False
        pt.name = Path("/out/M31")
        assert pt.run_label({}) == "M31"

    def test_master_label_describes_the_calibration_frames(self):
        pt = ProcessedTarget.__new__(ProcessedTarget)
        pt.is_master = True
        pt.name = Path("/tmp/temp_abc")
        label = pt.run_label(
            {"session_config": "flat_Ha", "date": "2024-01-01", "camera_id": "canon"}
        )
        assert label == "Master flat_Ha · 2024-01-01 · canon"

    def test_master_record_result_uses_the_descriptive_label(self, tmp_path):
        target = _write_target(tmp_path, "temp_abc", [("stack", False)])
        pt = ProcessedTarget.open(target)
        pt.is_master = True
        pt.run = None

        task = FakeTask("stack", "stack")
        task.meta["context"] = {"session_config": "flat_Ha", "date": "2024-01-01"}
        pt.task_started(task)

        tree = pt.run_tree()
        assert tree is not None
        assert tree.is_master is True
        assert tree.target == "Master flat_Ha · 2024-01-01"


class TestLazyMetadata:
    def test_open_does_not_parse_metadata_files(self, tmp_path, monkeypatch):
        """Listing/opening a target must not read about.toml or sessions.toml.

        A sessions.toml carries per-frame metadata and can be large; parsing every
        one while enumerating targets stalled the GUI.  They load on demand.
        """
        target = _write_target(tmp_path, "M31", [("stack", False)])
        calls: list[str] = []
        original = ProcessedTarget._read_or_template

        def spy(path, template_name):
            calls.append(str(path))
            return original(path, template_name)

        monkeypatch.setattr(ProcessedTarget, "_read_or_template", staticmethod(spy))

        target_obj = ProcessedTarget.open(target)
        assert calls == []

        _ = target_obj.sessions
        assert len(calls) == 1 and calls[0].endswith("sessions.toml")

        _ = target_obj.about
        assert len(calls) == 2 and calls[1].endswith("about.toml")

    def test_parameter_store_is_built_lazily(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)

        assert getattr(pt, "_parameter_store", None) is None
        _ = pt.parameter_store
        assert pt._parameter_store is not None


class TestRunStageSelection:
    def test_only_stages_that_produced_tasks_are_listed(self, tmp_path):
        # main.toml lists the whole catalog, but doit only kept two stages.
        target = _write_target(
            tmp_path,
            "sh2126",
            [("master_dark", False), ("stack", False), ("noise_exterminator", False)],
        )
        pt = ProcessedTarget.open(target)
        pt.read_only = False
        pt.set_run_stages([{"name": "stack"}, {"name": "noise_exterminator"}])

        pt.task_started(FakeTask("stack", "stack"))
        names = [s.name for s in pt.run_tree().stages]

        assert names == ["stack", "noise_exterminator"]
        assert "master_dark" not in names

    def test_config_excluded_stage_is_still_listed_and_marked(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("stack", False), ("denoise", True)])
        pt = ProcessedTarget.open(target)
        pt.read_only = False
        # Both stages produced a task; `denoise` was then excluded by the user.
        pt.set_run_stages([{"name": "stack"}, {"name": "denoise"}])

        pt.task_started(FakeTask("stack", "stack"))
        stages = {s.name: s for s in pt.run_tree().stages}

        assert stages["denoise"].excluded is True
        assert stages["denoise"].status == RunStatus.EXCLUDED
        assert stages["stack"].excluded is False

    def test_falls_back_to_config_without_a_task_list(self, tmp_path):
        target = _write_target(tmp_path, "M31", [("a", False), ("b", True)])
        pt = ProcessedTarget.open(target)

        pt.task_started(FakeTask("a", "a"))

        assert [(s.name, s.excluded) for s in pt.run_tree().stages] == [("a", False), ("b", True)]


class TestFinishRuns:
    def test_finish_runs_persists_and_announces_the_run(self, tmp_path):
        from starbash import events
        from starbash.processing import Processing

        target = _write_target(tmp_path, "M31", [("stack", False)])
        pt = ProcessedTarget.open(target)
        pt.read_only = False  # simulate the writable processing-path target
        task = FakeTask("stack", "stack")
        pt.task_started(task)
        pt.record_result(_result(task))

        # A ProcessingResult-shaped object referencing our target.
        result = SimpleNamespace(task=SimpleNamespace(meta={"processed_target": pt}))

        processed = Processing.__new__(Processing)  # no __init__ side effects
        received: list[events.Event] = []
        unsubscribe = events.subscribe(received.append)
        try:
            processed._finish_runs([result])
        finally:
            unsubscribe()

        assert (target / ".starbash" / "run-log.toml").exists()
        finished = [e for e in received if e.kind == events.EVENT_RUN_FINISHED]
        assert finished, "finishing a run should publish run.finished"
        assert finished[0].data["target"] == "M31"
        assert finished[0].data["run"]["stages"][0]["name"] == "stack"


