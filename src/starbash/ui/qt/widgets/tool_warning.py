"""Warning bars for tools Starbash needs but cannot find.

The core reports tool availability as :class:`~starbash.tool.base.ToolStatus`
values (see :func:`starbash.tool.missing_tool_statuses`), which carry both how
important the tool is (:class:`~starbash.tool.base.ToolSeverity`) and where the
user can get it.  This module renders those as dismissible bars at the top of the
main window: each bar offers a button that opens the tool's install page and, for
anything that is *not* required, an *Ignore* button that silences the warning for
good (the window persists that; see ``MainWindow._on_ignore_tool``).

A *required* tool (Siril) deliberately has no *Ignore* button - most workflows
cannot run without it, so the bar stays until it is installed.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from starbash.tool import ToolStatus, missing_tool_statuses, plain_message
from starbash.ui.qt.widgets.file_links import open_with_status

__all__ = ["ToolWarningBar", "ToolWarningPanel"]


class ToolWarningBar(QFrame):
    """One missing tool, drawn as a bar.

    The severity picks the colour (via the ``severity`` dynamic property, which the
    theme's stylesheet selects on) and whether the *Ignore* button is offered.

    Signals:
        ignored: the user clicked *Ignore*; carries the tool key.  Persisting the
            choice is the window's job - this widget only reports it.
        status: a short result message for the status bar (e.g. an open failure).
    """

    ignored = Signal(str)
    status = Signal(str)

    def __init__(self, tool_status: ToolStatus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool_status = tool_status
        #: The action buttons offered, or ``None`` when the bar does not offer one
        #: (a *required* tool has no *Ignore*, a built-in tool no install page).
        self._install_button: QPushButton | None = None
        self._ignore_button: QPushButton | None = None
        self.setObjectName("ToolWarningBar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # A dynamic property, not a fixed id: Qt selectors cannot reach a parent's
        # property, so both the frame and the badge carry it.
        self.setProperty("severity", tool_status.severity.label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)

        badge = QLabel(tool_status.severity.label.upper())
        badge.setObjectName("ToolWarningBadge")
        badge.setProperty("severity", tool_status.severity.label)
        layout.addWidget(badge)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)

        title = QLabel(f"{tool_status.name} was not found")
        title.setObjectName("ToolWarningTitle")
        text.addWidget(title)

        summary = tool_status.summary
        if summary:
            detail = QLabel(summary)
            detail.setObjectName("ToolWarningDetail")
            detail.setWordWrap(True)
            if tool_status.detail:
                # The full (console-worded) explanation stays reachable on hover.
                detail.setToolTip(plain_message(tool_status.detail))
            text.addWidget(detail)

        layout.addLayout(text, 1)

        if tool_status.install_url:
            install = QPushButton("How to install")
            install.setObjectName("Primary")
            install.setToolTip(tool_status.install_url)
            install.clicked.connect(self._on_install)
            layout.addWidget(install)
            self._install_button = install

        if tool_status.can_be_ignored:
            ignore = QPushButton("Ignore")
            ignore.setToolTip(f"Stop warning about {tool_status.name}")
            ignore.clicked.connect(self._on_ignore)
            layout.addWidget(ignore)
            self._ignore_button = ignore

    def _on_install(self) -> None:
        """Open the tool's install page in the user's browser."""
        url = self.tool_status.install_url
        if url:
            open_with_status(url, self.status.emit)

    def _on_ignore(self) -> None:
        """Report the user's choice; the window persists it and drops this bar."""
        self.ignored.emit(self.tool_status.key)


class ToolWarningPanel(QWidget):
    """A stack of :class:`ToolWarningBar`s, one per missing tool.

    It is hidden when nothing is missing, so a healthy install pays no vertical
    space, and it re-reads the tool registry on :meth:`refresh`, so a bar goes away
    once its tool is installed or ignored.

    Args:
        on_ignore: called with a tool key when the user clicks *Ignore*; the window
            persists the choice (see ``MainWindow._on_ignore_tool``).
        parent: parent widget (pass one: a parentless panel is a top-level window
            while it has bars to show).
    """

    status = Signal(str)

    def __init__(
        self,
        on_ignore: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_ignore = on_ignore
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 0)
        self._layout.setSpacing(8)
        self._bars: list[ToolWarningBar] = []
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the bars from the current tool availability."""
        for bar in self._bars:
            self._layout.removeWidget(bar)
            bar.deleteLater()
        self._bars.clear()

        for tool_status in missing_tool_statuses():
            bar = ToolWarningBar(tool_status, self)
            bar.ignored.connect(self._on_bar_ignored)
            bar.status.connect(self.status.emit)
            self._layout.addWidget(bar)
            self._bars.append(bar)

        self.setVisible(bool(self._bars))

    def bars(self) -> list[ToolWarningBar]:
        """The bars currently shown, most important tool first."""
        return list(self._bars)

    def _on_bar_ignored(self, key: str) -> None:
        """Let the window persist the choice, then drop that bar."""
        if self._on_ignore is not None:
            self._on_ignore(key)
        self.refresh()
