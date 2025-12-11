import faulthandler
import logging
import sys
from importlib.metadata import version
from pathlib import Path
from string import Template
from typing import Any

import rich.console
import typer
from astropy.io import fits
from rich.logging import RichHandler
from rich.progress import track

import starbash
from repo import Repo, RepoManager, repo_suffix
from starbash.aliases import (
    Aliases,
    get_aliases,
    normalize_target_name,
    set_aliases,
)
from starbash.analytics import (
    NopAnalytics,
    analytics_exception,
    analytics_setup,
    analytics_shutdown,
    analytics_start_transaction,
)
from starbash.check_version import check_version
from starbash.database import (
    Database,
    ImageRow,
    SearchCondition,
    SessionRow,
    get_column_name,
)
from starbash.dwarf3 import extend_dwarf3_headers
from starbash.exception import UserHandledError, raise_missing_repo
from starbash.linux import linux_init
from starbash.os import symlink_or_copy
from starbash.paths import get_user_config_dir, get_user_config_path
from starbash.score import ScoredCandidate, score_candidates
from starbash.selection import Selection, build_search_conditions
from starbash.toml import toml_from_template
from starbash.tool import preflight_tools
from starbash.windows import windows_init

critical_keys = [Database.DATE_OBS_KEY, Database.IMAGETYP_KEY]

force_local_recipes = False  # Set to True to always use local recipes for testing


def setup_logging(console: rich.console.Console):
    """
    Configures basic logging.
    """
    from starbash import _is_test_env  # Lazy import to avoid circular dependency

    handlers = (
        [RichHandler(console=console, rich_tracebacks=True, markup=True)]
        if not _is_test_env
        else []
    )
    logging.basicConfig(
        level=starbash.log_filter_level,  # use the global log filter level
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,  # if this is included it hangs while spinners/liveviews if doit capture is also enabled
    )


def create_user() -> Path:
    """Create user directories if they don't exist yet."""
    path = get_user_config_path()
    if not path.exists():
        toml_from_template("userconfig", path)
        logging.info(f"Created user config file: {path}")
    return get_user_config_dir()


def copy_images_to_dir(images: list[ImageRow], output_dir: Path) -> None:
    """Copy images to the specified output directory (using symbolic links if possible).

    This function requires that "abspath" already be populated in each ImageRow.  Normally
    the caller does this by calling Starbash._add_image_abspath() on the image.
    """
    from starbash import console  # Lazy import to avoid circular dependency

    # Export images
    console.print(f"[cyan]Exporting {len(images)} images to {output_dir}...[/cyan]")

    linked_count = 0
    error_count = 0

    for image in images:
        # Get the source path from the image metadata
        source_path = Path(image.get("abspath", ""))

        if not source_path.exists():
            console.print(f"[red]Warning: Source file not found: {source_path}[/red]")
            error_count += 1
            continue

        # Determine destination filename
        dest_path = output_dir / source_path.name
        if dest_path.exists():
            console.print(f"[yellow]Skipping existing file: {dest_path}[/yellow]")
            error_count += 1
            continue

        # Try to create a symbolic link first
        symlink_or_copy(str(source_path.resolve()), str(dest_path))
        linked_count += 1

    # Print summary
    console.print("[green]Export complete![/green]")
    if linked_count > 0:
        console.print(f"  Linked: {linked_count} files")
    if error_count > 0:
        console.print(f"  [red]Errors: {error_count} files[/red]")


class Starbash:
    """The main Starbash application class."""

    def __init__(self, cmd: str = "unspecified", stderr_logging: bool = False):
        """
        Initializes the Starbash application by loading configurations
        and setting up the repository manager.

        Args:
            cmd (str): The command name or identifier for the current Starbash session.
            stderr_logging (bool): Whether to enable logging to stderr.
            no_progress (bool): Whether to disable the (asynchronous) progress display (because it breaks typer.ask)
        """
        from starbash import _is_test_env  # Lazy import to avoid circular dependency

        # It is important to disable fancy colors and line wrapping if running under test - because
        # those tests will be string parsing our output.
        console = rich.console.Console(
            force_terminal=False if _is_test_env else None,
            width=999999 if _is_test_env else None,  # Disable line wrapping in tests
            stderr=stderr_logging,
        )

        starbash.console = console  # Update the global console to use the progress version

        # Must be **after** _init_analytics otherwise we can get mutex locks later while emitting logs
        setup_logging(starbash.console)

        windows_init()
        linux_init()

        try:
            faulthandler.enable(sys.stderr)  # catch native stack traces if we crash
        except Exception:
            pass  # ignore failures - it isn't supported on all architectures or in pytest

        # Load app defaults and initialize the repository manager
        self._init_repos()
        self._init_analytics(cmd)  # after init repos so we have user prefs

        logging.info("Starbash starting")

        check_version()
        self._init_aliases()

        logging.info(f"Repo manager initialized with {len(self.repo_manager.repos)} repos.")
        # self.repo_manager.dump()

        self._db = None  # Lazy initialization - only create when accessed

        # Initialize selection state (stored in user config repo)
        self.selection = Selection(self.user_repo)
        preflight_tools()

    def _install_local_recipes(self) -> bool:
        """Use our local github submodule for recipes during development.

        Returns True if local recipes were installed."""

        submodule_path = Path(__file__).parent.parent.parent / "starbash-recipes"
        if submodule_path.exists():
            logging.info(f"Using local recipes from {submodule_path}")
            self.repo_manager.add_repo(f"file://{submodule_path}")
            return True
        return False

    def _init_repos(self) -> None:
        """Initialize all repositories managed by the RepoManager."""
        self.repo_manager = RepoManager()
        self.repo_manager.add_repo("pkg://defaults")

        # Add user prefs as a repo
        self.user_repo = self.repo_manager.add_repo("file://" + str(create_user()))

        # We always need at least one set of recipes.  If the user hasn't specified one use the default.
        if self.repo_manager.get_repo_by_kind("std-recipe") is None:
            if force_local_recipes:
                if self._install_local_recipes():
                    return  # We were able to use a local submodule version

            default_recipes_url = self.repo_manager.get("repo.recipe_default")
            assert default_recipes_url, (
                "Bug, repo.recipe_default not found."
            )  # Should be guaranteed
            # Substitute version in URL template (e.g., ${version} -> 0.1.30)
            app_version = version("starbash")
            default_recipes_url = Template(default_recipes_url).safe_substitute(version=app_version)
            # Try to add the versioned repo; fall back to local submodule if it fails
            try:
                self.repo_manager.add_repo(default_recipes_url)
            except ValueError as e:
                # Fallback to local submodule if remote version doesn't exist yet
                logging.warning(f"Could not load recipes from {default_recipes_url}: {e}")
                if not self._install_local_recipes():
                    raise

    def _init_analytics(self, cmd: str) -> None:
        self.analytics = NopAnalytics()
        if self.user_repo.get("analytics.enabled", True):
            include_user = self.user_repo.get("analytics.include_user", False)
            user_email = self.user_repo.get("user.email", None) if include_user else None
            if user_email is not None:
                user_email = str(user_email)
            analytics_setup(allowed=True, user_email=user_email)
            # this is intended for use with "with" so we manually do enter/exit
            self.analytics = analytics_start_transaction(name="App session", op=cmd)
            self.analytics.__enter__()

    def _init_aliases(self) -> None:
        alias_dict = self.repo_manager.get("aliases", {})
        assert isinstance(alias_dict, dict), "Aliases config must be a dictionary"
        a = Aliases(alias_dict)
        set_aliases(a)  # set global singleton instance

    @property
    def db(self) -> Database:
        """Lazy initialization of database - only created as needed."""
        if self._db is None:
            self._db = Database()
            # Ensure all repos are registered in the database
            self.repo_db_update()
        return self._db

    def repo_db_update(self) -> None:
        """Update the database with all managed repositories.

        Iterates over all repos in the RepoManager and ensures each one
        has a record in the repos table. This is called during lazy database
        initialization to prepare repo_id values for image insertion.
        """
        if self._db is None:
            return

        for repo in self.repo_manager.repos:
            self._db.upsert_repo(repo.url)
            logging.debug(f"Registered repo in database: {repo.url}")

    # --- Lifecycle ---
    def close(self) -> None:
        self.analytics.__exit__(None, None, None)

        analytics_shutdown()
        if self._db is not None:
            self._db.close()

    # Context manager support
    def __enter__(self) -> "Starbash":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        from starbash import _is_test_env
        from starbash.exception import UserHandledError

        handled = False
        # Don't suppress typer.Exit - it's used for controlled exit codes
        if exc and not isinstance(exc, typer.Exit) and not isinstance(exc, KeyboardInterrupt):
            # For UserHandledError, call ask_user_handled() and don't suppress
            if isinstance(exc, UserHandledError):
                exc.ask_user_handled()
                self.close()
                # Raise typer.Exit to ensure proper exit code
                raise typer.Exit(code=1)
            else:
                handled = analytics_exception(exc)
                self.close()
                if not handled:
                    # Show the full exception for developers
                    starbash.console.print_exception(show_locals=True)

                # In test environments, let exceptions propagate naturally for better test diagnostics
                if not _is_test_env:
                    # But in any case, make our app exit with an error code
                    raise typer.Exit(code=1)
        else:
            self.close()

        return handled

    def _add_session(self, header: dict) -> None:
        """We just added a new image, create or update its session entry as needed."""
        image_doc_id: int = header[Database.ID_KEY]  # this key is requirjust ed to exist
        image_type = header.get(Database.IMAGETYP_KEY)
        date = header.get(Database.DATE_OBS_KEY)
        if not date or not image_type:
            logging.warning(
                "Image '%s' missing either DATE-OBS or IMAGETYP FITS header, skipping...",
                header.get("path", "unspecified"),
            )
        else:
            exptime = header.get(Database.EXPTIME_KEY, 0)

            new = {
                get_column_name(Database.START_KEY): date,
                get_column_name(
                    Database.END_KEY
                ): date,  # FIXME not quite correct, should be longer by exptime
                get_column_name(Database.IMAGE_DOC_KEY): image_doc_id,
                get_column_name(Database.IMAGETYP_KEY): image_type,
                get_column_name(Database.NUM_IMAGES_KEY): 1,
                get_column_name(Database.EXPTIME_TOTAL_KEY): exptime,
                get_column_name(Database.EXPTIME_KEY): exptime,
            }

            filter = header.get(Database.FILTER_KEY)
            if filter:
                new[get_column_name(Database.FILTER_KEY)] = filter

            telescop = header.get(Database.TELESCOP_KEY)
            if telescop:
                new[get_column_name(Database.TELESCOP_KEY)] = telescop

            obj = header.get(Database.OBJECT_KEY)
            if obj:
                new[get_column_name(Database.OBJECT_KEY)] = obj

            session = self.db.get_session(new)
            self.db.upsert_session(new, existing=session)

    def add_local_repo(self, path: str, repo_type: str | None = None) -> None:
        """Add a local repository located at the specified path.  If necessary toml config files
        will be created at the root of the repository."""

        p = Path(path)
        console = starbash.console

        repo_toml = p / repo_suffix  # the starbash.toml file at the root of the repo
        if repo_toml.exists():
            logging.debug("Using existing repository config file: %s", repo_toml)
        else:
            if repo_type:
                console.print(f"Creating {repo_type} repository: {p}")
                toml_from_template(
                    f"repo/{repo_type}",
                    p / repo_suffix,
                    overrides={
                        "REPO_TYPE": repo_type,
                        "REPO_PATH": str(p),
                    },
                )
            else:
                # No type specified, therefore (for now) assume we are just using this as an input
                # repo (and it must exist)
                if not p.exists():
                    console.print(f"[red]Error: Repo path does not exist: {p}[/red]")
                    raise typer.Exit(code=1)

        console.print(f"Adding repository: {p}")

        repo = self.user_repo.add_repo_ref(self.repo_manager, p)
        if repo:
            self.reindex_repo(repo)

            # we don't yet always write default config files at roots of repos, but it would be easy to add here
            # r.write_config()
            self.user_repo.write_config()

    def guess_sessions(self, ref_session: SessionRow, want_type: str) -> list[ScoredCandidate]:
        """Given a particular session type (i.e. FLAT or BIAS etc...) and an
        existing session (which is assumed to generally be a LIGHT frame based session):

        Return a list of possible sessions which would be acceptable.  The more desirable
        matches are first in the list.  Possibly in the future I might have a 'score' and reason
        given for each ranking.

        The following critera MUST match to be acceptable:
        * matches requested imagetyp.
        * same filter as reference session (in the case want_type==FLAT only)
        * same telescope as reference session

        Quality is determined by (most important first):
        * GAIN setting is as close as possible to the reference session (very high penalty for mismatch)
        * smaller DATE-OBS delta to the reference session (within same week beats 5°C temp difference)
        * temperature of CCD-TEMP is closer to the reference session

        Eventually the code will check the following for 'nice to have' (but not now):
        * TBD

        Possibly eventually this code could be moved into recipes.

        """
        # Get reference image to access CCD-TEMP and DATE-OBS

        # Build search conditions - MUST match criteria
        conditions = {
            Database.IMAGETYP_KEY: want_type,
            Database.TELESCOP_KEY: ref_session[get_column_name(Database.TELESCOP_KEY)],
        }

        # For FLAT frames, filter must match the reference session
        if want_type.lower() == "flat":
            conditions[Database.FILTER_KEY] = ref_session[get_column_name(Database.FILTER_KEY)]

        # Search for candidate sessions
        candidates = self.db.search_session(build_search_conditions(conditions))

        return score_candidates(candidates, ref_session)

    def search_session(self, conditions: list[SearchCondition] | None = None) -> list[SessionRow]:
        """Search for sessions, optionally filtered by the current selection."""
        # Get query conditions from selection
        if conditions is None:
            conditions = self.selection.get_query_conditions()

        self.add_filter_not_masters(conditions)  # we never return processed masters as sessions
        return self.db.search_session(conditions)

    def _add_image_abspath(self, image: ImageRow) -> ImageRow:
        """Reconstruct absolute path from image row containing repo_url and relative path.

        Args:
            image: Image record with 'repo_url' and 'path' (relative) fields

        Returns:
            Modified image record with 'abspath' as absolute path
        """
        # Some nodes might have an abspath but not yet have repo set.  Fix that here!
        repo_url = image.get(Database.REPO_URL_KEY)
        repo = None
        if repo_url:
            repo = self.repo_manager.get_repo_by_url(repo_url)
            if repo:
                image["repo"] = repo  # cache the repo object as well

        if not image.get("abspath"):
            relative_path = image.get("path")

            if repo and relative_path:
                absolute_path = repo.resolve_path(relative_path)
                image["abspath"] = str(absolute_path)
            else:
                raise UserHandledError(f"Repo not found for URL: {repo_url}, session skipped.")

        return image

    def get_session_image(self, session: SessionRow) -> ImageRow:
        """
        Get the reference ImageRow for a session with absolute path.
        """
        from starbash.database import SearchCondition

        images = self.db.search_image(
            [SearchCondition("i.id", "=", session[get_column_name(Database.IMAGE_DOC_KEY)])]
        )
        assert len(images) == 1, f"Expected exactly one reference for session, found {len(images)}"
        return self._add_image_abspath(images[0])

    def get_master_images(
        self, imagetyp: str | None = None, reference_session: SessionRow | None = None
    ) -> list[ImageRow]:
        """Return a list of the specified master imagetyp (bias, flat etc...)
        (or any type if not specified).

        The first image will be the 'best' remaining entries progressively worse matches.

        (the following is not yet implemented)
        If reference_session is provided it will be used to refine the search as follows:
        * The telescope must match
        * The image resolutions and binnings must match
        * The filter must match (for FLAT frames only)
        * Preferably the master date_obs would be either before or slightly after (<24 hrs) the reference session start time
        * Preferably the master date_obs should be the closest in date to the reference session start time
        * The camera temperature should be as close as possible to the reference session camera temperature
        """
        master_repo = self.repo_manager.get_repo_by_kind("master")

        if master_repo is None:
            raise_missing_repo("master")

        # Search for images in the master repo only
        from starbash.database import SearchCondition

        search_conditions = [SearchCondition("r.url", "=", master_repo.url)]
        if imagetyp:
            search_conditions.append(SearchCondition("i.imagetyp", "=", imagetyp))

        images = self.db.search_image(search_conditions)

        # WE NO LONGER block mismatched filters here, instead we let our scoring function just heavily derank them
        # For flat frames, filter images based on matching reference_session filter
        # if reference_session and imagetyp and self.aliases.normalize(imagetyp) == "flat":
        #     ref_filter = self.aliases.normalize(
        #         reference_session.get(get_column_name(Database.FILTER_KEY), "None")
        #     )
        #     if ref_filter:
        #         # Filter images to only those with matching filter in metadata
        #         filtered_images = []
        #         for img in images:
        #             img_filter = img.get(Database.FILTER_KEY, "None")
        #             if img_filter == ref_filter:
        #                 filtered_images.append(img)
        #         images = filtered_images

        return images

    def add_filter_not_masters(self, conditions: list[SearchCondition]) -> None:
        """Add conditions to filter out master and processed repos from image searches."""
        master_repo = self.repo_manager.get_repo_by_kind("master")
        if master_repo is not None:
            conditions.append(SearchCondition("r.url", "<>", master_repo.url))
        processed_repo = self.repo_manager.get_repo_by_kind("processed")
        if processed_repo is not None:
            conditions.append(SearchCondition("r.url", "<>", processed_repo.url))

    def get_session_images(self, session: SessionRow, processed_ok: bool = False) -> list[ImageRow]:
        """
        Get all images belonging to a specific session.

        Sessions are defined by a unique combination of filter, imagetyp (image type),
        object (target name), telescope, and date range. This method queries the images
        table for all images matching the session's criteria in a single database query.

        Args:
            session_id: The database ID of the session

            processed_ok: If True, include images which were processed by apps (i.e. stacked or other procesing)
            Normally image pipelines don't want to accidentially consume those files.

        Returns:
            List of image records (dictionaries with path, metadata, etc.)
            Returns empty list if session not found or has no images.

        Raises:
            ValueError: If session_id is not found in the database
        """
        from starbash.database import SearchCondition

        # Query images that match ALL session criteria including date range
        # Note: We need to search JSON metadata for FILTER, IMAGETYP, OBJECT, TELESCOP
        # since they're not indexed columns in the images table
        conditions = [
            SearchCondition("i.date_obs", ">=", session[get_column_name(Database.START_KEY)]),
            SearchCondition("i.date_obs", "<=", session[get_column_name(Database.END_KEY)]),
            SearchCondition("i.imagetyp", "=", session[get_column_name(Database.IMAGETYP_KEY)]),
        ]

        # Note: not needed here, because we filter this earlier - when building the
        # list of candidate sessions.
        # we never want to return 'master' or 'processed' images as part of the session image paths
        # (because we will be passing these tool siril or whatever to generate masters or
        # some other downstream image)
        # self.add_filter_not_masters(conditions)

        # Single query with indexed date conditions
        images = self.db.search_image(conditions)

        # We no lognger filter by target(object) because it might not be set anyways
        filtered_images = []
        for img in images:
            # "HISTORY" nodes are added by processing tools (Siril etc...), we never want to accidentally read those images
            has_history = img.get("HISTORY")

            # images that were stacked seem to always have a STACKCNT header set (in the case of Siril)
            # or a NAXIS of >2 (because presumably the dwarflab tools view the third dimension as time)
            is_stacked = img.get("STACKCNT") or img.get("NAXIS", 0) > 2

            if (
                img.get(Database.FILTER_KEY) == session[get_column_name(Database.FILTER_KEY)]
                # and img.get(Database.OBJECT_KEY)
                # == session[get_column_name(Database.OBJECT_KEY)]
                and img.get(Database.TELESCOP_KEY)
                == session[get_column_name(Database.TELESCOP_KEY)]
                and (processed_ok or (not has_history and not is_stacked))
            ):
                filtered_images.append(img)

        # Reconstruct absolute paths for all images
        return [self._add_image_abspath(img) for img in filtered_images]

    def remove_repo_ref(self, url: str) -> None:
        """
        Remove a repository reference from the user configuration.

        Args:
            url: The repository URL to remove (e.g., 'file:///path/to/repo')

        Raises:
            ValueError: If the repository URL is not found in user configuration
        """
        self.db.remove_repo(url)

        # Get the repo-ref list from user config
        repo_refs: list = self.user_repo.config.get("repo-ref", [])

        # Find and remove the matching repo-ref
        found = False
        refs_copy = [r for r in repo_refs]  # Make a copy to iterate
        for ref in refs_copy:
            ref_dir = ref.get("dir", "")
            # Match by converting to file:// URL format if needed
            if ref_dir == url or f"file://{ref_dir}" == url:
                repo_refs.remove(ref)

                found = True
                break

        if not found:
            raise UserHandledError(f"Repository '{url}' not found in user configuration.")

        # Write the updated config
        self.user_repo.write_config()

    def _extend_image_header(self, headers: dict[str, Any], full_image_path: Path) -> bool:
        """Given a FITS header dictionary, possibly extend it with additional computed fields.
        Returns True if the header is invalid and should be skipped."""

        def has_critical_keys() -> bool:
            return all(key in headers for key in critical_keys)

        # Some device software (old Asiair versions) fails to populate TELESCOP, in that case fall back to
        # CREATOR (see doc/fits/malformedasimaster.txt for an example)
        if Database.TELESCOP_KEY not in headers:
            creator = headers.get("CREATOR")
            if creator:
                headers[Database.TELESCOP_KEY] = creator

        if not has_critical_keys():
            # See if possibly from a Dwarf3 camera which needs special handling
            extend_dwarf3_headers(headers, full_image_path)

            # Perhaps it saved us
            if not has_critical_keys():
                logging.debug(f"Headers {headers}")
                logging.warning(
                    "Image '%s' missing a required FITS header , skipping...",
                    headers["path"],
                )
                return False

        return True

    def add_image(
        self, repo: Repo, f: Path, force: bool = False, extra_metadata: dict[str, Any] = {}
    ) -> dict[str, Any] | None:
        """Read FITS header from file and add/update image entry in the database."""

        path = repo.get_path()
        if not path:
            raise ValueError(f"Repo path not found for {repo}")

        whitelist = None
        config = self.repo_manager.merged.get("config")
        if config:
            whitelist = config.get("fits-whitelist", None)

        # Convert absolute path to relative path within repo
        relative_path = f.relative_to(path)

        found = self.db.get_image(repo.url, str(relative_path))

        # for debugging sometimes we want to limit scanning to a single directory or file
        # debug_target = "masters-raw/2025-09-09/DARK"
        debug_target = None
        if debug_target:
            if str(relative_path).startswith(debug_target):
                logging.error("Debugging %s...", f)
                found = False
            else:
                found = True  # skip processing
                force = False

        if not found or force:
            # Read and log the primary header (HDU 0)
            with fits.open(str(f), memmap=False) as hdul:
                # convert headers to dict
                hdu0: Any = hdul[0]
                header = hdu0.header
                if type(header).__name__ == "Unknown":
                    raise ValueError("FITS header has Unknown type: %s", f)

                items = header.items()
                headers = {}
                for key, value in items:
                    if (not whitelist) or (key in whitelist):
                        headers[key] = value

                # Add any extra metadata if it was missing in the existing headers
                for key, value in extra_metadata.items():
                    headers.setdefault(key, value)

                # Store relative path in database
                headers["path"] = str(relative_path)
                if self._extend_image_header(headers, f):
                    image_doc_id = self.db.upsert_image(headers, repo.url)
                    headers[Database.ID_KEY] = image_doc_id

                    if not found:  # allow a session to also be created
                        return headers

        return None

    def add_image_and_session(self, repo: Repo, f: Path, force: bool = False) -> None:
        """Read FITS header from file and add/update image entry in the database."""
        headers = self.add_image(repo, f, force=force)

        if headers:
            # if "dark_exp_" in headers.get("path", ""):
            #    logging.debug("Debugging dark_exp image")

            # Update the session infos, but ONLY on first file scan
            # (otherwise invariants will get messed up)
            self._add_session(headers)

    def reindex_repo(self, repo: Repo, subdir: str | None = None):
        """Reindex all repositories managed by the RepoManager."""

        # make sure this new repo is listed in the repos table
        self.repo_db_update()  # not really ideal, a more optimal version would just add the new repo

        path = repo.get_path()

        repo_kind = repo.kind()
        if path and repo.is_scheme("file") and repo_kind != "recipe":
            logging.debug("Reindexing %s...", repo.url)

            if subdir:
                path = path / subdir
                # used to debug

            # Find all FITS files under this repo path
            for f in track(
                list(path.rglob("*.fit*")),
                description=f"Indexing {repo.url}...",
            ):
                # progress.console.print(f"Indexing {f}...")
                if repo_kind == "master":
                    # for master repos we only add to the image table
                    self.add_image(repo, f, force=True)
                elif repo_kind == "processed":
                    pass  # we never add processed images to our db
                else:
                    self.add_image_and_session(repo, f, force=starbash.force_regen)

    def reindex_repos(self):
        """Reindex all repositories managed by the RepoManager."""
        logging.debug("Reindexing all repositories...")

        for repo in track(self.repo_manager.repos, description="Reindexing repos..."):
            self.reindex_repo(repo)

    def get_recipes(self) -> list[Repo]:
        """Get all recipe repos available, sorted by priority (lower number first).

        Recipes without a priority are placed at the end of the list.
        """
        recipes = [r for r in self.repo_manager.repos if r.kind() == "recipe"]

        # Sort recipes by priority (lower number first). If no priority specified,
        # use float('inf') to push those to the end of the list.
        def priority_key(r: Repo) -> float:
            priority = r.get("recipe.priority")
            return float(priority) if priority is not None else float("inf")

        recipes.sort(key=priority_key)

        return recipes

    def filter_by_imagetyp(
        self, sessions: list[ImageRow] | list[SessionRow], imagetyp: str
    ) -> list[ImageRow] | list[SessionRow]:
        """Filter sessions to only those that contain light frames."""
        filtered_sessions: list[ImageRow] = []
        for s in sessions:
            imagetyp_val = s.get(Database.IMAGETYP_KEY) or s.get(
                get_column_name(Database.IMAGETYP_KEY)
            )
            if imagetyp_val is None:
                continue
            if get_aliases().normalize(str(imagetyp_val)) == imagetyp:
                filtered_sessions.append(s)
        return filtered_sessions

    def filter_sessions_by_target(
        self, sessions: list[SessionRow], target: str
    ) -> list[SessionRow]:
        """Filter sessions to only those that match the given target name."""
        filtered_sessions: list[SessionRow] = []
        for s in sessions:
            obj_val = s.get(get_column_name(Database.OBJECT_KEY))
            if obj_val is None:
                continue
            if normalize_target_name(str(obj_val)) == target:
                filtered_sessions.append(s)
        return filtered_sessions
