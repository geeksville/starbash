"""Tests for the GitHub publishing API client."""

import json
import urllib.error
import urllib.parse

import pytest

from starbash.publish.github_service import GitHubAuthenticationError, GitHubError, GitHubService


class FakeResponse:
    """Minimal response object accepted by ``GitHubService``."""

    status = 200

    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class ErrorResponse:
    """Context manager response used to raise an HTTP error from an opener."""

    def __init__(self, code: int, body: dict) -> None:
        self.code = code
        self.body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self.body


def http_error(code: int, body: dict) -> urllib.error.HTTPError:
    """Create an HTTP error with a response body."""
    error = urllib.error.HTTPError(
        "https://api.github.com/user",
        code,
        "error",
        hdrs=None,
        fp=None,
    )
    error.read = lambda: json.dumps(body).encode()  # type: ignore[method-assign]
    return error


def test_app_is_installed_checks_app_slug():
    requests = []

    def opener(request):
        requests.append(request)
        return FakeResponse(
            {
                "installations": [
                    {"app_slug": "another-app"},
                    {"app_slug": "geeksville-starbash"},
                ]
            }
        )

    service = GitHubService("token", opener=opener)

    assert service.app_is_installed("geeksville-starbash") is True
    assert requests[0].full_url == (
        "https://api.github.com/user/installations?per_page=100"
    )


def test_app_is_installed_is_false_when_app_is_missing():
    service = GitHubService(
        "token",
        opener=lambda request: FakeResponse({"installations": []}),
    )

    assert service.app_is_installed("geeksville-starbash") is False


def test_poll_device_token_returns_refresh_metadata():
    service = GitHubService(
        opener=lambda request: FakeResponse(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 28800,
                "refresh_token_expires_in": 15897600,
                "token_type": "bearer",
            }
        )
    )

    result = service.poll_device_token(
        type("Device", (), {"device_code": "device", "expires_in": 1, "interval": 0})(),
        "client",
        sleeper=lambda interval: None,
    )

    assert result["access_token"] == "new-access"
    assert result["refresh_token"] == "new-refresh"


def test_refresh_access_token_sends_rotating_refresh_token():
    requests = []

    def opener(request):
        requests.append(request)
        return FakeResponse(
            {
                "access_token": "new-access",
                "refresh_token": "rotated-refresh",
                "expires_in": 28800,
            }
        )

    service = GitHubService(opener=opener)
    result = service.refresh_access_token("client", "old-refresh")

    assert result["access_token"] == "new-access"
    assert urllib.parse.parse_qs(requests[0].data.decode()) == {
        "client_id": ["client"],
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh"],
    }


def test_request_refreshes_once_after_401_and_persists_new_token():
    calls = 0
    refreshed = []

    def opener(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http_error(401, {"message": "Bad credentials"})
        return FakeResponse({"login": "owner"})

    service = GitHubService(
        "old-access",
        refresh_token="old-refresh",
        client_id="client",
        opener=opener,
        on_token_refresh=refreshed.append,
    )
    service.refresh_access_token = lambda client_id, refresh_token: {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 28800,
    }

    assert service.user() == {"login": "owner"}
    assert service.token == "new-access"
    assert service.refresh_token == "new-refresh"
    assert refreshed == [{
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 28800,
    }]
    assert calls == 2


def test_request_raises_authentication_error_after_refresh_retry_fails():
    def opener(request):
        raise http_error(401, {"message": "Bad credentials"})

    service = GitHubService("access", opener=opener)

    with pytest.raises(GitHubAuthenticationError, match="publish github --login"):
        service.user()


def test_create_blob_retries_timeouts_up_to_three_attempts(caplog):
    """GitHub calls retry transient timeouts and warn about each retry."""
    attempts = 0

    def opener(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("timed out")
        return FakeResponse({"sha": "blob-sha"})

    service = GitHubService(opener=opener)

    with caplog.at_level("WARNING"):
        assert service.create_blob("owner", "repo", b"content") == "blob-sha"

    assert attempts == 3
    assert caplog.messages == [
        "GitHub request timed out; retrying (attempt 2/3): POST "
        "https://api.github.com/repos/owner/repo/git/blobs",
        "GitHub request timed out; retrying (attempt 3/3): POST "
        "https://api.github.com/repos/owner/repo/git/blobs",
    ]


def test_create_blob_stops_after_three_timeouts(caplog):
    """GitHub calls stop retrying after three timed-out attempts."""
    attempts = 0

    def opener(request):
        nonlocal attempts
        attempts += 1
        raise TimeoutError("timed out")

    service = GitHubService(opener=opener)

    with caplog.at_level("WARNING"), pytest.raises(GitHubError, match="timed out"):
        service.create_blob("owner", "repo", b"content")

    assert attempts == 3
    assert caplog.messages[-1] == (
        "GitHub request timed out after 3 attempts: POST "
        "https://api.github.com/repos/owner/repo/git/blobs"
    )


def test_create_blob_retries_transient_gateway_errors(caplog):
    """Blob uploads retry temporary gateway failures such as HTTP 502."""
    attempts = 0

    def opener(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise http_error(502, {"message": "Bad Gateway"})
        return FakeResponse({"sha": "blob-sha"})

    service = GitHubService(opener=opener)

    with caplog.at_level("WARNING"):
        assert service.create_blob("owner", "repo", b"content") == "blob-sha"

    assert attempts == 3
    assert caplog.messages == [
        "GitHub request failed transiently; retrying (attempt 2/3): POST "
        "https://api.github.com/repos/owner/repo/git/blobs",
        "GitHub request failed transiently; retrying (attempt 3/3): POST "
        "https://api.github.com/repos/owner/repo/git/blobs",
    ]


def test_create_tree_retries_github_timeout_responses(caplog):
    """GitHub timeout responses are retried for tree creation too."""
    attempts = 0

    def opener(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise http_error(
                422,
                {"message": "Sorry, your request timed out. It's likely too large."},
            )
        return FakeResponse({"sha": "tree-sha"})

    service = GitHubService(opener=opener)

    with caplog.at_level("WARNING"):
        assert service.create_tree("owner", "repo", []) == "tree-sha"

    assert attempts == 3
    assert len(caplog.records) == 2
