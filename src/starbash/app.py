import glob
import itertools
import logging
import os
import shutil
import tempfile
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import rich.console
import typer
from astropy.io import fits
from rich.logging import RichHandler
from rich.progress import Progress, track

import starbash
from repo import Repo, RepoManager, repo_suffix
from starbash.aliases import Aliases, normalize_target_name
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
from starbash.exception import UserHandledError
from starbash.paths import get_user_cache_dir, get_user_config_dir
from starbash.selection import Selection, build_search_conditions
from starbash.toml import toml_from_template
from starbash.tool import expand_context_unsafe, tools


@dataclass
class ProcessingResult:
    target: str  # normalized target name, or in the case of masters the camera or instrument id
    sessions: list[SessionRow] = field(
        default_factory=list
    )  # the input sessions processed to make this result
    success: bool | None = None  # false if we had an error, None if skipped
    notes: str | None = None  # notes about what happened
    # FIXME, someday we will add information about masters/flats that were used?


def update_processing_result(result: ProcessingResult, e: Exception | None = None) -> None:
    """Handle exceptions during processing and update the ProcessingResult accordingly."""

    result.success = True  # assume success
    if e:
        result.success = False

        if isinstance(e, UserHandledError):
            if e.ask_user_handled():
                logging.debug("UserHandledError was handled.")
            result.notes = e.__rich__()  # No matter what we want to show the fault in our results

        elif isinstance(e, RuntimeError):
            # Print errors for runtimeerrors but keep processing other runs...
            logging.error(f"Skipping run due to: {e}")
            result.notes = "Aborted due to possible error in (alpha) code, please report a bug on our github..."
        else:
            # Unexpected exception - log it and re-raise
            logging.exception("Unexpected error during processing:")
            raise e


def setup_logging(console: rich.console.Console):
    """
    Configures basic logging.
    """
    from starbash import _is_test_env  # Lazy import to avoid circular dependency

    handlers = [RichHandler(console=console, rich_tracebacks=True)] if not _is_test_env else []
    logging.basicConfig(
        level=starbash.log_filter_level,  # use the global log filter level
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )


def get_user_config_path() -> Path:
    """Returns the path to the user config file."""
    config_dir = get_user_config_dir()
    return config_dir / repo_suffix


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
    copied_count = 0
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
        try:
            dest_path.symlink_to(source_path.resolve())
            linked_count += 1
        except (OSError, NotImplementedError):
            # If symlink fails, try to copy
            try:
                shutil.copy2(source_path, dest_path)
                copied_count += 1
            except Exception as e:
                console.print(f"[red]Error copying {source_path.name}: {e}[/red]")
                error_count += 1

    # Print summary
    console.print("[green]Export complete![/green]")
    if linked_count > 0:
        console.print(f"  Linked: {linked_count} files")
    if copied_count > 0:
        console.print(f"  Copied: {copied_count} files")
    if error_count > 0:
        console.print(f"  [red]Errors: {error_count} files[/red]")


class ProcessingContext(tempfile.TemporaryDirectory):
    """For processing a set of sessions for a particular target.

    Keeps a shared temporary directory for intermediate files.  We expose the path to that
    directory in context["process_dir"].
    """

    def __init__(self, starbash: "Starbash"):
        cache_dir = get_user_cache_dir()
        super().__init__(prefix="sbprocessing_", dir=cache_dir)
        self.sb = starbash
        logging.debug(f"Created processing context at {self.name}")

        self.sb.init_context()
        self.sb.context["process_dir"] = self.name

    def __enter__(self) -> "ProcessingContext":
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        """Returns true if exceptions were handled"""
        logging.debug(f"Cleaning up processing context at {self.name}")

        # unregister our process dir
        self.sb.context.pop("process_dir", None)

        super().__exit__(exc_type, exc_value, traceback)
        # return handled


class NotEnoughFilesError(UserHandledError):
    """Exception raised when not enough input files are provided for a processing stage."""

    def __init__(self, message: str, files: list[str]):
        super().__init__(message)
        self.files = files


class Starbash:
    """The main Starbash application class."""

    def __init__(
        self, cmd: str = "unspecified", stderr_logging: bool = False, no_progress: bool = False
    ):
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

        # We create one top-level progress context so that when various subtasks are created
        # the progress bars stack and don't mess up our logging.
        self.progress = Progress(console=console, refresh_per_second=2)
        if not no_progress:
            self.progress.start()

        setup_logging(starbash.console)
        logging.info("Starbash starting...")

        # Load app defaults and initialize the repository manager
        self._init_repos()
        self._init_analytics(cmd)  # after init repos so we have user prefs
        check_version()
        self._init_aliases()

        logging.info(f"Repo manager initialized with {len(self.repo_manager.repos)} repos.")
        # self.repo_manager.dump()

        self._db = None  # Lazy initialization - only create when accessed

        # Initialize selection state (stored in user config repo)
        self.selection = Selection(self.user_repo)

    def _init_repos(self) -> None:
        """Initialize all repositories managed by the RepoManager."""
        self.repo_manager = RepoManager()
        self.repo_manager.add_repo("pkg://defaults")

        # Add user prefs as a repo
        self.user_repo = self.repo_manager.add_repo("file://" + str(create_user()))

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
        self.aliases = Aliases(alias_dict)

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
        self.progress.stop()
        self.analytics.__exit__(None, None, None)

        analytics_shutdown()
        if self._db is not None:
            self._db.close()

    # Context manager support
    def __enter__(self) -> "Starbash":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        handled = False
        # Don't suppress typer.Exit - it's used for controlled exit codes
        if exc and not isinstance(exc, typer.Exit):
            handled = analytics_exception(exc)
        self.close()
        return handled

    def _add_session(self, header: dict) -> None:
        """We just added a new image, create or update its session entry as needed."""
        image_doc_id: int = header[Database.ID_KEY]  # this key is required to exist
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

    def add_local_repo(self, path: str, repo_type: str | None = None) -> Repo:
        """Add a local repository located at the specified path.  If necessary toml config files
        will be created at the root of the repository."""

        p = Path(path)
        console = starbash.console

        repo_toml = p / repo_suffix  # the starbash.toml file at the root of the repo
        if repo_toml.exists():
            logging.warning("Using existing repository config file: %s", repo_toml)
        else:
            if repo_type:
                console.print(f"Creating {repo_type} repository: {p}")
                p.mkdir(parents=True, exist_ok=True)

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

        repo = self.user_repo.add_repo_ref(p)
        if repo:
            self.reindex_repo(repo)

            # we don't yet always write default config files at roots of repos, but it would be easy to add here
            # r.write_config()
            self.user_repo.write_config()

    def guess_sessions(self, ref_session: SessionRow, want_type: str) -> list[SessionRow]:
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
        * temperature of CCD-TEMP is closer to the reference session
        * smaller DATE-OBS delta to the reference session

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

        return self.score_candidates(candidates, ref_session)

    def score_candidates(
        self, candidates: list[dict[str, Any]], ref_session: SessionRow
    ) -> list[SessionRow]:
        """Given a list of images or sessions, try to rank that list by desirability.

        Return a list of possible images/sessions which would be acceptable.  The more desirable
        matches are first in the list.  Possibly in the future I might have a 'score' and reason
        given for each ranking.

        The following critera MUST match to be acceptable:
        * matches requested imagetyp.
        * same filter as reference session (in the case want_type==FLAT only)
        * same telescope as reference session

        Quality is determined by (most important first):
        * temperature of CCD-TEMP is closer to the reference session
        * smaller DATE-OBS delta to the reference session

        Eventually the code will check the following for 'nice to have' (but not now):
        * TBD

        Possibly eventually this code could be moved into recipes.

        """

        metadata: dict = ref_session.get("metadata", {})
        ref_temp = metadata.get("CCD-TEMP", None)
        ref_date_str = metadata.get(Database.DATE_OBS_KEY)

        # Now score and sort the candidates
        scored_candidates = []

        for candidate in candidates:
            score = 0.0

            # Get candidate image metadata to access CCD-TEMP and DATE-OBS
            try:
                candidate_image = candidate.get("metadata", {})

                # Score by CCD-TEMP difference (most important)
                # Lower temperature difference = better score
                if ref_temp is not None:
                    candidate_temp = candidate_image.get("CCD-TEMP")
                    if candidate_temp is not None:
                        try:
                            temp_diff = abs(float(ref_temp) - float(candidate_temp))
                            # Use exponential decay: closer temps get much better scores
                            # Perfect match (0°C diff) = 1000, 1°C diff ≈ 368, 2°C diff ≈ 135
                            score += 1000 * (2.718 ** (-temp_diff))
                        except (ValueError, TypeError):
                            # If we can't parse temps, give a neutral score
                            score += 0

                # Parse reference date for time delta calculations
                candidate_date_str = candidate_image.get(Database.DATE_OBS_KEY)
                if ref_date_str and candidate_date_str:
                    try:
                        ref_date = datetime.fromisoformat(ref_date_str)
                        candidate_date = datetime.fromisoformat(candidate_date_str)
                        time_delta = abs((ref_date - candidate_date).total_seconds())
                        # Closer in time = better score
                        # Same day ≈ 100, 7 days ≈ 37, 30 days ≈ 9
                        # Using 7-day half-life
                        score += 100 * (2.718 ** (-time_delta / (7 * 86400)))
                    except (ValueError, TypeError):
                        logging.warning("Malformed date - ignoring entry")

                scored_candidates.append((score, candidate))

            except (AssertionError, KeyError) as e:
                # If we can't get the session image, log and skip this candidate
                logging.warning(f"Could not score candidate session {candidate.get('id')}: {e}")
                continue

        # Sort by score (highest first)
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        return [candidate for _, candidate in scored_candidates]

    def search_session(self) -> list[SessionRow]:
        """Search for sessions, optionally filtered by the current selection."""
        # Get query conditions from selection
        conditions = self.selection.get_query_conditions()
        self.add_filter_not_masters(conditions)
        return self.db.search_session(conditions)

    def _add_image_abspath(self, image: ImageRow) -> ImageRow:
        """Reconstruct absolute path from image row containing repo_url and relative path.

        Args:
            image: Image record with 'repo_url' and 'path' (relative) fields

        Returns:
            Modified image record with 'abspath' as absolute path
        """
        if not image.get("abspath"):
            repo_url = image.get(Database.REPO_URL_KEY)
            relative_path = image.get("path")

            if repo_url and relative_path:
                repo = self.repo_manager.get_repo_by_url(repo_url)
                if repo:
                    absolute_path = repo.resolve_path(relative_path)
                    image["abspath"] = str(absolute_path)

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
            logging.warning("No master repo configured - skipping master frame load.")
            return []

        # Search for images in the master repo only
        from starbash.database import SearchCondition

        search_conditions = [SearchCondition("r.url", "=", master_repo.url)]
        if imagetyp:
            search_conditions.append(SearchCondition("i.imagetyp", "=", imagetyp))

        images = self.db.search_image(search_conditions)

        # FIXME - move this into a general filter function
        # For flat frames, filter images based on matching reference_session filter
        if reference_session and imagetyp and self.aliases.normalize(imagetyp) == "flat":
            ref_filter = self.aliases.normalize(
                reference_session.get(get_column_name(Database.FILTER_KEY), "None")
            )
            if ref_filter:
                # Filter images to only those with matching filter in metadata
                filtered_images = []
                for img in images:
                    img_filter = img.get(Database.FILTER_KEY, "None")
                    if img_filter == ref_filter:
                        filtered_images.append(img)
                images = filtered_images

        return images

    def add_filter_not_masters(self, conditions: list[SearchCondition]) -> None:
        """Add conditions to filter out master and processed repos from image searches."""
        master_repo = self.repo_manager.get_repo_by_kind("master")
        if master_repo is not None:
            conditions.append(SearchCondition("r.url", "<>", master_repo.url))
        processed_repo = self.repo_manager.get_repo_by_kind("processed")
        if processed_repo is not None:
            conditions.append(SearchCondition("r.url", "<>", processed_repo.url))

    def get_session_images(self, session: SessionRow) -> list[ImageRow]:
        """
        Get all images belonging to a specific session.

        Sessions are defined by a unique combination of filter, imagetyp (image type),
        object (target name), telescope, and date range. This method queries the images
        table for all images matching the session's criteria in a single database query.

        Args:
            session_id: The database ID of the session

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

            # images that were stacked on Seestar have one of these keys
            is_stacked = img.get("CD1_1") or img.get("OBJCTTYP")

            if (
                img.get(Database.FILTER_KEY) == session[get_column_name(Database.FILTER_KEY)]
                # and img.get(Database.OBJECT_KEY)
                # == session[get_column_name(Database.OBJECT_KEY)]
                and img.get(Database.TELESCOP_KEY)
                == session[get_column_name(Database.TELESCOP_KEY)]
                and not has_history
                and not is_stacked
            ):
                filtered_images.append(img)

        # Reconstruct absolute paths for all images
        return [self._add_image_abspath(img) for img in filtered_images] if filtered_images else []

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
        repo_refs = self.user_repo.config.get("repo-ref")

        if not repo_refs:
            raise ValueError("No repository references found in user configuration.")

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
            raise ValueError(f"Repository '{url}' not found in user configuration.")

        # Write the updated config
        self.user_repo.write_config()

    def add_image(self, repo: Repo, f: Path, force: bool = False) -> dict[str, Any] | None:
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

                # Some device software (old Asiair versions) fails to populate TELESCOP, in that case fall back to
                # CREATOR (see doc/fits/malformedasimaster.txt for an example)
                if Database.TELESCOP_KEY not in headers:
                    creator = headers.get("CREATOR")
                    if creator:
                        headers[Database.TELESCOP_KEY] = creator

                logging.debug("Headers for %s: %s", f, headers)

                # Store relative path in database
                headers["path"] = str(relative_path)
                image_doc_id = self.db.upsert_image(headers, repo.url)
                headers[Database.ID_KEY] = image_doc_id

                if not found:
                    return headers

        return None

    def add_image_and_session(self, repo: Repo, f: Path, force: bool = False) -> None:
        """Read FITS header from file and add/update image entry in the database."""
        headers = self.add_image(repo, f, force=force)
        if headers:
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

    def _get_stages(self, name: str) -> list[dict[str, Any]]:
        """Get all pipeline stages defined in the merged configuration.

        Returns:
            List of stage definitions (dictionaries with 'name' and 'priority')
        """
        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).
        pipeline_definitions = self.repo_manager.merged.getall(name)
        flat_pipeline_steps = list(itertools.chain.from_iterable(pipeline_definitions))

        # 2. Sort the pipeline steps by their 'priority' field.
        try:
            sorted_pipeline = sorted(flat_pipeline_steps, key=lambda s: s["priority"])
        except KeyError as e:
            # Re-raise as a ValueError with a more descriptive message.
            raise ValueError(
                "invalid stage definition: a stage is missing the required 'priority' key"
            ) from e

        logging.debug(f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority.")
        return sorted_pipeline

    def run_pipeline_step(self, step_name: str):
        logging.info(f"--- Running pipeline step: '{step_name}' ---")

        # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
        task_definitions = self.repo_manager.merged.getall("stage")
        all_tasks = list(itertools.chain.from_iterable(task_definitions))

        # Find all tasks that should run during this pipeline step.
        tasks_to_run = [task for task in all_tasks if task.get("when") == step_name]
        for task in tasks_to_run:
            self.run_stage(task)

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

    def get_recipe_for_session(self, session: SessionRow, step: dict[str, Any]) -> Repo | None:
        """Try to find a recipe that can be used to process the given session for the given step name
        (master-dark, master-bias, light, stack, etc...)

        * if a recipe doesn't have a matching recipe.stage.<step_name> it is not considered
        * As part of this checking we will look at recipe.auto.require.* conditions to see if the recipe
        is suitable for this session.
        * the imagetyp of this session matches step.input

        Currently we return just one Repo but eventually we should support multiple matching recipes
        and make the user pick (by throwing an exception?).
        """
        # Get all recipe repos - FIXME add a getall(kind) to RepoManager
        recipe_repos = self.get_recipes()

        step_name = step.get("name")
        if not step_name:
            raise ValueError("Invalid pipeline step found: missing 'name' key.")

        input_name = step.get("input")
        if not input_name:
            raise ValueError("Invalid pipeline step found: missing 'input' key.")

        # if input type is recipe we don't check for filetype match - because we'll just use files already in
        # the tempdir
        if input_name != "recipe":
            imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))

            if not imagetyp or input_name != self.aliases.normalize(imagetyp):
                logging.debug(
                    f"Session imagetyp '{imagetyp}' does not match step input '{input_name}', skipping"
                )
                return None

        # Get session metadata for checking requirements
        session_metadata = session.get("metadata", {})

        for repo in recipe_repos:
            # Check if this recipe has the requested stage
            stage_config = repo.get(f"recipe.stage.{step_name}")
            if not stage_config:
                logging.debug(f"Recipe {repo.url} does not have stage '{step_name}', skipping")
                continue

            # Check auto.require conditions if they exist

            # If requirements are specified, check if session matches
            required_filters = repo.get("recipe.auto.require.filter", [])
            if required_filters:
                session_filter = self.aliases.normalize(
                    session_metadata.get(Database.FILTER_KEY), lenient=True
                )

                # Session must have AT LEAST one filter that matches one of the required filters
                if not session_filter or session_filter not in required_filters:
                    logging.debug(
                        f"Recipe {repo.url} requires filters {required_filters}, "
                        f"session has '{session_filter}', skipping"
                    )
                    continue

            required_color = repo.get("recipe.auto.require.color", False)
            if required_color:
                session_bayer = session_metadata.get("BAYERPAT")

                # Session must be color (i.e. have a BAYERPAT header)
                if not session_bayer:
                    logging.debug(
                        f"Recipe {repo.url} requires a color camera, "
                        f"but session has no BAYERPAT header, skipping"
                    )
                    continue

            required_cameras = repo.get("recipe.auto.require.camera", [])
            if required_cameras:
                session_camera = self.aliases.normalize(
                    session_metadata.get("INSTRUME"), lenient=True
                )  # Camera identifier

                # Session must have a camera that matches one of the required cameras
                if not session_camera or session_camera not in required_cameras:
                    logging.debug(
                        f"Recipe {repo.url} requires cameras {required_cameras}, "
                        f"session has '{session_camera}', skipping"
                    )
                    continue

            # This recipe matches!
            logging.info(f"Selected recipe {repo.url} for stage '{step_name}' ")
            return repo

        # No matching recipe found
        return None

    def filter_sessions_with_lights(self, sessions: list[SessionRow]) -> list[SessionRow]:
        """Filter sessions to only those that contain light frames."""
        filtered_sessions: list[SessionRow] = []
        for s in sessions:
            imagetyp_val = s.get(get_column_name(Database.IMAGETYP_KEY))
            if imagetyp_val is None:
                continue
            if self.aliases.normalize(str(imagetyp_val)) == "light":
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

    def process_target(self, target: str, sessions: list[SessionRow]) -> ProcessingResult:
        """Do processing for a particular target (i.e. all sessions for a particular object)."""

        pipeline = self._get_stages("stages")

        lights_step = pipeline[
            0
        ]  # FIXME super nasty - we assume the array is exactly these two elements
        stack_step = pipeline[1]
        task_exception: Exception | None = None

        result = ProcessingResult(target=target, sessions=sessions)

        with ProcessingContext(self):
            try:
                # target specific processing here

                # we find our recipe while processing our first light frame session
                recipe = None

                # process all light frames
                step = lights_step
                lights_task = self.progress.add_task("Processing session...", total=len(sessions))
                try:
                    lights_processed = False  # for better reporting
                    stack_processed = False

                    for session in sessions:
                        step_name = step["name"]
                        if not recipe:
                            # for the time being: The first step in the pipeline MUST be "light"
                            recipe = self.get_recipe_for_session(session, step)
                            if not recipe:
                                continue  # No recipe found for this target/session

                            # find the task for this step
                            task = None
                            if recipe:
                                task = recipe.get("recipe.stage." + step_name)

                            if task:
                                # put all relevant session info into context
                                self.set_session_in_context(session)

                                # The following operation might take a long time, so give the user some more info...
                                self.progress.update(
                                    lights_task,
                                    description=f"Processing {step_name} {self.context['date']}...",
                                )
                                try:
                                    self.run_stage(task)
                                    lights_processed = True
                                except NotEnoughFilesError:
                                    logging.warning(
                                        "Skipping session, siril requires at least two frames per session..."
                                    )

                        # We made progress - call once per iteration ;-)
                        self.progress.advance(lights_task)
                finally:
                    self.progress.remove_task(lights_task)

                # after all light frames are processed, do the stacking
                step = stack_step
                if recipe:
                    task = recipe.get("recipe.stage." + step["name"])

                    if task:
                        #
                        # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                        # dirs for particular targets?
                        try:
                            self.run_stage(task)
                            stack_processed = True
                        except NotEnoughFilesError:
                            logging.warning(
                                "Skipping stacking, siril requires at least two frames per session..."
                            )

                # Success!  we processed all lights and did a stack (probably)
                if not lights_processed:
                    result.notes = "Skipped, no suitable recipe found for light frames..."
                elif not stack_processed:
                    result.notes = "Skipped, no suitable recipe found for stacking..."
                else:
                    update_processing_result(result)
            except Exception as e:
                task_exception = e
                update_processing_result(result, task_exception)

        return result

    def run_all_stages(self) -> list[ProcessingResult]:
        """On the currently active session, run all processing stages

        * for each target in the current selection:
        *   select ONE recipe for processing that target (check recipe.auto.require.* conditions)
        *   init session context (it will be shared for all following steps) - via ProcessingContext
        *   create a temporary processing directory (for intermediate files - shared by all stages)
        *   create a processed output directory (for high value final files) - via run_stage()
        *   iterate over all light frame sessions in the current selection
        *     for each session:
        *       update context input and output files
        *       run session.light stages
        *   after all sessions are processed, run final.stack stages (using the shared context and temp dir)

        """
        sessions = self.search_session()
        targets = {
            normalize_target_name(obj)
            for s in sessions
            if (obj := s.get(get_column_name(Database.OBJECT_KEY))) is not None
        }

        target_task = self.progress.add_task("Processing targets...", total=len(targets))

        results: list[ProcessingResult] = []
        try:
            for target in targets:
                self.progress.update(target_task, description=f"Processing target {target}...")
                # select sessions for this target
                target_sessions = self.filter_sessions_by_target(sessions, target)

                # we only want sessions with light frames
                target_sessions = self.filter_sessions_with_lights(target_sessions)

                if target_sessions:
                    result = self.process_target(target, target_sessions)
                    results.append(result)

                # We made progress - call once per iteration ;-)
                self.progress.advance(target_task)
        finally:
            self.progress.remove_task(target_task)

        return results

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate any missing master frames

        Steps:
        * loop across all pipeline stages, first bias, then dark, then flat, etc...  Very important that bias is before flat.
        * set all_tasks to be all tasks for when == "setup.master.bias"
        * loop over all currently unfiltered sessions
        * if task input.type == the imagetyp for this current session
        *    add_input_to_context() add the input files to the context (from the session)
        *    run_stage(task) to generate the new master frame
        """
        sorted_pipeline = self._get_stages("master-stages")
        sessions = self.search_session()
        results: list[ProcessingResult] = []

        # we loop over pipeline steps in the
        for step in sorted_pipeline:
            step_name = step.get("name")
            if not step_name:
                raise ValueError("Invalid pipeline step found: missing 'name' key.")
            for session in track(sessions, description=f"Processing {step_name} for sessions..."):
                task = None
                recipe = self.get_recipe_for_session(session, step)
                if recipe:
                    task = recipe.get("recipe.stage." + step_name)

                processing_exception: Exception | None = None
                result = ProcessingResult(target=step_name, sessions=[session])

                if task:
                    try:
                        # Create a default process dir in /tmp.
                        # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                        # dirs for particular targets?
                        with ProcessingContext(self):
                            self.set_session_in_context(session)
                            self.run_stage(task)
                    except Exception as e:
                        processing_exception = e

                    # We did one processing run. add the results
                    update_processing_result(result, processing_exception)

                # if we skipped leave the result as skipped
                results.append(result)

        return results

    def init_context(self) -> None:
        """Do common session init"""

        # Context is preserved through all stages, so each stage can add new symbols to it for use by later stages
        self.context = {}

        # Update the context with runtime values.
        runtime_context = {
            # "masters": "/workspaces/starbash/images/masters",  # FIXME find this the correct way
        }
        self.context.update(runtime_context)

    def set_session_in_context(self, session: SessionRow) -> None:
        """adds to context from the indicated session:

        Sets the following context variables based on the provided session:
        * target - the normalized target name of the session
        * instrument - for the session
        * date - the localtimezone date of the session
        * imagetyp - the imagetyp of the session
        * session - the current session row (joined with a typical image) (can be used to
        find things like telescope, temperature ...)
        * session_config - a short human readable description of the session - suitable for logs or filenames
        """
        # it is okay to give them the actual session row, because we're never using it again
        self.context["session"] = session

        target = session.get(get_column_name(Database.OBJECT_KEY))
        if target:
            self.context["target"] = normalize_target_name(target)

        instrument = session.get(get_column_name(Database.TELESCOP_KEY))
        if instrument:
            self.context["instrument"] = instrument

        imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))
        if imagetyp:
            imagetyp = self.aliases.normalize(imagetyp)
            self.context["imagetyp"] = imagetyp

            # add a short human readable description of the session - suitable for logs or in filenames
            session_config = f"{imagetyp}"

            metadata = session.get("metadata", {})
            filter = metadata.get(Database.FILTER_KEY)
            if (imagetyp == "flat" or imagetyp == "light") and filter:
                # we only care about filters in these cases
                session_config += f"_{filter}"
            if imagetyp == "dark":
                exptime = session.get(get_column_name(Database.EXPTIME_KEY))
                if exptime:
                    session_config += f"_{int(float(exptime))}s"

            self.context["session_config"] = session_config

        date = session.get(get_column_name(Database.START_KEY))
        if date:
            from starbash import (
                to_shortdate,
            )  # Lazy import to avoid circular dependency

            self.context["date"] = to_shortdate(date)

    def add_input_masters(self, stage: dict) -> None:
        """based on input.masters add the correct master frames as context.master.<type> filepaths"""
        session = self.context.get("session")
        assert session is not None, "context.session should have been already set"

        input_config = stage.get("input", {})
        master_types: list[str] = input_config.get("masters", [])
        for master_type in master_types:
            masters = self.get_master_images(imagetyp=master_type, reference_session=session)
            if not masters:
                raise RuntimeError(
                    f"No master frames of type '{master_type}' found for stage '{stage.get('name')}'"
                )

            context_master = self.context.setdefault("master", {})

            if len(masters) > 1:
                logging.debug(
                    f"Multiple ({len(masters)}) master frames of type '{master_type}' found, using first. FIXME."
                )

            # Try to rank the images by desirability
            masters = self.score_candidates(masters, session)

            self._add_image_abspath(masters[0])  # make sure abspath is populated
            selected_master = masters[0]["abspath"]
            logging.info(f"For master '{master_type}', using: {selected_master}")

            context_master[master_type] = selected_master

    def add_input_files(self, stage: dict) -> None:
        """adds to context.input_files based on the stage input config"""
        input_config = stage.get("input")
        input_required = 0
        if input_config:
            # if there is an "input" dict, we assume input.required is true if unset
            input_required = input_config.get("required", 0)
            source = input_config.get("source")
            if source is None:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' configuration: missing 'source'"
                )
            if source == "path":
                # The path might contain context variables that need to be expanded.
                # path_pattern = expand_context(input_config["path"], context)
                path_pattern = input_config["path"]
                input_files = glob.glob(path_pattern, recursive=True)

                self.context["input_files"] = (
                    input_files  # Pass in the file list via the context dict
                )
            elif source == "repo":
                # Get images for this session (by pulling from repo)
                session = self.context.get("session")
                assert session is not None, "context.session should have been already set"

                images = self.get_session_images(session)
                logging.debug(f"Using {len(images)} files as input_files")
                self.context["input_files"] = [
                    img["abspath"] for img in images
                ]  # Pass in the file list via the context dict
            elif source == "recipe":
                # The input files are already in the tempdir from the recipe processing
                # therefore we don't need to do anything here
                pass
            else:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' source: {source}"
                )

            # FIXME compare context.output to see if it already exists and is newer than the input files, if so skip processing
        else:
            # The script doesn't mention input, therefore assume it doesn't want input_files
            if "input_files" in self.context:
                del self.context["input_files"]

        input_files: list[str] = self.context.get("input_files", [])
        if input_required:
            if len(input_files) < input_required:
                raise NotEnoughFilesError(
                    f"Stage requires at least {input_required} input files", input_files
                )

    def add_output_path(self, stage: dict) -> None:
        """Adds output path information to context based on the stage output config.

        If the output dest is 'repo', it finds the appropriate repository and constructs
        the full output path based on the repository's base path and relative path expression.

        Sets the following context variables:
        - context.output.root_path - base path of the destination repo
        - context.output.base_path - full path without file extension
        - context.output.suffix - file extension (e.g., .fits or .fit.gz)
        - context.output.full_path - complete output file path
        - context.output.repo - the destination Repo (if applicable)
        """
        output_config = stage.get("output")
        if not output_config:
            # No output configuration, remove any existing output from context
            if "output" in self.context:
                del self.context["output"]
            return

        dest = output_config.get("dest")
        if not dest:
            raise ValueError(
                f"Stage '{stage.get('description', 'unknown')}' has 'output' config but missing 'dest'"
            )

        if dest == "repo":
            # Find the destination repo by type/kind
            output_type = output_config.get("type")
            if not output_type:
                raise ValueError(
                    f"Stage '{stage.get('description', 'unknown')}' has output.dest='repo' but missing 'type'"
                )

            # Find the repo with matching kind
            dest_repo = self.repo_manager.get_repo_by_kind(output_type)
            if not dest_repo:
                raise ValueError(
                    f"No repository found with kind '{output_type}' for output destination"
                )

            repo_base = dest_repo.get_path()
            if not repo_base:
                raise ValueError(f"Repository '{dest_repo.url}' has no filesystem path")

            repo_relative: str | None = dest_repo.get("repo.relative")
            if not repo_relative:
                raise ValueError(
                    f"Repository '{dest_repo.url}' is missing 'repo.relative' configuration"
                )

            # we support context variables in the relative path
            repo_relative = expand_context_unsafe(repo_relative, self.context)
            full_path = repo_base / repo_relative

            # base_path but without spaces - because Siril doesn't like that
            full_path = Path(str(full_path).replace(" ", r"_"))

            base_path = full_path.parent / full_path.stem
            if str(base_path).endswith("*"):
                # The relative path must be of the form foo/blah/*.fits or somesuch.  In that case we want the base
                # path to just point to that directory prefix.
                base_path = Path(str(base_path)[:-1])

            # create output directory if needed
            os.makedirs(base_path.parent, exist_ok=True)

            # Set context variables as documented in the TOML
            self.context["output"] = {
                # "root_path": repo_relative, not needed I think
                "base_path": base_path,
                # "suffix": full_path.suffix, not needed I think
                "full_path": full_path,
                "repo": dest_repo,
            }
        else:
            raise ValueError(
                f"Unsupported output destination type: {dest}. Only 'repo' is currently supported."
            )

    def expand_to_context(self, to_add: dict[str, Any]):
        """Expands any string values in to_add using the current context and updates the context.

        This allows scripts to add new context variables - with general python expressions inside
        """
        for key, value in to_add.items():
            if isinstance(value, str):
                expanded_value = expand_context_unsafe(value, self.context)
                self.context[key] = expanded_value
            else:
                self.context[key] = value

    def run_stage(self, stage: dict) -> None:
        """
        Executes a single processing stage.

        Args:
            stage: A dictionary representing the stage configuration, containing
                   at least 'tool' and 'script' keys.
        """
        stage_desc = stage.get("description", "(missing description)")
        stage_disabled = stage.get("disabled", False)
        if stage_disabled:
            logging.info(f"Skipping disabled stage: {stage_desc}")
            return

        logging.info(f"Running stage: {stage_desc}")

        tool_dict = stage.get("tool")
        if not tool_dict:
            raise ValueError(f"Stage '{stage.get('name')}' is missing a 'tool' definition.")
        tool_name = tool_dict.get("name")
        if not tool_name:
            raise ValueError(f"Stage '{stage.get('name')}' is missing a 'tool.name' definition.")
        tool = tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' for stage '{stage.get('name')}' not found.")
        logging.debug(f"Using tool: {tool_name}")
        tool.set_defaults()

        # Allow stage to override tool timeout if specified
        tool_timeout = tool_dict.get("timeout")
        if tool_timeout is not None:
            tool.timeout = float(tool_timeout)
            logging.debug(f"Using tool timeout: {tool.timeout} seconds")

        # is the script included inline?
        script = stage.get("script")
        if script:
            script = textwrap.dedent(script)  # it might be indented in the toml
        else:
            # try to load it from a file
            script_filename = stage.get("script-file", tool.default_script_file)
            if script_filename:
                source = stage.source  # type: ignore (was monkeypatched by repo)
                try:
                    script = source.read(script_filename)
                except OSError as e:
                    raise ValueError(f"Error reading script file '{script_filename}'") from e

        if script is None:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'script' or 'script-file' definition."
            )

        # This allows recipe TOML to define their own default variables.
        # (apply all of the changes to context that the task demands)
        stage_context = stage.get("context", {})
        self.expand_to_context(stage_context)
        self.add_output_path(stage)

        try:
            self.add_input_files(stage)
            self.add_input_masters(stage)

            # if the output path already exists and is newer than all input files, skip processing
            output_info: dict | None = self.context.get("output")
            if output_info and not starbash.force_regen:
                output_path = output_info.get("full_path")
                if output_path:
                    # output_path might contain * wildcards, make output_files be a list
                    output_files = glob.glob(str(output_path))
                    if len(output_files) > 0:
                        logging.info(
                            f"Output file already exists, skipping processing: {output_path}"
                        )
                        return

            # We normally run tools in a temp dir, but if input.source is recipe we assume we want to
            # run in the shared processing directory.  Because prior stages output files are waiting for us there.
            cwd = None
            if stage.get("input", {}).get("source") == "recipe":
                cwd = self.context.get("process_dir")

            tool.run(script, context=self.context, cwd=cwd)
        except NotEnoughFilesError as e:
            # Not enough input files provided
            input_files = e.files
            if len(input_files) != 1:
                raise  # We only handle the single file case here

            # Copy the single input file to the output path
            output_path = self.context.get("output", {}).get("full_path")
            if output_path:
                shutil.copy(input_files[0], output_path)
                logging.warning(f"Copied single master from {input_files[0]} to {output_path}")
            else:
                # no output path specified, re-raise
                raise

        # verify context.output was created if it was specified
        output_info: dict | None = self.context.get("output")
        if output_info:
            output_path = output_info[
                "full_path"
            ]  # This must be present, because we created it when we made the output node

            # output_path might contain * wildcards, make output_files be a list
            output_files = glob.glob(str(output_path))

            if len(output_files) < 1:
                raise RuntimeError(f"Expected output file not found: {output_path}")
            else:
                if output_info["repo"].kind() == "master":
                    # we add new masters to our image DB
                    # add to image DB (ONLY! we don't also create a session)
                    self.add_image(output_info["repo"], Path(output_path), force=True)
