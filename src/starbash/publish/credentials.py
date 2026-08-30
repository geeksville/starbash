"""Credential stores used by the GitHub publishing commands."""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import tomlkit

from starbash.paths import get_user_config_dir

logger = logging.getLogger(__name__)

SERVICE_NAME = "starbash"
ACCOUNT_NAME = "github"
FALLBACK_FILENAME = "github-creds.toml"


@dataclass(frozen=True)
class GitHubCredential:
    """An OAuth access token and, when available, its refresh metadata."""

    access_token: str
    refresh_token: str | None = None
    access_token_expires_at: float | None = None
    refresh_token_expires_at: float | None = None
    token_type: str = "bearer"
    scope: str = ""

    @classmethod
    def from_token_response(cls, value: dict[str, Any]) -> GitHubCredential:
        """Build a credential from GitHub's token response."""
        now = time.time()
        expires_in = value.get("expires_in")
        refresh_expires_in = value.get("refresh_token_expires_in")
        return cls(
            access_token=str(value["access_token"]),
            refresh_token=str(value["refresh_token"]) if value.get("refresh_token") else None,
            access_token_expires_at=now + float(expires_in) if expires_in is not None else None,
            refresh_token_expires_at=(
                now + float(refresh_expires_in) if refresh_expires_in is not None else None
            ),
            token_type=str(value.get("token_type", "bearer")),
            scope=str(value.get("scope", "")),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GitHubCredential:
        """Build a credential from persisted data."""
        return cls(
            access_token=str(value["access_token"]),
            refresh_token=str(value["refresh_token"]) if value.get("refresh_token") else None,
            access_token_expires_at=(
                float(value["access_token_expires_at"])
                if value.get("access_token_expires_at") is not None
                else None
            ),
            refresh_token_expires_at=(
                float(value["refresh_token_expires_at"])
                if value.get("refresh_token_expires_at") is not None
                else None
            ),
            token_type=str(value.get("token_type", "bearer")),
            scope=str(value.get("scope", "")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return serializable credential fields."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_token_expires_at": self.access_token_expires_at,
            "refresh_token_expires_at": self.refresh_token_expires_at,
            "token_type": self.token_type,
            "scope": self.scope,
        }

    def needs_refresh(self, leeway: float = 60) -> bool:
        """Return whether the access token is expired or close to expiry."""
        return self.access_token_expires_at is not None and time.time() + leeway >= self.access_token_expires_at


class SimpleCredentialStore:
    """Store the GitHub token in a simple TOML file fallback."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_user_config_dir() / FALLBACK_FILENAME

    def load(self) -> GitHubCredential | None:
        """Return the saved token, if one exists."""
        if not self.path.exists():
            return None
        document = tomlkit.parse(self.path.read_text())
        github = document.get("github", {})
        if not isinstance(github, dict):
            return None
        token = github.get("access_token", github.get("token"))
        if not token:
            return None
        if "access_token" not in github:
            return GitHubCredential(str(token))
        try:
            return GitHubCredential.from_dict(dict(github))
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"Invalid GitHub credential in {self.path}") from exc

    def save(self, credential: GitHubCredential | str) -> None:
        """Save the token to the fallback TOML file."""
        if isinstance(credential, str):
            credential = GitHubCredential(credential)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        document = tomlkit.document()
        github = tomlkit.table()
        github["access_token"] = credential.access_token
        if credential.refresh_token is not None:
            github["refresh_token"] = credential.refresh_token
        if credential.access_token_expires_at is not None:
            github["access_token_expires_at"] = credential.access_token_expires_at
        if credential.refresh_token_expires_at is not None:
            github["refresh_token_expires_at"] = credential.refresh_token_expires_at
        github["token_type"] = credential.token_type
        github["scope"] = credential.scope
        document["github"] = github
        temporary.write_text(tomlkit.dumps(document))
        try:
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temporary, self.path)


class KeyringCredentialStore:
    """Store the GitHub token in the operating system credential manager."""

    def __init__(self, service_name: str = SERVICE_NAME, account_name: str = ACCOUNT_NAME) -> None:
        self.service_name = service_name
        self.account_name = account_name

    def load(self) -> GitHubCredential | None:
        """Return the token from keyring, if one exists."""
        value = keyring.get_password(self.service_name, self.account_name)
        if not value:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return GitHubCredential(value)
        try:
            return GitHubCredential.from_dict(parsed)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("Invalid GitHub credential in keyring") from exc

    def save(self, credential: GitHubCredential | str) -> None:
        """Save or replace the token in keyring."""
        if isinstance(credential, str):
            credential = GitHubCredential(credential)
        keyring.set_password(
            self.service_name,
            self.account_name,
            json.dumps(credential.as_dict()),
        )


class GitHubCredentialStore:
    """Prefer keyring storage and fall back to a simple TOML credential file."""

    def __init__(
        self,
        keyring_store: KeyringCredentialStore | None = None,
        simple_store: SimpleCredentialStore | None = None,
    ) -> None:
        self.keyring_store = keyring_store or KeyringCredentialStore()
        self.simple_store = simple_store or SimpleCredentialStore()

    def load(self) -> GitHubCredential | None:
        """Return the saved token, falling back if keyring is unavailable."""
        try:
            token = self.keyring_store.load()
        except Exception as exc:
            logger.warning(
                "Keyring unavailable (%s); falling back to %s.",
                type(exc).__name__,
                self.simple_store.path,
            )
            return self.simple_store.load()
        return token or self.simple_store.load()

    def save(self, credential: GitHubCredential | str) -> None:
        """Save the token to keyring, falling back if keyring is unavailable."""
        try:
            self.keyring_store.save(credential)
        except Exception as exc:
            logger.warning(
                "Keyring unavailable (%s); falling back to %s.",
                type(exc).__name__,
                self.simple_store.path,
            )
            self.simple_store.save(credential)
