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
from starbash.database import Database, SessionRow, ImageRow, get_column_name
from repo import Repo, repo_suffix
from starbash.toml import toml_from_template
from starbash.tool import Tool, expand_context
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
    """Copy images to the specified output directory (using symbolic links if possible)."""

    # Export images
    console.print(f"[cyan]Exporting {len(images)} images to {output_dir}...[/cyan]")

    linked_count = 0
    copied_count = 0
    error_count = 0

    for image in images:
        # Get the source path from the image metadata
        source_path = Path(image.get("path", ""))

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


def imagetyp_equals(imagetyp1: str, imagetyp2: str) -> bool:
    """Imagetyps (BIAS, Dark, FLAT, flats) have a number of slightly different convetions.
    Do a sloppy equality check.

    Eventually handle non english variants by using the repos aliases table."""
    return imagetyp1.strip().lower() == imagetyp2.strip().lower()


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
        self.repo_manager = RepoManager()
        self.repo_manager.add_repo("pkg://defaults")

        # Add user prefs as a repo
        self.user_repo = self.repo_manager.add_repo("file://" + str(create_user()))

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

        logging.info(
            f"Repo manager initialized with {len(self.repo_manager.repos)} repos."
        )
        # self.repo_manager.dump()

        self._db = None  # Lazy initialization - only create when accessed
        self.session_query = None  # None means search all sessions

        # Initialize selection state (stored in user config repo)
        self.selection = Selection(self.user_repo)

        # FIXME, call reindex somewhere and also index whenever new repos are added
        # self.reindex_repos()

    @property
    def db(self) -> Database:
        """Lazy initialization of database - only created as needed."""
        if self._db is None:
            self._db = Database()
        return self._db

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

    def _add_session(self, f: str, image_doc_id: int, header: dict) -> None:
        """We just added a new image, create or update its session entry as needed."""
        filter = header.get(Database.FILTER_KEY, "unspecified")
        image_type = header.get(Database.IMAGETYP_KEY)
        date = header.get(Database.DATE_OBS_KEY)
        if not date or not image_type:
            logging.warning(
                "Image %s missing either DATE-OBS or IMAGETYP FITS header, skipping...",
                f,
            )
        else:
            exptime = header.get(Database.EXPTIME_KEY, 0)
            telescop = header.get(Database.TELESCOP_KEY, "unspecified")
            new = {
                Database.FILTER_KEY: filter,
                Database.START_KEY: date,
                Database.END_KEY: date,  # FIXME not quite correct, should be longer by exptime
                Database.IMAGE_DOC_KEY: image_doc_id,
                Database.IMAGETYP_KEY: image_type,
                Database.NUM_IMAGES_KEY: 1,
                Database.EXPTIME_TOTAL_KEY: exptime,
                Database.OBJECT_KEY: header.get(Database.OBJECT_KEY, "unspecified"),
                Database.TELESCOP_KEY: telescop,
            }
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
        ref_image = self.get_session_image(ref_session)
        ref_temp = ref_image.get("CCD-TEMP", None)
        ref_date_str = ref_image.get(Database.DATE_OBS_KEY)

        # Parse reference date for time delta calculations
        ref_date = None
        if ref_date_str:
            try:
                ref_date = datetime.fromisoformat(ref_date_str)
            except (ValueError, TypeError):
                logging.warning(f"Malformed session ref date: {ref_date_str}")

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

        # Now score and sort the candidates
        scored_candidates = []

        for candidate in candidates:
            score = 0.0

            # Get candidate image metadata to access CCD-TEMP and DATE-OBS
            try:
                candidate_image = self.get_session_image(candidate)

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

                # Score by date/time proximity (secondary importance)
                if ref_date is not None:
                    candidate_date_str = candidate_image.get(Database.DATE_OBS_KEY)
                    if candidate_date_str:
                        try:
                            candidate_date = datetime.fromisoformat(candidate_date_str)
                            time_delta = abs(
                                (ref_date - candidate_date).total_seconds()
                            )
                            # Closer in time = better score
                            # Same day ≈ 100, 7 days ≈ 37, 30 days ≈ 9
                            # Using 7-day half-life
                            score += 100 * (2.718 ** (-time_delta / (7 * 86400)))
                        except (ValueError, TypeError):
                            logging.warning(
                                f"Could not parse candidate date: {candidate_date_str}"
                            )

                scored_candidates.append((score, candidate))

            except (AssertionError, KeyError) as e:
                # If we can't get the session image, log and skip this candidate
                logging.warning(
                    f"Could not score candidate session {candidate.get('id')}: {e}"
                )
                continue

        # Sort by score (highest first) and return just the sessions
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        return [candidate for score, candidate in scored_candidates]

    def search_session(self) -> list[SessionRow]:
        """Search for sessions, optionally filtered by the current selection."""
        # Get query conditions from selection
        conditions = self.selection.get_query_conditions()
        return self.db.search_session(conditions)

    def get_session_image(self, session: SessionRow) -> ImageRow:
        """
        Get the reference ImageRow for a session.
        """
        images = self.db.search_image(
            {Database.ID_KEY: session[get_column_name(Database.IMAGE_DOC_KEY)]}
        )
        assert (
            len(images) == 1
        ), f"Expected exactly one reference for session, found {len(images)}"
        return images[0]

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
        # Query images that match ALL session criteria including date range
        conditions = {
            Database.FILTER_KEY: session[get_column_name(Database.FILTER_KEY)],
            Database.IMAGETYP_KEY: session[get_column_name(Database.IMAGETYP_KEY)],
            Database.OBJECT_KEY: session[get_column_name(Database.OBJECT_KEY)],
            Database.TELESCOP_KEY: session[get_column_name(Database.TELESCOP_KEY)],
            "date_start": session[get_column_name(Database.START_KEY)],
            "date_end": session[get_column_name(Database.END_KEY)],
        }

        # Single query with all conditions
        images = self.db.search_image(conditions)
        return images if images else []

    def remove_repo_ref(self, url: str) -> None:
        """
        Remove a repository reference from the user configuration.

        Args:
            url: The repository URL to remove (e.g., 'file:///path/to/repo')

        Raises:
            ValueError: If the repository URL is not found in user configuration
        """
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

    def reindex_repo(self, repo: Repo, force: bool = False):
        """Reindex all repositories managed by the RepoManager."""
        # FIXME, add a method to get just the repos that contain images
        if repo.is_scheme("file") and repo.kind != "recipe":
            logging.debug("Reindexing %s...", repo.url)

            whitelist = None
            config = self.repo_manager.merged.get("config")
            if config:
                whitelist = config.get("fits-whitelist", None)

            path = repo.get_path()
            if not path:
                raise ValueError(f"Repo path not found for {repo}")

            # Find all FITS files under this repo path
            for f in track(
                list(path.rglob("*.fit*")),
                description=f"Indexing {repo.url}...",
            ):
                # progress.console.print(f"Indexing {f}...")
                try:
                    found = self.db.get_image(str(f))
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
                            headers["path"] = str(f)
                            image_doc_id = self.db.upsert_image(headers)

                            if not found:
                                # Update the session infos, but ONLY on first file scan
                                # (otherwise invariants will get messed up)
                                self._add_session(str(f), image_doc_id, header)

                except Exception as e:
                    logging.warning("Failed to read FITS header for %s: %s", f, e)

    def reindex_repos(self, force: bool = False):
        """Reindex all repositories managed by the RepoManager."""
        logging.debug("Reindexing all repositories...")

        for repo in track(self.repo_manager.repos, description="Reindexing repos..."):
            self.reindex_repo(repo, force=force)

    def run_all_stages(self):
        """On the currently active session, run all processing stages"""
        logging.info("--- Running all stages ---")

        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).
        pipeline_definitions = self.repo_manager.merged.getall("stages")
        flat_pipeline_steps = list(itertools.chain.from_iterable(pipeline_definitions))

        # 2. Sort the pipeline steps by their 'priority' field.
        try:
            sorted_pipeline = sorted(flat_pipeline_steps, key=lambda s: s["priority"])
        except KeyError as e:
            # Re-raise as a ValueError with a more descriptive message.
            raise ValueError(
                f"invalid stage definition: a stage is missing the required 'priority' key"
            ) from e

        logging.info(
            f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority."
        )

        self.init_context()
        # 4. Iterate through the sorted pipeline and execute the associated tasks.
        for step in sorted_pipeline:
            step_name = step.get("name")
            if not step_name:
                raise ValueError("Invalid pipeline step found: missing 'name' key.")
            self.run_pipeline_step(step_name)

    def run_pipeline_step(self, step_name: str):
        logging.info(f"--- Running pipeline step: '{step_name}' ---")

        # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
        task_definitions = self.repo_manager.merged.getall("stage")
        all_tasks = list(itertools.chain.from_iterable(task_definitions))

        # Find all tasks that should run during this pipeline step.
        tasks_to_run = [task for task in all_tasks if task.get("when") == step_name]
        for task in tasks_to_run:
            self.run_stage(task)

    def run_master_stages(self):
        """Generate any missing master frames

        Steps:
        * set all_tasks to be all tasks for when == "setup.masters"
        * loop over all currently unfiltered sessions
        * for each session loop across all_tasks
        * if task input.type == the imagetyp for this current session
        *    add_input_to_context() add the input files to the context (from the session)
        *    run_stage(task) to generate the new master frame
        """
        sessions = self.search_session()
        for session in sessions:
            imagetyp = session[get_column_name(Database.IMAGETYP_KEY)]
            logging.debug(
                f"Processing session ID {session[get_column_name(Database.ID_KEY)]} with imagetyp '{imagetyp}'"
            )

            # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
            task_definitions = self.repo_manager.merged.getall("stage")
            all_tasks = list(itertools.chain.from_iterable(task_definitions))

            # Find all tasks that should run during the "setup.masters" step.
            tasks_to_run = [
                task for task in all_tasks if task.get("when") == "setup.masters"
            ]

            for task in tasks_to_run:
                input_config = task.get("input", {})
                input_type = input_config.get("type")
                if imagetyp_equals(input_type, imagetyp):
                    logging.info(
                        f"  Running master stage task for imagetyp '{imagetyp}'"
                    )

                    # Create a default process dir in /tmp, though more advanced 'session' based workflows will
                    # probably override this and place it somewhere persistent.
                    with tempfile.TemporaryDirectory(prefix="session_tmp_") as temp_dir:
                        logging.debug(
                            f"Created temporary session directory: {temp_dir}"
                        )
                        self.init_context()
                        self.context["process_dir"] = temp_dir
                        self.add_session_to_context(session)
                        self.run_stage(task)

    def init_context(self) -> None:
        """Do common session init"""

        # Context is preserved through all stages, so each stage can add new symbols to it for use by later stages
        self.context = {}

        # Update the context with runtime values.
        runtime_context = {
            "masters": "/workspaces/starbash/images/masters",  # FIXME find this the correct way
        }
        self.context.update(runtime_context)

    def add_session_to_context(self, session: SessionRow) -> None:
        """adds to context from the indicated session:
        * input_files - all of the files mentioned in the session
        * instrument - for the session
        * date - the localtimezone date of the session
        * imagetyp - the imagetyp of the session
        * session - the current session row (joined with a typical image) (can be used to
        find things like telescope, temperature ...)
        """
        # Get images for this session
        images = self.get_session_images(session)
        logging.debug(f"Adding {len(images)} files as context.input_files")
        self.context["input_files"] = [
            img["path"] for img in images
        ]  # Pass in the file list via the context dict

        # it is okay to give them the actual session row, because we're never using it again
        self.context["session"] = session

        instrument = session.get(get_column_name(Database.TELESCOP_KEY))
        if instrument:
            self.context["instrument"] = instrument

        imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))
        if imagetyp:
            self.context["imagetyp"] = imagetyp

        date = session.get(get_column_name(Database.START_KEY))
        if date:
            self.context["date"] = to_shortdate(date)

    def add_input_files(self, stage: dict) -> None:
        """adds to context.input_files based on the stage input config"""
        input_config = stage.get("input")
        input_required = False
        if input_config:
            # if there is an "input" dict, we assume input.required is true if unset
            input_required = input_config.get("required", True)
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
                # We expect that higher level code has already added the correct input files
                # to the context
                if not "input_files" in self.context:
                    raise RuntimeError(
                        "Input config specifies 'repo' but no 'input_files' found in context"
                    )
            else:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' source: {source}"
                )

            # FIXME compare context.output to see if it already exists and is newer than the input files, if so skip processing
        else:
            # The script doesn't mention input, therefore assume it doesn't want input_files
            if "input_files" in self.context:
                del self.context["input_files"]

        if input_required and not "input_files" in self.context:
            raise RuntimeError("No input files found for stage")

    def add_output_path(self, stage: dict) -> None:
        """Adds output path information to context based on the stage output config.

        Sets the following context variables:
        - context.output.root_path - base path of the destination repo
        - context.output.base_path - full path without file extension
        - context.output.suffix - file extension (e.g., .fits or .fit.gz)
        - context.output.full_path - complete output file path
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
            repo_relative = expand_context(repo_relative, self.context)
            full_path = repo_base / repo_relative

            suffix = ".fits"

            # Set context variables as documented in the TOML
            self.context["output"] = {
                # "root_path": repo_relative, not needed I think
                "base_path": full_path.stem,
                # "suffix": full_path.suffix, not needed I think
                "full_path": full_path,
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

        tool_name = stage.get("tool")
        if not tool_name:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'tool' definition."
            )
        tool: Tool | None = tools.get(tool_name)
        if not tool:
            raise ValueError(
                f"Tool '{tool_name}' for stage '{stage.get('name')}' not found."
            )
        logging.debug(f"  Using tool: {tool_name}")

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
        self.add_output_path(stage)

        tool.run_in_temp_dir(script, context=self.context)

        # verify context.output was created if it was specified
        if "output" in self.context:
            output_info = self.context["output"]
            # Handle both old string format and new dict format
            if isinstance(output_info, dict):
                output_path = output_info.get("full_path")
            else:
                output_path = output_info

            if output_path and not os.path.exists(output_path):
                raise RuntimeError(f"Expected output file not found: {output_path}")
