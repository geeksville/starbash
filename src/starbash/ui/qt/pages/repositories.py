"""Manage the repositories Starbash reads raw and master frames from."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from starbash import events
from starbash.ui.qt.jobs import add_repo_job, reindex_job
from starbash.ui.qt.models import REPO_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import load_repos

__all__ = ["RepositoriesPage"]

#: (label, repo kind) pairs offered when adding a folder.
ADD_KINDS: list[tuple[str, str | None]] = [
    ("Raw images", None),
    ("Master frames", "master"),
    ("Processed output", "processed"),
]


class RepositoriesPage(Page):
    """Add/remove repository folders and re-index them with live progress."""

    nav_title = "Repositories"
    subtitle = "Add, remove and re-index the folders Starbash reads frames from."

    #: Emitted after a repository is added, since the repo list changed on disk.
    contextChanged = Signal()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._model = DictTableModel(REPO_COLUMNS)
        self._table = self.make_table(self._model)
        layout.addWidget(self._table, 1)

        self._kind = QComboBox()
        for label, value in ADD_KINDS:
            self._kind.addItem(label, value)

        self._add = QPushButton("Add folder…")
        self._add.clicked.connect(self._on_add)

        self._remove = QPushButton("Remove selected")
        self._remove.setObjectName("Danger")
        self._remove.clicked.connect(self._on_remove)

        self._reindex = QPushButton("Re-index all")
        self._reindex.setObjectName("Primary")
        self._reindex.clicked.connect(self._on_reindex)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Add as:"))
        bar.addWidget(self._kind)
        bar.addWidget(self._add)
        bar.addWidget(self._remove)
        bar.addStretch(1)
        bar.addWidget(self._reindex)
        layout.addLayout(bar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        if self.bus is not None:
            self.bus.received.connect(self._on_event)  # type: ignore[attr-defined]

    def refresh(self) -> None:
        """Reload the repository list."""
        self._model.set_rows(load_repos(self.sb))

    # --- actions ----------------------------------------------------------
    def _selected_url(self) -> tuple[dict | None, str]:
        indexes = self._table.selectionModel().selectedRows()
        row = self._model.row_at(indexes[0].row()) if indexes else None
        return row, (row or {}).get("url", "")

    def _on_add(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a repository folder")
        if not path:
            return
        kind = self._kind.currentData()
        self._busy(True, f"Adding {path}…")
        self.start_job(
            lambda report, token: add_repo_job(report, token, path, kind),
            on_progress=self._on_progress,
            on_finished=self._on_job_done,
        )

    def _on_remove(self) -> None:
        _row, url = self._selected_url()
        if not url:
            self.status.emit("Select a repository to remove first.")
            return
        try:
            self.sb.remove_repo_ref(url)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.show_error(f"Could not remove {url}: {exc}")
            return
        self.refresh()
        self.contextChanged.emit()
        self.status.emit(f"Removed repository: {url}")

    def _on_reindex(self) -> None:
        self._busy(True, "Re-indexing repositories…")
        self.start_job(
            lambda report, token: reindex_job(report, token),
            on_progress=self._on_progress,
            on_finished=self._on_job_done,
        )

    # --- job/event plumbing ----------------------------------------------
    def _on_job_done(self, result: object) -> None:
        self._busy(False)
        self.refresh()
        self.contextChanged.emit()
        if isinstance(result, dict) and result.get("message"):
            self.status.emit(str(result["message"]))

    def _on_progress(self, payload: object) -> None:
        self.status.emit(str(payload))

    def _on_event(self, kind: str, data: dict) -> None:
        """React to indexing progress published by the core."""
        if kind == events.EVENT_REINDEX_PROGRESS:
            total = int(data.get("total") or 0)
            done = int(data.get("done") or 0)
            if total:
                self._progress.setRange(0, total)
                self._progress.setValue(done)
            self.status.emit(f"Indexing {data.get('repo', '')} — {done}/{total}")
        elif kind == events.EVENT_REINDEX_FINISHED:
            self.status.emit(f"Indexed {data.get('indexed', 0)} file(s) in {data.get('repo', '')}")

    def _busy(self, busy: bool, message: str = "") -> None:
        for button in (self._add, self._remove, self._reindex):
            button.setEnabled(not busy)
        self._progress.setVisible(busy)
        if busy:
            self._progress.setRange(0, 0)  # indeterminate until the first progress event
        if message:
            self.status.emit(message)
