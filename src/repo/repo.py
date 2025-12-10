from __future__ import annotations

import logging
from collections.abc import MutableMapping
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

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

    def __init__(self, url_or_path: str | Path, default_toml: TOMLDocument | None = None):
        """Initialize a Repo instance.

        Args:
            url_or_path: Either a string URL (e.g. file://, pkg://, http://...) or a Path.
                If a Path is provided it will be converted to a file:// URL using its
                absolute, resolved form.

        Note:
            If the URL/path ends with .toml, it's treated as a direct TOML file.
            Otherwise, it's treated as a directory containing a starbash.toml file.

        Import Resolution:
            After loading the TOML config, this constructor processes any 'import' keys
            found in the configuration. Import syntax:

            [import]
            node = "some.dotted.path"  # required: which node to import
            file = "path/to/file.toml"  # optional: source file (default: current file)
            repo = "url_or_path"        # optional: source repo (default: current repo)

            The import key is replaced with the contents of the referenced node.
            Files are cached during import resolution to avoid redundant reads.
        """
        if isinstance(url_or_path, Path):
            # Always resolve to an absolute path to avoid ambiguity
            resolved = url_or_path.expanduser().resolve()
            url = f"file://{resolved}"
        else:
            url = str(url_or_path)

        self.url: str = url
        self._import_cache: dict[str, TOMLDocument] = {}  # Cache for imported files
        self.config: TOMLDocument = self._load_config(default_toml)
        self._as_read = (
            self.config.as_string()
        )  # the contents of the toml as we originally read from disk

        self._monkey_patch()
        self._resolve_imports()

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

    def _resolve_imports_in_doc(self, doc: TOMLDocument) -> None:
        """Helper to resolve imports in a standalone TOML document."""
        self._resolve_imports(doc, None, None)

    def _resolve_imports(
        self, o: Any | None = None, parent: dict | None = None, key: str | None = None
    ) -> None:
        """Recursively resolve 'import' keys in the TOML structure.

        Searches through the config dictionary tree looking for tables with an 'import' key.
        When found, loads the referenced node from the specified file/repo and replaces
        the entire table containing the import key with the imported content.

        Args:
            o: The current object being processed (None = start at root config)
            parent: Parent dict containing the current object
            key: Key in parent dict that references the current object

        Import table structure:
            [import]
            node = "some.dotted.path"  # required: which node to import
            file = "path/to/file.toml"  # optional: relative or absolute path
            repo = "url_or_path"        # optional: repo URL or path

        Raises:
            ValueError: If import is malformed or referenced content not found
        """
        # Base case - start recursion at root
        if o is None:
            self._resolve_imports(self.config, None, None)
            return

        # Check if this is a dict with an 'import' key
        if isinstance(o, dict):
            if "import" in o:
                # Found an import directive - resolve it
                import_spec = o["import"]
                if not isinstance(import_spec, dict):
                    raise ValueError(
                        f"Import specification must be a table, got {type(import_spec)}"
                    )

                # Extract import parameters
                node_path = import_spec.get("node")
                if not node_path:
                    raise ValueError("Import must specify a 'node' key")

                file_path = import_spec.get("file")
                repo_spec = import_spec.get("repo")

                # Resolve the imported content
                imported_content = self._resolve_import_node(node_path, file_path, repo_spec)

                # Replace the entire parent table with the imported content
                if parent is not None and key is not None:
                    parent[key] = imported_content
                    # Monkey patch the imported content to indicate its source
                    self._monkey_patch(parent[key])
                else:
                    # Can't replace root config with an import
                    raise ValueError("Cannot use import at the root level of config")

                # Don't recurse into the import spec - we've replaced it
                return

            # Not an import table, recurse into children
            # We need to iterate over a copy because we might modify the dict
            for k, v in list(o.items()):
                self._resolve_imports(v, o, k)

        # Recursively process list-like objects (including AoT)
        elif hasattr(o, "__iter__") and not isinstance(o, str | bytes):
            try:
                # For lists, we need to iterate and process each item
                # We can't easily replace items in tomlkit AoT structures,
                # so we recurse into each item which should be a dict
                for item in o:
                    # Each item in an AoT is a table (dict)
                    if isinstance(item, dict):
                        # Check for import at the table level
                        if "import" in item:
                            import_spec = item["import"]
                            if not isinstance(import_spec, dict):
                                raise ValueError(
                                    f"Import specification must be a table, got {type(import_spec)}"
                                )
                            node_path = import_spec.get("node")
                            if not node_path:
                                raise ValueError("Import must specify a 'node' key")
                            file_path = import_spec.get("file")
                            repo_spec = import_spec.get("repo")

                            # Get imported content
                            imported_content = self._resolve_import_node(
                                node_path, file_path, repo_spec
                            )

                            # Merge imported content into this item (preserving other keys)
                            # First remove the import key
                            del item["import"]
                            # Then merge in the imported content
                            if isinstance(imported_content, dict):
                                for k, v in imported_content.items():
                                    if k not in item:  # Don't override existing keys
                                        item[k] = v
                            self._monkey_patch(item)
                        else:
                            # No import, just recurse normally
                            self._resolve_imports(item, o, None)
            except TypeError:
                # Not actually iterable, skip
                pass

    def _resolve_import_node(
        self, node_path: str, file_path: str | None, repo_spec: str | None
    ) -> Any:
        """Resolve and return the content of an imported node.

        Args:
            node_path: Dot-separated path to the node (e.g., "recipe.stage.light")
            file_path: Optional path to TOML file (relative or absolute)
            repo_spec: Optional repo URL or path

        Returns:
            The imported content (deep copy to avoid reference issues)

        Raises:
            ValueError: If the import cannot be resolved
        """
        import copy

        # Determine which repo to use
        if repo_spec:
            # Import from a different repo - create a temporary repo instance
            source_repo = Repo(repo_spec)
        else:
            # Import from current repo
            source_repo = self

        # Determine which file to load
        if file_path:
            # Load a different TOML file from the source repo
            cache_key = f"{source_repo.url}::{file_path}"

            if cache_key not in self._import_cache:
                # Load and parse the TOML file
                toml_content = source_repo.read(file_path)
                parsed_doc = tomlkit.parse(toml_content)
                # Process imports in the cached file recursively
                self._resolve_imports_in_doc(parsed_doc)
                self._import_cache[cache_key] = parsed_doc

            source_doc = self._import_cache[cache_key]
        else:
            # Use the current file's config
            source_doc = source_repo.config

        # Navigate to the specified node
        current = source_doc
        for key in node_path.split("."):
            if not isinstance(current, dict):
                raise ValueError(f"Cannot navigate to '{key}' in path '{node_path}' - not a dict")
            if key not in current:
                raise ValueError(
                    f"Node '{key}' not found in path '{node_path}' while resolving import"
                )
            current = current[key]

        # Return a deep copy to avoid reference issues
        # Note: tomlkit objects need special handling for deep copy
        return copy.deepcopy(current)

    def __str__(self) -> str:
        """Return a concise one-line description of this repo.

        Example: "Repo(kind=recipe, local=True, url=file:///path/to/repo)"
        """
        return f"Repo(kind={self.kind()}, url={self.url})"

    __repr__ = __str__

    def __deepcopy__(self, memo):
        # Supress deepcopy because users almost certainly don't want to deepcopy repos
        return self

    def kind(self, unknown_kind: str = "unknown") -> str:
        """
        Read-only attribute for the repository kind (e.g., "recipe", "data", etc.).

        Returns:
            The kind of the repository as a string.
        """
        c = self.get("repo.kind", unknown_kind)
        return str(c)

    @property
    def config_url(self) -> str:
        """
        Returns the URL to the configuration file for this repository.

        For direct .toml file URLs, returns the URL as-is.
        For directory URLs, appends '/starbash.toml' to the URL.

        Returns:
            The complete URL to the starbash.toml configuration file.
        """
        if self._is_direct_toml_file():
            return self.url
        return f"{self.url.rstrip('/')}/{repo_suffix}"

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
        if not self.is_scheme("file"):
            raise ValueError("Cannot write config for non-local repository")

        if self._is_direct_toml_file():
            config_path = Path(self.url[len("file://") :])
        else:
            base_path = self.get_path()
            if base_path is None:
                raise ValueError("Cannot resolve path for non-local repository")
            config_path = base_path / repo_suffix

        if self.config.as_string() == self._as_read:
            logging.debug(f"Config unchanged, not writing: {config_path}")
        else:
            # FIXME, be more careful to write the file atomically (by writing to a temp file and renaming)
            # create the output directory if it doesn't exist
            config_path.parent.mkdir(parents=True, exist_ok=True)
            TOMLFile(config_path).write(self.config)
            logging.debug(f"Wrote config to {config_path}")

    def _is_direct_toml_file(self) -> bool:
        """
        Check if the URL points directly to a .toml file.

        Returns:
            bool: True if the URL ends with .toml, False otherwise.
        """
        return self.url.endswith(".toml")

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

        For directory URLs, returns the directory path.
        For .toml file URLs, returns the parent directory path.

        Returns:
            A Path object if the URL is a local file, otherwise None.
        """
        if self.is_scheme("file"):
            path = Path(self.url[len("file://") :])
            if self._is_direct_toml_file():
                return path.parent
            return path

        return None

    def add_from_ref(self, manager: RepoManager, ref: dict) -> Repo | None:
        """
        Adds a repository based on a repo-ref dictionary.
        """
        url: str | None = None  # assume failure

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

        if url:
            return manager.add_repo(url)
        else:
            logging.warning("Skipping empty repo reference")
            return None

    def add_by_repo_refs(self, manager: RepoManager) -> None:
        """Add all repos mentioned by repo-refs in this repo's config."""
        repo_refs = self.config.get(REPO_REF, [])

        for ref in repo_refs:
            self.add_from_ref(manager, ref)

    def resolve_path(self, filepath: str | None = None) -> Path:
        """
        Resolve a filepath relative to the base of this repo.

        For directory URLs, resolves relative to the directory.
        For .toml file URLs, resolves relative to the parent directory.

        Args:
            filepath: The path to the file, relative to the repository root.

        Returns:
            The resolved Path object.
        """
        base_path = self.get_path()
        if base_path is None:
            raise ValueError("Cannot resolve filepaths for non-local repositories")

        target_path = (base_path / filepath) if filepath else base_path
        target_path = target_path.resolve()

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
                     If empty, reads directly from the URL (for .toml file URLs).

        Returns:
            The content of the file as a string.
        """
        if not filepath:
            # Read directly from the URL
            path = Path(self.url[len("file://") :])
            return path.read_text()

        target_path = self.resolve_path(filepath)
        return target_path.read_text()

    def _read_http(self, filepath: str) -> str:
        """
        Read a resource from an HTTP(S) URL.

        Args:
            filepath: Path within the base resource directory for this repo.
                     If empty, reads directly from the URL (for .toml file URLs).

        Returns:
            The content of the resource as a string.

        Raises:
            ValueError: If the HTTP request fails.
        """
        # Construct the full URL by joining the base URL with the filepath
        if filepath:
            url = self.url.rstrip("/") + "/" + filepath.lstrip("/")
        else:
            url = self.url

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
                     If empty, reads directly from the URL (for .toml file URLs).

        Returns:
            The content of the resource as a string (UTF-8).
        """
        # Path portion after pkg://, interpreted relative to the 'starbash' package
        subpath = self.url[len("pkg://") :].strip("/")

        if filepath:
            res = resources.files("starbash").joinpath(subpath).joinpath(filepath)
        else:
            res = resources.files("starbash").joinpath(subpath)
        return res.read_text()

    def _load_config(
        self, default_toml: tomlkit.TOMLDocument | None = None
    ) -> tomlkit.TOMLDocument:
        """
        Loads the repository's configuration file.

        For URLs ending with .toml, reads that file directly.
        Otherwise, reads starbash.toml from the directory.

        If the config file does not exist, it logs a warning and returns an empty dict.

        Returns:
            A TOMLDocument containing the parsed configuration.
        """
        if default_toml is None:
            default_toml = tomlkit.TOMLDocument()  # empty placeholder

        try:
            if self._is_direct_toml_file():
                # Read the .toml file directly from the URL
                config_content = self.read("")
                logging.debug(f"Loading repo config from {self.url}")
            else:
                # Read starbash.toml from the directory
                config_content = self.read(repo_suffix)
                logging.debug(f"Loading repo config from {repo_suffix}")
            parsed = tomlkit.parse(config_content)

            # All repos must have a "repo" table inside, otherwise we assume the file is invalid and should
            # be reinited from template.
            return parsed if "repo" in parsed else default_toml

        except FileNotFoundError:
            logging.debug(f"No config file found for {self.url}, using template...")
            return default_toml

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

    @overload
    def get(self, key: str) -> Any | None: ...

    @overload
    def get[T](self, key: str, default: T, do_create: bool = False) -> T: ...

    def get(self, key: str, default: Any | None = None, do_create: bool = False) -> Any | None:
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
        parent: MutableMapping = value  # track our dict parent in case we need to add to it
        last_name = key
        for k in key.split("."):
            if value is None and do_create and default is not None:
                # If we are here that means the node above us in the dot path was missing, make it as a table
                value = tomlkit.table()
                parent[last_name] = value

            if not isinstance(value, dict):
                # Key path traverses through a non-dict value (including None), return default
                return default

            parent = value
            value = value.get(k)
            last_name = k

        if value is None and default is not None:
            # Try to convert 'dumb' list and dict defaults into tomlkit equivalents
            # Check for AoT first (before list) since AoT is a subclass of list
            if isinstance(default, AoT):
                # Preserve AoT type - don't convert it
                value = default
            elif isinstance(default, list):
                value = tomlkit.array()
                for item in default:
                    value.append(item)
            elif isinstance(default, dict):
                value = tomlkit.table()
                for k, v in default.items():
                    value[k] = v
            else:
                value = default

            # We might add the default value into the config when not found, because client might mutate it and then want to save the file
            if do_create:
                parent[last_name] = value

        return value

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
