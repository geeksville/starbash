"""Long-running operations executed on worker threads.

Each job constructs its **own** :class:`~starbash.app.Starbash`, so it owns a
private SQLite connection and can safely run off the GUI thread.  Detailed
progress is not pushed from here - the core publishes it on the event bus and
:class:`~starbash.ui.qt.bridge.EventBusBridge` forwards it to the GUI.

Jobs poll their :class:`~starbash.ui.qt.workers.CancelToken` between phases.
Cancellation is therefore *cooperative*: it takes effect at the next phase
boundary, not mid-recipe.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from starbash.ui.qt.workers import CancelToken

__all__ = [
    "reindex_job",
    "process_job",
    "add_repo_job",
    "github_sign_in_job",
    "github_install_job",
    "github_identity_job",
    "publish_github_job",
]

#: How long a cancel-aware sleep lasts before it re-checks its token.
_SLEEP_SLICE_SECONDS = 0.1


def reindex_job(report: Callable[[Any], None], token: CancelToken) -> dict[str, Any]:
    """Re-index every configured repository."""
    from starbash.app import Starbash

    token.raise_if_cancelled()
    report("Re-indexing repositories...")
    with Starbash("gui.reindex") as sb:
        sb.reindex_repos()
    return {"message": "Re-index complete."}


def add_repo_job(
    report: Callable[[Any], None],
    token: CancelToken,
    path: str,
    kind: str | None = None,
) -> dict[str, Any]:
    """Add (and index) a local repository folder."""
    from starbash.app import Starbash

    token.raise_if_cancelled()
    report(f"Adding repository {path}...")
    with Starbash("gui.repo.add") as sb:
        sb.add_local_repo(path, repo_type=kind)
    return {"message": f"Added repository: {path}"}


def process_job(
    report: Callable[[Any], None],
    token: CancelToken,
) -> dict[str, Any]:
    """Run the automated processing pipeline.

    Masters-only processing is CLI-only (`sb process masters`), so there is no
    option for it here.
    """
    from starbash.app import Starbash
    from starbash.processing import Processing

    token.raise_if_cancelled()
    report("Auto-processing selected sessions...")

    # Bind before the `with`: `__exit__` can suppress exceptions, so the type
    # checker (correctly) can't prove the body ran.
    results: list[Any] = []
    with Starbash("gui.process") as sb, Processing(sb) as proc:
        results = proc.run_all_stages()

    succeeded = sum(1 for r in results if getattr(r, "success", None))
    failed = len(results) - succeeded
    return {
        "count": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "message": f"{len(results)} stage(s) run, {succeeded} succeeded, {failed} failed.",
    }


def _cancel_aware_sleeper(token: CancelToken) -> Callable[[float], None]:
    """Return a ``sleep`` that gives up as soon as ``token`` is cancelled.

    The device-flow poll sleeps for GitHub's polling interval (five seconds or
    more), so a plain ``time.sleep`` would keep a closed dialog's worker alive
    with no way to stop it.  Slicing the sleep makes cancellation responsive
    without changing the polling interval GitHub sees.
    """

    def sleep(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            token.raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(_SLEEP_SLICE_SECONDS, remaining))

    return sleep


def github_sign_in_job(report: Callable[[Any], None], token: CancelToken) -> dict[str, Any]:
    """Start GitHub's device flow and wait for the user to authorize it.

    Progress payload is ``{"user_code": ..., "verification_uri": ...}``, reported as
    soon as GitHub issues the code, so the dialog can display (and open) it while
    this thread keeps polling.

    The resulting credential is returned but deliberately **not** saved: the caller
    installs the App first and only then persists it, so a half-finished sign-in
    never leaves a credential that cannot publish.
    """
    from starbash.publish.github_publish import CLIENT_ID, finish_device_login
    from starbash.publish.github_service import GitHubService

    token.raise_if_cancelled()
    service = GitHubService()
    device = service.device_code(CLIENT_ID)
    token.raise_if_cancelled()
    report({"user_code": device.user_code, "verification_uri": device.verification_uri})
    credential = finish_device_login(
        service, device, CLIENT_ID, sleeper=_cancel_aware_sleeper(token)
    )
    return {"credential": credential.as_dict()}


def github_install_job(
    report: Callable[[Any], None],
    token: CancelToken,
    credential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check that the signed-in account has installed the Starbash GitHub App.

    When ``credential`` is omitted the stored one is loaded - here, on the worker
    thread, so the GUI thread never touches the keyring.  Once the App is present
    the credential is saved - together with the account name GitHub reports - which
    is what lets later publishes skip the sign-in and the Publish page show who is
    signed in.

    Returns ``{"signed_in": bool, "installed": bool, "login": str}``.
    """
    from dataclasses import replace

    from starbash.publish.credentials import GitHubCredential, GitHubCredentialStore
    from starbash.publish.github_publish import APP_SLUG, credential_service, save_credential

    token.raise_if_cancelled()
    store = GitHubCredentialStore()
    loaded = GitHubCredential.from_dict(credential) if credential is not None else store.load()
    if loaded is None:
        return {"signed_in": False, "installed": False, "login": ""}

    service = credential_service(loaded, store=store)
    if not service.app_is_installed(APP_SLUG):
        return {"signed_in": True, "installed": False, "login": ""}

    # Ask GitHub who we are and remember the answer beside the token, so the
    # Publish page can show the account without asking again.
    login = str(service.user().get("login", ""))
    save_credential(replace(loaded, login=login) if login else loaded, store=store)
    return {"signed_in": True, "installed": True, "login": login}


def github_identity_job(report: Callable[[Any], None], token: CancelToken) -> dict[str, Any]:
    """Report the GitHub account Starbash is signed in as.

    The credential store is read here, on the worker thread, because the GUI thread
    must not touch the keyring.  The account name comes from the stored credential -
    recorded when the App is installed and refreshed on every publish - so this job
    makes no network calls.

    Returns ``{"signed_in": bool, "login": str}``.  ``login`` is empty for a
    credential saved before Starbash started recording account names.
    """
    from starbash.publish.credentials import GitHubCredentialStore

    token.raise_if_cancelled()
    credential = GitHubCredentialStore().load()
    if credential is None:
        return {"signed_in": False, "login": ""}
    return {"signed_in": True, "login": credential.login}


def publish_github_job(
    report: Callable[[Any], None],
    token: CancelToken,
) -> dict[str, Any]:
    """Generate the report site and publish it to GitHub Pages.

    The site is generated for - and uploaded to - the account GitHub reports for the
    stored credential, so there is nothing for the caller to fill in.

    Progress payloads are ``(description, completed, total)`` publication steps, so
    the page can drive a progress bar (see :func:`~starbash.publish.github_publish.publish_site`).

    The two states only the user can resolve are *returned* rather than raised, so
    the page can guide them and simply run the job again: ``{"needs_sign_in": True}``
    when no credential is stored, and ``{"needs_install": True}`` when the App is
    missing.
    """
    from dataclasses import replace
    from datetime import UTC, datetime
    from pathlib import Path

    from starbash.analytics import analytics_start_span
    from starbash.app import Starbash
    from starbash.publish.credentials import GitHubCredentialStore
    from starbash.publish.github import GitHubPublisher
    from starbash.publish.github_publish import (
        APP_SLUG,
        CLIENT_ID,
        collect_site_files,
        credential_service,
        publish_site,
        refresh_if_needed,
        save_credential,
    )

    token.raise_if_cancelled()
    store = GitHubCredentialStore()
    credential = store.load()
    if credential is None:
        return {"needs_sign_in": True, "message": "Sign in to GitHub to publish the site."}

    report("Contacting GitHub...")
    service = credential_service(credential)
    credential = refresh_if_needed(service, credential, client_id=CLIENT_ID)
    owner = str(service.user()["login"])
    if credential.login != owner:
        # Remember the account name beside the token, so the Publish page can show
        # it straight away (and upgraded installs learn it on their next publish).
        save_credential(replace(credential, login=owner), store=store)
    token.raise_if_cancelled()
    if not service.app_is_installed(APP_SLUG):
        return {
            "needs_install": True,
            "message": "The Starbash GitHub App is not installed for this account yet.",
        }

    report("Generating report site...")
    site = ""
    with Starbash("gui.publish.github") as sb:
        site = str(GitHubPublisher(sb, github_username=owner).publish())
    token.raise_if_cancelled()

    site_path = Path(site)
    files = collect_site_files(site_path)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with analytics_start_span(name="github", op="upload"):
        result = publish_site(
            service,
            owner,
            site_path,
            files,
            message=f"Publish Starbash images ({timestamp})",
            require_app=False,
            on_step=lambda description, completed, total: report((description, completed, total)),
        )
    return {
        "site": site,
        "owner": result.owner,
        "pages_url": result.pages_url,
        "files": result.file_count,
        "message": (
            f"Published {result.file_count} files to {result.pages_url} ... "
            "it should be live in a few minutes."
        ),
    }
