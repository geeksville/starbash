"""Browse the indexed master calibration frames."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout

from starbash.ui.qt.models import MASTER_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import image_basename, load_masters
from starbash.ui.qt.widgets import ImageViewer

__all__ = ["MastersPage"]


class MastersPage(Page):
    """List master bias/dark/flat frames and preview the selected one."""

    nav_title = "Masters"
    subtitle = "Master calibration frames Starbash can reuse when processing."

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._model = DictTableModel(MASTER_COLUMNS)
        self._table = self.make_table(self._model)
        self._table.selectionModel().selectionChanged.connect(self._on_selected)

        self._viewer = ImageViewer()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._table)
        splitter.addWidget(self._viewer)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter, 1)

        self._count = QLabel("")
        self._count.setObjectName("PageSubtitle")
        layout.addWidget(self._count)

    def refresh(self) -> None:
        """Reload the master list."""
        rows = load_masters(self.sb)
        self._model.set_rows(rows)
        self._count.setText(f"{len(rows)} master frame(s).")
        self._viewer.clear()

    def _on_selected(self) -> None:
        indexes = self._table.selectionModel().selectedRows()
        row = self._model.row_at(indexes[0].row()) if indexes else None
        if not row:
            self._viewer.clear()
            return
        path = row.get("abspath") or row.get("path")
        if not path:
            self._viewer.show_message(f"{image_basename(row)}\n\nNo file path recorded.")
            return
        try:
            self._viewer.show_file(path)
        except Exception as exc:  # noqa: BLE001 - a bad frame must not break the page
            self._viewer.show_message(f"{image_basename(row)}\n\nPreview failed:\n{exc}")
