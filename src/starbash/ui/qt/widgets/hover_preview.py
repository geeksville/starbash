"""Hover-preview popups for file links.

Hovering a link in an item view that carries a URL shows a small, frameless
preview window (text, FITS or an ordinary raster image) once the cursor comes to
rest there.  The popup is deliberately *transient*: it never takes focus, it is
placed **beside** the hovered cell so it cannot cover what the user is pointing
at, and it disappears the moment the cursor moves on.

Only *local* files are previewed.  A URL with no readable local path (for example
an ``https://`` recipe) is ignored here while staying clickable in the view.

The engine is reusable: it knows nothing about the file-name cells it decorates -
it just reads a URL out of an item-data *role*.  The view decides which cells are
links and marks them with that role; :class:`HoverPreview` does the rest.

    from starbash.ui.qt.widgets.hover_preview import HoverPreview

    preview = HoverPreview(tree, url_role=URL_ROLE, parent=page)
    ...
    preview.dismiss()   # e.g. right before the tree is rebuilt
"""

from __future__ import annotations

import logging
import weakref
from enum import StrEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from starbash.ui.qt.widgets.busy_indicator import BusyIndicator
from starbash.ui.qt.widgets.image_viewer import load_image_file
from starbash.ui.qt.workers import run_async

logger = logging.getLogger(__name__)

__all__ = ["PreviewKind", "local_path", "preview_kind", "HoverPreview"]

#: Every live popup, so showing one can close any other (at most one preview).
_open_popups: weakref.WeakSet[_PreviewPopup] = weakref.WeakSet()


def _safe_hide(popup: _PreviewPopup) -> None:
    """Hide a popup, tolerating one whose underlying Qt object is already gone."""
    try:
        popup.hide()
    except RuntimeError:  # pragma: no cover - the C++ object was destroyed first
        pass

#: Suffixes we decode as an image (FITS via astropy, the rest via Qt).
FITS_SUFFIXES = {".fit", ".fits", ".fts"}
RASTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
#: Suffixes we show as plain text.
TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".md",
    ".ini",
    ".cfg",
    ".conf",
    ".seq",
    ".ssf",
    ".py",
    ".sh",
    ".dat",
    ".xml",
    ".html",
    ".htm",
    ".rst",
    ".sb",
}

#: Upper bounds so a huge file can never stall the preview worker.
MAX_TEXT_BYTES = 256 * 1024
MAX_TEXT_LINES = 400

#: Popup size as a fraction of the owning window, with sane pixel clamps.
SIZE_FRACTION = 0.25
MIN_WIDTH, MAX_WIDTH = 280, 620
MIN_HEIGHT, MAX_HEIGHT = 180, 480

#: Gap between the hovered cell and the popup, so the popup never covers it.
GAP = 18

#: Space the card's own chrome adds around the content (margins + title row).
_CHROME_W = 12 * 2 + 10 * 2
_CHROME_H = 12 * 2 + 8 + 10 + 22 + 6

_POPUP_QSS = """
QFrame#PreviewCard {
    background-color: #1b2127;
    border: 1px solid #3a444d;
    border-radius: 10px;
}
QLabel#PreviewTitle {
    color: #cfd8e0;
    font-weight: 600;
}
QPushButton#PreviewClose {
    background: transparent;
    border: none;
    color: #8b98a5;
    font-size: 15px;
    font-weight: 600;
    padding: 0px;
}
QPushButton#PreviewClose:hover {
    color: #e6edf3;
    background-color: #2c353d;
    border-radius: 4px;
}
QLabel#PreviewMessage {
    color: #8b98a5;
}
QPlainTextEdit#PreviewText {
    background-color: #0f1317;
    border: 1px solid #2c353d;
    border-radius: 6px;
    color: #d7dde3;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 11px;
}
"""


class PreviewKind(StrEnum):
    """What (if anything) we can render for a URL in-process."""

    NONE = "none"
    TEXT = "text"
    IMAGE = "image"


def local_path(url: str | None) -> Path | None:
    """Return the existing local file behind ``url``, or ``None``.

    ``http(s)`` (and any other non-file scheme) has no local path, and a path that
    does not point at a real file is treated the same way.
    """
    if not url:
        return None
    parsed = QUrl(url)
    if parsed.isLocalFile():
        candidate = Path(parsed.toLocalFile())
    elif url.startswith("file://"):
        candidate = Path(url[len("file://") :])
    else:
        return None
    return candidate if candidate.is_file() else None


def preview_kind(url: str | None) -> PreviewKind:
    """Classify how (if at all) ``url`` can be previewed in-process."""
    path = local_path(url)
    if path is None:
        return PreviewKind.NONE
    suffix = path.suffix.lower()
    if suffix in FITS_SUFFIXES or suffix in RASTER_SUFFIXES:
        return PreviewKind.IMAGE
    if suffix in TEXT_SUFFIXES:
        return PreviewKind.TEXT
    return PreviewKind.NONE


class _PreviewPopup(QFrame):
    """A frameless, shadowed window that renders one file preview.

    It is a top-level ``Qt.Tool`` window: interactive (so its scrollbars and its
    close adornment work) yet non-activating, so hovering a link never steals
    focus.  It stays open until the user closes it or another preview replaces it
    (there is at most one).  Content is loaded on a worker thread (a FITS frame is
    far too slow to read on the GUI thread), guarded by a request counter so a
    stale load is dropped.
    """

    #: Emitted when the user closes the popup (its close adornment or Escape).
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(_POPUP_QSS)
        _open_popups.add(self)

        self._request = 0
        self._target = QSize(MIN_WIDTH, MIN_HEIGHT)
        self._content: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)  # breathing room for the shadow

        self._card = QFrame()
        self._card.setObjectName("PreviewCard")
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(10, 8, 10, 10)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self._title = QLabel()
        self._title.setObjectName("PreviewTitle")
        header.addWidget(self._title, 1)

        self._close = QPushButton("\u2715")  # ✕ - a conventional close adornment
        self._close.setObjectName("PreviewClose")
        self._close.setFixedSize(18, 18)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setToolTip("Close preview")
        self._close.clicked.connect(self._request_close)
        header.addWidget(self._close, 0)
        card_layout.addLayout(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self._body, 1)

        #: Busy arc shown over the body while the file is read.
        self._busy = BusyIndicator(self._body, caption="")

    # --- public API -------------------------------------------------------
    def preview(self, url: str, anchor: QRect, parent: QWidget) -> bool:
        """Show a preview of ``url`` beside ``anchor``; return whether it opened."""
        kind = preview_kind(url)
        path = local_path(url)
        if kind is PreviewKind.NONE or path is None:
            self.hide()
            return False

        # At most one preview window: close any other before opening this one.
        for other in list(_open_popups):
            if other is not self:
                _safe_hide(other)

        self._request += 1
        request = self._request
        self._target = self._target_size(parent)

        self._title.setText(path.name)
        self._clear_body()
        self.resize(self._target)
        self._place(anchor)
        self._busy.start()
        self.show()
        self.raise_()

        if kind is PreviewKind.TEXT:
            self._load_text(path, request)
        else:
            self._load_image(path, request)
        return True

    def hide(self) -> None:  # noqa: D401 - Qt API
        """Hide the popup and abandon any load still in flight."""
        self._request += 1
        self._busy.stop()
        super().hide()

    def close_for_user(self) -> None:
        """Close the popup exactly as its close adornment does."""
        self._request_close()

    def _request_close(self) -> None:
        """User-initiated close: hide and tell the engine it was dismissed."""
        self.hide()
        self.closed.emit()

    # --- events -----------------------------------------------------------
    def keyPressEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Escape closes the preview."""
        if getattr(event, "key", None) == Qt.Key.Key_Escape:
            self._request_close()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """A window-manager close counts as a user close."""
        self.closed.emit()
        super().closeEvent(event)  # type: ignore[arg-type]

    # --- loading ----------------------------------------------------------
    def _load_text(self, path: Path, request: int) -> None:
        """Read (a bounded slice of) a text file on a worker thread."""

        def job(_report: Any, _token: Any) -> tuple[bool, Any]:
            try:
                data = path.read_bytes()[:MAX_TEXT_BYTES]
                return True, data.decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 - an unreadable file is expected
                return False, str(exc) or exc.__class__.__name__

        run_async(job, on_finished=lambda result: self._on_text(result, request))

    def _on_text(self, result: Any, request: int) -> None:
        """Populate the body with ``text`` (GUI thread)."""
        if request != self._request:
            return
        self._busy.stop()
        ok, text = result
        if not ok:
            self._show_error(str(text))
            return

        lines = str(text).splitlines()
        if len(lines) > MAX_TEXT_LINES:
            lines = lines[:MAX_TEXT_LINES] + ["…"]

        view = QPlainTextEdit()
        view.setObjectName("PreviewText")
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setPlainText("\n".join(lines))
        self.resize(self._target)
        self._set_body(view)

    def _load_image(self, path: Path, request: int) -> None:
        """Decode a FITS/raster image on a worker thread (returns a QImage)."""

        def job(_report: Any, _token: Any) -> tuple[bool, Any]:
            try:
                return True, load_image_file(path)
            except Exception as exc:  # noqa: BLE001 - an unreadable file is expected
                return False, str(exc) or exc.__class__.__name__

        run_async(job, on_finished=lambda result: self._on_image(result, request))

    def _show_error(self, message: str) -> None:
        """Show a readable failure inside the popup (never raise)."""
        label = QLabel(f"Preview failed:\n{message}")
        label.setObjectName("PreviewMessage")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.resize(self._target)
        self._set_body(label)

    def _on_image(self, result: Any, request: int) -> None:
        """Scale the decoded image to fit and hug it with the popup."""
        if request != self._request:
            return
        self._busy.stop()
        ok, image = result
        if not ok or image is None:
            self._show_error(str(image))
            return

        max_body = QSize(
            max(1, self._target.width() - _CHROME_W),
            max(1, self._target.height() - _CHROME_H),
        )
        pixmap = QPixmap.fromImage(image).scaled(
            max_body,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pixmap)
        self._set_body(label)

        # Hug the image, but never grow past the 25%-of-window budget.
        self.adjustSize()
        self.resize(
            min(self.width(), self._target.width()),
            min(self.height(), self._target.height()),
        )

    # --- layout -----------------------------------------------------------
    def _set_body(self, widget: QWidget) -> None:
        """Replace the body's content widget."""
        self._clear_body()
        self._content = widget
        self._body_layout.addWidget(widget)

    def _clear_body(self) -> None:
        """Delete the current content widget, if any."""
        if self._content is not None:
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None

    @staticmethod
    def _target_size(parent: QWidget) -> QSize:
        """About 25% of the owning window, clamped to a sensible pixel range."""
        window = parent.window() or parent
        size = window.size()
        width = max(MIN_WIDTH, min(int(size.width() * SIZE_FRACTION), MAX_WIDTH))
        height = max(MIN_HEIGHT, min(int(size.height() * SIZE_FRACTION), MAX_HEIGHT))
        return QSize(width, height)

    def _place(self, anchor: QRect) -> None:
        """Move beside ``anchor`` (never over it), staying on-screen."""
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else anchor
        size = self.size()

        x = anchor.right() + GAP
        if x + size.width() > available.right():
            x = anchor.left() - GAP - size.width()  # flip to the left
        x = max(available.left() + 4, min(x, available.right() - size.width() - 4))

        y = anchor.top()
        if y + size.height() > available.bottom():
            y = available.bottom() - size.height() - 4
        y = max(available.top() + 4, y)

        self.move(QPoint(x, y))


class HoverPreview(QObject):
    """Show a preview popup when the cursor rests on a link in ``view``.

    The view marks link cells by storing the target URL under ``url_role``.
    Resting on such a cell for ``delay_ms`` shows the preview, which then **stays
    open** until the user closes it or hovers a *different* link (there is only
    ever one preview).  Moving the cursor away - or onto the preview's own
    scrollbars - leaves it alone; clicking or scrolling the view, or the view
    going away, closes it.
    """

    def __init__(
        self,
        view: Any,
        *,
        url_role: int,
        delay_ms: int = 550,
        parent: QObject | None = None,
    ) -> None:
        """Watch ``view`` for hovering over cells that carry ``url_role``."""
        super().__init__(parent or view)
        self._view = view
        self._url_role = url_role
        #: Link under the cursor, awaiting the delay (and the index it is on).
        self._pending_url: str | None = None
        self._pending_index: Any = None
        #: Link currently shown in the popup, if any.
        self._shown_url: str | None = None
        #: A link the user closed, which must not reopen until they leave it.
        self._suppressed_url: str | None = None

        window = view.window()
        self._popup = _PreviewPopup(window)
        self._popup.closed.connect(self._on_user_closed)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show_preview)

        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    def dismiss(self) -> None:
        """Close any preview and forget all hover state (idempotent).

        Used programmatically - e.g. right before the view's items are rebuilt -
        rather than for cursor movement, which deliberately leaves the popup open.
        """
        self._timer.stop()
        self._pending_url = None
        self._pending_index = None
        self._shown_url = None
        self._suppressed_url = None
        _safe_hide(self._popup)

    # --- events -----------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        """Track hover movement; close on a click/scroll or when the view goes away.

        Deliberately *not* on leaving the viewport or on focus changes: the popup is
        interactive, so the user may move onto its scrollbars (which focuses it)
        without losing it.
        """
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self._on_mouse_move(event.position().toPoint())  # type: ignore[attr-defined]
        elif kind in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
            QEvent.Type.Scroll,
            QEvent.Type.KeyPress,
            QEvent.Type.Hide,
            QEvent.Type.HideToParent,
        ):
            self.dismiss()
        return False

    def _on_mouse_move(self, pos: QPoint) -> None:
        """Start (or restart) the delay once the cursor rests on a new link."""
        index = self._view.indexAt(pos)
        url = self._url_at(index)
        self._set_link_cursor(bool(url))

        if url is None:
            # Moved off any link: cancel a pending preview but keep an open one -
            # the user may be on their way to its scrollbars.
            self._suppressed_url = None
            self._pending_url = None
            self._pending_index = None
            self._timer.stop()
            return

        if url == self._shown_url and self._popup.isVisible():
            return  # already previewing this link; leave it alone

        if url == self._suppressed_url:
            return  # the user closed this one; don't reopen until they leave it

        if url == self._pending_url:
            return  # already waiting on this link

        self._timer.stop()
        self._pending_url = url
        self._pending_index = index
        self._timer.start()

    def _url_at(self, index: Any) -> str | None:
        """The link URL stored on ``index``, if any."""
        if index is None or not index.isValid():
            return None
        value = index.data(self._url_role)
        return str(value) if value else None

    def _set_link_cursor(self, on_link: bool) -> None:
        """Show the pointing-hand cursor while over a link."""
        shape = Qt.CursorShape.PointingHandCursor if on_link else Qt.CursorShape.ArrowCursor
        viewport = self._view.viewport()
        if viewport.cursor().shape() != shape:
            viewport.setCursor(shape)

    def _on_user_closed(self) -> None:
        """The user closed the popup: don't reopen while still on that link."""
        self._timer.stop()
        self._suppressed_url = self._shown_url
        self._shown_url = None
        self._pending_url = None
        self._pending_index = None

    def _show_preview(self) -> None:
        """Pop the preview beside the hovered cell (delayed)."""
        if self._pending_url is None or self._pending_index is None:
            return
        url = self._pending_url
        index = self._pending_index
        self._pending_url = None
        self._pending_index = None

        rect = self._view.visualRect(index)
        if not rect.isValid() or rect.isEmpty():
            return
        anchor = QRect(self._view.viewport().mapToGlobal(rect.topLeft()), rect.size())
        if self._popup.preview(url, anchor, self._view):
            self._suppressed_url = None
            self._shown_url = url
        else:
            self._shown_url = None

