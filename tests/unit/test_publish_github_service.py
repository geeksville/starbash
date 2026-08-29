"""Tests for the GitHub publishing API client."""

import json

from starbash.publish.github_service import GitHubService


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
