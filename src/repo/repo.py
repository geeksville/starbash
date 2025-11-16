from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit
from tomlkit.items import AoT
from tomlkit.toml_document import TOMLDocument
from tomlkit.toml_file import TOMLFile

from .http_client import http_session

if TYPE_CHECKING:
    from .manager import RepoManager

repo_suffix = "starbash.toml"

REPO_REF = "repo-ref"


class Repo:
    """
    Represents a single starbash repository.
    """

    def __init__(self, url_or_path: str | Path):
        """Initialize a Repo instance.

        Args:
            url_or_path: Either a string URL (e.g. file://, pkg://, http://...) or a Path.
                If a Path is provided it will be converted to a file:// URL using its
                absolute, resolved form.
        """
        if isinstance(url_or_path, Path):
            # Always resolve to an absolute path to avoid ambiguity
            resolved = url_or_path.expanduser().resolve()
            url = f"file://{resolved}"
        else:
            url = str(url_or_path)

        self.url: str = url
        self.config: TOMLDocument = self._load_config()
        self._as_read = (
            self.config.as_string()
        )  # the contents of the toml as we originally read from disk

        self._monkey_patch()

    def _monkey_patch(self, o: Any | None = None) -> None:
        """Add a 'source' back-ptr to all child items in the config.

        so that users can find the source repo (for attribution, URL relative resolution, whatever...)
        """
        # base case - start us recursing
        if o is None:
            self._monkey_patch(self.config)
            return

        # We monkey patch source into any object that came from a repo,
        try:
            o.source = self

            # Recursively patch dict-like objects
            if isinstance(o, dict):
                for value in o.values():
                    self._monkey_patch(value)
            # Recursively patch list-like objects (including AoT)
            elif hasattr(o, "__iter__") and not isinstance(o, str | bytes):
                try:
                    for item in o:
                        self._monkey_patch(item)
                except TypeError:
                    # Not actually iterable, skip
                    pass
        except AttributeError:
            pass  # simple types like int, str, float, etc. can't have attributes set on them

    def __str__(self) -> str:
        """Return a concise one-line description of this repo.

        Example: "Repo(kind=recipe, local=True, url=file:///path/to/repo)"
        """
        return f"Repo(kind={self.kind()}, url={self.url})"

    __repr__ = __str__

    def kind(self, unknown_kind: str = "unknown") -> str:
        """
        Read-only attribute for the repository kind (e.g., "recipe", "data", etc.).

        Returns:
            The kind of the repository as a string.
        """
        c = self.get("repo.kind", unknown_kind)
        return str(c)

    def add_repo_ref(self, manager: RepoManager, dir: Path) -> Repo | None:
        """
        Adds a new repo-ref to this repository's configuration.
        if new returns the newly added Repo object, if already exists returns None"""

        # if dir is not absolute, we need to resolve it relative to the cwd
        if not dir.is_absolute():
            dir = (Path.cwd() / dir).resolve()

        # Add the ref to this repo
        aot = self.config.get(REPO_REF, None)
        if aot is None:
            aot = tomlkit.aot()
            self.config[REPO_REF] = aot  # add an empty AoT at the end of the file

        if type(aot) is not AoT:
            raise ValueError(f"repo-ref in {self.url} is not an array")

        for t in aot:
            if "dir" in t and t["dir"] == str(dir):
                logging.warning(f"Repo ref {dir} already exists - ignoring.")
                return None  # already exists

        ref = {"dir": str(dir)}
        aot.append(ref)

        # Also add the repo to the manager
        return self.add_from_ref(manager, ref)

    def write_config(self) -> None:
        """
        Writes the current (possibly modified) configuration back to the repository's config file.

        Raises:
            ValueError: If the repository is not a local file repository.
        """
        base_path = self.get_path()
        if base_path is None:
            raise ValueError("Cannot resolve path for non-local repository")

        config_path = base_path / repo_suffix
        if self.config.as_string() == self._as_read:
            logging.debug(f"Config unchanged, not writing: {config_path}")
        else:
            # FIXME, be more careful to write the file atomically (by writing to a temp file and renaming)
            TOMLFile(config_path).write(self.config)
            logging.debug(f"Wrote config to {config_path}")

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

    def add_from_ref(self, manager: RepoManager, ref: dict) -> Repo:
        """
        Adds a repository based on a repo-ref dictionary.
        """
        if "url" in ref:
            url = ref["url"]
        elif "dir" in ref:
            # FIXME don't allow ~ or .. in file paths for security reasons?
            if self.is_scheme("file"):
                path = Path(ref["dir"])
                base_path = self.get_path()

                if base_path and not path.is_absolute():
                    # Resolve relative to the current TOML file's directory
                    path = (base_path / path).resolve()
                else:
                    # Expand ~ and resolve from CWD
                    path = path.expanduser().resolve()
                url = f"file://{path}"
            else:
                # construct an URL relative to this repo's URL
                url = self.url.rstrip("/") + "/" + ref["dir"].lstrip("/")
        else:
            raise ValueError(f"Invalid repo reference: {ref}")
        return manager.add_repo(url)

    def add_by_repo_refs(self, manager: RepoManager) -> None:
        """Add all repos mentioned by repo-refs in this repo's config."""
        repo_refs = self.config.get(REPO_REF, [])

        for ref in repo_refs:
            self.add_from_ref(manager, ref)

    def resolve_path(self, filepath: str) -> Path:
        """
        Resolve a filepath relative to the base of this repo.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The resolved Path object.
        """
        base_path = self.get_path()
        if base_path is None:
            raise ValueError("Cannot resolve filepaths for non-local repositories")
        target_path = (base_path / filepath).resolve()

        # Security check to prevent accessing files outside the repo directory.
        # FIXME SECURITY - temporarily disabled because I want to let file urls say things like ~/foo.
        # it would false trigger if user homedir path has a symlink in it (such as /home -> /var/home)
        #   base_path = PosixPath('/home/kevinh/.config/starbash')                   │                                                                                          │
        #   filepath = 'starbash.toml'                                              │                                                                                          │
        #   self = <repr-error 'maximum recursion depth exceeded'>              │                                                                                          │
        #   target_path = PosixPath('/var/home/kevinh/.config/starbash/starbash.toml')
        #
        # if base_path not in target_path.parents and target_path != base_path:
        #    raise PermissionError("Attempted to access file outside of repository")

        return target_path

    def _read_file(self, filepath: str) -> str:
        """
        Read a filepath relative to the base of this repo. Return the contents in a string.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The content of the file as a string.
        """
        target_path = self.resolve_path(filepath)

        return target_path.read_text()

    def _read_http(self, filepath: str) -> str:
        """
        Read a resource from an HTTP(S) URL.

        Args:
            filepath: Path within the base resource directory for this repo.

        Returns:
            The content of the resource as a string.

        Raises:
            ValueError: If the HTTP request fails.
        """
        # Construct the full URL by joining the base URL with the filepath
        url = self.url.rstrip("/") + "/" + filepath.lstrip("/")

        try:
            response = http_session.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.text
        except Exception as e:
            raise ValueError(f"Failed to read {url}: {e}") from e

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

    def _load_config(self) -> tomlkit.TOMLDocument:
        """
        Loads the repository's configuration file (e.g., repo.sb.toml).

        If the config file does not exist, it logs a warning and returns an empty dict.

        Returns:
            A dictionary containing the parsed configuration.
        """
        try:
            config_content = self.read(repo_suffix)
            logging.debug(f"Loading repo config from {repo_suffix}")
            return tomlkit.parse(config_content)
        except FileNotFoundError:
            logging.debug(
                f"No {repo_suffix} found"
            )  # we currently make it optional to have the config file at root
            return tomlkit.TOMLDocument()  # empty placeholder

    def read(self, filepath: str) -> str:
        """
        Read a filepath relative to the base of this repo. Return the contents in a string.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The content of the file as a string.
        """
        if self.is_scheme("file"):
            return self._read_file(filepath)
        elif self.is_scheme("pkg"):
            return self._read_resource(filepath)
        elif self.is_scheme("http") or self.is_scheme("https"):
            return self._read_http(filepath)
        else:
            raise ValueError(f"Unsupported URL scheme for repo: {self.url}")

    def get(self, key: str, default: Any | None = None) -> Any | None:
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

    def set(self, key: str, value: Any) -> None:
        """
        Sets a value in this repo's config for a given key.
        The key can be a dot-separated string for nested values.
        Creates nested Table structures as needed.

        Args:
            key: The dot-separated key to set (e.g., "repo.kind").
            value: The value to set.

        Example:
            repo.set("repo.kind", "preferences")
            repo.set("user.name", "John Doe")
        """
        keys = key.split(".")
        current: Any = self.config

        # Navigate/create nested structure for all keys except the last
        for k in keys[:-1]:
            if k not in current:
                # Create a new nested table
                current[k] = tomlkit.table()
            elif not isinstance(current[k], dict):
                # Overwrite non-dict value with a table
                current[k] = tomlkit.table()
            current = current[k]

        # Set the final value
        current[keys[-1]] = value
