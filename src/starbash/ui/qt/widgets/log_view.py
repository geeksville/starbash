"""A streaming, colourised log pane.

Fed either directly (``append_line``) or, more usually, by the processing page
which connects it to the :class:`~starbash.ui.qt.bridge.EventBusBridge`.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QWidget

__all__ = ["LogView"]

#: Colour per log level, matching the dark theme.
LEVEL_COLORS = {
    "debug": "#6a7681",
    "info": "#d7dde3",
    "tool": "#e8c07d",
    "warning": "#e0b341",
    "error": "#e06c6c",
    "success": "#7fd18a",
}


class LogView(QPlainTextEdit):
    """A read-only, auto-scrolling log pane with a bounded history.

    Args:
        max_blocks: how many lines to retain (older lines are dropped).
        parent: optional parent widget.
    """

    def __init__(self, max_blocks: int = 5000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_blocks)
        self.setFont(QFont("JetBrains Mono", 9))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def append_line(self, text: str, level: str = "info") -> None:
        """Append a single line, colourised by ``level``.

        Text is HTML-escaped so tool output containing ``<`` can't inject markup.
        """
        color = LEVEL_COLORS.get(level, LEVEL_COLORS["info"])
        safe = html.escape(text.rstrip("\n"))
        self.appendHtml(f'<span style="color:{color}">{safe}</span>')

    def clear_log(self) -> None:
        """Empty the pane."""
        self.clear()
