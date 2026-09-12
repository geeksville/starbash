"""Shared helpers for clickable, hover-previewable links in item views.

A "link" here is any cell that points at a file or URL - a stage's recipe, a
task's output file, a target's output folder.  Marking a cell with
:data:`LINK_ROLE` underlines it and gives it a pointing-hand cursor, and makes it:

* **clickable** - the OS default application opens it (an external process); if
  no handler is installed it falls back to opening the containing folder;
* **hoverable** - resting the cursor pops up an in-process preview
  (:class:`~starbash.ui.qt.widgets.hover_preview.HoverPreview`).

:class:`LinkDecorator` wires both behaviours onto a view in one call, so the
Processing and Targets pages share exactly the same link handling.  Table models
(see :class:`~starbash.ui.qt.models.DictTableModel`) mark cells via
``Column.link_key``, while tree pages call :func:`set_link`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTreeWidgetItem

from starbash.ui.qt.models import LINK_ROLE
from starbash.ui.qt.widgets.hover_preview import HoverPreview

__all__ = ["LINK_ROLE", "set_link", "open_link", "open_with_status", "LinkDecorator"]

#: Which view signal opens a link.
#:
#: ``clicked`` suits trees/tables where a click is otherwise inert (the Processing
#: run tree).  ``activated`` (double-click or Enter) suits views where a single
#: click already means "select" - e.g. the Targets tree, whose stage rows are
#: checkboxes/selection targets.
OpenOn = Literal["clicked", "activated"]


def set_link(item: QTreeWidgetItem, column: int, url: object) -> None:
    """Mark a tree cell as a link: underlined, clickable and hover-previewable.

    A URL we cannot preview locally (e.g. an ``https://`` recipe) also gets a
    native tooltip, so its destination is discoverable without clicking.
    """
    if not url:
        return
    text = str(url)
    item.setData(column, LINK_ROLE, text)
    font = item.font(column)
    font.setUnderline(True)
    item.setFont(column, font)
    if QUrl(text).scheme() in ("http", "https"):
        item.setToolTip(column, text)


def _folder_for(url: QUrl) -> Path | None:
    """The containing folder of a local file URL (or the folder itself)."""
    if url.isLocalFile():
        path = Path(url.toLocalFile())
    elif url.toString().startswith("file://"):
        path = Path(url.toString()[len("file://") :])
    else:
        return None
    folder = path if path.is_dir() else path.parent
    return folder if folder.exists() else None


def open_link(url: str) -> bool:
    """Open ``url`` with the OS default app, returning whether anything launched.

    When the desktop has no handler for the file's type (the ``No applications
    found for mimetype`` case), its containing folder is opened in the file
    manager instead, so the user can always reach the file.
    """
    parsed = QUrl(url)
    if QDesktopServices.openUrl(parsed):
        return True
    folder = _folder_for(parsed)
    if folder is not None and QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
        return True
    return False


def open_with_status(url: str, on_status: Callable[[str], None] | None = None) -> bool:
    """Open ``url``, reporting the outcome through ``on_status`` (if given)."""
    opened = open_link(url)
    if on_status is not None:
        on_status(f"Opened {url}" if opened else f"Could not open {url}")
    return opened


class LinkDecorator(QObject):
    """Give a view clickable + hover-previewable links in one step.

    Works for any :class:`~PySide6.QtWidgets.QAbstractItemView`: the generic
    ``clicked(QModelIndex)`` signal and ``indexAt`` are used, so trees and tables
    behave identically.  Cells must expose their URL under :data:`LINK_ROLE`.
    """

    def __init__(
        self,
        view: object,
        *,
        parent: QObject | None = None,
        on_status: Callable[[str], None] | None = None,
        open_on: OpenOn = "clicked",
    ) -> None:
        """Decorate ``view``; ``on_status`` receives a short result message.

        ``open_on`` selects the signal that opens a link: ``"clicked"`` (default)
        or ``"activated"`` for views whose single click is already taken (e.g. by
        selection or a checkbox).  Hover previews are unaffected either way.
        """
        super().__init__(parent or view)  # type: ignore[arg-type]
        self._on_status = on_status
        #: The hover engine (exposed so a page can close a preview before a rebuild).
        self.preview = HoverPreview(view, url_role=LINK_ROLE, parent=self)
        getattr(view, open_on).connect(self._on_open)

    def _on_open(self, index: object) -> None:
        """Open the cell's link with the OS default application."""
        url = index.data(LINK_ROLE)  # type: ignore[attr-defined]
        if not url:
            return
        open_with_status(str(url), self._on_status)

    def dismiss(self) -> None:
        """Close any open preview (delegated to the hover engine)."""
        self.preview.dismiss()
