"""Tests for the live run-state model (``starbash.run_state``)."""

from __future__ import annotations

import tomlkit

from starbash.run_state import (
    FileRef,
    RunState,
    RunStatus,
    StageNode,
    TaskNode,
    document_to_tree,
)


def _stage(state: RunState, name: str) -> StageNode:
    """Return a registered stage, asserting it exists (``stage()`` is Optional)."""
    node = state.stage(name)
    assert node is not None
    return node


def _task(name: str, status: RunStatus, deps=(), targets=()) -> TaskNode:
    return TaskNode(
        name=name,
        status=status,
        file_dep=list(deps),
        targets=list(targets),
        outputs=[FileRef(label=f"{name}.fits", url=f"file:///{name}.fits")],
    )


class TestStatusLabels:
    def test_pending_reads_as_unused_in_the_ui(self):
        assert RunStatus.PENDING.label == "unused"
        # The serialized value stays stable for run-log.toml compatibility.
        assert str(RunStatus.PENDING) == "pending"

    def test_other_labels_match_their_values(self):
        assert RunStatus.OK.label == "ok"
        assert RunStatus.EXCLUDED.label == "excluded"
        assert RunStatus.FAILED.label == "failed"


class TestRunStateStatus:
    def test_excluded_stage_stays_excluded(self):
        state = RunState("M31")
        state.register_stage("denoise", excluded=True)
        assert state.tree().stages[0].status == RunStatus.EXCLUDED

    def test_stage_fails_if_any_task_fails(self):
        state = RunState("M31")
        state.add_task("stack", _task("stack_a", RunStatus.OK))
        state.add_task("stack", _task("stack_b", RunStatus.FAILED))
        assert state.tree().stages[0].status == RunStatus.FAILED

    def test_stage_running_while_a_task_runs(self):
        state = RunState("M31")
        state.add_task("stack", _task("stack_a", RunStatus.OK))
        state.add_task("stack", _task("stack_b", RunStatus.RUNNING))
        assert state.tree().stages[0].status == RunStatus.RUNNING

    def test_task_started_sets_running_then_add_task_marks_running(self):
        state = RunState("M31")
        state.register_stage("stack")
        task = state.add_task("stack", _task("stack_a", RunStatus.RUNNING))
        assert task.status == RunStatus.RUNNING
        assert _stage(state, "stack").status == RunStatus.RUNNING


class TestDependencies:
    def test_dependency_derived_from_file_dep_and_targets(self):
        state = RunState("M31")
        state.add_task("calibrate", _task("calibrate", RunStatus.OK, targets=["/out/pp.fits"]))
        state.add_task(
            "stack", _task("stack", RunStatus.OK, deps=["/out/pp.fits"], targets=["/out/s.fits"])
        )
        stages = {s.name: s for s in state.tree().stages}
        assert stages["stack"].dependencies == ["calibrate"]
        assert stages["calibrate"].dependencies == []

    def test_no_self_dependency(self):
        state = RunState("M31")
        state.add_task(
            "stack", _task("stack", RunStatus.OK, deps=["/out/s.fits"], targets=["/out/s.fits"])
        )
        assert state.tree().stages[0].dependencies == []


class TestLogTail:
    def test_only_the_trailing_lines_are_kept(self):
        state = RunState("M31", log_tail_lines=3)
        state.register_stage("stack")
        state.set_current_stage("stack")
        for i in range(10):
            state.add_log(f"line {i}")
        assert _stage(state, "stack").logs == ["line 7", "line 8", "line 9"]

    def test_lines_go_to_the_running_task_and_the_stage(self):
        state = RunState("M31", log_tail_lines=3)
        state.register_stage("stack")
        task = state.add_task("stack", _task("stack_a", RunStatus.RUNNING))
        state.set_current_stage("stack")
        state.set_current_task(task)
        for i in range(10):
            state.add_log(f"line {i}")
        assert task.logs == ["line 7", "line 8", "line 9"]
        assert _stage(state, "stack").logs == ["line 7", "line 8", "line 9"]

    def test_lines_fall_back_to_the_stage_once_the_task_ends(self):
        state = RunState("M31", log_tail_lines=3)
        state.register_stage("stack")
        task = state.add_task("stack", _task("stack_a", RunStatus.RUNNING))
        state.set_current_stage("stack")
        state.set_current_task(task)
        state.add_log("during the task")
        state.set_current_task(None)
        state.add_log("after the task")
        assert task.logs == ["during the task"]
        assert _stage(state, "stack").logs == ["during the task", "after the task"]

    def test_task_logs_round_trip_through_toml(self):
        state = RunState("M31")
        task = state.add_task("calibrate", _task("calibrate", RunStatus.OK))
        task.add_log("hello task")

        assert state.tree().stages[0].tasks[0].logs == ["hello task"]

        reparsed = tomlkit.parse(tomlkit.dumps(state.to_document()))
        tree = document_to_tree(reparsed)
        assert tree is not None
        assert tree.stages[0].tasks[0].logs == ["hello task"]

    def test_log_without_current_stage_is_ignored(self):
        state = RunState("M31")
        state.register_stage("stack")
        state.add_log("orphan")
        assert _stage(state, "stack").logs == []


class TestSerialisation:
    def test_round_trip_through_toml(self):
        state = RunState("M31", config_url="file:///c/main.toml")
        state.register_stage("calibrate", recipe_url="file:///r/cal.toml")
        state.add_task("calibrate", _task("calibrate", RunStatus.OK, targets=["/out/pp.fits"]))
        state.set_current_stage("calibrate")
        state.add_log("hello")
        state.timestamp = "2026-01-02T03:04:05Z"
        state.success = True

        document = state.to_document()
        # The document must be real TOML that parses back to the same values.
        reparsed = tomlkit.parse(tomlkit.dumps(document))
        tree = document_to_tree(reparsed)

        assert tree is not None
        assert tree.target == "M31"
        assert tree.timestamp == "2026-01-02T03:04:05Z"
        assert tree.success is True
        stage = tree.stages[0]
        assert stage.recipe_url == "file:///r/cal.toml"
        assert stage.config_url == "file:///c/main.toml"
        assert stage.outputs[0].label == "calibrate.fits"
        assert stage.logs == ["hello"]
        assert tree.stages_run == 1

    def test_empty_document_returns_none(self):
        assert document_to_tree(tomlkit.document()) is None
