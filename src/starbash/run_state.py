"""Live run state for a processed target.

This module is deliberately **dependency-free**: it must not import ``doit``,
``processing`` or any UI toolkit, so both the CLI and the GUI can consume the
same plain-data model without dragging the processing pipeline (or a Qt
dependency) along.  The doit-specific extraction lives in
:mod:`starbash.processed_target`.

The model is a small tree::

    RunTree(target)
      └── StageNode(name)          # one recipe stage
            └── TaskNode(name)     # one doit task (per session / multiplex index)

Every node carries a :class:`RunStatus`, clickable :class:`FileRef` inputs and
outputs, the stage's upstream ``dependencies`` (derived from the doit task graph)
and a bounded ``logs`` tail.  A run can be serialised to ``run-log.toml``
(:meth:`RunState.to_toml`) and loaded back (:meth:`RunState.from_toml`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "RunStatus",
    "FileRef",
    "TaskNode",
    "StageNode",
    "RunTree",
    "RunState",
    "LOG_TAIL_LINES",
]

#: How many trailing log lines to keep per stage.
LOG_TAIL_LINES = 8


class RunStatus(StrEnum):
    """The state of a stage or task within a run."""

    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"
    EXCLUDED = "excluded"

    @property
    def glyph(self) -> str:
        """A short, plain-text marker used by both the CLI and GUI."""
        return _GLYPHS[self]

    @property
    def label(self) -> str:
        """A display label for the status.

        ``PENDING`` reads as ``unused`` in the tree: a stage only keeps this status
        when no task for it ever ran, i.e. it was not used for this target.
        """
        return "unused" if self is RunStatus.PENDING else str(self.value)

    @property
    def rich_style(self) -> str:
        """A Rich style name (also usable as a GUI colour hint)."""
        return _RICH_STYLES[self]

    @property
    def is_terminal(self) -> bool:
        """True once the node will not change again."""
        return self in (RunStatus.OK, RunStatus.SKIPPED, RunStatus.FAILED, RunStatus.EXCLUDED)


_GLYPHS: dict[RunStatus, str] = {
    RunStatus.PENDING: "·",
    RunStatus.RUNNING: "⏳",
    RunStatus.OK: "✓",
    RunStatus.SKIPPED: "Ø",
    RunStatus.FAILED: "✗",
    RunStatus.EXCLUDED: "⊘",
}

_RICH_STYLES: dict[RunStatus, str] = {
    RunStatus.PENDING: "dim",
    RunStatus.RUNNING: "cyan",
    RunStatus.OK: "green",
    RunStatus.SKIPPED: "yellow",
    RunStatus.FAILED: "red",
    RunStatus.EXCLUDED: "dim",
}


@dataclass
class FileRef:
    """One clickable file: a display ``label`` and an optional ``url``."""

    label: str
    url: str | None = None

    def to_plain(self) -> dict[str, Any]:
        return {"label": self.label, "url": self.url}

    @classmethod
    def from_plain(cls, data: dict[str, Any]) -> FileRef:
        return cls(label=str(data.get("label", "")), url=data.get("url"))


@dataclass
class TaskNode:
    """One doit task: a single session (or multiplex index) within a stage."""

    name: str
    title: str = ""
    status: RunStatus = RunStatus.PENDING
    reason: str | None = None
    session: str | None = None
    inputs: list[FileRef] = field(default_factory=list)
    outputs: list[FileRef] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    #: doit ``file_dep`` paths (inputs) - used to derive stage dependencies.
    file_dep: list[str] = field(default_factory=list, repr=False)
    #: doit ``targets`` paths (outputs) - used to derive stage dependencies.
    targets: list[str] = field(default_factory=list, repr=False)

    def to_plain(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "status": str(self.status),
            "reason": self.reason,
            "session": self.session,
            "inputs": [f.to_plain() for f in self.inputs],
            "outputs": [f.to_plain() for f in self.outputs],
            "logs": list(self.logs),
        }

    @classmethod
    def from_plain(cls, data: dict[str, Any]) -> TaskNode:
        return cls(
            name=str(data.get("name", "")),
            title=str(data.get("title", "")),
            status=RunStatus(data.get("status", RunStatus.PENDING)),
            reason=data.get("reason"),
            session=data.get("session"),
            inputs=[FileRef.from_plain(f) for f in data.get("inputs", [])],
            outputs=[FileRef.from_plain(f) for f in data.get("outputs", [])],
            logs=[str(line) for line in data.get("logs", [])],
        )

@dataclass
class StageNode:
    """One recipe stage for the current target, with its tasks."""

    name: str
    description: str | None = None
    status: RunStatus = RunStatus.PENDING
    excluded: bool = False
    recipe_url: str | None = None
    config_url: str | None = None
    inputs: list[FileRef] = field(default_factory=list)
    outputs: list[FileRef] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tasks: list[TaskNode] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def add_log(self, line: str, limit: int = LOG_TAIL_LINES) -> None:
        """Append a log line, keeping only the trailing ``limit`` lines."""
        if not line:
            return
        self.logs.append(line)
        if limit > 0 and len(self.logs) > limit:
            del self.logs[: len(self.logs) - limit]

    def to_plain(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": str(self.status),
            "excluded": self.excluded,
            "recipe_url": self.recipe_url,
            "config_url": self.config_url,
            "inputs": [f.to_plain() for f in self.inputs],
            "outputs": [f.to_plain() for f in self.outputs],
            "dependencies": list(self.dependencies),
            "logs": list(self.logs),
            "tasks": [t.to_plain() for t in self.tasks],
        }

    @classmethod
    def from_plain(cls, data: dict[str, Any]) -> StageNode:
        return cls(
            name=str(data.get("name", "")),
            description=data.get("description"),
            status=RunStatus(data.get("status", RunStatus.PENDING)),
            excluded=bool(data.get("excluded", False)),
            recipe_url=data.get("recipe_url"),
            config_url=data.get("config_url"),
            inputs=[FileRef.from_plain(f) for f in data.get("inputs", [])],
            outputs=[FileRef.from_plain(f) for f in data.get("outputs", [])],
            dependencies=[str(d) for d in data.get("dependencies", [])],
            tasks=[TaskNode.from_plain(t) for t in data.get("tasks", [])],
            logs=[str(line) for line in data.get("logs", [])],
        )


@dataclass
class RunTree:
    """A whole run for one target: an ordered list of :class:`StageNode`."""

    target: str
    output_url: str | None = None
    timestamp: str | None = None
    success: bool | None = None
    is_master: bool = False
    stages: list[StageNode] = field(default_factory=list)

    @property
    def stages_run(self) -> int:
        """Count of stages that actually executed successfully."""
        return sum(1 for s in self.stages if s.status == RunStatus.OK)

    @property
    def stages_failed(self) -> int:
        """Count of stages that failed."""
        return sum(1 for s in self.stages if s.status == RunStatus.FAILED)

    def to_plain(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "output_url": self.output_url,
            "timestamp": self.timestamp,
            "success": self.success,
            "is_master": self.is_master,
            "stages_run": self.stages_run,
            "stages_failed": self.stages_failed,
            "stages": [s.to_plain() for s in self.stages],
        }

    @classmethod
    def from_plain(cls, data: dict[str, Any]) -> RunTree:
        return cls(
            target=str(data.get("target", "")),
            output_url=data.get("output_url"),
            timestamp=data.get("timestamp"),
            success=data.get("success"),
            is_master=bool(data.get("is_master", False)),
            stages=[StageNode.from_plain(s) for s in data.get("stages", [])],
        )
def _plain_to_toml(value: Any) -> Any:
    """Convert a JSON-able value into tomlkit items (dicts -> tables, dict-lists -> AoT)."""
    import tomlkit

    if isinstance(value, dict):
        table = tomlkit.table()
        for key, item in value.items():
            if item is None:
                continue  # TOML has no null; omit unset fields
            table[str(key)] = _plain_to_toml(item)
        return table
    if isinstance(value, (list, tuple)):
        items = [x for x in value if x is not None]
        if items and all(isinstance(x, dict) for x in items):
            aot = tomlkit.aot()
            for item in items:
                aot.append(_plain_to_toml(item))
            return aot
        return [_plain_to_toml(item) for item in items]
    return value


def _toml_to_plain(value: Any) -> Any:
    """Convert tomlkit documents/tables/AoTs back into plain dicts/lists."""
    if isinstance(value, str):
        return value
    if hasattr(value, "items"):
        return {str(k): _toml_to_plain(v) for k, v in value.items()}  # type: ignore[union-attr]
    if isinstance(value, Iterable):
        return [_toml_to_plain(v) for v in value]
    return value


class RunState:
    """Accumulates live results for one target's run into a :class:`RunTree`.

    Stages may be pre-registered (so excluded / not-yet-run stages show in the
    tree), then tasks/results/status/logs are fed in as doit reports them.
    """

    def __init__(
        self,
        target: str,
        config_url: str | None = None,
        log_tail_lines: int = LOG_TAIL_LINES,
        is_master: bool = False,
    ) -> None:
        self.target = target
        self.config_url = config_url
        self.log_tail_lines = log_tail_lines
        self.is_master = is_master
        self.output_url: str | None = None
        self.timestamp: str | None = None
        self.success: bool | None = None
        self._stages: dict[str, StageNode] = {}  # insertion order == run order
        self._current_stage: str | None = None

    # --- stage registration / lookup -------------------------------------

    def register_stage(
        self,
        name: str,
        *,
        description: str | None = None,
        excluded: bool = False,
        recipe_url: str | None = None,
        status: RunStatus | None = None,
    ) -> StageNode:
        """Ensure a stage node exists and return it (idempotent)."""
        node = self._stages.get(name)
        if node is None:
            node = StageNode(
                name=name,
                description=description,
                excluded=excluded,
                recipe_url=recipe_url,
                config_url=self.config_url,
                status=status or (RunStatus.EXCLUDED if excluded else RunStatus.PENDING),
            )
            self._stages[name] = node
        else:
            # Fill in any newly-known metadata without clobbering live state.
            if description is not None:
                node.description = description
            if recipe_url is not None:
                node.recipe_url = recipe_url
            node.excluded = node.excluded or excluded
        return node

    def stage(self, name: str) -> StageNode | None:
        """Return the stage node for ``name`` (or None)."""
        return self._stages.get(name)

    @property
    def stages(self) -> list[StageNode]:
        """Stages in insertion (run) order."""
        return list(self._stages.values())

    # --- live lifecycle ---------------------------------------------------

    def set_current_stage(self, name: str | None) -> None:
        """Point the log tail at the stage that is currently executing."""
        self._current_stage = name

    def add_task(self, stage_name: str, task: TaskNode) -> TaskNode:
        """Attach a task to its stage, marking the stage as running."""
        node = self.register_stage(stage_name)
        node.tasks.append(task)
        if node.status in (RunStatus.PENDING, RunStatus.EXCLUDED):
            node.excluded = False
            node.status = RunStatus.RUNNING
        return task

    def add_log(self, line: str) -> None:
        """Append a log line to the currently running stage (if any)."""
        if self._current_stage is None:
            return
        node = self._stages.get(self._current_stage)
        if node is not None:
            node.add_log(line, self.log_tail_lines)

    def set_status(self, stage_name: str, status: RunStatus) -> None:
        """Force a stage's status (used for excluded / pending stages)."""
        node = self.register_stage(stage_name)
        node.status = status


    # --- finalisation -----------------------------------------------------

    def compute_dependencies(self) -> None:
        """Derive stage dependencies from the doit task graph.

        An edge A -> B exists when a ``file_dep`` of A's task is produced as a
        ``target`` of B's task.  This is purely doit data (the stage ``after``
        regexes are already baked into ``file_dep``/``targets``).
        """
        producer: dict[str, str] = {}
        for stage in self._stages.values():
            for task in stage.tasks:
                for target in task.targets:
                    producer.setdefault(target, stage.name)

        for stage in self._stages.values():
            deps: set[str] = set()
            for task in stage.tasks:
                for dep in task.file_dep:
                    other = producer.get(dep)
                    if other and other != stage.name:
                        deps.add(other)
            stage.dependencies = sorted(deps)

    def _aggregate(self) -> None:
        """Roll per-task statuses and files up into each stage."""
        for stage in self._stages.values():
            if stage.excluded:
                stage.status = RunStatus.EXCLUDED
                continue
            # Roll the tasks' file references up so the stage shows its own I/O.
            inputs: list[FileRef] = []
            outputs: list[FileRef] = []
            seen_in: set[str] = set()
            seen_out: set[str] = set()
            for task in stage.tasks:
                for ref in task.inputs:
                    key = f"{ref.label}|{ref.url}"
                    if key not in seen_in:
                        seen_in.add(key)
                        inputs.append(ref)
                for ref in task.outputs:
                    key = f"{ref.label}|{ref.url}"
                    if key not in seen_out:
                        seen_out.add(key)
                        outputs.append(ref)
            if inputs:
                stage.inputs = inputs
            if outputs:
                stage.outputs = outputs

            statuses = [t.status for t in stage.tasks]
            if not statuses:
                continue
            if RunStatus.FAILED in statuses:
                stage.status = RunStatus.FAILED
            elif any(s in (RunStatus.PENDING, RunStatus.RUNNING) for s in statuses):
                stage.status = (
                    RunStatus.RUNNING if RunStatus.RUNNING in statuses else RunStatus.PENDING
                )
            elif RunStatus.OK in statuses:
                stage.status = RunStatus.OK
            else:
                stage.status = RunStatus.SKIPPED

    def tree(self) -> RunTree:
        """Freeze the current state into a :class:`RunTree`."""
        self._aggregate()
        self.compute_dependencies()
        return RunTree(
            target=self.target,
            output_url=self.output_url,
            timestamp=self.timestamp,
            success=self.success,
            is_master=self.is_master,
            stages=self.stages,
        )

    # --- serialisation ----------------------------------------------------

    def to_plain(self) -> dict[str, Any]:
        """The current state as a JSON-able dict (one ``run`` entry)."""
        return self.tree().to_plain()

    def to_document(self) -> Any:
        """The current state as a tomlkit document with a ``[[run]]`` array."""
        import tomlkit

        document = tomlkit.document()
        document["run"] = _plain_to_toml([self.to_plain()])
        return document

    @classmethod
    def from_tree(cls, tree: RunTree, log_tail_lines: int = LOG_TAIL_LINES) -> RunState:
        """Rebuild a state from a parsed :class:`RunTree` (read-only viewing)."""
        state = cls(tree.target, log_tail_lines=log_tail_lines, is_master=tree.is_master)
        state.output_url = tree.output_url
        state.timestamp = tree.timestamp
        state.success = tree.success
        for stage in tree.stages:
            state._stages[stage.name] = stage
        return state


def document_to_tree(document: Any) -> RunTree | None:
    """Parse a ``run-log.toml`` document into its most recent :class:`RunTree`."""
    plain = _toml_to_plain(document)
    runs = plain.get("run") if isinstance(plain, dict) else None
    if not isinstance(runs, list) or not runs:
        return None
    first = runs[0]
    if not isinstance(first, dict):
        return None
    return RunTree.from_plain(first)

