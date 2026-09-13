"""Tests for the GitHub setup dialog: the sign-in/install step machine.

The dialog's whole job is to walk a user through two steps only they can complete,
while the network work happens on worker threads.  These tests pin down the step
transitions, *which* job each step runs (and with what credential), and that closing
the window stops the work instead of leaving it running behind a dead dialog.

``run_async`` is replaced with a recorder rather than the real thread pool: the job
bodies talk to GitHub, and what we want to check is the sequencing around them.  The
recorded callbacks are then invoked directly - exactly as the real signals would be,
and on this (GUI) thread.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from starbash.ui.qt.widgets import github_login as login  # noqa: E402
from starbash.ui.qt.widgets.github_login import GitHubSetupDialog  # noqa: E402
from starbash.ui.qt.workers import CancelToken  # noqa: E402

pytestmark = pytest.mark.gui

VERIFICATION_URI = "https://github.com/login/device"
DEVICE_CODE = {"user_code": "ABCD-1234", "verification_uri": VERIFICATION_URI}
#: What github_sign_in_job returns: the raw token response, not yet stored.
CREDENTIAL = {"access_token": "tok", "refresh_token": None, "token_type": "bearer"}


class _RecordedJob:
    """One captured ``run_async`` call, with its callbacks kept reachable."""

    def __init__(self, job: Any, **callbacks: Any) -> None:
        self.job = job
        self.on_finished = callbacks.get("on_finished")
        self.on_failed = callbacks.get("on_failed")
        self.on_progress = callbacks.get("on_progress")
        self.worker = _FakeWorker()

    def progress(self, payload: Any) -> None:
        """Deliver a progress payload, as WorkerSignals.progress would."""
        if self.on_progress is not None:
            self.on_progress(payload)

    def finish(self, result: Any) -> None:
        """Deliver a successful result, as WorkerSignals.finished would."""
        if self.on_finished is not None:
            self.on_finished(result)

    def fail(self, message: str) -> None:
        """Deliver a failure, as WorkerSignals.failed would."""
        if self.on_failed is not None:
            self.on_failed(message)


class _FakeWorker:
    """Just the cancel token the dialog needs from a Worker."""

    def __init__(self) -> None:
        self.token = CancelToken()


@pytest.fixture
def recorded(monkeypatch) -> list[_RecordedJob]:
    """Capture each ``run_async`` call instead of running it off-thread."""
    jobs: list[_RecordedJob] = []

    def fake_run_async(job: Any, **callbacks: Any) -> _FakeWorker:
        entry = _RecordedJob(job, **callbacks)
        jobs.append(entry)
        return entry.worker

    monkeypatch.setattr(login, "run_async", fake_run_async)
    return jobs


@pytest.fixture
def opened(monkeypatch) -> list[str]:
    """Record the URLs the dialog would open, so no browser is launched."""
    urls: list[str] = []

    def fake_open_url(url: str) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr(login, "_open_url", fake_open_url)
    return urls


def _dialog(qtbot, **kwargs: Any) -> GitHubSetupDialog:
    """A dialog parented to nothing, owned by ``qtbot`` so it is cleaned up."""
    dialog = GitHubSetupDialog(None, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


# --- the first step ---------------------------------------------------------


def test_dialog_starts_on_the_sign_in_step(qtbot):
    """A fresh dialog offers the sign-in, with nothing else on screen yet."""
    dialog = _dialog(qtbot)

    assert dialog._step == login.STEP_WELCOME
    assert dialog.ready is False
    assert dialog._primary.text() == "Sign in with GitHub"
    assert dialog._primary.isEnabled()
    assert dialog._code.isHidden()
    assert dialog._secondary.isHidden()


def test_sign_in_shows_the_device_code_and_opens_the_authorization_page(
    qtbot, recorded, opened, monkeypatch
):
    """Pressing Sign in runs the device flow and surfaces GitHub's code."""
    sign_in = MagicMock()
    monkeypatch.setattr(login, "github_sign_in_job", sign_in)
    dialog = _dialog(qtbot)

    dialog._primary.click()

    assert dialog._step == login.STEP_WAITING
    assert recorded[-1].job is sign_in  # the shared, front-end-agnostic job
    # Nothing to open until GitHub issues a code, and nothing to copy yet.
    assert dialog._primary.isEnabled() is False
    assert dialog._secondary.isEnabled() is False
    assert opened == []

    recorded[-1].progress(DEVICE_CODE)

    assert dialog._code.text() == "ABCD-1234"
    assert dialog._code.isHidden() is False
    assert dialog._primary.isEnabled()
    assert opened == [VERIFICATION_URI]


def test_the_open_button_does_nothing_until_there_is_a_page_to_open(qtbot, recorded, opened):
    """A disabled primary cannot open a URL the dialog has not been given."""
    dialog = _dialog(qtbot)
    dialog._primary.click()  # start the sign-in, but no code has arrived yet

    dialog._primary.click()

    assert opened == []


def test_the_copy_button_puts_the_code_on_the_clipboard(qtbot, recorded):
    """The secondary action copies the code for pasting into the browser."""
    dialog = _dialog(qtbot)
    dialog._primary.click()
    recorded[-1].progress(DEVICE_CODE)

    dialog._secondary.click()

    assert login.QGuiApplication.clipboard().text() == "ABCD-1234"
    assert "Paste it" in dialog._status.text()


# --- the install step -------------------------------------------------------


def test_completing_the_sign_in_moves_to_the_install_step(qtbot, recorded, opened, monkeypatch):
    """The credential from the device flow is handed to the installation check."""
    install = MagicMock()
    monkeypatch.setattr(login, "github_install_job", install)
    dialog = _dialog(qtbot)
    dialog._primary.click()
    recorded[-1].progress(DEVICE_CODE)

    recorded[-1].finish({"credential": CREDENTIAL})

    assert dialog._step == login.STEP_INSTALL
    assert opened == [VERIFICATION_URI, login.APP_INSTALLATION_URL]
    assert len(recorded) == 2

    # Running the recorded job is what the real worker would do, and it must pass
    # along both the progress reporter and the credential just obtained.
    report = MagicMock()
    recorded[-1].job(report, recorded[-1].worker.token)
    install.assert_called_once_with(report, recorded[-1].worker.token, CREDENTIAL)


def test_the_install_step_can_be_started_directly(qtbot, recorded, opened, monkeypatch):
    """A user who is signed in but not installed skips straight to step two."""
    install = MagicMock()
    monkeypatch.setattr(login, "github_install_job", install)

    dialog = _dialog(qtbot, start_at_install=True)

    assert dialog._step == login.STEP_INSTALL
    assert opened == [login.APP_INSTALLATION_URL]
    report = MagicMock()
    recorded[-1].job(report, recorded[-1].worker.token)
    # No credential was passed in, so the job loads the stored one (off-thread).
    install.assert_called_once_with(report, recorded[-1].worker.token, None)


def test_installed_account_finishes_the_dialog(qtbot, recorded):
    """Once GitHub reports the App, the dialog is done and publishing can start."""
    dialog = _dialog(qtbot, start_at_install=True)

    recorded[-1].finish({"signed_in": True, "installed": True, "login": "octocat"})

    assert dialog.ready is True
    assert dialog._step == login.STEP_DONE
    assert dialog._primary.text() == "Done"
    assert "octocat" in dialog._subtitle.text()


def test_a_missing_installation_tells_the_user_what_to_do(qtbot, recorded):
    """Signed in but not installed: stay on the step and say what is missing."""
    dialog = _dialog(qtbot, start_at_install=True)

    recorded[-1].finish({"signed_in": True, "installed": False, "login": ""})

    assert dialog.ready is False
    assert dialog._step == login.STEP_INSTALL
    assert dialog._primary.isEnabled()
    assert "I've installed it" in dialog._status.text()


def test_a_lost_credential_returns_to_the_sign_in_step(qtbot, recorded):
    """Without a usable credential the install step can never succeed, so restart."""
    dialog = _dialog(qtbot, start_at_install=True)

    recorded[-1].finish({"signed_in": False, "installed": False, "login": ""})

    assert dialog.ready is False
    assert dialog._step == login.STEP_WELCOME
    assert "no longer signed in" in dialog._status.text()


# --- the window has to fit each step ----------------------------------------


def _clipped(label: QLabel) -> bool:
    """Whether ``label`` got less room than its text needs to be drawn.

    ``QLabel``'s own hints cannot be trusted here: for wrapped text its
    ``sizeHint`` can be shorter than the text needs at the width the layout gave
    it, and both hints are clamped by whatever minimum height it was given.  The
    font metrics are what the painter actually measures with, so ask those.
    """
    metrics = label.fontMetrics()
    if not label.wordWrap():
        return label.contentsRect().height() < metrics.height()
    needed = metrics.boundingRect(
        QRect(0, 0, label.contentsRect().width(), 10_000),
        int(Qt.TextFlag.TextWordWrap),
        label.text(),
    )
    return label.height() < needed.height()


def test_a_revealed_step_is_not_clipped(qtbot, qapp, recorded, opened):
    """Every step has to fit into the window it is revealed into.

    The dialog is shown on the welcome step, so each later step - the device code
    the user has to read accurately, then the install instructions, then a status
    message that wraps - has to grow the window itself, or its text is cut off.
    """
    from starbash.ui.qt import theme

    # The clipping is about the theme's styling (a large monospace device code,
    # padded labels), which the app applies but the suite otherwise does not.
    theme.apply_theme(qapp)
    dialog = _dialog(qtbot)
    dialog.show()

    dialog._primary.click()  # welcome -> waiting, which reveals the code label
    recorded[-1].progress(DEVICE_CODE)

    assert dialog._code.text() == "ABCD-1234"
    assert not _clipped(dialog._code)

    recorded[-1].finish({"credential": CREDENTIAL})  # waiting -> install

    assert dialog._step == login.STEP_INSTALL
    assert not _clipped(dialog._subtitle)

    # ... and a status line that has to wrap to two lines still fits.
    recorded[-1].finish({"signed_in": True, "installed": False, "login": ""})

    assert "I've installed it" in dialog._status.text()
    assert not _clipped(dialog._status)
    assert dialog.height() >= dialog._box.minimumSize().height()


# --- failures and cancellation ---------------------------------------------


def test_a_failed_sign_in_offers_another_try(qtbot, recorded):
    """A device-flow failure returns to step one, with an enabled button."""
    dialog = _dialog(qtbot)
    dialog._primary.click()

    recorded[-1].fail("network is unreachable")

    assert dialog._step == login.STEP_WELCOME
    assert dialog._primary.isEnabled()
    assert "network is unreachable" in dialog._status.text()


def test_a_failed_install_check_keeps_the_install_step(qtbot, recorded):
    """A failed install check leaves the user on the step they were working on."""
    dialog = _dialog(qtbot, start_at_install=True)

    recorded[-1].fail("GitHub said no")

    assert dialog._step == login.STEP_INSTALL
    assert dialog._primary.isEnabled()
    assert "GitHub said no" in dialog._status.text()


def test_cancelling_stops_the_worker_and_ignores_late_callbacks(qtbot, recorded):
    """Closing the dialog must not leave a poll running behind a dead window."""
    dialog = _dialog(qtbot)
    dialog._primary.click()
    worker = recorded[-1].worker

    dialog.reject()

    assert worker.token.is_cancelled()
    # A result that arrives after the user gave up must not touch the UI.
    recorded[-1].progress(DEVICE_CODE)
    recorded[-1].finish({"credential": CREDENTIAL})
    assert dialog._code.text() == "…"
    assert dialog.ready is False
    assert dialog._step == login.STEP_WAITING


def test_closing_the_window_stops_the_worker_too(qtbot, recorded):
    """The window manager's close button is not the dialog's Cancel button."""
    dialog = _dialog(qtbot)
    dialog._primary.click()
    worker = recorded[-1].worker

    dialog.closeEvent(login.QCloseEvent())

    assert worker.token.is_cancelled()


def test_run_github_setup_reports_whether_publishing_can_proceed(monkeypatch):
    """The module-level entry point just reports the dialog's outcome."""

    class _FakeDialog:
        def __init__(self, parent=None, *, start_at_install: bool = False) -> None:
            self.ready = start_at_install

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(login, "GitHubSetupDialog", _FakeDialog)

    assert login.run_github_setup(None, start_at_install=True) is True
    assert login.run_github_setup(None) is False
