"""Tests for the GUI's GitHub jobs: knowing the account, and recording it.

The jobs are what the Publish page and the setup dialog run on worker threads.  Two
behaviours are easy to lose in a refactor and are pinned down here: the account shown
on the page is *read back* from the credential store (no network call, and no keyring
access on the GUI thread), and the account name is only ever whatever GitHub reports.

The publish job is deliberately only driven up to its GitHub check: past that it
generates and uploads a site, which is the core's job to test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from starbash.publish import credentials, github_publish  # noqa: E402
from starbash.publish.credentials import GitHubCredential  # noqa: E402
from starbash.ui.qt import jobs  # noqa: E402
from starbash.ui.qt.workers import CancelToken  # noqa: E402

pytestmark = pytest.mark.gui


def _stored_credential(monkeypatch, credential: GitHubCredential | None) -> MagicMock:
    """Make the store the jobs build hold ``credential``, and return that store."""
    store = MagicMock()
    store.load.return_value = credential
    monkeypatch.setattr(credentials, "GitHubCredentialStore", MagicMock(return_value=store))
    return store


def _service(monkeypatch, *, login: str, installed: bool) -> MagicMock:
    """Point the jobs' authenticated service at an account with a known login."""
    service = MagicMock()
    service.app_is_installed.return_value = installed
    service.user.return_value = {"login": login}
    monkeypatch.setattr(github_publish, "credential_service", MagicMock(return_value=service))
    return service


# --- what the Publish page shows --------------------------------------------


def test_the_identity_job_reports_the_stored_account(monkeypatch):
    """The page shows the account recorded with the credential, without a network call."""
    _stored_credential(monkeypatch, GitHubCredential("token", login="octocat"))

    result = jobs.github_identity_job(MagicMock(), CancelToken())

    assert result == {"signed_in": True, "login": "octocat"}


def test_the_identity_job_reports_nobody_signed_in_without_a_credential(monkeypatch):
    """No stored credential means the page says so rather than inventing an account."""
    _stored_credential(monkeypatch, None)

    result = jobs.github_identity_job(MagicMock(), CancelToken())

    assert result == {"signed_in": False, "login": ""}


# --- recording the account with the credential ------------------------------


def test_installing_the_app_saves_the_account_github_reports(monkeypatch):
    """Once the App is installed the credential is stored *with* the account name."""
    store = _stored_credential(monkeypatch, GitHubCredential("token"))
    _service(monkeypatch, login="octocat", installed=True)

    result = jobs.github_install_job(MagicMock(), CancelToken())

    assert result == {"signed_in": True, "installed": True, "login": "octocat"}
    assert store.save.call_args.args[0].login == "octocat"


def test_a_publish_records_the_account_github_reports(monkeypatch):
    """A publish stores the account as soon as GitHub reports it.

    The upload stops here (the App is not installed yet), which is exactly why the
    account has to be saved first: the page can then show who is signed in while the
    user works through the installation step.
    """
    store = _stored_credential(monkeypatch, GitHubCredential("token"))
    _service(monkeypatch, login="octocat", installed=False)
    monkeypatch.setattr(
        github_publish,
        "refresh_if_needed",
        MagicMock(side_effect=lambda service, credential, **kwargs: credential),
    )

    result = jobs.publish_github_job(MagicMock(), CancelToken())

    assert result["needs_install"] is True
    assert store.save.call_args.args[0].login == "octocat"


def test_a_publish_does_not_rewrite_a_credential_that_already_names_its_account(monkeypatch):
    """Publishing is not an excuse to touch the keyring on every run."""
    store = _stored_credential(monkeypatch, GitHubCredential("token", login="octocat"))
    _service(monkeypatch, login="octocat", installed=False)
    monkeypatch.setattr(
        github_publish,
        "refresh_if_needed",
        MagicMock(side_effect=lambda service, credential, **kwargs: credential),
    )

    jobs.publish_github_job(MagicMock(), CancelToken())

    store.save.assert_not_called()
