"""Browse sessions, inspect their frames, and export a session's raw images."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from starbash.app import copy_images_to_dir
from starbash.ui.qt.models import IMAGE_COLUMNS, SESSION_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import load_session_images, load_sessions
from starbash.ui.qt.widgets import ImageViewer, SelectionPanel

__all__ = ["SessionsPage"]


class SessionsPage(Page):
    """The main working view: filter sessions, drill into frames, preview, export."""

    nav_title = "Sessions"
    subtitle = "Filter your sessions, inspect individual frames, and export raw data."

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._selection = SelectionPanel()
        self._selection.selectionChanged.connect(self.refresh)
        layout.addWidget(self._selection)

        self._session_model = DictTableModel(SESSION_COLUMNS)
        self._session_table = self.make_table(self._session_model)
        self._session_table.selectionModel().selectionChanged.connect(self._on_session_selected)

        self._image_model = DictTableModel(IMAGE_COLUMNS)
        self._image_table = self.make_table(self._image_model)
        self._image_table.selectionModel().selectionChanged.connect(self._on_image_selected)

        self._viewer = ImageViewer()

        right = QSplitter(Qt.Orientation.Horizontal)
        right.addWidget(self._image_table)
        right.addWidget(self._viewer)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 4)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._session_table)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self._export = QPushButton("Export session…")
        self._export.clicked.connect(self._on_export)
        self._export.setEnabled(False)

        self._summary = QLabel("")
        self._summary.setObjectName("PageSubtitle")

        bar = QHBoxLayout()
        bar.addWidget(self._export)
        bar.addWidget(self._summary, 1)
        layout.addLayout(bar)

    def refresh(self) -> None:
        """Reload the selection panel and the session table."""
        self._selection.load(self.sb)
        rows = load_sessions(self.sb)
        self._session_model.set_rows(rows)
        self._image_model.set_rows([])
        self._viewer.clear()
        self._export.setEnabled(False)

        summary = self.sb.selection.summary()
        if summary.get("status") == "all":
            self._summary.setText(f"{len(rows)} session(s) — no filters active.")
        else:
            self._summary.setText(
                f"{len(rows)} session(s) — " + "; ".join(summary.get("criteria", []))
            )

    def _selected_session(self) -> dict | None:
        indexes = self._session_table.selectionModel().selectedRows()
        return self._session_model.row_at(indexes[0].row()) if indexes else None

    def _on_session_selected(self) -> None:
        session = self._selected_session()
        self._viewer.clear()
        if session is None:
            self._image_model.set_rows([])
            self._export.setEnabled(False)
            return

        try:
            images = load_session_images(self.sb, session)
        except Exception as exc:  # noqa: BLE001 - show, don't crash
            self.show_error(f"Could not list frames: {exc}")
            return

        self._image_model.set_rows(images)
        self._export.setEnabled(bool(images))
        self.status.emit(f"{len(images)} frame(s) in the selected session.")

    def _on_image_selected(self) -> None:
        indexes = self._image_table.selectionModel().selectedRows()
        row = self._image_model.row_at(indexes[0].row()) if indexes else None
        if not row:
            self._viewer.clear()
            return
        path = row.get("abspath") or row.get("path")
        if not path:
            self._viewer.show_message(f"{row.get('basename', 'frame')}\n\nNo file path recorded.")
            return
        # Decoding happens on a worker thread and the viewer shows a busy arc;
        # an unreadable frame is reported in the viewer, not raised here.
        self._viewer.show_file(path)

    def _on_export(self) -> None:
        session = self._selected_session()
        if session is None:
            return
        destination = QFileDialog.getExistingDirectory(self, "Export session to folder")
        if not destination:
            return
        try:
            images = load_session_images(self.sb, session)
            copy_images_to_dir(images, Path(destination))
        except Exception as exc:  # noqa: BLE001 - report to the user
            self.show_error(f"Export failed: {exc}")
            return
        self.show_info(f"Exported {len(images)} frame(s) to {destination}.")
