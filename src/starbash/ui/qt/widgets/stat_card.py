"""A small headline-number card used on the dashboard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

__all__ = ["StatCard"]


class StatCard(QFrame):
    """A card showing a large value above a small caption.

    Args:
        caption: the small uppercase label describing the value.
        value: initial value text.
        parent: optional parent widget.
    """

    def __init__(self, caption: str, value: str = "–", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)

        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._caption = QLabel(caption)
        self._caption.setObjectName("StatCaption")

        layout.addWidget(self._value)
        layout.addWidget(self._caption)

    def set_value(self, value: object) -> None:
        """Update the displayed number/text."""
        self._value.setText("–" if value is None else str(value))
