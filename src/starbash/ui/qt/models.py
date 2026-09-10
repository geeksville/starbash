"""Qt table models backed by plain dictionaries.

The core returns ``sqlite3.Row`` objects, which must never cross a thread
boundary into live use.  Workers therefore convert rows to plain dicts (see
:func:`plain_row`) before emitting them, and these models know nothing about the
database - they only format dictionaries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from starbash.database import Database

__all__ = [
    "Column",
    "DictTableModel",
    "format_minutes",
    "plain_row",
    "plain_rows",
]

#: Qt passes either type to model methods, so overrides must accept both.
ModelIndex = QModelIndex | QPersistentModelIndex


def plain_row(row: Any) -> dict[str, Any]:
    """Coerce a ``sqlite3.Row`` / mapping into a plain ``dict``.

    Values are left as-is; callers only need the *keys* to be addressable as a
    normal dict so the result can cross thread boundaries safely.
    """
    if isinstance(row, dict):
        return row
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {str(key): row[key] for key in cast(Iterable[str], keys())}
    raise TypeError(f"Cannot convert {type(row)!r} to a plain row")


def plain_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert an iterable of rows to a list of plain dicts."""
    return [plain_row(row) for row in rows]


def format_minutes(seconds: Any) -> str:
    """Render a duration in seconds as approximately whole minutes.

    Used by compact session tables, where "424" reads far better than
    "25440.0" (and sidesteps float noise like "4.33369999999999").
    """
    try:
        minutes = float(seconds) / 60.0
    except (TypeError, ValueError):
        return ""
    return f"{minutes:.0f}"


@dataclass(frozen=True)
class Column:
    """Describes one table column: its header, source key, width and formatter."""

    header: str
    key: str
    width: int = 120
    align_right: bool = False
    fmt: Callable[[Any], str] | None = None

    def render(self, row: Mapping[str, Any]) -> str:
        """Format ``row``'s value for this column as display text."""
        value = row.get(self.key)
        if value is None:
            return ""
        if self.fmt is not None:
            return self.fmt(value)
        return str(value)


class DictTableModel(QAbstractTableModel):
    """A read-only table model over a list of dictionaries."""

    def __init__(self, columns: list[Column], parent: Any = None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._rows: list[dict[str, Any]] = []

    # --- data management -------------------------------------------------
    def set_rows(self, rows: Iterable[Any]) -> None:
        """Replace the table contents, converting rows to plain dicts."""
        self.beginResetModel()
        self._rows = [plain_row(row) for row in rows]
        self.endResetModel()

    def rows(self) -> list[dict[str, Any]]:
        """Return the current rows (as plain dicts)."""
        return self._rows

    def columns(self) -> list[Column]:
        """Return the column definitions (used to size the table view)."""
        return self._columns

    def row_at(self, index: int) -> dict[str, Any] | None:
        """Return the row dict at ``index`` or ``None`` when out of range."""
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def update_cells(self, row_index: int, values: dict[str, Any]) -> None:
        """Merge ``values`` into one row and notify the view.

        Unlike :meth:`set_rows` this preserves the current selection, which matters
        when saving edits to the row the user is working on.
        """
        if not 0 <= row_index < len(self._rows):
            return
        self._rows[row_index].update(values)
        self.dataChanged.emit(
            self.index(row_index, 0), self.index(row_index, len(self._columns) - 1)
        )

    # --- QAbstractTableModel API -----------------------------------------
    def rowCount(self, parent: ModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: ModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = self._columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return column.render(row)

        if role == Qt.ItemDataRole.TextAlignmentRole and column.align_right:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ToolTipRole:
            value = row.get(column.key)
            return str(value) if value is not None else None

        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].header
        return section + 1

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort rows by a column's raw value (stable)."""
        key = self._columns[column].key
        reverse = order == Qt.SortOrder.DescendingOrder
        self.beginResetModel()
        self._rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=reverse)
        self.endResetModel()


# --- Column definitions used by the pages ---------------------------------
#
# Pages pre-shape each row into a plain dict whose keys match these `Column.key`
# values, so the models stay completely free of database knowledge.

SESSION_COLUMNS = [
    Column("Target", "object", 170),
    Column("Filter", "filter", 100),
    Column("Type", "imagetyp", 90),
    Column("Start", "start", 170),
    Column("Frames", "num_images", 80, align_right=True),
    Column(
        "Integration (min)",
        "exptime_total",
        140,
        align_right=True,
        fmt=format_minutes,
    ),
]

IMAGE_COLUMNS = [
    Column("File", "basename", 280),
    Column("Filter", Database.FILTER_KEY, 90),
    Column("Type", Database.IMAGETYP_KEY, 90),
    Column("Exposure", Database.EXPTIME_KEY, 90, align_right=True),
    Column("Observed", Database.DATE_OBS_KEY, 180),
]

REPO_COLUMNS = [
    Column("Kind", "kind", 100),
    Column("URL", "url", 460),
    Column("Images", "images", 90, align_right=True),
]

TARGET_COLUMNS = [
    Column("Target", "target", 160),
    Column("Active stages", "used", 110, align_right=True),
    Column("Excluded", "excluded", 100, align_right=True),
    Column("Output", "path", 460),
]

MASTER_COLUMNS = [
    Column("File", "basename", 300),
    Column("Type", Database.IMAGETYP_KEY, 100),
    Column("Filter", Database.FILTER_KEY, 100),
    Column("Observed", Database.DATE_OBS_KEY, 180),
]

__all__ += [
    "SESSION_COLUMNS",
    "IMAGE_COLUMNS",
    "REPO_COLUMNS",
    "MASTER_COLUMNS",
    "TARGET_COLUMNS",
]
