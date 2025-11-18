import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import rich.console
import tomlkit
import typer
from astropy.io import fits
from rich.logging import RichHandler
from rich.progress import track
from tomlkit.items import Item

import starbash
from repo import Repo, RepoManager, repo_suffix
from starbash.aliases import (
    Aliases,
    normalize_target_name,
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
    metadata_to_camera_id,
    metadata_to_instrument_id,
)
from starbash.dwarf3 import extend_dwarf3_headers
from starbash.paths import get_user_config_dir, get_user_config_path
from starbash.selection import Selection, build_search_conditions
from starbash.toml import toml_from_template
from starbash.tool import preflight_tools

critical_keys = [Database.DATE_OBS_KEY, Database.IMAGETYP_KEY]


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
        handlers=handlers,
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


@dataclass
class ScoredCandidate:
    """Our helper structure for scoring candidate sessions will return lists of these."""

    candidate: dict[str, Any]  # the scored candidate
    score: float  # a score - higher is better.  higher scores will be at the head of the list
    reason: str  # short explanation of why this score

    @property
    def comment(self) -> str:
        """Generate a comment string for this candidate."""
        return f"{round(self.score)} {self.reason}"

    @property
    def as_toml(self) -> Item:
        """As a formatted toml node with documentation comment"""
        s: str = self.candidate["path"]  # Must be defined by now, FIXME, use abspath instead?
        result = tomlkit.string(s)
        result.comment(self.comment)
        return result


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
        preflight_tools()

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
        if exc and not isinstance(exc, typer.Exit) and not isinstance(exc, KeyboardInterrupt):
            handled = analytics_exception(exc)
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
            logging.warning("Using existing repository config file: %s", repo_toml)
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

        return self.score_candidates(candidates, ref_session)

    def score_candidates(
        self, candidates: list[dict[str, Any]], ref_session: SessionRow
    ) -> list[ScoredCandidate]:
        """Given a list of images or sessions, try to rank that list by desirability.

        Return a list of possible images/sessions which would be acceptable.  The more desirable
        matches are first in the list.  Possibly in the future I might have a 'score' and reason
        given for each ranking.

        The following critera MUST match to be acceptable:
        * matches requested imagetyp.
        * same telescope as reference session

        Quality is determined by (most important first):
        * GAIN setting is as close as possible to the reference session (very high penalty for mismatch)
        * same filter as reference session (in the case want_type==FLAT only)
        * smaller DATE-OBS delta to the reference session (within same week beats 5°C temp difference)
        * temperature of CCD-TEMP is closer to the reference session

        Eventually the code will check the following for 'nice to have' (but not now):
        * TBD

                Implementation notes:
                - This uses a list of inner "ranker" functions that each compute a score contribution
                    and may append to a shared 'reasons' list from the outer closure. This makes it easy
                    to add new ranking dimensions by appending another function to the list.

        """

        metadata: dict = ref_session.get("metadata", {})

        # Now score and sort the candidates
        scored_candidates: list[ScoredCandidate] = []

        for candidate in candidates:
            score = 0.0
            reasons: list[str] = []

            # Get candidate image metadata to access CCD-TEMP and DATE-OBS
            try:
                candidate_image = candidate  # metadata is already in the root of this object

                # Define rankers that close over candidate_image, ref_* and reasons
                def rank_gain(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Score by GAIN difference: prefer exact match, penalize mismatch."""
                    ref_gain = metadata.get(Database.GAIN_KEY, None)
                    if ref_gain is None:
                        return 0.0
                    candidate_gain = candidate_image.get(Database.GAIN_KEY)
                    if candidate_gain is None:
                        return 0.0
                    try:
                        gain_diff = abs(float(ref_gain) - float(candidate_gain))
                        # Massive bonus for exact match, linear heavy penalty otherwise
                        gain_score = 30000 - 1000 * gain_diff
                        if gain_diff > 0:
                            reasons.append(f"gain Δ={gain_diff:.0f}")
                        else:
                            reasons.append("gain match")
                        return float(gain_score)
                    except (ValueError, TypeError):
                        return 0.0

                def rank_temp(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Score by CCD-TEMP difference: prefer closer temperatures."""
                    ref_temp = metadata.get("CCD-TEMP", None)
                    if ref_temp is None:
                        return 0.0
                    candidate_temp = candidate_image.get("CCD-TEMP")
                    if candidate_temp is None:
                        return 0.0
                    try:
                        temp_diff = abs(float(ref_temp) - float(candidate_temp))
                        # Exponential decay: closer temps get better scores
                        temp_score = 500 * (2.718 ** (-temp_diff / 5))
                        if temp_diff >= 0.2:  # don't report tiny differences
                            reasons.append(f"temp Δ={temp_diff:.1f}°C")
                        return float(temp_score)
                    except (ValueError, TypeError):
                        return 0.0

                def rank_time(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Score by time difference: prefer older or slightly newer candidates."""
                    ref_date_str = metadata.get(Database.DATE_OBS_KEY)
                    candidate_date_str = candidate_image.get(Database.DATE_OBS_KEY)
                    if not (ref_date_str and candidate_date_str):
                        return 0.0
                    try:
                        ref_date = datetime.fromisoformat(ref_date_str)  # type: ignore[arg-type]
                        candidate_date = datetime.fromisoformat(candidate_date_str)
                        time_delta = (candidate_date - ref_date).total_seconds()
                        days_diff = time_delta / 86400
                        # Prefer candidates OLDER or less than 2 days newer
                        if time_delta <= 0 or days_diff <= 2.0:
                            # 7-day half-life, weighted higher than temp
                            time_score = 1000 * (2.718 ** (-abs(time_delta) / (7 * 86400)))
                            reasons.append(f"time Δ={days_diff:.1f}d")
                        else:
                            # Penalize candidates >2 days newer by 10x
                            time_score = 100 * (2.718 ** (-abs(time_delta) / (7 * 86400)))
                            reasons.append(f"time Δ={days_diff:.1f}d (in future!)")
                        return float(time_score)
                    except (ValueError, TypeError):
                        logging.warning("Malformed date - ignoring entry")
                        return 0.0

                def rank_instrument(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Penalize instrument mismatch between reference and candidate."""
                    ref_instrument = metadata_to_instrument_id(metadata)
                    candidate_instrument = metadata_to_instrument_id(candidate_image)
                    if ref_instrument != candidate_instrument:
                        reasons.append("instrument mismatch")
                        return -200000.0
                    return 0.0

                def rank_camera(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Penalize camera mismatch between reference and candidate."""
                    ref_camera = metadata_to_camera_id(metadata)
                    candidate_camera = metadata_to_camera_id(candidate_image)
                    if ref_camera != candidate_camera:
                        reasons.append("camera mismatch")
                        return -300000.0
                    return 0.0

                def rank_camera_dimensions(
                    reasons=reasons, candidate_image=candidate_image
                ) -> float:
                    """Penalize if camera dimensions do not match (NAXIS, NAXIS1, NAXIS2)."""
                    dimension_keys = ["NAXIS", "NAXIS1", "NAXIS2"]
                    for key in dimension_keys:
                        ref_value = metadata.get(key)
                        candidate_value = candidate_image.get(key)
                        if ref_value != candidate_value:
                            reasons.append(f"{key} mismatch")
                            return float("-inf")
                    return 0.0

                def rank_flat_filter(reasons=reasons, candidate_image=candidate_image) -> float:
                    """Heavily penalize FLAT frames whose FILTER metadata does not match the reference.

                    Only applies if the candidate imagetyp is FLAT. Missing filter values are treated as None
                    and do not cause a penalty (neutral)."""
                    imagetyp = self.aliases.normalize(
                        candidate_image.get(Database.IMAGETYP_KEY), lenient=True
                    )
                    if imagetyp and imagetyp == "flat":
                        ref_filter = self.aliases.normalize(
                            metadata.get(Database.FILTER_KEY, "None"), lenient=True
                        )
                        candidate_filter = self.aliases.normalize(
                            candidate_image.get(Database.FILTER_KEY, "None"), lenient=True
                        )
                        if ref_filter != candidate_filter:
                            reasons.append("filter mismatch")
                            return -100000.0
                        else:
                            reasons.append("filter match")
                    return 0.0

                rankers = [
                    rank_gain,
                    rank_temp,
                    rank_time,
                    rank_instrument,
                    rank_camera,
                    rank_camera_dimensions,
                    rank_flat_filter,
                ]

                # Apply all rankers and check for unusable candidates
                for r in rankers:
                    contribution = r()
                    score += contribution
                    # If any ranker returns -inf, this candidate is unusable
                    if contribution == float("-inf"):
                        break

                # Only keep usable candidates
                if score != float("-inf"):
                    reason = ", ".join(reasons) if reasons else "no scoring factors"
                    scored_candidates.append(
                        ScoredCandidate(candidate=candidate, score=score, reason=reason)
                    )

            except (AssertionError, KeyError) as e:
                # If we can't get the session image, log and skip this candidate
                logging.warning(f"Could not score candidate session {candidate.get('id')}: {e}")
                continue

        # Sort by score (highest first)
        scored_candidates.sort(key=lambda x: x.score, reverse=True)

        return scored_candidates

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

    def _extend_image_header(self, headers: dict[str, Any], full_image_path: Path) -> bool:
        """Given a FITS header dictionary, possibly extend it with additional computed fields.
        Returns True if the header is invalid and should be skipped."""

        def has_critical_keys() -> bool:
            return all(key in headers for key in critical_keys)

        if not has_critical_keys():
            # See if possibly from a Dwarf3 camera which needs special handling
            extend_dwarf3_headers(headers, full_image_path)

            # Perhaps it saved us
            if not has_critical_keys():
                logging.debug(f"Headers {headers}")
                logging.warning(
                    "Image '%s' missing required FITS header (DATE-OBS or IMAGETYP), skipping...",
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

                # Some device software (old Asiair versions) fails to populate TELESCOP, in that case fall back to
                # CREATOR (see doc/fits/malformedasimaster.txt for an example)
                if Database.TELESCOP_KEY not in headers:
                    creator = headers.get("CREATOR")
                    if creator:
                        headers[Database.TELESCOP_KEY] = creator

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
                    session_metadata.get(Database.INSTRUME_KEY), lenient=True
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
