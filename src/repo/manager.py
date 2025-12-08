"""
Manages the repository of processing recipes and configurations.
"""

# pyright: reportImportCycles=false
# The circular dependency between manager.py and repo.py is properly handled
# using TYPE_CHECKING and local imports where needed.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from multidict import MultiDict

if TYPE_CHECKING:
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
        self.repos: list[Repo] = []

        # We expose the app default preferences as a special root repo with a private URL
        # root_repo = Repo(self, "pkg://starbash-defaults", config=app_defaults)
        # self.repos.append(root_repo)

        # Most users will just want to read from merged
        self.merged: MultiDict[Any] = MultiDict()

    @property
    def regular_repos(self) -> list[Repo]:
        "We exclude certain repo types (preferences, recipe) from the list of repos users care about."
        return [
            r
            for r in self.repos
            if r.kind() not in ["preferences", "recipe"] and not r.is_scheme("pkg")
        ]

    def add_repo(self, url: str) -> Repo:
        from repo.repo import Repo  # Local import to avoid circular dependency

        logging.debug(f"Adding repo: {url}")
        r = Repo(url)
        self.repos.append(r)

        # FIXME, generate the merged dict lazily
        self._add_merged(r)

        # if this new repo has sub-repos, add them too
        r.add_by_repo_refs(self)

        return r

    def get_repo_by_url(self, url: str) -> Repo | None:
        """
        Retrieves a repository by its URL.

        Args:
            url: The URL of the repository to retrieve.

        Returns:
            The Repo instance with the matching URL, or None if not found.
        """
        for repo in self.repos:
            if repo.url == url:
                return repo
        return None

    def get_repo_by_kind(self, kind: str) -> Repo | None:
        """
        Retrieves the first repository matching the specified kind.

        Args:
            kind: The kind of repository to search for (e.g., "recipe", "preferences").

        Returns:
            The first Repo instance matching the kind, or None if not found.
        """
        for repo in self.repos:
            if repo.kind() == kind:
                return repo
        return None

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
            logging.info("  %s: %s", key, value)

    def _add_merged(self, repo: Repo) -> None:
        for key, value in repo.config.items():
            self.merged.add(key, value)

    def __str__(self):
        lines = [f"RepoManager with {len(self.repos)} repositories:"]
        for i, repo in enumerate(self.repos):
            lines.append(f"  [{i}] {repo.url}")
        return "\n".join(lines)
