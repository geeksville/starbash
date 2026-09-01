"""Small GitHub API client used by the GitHub Pages publisher."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jinja2 import Environment

logger = logging.getLogger(__name__)


class GitHubError(RuntimeError):
    """A safe, user-facing GitHub API error without response credentials."""


class GitHubAuthenticationError(GitHubError):
    """The saved access token was rejected by GitHub."""


class GitHubTimeoutError(GitHubError):
    """A GitHub request timed out."""


GITHUB_REQUEST_ATTEMPTS = 3


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


class GitHubService:
    """GitHub REST operations needed by the publishing commands."""

    api = "https://api.github.com"
    api_version = "2026-03-10"

    def __init__(
        self,
        token: str | None = None,
        opener: Any = urllib.request.urlopen,
        refresh_token: str | None = None,
        client_id: str | None = None,
        on_token_refresh: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.token = token
        self.opener = opener
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.on_token_refresh = on_token_refresh
        self._refresh_lock = threading.Lock()

    @staticmethod
    def _json_response(response: Any) -> Any:
        body = response.read().decode("utf-8")
        # Some successful or conflict responses from GitHub, including an
        # already-enabled Pages site, have no response body.
        return json.loads(body) if body.strip() else {}

    @staticmethod
    def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        """Redact credentials and keep large blob bodies out of debug logs."""
        if payload is None:
            return None
        safe = dict(payload)
        if "content" in safe:
            content = safe["content"]
            safe["content"] = f"<redacted {len(content)} bytes>"
        return safe

    @classmethod
    def _safe_response(cls, value: Any) -> Any:
        """Redact authentication values before writing a response to debug logs."""
        if isinstance(value, dict):
            return {
                key: "<redacted>"
                if key in {"access_token", "device_code", "refresh_token", "token"}
                else cls._safe_response(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._safe_response(item) for item in value]
        return value

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        _retried_after_refresh: bool = False,
    ) -> dict[str, Any]:
        """Make a GitHub request, retrying transient timeouts."""
        for attempt in range(1, GITHUB_REQUEST_ATTEMPTS + 1):
            try:
                return self._request_once(
                    method, url, payload, _retried_after_refresh
                )
            except GitHubTimeoutError:
                if attempt == GITHUB_REQUEST_ATTEMPTS:
                    logger.warning(
                        "GitHub request timed out after %d attempts: %s %s",
                        GITHUB_REQUEST_ATTEMPTS,
                        method,
                        url,
                    )
                    raise
                logger.warning(
                    "GitHub request timed out; retrying (attempt %d/%d): %s %s",
                    attempt + 1,
                    GITHUB_REQUEST_ATTEMPTS,
                    method,
                    url,
                )
        raise AssertionError("unreachable")

    def _request_once(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        _retried_after_refresh: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "starbash",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request_token = self.token
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        logger.debug("GitHub request: %s %s params=%r", method, url, self._safe_payload(payload))
        try:
            with self.opener(request) as response:
                result = self._json_response(response)
                logger.debug(
                    "GitHub response: %s %s status=%s body=%r",
                    method,
                    url,
                    response.status,
                    self._safe_response(result),
                )
                return result
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            parsed_response: Any = None
            try:
                parsed_response = json.loads(response_body)
                response_body = repr(self._safe_response(parsed_response))
            except json.JSONDecodeError:
                response_body = response_body[:1000]
            logger.debug(
                "GitHub response: %s %s status=%s body=%r",
                method,
                url,
                exc.code,
                response_body,
            )
            if exc.code == 422 and isinstance(parsed_response, dict):
                message = parsed_response.get("message")
                if isinstance(message, str) and "timed out" in message.lower():
                    raise GitHubTimeoutError("GitHub request timed out") from exc
            if exc.code == 404:
                raise GitHubError("GitHub resource was not found") from exc
            if exc.code == 401:
                if self.refresh_token and self.client_id and not _retried_after_refresh:
                    with self._refresh_lock:
                        if self.token == request_token:
                            refreshed = self.refresh_access_token(self.client_id, self.refresh_token)
                            self.apply_token_response(refreshed)
                    return self._request(method, url, payload, _retried_after_refresh=True)
                raise GitHubAuthenticationError(
                    "GitHub rejected the access token; run 'sb publish github --login' again"
                ) from exc
            if exc.code == 403:
                raise GitHubError(
                    "GitHub rejected the request; check the OAuth token's permissions "
                    "and whether the request is rate-limited"
                ) from exc
            if exc.code == 409:
                raise GitHubError(
                    "GitHub cannot use the repository's Git database because it is empty; "
                    "the repository needs an initial commit"
                ) from exc
            raise GitHubError(f"GitHub API request failed ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.debug("GitHub request failed: %s %s error=%r", method, url, exc)
            if isinstance(exc, TimeoutError) or (
                isinstance(exc, urllib.error.URLError)
                and isinstance(exc.reason, TimeoutError)
            ):
                raise GitHubTimeoutError("GitHub request timed out") from exc
            raise GitHubError("Could not connect to GitHub") from exc

    def device_code(self, client_id: str, scope: str = "repo offline_access") -> DeviceCode:
        """Request a GitHub Device Flow code."""
        logger.debug("GitHub device-code request: client_id=%s scope=%s", client_id, scope)
        body = urllib.parse.urlencode({"client_id": client_id, "scope": scope}).encode()
        request = urllib.request.Request(
            "https://github.com/login/device/code",
            data=body,
            headers={"Accept": "application/json", "User-Agent": "starbash", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener(request) as response:
                value = self._json_response(response)
                logger.debug(
                    "GitHub device-code response: status=%s body=%r",
                    response.status,
                    self._safe_response(value),
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GitHubError("Could not start GitHub authentication") from exc
        if "error" in value:
            raise GitHubError("GitHub refused the authentication request")
        return DeviceCode(
            value["device_code"], value["user_code"], value["verification_uri"],
            int(value.get("interval", 5)), int(value["expires_in"]),
        )

    def poll_device_token(
        self, device: DeviceCode, client_id: str, sleeper: Any = time.sleep
    ) -> dict[str, Any]:
        """Poll until the user authorizes or GitHub returns a terminal error."""
        deadline = time.monotonic() + device.expires_in
        interval = device.interval
        while time.monotonic() < deadline:
            body = urllib.parse.urlencode({
                "client_id": client_id,
                "device_code": device.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }).encode()
            request = urllib.request.Request(
                "https://github.com/login/oauth/access_token", data=body,
                headers={"Accept": "application/json", "User-Agent": "starbash", "Content-Type": "application/x-www-form-urlencoded"}, method="POST",
            )
            try:
                with self.opener(request) as response:
                    value = self._json_response(response)
                    logger.debug(
                        "GitHub token response: status=%s body=%r",
                        response.status,
                        self._safe_response(value),
                    )
            except (urllib.error.URLError, TimeoutError) as exc:
                logger.debug("GitHub token request failed: %r", exc)
                raise GitHubError("Could not complete GitHub authentication") from exc
            if value.get("access_token"):
                return value
            error = value.get("error")
            if error == "authorization_pending":
                sleeper(interval)
                continue
            if error == "slow_down":
                interval += 5
                sleeper(interval)
                continue
            if error in {"expired_token", "access_denied"}:
                raise GitHubError("GitHub authentication was not completed")
            raise GitHubError("GitHub returned an unexpected authentication response")
        raise GitHubError("GitHub authentication timed out")

    def refresh_access_token(self, client_id: str, refresh_token: str) -> dict[str, Any]:
        """Rotate an expired access/refresh-token pair."""
        body = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode()
        request = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=body,
            headers={
                "Accept": "application/json",
                "User-Agent": "starbash",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self.opener(request) as response:
                value = self._json_response(response)
                logger.debug(
                    "GitHub token refresh response: status=%s body=%r",
                    response.status,
                    self._safe_response(value),
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GitHubError("Could not refresh GitHub authentication") from exc
        if value.get("access_token"):
            return value
        if value.get("error") == "bad_refresh_token":
            raise GitHubError(
                "The GitHub refresh token has expired; run 'sb publish github --login' again"
            )
        raise GitHubError("GitHub returned an unexpected token refresh response")

    def apply_token_response(self, value: dict[str, Any]) -> None:
        """Replace the in-memory token and persist the rotated credentials."""
        self.token = str(value["access_token"])
        self.refresh_token = (
            str(value["refresh_token"]) if value.get("refresh_token") else self.refresh_token
        )
        if self.on_token_refresh:
            self.on_token_refresh(value)

    def user(self) -> dict[str, Any]:
        return self._request("GET", f"{self.api}/user")

    def user_installations(self) -> list[dict[str, Any]]:
        """Return GitHub App installations visible to the authenticated user."""
        result = self._request("GET", f"{self.api}/user/installations?per_page=100")
        installations = result.get("installations", [])
        return [installation for installation in installations if isinstance(installation, dict)]

    def app_is_installed(self, app_slug: str) -> bool:
        """Return whether the authenticated user has installed the named GitHub App."""
        return any(
            installation.get("app_slug") == app_slug
            for installation in self.user_installations()
        )

    def repository(self, owner: str, name: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"{self.api}/repos/{owner}/{name}")
        except GitHubError as exc:
            if str(exc) == "GitHub resource was not found":
                return None
            raise

    def branch_exists(self, owner: str, name: str, branch: str) -> bool:
        """Return whether a branch ref exists, rather than using repository size."""
        try:
            self._request("GET", f"{self.api}/repos/{owner}/{name}/git/ref/heads/{branch}")
        except GitHubError as exc:
            if str(exc) in {
                "GitHub resource was not found",
                "GitHub cannot use the repository's Git database because it is empty; the repository needs an initial commit",
            }:
                return False
            raise
        return True

    def create_repository(self, name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.api}/user/repos",
            {
                "name": name,
                # note: markdown is not supported in the description field
                "description": "Semiautomatic (beta) image workflows by Starbash",
                "private": False,
                # we want to make main ourselves
                "auto_init": False,
            },
        )

    def bootstrap_repository(
        self, owner: str, name: str, pages_url: str, github_username: str
    ) -> dict[str, Any]:
        """Create an initial commit for an existing empty repository."""
        readme = resources.files("starbash").joinpath("templates/report/README.md.jinja")
        template = Environment().from_string(readme.read_text())
        rendered = template.render(
            pages_url=pages_url,
            github_username=github_username,
            repository_url=f"https://github.com/{owner}/{name}",
            repository_tree_url=f"https://github.com/{owner}/{name}/tree/gh-pages",
        )
        content = base64.b64encode(rendered.encode("utf-8")).decode("ascii")
        return self._request(
            "PUT",
            f"{self.api}/repos/{owner}/{name}/contents/README.md",
            {
                "message": "Initialize Starbash publishing repository",
                "content": content
            },
        )

    def create_blob(self, owner: str, name: str, content: bytes) -> str:
        """Create a Git blob."""
        encoded = base64.b64encode(content).decode("ascii")
        url = f"{self.api}/repos/{owner}/{name}/git/blobs"
        payload = {"content": encoded, "encoding": "base64"}
        return str(self._request("POST", url, payload)["sha"])

    def create_tree(self, owner: str, name: str, entries: list[dict[str, str]]) -> str:
        return str(self._request("POST", f"{self.api}/repos/{owner}/{name}/git/trees", {"tree": entries})["sha"])

    def create_commit(self, owner: str, name: str, message: str, tree: str) -> str:
        return str(self._request("POST", f"{self.api}/repos/{owner}/{name}/git/commits", {"message": message, "tree": tree})["sha"])

    def update_branch(self, owner: str, name: str, commit: str) -> None:
        url = f"{self.api}/repos/{owner}/{name}/git/refs/heads/gh-pages"
        try:
            self._request("PATCH", url, {"sha": commit, "force": True})
        except GitHubError as exc:
            if str(exc) not in {
                "GitHub resource was not found",
                "GitHub API request failed (422)",
            }:
                raise
            self._request(
                "POST",
                f"{self.api}/repos/{owner}/{name}/git/refs",
                {"ref": "refs/heads/gh-pages", "sha": commit},
            )

    def configure_pages(self, owner: str, name: str) -> dict[str, Any]:
        payload = {"source": {"branch": "gh-pages", "path": "/"}}
        url = f"{self.api}/repos/{owner}/{name}/pages"
        for attempt in range(3):
            try:
                return self._request("PUT", url, payload)
            except GitHubError as exc:
                if str(exc) in {
                    "GitHub API request failed (409)",
                    "GitHub API request failed (422)",
                }:
                    logger.info("GitHub Pages is already enabled; continuing with deployment wait.")
                    return {"status": "already-enabled"}
                if str(exc) != "GitHub resource was not found" or attempt == 2:
                    raise
                logger.info(
                    "GitHub Pages configuration is not ready yet; retrying in 5 seconds "
                    "(%d/3).",
                    attempt + 2,
                )
                time.sleep(5)
        raise AssertionError("GitHub Pages configuration retry loop did not return")


