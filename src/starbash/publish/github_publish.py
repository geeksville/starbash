"""Front-end-agnostic GitHub Pages publication.

Generating the site itself already lives in :mod:`starbash.publish.github`, but the
*sequence* that pushes it to GitHub - sign in, check the App installation, create the
``starbash-public`` repository, upload blobs, commit, publish - used to live inside the
``sb publish github`` command.  The desktop GUI needs exactly the same sequence, so it
lives here instead: this module imports no terminal, Rich or Qt code.  Callers pass a
small ``on_step`` callback for progress and decide for themselves how to talk to the
user (Rich panels + prompts in the CLI, a dialog in the GUI).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from starbash.publish.credentials import GitHubCredential, GitHubCredentialStore
from starbash.publish.github_service import DeviceCode, GitHubError, GitHubService

__all__ = [
    "APP_INSTALLATION_URL",
    "APP_SLUG",
    "CLIENT_ID",
    "MAX_BLOB_UPLOADS",
    "PUBLISH_REPOSITORY",
    "UPLOAD_PATH_BLACKLIST",
    "GitHubAppNotInstalledError",
    "PublishResult",
    "StepReporter",
    "collect_site_files",
    "credential_service",
    "finish_device_login",
    "pages_url_for",
    "publish_site",
    "refresh_if_needed",
    "save_credential",
    "upload_blobs",
]

#: Public OAuth client id of the Starbash GitHub App.
CLIENT_ID = "Iv23liewanBO4WT8No6v"
#: Slug of the Starbash GitHub App (used for installation checks and its install page).
APP_SLUG = "geeksville-starbash"
#: Where a user grants the App access to their repositories.
APP_INSTALLATION_URL = f"https://github.com/apps/{APP_SLUG}/installations/new"
#: The single repository Starbash publishes into.  It is always public because
#: GitHub Pages needs a public repository (or a paid plan) to serve a site.
PUBLISH_REPOSITORY = "starbash-public"
#: Path prefixes (relative to the site root) that must never be uploaded: the
#: ``Gemfile`` bundle serves Jekyll locally, and a stray credential file is secret.
UPLOAD_PATH_BLACKLIST = ("Gemfile", "github-auth.toml")
#: How many blob uploads run at once (GitHub is happy with a handful, not hundreds).
MAX_BLOB_UPLOADS = 4
#: How many ``on_step`` calls :func:`publish_site` makes, excluding one per file.
_FIXED_STEPS = 10


class GitHubAppNotInstalledError(GitHubError):
    """The Starbash GitHub App is not installed for the signed-in account."""


@dataclass(frozen=True)
class PublishResult:
    """What a completed publication produced."""

    #: The account the site was published to.
    owner: str
    #: The public URL GitHub Pages will serve the site from.
    pages_url: str
    #: How many files were uploaded.
    file_count: int


#: Reports one completed publication step: ``(description, completed, total)``.
StepReporter = Callable[[str, int, int], None]


def pages_url_for(owner: str, repository: str = PUBLISH_REPOSITORY) -> str:
    """Return the GitHub Pages URL a repository is served from."""
    return f"https://{owner}.github.io/{repository}/"


def credential_service(
    credential: GitHubCredential,
    *,
    client_id: str = CLIENT_ID,
    store: GitHubCredentialStore | None = None,
) -> GitHubService:
    """Create an authenticated service that persists any rotated token."""

    def persist_rotated(value: dict[str, Any]) -> None:
        """Save a rotated token, keeping the account name it belongs to."""
        rotated = GitHubCredential.from_token_response(value)
        credential_store.save(replace(rotated, login=credential.login))

    credential_store = store or GitHubCredentialStore()
    return GitHubService(
        credential.access_token,
        refresh_token=credential.refresh_token,
        client_id=client_id,
        on_token_refresh=persist_rotated,
    )


def refresh_if_needed(
    service: GitHubService,
    credential: GitHubCredential,
    *,
    client_id: str = CLIENT_ID,
) -> GitHubCredential:
    """Rotate an expired access token in place, when a refresh token allows it.

    Returns the credential that is now in effect: the rotated one when a refresh
    happened (already persisted by the service's ``on_token_refresh``), otherwise
    ``credential`` unchanged.  Callers that want to store anything beside the token
    (the account name, say) must save what they get back, not the stale argument.
    """
    if credential.needs_refresh() and credential.refresh_token:
        value = service.refresh_access_token(client_id, credential.refresh_token)
        service.apply_token_response(value)
        return replace(GitHubCredential.from_token_response(value), login=credential.login)
    return credential


def save_credential(
    credential: GitHubCredential, *, store: GitHubCredentialStore | None = None
) -> None:
    """Store the credential so later runs do not have to sign in again."""
    (store or GitHubCredentialStore()).save(credential)


def finish_device_login(
    service: GitHubService,
    device: DeviceCode,
    client_id: str = CLIENT_ID,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> GitHubCredential:
    """Wait for the user to authorize the device code and return the credential.

    The credential is deliberately *not* stored here: a caller may want to check the
    App installation (or confirm something with the user) before committing it.
    ``sleeper`` is injectable so the GUI can poll in small slices and abort promptly
    when its dialog is closed.

    Raises:
        GitHubError: GitHub refused, the code expired, or the user denied access.
    """
    token = service.poll_device_token(device, client_id, sleeper)
    return GitHubCredential.from_token_response(token)


def collect_site_files(
    site: Path, *, blacklist: tuple[str, ...] = UPLOAD_PATH_BLACKLIST
) -> list[Path]:
    """Return the uploadable files of a generated site, in a stable order.

    Git metadata, the Jekyll cache and any intermediate ``_site`` tree stay local;
    ``blacklist`` holds path prefixes (relative to ``site``) that must not be uploaded.
    """
    files: list[Path] = []
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or ".jekyll-cache" in path.parts or "_site" in path.parts:
            continue
        if path.relative_to(site).as_posix().startswith(blacklist):
            continue
        files.append(path)
    return sorted(files)


def upload_blobs(
    service: GitHubService,
    owner: str,
    site: Path,
    files: list[Path],
    *,
    repository: str = PUBLISH_REPOSITORY,
    max_workers: int = MAX_BLOB_UPLOADS,
    on_blob: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    """Upload ``files`` as independent Git blobs, a few at a time.

    Blob uploads are independent HTTP calls, so they run concurrently; each entry is
    appended as its upload finishes (tree entries are order-insensitive).  When
    ``on_blob`` is given it receives the uploaded file's site-relative path.
    """

    def upload(path: Path) -> tuple[str, str]:
        relative_path = path.relative_to(site).as_posix()
        blob = service.create_blob(owner, repository, path.read_bytes())
        return relative_path, blob

    entries: list[dict[str, str]] = []
    worker_count = min(max_workers, len(files)) or 1
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="github-blob") as executor:
        futures = {executor.submit(upload, path): path for path in files}
        for future in as_completed(futures):
            relative_path, blob = future.result()
            entries.append(
                {
                    "path": relative_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob,
                }
            )
            if on_blob is not None:
                on_blob(relative_path)

    return entries


def publish_site(
    service: GitHubService,
    owner: str,
    site: Path,
    files: list[Path],
    *,
    message: str,
    repository: str = PUBLISH_REPOSITORY,
    require_app: bool = True,
    on_step: StepReporter | None = None,
) -> PublishResult:
    """Upload a generated site and (re)configure GitHub Pages for it.

    Args:
        service: an authenticated service for ``owner``.
        owner: the account whose ``repository`` receives the site.
        site: the generated site's root directory (blob paths are relative to it).
        files: the files to upload, normally from :func:`collect_site_files`.
        message: the commit message.
        repository: the repository to publish into.
        require_app: check the App installation first.  A front end that has already
            guided the user through installation (the CLI does) passes ``False``.
        on_step: called after each step with ``(description, completed, total)``.

    Raises:
        GitHubAppNotInstalledError: when ``require_app`` is set and the App is missing.
        GitHubError: when GitHub rejects any part of the publication.
    """
    total = _FIXED_STEPS + len(files)
    completed = 0
    pages_url = pages_url_for(owner, repository)

    def step(description: str) -> None:
        nonlocal completed
        completed += 1
        if on_step is not None:
            on_step(description, completed, total)

    step(f"Authenticated as {owner}")
    if require_app and not service.app_is_installed(APP_SLUG):
        raise GitHubAppNotInstalledError(
            "The Starbash GitHub App is not installed for this account yet."
        )
    step("Checked the Starbash GitHub App")

    repository_info = service.repository(owner, repository)
    step(f"Checked the {repository} repository")
    if repository_info is None:
        service.create_repository(repository)
        step(f"Created the {repository} repository")
    else:
        step(f"Found the existing {repository} repository")

    if not service.branch_exists(owner, repository, "main"):
        service.bootstrap_repository(owner, repository, pages_url, owner)
        step("Initialized the repository")
    else:
        step("Repository is ready")

    entries = upload_blobs(
        service,
        owner,
        site,
        files,
        repository=repository,
        on_blob=lambda relative_path: step(f"Uploaded {relative_path}"),
    )
    tree = service.create_tree(owner, repository, entries)
    step("Created the Git tree")
    commit = service.create_commit(owner, repository, message, tree)
    step("Created the publication commit")
    service.update_branch(owner, repository, commit)
    step("Updated the gh-pages branch")
    service.configure_pages(owner, repository)
    step("Configured GitHub Pages")
    step("GitHub Pages deployment complete")

    return PublishResult(owner=owner, pages_url=pages_url, file_count=len(files))
