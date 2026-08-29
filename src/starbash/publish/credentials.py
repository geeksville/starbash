"""Credential stores used by the GitHub publishing commands."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import keyring
import tomlkit

from starbash.paths import get_user_config_dir

logger = logging.getLogger(__name__)

SERVICE_NAME = "starbash"
ACCOUNT_NAME = "github"
FALLBACK_FILENAME = "github-creds.toml"


class SimpleCredentialStore:
    """Store the GitHub token in a simple TOML file fallback."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_user_config_dir() / FALLBACK_FILENAME

    def load(self) -> str | None:
        """Return the saved token, if one exists."""
        if not self.path.exists():
            return None
        document = tomlkit.parse(self.path.read_text())
        github = document.get("github", {})
        token = github.get("token") if isinstance(github, dict) else None
        return str(token) if token else None

    def save(self, token: str) -> None:
        """Save the token to the fallback TOML file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        document = tomlkit.document()
        github = tomlkit.table()
        github["token"] = token
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

    def load(self) -> str | None:
        """Return the token from keyring, if one exists."""
        return keyring.get_password(self.service_name, self.account_name)

    def save(self, token: str) -> None:
        """Save or replace the token in keyring."""
        keyring.set_password(self.service_name, self.account_name, token)


class GitHubCredentialStore:
    """Prefer keyring storage and fall back to a simple TOML credential file."""

    def __init__(
        self,
        keyring_store: KeyringCredentialStore | None = None,
        simple_store: SimpleCredentialStore | None = None,
    ) -> None:
        self.keyring_store = keyring_store or KeyringCredentialStore()
        self.simple_store = simple_store or SimpleCredentialStore()

    def load(self) -> str | None:
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

    def save(self, token: str) -> None:
        """Save the token to keyring, falling back if keyring is unavailable."""
        try:
            self.keyring_store.save(token)
        except Exception as exc:
            logger.warning(
                "Keyring unavailable (%s); falling back to %s.",
                type(exc).__name__,
                self.simple_store.path,
            )
            self.simple_store.save(token)
