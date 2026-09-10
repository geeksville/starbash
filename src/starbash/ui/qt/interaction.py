"""A Qt implementation of the core :class:`UserInteraction` protocol.

When a guided command (e.g. first-run setup) runs *inside* the GUI, prompts must
appear as native dialogs rather than reading stdin.  Installing
:class:`QtUserInteraction` via :func:`starbash.interaction.set_interaction` makes
that happen without the command knowing anything about Qt.

Call these methods from the GUI thread.  :meth:`notify` is safe to call from a
worker thread: it marshals the message onto the GUI thread via a queued signal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox, QWidget

from starbash.interaction import UserInteraction

__all__ = ["QtUserInteraction"]


class _Notifier(QObject):
    """Carries ``notify`` messages from any thread onto the GUI thread."""

    message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.message.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def _show(self, text: str) -> None:
        QMessageBox.information(self.parent(), "Starbash", text)  # type: ignore[arg-type]


class QtUserInteraction(UserInteraction):
    """Ask the user questions with native Qt dialogs.

    Args:
        parent: widget to use as the dialog parent (keeps dialogs centered).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        self._parent = parent
        self._notifier = _Notifier(parent)

    def confirm(self, prompt: str, default: bool = True) -> bool:
        """Show a yes/no dialog, returning the user's choice."""
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        default_button = (
            QMessageBox.StandardButton.Yes if default else QMessageBox.StandardButton.No
        )
        answer = QMessageBox.question(
            self._parent,
            "Starbash",
            prompt,
            buttons,
            default_button,
        )
        return answer == QMessageBox.StandardButton.Yes

    def text(self, prompt: str, default: str = "", show_default: bool = True) -> str:
        """Show a single-line input dialog."""
        value, ok = QInputDialog.getText(
            self._parent,
            "Starbash",
            prompt,
            QLineEdit.EchoMode.Normal,
            default,
        )
        return value if ok else default

    def notify(self, message: str) -> None:
        """Show an information dialog (safe to call from any thread)."""
        if QApplication.instance() is None:  # pragma: no cover - headless safety net
            return
        self._notifier.message.emit(message)

    def open_url(self, url: str) -> bool:
        """Open ``url`` with the system default handler via Qt."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return bool(QDesktopServices.openUrl(QUrl(url)))
