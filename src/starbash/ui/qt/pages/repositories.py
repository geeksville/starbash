"""Manage the repositories Starbash reads raw and master frames from."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
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
        #: True while a job runs, so *Remove selected* stays disabled no matter
        #: what the table selection is doing.
        self._busy_state = False

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
        self._remove.setEnabled(False)  # nothing is selected yet
        self._table.selectionModel().selectionChanged.connect(self._update_remove_enabled)

        self._show_all = QCheckBox("Show all repositories")
        self._show_all.setToolTip(
            "Also list the internal repositories Starbash manages for you "
            "(preferences, recipes and the built-in defaults)."
        )
        self._show_all.toggled.connect(self.refresh)

        self._reindex = QPushButton("Re-index all")
        self._reindex.setObjectName("Primary")
        self._reindex.clicked.connect(self._on_reindex)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Add as:"))
        bar.addWidget(self._kind)
        bar.addWidget(self._add)
        bar.addWidget(self._remove)
        bar.addWidget(self._show_all)
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
        self._model.set_rows(load_repos(self.sb, show_all=self._show_all.isChecked()))
        self._update_add_kinds()
        self._update_remove_enabled()

    # --- button/kind state -------------------------------------------------
    def _update_add_kinds(self) -> None:
        """Disable add kinds that already have a repository.

        Master and processed output repos are restricted to one each (see
        ``sb repo add``), so offering to add a second one is a trap.  Raw image
        repos may be added as many times as the user likes.
        """
        kinds = [value for _label, value in ADD_KINDS if value]
        present = {kind for kind in kinds if self.sb.repo_manager.get_repo_by_kind(kind)}

        model = self._kind.model()
        for index, (_label, value) in enumerate(ADD_KINDS):
            if value is None or not isinstance(model, QStandardItemModel):
                continue
            item = model.item(index)
            if item is not None:
                item.setEnabled(value not in present)

        # If the current choice just became unavailable, fall back to an enabled
        # one - otherwise "Add folder…" would try to add a kind we already have.
        if not self._kind_enabled(self._kind.currentIndex()):
            for index in range(self._kind.count()):
                if self._kind_enabled(index):
                    self._kind.setCurrentIndex(index)
                    break

    def _kind_enabled(self, index: int) -> bool:
        """Return whether the add-kind entry at ``index`` may be chosen."""
        model = self._kind.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(index)
            if item is not None:
                return item.isEnabled()
        return True

    def _update_remove_enabled(self) -> None:
        """Enable *Remove selected* only for a repo the user can actually remove.

        Repositories Starbash manages itself (the recipes checkout, the built-in
        defaults and the preferences repo) have no entry in the user config, so
        they cannot be removed individually; the button stays off for them rather
        than offering a click that can only fail after the fact.
        """
        _row, url = self._selected_url()
        removable = bool(url) and self.sb.is_repo_removable(url)
        self._remove.setEnabled(removable and not self._busy_state)
        self._remove.setToolTip(
            "" if removable or not url else f"{url} is managed by Starbash and cannot be removed."
        )

    # --- actions ----------------------------------------------------------
    def _selected_url(self) -> tuple[dict | None, str]:
        """The selected row (if any) and its repository URL ('' when none)."""
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
        if not self.sb.is_repo_removable(url):
            # Defensive: the button is disabled for these, but never silently
            # drop indexed rows for a repository we cannot actually remove.
            self.status.emit(f"{url} is managed by Starbash and cannot be removed.")
            return
        try:
            removal = self.sb.remove_repo_ref(url)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.show_error(f"Could not remove {url}: {exc}")
            return
        self.refresh()
        self.contextChanged.emit()
        self.status.emit(f"Removed repository: {url} — {removal.summary()}")

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
        self._busy_state = busy
        for button in (self._add, self._reindex):
            button.setEnabled(not busy)
        self._update_remove_enabled()
        self._progress.setVisible(busy)
        if busy:
            self._progress.setRange(0, 0)  # indeterminate until the first progress event
        if message:
            self.status.emit(message)
