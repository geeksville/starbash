"""Build the shareable report site for processed targets.

Uploading to GitHub Pages still uses the authenticated device flow, so this page
generates the site locally and points you at ``sb publish github --login``.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from starbash.paths import get_publish_site_dir
from starbash.ui.qt.jobs import publish_job
from starbash.ui.qt.pages.base import Page

__all__ = ["PublishPage"]

UPLOAD_HINT = (
    "Uploading to GitHub Pages needs the interactive sign-in flow: run "
    "“sb publish github --login” in a terminal."
)


class PublishPage(Page):
    """Generate the local Jekyll report site and open it."""

    nav_title = "Publish"
    subtitle = "Build a shareable report site for your processed targets."

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._username = QLineEdit()
        self._username.setPlaceholderText("GitHub username (optional, used for links)")
        row = QHBoxLayout()
        row.addWidget(QLabel("GitHub user:"))
        row.addWidget(self._username, 1)
        layout.addLayout(row)

        self._generate = QPushButton("Generate report site")
        self._generate.setObjectName("Primary")
        self._generate.clicked.connect(self._on_generate)

        self._open_dir = QPushButton("Open site folder")
        self._open_dir.clicked.connect(self._on_open_folder)

        self._open_site = QPushButton("Open in browser")
        self._open_site.clicked.connect(self._on_open_site)

        bar = QHBoxLayout()
        bar.addWidget(self._generate)
        bar.addWidget(self._open_dir)
        bar.addWidget(self._open_site)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._status = QLabel(f"Site directory: {get_publish_site_dir()}")
        self._status.setObjectName("PageSubtitle")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        hint = QLabel(UPLOAD_HINT)
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

    def _on_generate(self) -> None:
        username = self._username.text().strip() or None
        self._generate.setEnabled(False)
        self.start_job(
            lambda report, token: publish_job(report, token, username),
            on_progress=lambda payload: self._status.setText(str(payload)),
            on_finished=self._on_generated,
        )

    def _on_generated(self, result: object) -> None:
        self._generate.setEnabled(True)
        if isinstance(result, dict):
            self._status.setText(str(result.get("message", "Done.")))
            self.status.emit(str(result.get("message", "Report site generated.")))

    def _on_open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_publish_site_dir())))

    def _on_open_site(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(get_publish_site_dir() / "index.html"))
        )
