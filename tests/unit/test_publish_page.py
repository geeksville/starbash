"""Tests for the Publish page: publishing to GitHub Pages.

The page is thin on purpose - the work lives in the shared jobs - but it owns the
part users actually feel: the button/progress/status dance, handing a user who is
not yet connected to GitHub over to the setup dialog and *then running the publish
again*, and only offering "Open in browser" once a publish has produced a site.
That retry is the bit worth pinning down, since the job reports
``needs_sign_in``/``needs_install`` as ordinary results rather than errors.

The GitHub account shown on the page is read-only: it is what ``github_identity_job``
reads back from the credential store (and what GitHub reports at publish time), never
anything the user types.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from starbash.ui.qt.pages import base as base_page  # noqa: E402
from starbash.ui.qt.pages import publish as publish_page  # noqa: E402
from starbash.ui.qt.pages.publish import PublishPage  # noqa: E402
from starbash.ui.qt.workers import CancelToken  # noqa: E402

pytestmark = pytest.mark.gui


class _FakeWorker:
    """Just the cancel token a page's worker exposes."""

    def __init__(self) -> None:
        self.token = CancelToken()


class _RecordedJob:
    """One captured ``run_async`` call, with its callbacks kept reachable."""

    def __init__(self, job: Any, **callbacks: Any) -> None:
        self.job = job
        self.on_finished = callbacks.get("on_finished")
        self.on_failed = callbacks.get("on_failed")
        self.on_progress = callbacks.get("on_progress")
        self.worker = _FakeWorker()

    def progress(self, payload: Any) -> None:
        if self.on_progress is not None:
            self.on_progress(payload)

    def finish(self, result: Any) -> None:
        if self.on_finished is not None:
            self.on_finished(result)

    def fail(self, message: str) -> None:
        if self.on_failed is not None:
            self.on_failed(message)

    def run(self, report: Any) -> Any:
        """Run the recorded job body, as the real worker thread would."""
        return self.job(report, self.worker.token)


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context."""
    from starbash.app import Starbash

    with Starbash("test.publish-page") as sb:
        yield sb


@pytest.fixture
def recorded(monkeypatch) -> list[_RecordedJob]:
    """Capture each ``run_async`` call instead of running it off-thread."""
    jobs: list[_RecordedJob] = []

    def fake_run_async(job: Any, **callbacks: Any) -> _FakeWorker:
        entry = _RecordedJob(job, **callbacks)
        jobs.append(entry)
        return entry.worker

    # Page.start_job() looks the name up in its own module, so that is where the
    # fake has to go.
    monkeypatch.setattr(base_page, "run_async", fake_run_async)
    return jobs


@pytest.fixture(autouse=True)
def errors(monkeypatch) -> list[str]:
    """Record the modal error dialogs the page would have shown.

    A real QMessageBox blocks a headless run forever, so failures are captured
    instead of displayed.  Autouse, so no test can accidentally block.
    """
    messages: list[str] = []

    def fake_show_error(self: Any, message: str, title: str = "Starbash") -> None:
        messages.append(message)

    monkeypatch.setattr(PublishPage, "show_error", fake_show_error)
    return messages


def _page(qtbot, app_context) -> PublishPage:
    """A Publish page owned by ``qtbot`` so it is cleaned up."""
    page = PublishPage(app_context, None)
    qtbot.addWidget(page)
    return page


class _FakeDesktop:
    """A stand-in for ``QDesktopServices`` that records what was opened."""

    def __init__(self) -> None:
        self.opened: list[str] = []

    def openUrl(self, url: object) -> bool:  # noqa: N802 - Qt API
        self.opened.append(url.toString())  # type: ignore[attr-defined]
        return True


def _statuses(page: PublishPage) -> list[str]:
    """Collect the messages the page emits for the window's status bar."""
    messages: list[str] = []
    page.status.connect(messages.append)
    return messages


# --- the page at rest -------------------------------------------------------


def test_the_page_offers_publishing_as_the_primary_action(qtbot, app_context):
    """Publishing is the button a first-time user should reach for."""
    page = _page(qtbot, app_context)

    assert page._publish.text() == "Publish to GitHub"
    assert page._publish.objectName() == "Primary"
    assert page._publish.isEnabled()
    # The progress bar is only interesting while an upload is in flight.
    assert page._progress.isHidden()


def test_opening_the_site_is_offered_only_once_something_has_been_published(
    qtbot, app_context, monkeypatch
):
    """There is no site to open before a publish, so the button starts disabled."""
    desktop = _FakeDesktop()
    monkeypatch.setattr(publish_page, "QDesktopServices", desktop)
    page = _page(qtbot, app_context)

    assert page._open_site.isEnabled() is False
    page._open_site.click()  # a no-op: it is disabled
    assert desktop.opened == []


# --- the signed-in account --------------------------------------------------


def test_the_account_field_is_read_only_and_shows_what_the_identity_job_reports(
    qtbot, app_context, recorded
):
    """The account is GitHub's answer, not a form field the user can edit."""
    page = _page(qtbot, app_context)

    assert page._username.isReadOnly()
    assert page._username.text() == ""
    assert page._username.placeholderText() == "Not signed in to GitHub"

    page.refresh()
    recorded[-1].finish({"signed_in": True, "login": "octocat"})

    assert page._username.text() == "octocat"


def test_a_stored_credential_without_an_account_name_still_says_it_is_signed_in(
    qtbot, app_context, recorded
):
    """Credentials saved before the login was recorded read back as an empty login."""
    page = _page(qtbot, app_context)

    page.refresh()
    recorded[-1].finish({"signed_in": True, "login": ""})

    assert page._username.text() == ""
    assert page._username.placeholderText() == "Signed in to GitHub"


def test_a_page_whose_identity_read_fails_stays_idle(qtbot, app_context, recorded, errors):
    """A broken credential store is an error dialog, but must not wedge the page."""
    page = _page(qtbot, app_context)

    page.refresh()
    recorded[-1].fail("Invalid GitHub credential in keyring")

    assert errors == ["Invalid GitHub credential in keyring"]
    assert page._publish.isEnabled()
    assert page._username.isReadOnly()


# --- publishing -------------------------------------------------------------


def test_publishing_runs_the_shared_job_and_drives_the_bar_from_its_steps(
    qtbot, app_context, recorded, monkeypatch
):
    """The page starts the publish and renders the job's per-file steps."""
    publish = MagicMock()
    monkeypatch.setattr(publish_page, "publish_github_job", publish)
    page = _page(qtbot, app_context)

    page._publish.click()

    assert page._publish.isEnabled() is False
    assert page._open_site.isEnabled() is False
    assert page._spinner.is_running()
    assert page._progress.isHidden() is False

    report = MagicMock()
    recorded[-1].run(report)
    # The account comes from the credential, so the page passes nothing in.
    publish.assert_called_once_with(report, recorded[-1].worker.token)

    # Steps arrive as (description, completed, total) and fill the bar.
    recorded[-1].progress(("Uploaded index.html", 4, 12))
    assert page._progress.value() == 4
    assert page._progress.maximum() == 12
    assert page._status.text() == "Uploaded index.html"
    assert page._open_site.isEnabled() is False

    recorded[-1].finish(
        {
            "owner": "octocat",
            "pages_url": "https://octocat.github.io/starbash-public/",
            "message": "Published 3 files.",
        }
    )

    assert page._publish.isEnabled()
    assert page._spinner.is_running() is False
    assert page._progress.isHidden()
    assert page._status.text() == "Published 3 files."
    # What GitHub reported is what the field shows, and the site can now be opened.
    assert page._username.text() == "octocat"
    assert page._open_site.isEnabled()


def test_opening_the_site_opens_the_published_pages_url(qtbot, app_context, recorded, monkeypatch):
    """The button opens the github.io site - not a local file."""
    monkeypatch.setattr(publish_page, "publish_github_job", lambda *args: {})
    desktop = _FakeDesktop()
    monkeypatch.setattr(publish_page, "QDesktopServices", desktop)
    page = _page(qtbot, app_context)

    page._publish.click()
    recorded[-1].finish(
        {
            "owner": "octocat",
            "pages_url": "https://octocat.github.io/starbash-public/",
            "message": "Published 3 files.",
        }
    )

    page._open_site.click()

    assert desktop.opened == ["https://octocat.github.io/starbash-public/"]


def test_a_publish_that_reports_no_pages_url_leaves_nothing_to_open(
    qtbot, app_context, recorded, monkeypatch
):
    """Only a publish that reports a site URL enables the browser button."""
    monkeypatch.setattr(publish_page, "publish_github_job", lambda *args: {})
    page = _page(qtbot, app_context)

    page._publish.click()
    recorded[-1].finish({"owner": "octocat", "message": "Published 3 files."})

    assert page._pages_url == ""
    assert page._open_site.isEnabled() is False


def test_a_later_failed_publish_keeps_the_link_to_the_live_site(
    qtbot, app_context, recorded, monkeypatch
):
    """A site that is already up stays reachable after a failed retry."""
    monkeypatch.setattr(publish_page, "publish_github_job", lambda *args: {})
    page = _page(qtbot, app_context)

    page._publish.click()
    recorded[-1].finish(
        {
            "owner": "octocat",
            "pages_url": "https://octocat.github.io/starbash-public/",
            "message": "Published 3 files.",
        }
    )
    assert page._open_site.isEnabled()

    page._publish.click()
    assert page._open_site.isEnabled() is False  # nothing to open while it runs

    recorded[-1].fail("GitHub rejected the upload")

    assert page._open_site.isEnabled()


def test_publishing_without_a_credential_opens_the_setup_dialog_and_retries(
    qtbot, app_context, recorded, monkeypatch
):
    """The whole point: guide the user, then run the publish again for them."""
    monkeypatch.setattr(publish_page, "publish_github_job", lambda *args: {})
    setup = MagicMock(return_value=True)
    monkeypatch.setattr(publish_page, "run_github_setup", setup)
    page = _page(qtbot, app_context)

    page._publish.click()
    recorded[-1].finish({"needs_sign_in": True, "message": "Sign in to GitHub."})

    setup.assert_called_once_with(page, start_at_install=False)
    # A second publish is already in flight, so the work carries on by itself.
    assert len(recorded) == 2
    assert page._publish.isEnabled() is False
    assert page._progress.isHidden() is False

    recorded[-1].finish({"message": "Published 3 files."})

    assert page._publish.isEnabled()
    assert page._status.text() == "Published 3 files."


def test_a_missing_app_installation_opens_the_setup_dialog_at_that_step(
    qtbot, app_context, recorded, monkeypatch
):
    """Signed in but not installed resumes at step two rather than re-signing in."""
    monkeypatch.setattr(publish_page, "publish_github_job", lambda *args: {})
    setup = MagicMock(return_value=False)
    monkeypatch.setattr(publish_page, "run_github_setup", setup)
    page = _page(qtbot, app_context)
    statuses = _statuses(page)

    page._publish.click()
    recorded[-1].finish({"needs_install": True, "message": "The app is not installed."})

    assert setup.call_args.kwargs["start_at_install"] is True
    # The user gave up in the dialog, so nothing is left spinning.
    assert len(recorded) == 1
    assert page._publish.isEnabled()
    assert page._open_site.isEnabled() is False
    assert page._spinner.is_running() is False
    assert page._progress.isHidden()
    assert page._status.text() == "Publishing cancelled."
    assert statuses == ["Publishing cancelled."]


def test_a_failed_publish_is_reported_and_the_page_is_usable_again(
    qtbot, app_context, recorded, errors
):
    """A real failure (not a user step) is surfaced, with the page left idle."""
    page = _page(qtbot, app_context)

    page._publish.click()
    recorded[-1].fail("GitHub rejected the upload")

    assert errors == ["GitHub rejected the upload"]
    assert page._publish.isEnabled()
    assert page._open_site.isEnabled() is False
    assert page._progress.isHidden()
    assert page._status.text() == "Publishing failed: GitHub rejected the upload"
