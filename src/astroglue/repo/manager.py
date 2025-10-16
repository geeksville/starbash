"""
Manages the repository of processing recipes and configurations.
"""

import logging
from pathlib import Path

import tomlkit


class Repo:
    """
    Represents a single astroglue repository."""

    def __init__(self, url: str):
        """
        Initializes a Repo instance.

        Args:
            url: The URL or path to the repository. Can be a local path
                 (e.g., 'file:///path/to/repo') or a remote URL.
        """
        self.url = url
        self.path = self._resolve_path(url)
        self.config = self._load_config()

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
            config_path = self.path / "repo.ag.toml"
            if config_path.is_file():
                logging.info(f"Loading repo config from {config_path}")
                with open(config_path, "r") as f:
                    return tomlkit.parse(f.read())
            else:
                logging.warning(f"No repo.ag.toml found in {self.path}")
        return {}


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

        # From appdefaults.ag.toml, repo.ref is a list of tables
        repo_refs = self.app_defaults.get("repo", {}).get("ref", [])

        self.repos = []
        for ref in repo_refs:
            if "url" in ref:
                url = ref["url"]
            elif "file" in ref:
                # Expand ~, resolve to an absolute path, and convert to a file URI
                path = Path(ref["file"]).expanduser().resolve()
                url = f"file://{path}"
            else:
                raise ValueError(f"Invalid repo reference: {ref}")
            self.add_repo(url)

    def add_repo(self, url: str):
        logging.info(f"Adding repo: {url}")
        self.repos.append(Repo(url))

    def search(self):
        """Provides an API for searching known repos."""
        # Placeholder for future implementation
        pass
