"""Editing panel for the persistent session selection.

Mirrors ``sb select ...``: the same :class:`~starbash.selection.Selection`
object is written, so the CLI and GUI always agree about what is selected.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from starbash.app import Starbash
from starbash.database import Database

__all__ = ["SelectionPanel"]


def _split(text: str) -> list[str]:
    """Split a comma-separated entry into clean values."""
    return [part.strip() for part in text.split(",") if part.strip()]


def _join(values: list[str]) -> str:
    """Render a list of values as a comma-separated string."""
    return ", ".join(values)


class SelectionPanel(QGroupBox):
    """A form that edits targets/telescopes/filters/types and a date range.

    Emits :attr:`selectionChanged` after a successful ``Apply`` (or ``Clear``) so
    the owning page can refresh its results.
    """

    selectionChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Selection", parent)
        self._sb: Starbash | None = None

        self._targets = QLineEdit()
        self._telescopes = QLineEdit()
        self._filters = QLineEdit()
        self._image_types = QLineEdit()
        for field, placeholder in (
            (self._targets, "e.g. m31, ngc7000"),
            (self._telescopes, "e.g. seestar s50"),
            (self._filters, "e.g. Ha, OIII"),
            (self._image_types, "e.g. LIGHT, FLAT"),
        ):
            field.setPlaceholderText(placeholder)

        self._use_start = QCheckBox("From")
        self._date_start = QDateEdit()
        self._date_start.setCalendarPopup(True)
        self._date_start.setDisplayFormat("yyyy-MM-dd")
        self._date_start.setDate(QDate.currentDate())
        self._date_start.setEnabled(False)
        self._use_start.toggled.connect(self._date_start.setEnabled)

        self._use_end = QCheckBox("To")
        self._date_end = QDateEdit()
        self._date_end.setCalendarPopup(True)
        self._date_end.setDisplayFormat("yyyy-MM-dd")
        self._date_end.setDate(QDate.currentDate())
        self._date_end.setEnabled(False)
        self._use_end.toggled.connect(self._date_end.setEnabled)

        dates = QHBoxLayout()
        dates.addWidget(self._use_start)
        dates.addWidget(self._date_start)
        dates.addWidget(self._use_end)
        dates.addWidget(self._date_end)
        dates.addStretch(1)

        form = QFormLayout()
        form.addRow("Targets", self._targets)
        form.addRow("Telescopes", self._telescopes)
        form.addRow("Filters", self._filters)
        form.addRow("Image types", self._image_types)
        form.addRow("Dates", dates)

        self._apply = QPushButton("Apply filters")
        self._apply.setObjectName("Primary")
        self._apply.clicked.connect(self._on_apply)
        self._clear = QPushButton("Clear (select all)")
        self._clear.clicked.connect(self._on_clear)

        buttons = QHBoxLayout()
        buttons.addWidget(self._apply)
        buttons.addWidget(self._clear)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    # --- population -------------------------------------------------------
    def load(self, sb: Starbash) -> None:
        """Fill the fields from the current selection and DB suggestions."""
        self._sb = sb
        selection = sb.selection
        self._targets.setText(_join(selection.targets))
        self._telescopes.setText(_join(selection.telescopes))
        self._filters.setText(_join(selection.filters))
        self._image_types.setText(_join(selection.image_types))

        self._set_date(self._use_start, self._date_start, selection.date_start)
        self._set_date(self._use_end, self._date_end, selection.date_end)

        self._suggest(self._targets, sb, "object")
        self._suggest(self._telescopes, sb, "telescop")
        self._suggest(self._filters, sb, "filter")
        self._suggest(self._image_types, sb, "imagetyp")

    @staticmethod
    def _set_date(toggle: QCheckBox, editor: QDateEdit, value: str | None) -> None:
        """Apply a stored ISO date (or clear it) to a toggle/editor pair."""
        if value:
            date = QDate.fromString(str(value)[:10], Qt.DateFormat.ISODate)
            if date.isValid():
                editor.setDate(date)
            toggle.setChecked(True)
        else:
            toggle.setChecked(False)

    @staticmethod
    def _suggest(field: QLineEdit, sb: Starbash, column: str) -> None:
        """Attach a case-insensitive completer of existing DB values."""
        try:
            values = {str(v) for v in sb.db.get_column(Database.SESSIONS_TABLE, column) if v}
        except Exception:  # noqa: BLE001 - suggestions are best-effort only
            return
        if not values:
            return
        completer = QCompleter(QStringListModel(sorted(values)), field)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        field.setCompleter(completer)

    # --- actions ----------------------------------------------------------
    def _on_apply(self) -> None:
        self._write()
        self.selectionChanged.emit()

    def _on_clear(self) -> None:
        for field in (self._targets, self._telescopes, self._filters, self._image_types):
            field.clear()
        self._use_start.setChecked(False)
        self._use_end.setChecked(False)
        self._write()
        self.selectionChanged.emit()

    def _write(self) -> None:
        """Push the form state onto the shared selection and persist it."""
        if self._sb is None:
            return
        selection = self._sb.selection
        selection.set_targets(_split(self._targets.text()))
        selection.set_telescopes(_split(self._telescopes.text()))
        selection.set_filters(_split(self._filters.text()))
        selection.set_image_types(_split(self._image_types.text()))

        start = (
            self._date_start.date().toString(Qt.DateFormat.ISODate)
            if self._use_start.isChecked()
            else None
        )
        end = (
            self._date_end.date().toString(Qt.DateFormat.ISODate)
            if self._use_end.isChecked()
            else None
        )
        selection.set_date_range(start, end)
