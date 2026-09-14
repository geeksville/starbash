"""Pick which calibration master a processed session uses.

One :class:`MasterPicker` shows the scored candidates for a single
``(session, calibration type)`` pair.  A radio-style check column marks the
current selection; choosing another row is the "elegant way to change it" the
Targets screen needs.  The widget is purely a view + chooser — the page owns the
dirty/save bookkeeping and writes ``selected_by = "user"`` through
:func:`starbash.ui.qt.services.save_master_selections`.

See ``doc/plans/session-masters.md`` for the on-disk schema.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starbash.ui.qt.services import MasterCandidate, SessionMasterOption
from starbash.ui.qt.widgets.file_links import LinkDecorator, set_link

__all__ = ["MasterPicker"]

#: Column indices in the candidate table.
_COL_CHECK = 0
_COL_MASTER = 1
_COL_SCORE = 2
_COL_WHY = 3


def _why_text(candidate: MasterCandidate) -> str:
    """Human explanation for a candidate, from its recorded reason fragments."""
    return " · ".join(candidate.reasons) if candidate.reasons else ""


def _score_text(candidate: MasterCandidate) -> str:
    """Score column text (blank for legacy candidates that recorded none)."""
    return "" if candidate.score is None else f"{round(candidate.score)}"


class MasterPicker(QWidget):
    """A radio list of the master candidates for one session + calibration type.

    Given a URL resolver, each candidate's Master cell is also a *link*: hovering it
    previews that master frame and activating the row (double-click / Enter) opens
    it.  A plain click still just chooses the master - opening a FITS file every
    time the user picked a row would be hostile.
    """

    #: Emitted with ``(session_key, master_type, path)`` when the user changes the
    #: selection.  The page decides whether that makes it dirty and when to save.
    selectionChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the (empty) picker; call :meth:`set_context` to fill it."""
        super().__init__(parent)
        self._key: tuple[str, ...] = ()
        self._master_type: str = ""
        self._paths: list[str] = []
        self._default_path: str | None = None
        #: Maps a candidate's repo-relative path to a file URL (None = plain rows).
        self._resolve_url: Callable[[str], str | None] | None = None
        #: True while we populate the table, so our own edits don't look like input.
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._title = QLabel("")
        self._title.setObjectName("MasterPickerTitle")
        layout.addWidget(self._title)

        self._hint = QLabel("")
        self._hint.setObjectName("MasterPickerHint")
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setObjectName("MasterPickerTable")
        self._table.setHorizontalHeaderLabels(["", "Master", "Score", "Why"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_CHECK, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(_COL_CHECK, 30)
        self._table.setColumnWidth(_COL_MASTER, 240)
        header.setSectionResizeMode(_COL_WHY, QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table, 1)

        #: Hover-preview + open for the Master cells; *not* on a plain click, which
        #: is how a row is chosen here.
        self._links = LinkDecorator(self._table, parent=self, open_on="activated")

        row = QHBoxLayout()
        self._reset = QPushButton("Reset to automatic")
        self._reset.setObjectName("MasterPickerReset")
        self._reset.clicked.connect(self._on_reset)
        row.addWidget(self._reset)
        row.addStretch(1)
        layout.addLayout(row)

    # --- API for the page -------------------------------------------------

    def set_context(
        self,
        label: str,
        key: tuple[str, ...],
        option: SessionMasterOption,
        *,
        resolve_url: Callable[[str], str | None] | None = None,
    ) -> None:
        """Fill the picker with ``option``'s candidates for one session.

        ``resolve_url`` maps a candidate's repo-relative path to a file URL, which
        makes each Master cell previewable on hover (and openable when activated).
        Without it the rows are plain text - which is all a caller that has no
        master repo to resolve against can offer.
        """
        self._key = key
        self._master_type = option.type
        self._resolve_url = resolve_url
        # The rows are about to be replaced; any preview of the old ones is stale.
        self._links.dismiss()
        self._paths = []
        self._default_path = next(
            (candidate.path for candidate in option.candidates if candidate.selected),
            option.candidates[0].path if option.candidates else None,
        )

        self._title.setText(f"{option.type.title()} master · {label}")
        self._hint.setText(self._hint_text(option))

        self._updating = True
        try:
            self._table.setRowCount(0)
            for candidate in option.candidates:
                self._append_row(candidate)
        finally:
            self._updating = False

    def selection(self) -> tuple[tuple[str, ...], str, str | None]:
        """Return the ``(session_key, master_type, path)`` currently checked."""
        return (self._key, self._master_type, self._checked_path())

    def default_path(self) -> str | None:
        """The candidate processing selected on the last run (its ``auto`` pick)."""
        return self._default_path

    # --- internals --------------------------------------------------------

    @staticmethod
    def _hint_text(option: SessionMasterOption) -> str:
        """Explain who chose the current master and how many alternatives exist."""
        count = len(option.candidates)
        alternatives = f"{count - 1} other candidate{'s' if count != 2 else ''}"
        if option.selected_by == "user":
            return f"You chose this master. {alternatives} considered."
        return f"Automatically selected by the scorer. {alternatives} considered."

    def _append_row(self, candidate: MasterCandidate) -> None:
        """Add one candidate as a table row."""
        row = self._table.rowCount()
        self._table.insertRow(row)

        check = QTableWidgetItem("")
        check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        check.setCheckState(
            Qt.CheckState.Checked if candidate.selected else Qt.CheckState.Unchecked
        )
        check.setToolTip("Use this master")
        self._table.setItem(row, _COL_CHECK, check)

        name = QTableWidgetItem(Path(candidate.path).name)
        name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        name.setToolTip(candidate.path)
        if self._resolve_url is not None:
            # The Master cell *is* the file name, so it is the one that previews.
            set_link(name, _COL_MASTER, self._resolve_url(candidate.path))
        self._table.setItem(row, _COL_MASTER, name)

        score = QTableWidgetItem(_score_text(candidate))
        score.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        score.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._table.setItem(row, _COL_SCORE, score)

        why = QTableWidgetItem(_why_text(candidate))
        why.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._table.setItem(row, _COL_WHY, why)

        self._paths.append(candidate.path)

    def _checked_path(self) -> str | None:
        """The path of the currently checked row, if any."""
        for row, path in enumerate(self._paths):
            item = self._table.item(row, _COL_CHECK)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                return path
        return None

    def _check_row(self, row: int) -> None:
        """Check ``row`` and uncheck every other row (radio semantics)."""
        if row < 0 or row >= len(self._paths):
            return
        self._updating = True
        try:
            for other in range(len(self._paths)):
                item = self._table.item(other, _COL_CHECK)
                if item is not None:
                    item.setCheckState(
                        Qt.CheckState.Checked if other == row else Qt.CheckState.Unchecked
                    )
            self._table.selectRow(row)
        finally:
            self._updating = False

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        """Any click in a row selects that master."""
        if self._updating or row < 0 or row >= len(self._paths):
            return
        if self._checked_path() == self._paths[row]:
            return
        self._check_row(row)
        self._emit_selection()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Keep the check column exclusive when Qt toggles a box itself."""
        if self._updating or item.column() != _COL_CHECK:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._check_row(item.row())
            self._emit_selection()
        else:
            # Refuse to leave nothing selected: put the tick back.
            item.setCheckState(Qt.CheckState.Checked)

    def _on_reset(self) -> None:
        """Revert to the candidate processing picked automatically."""
        if self._default_path is None:
            return
        try:
            row = self._paths.index(self._default_path)
        except ValueError:
            return
        self._check_row(row)
        self._emit_selection()

    def _emit_selection(self) -> None:
        """Announce the current pick to the page."""
        self.selectionChanged.emit(self.selection())
