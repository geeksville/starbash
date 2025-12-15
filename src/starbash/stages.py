"""Stage utility functions for managing processing stages and tasks."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

from starbash import InputDef, StageDict
from starbash.database import ImageRow, SessionRow
from starbash.doit_types import TaskDict
from starbash.safety import get_safe
from starbash.stage_utils import get_from_toml, set_excluded, set_used, stage_with_comment

if TYPE_CHECKING:
    from starbash.processed_target import ProcessedTarget

__all__ = [
    "stage_with_comment",
    "set_used",
    "set_excluded",
    "get_from_toml",
    "task_to_stage",
    "task_to_session",
    "sort_stages",
    "tasks_to_stages",
    "set_used_stages_from_tasks",
    "make_imagerow",
    "stage_to_doc",
    "inputs_with_key",
    "inputs_by_kind",
    "remove_excluded_tasks",
    "create_default_task",
]


def task_to_stage(task: TaskDict) -> StageDict:
    """Extract the stage from the given task's context."""
    return task["meta"]["stage"]


def task_to_session(task: TaskDict) -> SessionRow | None:
    """Extract the session from the given task's context."""
    context = task["meta"]["context"]
    session = context.get("session")
    return session


def sort_stages(stages: list[StageDict]) -> list[StageDict]:
    """Sort the given list of stages by priority and dependency order.

    Stages are sorted such that:
    1. Dependencies (specified via 'after' in inputs) are respected
    2. Within dependency levels, higher priority stages come first
    3. Stages without dependencies come before those with dependencies (unless overridden by priority)
    """
    import re

    def get_after(s: StageDict) -> Generator[str, None, None]:
        """Get the names of stages that should come after this one.  Each entry is a regex that matches to stage name"""
        for input in s.get("inputs", []):
            after: str | None = input.get("after")
            if after:
                yield after

    # Build a mapping of stage names to their stage dicts for quick lookup
    stage_by_name: dict[str, StageDict] = {s.get("name", ""): s for s in stages}

    # Build dependency graph: for each stage, find which stages it depends on
    # If stage A has "after = B", then A depends on B, meaning B must come before A
    dependencies: dict[str, set[str]] = {}
    for stage in stages:
        stage_name = stage.get("name", "")
        dependencies[stage_name] = set()

        for after_pattern in get_after(stage):
            # Match the after pattern against all stage names
            try:
                pattern = re.compile(f"^{after_pattern}$")
                for candidate_name in stage_by_name.keys():
                    if pattern.match(candidate_name):
                        dependencies[stage_name].add(candidate_name)
            except re.error as e:
                logging.warning(f"Invalid regex pattern '{after_pattern}' in stage '{stage_name}': {e}")

    # Topological sort using Kahn's algorithm with priority-based ordering
    # Track which dependencies remain for each stage
    remaining_deps: dict[str, set[str]] = {
        name: deps.copy() for name, deps in dependencies.items()
    }

    # Start with stages that have no dependencies
    available = [name for name in stage_by_name.keys() if len(remaining_deps[name]) == 0]
    # Sort available stages by priority (higher priority first)
    available.sort(key=lambda name: stage_by_name[name].get("priority", 0), reverse=True)

    sorted_stages: list[StageDict] = []
    visited_names: set[str] = set()

    while available:
        # Pick the highest priority available stage
        current_name = available.pop(0)
        visited_names.add(current_name)
        sorted_stages.append(stage_by_name[current_name])

        # For each stage, check if current_name was one of its dependencies
        # If so, remove it and check if all dependencies are now satisfied
        for stage_name in stage_by_name.keys():
            if stage_name not in visited_names and current_name in remaining_deps[stage_name]:
                remaining_deps[stage_name].discard(current_name)
                # If all dependencies are satisfied, add to available
                if len(remaining_deps[stage_name]) == 0 and stage_name not in available:
                    available.append(stage_name)

        # Re-sort available stages by priority
        available.sort(key=lambda name: stage_by_name[name].get("priority", 0), reverse=True)

    # Check for cycles (any remaining stages with non-zero dependencies)
    remaining = [name for name in stage_by_name.keys() if name not in visited_names]
    if remaining:
        logging.warning(
            f"Circular dependencies detected in stages: {remaining}. "
            f"These stages will be appended in priority order."
        )
        # Add remaining stages in priority order as fallback
        remaining_stages = sorted(
            [stage_by_name[name] for name in remaining],
            key=lambda s: s.get("priority", 0),
            reverse=True
        )
        sorted_stages.extend(remaining_stages)

    logging.debug(f"Stages in dependency and priority order: {[s.get('name') for s in sorted_stages]}")
    return sorted_stages

def tasks_to_stages(tasks: list[TaskDict]) -> list[StageDict]:
    """Extract unique stages from the given list of tasks, sorted by priority."""
    stage_dict: dict[str, StageDict] = {}
    for task in tasks:
        stage = task["meta"]["stage"]
        stage_dict[stage["name"]] = stage

    stages = sort_stages(list(stage_dict.values()))
    return stages


def set_used_stages_from_tasks(tasks: list[dict]) -> None:
    """Given a list of tasks, set the used stages in each session touched by those tasks."""

    # Inside each session we touched, collect a list of used stages (initially as a list of strings but then in the final)
    # cleanup converted into toml lists with set_used.
    # We rely on the fact that a single session row instance is shared between all tasks for that session.

    if not tasks:
        return

    typ_task = tasks[0]
    pt: ProcessedTarget | None = typ_task["meta"]["processed_target"]
    assert pt, "ProcessedTarget must be set in Processing for sessionless tasks"

    # step 1: clear our temp lists
    default_stages: list[StageDict] = []
    for task in tasks:
        session = task_to_session(task)
        if session:
            session["_temp_used_stages"] = []

    # step 2: collect used stages
    for task in tasks:
        stage = task_to_stage(task)
        session = task_to_session(task)
        used = session["_temp_used_stages"] if session else default_stages
        if stage not in used:
            used.append(stage)

    # step 3: commit used stages to toml (and remove temp lists)
    for task in tasks:
        session = task_to_session(task)
        if session:
            used_stages: list[StageDict] = session.pop("_temp_used_stages", [])
            if used_stages:
                set_used(session, used_stages)

    # Commit our default used stages too
    if default_stages:
        set_used(pt.default_stages, default_stages)


def make_imagerow(dir: Path, path: str) -> ImageRow:
    """Make a stub imagerow definition with just an abspath (no metadata or other standard columns)"""
    return {"abspath": str(dir / path), "path": path}


def stage_to_doc(task: TaskDict, stage: StageDict) -> None:
    """Given a stage definition, populate the "doc" string of the task dictionary."""
    task["doc"] = stage.get("description", "No description provided")


def inputs_with_key(stage: StageDict, key: str) -> list[InputDef]:
    """Returns all inputs which contain a particular key."""
    inputs: list[InputDef] = stage.get("inputs", [])
    return [inp for inp in inputs if key in inp]


def inputs_by_kind(stage: StageDict, kind: str) -> list[InputDef]:
    """Returns all inputs of a particular kind from the given stage definition."""
    inputs: list[InputDef] = stage.get("inputs", [])
    return [inp for inp in inputs if inp.get("kind") == kind]


def remove_excluded_tasks(tasks: list[TaskDict]) -> list[TaskDict]:
    """Look in our session['stages'] dict to see if this task is allowed to be processed"""

    def task_allowed(task: TaskDict) -> bool:
        stage = task_to_stage(task)
        session = task_to_session(task)
        if not session:
            pt: ProcessedTarget = task["meta"]["processed_target"]
            assert pt, "ProcessedTarget must be set in Processing for sessionless tasks"
            session = pt.default_stages

        excluded_stages = get_from_toml(session, "excluded")
        return stage.get("name") not in excluded_stages

    return [t for t in tasks if task_allowed(t)]


def create_default_task(tasks: list[TaskDict]) -> TaskDict:
    """Create a default task that depends on all given tasks.

    This task can be used to represent the overall processing of a target.

    Args:
        tasks: List of TaskDict objects to depend on.

    Returns:
        A TaskDict representing the default task.
    """
    default_task_name = "process_all"
    task_deps = []
    for task in tasks:
        # We consider tasks that are writing to the final output repos
        # 'high value' and what we should run by default
        stage = task["meta"]["stage"]
        outputs = stage.get("outputs", [])
        for output in outputs:
            output_kind = get_safe(output, "kind")
            if output_kind == "master" or output_kind == "processed":
                high_value_task = task
                task_deps.append(high_value_task["name"])
                break  # no need to check other outputs for this task

    task_dict: TaskDict = {
        "name": default_task_name,
        "task_dep": task_deps,
        "actions": None,  # No actions, just depends on other tasks
        "doc": "Top level task to process all stages for all targets",
    }
    return task_dict
