"""
Manages the repository of processing recipes and configurations.
"""

from __future__ import annotations
import logging
from pathlib import Path
from importlib import resources
from typing import Any

import tomlkit
from tomlkit.toml_file import TOMLFile
from tomlkit.items import AoT
from multidict import MultiDict
from repo.repo import Repo


class RepoManager:
    """
    Manages the collection of starbash repositories.

    This class is responsible for finding, loading, and providing an API
    for searching through known repositories defined in TOML configuration
    files (like appdefaults.sb.toml).
    """

    def __init__(self):
        """
        Initializes the RepoManager by loading the application default repos.
        """
        self.repos = []

        # We expose the app default preferences as a special root repo with a private URL
        # root_repo = Repo(self, "pkg://starbash-defaults", config=app_defaults)
        # self.repos.append(root_repo)

        # Most users will just want to read from merged
        self.merged = MultiDict()

    @property
    def regular_repos(self) -> list[Repo]:
        "We exclude certain repo types (preferences, recipe) from the list of repos users care about."
        return [
            r
            for r in self.repos
            if r.kind() not in ("preferences") and not r.is_scheme("pkg")
        ]

    def add_repo(self, url: str) -> Repo:
        logging.debug(f"Adding repo: {url}")
        r = Repo(self, url)
        self.repos.append(r)

        # FIXME, generate the merged dict lazily
        self._add_merged(r)

        # if this new repo has sub-repos, add them too
        r.add_by_repo_refs()

        return r

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

        combined_config = self.merged
        logging.info("RepoManager Dump")
        for key, value in combined_config.items():
            # tomlkit.items() can return complex types (e.g., ArrayOfTables, Table)
            # For a debug dump, a simple string representation is usually sufficient.
            logging.info(f"  %s: %s", key, value)

    def _add_merged(self, repo: Repo) -> None:
        for key, value in repo.config.items():
            # if the toml object is an AoT type, monkey patch each element in the array instead
            if isinstance(value, AoT):
                for v in value:
                    setattr(v, "source", repo)
                else:
                    # We monkey patch source into any object that came from a repo, so that users can
                    # find the source repo (for attribution, URL relative resolution, whatever...)
                    setattr(value, "source", repo)

            self.merged.add(key, value)

    def __str__(self):
        lines = [f"RepoManager with {len(self.repos)} repositories:"]
        for i, repo in enumerate(self.repos):
            lines.append(f"  [{i}] {repo.url}")
        return "\n".join(lines)
