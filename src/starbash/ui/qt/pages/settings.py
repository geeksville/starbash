"""User preferences and application paths."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from starbash.paths import get_user_config_path, get_user_data_dir, get_user_documents_dir
from starbash.ui.qt.pages.base import Page

__all__ = ["SettingsPage"]


class SettingsPage(Page):
    """Edit the same user settings as ``sb user ...``."""

    nav_title = "Settings"
    subtitle = "Your name, email, analytics preference and where Starbash keeps data."

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._name = QLineEdit()
        self._name.setPlaceholderText("Used for attribution in generated images")
        self._email = QLineEdit()
        self._email.setPlaceholderText("Optional, for attribution and support")
        self._analytics = QCheckBox("Send anonymous crash reports and usage data")
        self._include_email = QCheckBox("Include my email with crash reports")

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Email", self._email)
        form.addRow("Analytics", self._analytics)
        form.addRow("", self._include_email)
        layout.addLayout(form)

        self._save = QPushButton("Save settings")
        self._save.setObjectName("Primary")
        self._save.clicked.connect(self._on_save)

        bar = QHBoxLayout()
        bar.addWidget(self._save)
        bar.addStretch(1)
        layout.addLayout(bar)

        locations = QLabel(
            f"Config: {get_user_config_path()}\n"
            f"Data: {get_user_data_dir()}\n"
            f"Documents: {get_user_documents_dir()}"
        )
        locations.setObjectName("PageSubtitle")
        locations.setWordWrap(True)
        layout.addWidget(locations)
        layout.addStretch(1)

    def refresh(self) -> None:
        """Load the current user preferences."""
        repo = self.sb.user_repo
        self._name.setText(str(repo.get("user.name", "") or ""))
        self._email.setText(str(repo.get("user.email", "") or ""))
        self._analytics.setChecked(bool(repo.get("analytics.enabled", False)))
        self._include_email.setChecked(bool(repo.get("analytics.include_user", False)))

    def _on_save(self) -> None:
        repo = self.sb.user_repo
        repo.set("user.name", self._name.text().strip())
        repo.set("user.email", self._email.text().strip())
        repo.set("analytics.enabled", self._analytics.isChecked())
        repo.set("analytics.include_user", self._include_email.isChecked())
        try:
            repo.write_config()
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.show_error(f"Could not save settings: {exc}")
            return
        self.status.emit("Settings saved.")
