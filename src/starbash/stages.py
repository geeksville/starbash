"""Stage utility functions for managing processing stages and tasks."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from starbash import InputDef, StageDict
from starbash.database import ImageRow, SessionRow
from starbash.doit_types import TaskDict
from starbash.safety import get_safe
from starbash.stage_utils import is_excluded, mark_excluded, mark_used, upsert_stage

if TYPE_CHECKING:
    from starbash.processed_target import ProcessedTarget

__all__ = [
    "mark_used",
    "mark_excluded",
    "is_excluded",
    "upsert_stage",
    "task_to_stage",
    "task_to_session",
    "sort_stages",
    "StageSelection",
    "select_stages",
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


@dataclass
class StageSelection:
    """The stages that may run, plus what role selection decided.

    See ``doc/plans/stage-roles.md``.  A stage may declare an optional ``role``
    ("deblur", "denoise", ...); when several stages share a role they are
    interchangeable implementations of one pipeline step and only the best
    priority one runs.
    """

    #: The stages that may run, in catalog order.
    stages: list[StageDict]
    #: role -> name of the stage that will implement it.
    roles: dict[str, str]
    #: dropped stage name -> why it is not running (for logs and the GUI).
    dropped: dict[str, str]
    #: every stage name that declares a role -> that role, including dropped ones.
    roles_by_stage: dict[str, str] = field(default_factory=dict)

    def _canonical(self, name: str, selected: set[str]) -> str | None:
        """Map a stage/role name onto the stage that will actually run.

        ``name`` may be a stage name (which may carry a role) *or* a role name
        itself; the union is why ``after = "denoise"`` works whether ``denoise``
        is read as the GraXpert stage or as the role.
        """
        role = self.roles_by_stage.get(name)
        if role is None and name in self.roles:
            role = name  # the name is itself a role ("deblur", "denoise", ...)
        if role is not None and role in self.roles:
            return self.roles[role]
        return name if name in selected else None

    def resolve(self, pattern: str) -> list[str]:
        """Stage names that will actually run, for an ``after`` pattern.

        The pattern (a regex) is matched against **both stage names and role
        names**, and each match is canonicalized onto the stage that will really
        produce the output:

        * a selected stage name -> itself
        * a dropped stage name -> the winner of its role (loser -> winner redirect)
        * a role name -> the winner of that role

        A name that is both a stage and a role is matched in both namespaces; the
        canonical forms dedup to a single provider.  Returns ``[]`` when nothing
        matches (a typo, or a role no available stage implements).
        """
        try:
            regex = re.compile(pattern)
        except re.error:
            return []

        selected = {s.get("name", "") for s in self.stages}
        providers: set[str] = set()
        for name in (*selected, *self.dropped, *self.roles):
            if not name or not regex.fullmatch(name):
                continue
            canonical = self._canonical(name, selected)
            if canonical:
                providers.add(canonical)
        return sorted(providers)

    def unimplemented_role(self, pattern: str) -> str | None:
        """Return a role the pattern names that no available stage implements.

        Used to explain a skipped stage at ``INFO`` rather than ``DEBUG``: a role
        nobody can implement silently removes its consumers, which is otherwise
        invisible to the user.
        """
        try:
            for role in sorted(set(self.roles_by_stage.values())):
                if role not in self.roles and re.fullmatch(pattern, role):
                    return role
        except re.error:
            return None
        return None


def _priority(stage: StageDict) -> int:
    """A stage's ``priority`` as an int (default 0, matching ``sort_stages``)."""
    try:
        return int(stage.get("priority", 0))
    except (TypeError, ValueError):
        logging.warning(f"Stage '{stage.get('name')}' has a non-numeric priority; treating it as 0")
        return 0


def _stage_drop_reason(
    stage: StageDict,
    *,
    is_available: Callable[[str], bool] | None,
    is_excluded: Callable[[StageDict], bool] | None,
) -> str | None:
    """Why ``stage`` cannot be considered, or None when it is a candidate."""
    if stage.get("disabled"):
        return "disabled"
    if is_excluded is not None and is_excluded(stage):
        return "excluded for this target"
    tool = stage.get("tool")
    tool_name = tool.get("name") if isinstance(tool, dict) else None
    if is_available is not None and tool_name and not is_available(str(tool_name)):
        return f"tool '{tool_name}' is not installed"
    return None


def select_stages(
    stages: list[StageDict],
    *,
    is_available: Callable[[str], bool] | None = None,
    is_excluded: Callable[[StageDict], bool] | None = None,
) -> StageSelection:
    """Filter a stage catalog down to the stages that may run, one per role.

    Order of filtering (the first reason that applies wins): ``disabled`` ->
    excluded -> tool availability -> role dedup.  A stage with no ``role`` is only
    subject to the first three rules, so recipes without roles behave exactly as
    before.

    Role selection happens *before* any task is created, so the losing
    implementation's branch never materialises (see ``doc/plans/stage-roles.md``).

    Args:
        stages: the merged recipe catalog, in the order ties should be broken (earlier wins).
        is_available: predicate mapping a tool name to "installed on this machine".
        is_excluded: predicate saying whether the user excluded a stage for this target.
    """
    kept: list[StageDict] = []
    dropped: dict[str, str] = {}
    roles_by_stage: dict[str, str] = {}

    for stage in stages:
        name = str(stage.get("name", ""))
        role = stage.get("role")
        if role:
            roles_by_stage[name] = str(role)

        reason = _stage_drop_reason(stage, is_available=is_available, is_excluded=is_excluded)
        if reason:
            if reason.startswith("tool "):
                # Keep the visibility that _remove_missing_tool_tasks used to give
                # (these stages are now dropped before any task is created).
                logging.warning(f"Ignoring recipe '{name}' because {reason}")
            else:
                logging.debug(f"Stage '{name}' is not a candidate: {reason}")
            dropped[name] = reason
            continue
        kept.append(stage)

    # Group the candidates by role, then pick a winner per role.  ``max`` returns
    # the first maximal element, so equal priorities keep catalog order (earlier
    # wins) - the same stable-sort rule that orders stages elsewhere.
    candidates_by_role: dict[str, list[StageDict]] = {}
    for stage in kept:
        role = stage.get("role")
        if role:
            candidates_by_role.setdefault(str(role), []).append(stage)

    roles: dict[str, str] = {}
    winners: set[str] = set()
    for role, members in candidates_by_role.items():
        winner = max(members, key=lambda s: _priority(s))
        winner_name = str(winner.get("name", ""))
        winner_priority = _priority(winner)
        roles[role] = winner_name
        winners.add(winner_name)

        for loser in members:
            loser_name = str(loser.get("name", ""))
            if loser_name == winner_name:
                continue
            dropped[loser_name] = (
                f"role '{role}' handled by '{winner_name}' (priority {winner_priority})"
            )
            logging.info(
                f"Stage '{loser_name}' shares role '{role}' with '{winner_name}'; "
                f"using the latter (priority {winner_priority})"
            )

    # A role nobody can implement silently takes its consumers with it, so say so
    # once per role, with the reason each member is out.  The commonest cause is a
    # user exclusion persisted before roles existed.
    for role in sorted({r for r in roles_by_stage.values() if r not in roles}):
        members = [n for n, r in roles_by_stage.items() if r == role]
        detail = "; ".join(f"'{n}': {dropped.get(n, 'not a candidate')}" for n in members)
        logging.info(f"No available stage implements role '{role}' ({detail})")

    selected = [s for s in kept if not s.get("role") or str(s.get("name", "")) in winners]
    logging.debug(
        f"Selected stages: {[s.get('name') for s in selected]} (roles: {roles}, dropped: {dropped})"
    )
    return StageSelection(
        stages=selected, roles=roles, dropped=dropped, roles_by_stage=roles_by_stage
    )


def sort_stages(
    stages: list[StageDict],
    resolve: Callable[[str], list[str]] | None = None,
) -> list[StageDict]:
    """Sort the given list of stages by priority and dependency order.

    Stages are sorted such that:
    1. Dependencies (specified via 'after' in inputs) are respected
    2. Within dependency levels, higher priority stages come first
    3. Stages without dependencies come before those with dependencies (unless overridden by priority)

    Args:
        resolve: optional resolver turning an ``after`` pattern into the stage
            names that will actually run (see :meth:`StageSelection.resolve`).
            It lets a pattern name a *role*, and lets a reference to a dropped
            role member be redirected onto the winner.  ``None`` keeps the plain
            "regex over stage names" behaviour.
    """

    def get_after(s: StageDict) -> Generator[str, None, None]:
        """Get the names of stages that should come after this one.  Each entry is a regex that matches to stage name"""
        for input in s.get("inputs", []):
            after: str | None = input.get("after")
            if after:
                yield after

    # Build a mapping of stage names to their stage dicts for quick lookup
    stage_by_name: dict[str, StageDict] = {s.get("name", ""): s for s in stages}

    def matching_stages(after_pattern: str, stage_name: str) -> list[str]:
        """Names of the stages in this list that ``after_pattern`` depends on."""
        if resolve is not None:
            # Prefer the resolver: it knows which implementations will really run.
            resolved = [name for name in resolve(after_pattern) if name in stage_by_name]
            if resolved:
                return resolved

        # Match the after pattern against all stage names
        try:
            pattern = re.compile(f"^{after_pattern}$")
        except re.error as e:
            logging.warning(f"Invalid regex pattern '{after_pattern}' in stage '{stage_name}': {e}")
            return []
        return [name for name in stage_by_name.keys() if pattern.match(name)]

    # Build dependency graph: for each stage, find which stages it depends on
    # If stage A has "after = B", then A depends on B, meaning B must come before A
    dependencies: dict[str, set[str]] = {}
    for stage in stages:
        stage_name = stage.get("name", "")
        dependencies[stage_name] = set()

        for after_pattern in get_after(stage):
            dependencies[stage_name].update(matching_stages(after_pattern, stage_name))

    # Topological sort using Kahn's algorithm with priority-based ordering
    # Track which dependencies remain for each stage
    remaining_deps: dict[str, set[str]] = {name: deps.copy() for name, deps in dependencies.items()}

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
            reverse=True,
        )
        sorted_stages.extend(remaining_stages)

    logging.debug(
        f"Stages in dependency and priority order: {[s.get('name') for s in sorted_stages]}"
    )
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

    # Inside each session we touched, collect a list of used stages (initially as a list of stage
    # dicts) then in the final cleanup upsert them into the session's [[stages]] AoT with mark_used.
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
                mark_used(session, used_stages)

    # Commit our default used stages too
    if default_stages:
        mark_used(pt.default_stages, default_stages)


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

        return not is_excluded(session, stage.get("name", ""))

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
        # 'high value' and should run by default. State-only stages can opt in
        # with ``run_by_default = true`` because they have no output file.
        stage = task["meta"]["stage"]
        if stage.get("run_by_default", False):
            task_deps.append(task["name"])
            continue
        outputs = stage.get("outputs", [])
        for output in outputs:
            output_kind = get_safe(output, "kind")
            if output_kind == "master" or output_kind == "processed":
                task_deps.append(task["name"])
                break  # no need to check other outputs for this task

    task_dict: TaskDict = {
        "name": default_task_name,
        "task_dep": task_deps,
        "actions": None,  # No actions, just depends on other tasks
        "doc": "Top level task to process all stages for all targets",
    }
    return task_dict
