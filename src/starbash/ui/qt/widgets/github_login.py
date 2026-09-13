"""A step-by-step GitHub sign-in and App-installation dialog.

Publishing to GitHub Pages needs two separate things that a first-time user does not
have: an OAuth token, and permission for the Starbash App to create and publish the
``starbash-public`` repository.  GitHub deliberately splits those into two steps, so
the CLI walks a user through both with Rich prompts (see
:mod:`starbash.commands.publish`); this dialog walks the GUI user through the same
two steps instead, with the network work on worker threads so the window never
freezes.

The contract with the caller is narrow on purpose: the dialog either ends with the
App installed and a credential *stored*, or it does not.  A caller that gets ``True``
from :func:`run_github_setup` simply runs its publish job again.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from starbash.publish.github_publish import APP_INSTALLATION_URL, PUBLISH_REPOSITORY
from starbash.ui.qt.jobs import github_install_job, github_sign_in_job
from starbash.ui.qt.widgets.busy_indicator import Spinner
from starbash.ui.qt.workers import Worker, run_async

logger = logging.getLogger(__name__)

__all__ = ["GitHubSetupDialog", "run_github_setup"]

#: Steps of the dialog, in the order a first-time user walks them.
STEP_WELCOME = 0
STEP_WAITING = 1
STEP_INSTALL = 2
STEP_DONE = 3


def _open_url(url: str) -> bool:
    """Open ``url`` in the user's browser, best effort.

    Indirected through this function so tests can assert what would be opened
    without launching a browser.
    """
    try:
        return bool(QDesktopServices.openUrl(QUrl(url)))
    except Exception:  # pragma: no cover - a missing desktop handler must not crash
        logger.warning("Could not open %s in a browser", url, exc_info=True)
        return False


class GitHubSetupDialog(QDialog):
    """Walk a user through GitHub sign-in and App installation.

    Both network steps run through :func:`~starbash.ui.qt.workers.run_async`, so the
    dialog never blocks the GUI thread and every callback below arrives back on it.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        start_at_install: bool = False,
        credential: dict[str, Any] | None = None,
    ) -> None:
        """Create the dialog.

        Args:
            parent: optional parent widget.
            start_at_install: begin at the App-installation step.  Used when a token
                is already stored but the App is missing, so the user is not asked to
                sign in all over again.
            credential: a credential obtained moments ago (as the raw token response)
                to check instead of re-reading the store.
        """
        super().__init__(parent)
        self.setWindowTitle("Connect Starbash to GitHub")
        self.setMinimumWidth(560)

        #: Set once the App is installed and the credential has been stored, i.e.
        #: once publishing can actually work.
        self.ready = False
        self._step = STEP_WELCOME
        self._credential = credential
        self._login = ""
        self._verification_uri = ""
        self._worker: Worker | None = None
        self._closed = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        #: Kept so :meth:`_refit` can re-run the layout after a step reveals text.
        self._box = layout

        self._title = QLabel()
        self._title.setObjectName("PageTitle")
        layout.addWidget(self._title)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("PageSubtitle")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._code = QLabel()
        self._code.setObjectName("DeviceCode")
        self._code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._code)

        self._status = QLabel()
        self._status.setObjectName("PageSubtitle")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._primary = QPushButton()
        self._primary.setObjectName("Primary")
        self._primary.clicked.connect(self._on_primary)

        # A compact arc in the button row, so a step that is waiting on GitHub looks
        # alive without covering the code the user has to read.
        self._spinner = Spinner()

        self._secondary = QPushButton()
        self._secondary.clicked.connect(self._on_secondary)

        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(self.reject)

        bar = QHBoxLayout()
        bar.addWidget(self._primary)
        bar.addWidget(self._spinner)
        bar.addWidget(self._secondary)
        bar.addStretch(1)
        bar.addWidget(self._cancel)
        layout.addLayout(bar)

        if start_at_install:
            self._show_step(STEP_INSTALL)
            self._open_install_page()
            self._check_install()
        else:
            self._show_step(STEP_WELCOME)

    # --- rendering --------------------------------------------------------
    def _show_step(self, step: int) -> None:
        """Render ``step`` (one set of widgets is reused for all of them)."""
        self._step = step
        self._set_busy(False)
        if step == STEP_WELCOME:
            self._title.setText("Connect to GitHub")
            self._subtitle.setText(
                "Starbash publishes your report site with GitHub Pages, which needs a "
                "one-time sign-in so Starbash can create and update the site's "
                "repository for you.  Nothing is uploaded until you ask for it."
            )
            self._code.hide()
            self._set_status("")
            self._primary.setText("Sign in with GitHub")
            self._secondary.hide()
        elif step == STEP_WAITING:
            self._title.setText("Authorize Starbash")
            self._subtitle.setText(
                "GitHub is opening in your browser.  If it does not, press “Open the "
                "page” and enter this code there:"
            )
            self._code.show()
            # Nothing to open until GitHub hands us a verification URI.
            self._primary.setEnabled(bool(self._verification_uri))
            self._primary.setText("Open the page")
            self._secondary.setText("Copy code")
            self._secondary.show()
        elif step == STEP_INSTALL:
            self._title.setText("Install the Starbash app")
            self._subtitle.setText(
                "Signing in is not enough: GitHub also asks which repositories an app "
                "may use.\n\n"
                "1. Open the installation page.\n"
                "2. Select your account.\n"
                "3. Choose “All repositories”.\n"
                "4. Click Install.\n\n"
                "Starbash only ever creates and updates its own public "
                f"“{PUBLISH_REPOSITORY}” repository."
            )
            self._code.hide()
            self._primary.setText("Open the installation page")
            self._secondary.setText("I've installed it")
            self._secondary.show()
        else:
            self._title.setText("You're connected")
            who = f" as {self._login}" if self._login else ""
            self._subtitle.setText(f"GitHub is ready{who}.  Close this window and publish again.")
            self._code.hide()
            self._set_status("")
            self._primary.setText("Done")
            self._secondary.hide()
        # Showing a step reveals text (the device code, the install instructions)
        # that the size the dialog was first shown with has no room for.
        self._refit()

    def _refit(self) -> None:
        """Re-size the window to fit the text the current step revealed.

        The dialog is shown once, on the welcome step, so every later step has to
        grow the window itself.  ``adjustSize()`` alone is not enough to do that:
        for word-wrapped text a ``QLabel`` reports a ``sizeHint`` that can be
        *shorter* than the text needs at the width the layout actually gives it
        (the install step's instructions are the extreme case), which left the
        ends of those lines - and the device code, which the user has to read
        accurately - cut off.  ``heightForWidth()`` measured at the real width is
        accurate instead, but it needs the minimums from the previous step
        cleared first: ``QLabel`` clamps its own hints by the minimum height it
        was given, so a window that grew would never shrink again.
        """
        wrapped = (self._subtitle, self._status)
        for label in wrapped:
            label.setMinimumHeight(0)
        self._box.activate()
        for label in wrapped:
            # An empty label has no height for any width; it reports -1.
            label.setMinimumHeight(max(0, label.heightForWidth(label.width())))
        self._box.activate()
        self.adjustSize()

    def _set_status(self, text: str) -> None:
        """Set the status line, re-fitting first: a new message adds wrapped lines."""
        self._status.setText(text)
        self._refit()

    def _set_busy(self, busy: bool) -> None:
        """Lock the row while a step talks to GitHub, and show the arc."""
        self._primary.setEnabled(not busy)
        self._secondary.setEnabled(not busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()

    # --- button handling --------------------------------------------------
    def _on_primary(self) -> None:
        """Run the current step's main action."""
        if self._step == STEP_WELCOME:
            self._start_sign_in()
        elif self._step == STEP_WAITING:
            self._open_verification_page()
        elif self._step == STEP_INSTALL:
            self._open_install_page()
        else:
            self.accept()

    def _on_secondary(self) -> None:
        """Run the current step's secondary action."""
        if self._step == STEP_WAITING:
            QGuiApplication.clipboard().setText(self._code.text())
            self._set_status("Code copied.  Paste it into the GitHub page.")
        elif self._step == STEP_INSTALL:
            self._check_install()

    # --- steps that talk to GitHub ---------------------------------------
    def _open_verification_page(self) -> None:
        """Open GitHub's device-authorization page (the code is shown already)."""
        if not self._verification_uri:
            return
        if not _open_url(self._verification_uri):
            self._set_status(f"Could not open a browser - open {self._verification_uri} yourself.")

    def _open_install_page(self) -> None:
        """Open GitHub's App-installation page."""
        if not _open_url(APP_INSTALLATION_URL):
            self._set_status(f"Could not open a browser - open {APP_INSTALLATION_URL} yourself.")

    def _start_sign_in(self) -> None:
        """Request a device code, show it, and wait for the user to authorize it."""
        self._credential = None
        self._verification_uri = ""
        self._show_step(STEP_WAITING)
        self._code.setText("…")
        self._set_status("Contacting GitHub...")
        self._set_busy(True)
        self._worker = run_async(
            github_sign_in_job,
            on_progress=self._on_device_code,
            on_finished=self._on_signed_in,
            on_failed=self._on_failed,
        )

    def _on_device_code(self, payload: object) -> None:
        """Show the code GitHub issued, and open its authorization page."""
        if self._closed or not isinstance(payload, dict):
            return
        self._verification_uri = str(payload.get("verification_uri", ""))
        self._code.setText(str(payload.get("user_code", "")))
        self._set_busy(False)
        self._set_status("Waiting for you to authorize in your browser...")
        self._open_verification_page()

    def _on_signed_in(self, result: object) -> None:
        """The device login finished: move on to the App installation."""
        if self._closed:
            return
        if isinstance(result, dict) and isinstance(result.get("credential"), dict):
            self._credential = result["credential"]
        self._show_step(STEP_INSTALL)
        self._open_install_page()
        self._check_install()

    def _check_install(self) -> None:
        """Ask GitHub whether the App is installed yet."""
        self._set_status("Checking the installation...")
        self._set_busy(True)
        credential = self._credential
        self._worker = run_async(
            lambda report, token: github_install_job(report, token, credential),
            on_finished=self._on_install_checked,
            on_failed=self._on_failed,
        )

    def _on_install_checked(self, result: object) -> None:
        """Finish the dialog, or say that GitHub has not seen the install yet."""
        if self._closed:
            return
        payload = result if isinstance(result, dict) else {}
        if payload.get("installed"):
            self._login = str(payload.get("login", ""))
            self.ready = True
            self._show_step(STEP_DONE)
            return
        self._set_busy(False)
        if not payload.get("signed_in", False):
            # The stored credential is gone (or was rejected), so this step can
            # never succeed: send the user back to the start instead.
            self._show_step(STEP_WELCOME)
            self._set_status("Starbash is no longer signed in to GitHub.")
        else:
            self._set_status(
                "GitHub has not seen the installation yet.  Install the app, then press "
                "“I've installed it”."
            )

    def _on_failed(self, message: str) -> None:
        """Report a GitHub error and leave the user somewhere they can retry."""
        if self._closed:
            return
        logger.warning("GitHub setup step failed: %s", message)
        if self._step == STEP_WAITING and not self._verification_uri:
            # The device flow never got a code, so offer the first step again.
            self._show_step(STEP_WELCOME)
        else:
            self._set_busy(False)
        self._set_status(f"{message}  You can try again.")

    # --- lifecycle --------------------------------------------------------
    def _stop_worker(self) -> None:
        """Cancel any in-flight step; its callbacks then bail out."""
        self._closed = True
        if self._worker is not None:
            self._worker.token.cancel()
            self._worker = None

    def reject(self) -> None:  # noqa: D102 - QDialog API
        self._stop_worker()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """The window manager's close button must stop the worker too."""
        self._stop_worker()
        super().closeEvent(event)


def run_github_setup(parent: QWidget | None = None, *, start_at_install: bool = False) -> bool:
    """Show the GitHub setup dialog and return whether publishing can proceed.

    Args:
        parent: the widget to centre the dialog over.
        start_at_install: skip the sign-in step, for a user who is already signed in
            but has not installed the App yet.
    """
    dialog = GitHubSetupDialog(parent, start_at_install=start_at_install)
    dialog.exec()
    return dialog.ready
