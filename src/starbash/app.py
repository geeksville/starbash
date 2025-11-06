import cmd
import logging
from importlib import resources
import os
from pathlib import Path
import tempfile
import typer
import tomlkit
from tomlkit.toml_file import TOMLFile
import glob
from typing import Any
from astropy.io import fits
import itertools
from rich.progress import track
from rich.logging import RichHandler
import shutil
from datetime import datetime
import rich.console
import copy

import starbash
from starbash import console, _is_test_env, to_shortdate
from starbash.aliases import Aliases
from starbash.database import Database, SessionRow, ImageRow, get_column_name
from repo import Repo, repo, repo_suffix
from starbash.toml import toml_from_template
from starbash.tool import Tool, expand_context, expand_context_unsafe
from repo import RepoManager
from starbash.tool import tools
from starbash.paths import get_user_config_dir, get_user_data_dir
from starbash.selection import Selection, where_tuple
from starbash.analytics import (
    NopAnalytics,
    analytics_exception,
    analytics_setup,
    analytics_shutdown,
    analytics_start_transaction,
)

# Type aliases for better documentation


def setup_logging(stderr: bool = False):
    """
    Configures basic logging.
    """
    console = rich.console.Console(stderr=stderr)
    handlers = (
        [RichHandler(console=console, rich_tracebacks=True)] if not _is_test_env else []
    )
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
    console.print(f"[green]Export complete![/green]")
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
        super().__init__(prefix="sbprocessing_")
        self.sb = starbash
        logging.debug(f"Created processing context at {self.name}")

        self.sb.init_context()
        self.sb.context["process_dir"] = self.name

    def __enter__(self) -> "ProcessingContext":
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        logging.debug(f"Cleaning up processing context at {self.name}")

        # unregister our process dir
        self.sb.context.pop("process_dir", None)

        super().__exit__(exc_type, exc_value, traceback)


class Starbash:
    """The main Starbash application class."""

    def __init__(self, cmd: str = "unspecified", stderr_logging: bool = False):
        """
        Initializes the Starbash application by loading configurations
        and setting up the repository manager.
        """
        setup_logging(stderr=stderr_logging)
        logging.info("Starbash starting...")

        # Load app defaults and initialize the repository manager
        self._init_repos()
        self._init_analytics(cmd)
        self._init_aliases()

        logging.info(
            f"Repo manager initialized with {len(self.repo_manager.repos)} repos."
        )
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
            user_email = (
                self.user_repo.get("user.email", None) if include_user else None
            )
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

    def _add_session(self, image_doc_id: int, header: dict) -> None:
        """We just added a new image, create or update its session entry as needed."""
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

    def guess_sessions(
        self, ref_session: SessionRow, want_type: str
    ) -> list[SessionRow]:
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
        if want_type.upper() == "FLAT":
            conditions[Database.FILTER_KEY] = ref_session[
                get_column_name(Database.FILTER_KEY)
            ]

        # Search for candidate sessions
        candidates = self.db.search_session(where_tuple(conditions))

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
                        logging.warning(f"Malformed date - ignoring entry")

                scored_candidates.append((score, candidate))

            except (AssertionError, KeyError) as e:
                # If we can't get the session image, log and skip this candidate
                logging.warning(
                    f"Could not score candidate session {candidate.get('id')}: {e}"
                )
                continue

        # Sort by score (highest first)
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        return [candidate for _, candidate in scored_candidates]

    def search_session(self) -> list[SessionRow]:
        """Search for sessions, optionally filtered by the current selection."""
        # Get query conditions from selection
        conditions = self.selection.get_query_conditions()
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
            [
                SearchCondition(
                    "i.id", "=", session[get_column_name(Database.IMAGE_DOC_KEY)]
                )
            ]
        )
        assert (
            len(images) == 1
        ), f"Expected exactly one reference for session, found {len(images)}"
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
        return images

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
            SearchCondition(
                "i.date_obs", ">=", session[get_column_name(Database.START_KEY)]
            ),
            SearchCondition(
                "i.date_obs", "<=", session[get_column_name(Database.END_KEY)]
            ),
            SearchCondition(
                "i.imagetyp", "=", session[get_column_name(Database.IMAGETYP_KEY)]
            ),
        ]

        # we never want to return 'master' images as part of the session image paths
        # (because we will be passing these tool siril or whatever to generate masters or
        # some other downstream image)
        master_repo = self.repo_manager.get_repo_by_kind("master")
        if master_repo is not None:
            conditions.append(SearchCondition("r.url", "<>", master_repo.url))

        # Single query with indexed date conditions
        images = self.db.search_image(conditions)

        # We no lognger filter by target(object) because it might not be set anyways
        filtered_images = []
        for img in images:
            if (
                img.get(Database.FILTER_KEY)
                == session[get_column_name(Database.FILTER_KEY)]
                # and img.get(Database.OBJECT_KEY)
                # == session[get_column_name(Database.OBJECT_KEY)]
                and img.get(Database.TELESCOP_KEY)
                == session[get_column_name(Database.TELESCOP_KEY)]
            ):
                filtered_images.append(img)

        # Reconstruct absolute paths for all images
        return (
            [self._add_image_abspath(img) for img in filtered_images]
            if filtered_images
            else []
        )

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
            raise ValueError(f"No repository references found in user configuration.")

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

    def add_image_to_db(self, repo: Repo, f: Path, force: bool = False) -> None:
        """Read FITS header from file and add/update image entry in the database."""

        path = repo.get_path()
        if not path:
            raise ValueError(f"Repo path not found for {repo}")

        whitelist = None
        config = self.repo_manager.merged.get("config")
        if config:
            whitelist = config.get("fits-whitelist", None)

        try:
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
                    logging.debug("Headers for %s: %s", f, headers)
                    # Store relative path in database
                    headers["path"] = str(relative_path)
                    image_doc_id = self.db.upsert_image(headers, repo.url)

                    if not found:
                        # Update the session infos, but ONLY on first file scan
                        # (otherwise invariants will get messed up)
                        self._add_session(image_doc_id, header)

        except Exception as e:
            logging.warning("Failed to read FITS header for %s: %s", f, e)

    def reindex_repo(self, repo: Repo, force: bool = False, subdir: str | None = None):
        """Reindex all repositories managed by the RepoManager."""

        # make sure this new repo is listed in the repos table
        self.repo_db_update()  # not really ideal, a more optimal version would just add the new repo

        path = repo.get_path()

        if path and repo.is_scheme("file") and repo.kind != "recipe":
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
                self.add_image_to_db(repo, f, force=force)

    def reindex_repos(self, force: bool = False):
        """Reindex all repositories managed by the RepoManager."""
        logging.debug("Reindexing all repositories...")

        for repo in track(self.repo_manager.repos, description="Reindexing repos..."):
            self.reindex_repo(repo, force=force)

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
                f"invalid stage definition: a stage is missing the required 'priority' key"
            ) from e

        logging.debug(
            f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority."
        )
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

    def get_recipe_for_session(
        self, session: SessionRow, step: dict[str, Any]
    ) -> Repo | None:
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
        recipe_repos = [r for r in self.repo_manager.repos if r.kind() == "recipe"]

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
                logging.debug(
                    f"Recipe {repo.url} does not have stage '{step_name}', skipping"
                )
                continue

            # Check auto.require conditions if they exist

            # If requirements are specified, check if session matches
            required_filters = repo.get("auto.require.filter", [])
            if required_filters:
                session_filter = self.aliases.normalize(
                    session_metadata.get(Database.FILTER_KEY)
                )

                # Session must have a filter that matches one of the required filters
                if not session_filter or session_filter not in required_filters:
                    logging.debug(
                        f"Recipe {repo.url} requires filters {required_filters}, "
                        f"session has '{session_filter}', skipping"
                    )
                    continue

            required_cameras = repo.get("auto.require.camera", [])
            if required_cameras:
                session_camera = self.aliases.normalize(
                    session_metadata.get("INSTRUME")
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

    def run_all_stages(self):
        """On the currently active session, run all processing stages

        New design, not yet implemented:
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
        # Not ready to use this yet
        pipeline = self._get_stages("stages")
        sessions = self.search_session()

        # FIXME add a loop over multiple different targets in current selection (via session.object)
        for session in track(sessions, description="Processing target..."):
            # target specific processing here

            with ProcessingContext(self):
                recipe = None
                for step in pipeline:
                    task = None

                    if not recipe:
                        # for the time being: The first step in the pipeline MUST be "light"
                        recipe = self.get_recipe_for_session(session, step)
                        if not recipe:
                            continue  # No recipe found for this target/session

                    # find the task for this step
                    if recipe:
                        task = recipe.get("recipe.stage." + step["name"])

                    if task:
                        # Create a default process dir in /tmp.
                        # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                        # dirs for particular targets?
                        self.set_session_in_context(session)
                        self.run_stage(task)

    def run_master_stages(self):
        """Generate any missing master frames

        Steps:
        * set all_tasks to be all tasks for when == "setup.master.bias"
        * loop over all currently unfiltered sessions
        * for each session loop across all_tasks
        * if task input.type == the imagetyp for this current session
        *    add_input_to_context() add the input files to the context (from the session)
        *    run_stage(task) to generate the new master frame
        """
        sorted_pipeline = self._get_stages("master-stages")
        sessions = self.search_session()
        for session in track(sessions, description="Generating masters..."):
            # 4. Iterate through the sorted pipeline and execute the associated tasks.
            # FIXME unify the master vs normal step running code
            for step in sorted_pipeline:
                task = None
                recipe = self.get_recipe_for_session(session, step)
                if recipe:
                    task = recipe.get("recipe.stage." + step["name"])

                if task:
                    # Create a default process dir in /tmp.
                    # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                    # dirs for particular targets?
                    with ProcessingContext(self):
                        self.set_session_in_context(session)
                        self.run_stage(task)

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
        * instrument - for the session
        * date - the localtimezone date of the session
        * imagetyp - the imagetyp of the session
        * session - the current session row (joined with a typical image) (can be used to
        find things like telescope, temperature ...)
        * session_config - a short human readable description of the session - suitable for logs or filenames
        """
        # it is okay to give them the actual session row, because we're never using it again
        self.context["session"] = session

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
            self.context["date"] = to_shortdate(date)

    def add_input_masters(self, stage: dict) -> None:
        """based on input.masters add the correct master frames as context.master.<type> filepaths"""
        session = self.context.get("session")
        assert session is not None, "context.session should have been already set"

        input_config = stage.get("input", {})
        master_types: list[str] = input_config.get("masters", [])
        for master_type in master_types:
            masters = self.get_master_images(
                imagetyp=master_type, reference_session=session
            )
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
                assert (
                    session is not None
                ), "context.session should have been already set"

                images = self.get_session_images(session)
                logging.debug(f"Using {len(images)} files as input_files")
                self.context["input_files"] = [
                    img["abspath"] for img in images
                ]  # Pass in the file list via the context dict
            else:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' source: {source}"
                )

            # FIXME compare context.output to see if it already exists and is newer than the input files, if so skip processing
        else:
            # The script doesn't mention input, therefore assume it doesn't want input_files
            if "input_files" in self.context:
                del self.context["input_files"]

        if input_required and len(self.context.get("input_files", [])) < input_required:
            raise RuntimeError(f"Stage requires at least {input_required} input files")

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
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'tool' definition."
            )
        tool_name = tool_dict.get("name")
        if not tool_name:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'tool.name' definition."
            )
        tool = tools.get(tool_name)
        if not tool:
            raise ValueError(
                f"Tool '{tool_name}' for stage '{stage.get('name')}' not found."
            )
        logging.debug(f"Using tool: {tool_name}")
        tool.set_defaults()

        # Allow stage to override tool timeout if specified
        tool_timeout = tool_dict.get("timeout")
        if tool_timeout is not None:
            tool.timeout = float(tool_timeout)
            logging.debug(f"Using tool timeout: {tool.timeout} seconds")

        script_filename = stage.get("script-file", tool.default_script_file)
        if script_filename:
            source = stage.source  # type: ignore (was monkeypatched by repo)
            script = source.read(script_filename)
        else:
            script = stage.get("script")

        if script is None:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'script' or 'script-file' definition."
            )

        # This allows recipe TOML to define their own default variables.
        # (apply all of the changes to context that the task demands)
        stage_context = stage.get("context", {})
        self.context.update(stage_context)
        self.add_input_files(stage)
        self.add_input_masters(stage)
        self.add_output_path(stage)

        # if the output path already exists and is newer than all input files, skip processing
        output_info: dict | None = self.context.get("output")
        if output_info:
            output_path = output_info.get("full_path")

            if output_path and os.path.exists(output_path):
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

        # verify context.output was created if it was specified
        output_info: dict | None = self.context.get("output")
        if output_info:
            output_path = output_info.get("full_path")

            if not output_path or not os.path.exists(output_path):
                raise RuntimeError(f"Expected output file not found: {output_path}")
            else:
                self.add_image_to_db(output_info["repo"], Path(output_path), force=True)
