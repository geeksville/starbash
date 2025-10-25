"""
Manages the repository of processing recipes and configurations.
"""

from __future__ import annotations
import logging
from pathlib import Path

import tomlkit
from tomlkit.items import AoT
from multidict import MultiDict


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
        self.config = self._load_config()
        self.manager.add_all_repos(self.config, self._resolve_path())

    def _resolve_path(self) -> Path:
        """
        Resolves the URL to a local file system path if it's a file URI.

        Args:
            url: The repository URL.

        Returns:
            A Path object if the URL is a local file, otherwise fail.
        """
        url = self.url
        if url.startswith("file://"):
            return Path(url[len("file://") :])

        raise RuntimeError("FIXME currently only file URLs are supported")

    def read(self, filepath: str) -> str:
        """
        Read a filepath relative to the base of this repo. Return the contents in a string.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The content of the file as a string.
        """
        base_path = self._resolve_path()
        target_path = (base_path / filepath).resolve()

        # Security check to prevent reading files outside the repo directory
        if base_path not in target_path.parents and target_path != base_path:
            raise PermissionError("Attempted to read file outside of repository")

        return target_path.read_text()

    def _load_config(self) -> dict:
        """
        Loads the repository's configuration file (e.g., repo.ag.toml).

        If the config file does not exist, it logs a warning and returns an empty dict.

        Returns:
            A dictionary containing the parsed configuration.
        """
        try:
            config_content = self.read(repo_suffix)
            logging.debug(f"Loading repo config from {repo_suffix}")
            return tomlkit.parse(config_content)
        except FileNotFoundError:
            logging.warning(f"No {repo_suffix} found")
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

    def dump(self):
        """
        Prints a detailed, multi-line description of the combined top-level keys
        and values from all repositories, using a MultiDict for aggregation.
        This is useful for debugging and inspecting the consolidated configuration.
        """
        logging.info("--- RepoManager Dump ---")
        combined_config = self.union()
        if not combined_config:
            logging.info(
                "No top-level configuration keys found across all repositories."
            )
            logging.info("--- End RepoManager Dump ---")
            return

        for key, value in combined_config.items():
            # tomlkit.items() can return complex types (e.g., ArrayOfTables, Table)
            # For a debug dump, a simple string representation is usually sufficient.
            logging.info(f"  {key}: {value}")
        logging.info("--- End RepoManager Dump ---")

    def union(self) -> MultiDict:
        """
        Merges the top-level keys from all repository configurations into a MultiDict.

        This method iterates through all loaded repositories in their original order
        and combines their top-level configuration keys. If a key exists in multiple
        repositories, all of its values will be present in the returned MultiDict.

        Returns:
            A MultiDict containing the union of all top-level keys.
        """
        merged_dict = MultiDict()
        for repo in self.repos:
            for key, value in repo.config.items():
                # if the toml object is an AoT type, monkey patch each element in the array instead
                if isinstance(value, AoT):
                    for v in value:
                        setattr(v, "source", repo)
                else:
                    # We monkey patch source into any object that came from a repo, so that users can
                    # find the source repo (for attribution, URL relative resolution, whatever...)
                    setattr(value, "source", repo)

                merged_dict.add(key, value)

        return merged_dict

    def __str__(self):
        lines = [f"RepoManager with {len(self.repos)} repositories:"]
        for i, repo in enumerate(self.repos):
            lines.append(f"  [{i}] {repo.url}")
        return "\n".join(lines)
