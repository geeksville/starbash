"""
Manages the repository of processing recipes and configurations.
"""

from __future__ import annotations
import logging
from pathlib import Path
from importlib import resources

import tomlkit
from tomlkit.items import AoT
from multidict import MultiDict


repo_suffix = "starbash.toml"


class Repo:
    """
    Represents a single starbash repository."""

    def __init__(self, manager: RepoManager, url: str):
        """
        Initializes a Repo instance.

        Args:
            url: The URL to the repository (file or general http/https urls are acceptable).
        """
        self.manager = manager
        self.url = url
        self.config = self._load_config()

    def __str__(self) -> str:
        """Return a concise one-line description of this repo.

        Example: "Repo(kind=recipe, local=True, url=file:///path/to/repo)"
        """
        return f"Repo(kind={self.kind}, url={self.url})"

    __repr__ = __str__

    @property
    def kind(self) -> str:
        """
        Read-only attribute for the repository kind (e.g., "recipe", "data", etc.).

        Returns:
            The kind of the repository as a string.
        """
        return str(self.get("repo.kind", "unknown"))

    def is_scheme(self, scheme: str = "file") -> bool:
        """
        Read-only attribute indicating whether the repository URL points to a
        local file system path (file:// scheme).

        Returns:
            bool: True if the URL is a local file path, False otherwise.
        """
        return self.url.startswith(f"{scheme}://")

    def get_path(self) -> Path | None:
        """
        Resolves the URL to a local file system path if it's a file URI.

        Args:
            url: The repository URL.

        Returns:
            A Path object if the URL is a local file, otherwise None.
        """
        if self.is_scheme("file"):
            return Path(self.url[len("file://") :])

        return None

    def _read_file(self, filepath: str) -> str:
        """
        Read a filepath relative to the base of this repo. Return the contents in a string.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The content of the file as a string.
        """
        base_path = self.get_path()
        if base_path is None:
            raise ValueError("Cannot read files from non-local repositories")
        target_path = (base_path / filepath).resolve()

        # Security check to prevent reading files outside the repo directory
        if base_path not in target_path.parents and target_path != base_path:
            raise PermissionError("Attempted to read file outside of repository")

        return target_path.read_text()

    def _read_resource(self, filepath: str) -> str:
        """
        Read a resource from the installed starbash package using a pkg:// URL.

        Assumptions (simplified per project constraints):
        - All pkg URLs point somewhere inside the already-imported 'starbash' package.
        - The URL is treated as a path relative to the starbash package root.

        Examples:
            url: pkg://defaults   + filepath: "starbash.toml"
              -> reads starbash/defaults/starbash.toml

        Args:
            filepath: Path within the base resource directory for this repo.

        Returns:
            The content of the resource as a string (UTF-8).
        """
        # Path portion after pkg://, interpreted relative to the 'starbash' package
        subpath = self.url[len("pkg://") :].strip("/")

        res = resources.files("starbash").joinpath(subpath).joinpath(filepath)
        return res.read_text()

    def _load_config(self) -> dict:
        """
        Loads the repository's configuration file (e.g., repo.sb.toml).

        If the config file does not exist, it logs a warning and returns an empty dict.

        Returns:
            A dictionary containing the parsed configuration.
        """
        try:
            if self.is_scheme("file"):
                config_content = self._read_file(repo_suffix)
            elif self.is_scheme("pkg"):
                config_content = self._read_resource(repo_suffix)
            else:
                raise ValueError(f"Unsupported URL scheme for repo: {self.url}")
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

    def add_all_repos(self, toml: dict, base_path: Path | None = None) -> None:
        # From appdefaults.sb.toml, repo.ref is a list of tables
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
        logging.debug(f"Adding repo: {url}")
        r = Repo(self, url)
        self.repos.append(r)

        # FIXME, generate the merged dict lazily
        self._add_merged(r)

        # if this new repo has sub-repos, add them too
        self.add_all_repos(r.config, r.get_path())

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
