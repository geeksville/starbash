"""Run the automated pipeline with a live task tree, progress bar and log.

Nothing here polls: the core publishes tool output, task transitions and stage
results on the event bus, and this page renders them as they arrive.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from starbash import events
from starbash.ui.qt.jobs import process_job
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.widgets import LogView

__all__ = ["ProcessingPage"]


class ProcessingPage(Page):
    """Trigger a processing run and watch it happen, live."""

    nav_title = "Processing"
    subtitle = "Run the automated pipeline and watch every stage, tool and log line."

    def _build(self) -> None:
        self._worker = None
        self._items: dict[str, QTreeWidgetItem] = {}

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
        self._tasks.setHeaderLabels(["Stage / task", "Result"])
        self._tasks.setAlternatingRowColors(True)
        self._log = LogView()

        panes = QSplitter(Qt.Orientation.Vertical)
        panes.addWidget(self._tasks)
        panes.addWidget(self._log)
        panes.setStretchFactor(0, 2)
        panes.setStretchFactor(1, 3)
        layout.addWidget(panes, 1)

        if self.bus is not None:
            self.bus.received.connect(self._on_event)  # type: ignore[attr-defined]

    # --- actions ----------------------------------------------------------
    def _start(self, masters_only: bool) -> None:
        self._log.clear_log()
        self._tasks.clear()
        self._items.clear()
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
            self._log.append_line(message, "success")
        self.status.emit("Processing finished.")

    def _on_failed(self, message: str) -> None:
        self._finish()
        self._caption.setText(f"Failed: {message}")
        self._log.append_line(f"Failed: {message}", "error")
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
        elif kind == events.EVENT_TASK_STARTED:
            title = str(data.get("title") or data.get("task") or "task")
            item = QTreeWidgetItem([title, "running…"])
            self._tasks.addTopLevelItem(item)
            self._tasks.scrollToItem(item)
            self._items[str(data.get("task"))] = item
        elif kind == events.EVENT_TASK_FINISHED:
            self._render_task_finished(data)
        elif kind == events.EVENT_TOOL_OUTPUT:
            level = "error" if data.get("stream") == "stderr" else "tool"
            self._log.append_line(str(data.get("line", "")), level)
        elif kind == events.EVENT_TOOL_PROGRESS:
            self._progress.setRange(0, 100)
            self._progress.setValue(int(data.get("percent") or 0))
        elif kind == events.EVENT_STAGE_RESULT:
            notes = getattr(data.get("result"), "notes", None)
            if notes:
                self._log.append_line(f"• {notes}", "info")

    def _render_task_finished(self, data: dict) -> None:
        """Update the task tree row and append a log line for a finished task."""
        success = data.get("success")
        reason = data.get("reason")
        if success:
            label, level = "ok", "success"
        elif success is None:
            label, level = (f"skipped ({reason})" if reason else "skipped"), "info"
        else:
            label, level = "FAILED", "error"

        item = self._items.get(str(data.get("task")))
        if item is not None:
            item.setText(1, label)

        title = str(data.get("title") or data.get("task") or "task")
        self._log.append_line(f"{title} — {label}", level)

