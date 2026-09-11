"""Run the automated pipeline with a live task tree and progress bar.

Nothing here polls: the core publishes tool output, task transitions and stage
results on the event bus, and this page renders them as they arrive.  Tool output
lands under the stage node it belongs to, so the tree *is* the log.
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
from starbash.run_state import RunStatus
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

#: How many live tool-log lines to keep visible under one stage node.
_LIVE_LOG_LIMIT = 12

_DIM = "#8b949e"


class ProcessingPage(Page):
    """Trigger a processing run and watch it happen, live."""

    nav_title = "Processing"
    subtitle = "Run the automated pipeline and watch every stage, tool and log line."

    def _build(self) -> None:
        self._worker = None
        self._targets: dict[str, QTreeWidgetItem] = {}
        self._current: tuple[str, str] | None = None  # (target, stage) running now
        self._live_logs: dict[tuple[str, str], list[QTreeWidgetItem]] = {}

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
        self._current = None
        self._live_logs.clear()
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
            title = str(data.get("title") or data.get("task") or "task")
            self._caption.setText(f"Running: {title}")
            stage = str(data.get("stage") or "")
            self._current = (str(data.get("target") or "masters"), stage) if stage else None
        elif kind == events.EVENT_TASK_FINISHED:
            self._current = None
        elif kind == events.EVENT_TOOL_OUTPUT:
            self._append_log_line(
                str(data.get("line", "")), error=data.get("stream") == "stderr"
            )
        elif kind == events.EVENT_TOOL_PROGRESS:
            self._progress.setRange(0, 100)
            self._progress.setValue(int(data.get("percent") or 0))
        elif kind in (events.EVENT_STAGE_RESULT, events.EVENT_RUN_FINISHED):
            self._render_run(data.get("run"))
            self._current = None
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
        # The rebuilt children invalidate any live log rows we appended.
        for key in [k for k in self._live_logs if k[0] == target]:
            del self._live_logs[key]

        if run.get("output_url"):
            root.setText(1, "output →")

        for stage in run.get("stages", []):
            if not isinstance(stage, dict):
                continue
            status = RunStatus(stage.get("status", RunStatus.PENDING))
            stage_item = QTreeWidgetItem([self._stage_label(stage, status), status.label])
            stage_item.setData(0, Qt.ItemDataRole.UserRole, str(stage.get("name") or ""))
            self._apply_status(stage_item, status)
            root.addChild(stage_item)

            for line in stage.get("logs", []):
                log_item = QTreeWidgetItem([f"    {line}", ""])
                log_item.setForeground(0, QBrush(QColor(_DIM)))
                stage_item.addChild(log_item)

            outputs = self._file_labels(stage.get("outputs", []))
            if outputs:
                stage_item.addChild(QTreeWidgetItem(["    out", outputs]))

            for task in stage.get("tasks", []):
                if not isinstance(task, dict):
                    continue
                tstatus = RunStatus(task.get("status", RunStatus.PENDING))
                label = str(task.get("title") or task.get("name") or "task")
                details = tstatus.label
                if task.get("session"):
                    details = f"{task['session']} — {details}"
                task_item = QTreeWidgetItem([f"    {label}", details])
                self._apply_status(task_item, tstatus)
                stage_item.addChild(task_item)

        # Real targets open; master (calibration) runs stay collapsed — there are
        # usually many of them and they are rarely what the user is looking at.
        root.setExpanded(not run.get("is_master", False))
        self._tasks.scrollToItem(root)

    def _stage_item(self, target: str, stage: str) -> QTreeWidgetItem | None:
        """Find a stage row under a target (used for live log attribution)."""
        root = self._targets.get(target)
        if root is None:
            return None
        for index in range(root.childCount()):
            child = root.child(index)
            if child.data(0, Qt.ItemDataRole.UserRole) == stage:
                return child
        return None

    def _append_log_line(self, line: str, *, error: bool = False) -> None:
        """Append a streamed tool/log line under the currently running stage."""
        if not line or self._current is None:
            return
        target, stage = self._current
        stage_item = self._stage_item(target, stage)
        if stage_item is None:
            return

        item = QTreeWidgetItem([f"      {line}", ""])
        item.setForeground(0, QBrush(QColor("#f85149" if error else _DIM)))
        stage_item.addChild(item)
        stage_item.setExpanded(True)

        # Keep only the trailing lines so a chatty tool can't flood the tree.
        rows = self._live_logs.setdefault((target, stage), [])
        rows.append(item)
        while len(rows) > _LIVE_LOG_LIMIT:
            stale = rows.pop(0)
            parent = stale.parent()
            if parent is not None:
                parent.removeChild(stale)

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

