"""Publish the shareable report site for processed targets to GitHub Pages.

Publishing builds the site and uploads it to the user's GitHub account, which needs a
one-time sign-in plus an app installation, so the page hands that to
:class:`~starbash.ui.qt.widgets.github_login.GitHubSetupDialog`.

The account name is **read-only**: it comes from GitHub (and is recorded with the
stored credential) rather than from anything the user types.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from starbash.paths import get_publish_site_dir
from starbash.ui.qt.jobs import github_identity_job, publish_github_job
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.widgets.busy_indicator import Spinner
from starbash.ui.qt.widgets.github_login import run_github_setup

__all__ = ["PublishPage"]

PUBLISH_HINT = (
    "Publishing builds the site and uploads it to GitHub Pages for your GitHub "
    "account; it is usually live a few minutes later. The first publish walks you "
    "through signing in and installing the Starbash GitHub app."
)


class PublishPage(Page):
    """Build the report site for the signed-in account and upload it to GitHub Pages."""

    nav_title = "Publish"
    subtitle = "Build a shareable report site for your processed targets."

    def _build(self) -> None:
        #: URL of the last successful publish, so "Open in browser" stays useful
        #: even if a later publish fails.
        self._pages_url = ""

        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        # The account is *reported* by GitHub, never typed: the field is read-only and
        # is filled from the identity job (and from a successful publish).
        self._username = QLineEdit()
        self._username.setReadOnly(True)
        self._username.setPlaceholderText("Not signed in to GitHub")
        row = QHBoxLayout()
        row.addWidget(QLabel("GitHub user:"))
        row.addWidget(self._username, 1)
        layout.addLayout(row)

        self._publish = QPushButton("Publish to GitHub")
        self._publish.setObjectName("Primary")
        self._publish.clicked.connect(self._on_publish)

        self._open_site = QPushButton("Open in browser")
        # Nothing to open until a publish has produced a Pages site.
        self._open_site.setEnabled(False)
        self._open_site.clicked.connect(self._on_open_site)

        # An arc in the button row, so a publish that is waiting on GitHub looks
        # alive without covering the buttons (it keeps its slot when idle).
        self._spinner = Spinner()

        bar = QHBoxLayout()
        bar.addWidget(self._publish)
        bar.addWidget(self._spinner)
        bar.addWidget(self._open_site)
        bar.addStretch(1)
        layout.addLayout(bar)

        # An upload reports one step per file, so a bar is genuinely useful here -
        # but it only appears while a publish is in flight.
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel(f"Site directory: {get_publish_site_dir()}")
        self._status.setObjectName("PageSubtitle")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        hint = QLabel(PUBLISH_HINT)
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

    # --- signed-in account ------------------------------------------------
    def refresh(self) -> None:
        """Show the account Starbash is signed in to GitHub as.

        The credential store is read on a worker thread (never on this one, where a
        locked keyring could block), and the account name is the one recorded with
        the credential, so this usually makes no network calls.
        """
        self.start_job(github_identity_job, on_finished=self._on_identity)

    def _on_identity(self, result: object) -> None:
        """Render the signed-in account, or the reason there is not one."""
        payload = result if isinstance(result, dict) else {}
        signed_in = bool(payload.get("signed_in"))
        self._username.setText(str(payload.get("login", "")))
        # An empty login while signed in means a credential saved before Starbash
        # recorded account names; the next publish fills the real one in.
        self._username.setPlaceholderText(
            "Signed in to GitHub" if signed_in else "Not signed in to GitHub"
        )

    # --- publishing -------------------------------------------------------
    def _on_publish(self) -> None:
        """Generate the site and upload it, guiding the user through GitHub setup.

        The job *returns* ``needs_sign_in``/``needs_install`` rather than raising,
        because both are normal steps for a new user: each one opens the setup
        dialog and, once it succeeds, the job simply runs again.

        The site belongs to the account GitHub reports for the stored credential, so
        there is nothing for the page to pass in.
        """
        self._publish.setEnabled(False)
        self._open_site.setEnabled(False)
        self._spinner.start()
        self._progress.setRange(0, 0)  # indeterminate until the first step arrives
        self._progress.setVisible(True)
        self._status.setText("Generating the report site...")
        self.start_job(
            publish_github_job,
            on_progress=self._on_publish_progress,
            on_finished=self._on_published,
            on_failed=self._on_publish_failed,
        )

    def _on_publish_progress(self, payload: object) -> None:
        """Render either a ``(description, completed, total)`` step or plain text."""
        if isinstance(payload, tuple) and len(payload) == 3:
            description, completed, total = payload
            self._progress.setRange(0, int(total))
            self._progress.setValue(int(completed))
            self._status.setText(str(description))
        else:
            self._status.setText(str(payload))

    def _on_published(self, result: object) -> None:
        """Finish, or open the setup dialog when GitHub is not ready yet."""
        payload = result if isinstance(result, dict) else {}
        if payload.get("needs_sign_in") or payload.get("needs_install"):
            self._status.setText(str(payload.get("message", "GitHub needs one more step.")))
            self._idle_controls()
            installed = run_github_setup(self, start_at_install=bool(payload.get("needs_install")))
            if installed:
                self._on_publish()
            else:
                self._finish_publish("Publishing cancelled.")
            return

        owner = str(payload.get("owner", ""))
        if owner:
            # GitHub is authoritative about the account, so show what it just told us
            # (this also fills in a credential that predates the recorded name).
            self._username.setText(owner)
        self._pages_url = str(payload.get("pages_url", ""))
        self._finish_publish(str(payload.get("message", "Published.")))

    def _on_publish_failed(self, message: str) -> None:
        self._finish_publish(f"Publishing failed: {message}")

    def _idle_controls(self) -> None:
        """Re-enable the buttons and stop the arc, leaving the progress bar alone."""
        self._publish.setEnabled(True)
        self._spinner.stop()

    def _finish_publish(self, message: str) -> None:
        """Put the page back to rest once a publish attempt is over."""
        self._idle_controls()
        self._progress.setVisible(False)
        self._status.setText(message)
        self.status.emit(message)
        # Opening the site is only meaningful once a publish has produced one; a
        # failed *later* publish keeps the link to the site that is already up.
        self._open_site.setEnabled(bool(self._pages_url))

    def _on_open_site(self) -> None:
        """Open the published Pages site in the user's browser."""
        if self._pages_url:
            QDesktopServices.openUrl(QUrl(self._pages_url))
