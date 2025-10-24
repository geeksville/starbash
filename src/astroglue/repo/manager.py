"""
Manages the repository of processing recipes and configurations.
"""

from __future__ import annotations
import logging
from pathlib import Path

import tomlkit


repo_suffix = "astroglue.toml"


class Repo:
    """
    Represents a single astroglue repository."""

    def __init__(self, manager: RepoManager, url: str):
        """
        Initializes a Repo instance.

        Args:
            url: The URL to the repository (file or general http/https urls are acceptable).
        """
        self.manager = manager
        self.url = url
        self.path = self._resolve_path(url)
        self.config = self._load_config()
        self.manager.add_all_repos(self.config, base_path=self.path)

    def _resolve_path(self, url: str) -> Path | None:
        """
        Resolves the URL to a local file system path if it's a file URI.

        Args:
            url: The repository URL.

        Returns:
            A Path object if the URL is a local file, otherwise None.
        """
        if url.startswith("file://"):
            return Path(url[len("file://") :])
        return None

    def _load_config(self) -> dict:
        """
        Loads the repository's configuration file (e.g., repo.ag.toml).

        Returns:
            A dictionary containing the parsed configuration.
        """
        if self.path and self.path.is_dir():
            config_path = self.path / repo_suffix
            if config_path.is_file():
                logging.info(f"Loading repo config from {config_path}")
                with open(config_path, "r") as f:
                    return tomlkit.load(f)

        logging.warning(f"No {repo_suffix} found in {self.path}")
        return {}

    def get(self, key: str, default=None):
        """
        Gets a value from this repo's config for a given key.
        The key can be a dot-separated string for nested values.

        Args:
            key: The dot-separated key to search for (e.g., "repo.kind").
            default: The value to return if the key is not found.

        Returns:
            The found value or the default.
        """
        value = self.config
        for k in key.split("."):
            if not isinstance(value, dict):
                return default
            value = value.get(k)
        return value if value is not None else default


class RepoManager:
    """
    Manages the collection of astroglue repositories.

    This class is responsible for finding, loading, and providing an API
    for searching through known repositories defined in TOML configuration
    files (like appdefaults.ag.toml).
    """

    def __init__(self, app_defaults: str):
        """
        Initializes the RepoManager by loading the application default repos.
        """
        self.app_defaults = tomlkit.parse(app_defaults)
        self.repos = []
        self.add_all_repos(self.app_defaults)

    def add_all_repos(self, toml: dict, base_path: Path | None = None) -> None:
        # From appdefaults.ag.toml, repo.ref is a list of tables
        repo_refs = toml.get("repo", {}).get("ref", [])

        for ref in repo_refs:
            if "url" in ref:
                url = ref["url"]
            elif "dir" in ref:
                path = Path(ref["dir"])
                if base_path and not path.is_absolute():
                    # Resolve relative to the current TOML file's directory
                    path = (base_path / path).resolve()
                else:
                    # Expand ~ and resolve from CWD
                    path = path.expanduser().resolve()
                url = f"file://{path}"
            else:
                raise ValueError(f"Invalid repo reference: {ref}")
            self.add_repo(url)

    def add_repo(self, url: str) -> None:
        logging.info(f"Adding repo: {url}")
        self.repos.append(Repo(self, url))

    def get(self, key: str, default=None):
        """
        Searches for a key across all repositories and returns the first value found.
        The search is performed in reverse order of repository loading, so the
        most recently added repositories have precedence.

        Args:
            key: The dot-separated key to search for (e.g., "repo.kind").
            default: The value to return if the key is not found in any repo.

        Returns:
            The found value or the default.
        """
        # Iterate in reverse to give precedence to later-loaded repos
        for repo in reversed(self.repos):
            value = repo.get(key)
            if value is not None:
                return value

        return default
