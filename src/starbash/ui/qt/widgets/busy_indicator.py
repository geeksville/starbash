"""A small, understated "busy" arc for the GUI.

Reading a FITS frame is slow: the file is hundreds of megabytes and the pixel data
has to be stretched into an 8-bit image before it can be shown.  The GUI must not
freeze while that happens, so the work runs on a worker thread and the spot where
the image will appear shows this widget instead.

:class:`BusyIndicator` is deliberately self-contained: it centres itself over its
parent, animates a rotating arc on a timer that only runs while it is visible, and
never intercepts mouse events.  Anything that has to wait for something - a preview,
a thumbnail, a page load - can drop one in with ``BusyIndicator(some_widget)``.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import QWidget

__all__ = ["BusyIndicator", "BUSY_ACCENT", "BUSY_TRACK", "BUSY_CAPTION"]

#: Colour of the moving arc.
BUSY_ACCENT = "#4aa3df"
#: Colour of the faint ring and panel border it sweeps around.
BUSY_TRACK = "#2c353d"
#: Colour of the caption under the arc.
BUSY_CAPTION = "#8b98a5"
#: Panel fill (RGBA) - dark enough to read the arc over any image, translucent
#: enough to still hint at whatever is underneath.
BUSY_PANEL = (27, 31, 36, 214)

_ARC_DIAMETER = 34.0
_PEN_WIDTH = 3.0
_PADDING = 14.0
_CAPTION_GAP = 10.0
_PANEL_RADIUS = 10.0
#: Degrees of the visible arc, and how far it turns each frame (~60 fps).
_SWEEP = 110.0
_STEP = 5.0
_INTERVAL_MS = 16

#: Default caption; callers can replace or blank it with :meth:`set_caption`.
DEFAULT_CAPTION = "Loading…"


class BusyIndicator(QWidget):
    """An animated arc (plus optional caption) centred over ``parent``.

    Typical use::

        self._busy = BusyIndicator(self._viewport)
        self._busy.start()   # show + animate
        ...
        self._busy.stop()    # hide + stop the timer

    The widget keeps itself centred by watching its parent for resize events, so
    callers never have to lay it out.  It is a pure overlay: it is transparent to
    mouse events and raises itself whenever it starts.
    """

    def __init__(self, parent: QWidget, caption: str = DEFAULT_CAPTION) -> None:
        """Create the indicator as a hidden child of ``parent``.

        Args:
            parent: the widget to centre over (usually the view the content will
                eventually be shown in).
            caption: muted text under the arc; pass an empty string for the arc
                on its own.
        """
        super().__init__(parent)
        self._caption = caption
        self._angle = 0.0
        self._running = False

        # An overlay must never eat clicks meant for the widget underneath it.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

        parent.installEventFilter(self)
        self._recentre()

    # --- public API -------------------------------------------------------
    def start(self) -> None:
        """Show the indicator, centred, and begin animating."""
        if self._running:
            return
        self._running = True
        self._recentre()
        self.show()
        self.raise_()
        self._timer.start()
        self.update()

    def stop(self) -> None:
        """Stop animating and hide the indicator."""
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        self.hide()

    def is_running(self) -> bool:
        """Return ``True`` while the indicator is visible and animating."""
        return self._running

    def set_caption(self, text: str) -> None:
        """Change the caption under the arc (an empty string hides it)."""
        if text == self._caption:
            return
        self._caption = text
        self._recentre()
        self.update()

    # --- geometry ---------------------------------------------------------
    def sizeHint(self) -> QSize:
        """Size that fits the arc and its caption, plus the panel padding."""
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self._caption) if self._caption else 0
        width = max(_ARC_DIAMETER, float(text_width)) + 2 * _PADDING
        height = _ARC_DIAMETER + 2 * _PADDING
        if self._caption:
            height += _CAPTION_GAP + metrics.height()
        return QSize(int(width + 1), int(height + 1))

    def minimumSizeHint(self) -> QSize:
        """Same as :meth:`sizeHint`; the indicator is never squeezed."""
        return self.sizeHint()

    def _recentre(self) -> None:
        """Resize to the hint and centre over the parent widget."""
        parent = self.parentWidget()
        if parent is None:
            return

        wanted = self.sizeHint()
        if self.size() != wanted:
            self.setFixedSize(wanted)
        self.move(
            max(0, (parent.width() - wanted.width()) // 2),
            max(0, (parent.height() - wanted.height()) // 2),
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        """Keep the indicator centred when its parent is resized."""
        if event.type() == QEvent.Type.Resize and watched is self.parentWidget():
            self._recentre()
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        """Re-centre whenever we are shown (the parent may have moved on)."""
        super().showEvent(event)
        self._recentre()

    # --- painting ---------------------------------------------------------
    def _advance(self) -> None:
        """Rotate the arc by one frame."""
        self._angle = (self._angle + _STEP) % 360.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        """Draw the panel, the faint ring, the moving arc and the caption."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(BUSY_TRACK), 1))
        painter.setBrush(QColor(*BUSY_PANEL))
        painter.drawRoundedRect(panel, _PANEL_RADIUS, _PANEL_RADIUS)

        # Inset by half the pen so the stroke is not clipped by the arc box.
        inset = _PEN_WIDTH / 2 + 1
        arc_box = QRectF(
            (self.width() - _ARC_DIAMETER) / 2,
            _PADDING,
            _ARC_DIAMETER,
            _ARC_DIAMETER,
        ).adjusted(inset, inset, -inset, -inset)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(QColor(BUSY_TRACK), _PEN_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawArc(arc_box, 0, 360 * 16)

        painter.setPen(
            QPen(QColor(BUSY_ACCENT), _PEN_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawArc(arc_box, int(-self._angle * 16), int(-_SWEEP * 16))

        if self._caption:
            metrics = self.fontMetrics()
            painter.setPen(QColor(BUSY_CAPTION))
            painter.drawText(
                QRectF(0, _PADDING + _ARC_DIAMETER + _CAPTION_GAP, self.width(), metrics.height()),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                self._caption,
            )
        painter.end()
