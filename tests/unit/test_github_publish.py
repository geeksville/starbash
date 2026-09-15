"""Tests for the shared GitHub Pages publication logic."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from starbash.publish.credentials import GitHubCredential
from starbash.publish.github_publish import (
    GitHubAppNotInstalledError,
    collect_site_files,
    credential_service,
    finish_device_login,
    publish_site,
    refresh_if_needed,
    save_credential,
    upload_blobs,
)


def _ready_service() -> MagicMock:
    """Return a service mock for an account that is fully set up."""
    service = MagicMock()
    service.app_is_installed.return_value = True
    service.repository.return_value = {"name": "starbash-public"}
    service.branch_exists.return_value = True
    service.create_blob.return_value = "blob-sha"
    service.create_tree.return_value = "tree-sha"
    service.create_commit.return_value = "commit-sha"
    return service


def test_collect_site_files_skips_metadata_caches_and_blacklisted_prefixes(tmp_path):
    """Git data, Jekyll caches, intermediate builds and secret files stay local."""
    (tmp_path / "index.html").write_text("site")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "m31.jpg").write_bytes(b"jpg")
    (tmp_path / "README.md").write_text("readme")
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'")
    (tmp_path / "Gemfile.lock").write_text("lock")
    (tmp_path / "github-auth.toml").write_text("token = 'secret'")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git")
    (tmp_path / ".jekyll-cache").mkdir()
    (tmp_path / ".jekyll-cache" / "cache").write_text("cache")
    (tmp_path / "_site").mkdir()
    (tmp_path / "_site" / "stale.html").write_text("stale")

    files = collect_site_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "README.md",
        "images/m31.jpg",
        "index.html",
    ]


def test_collect_site_files_orders_files_the_same_on_every_platform(tmp_path):
    """The order is the site-relative posix path, not the platform's path ordering.

    Sorting the ``Path`` objects directly is case-*insensitive* on Windows, which
    reordered the site (and made the upload order differ per platform), so the
    case-sensitive posix path is what the sort key uses.
    """
    (tmp_path / "Zebra.txt").write_text("z")
    (tmp_path / "apple.txt").write_text("a")

    files = collect_site_files(tmp_path)

    assert [path.name for path in files] == ["Zebra.txt", "apple.txt"]


def test_upload_blobs_use_at_most_four_workers_and_keep_every_file(tmp_path):
    """Independent blob requests run concurrently, a few at a time."""
    files = []
    for index in range(6):
        path = tmp_path / f"image-{index}.fits"
        path.write_bytes(f"blob-{index}".encode())
        files.append(path)

    lock = threading.Lock()
    first_four_started = threading.Barrier(4)
    active = 0
    maximum_active = 0

    def create_blob(owner, name, content):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            if int(content.decode().split("-")[1]) < 4:
                first_four_started.wait(timeout=2)
            return content.decode()
        finally:
            with lock:
                active -= 1

    service = MagicMock()
    service.create_blob.side_effect = create_blob
    entries = upload_blobs(service, "owner", tmp_path, files)

    assert maximum_active == 4
    assert {entry["path"] for entry in entries} == {path.name for path in files}
    assert {entry["sha"] for entry in entries} == {f"blob-{index}" for index in range(6)}
    assert {entry["mode"] for entry in entries} == {"100644"}
    assert {entry["type"] for entry in entries} == {"blob"}


def test_upload_blobs_reports_each_uploaded_path(tmp_path):
    """The callback receives site-relative paths, even for nested files."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "m31.jpg").write_bytes(b"jpg")
    (tmp_path / "index.html").write_text("site")
    service = MagicMock(create_blob=MagicMock(return_value="sha"))

    seen: list[str] = []
    files = collect_site_files(tmp_path)
    upload_blobs(service, "owner", tmp_path, files, on_blob=seen.append)

    assert sorted(seen) == ["images/m31.jpg", "index.html"]


def test_publish_site_reports_every_step_in_order(tmp_path):
    """Every publication step is reported once, with a stable total."""
    files = []
    for index in range(3):
        path = tmp_path / f"image-{index}.fits"
        path.write_bytes(b"blob")
        files.append(path)
    service = _ready_service()
    steps: list[tuple[str, int, int]] = []

    result = publish_site(
        service,
        "owner",
        tmp_path,
        files,
        message="Publish Starbash images",
        on_step=lambda description, completed, total: steps.append((description, completed, total)),
    )

    descriptions = [description for description, _, _ in steps]
    assert descriptions[:5] == [
        "Authenticated as owner",
        "Checked the Starbash GitHub App",
        "Checked the starbash-public repository",
        "Found the existing starbash-public repository",
        "Repository is ready",
    ]
    assert descriptions[-5:] == [
        "Created the Git tree",
        "Created the publication commit",
        "Updated the gh-pages branch",
        "Configured GitHub Pages",
        "GitHub Pages deployment complete",
    ]
    assert sorted(d for d in descriptions if d.startswith("Uploaded ")) == sorted(
        f"Uploaded {path.name}" for path in files
    )
    assert [completed for _, completed, _ in steps] == list(range(1, len(steps) + 1))
    assert {total for _, _, total in steps} == {10 + len(files)}
    assert result.owner == "owner"
    assert result.pages_url == "https://owner.github.io/starbash-public/"
    assert result.file_count == 3


def test_publish_site_creates_a_missing_repository_and_bootstraps_it(tmp_path):
    """A first publication creates the repository and its initial commit."""
    (tmp_path / "index.html").write_text("site")
    files = collect_site_files(tmp_path)
    service = _ready_service()
    service.repository.return_value = None
    service.branch_exists.return_value = False
    descriptions: list[str] = []

    result = publish_site(
        service,
        "owner",
        tmp_path,
        files,
        message="message",
        on_step=lambda description, _completed, _total: descriptions.append(description),
    )

    service.create_repository.assert_called_once_with("starbash-public")
    service.bootstrap_repository.assert_called_once_with(
        "owner", "starbash-public", result.pages_url, "owner"
    )
    assert "Created the starbash-public repository" in descriptions
    assert "Initialized the repository" in descriptions
    service.configure_pages.assert_called_once_with("owner", "starbash-public")


def test_publish_site_requires_the_app_installation(tmp_path):
    """A missing App installation aborts before any repository work happens."""
    (tmp_path / "index.html").write_text("site")
    service = _ready_service()
    service.app_is_installed.return_value = False

    with pytest.raises(GitHubAppNotInstalledError, match="GitHub App"):
        publish_site(
            service,
            "owner",
            tmp_path,
            collect_site_files(tmp_path),
            message="message",
        )

    service.repository.assert_not_called()
    service.create_blob.assert_not_called()


def test_publish_site_can_skip_the_installation_check(tmp_path):
    """A front end that already guided the user through installing skips the check."""
    (tmp_path / "index.html").write_text("site")
    service = _ready_service()
    service.app_is_installed.return_value = False

    publish_site(
        service,
        "owner",
        tmp_path,
        collect_site_files(tmp_path),
        message="message",
        require_app=False,
    )

    service.app_is_installed.assert_not_called()
    service.configure_pages.assert_called_once_with("owner", "starbash-public")


def test_credential_service_persists_a_rotated_token():
    """The service hand-off callback stores whichever token GitHub returns.

    The account name is not part of a token response, so it has to be carried over
    from the credential being replaced - otherwise a routine refresh would erase it.
    """
    credential = GitHubCredential("old-token", refresh_token="refresh-token", login="octocat")
    store = MagicMock()
    with patch("starbash.publish.github_publish.GitHubService") as github_service:
        credential_service(credential, client_id="client", store=store)
        on_refresh = github_service.call_args.kwargs["on_token_refresh"]
        on_refresh({"access_token": "new-token", "refresh_token": "rotated"})

    assert github_service.call_args.args == ("old-token",)
    assert github_service.call_args.kwargs["client_id"] == "client"
    assert github_service.call_args.kwargs["refresh_token"] == "refresh-token"
    saved = store.save.call_args.args[0]
    assert saved.access_token == "new-token"
    assert saved.refresh_token == "rotated"
    assert saved.login == "octocat"


def test_finish_device_login_returns_a_credential_without_saving_it():
    """Device login hands back the credential; storing it is the caller's decision."""
    service = MagicMock()
    service.poll_device_token.return_value = {
        "access_token": "token",
        "refresh_token": "refresh",
        "expires_in": 3600,
    }
    device = MagicMock()
    sleeper = MagicMock()

    credential = finish_device_login(service, device, "client", sleeper=sleeper)

    service.poll_device_token.assert_called_once_with(device, "client", sleeper)
    assert credential.access_token == "token"
    assert credential.refresh_token == "refresh"
    assert not credential.needs_refresh()


def test_save_credential_uses_the_given_store():
    """An injected store replaces the keyring-backed default."""
    credential = GitHubCredential("token")
    store = MagicMock()

    save_credential(credential, store=store)

    store.save.assert_called_once_with(credential)


def test_a_credential_survives_a_round_trip_with_its_account_name():
    """The account name is stored beside the token, so a later run can show it."""
    credential = GitHubCredential("token", refresh_token="refresh", login="octocat")

    assert GitHubCredential.from_dict(credential.as_dict()) == credential


def test_the_fallback_store_keeps_the_account_name(tmp_path):
    """The TOML fallback persists the login too (a keyring may be unavailable)."""
    from starbash.publish.credentials import SimpleCredentialStore

    store = SimpleCredentialStore(tmp_path / "github-creds.toml")
    store.save(GitHubCredential("token", login="octocat"))

    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "token"
    assert loaded.login == "octocat"


def test_a_credential_written_before_account_names_loads_without_one(tmp_path):
    """Upgrading must not invalidate a token saved by an older Starbash."""
    from starbash.publish.credentials import SimpleCredentialStore

    path = tmp_path / "github-creds.toml"
    path.write_text('[github]\naccess_token = "token"\n')
    store = SimpleCredentialStore(path)

    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "token"
    assert loaded.login == ""


def test_refresh_if_needed_only_refreshes_an_expired_token():
    """A live token is left alone; an expired one is rotated in place.

    The returned credential is the one now in effect, so a caller can save the login
    beside it without resurrecting the expired token it passed in.
    """
    service = MagicMock()
    service.refresh_access_token.return_value = {"access_token": "fresh"}

    live = GitHubCredential("live", refresh_token="refresh", login="octocat")
    assert refresh_if_needed(service, live, client_id="client") is live
    service.refresh_access_token.assert_not_called()
    service.apply_token_response.assert_not_called()

    expired = GitHubCredential(
        "stale",
        refresh_token="refresh",
        access_token_expires_at=time.time() - 1,
        login="octocat",
    )
    refreshed = refresh_if_needed(service, expired, client_id="client")

    service.refresh_access_token.assert_called_once_with("client", "refresh")
    service.apply_token_response.assert_called_once_with({"access_token": "fresh"})
    assert refreshed.access_token == "fresh"
    assert refreshed.login == "octocat"


def test_refresh_if_needed_ignores_an_expired_token_without_a_refresh_token():
    """Without a refresh token there is nothing safe to do, so GitHub is not called."""
    service = MagicMock()
    expired = GitHubCredential("stale", access_token_expires_at=time.time() - 1)

    refresh_if_needed(service, expired, client_id="client")

    service.refresh_access_token.assert_not_called()
