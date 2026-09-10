"""Base class and shared helpers for the GUI pages."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from starbash.app import Starbash
from starbash.ui.qt.models import DictTableModel
from starbash.ui.qt.workers import run_async

__all__ = ["Page"]


class Page(QWidget):
    """Base class for a top-level navigation page.

    Subclasses build their widgets in :meth:`_build` and reload data in
    :meth:`refresh`, which the main window calls whenever the page is shown.
    """

    #: Human-readable name shown in the navigation rail.
    nav_title = "Page"
    #: One-line description shown under the page heading.
    subtitle = ""
    #: Emitted with a short message for the window's status bar.
    status = Signal(str)

    def __init__(self, sb: Starbash, bus: object | None = None, parent: QWidget | None = None) -> None:
        """Create the page.

        Args:
            sb: the shared application context (used for reads on this thread).
            bus: the :class:`~starbash.ui.qt.bridge.EventBusBridge`, so the page
                can react to core events (may be ``None`` in tests).
            parent: optional parent widget.
        """
        super().__init__(parent)
        self.sb = sb
        self.bus = bus
        self._build()

    # --- API for subclasses ----------------------------------------------
    def _build(self) -> None:
        """Construct the page's widgets. Subclasses must override."""

    def refresh(self) -> None:
        """Reload data from the core. The default implementation does nothing."""

    # --- shared helpers ---------------------------------------------------
    def start_job(
        self,
        job: object,
        *,
        on_finished: object | None = None,
        on_failed: object | None = None,
        on_progress: object | None = None,
    ) -> object:
        """Run ``job`` on the thread pool, surfacing failures as a dialog.

        Returns the :class:`~starbash.ui.qt.workers.Worker` so callers can cancel
        it.  Any error is shown to the user and also forwarded to ``on_failed``.
        """

        def _failed(message: str) -> None:
            self.show_error(message)
            if callable(on_failed):
                on_failed(message)

        return run_async(
            job,  # type: ignore[arg-type]
            on_finished=on_finished,  # type: ignore[arg-type]
            on_failed=_failed,
            on_progress=on_progress,  # type: ignore[arg-type]
        )
    def heading(self, text: str | None = None, subtitle: str | None = None) -> QVBoxLayout:
        """Return a layout holding the page title block."""
        box = QVBoxLayout()
        box.setSpacing(2)

        title = QLabel(text or self.nav_title)
        title.setObjectName("PageTitle")
        box.addWidget(title)

        sub = QLabel(subtitle if subtitle is not None else self.subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        box.addWidget(sub)
        return box

    def make_table(self, model: DictTableModel) -> QTableView:
        """Create a consistently configured, read-only, sortable table view."""
        view = QTableView()
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setAlternatingRowColors(True)
        view.setSortingEnabled(True)
        view.verticalHeader().setVisible(False)
        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        view.horizontalHeader().setStretchLastSection(True)
        return view

    def show_error(self, message: str, title: str = "Starbash") -> None:
        """Show a modal error dialog."""
        QMessageBox.critical(self, title, message)

    def show_info(self, message: str, title: str = "Starbash") -> None:
        """Show a modal information dialog."""
        QMessageBox.information(self, title, message)
