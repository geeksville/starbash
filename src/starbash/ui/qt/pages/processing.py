"""Run the automated pipeline with a live task tree and progress bar.

Nothing here polls: the core publishes tool output, task transitions and stage
results on the event bus, and this page renders them as they arrive.  Tool output
lands under the *task* node it belongs to, inside a collapsible ``Log`` node, so
the tree *is* the log.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from starbash import events
from starbash.run_state import LOG_TAIL_LINES, RunStatus
from starbash.ui.qt.jobs import process_job
from starbash.ui.qt.pages.base import Page

__all__ = ["ProcessingPage"]

#: Status -> foreground colour for the run tree.
_STATUS_COLORS: dict[RunStatus, str] = {
    RunStatus.PENDING: "#8b949e",
    RunStatus.RUNNING: "#39c5cf",
    RunStatus.OK: "#3fb950",
    RunStatus.SKIPPED: "#d29922",
    RunStatus.FAILED: "#f85149",
    RunStatus.EXCLUDED: "#6e7681",
}

#: How many live tool-log lines to keep under one task's ``Log`` node.
_LOG_LIMIT = LOG_TAIL_LINES

_DIM = "#8b949e"

#: Item-data roles, so nodes can be found again after a tree rebuild.
_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_NAME = Qt.ItemDataRole.UserRole + 1

#: Node kinds stored in ``_ROLE_KIND``.
_KIND_STAGE = "stage"
_KIND_TASK = "task"
_KIND_LOG = "log"
_KIND_OUT = "out"


class ProcessingPage(Page):
    """Trigger a processing run and watch it happen, live."""

    nav_title = "Processing"
    subtitle = "Run the automated pipeline and watch every stage, tool and log line."

    def _build(self) -> None:
        self._worker = None
        self._targets: dict[str, QTreeWidgetItem] = {}
        #: (target, stage, task) of the doit task running right now.
        self._running: tuple[str, str, str] | None = None

        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._run = QPushButton("Run auto pipeline")
        self._run.setObjectName("Primary")
        self._run.clicked.connect(lambda: self._start(masters_only=False))

        self._masters = QPushButton("Generate masters only")
        self._masters.clicked.connect(lambda: self._start(masters_only=True))

        self._cancel = QPushButton("Cancel")
        self._cancel.setEnabled(False)
        self._cancel.clicked.connect(self._on_cancel)

        bar = QHBoxLayout()
        bar.addWidget(self._run)
        bar.addWidget(self._masters)
        bar.addWidget(self._cancel)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._caption = QLabel("Idle.")
        self._caption.setObjectName("PageSubtitle")
        layout.addWidget(self._caption)

        self._tasks = QTreeWidget()
        self._tasks.setHeaderLabels(["Target / stage / task", "Status / details"])
        self._tasks.setAlternatingRowColors(True)
        layout.addWidget(self._tasks, 1)

        if self.bus is not None:
            self.bus.received.connect(self._on_event)  # type: ignore[attr-defined]

    # --- actions ----------------------------------------------------------
    def _start(self, masters_only: bool) -> None:
        self._tasks.clear()
        self._targets.clear()
        self._running = None
        self._progress.setRange(0, 0)  # indeterminate until a tool reports a percentage
        self._caption.setText("Starting…")

        for button in (self._run, self._masters):
            button.setEnabled(False)
        self._cancel.setEnabled(True)

        self._worker = self.start_job(
            lambda report, token: process_job(report, token, masters_only=masters_only),
            on_progress=self._on_progress,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
        )

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.token.cancel()  # type: ignore[attr-defined]
            self._caption.setText("Cancelling at the next phase boundary…")

    # --- job callbacks ----------------------------------------------------
    def _on_progress(self, payload: object) -> None:
        self._caption.setText(str(payload))

    def _on_finished(self, result: object) -> None:
        self._finish()
        if isinstance(result, dict):
            message = str(result.get("message", "Done."))
            self._caption.setText(message)
        self.status.emit("Processing finished.")

    def _on_failed(self, message: str) -> None:
        self._finish()
        self._caption.setText(f"Failed: {message}")
        self.status.emit("Processing failed.")

    def _finish(self) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        for button in (self._run, self._masters):
            button.setEnabled(True)
        self._cancel.setEnabled(False)

    # --- core event rendering --------------------------------------------
    def _on_event(self, kind: str, data: dict) -> None:
        """Render one event published by the core."""
        if kind == events.EVENT_PROCESS_TARGET:
            label = data.get("target") or "masters"
            self._caption.setText(f"Target {data.get('index')}/{data.get('total')}: {label}")
        elif kind == events.EVENT_RUN_STARTED:
            self._ensure_target(str(data.get("target") or "masters")).setExpanded(True)
        elif kind == events.EVENT_TASK_STARTED:
            self._on_task_started(data)
        elif kind == events.EVENT_TASK_FINISHED:
            self._on_task_finished(data)
        elif kind == events.EVENT_TOOL_OUTPUT:
            self._append_log_line(
                str(data.get("line", "")), error=data.get("stream") == "stderr"
            )
        elif kind == events.EVENT_TOOL_PROGRESS:
            self._progress.setRange(0, 100)
            self._progress.setValue(int(data.get("percent") or 0))
        elif kind in (events.EVENT_STAGE_RESULT, events.EVENT_RUN_FINISHED):
            self._render_run(data.get("run"))
            notes = getattr(data.get("result"), "notes", None)
            if notes:
                self._caption.setText(str(notes))

    def _ensure_target(self, target: str) -> QTreeWidgetItem:
        """Return (creating if needed) the top-level item for a target."""
        item = self._targets.get(target)
        if item is None:
            item = QTreeWidgetItem([target, ""])
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            self._tasks.addTopLevelItem(item)
            self._targets[target] = item
        return item

    def _render_run(self, run: object) -> None:
        """Rebuild a target's subtree from a plain run-tree snapshot."""
        if not isinstance(run, dict):
            return
        target = str(run.get("target") or "masters")
        root = self._ensure_target(target)
        root.takeChildren()

        if run.get("output_url"):
            root.setText(1, "output →")

        for stage in run.get("stages", []):
            if not isinstance(stage, dict):
                continue
            status = RunStatus(stage.get("status", RunStatus.PENDING))
            stage_item = QTreeWidgetItem([self._stage_label(stage, status), status.label])
            stage_item.setData(0, _ROLE_KIND, _KIND_STAGE)
            stage_item.setData(0, _ROLE_NAME, str(stage.get("name") or ""))
            self._apply_status(stage_item, status)
            root.addChild(stage_item)
            # Keep stages open so their tasks (and each task's Log/Out) are visible.
            stage_item.setExpanded(True)

            tasks = [task for task in stage.get("tasks", []) if isinstance(task, dict)]
            for task in tasks:
                self._add_task_rows(task, stage_item)

            # A stage with no tasks (rare) still shows its own flat logs/outputs.
            if not tasks:
                for line in stage.get("logs", []):
                    log_item = QTreeWidgetItem([f"    {line}", ""])
                    log_item.setForeground(0, QBrush(QColor(_DIM)))
                    stage_item.addChild(log_item)
                outputs = self._file_labels(stage.get("outputs", []))
                if outputs:
                    stage_item.addChild(QTreeWidgetItem(["    out", outputs]))

        # Real targets open; master (calibration) runs stay collapsed — there are
        # usually many of them and they are rarely what the user is looking at.
        root.setExpanded(not run.get("is_master", False))
        self._tasks.scrollToItem(root)

    def _add_task_rows(self, task: dict, stage_item: QTreeWidgetItem) -> None:
        """Add one task row, plus its collapsible ``Log`` and ``Out`` children."""
        tstatus = RunStatus(task.get("status", RunStatus.PENDING))
        label = str(task.get("title") or task.get("name") or "task")
        details = tstatus.label
        if task.get("session"):
            details = f"{task['session']} — {details}"
        task_item = QTreeWidgetItem([f"    {label}", details])
        task_item.setData(0, _ROLE_KIND, _KIND_TASK)
        task_item.setData(0, _ROLE_NAME, str(task.get("name") or label))
        self._apply_status(task_item, tstatus)
        stage_item.addChild(task_item)

        logs = [str(line) for line in task.get("logs", [])]
        if logs or tstatus in (RunStatus.RUNNING, RunStatus.FAILED):
            log_node = QTreeWidgetItem(["      Log", ""])
            log_node.setData(0, _ROLE_KIND, _KIND_LOG)
            log_node.setForeground(0, QBrush(QColor(_DIM)))
            for line in logs:
                row = QTreeWidgetItem([f"        {line}", ""])
                row.setForeground(0, QBrush(QColor(_DIM)))
                log_node.addChild(row)
            # The running task's log is open; a finished one is closed (unless it
            # failed, where the error should stay visible).  Set this *after*
            # attaching - an unattached item cannot hold expansion state.
            task_item.addChild(log_node)
            log_node.setExpanded(tstatus in (RunStatus.RUNNING, RunStatus.FAILED))

        outputs = task.get("outputs", [])
        if isinstance(outputs, list) and outputs:
            out_node = QTreeWidgetItem(["      Out", self._file_labels(outputs)])
            out_node.setData(0, _ROLE_KIND, _KIND_OUT)
            out_node.setForeground(0, QBrush(QColor(_DIM)))
            for ref in outputs:
                if not isinstance(ref, dict):
                    continue
                out_node.addChild(
                    QTreeWidgetItem(
                        [f"        {ref.get('label', '')}", str(ref.get("url") or "")]
                    )
                )
            task_item.addChild(out_node)

        task_item.setExpanded(
            bool(logs or outputs or tstatus in (RunStatus.RUNNING, RunStatus.FAILED))
        )

    def _stage_item(self, target: str, stage: str) -> QTreeWidgetItem | None:
        """Find a stage row under a target (used for live log attribution)."""
        root = self._targets.get(target)
        if root is None:
            return None
        for index in range(root.childCount()):
            child = root.child(index)
            if child.data(0, _ROLE_KIND) == _KIND_STAGE and child.data(0, _ROLE_NAME) == stage:
                return child
        return None

    def _ensure_stage_item(self, target: str, stage: str) -> QTreeWidgetItem:
        """Return (creating if needed) a stage row, so live logs have a home."""
        root = self._ensure_target(target)
        item = self._stage_item(target, stage)
        if item is None:
            item = QTreeWidgetItem([f"{RunStatus.RUNNING.glyph} {stage}", ""])
            item.setData(0, _ROLE_KIND, _KIND_STAGE)
            item.setData(0, _ROLE_NAME, stage)
            self._apply_status(item, RunStatus.RUNNING)
            root.addChild(item)
            item.setExpanded(True)
        return item

    def _task_item(self, target: str, stage: str, task: str) -> QTreeWidgetItem | None:
        """Find a task row under a stage (used for live log attribution)."""
        stage_item = self._stage_item(target, stage)
        if stage_item is None:
            return None
        for index in range(stage_item.childCount()):
            child = stage_item.child(index)
            if child.data(0, _ROLE_KIND) == _KIND_TASK and child.data(0, _ROLE_NAME) == task:
                return child
        return None

    def _log_item(self, target: str, stage: str, task: str) -> QTreeWidgetItem | None:
        """Find the ``Log`` node of a task (used for live log attribution)."""
        task_item = self._task_item(target, stage, task)
        if task_item is None:
            return None
        for index in range(task_item.childCount()):
            child = task_item.child(index)
            if child.data(0, _ROLE_KIND) == _KIND_LOG:
                return child
        return None

    def _on_task_started(self, data: dict) -> None:
        """Create the running task's row (with an open ``Log``) so lines can land."""
        target = str(data.get("target") or "masters")
        stage = str(data.get("stage") or "")
        task = str(data.get("task") or "")
        title = str(data.get("title") or task or "task")
        self._caption.setText(f"Running: {title}")

        if not stage or not task:
            self._running = None
            return
        self._running = (target, stage, task)

        stage_item = self._ensure_stage_item(target, stage)
        task_item = self._task_item(target, stage, task)
        if task_item is None:
            task_item = QTreeWidgetItem([f"    {title}", RunStatus.RUNNING.label])
            task_item.setData(0, _ROLE_KIND, _KIND_TASK)
            task_item.setData(0, _ROLE_NAME, task)
            self._apply_status(task_item, RunStatus.RUNNING)
            stage_item.addChild(task_item)
        task_item.setExpanded(True)

        log_item = self._log_item(target, stage, task)
        if log_item is None:
            log_item = QTreeWidgetItem(["      Log", ""])
            log_item.setData(0, _ROLE_KIND, _KIND_LOG)
            log_item.setForeground(0, QBrush(QColor(_DIM)))
            task_item.insertChild(0, log_item)
        log_item.setExpanded(True)
        self._tasks.scrollToItem(task_item)

    def _on_task_finished(self, data: dict) -> None:
        """Close the finished task's ``Log`` node (a failure keeps it open)."""
        running = self._running
        self._running = None
        if running is None:
            return
        log_item = self._log_item(*running)
        if log_item is None:
            return
        log_item.setExpanded(data.get("success") is False)

    def _append_log_line(self, line: str, *, error: bool = False) -> None:
        """Append a streamed tool/log line under the running task's ``Log`` node."""
        if not line or self._running is None:
            return
        log_item = self._log_item(*self._running)
        if log_item is None:
            return

        item = QTreeWidgetItem([f"        {line}", ""])
        item.setForeground(0, QBrush(QColor("#f85149" if error else _DIM)))
        log_item.addChild(item)
        log_item.setExpanded(True)

        # Keep only the trailing lines so a chatty tool can't flood the tree.
        while log_item.childCount() > _LOG_LIMIT:
            log_item.removeChild(log_item.child(0))

        self._tasks.scrollToItem(item)

    @staticmethod
    def _stage_label(stage: dict, status: RunStatus) -> str:
        """A display label for a stage row (glyph + name + deps + excluded)."""
        name = stage.get("name")
        if stage.get("excluded"):
            return f"{RunStatus.EXCLUDED.glyph} {name} (excluded)"
        label = f"{status.glyph} {name}"
        if stage.get("dependencies"):
            label += f"  ← {', '.join(stage['dependencies'])}"
        return label

    @staticmethod
    def _file_labels(refs: object) -> str:
        """Human-readable labels for a list of plain file refs."""
        if not isinstance(refs, list):
            return ""
        labels = [str(ref.get("label")) for ref in refs if isinstance(ref, dict)]
        return ", ".join(labels)

    @staticmethod
    def _apply_status(item: QTreeWidgetItem, status: RunStatus) -> None:
        """Colour a row by its run status."""
        item.setForeground(0, QBrush(QColor(_STATUS_COLORS.get(status, "#c9d1d9"))))

