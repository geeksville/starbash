"""A native first-run / re-run setup dialog.

This is the GUI equivalent of ``sb user setup``.  It writes the same user config
keys, so the two front ends stay interchangeable.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from starbash.app import Starbash
from starbash.paths import get_user_documents_dir

__all__ = ["SetupWizard", "run_setup_dialog"]


class SetupWizard(QDialog):
    """Collect the basic user preferences and optionally create output folders."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sb = sb
        self.setWindowTitle("Starbash setup")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tell Starbash how to credit your images. Every field is optional — "
            "you can change these later in Settings."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        repo = sb.user_repo
        self._name = QLineEdit(str(repo.get("user.name", "") or ""))
        self._email = QLineEdit(str(repo.get("user.email", "") or ""))
        self._analytics = QCheckBox("Send anonymous crash reports and usage data")
        self._analytics.setChecked(bool(repo.get("analytics.enabled", False)))
        self._include_email = QCheckBox("Include my email with crash reports")
        self._include_email.setChecked(bool(repo.get("analytics.include_user", False)))

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Email", self._email)
        form.addRow("Analytics", self._analytics)
        form.addRow("", self._include_email)
        layout.addLayout(form)

        self._create_dirs = QCheckBox(
            f"Create default output folders under {get_user_documents_dir() / 'repos'}"
        )
        self._create_dirs.setChecked(self._missing_output_repos())
        self._create_dirs.setVisible(self._missing_output_repos())
        layout.addWidget(self._create_dirs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _missing_output_repos(self) -> bool:
        """True when a master or processed output repo has not been created yet."""
        manager = self.sb.repo_manager
        return (
            manager.get_repo_by_kind("master") is None
            or manager.get_repo_by_kind("processed") is None
        )

    def apply(self) -> None:
        """Persist the collected preferences (and create folders if requested)."""
        repo = self.sb.user_repo
        repo.set("user.name", self._name.text().strip())
        repo.set("user.email", self._email.text().strip())
        repo.set("analytics.enabled", self._analytics.isChecked())
        repo.set("analytics.include_user", self._include_email.isChecked())
        repo.write_config()

        if self._create_dirs.isVisible() and self._create_dirs.isChecked():
            manager = self.sb.repo_manager
            base = get_user_documents_dir() / "repos"
            if manager.get_repo_by_kind("master") is None:
                self.sb.add_local_repo(str(base / "master"), repo_type="master")
            if manager.get_repo_by_kind("processed") is None:
                self.sb.add_local_repo(str(base / "processed"), repo_type="processed")


def run_setup_dialog(sb: Starbash, parent: QWidget | None = None) -> bool:
    """Show the setup dialog; return ``True`` if the user saved."""
    dialog = SetupWizard(sb, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    dialog.apply()
    return True
