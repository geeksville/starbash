"""Review processed targets and choose which stages run for each.

Edits the same ``[[stages]]`` array-of-tables (``name`` / ``excluded``) that
``sb process`` reads, via :mod:`starbash.stage_utils`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from starbash.ui.qt.models import TARGET_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import load_target_config, load_targets, save_target_stages

__all__ = ["TargetsPage"]


class TargetsPage(Page):
    """Pick a processed target, then tick/untick its stages and save."""

    nav_title = "Targets"
    subtitle = "Review processed targets and choose which stages run for each."

    def _build(self) -> None:
        self._current: dict | None = None

        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._model = DictTableModel(TARGET_COLUMNS)
        self._table = self.make_table(self._model)
        self._table.selectionModel().selectionChanged.connect(self._on_target_selected)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(QLabel("Stages — ticked = active, unticked = excluded"))

        self._stages = QListWidget()
        panel_layout.addWidget(self._stages, 1)

        self._save = QPushButton("Save stage selection")
        self._save.setObjectName("Primary")
        self._save.setEnabled(False)
        self._save.clicked.connect(self._on_save)
        panel_layout.addWidget(self._save)

        self._path = QLabel("")
        self._path.setObjectName("PageSubtitle")
        self._path.setWordWrap(True)
        panel_layout.addWidget(self._path)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._table)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        """Reload the list of processed targets."""
        self._model.set_rows(load_targets(self.sb))
        self._stages.clear()
        self._save.setEnabled(False)
        self._current = None
        self._path.setText("")

    def _on_target_selected(self) -> None:
        indexes = self._table.selectionModel().selectedRows()
        row = self._model.row_at(indexes[0].row()) if indexes else None
        self._current = row
        self._stages.clear()

        if not row:
            self._save.setEnabled(False)
            self._path.setText("")
            return

        try:
            stages = load_target_config(row["path"])
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.show_error(f"Could not read target config: {exc}")
            return

        for stage in stages:
            item = QListWidgetItem(stage["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked if stage["excluded"] else Qt.CheckState.Checked
            )
            self._stages.addItem(item)

        self._save.setEnabled(bool(stages))
        self._path.setText(row.get("path", ""))

    def _on_save(self) -> None:
        if not self._current:
            return
        used: list[str] = []
        excluded: list[str] = []
        for index in range(self._stages.count()):
            item = self._stages.item(index)
            target = used if item.checkState() == Qt.CheckState.Checked else excluded
            target.append(item.text())

        try:
            save_target_stages(self._current["path"], used, excluded)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.show_error(f"Could not save stage selection: {exc}")
            return

        self.status.emit(f"Saved stage selection for {self._current['target']}.")
        self.refresh()
