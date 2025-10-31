import logging
from importlib import resources
from pathlib import Path
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

import starbash
from starbash import console, _is_test_env
from starbash.database import Database
from repo.manager import Repo
from starbash.tool import Tool
from repo import RepoManager
from starbash.tool import tools
from starbash.paths import get_user_config_dir, get_user_data_dir
from starbash.selection import Selection
from starbash.analytics import (
    NopAnalytics,
    analytics_exception,
    analytics_setup,
    analytics_shutdown,
    analytics_start_transaction,
)


def setup_logging():
    """
    Configures basic logging.
    """
    handlers = [RichHandler(rich_tracebacks=True)] if not _is_test_env else []
    logging.basicConfig(
        level=starbash.log_filter_level,  # use the global log filter level
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )


def get_user_config_path() -> Path:
    """Returns the path to the user config file."""
    config_dir = get_user_config_dir()
    return config_dir / "starbash.toml"


def create_user() -> Path:
    """Create user directories if they don't exist yet."""
    path = get_user_config_path()
    if not path.exists():
        tomlstr = (
            resources.files("starbash")
            .joinpath("templates/userconfig.toml")
            .read_text()
        )
        toml = tomlkit.parse(tomlstr)
        TOMLFile(path).write(toml)
        logging.info(f"Created user config file: {path}")
    return get_user_config_dir()


def copy_images_to_dir(images: list[dict[str, Any]], output_dir: Path) -> None:
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


class Starbash:
    """The main Starbash application class."""

    def __init__(self, cmd: str = "unspecified"):
        """
        Initializes the Starbash application by loading configurations
        and setting up the repository manager.
        """
        setup_logging()
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

        self.db = Database()
        self.session_query = None  # None means search all sessions

        # Initialize selection state
        data_dir = get_user_data_dir()
        selection_file = data_dir / "selection.json"
        self.selection = Selection(selection_file)

        # FIXME, call reindex somewhere and also index whenever new repos are added
        # self.reindex_repos()

    # --- Lifecycle ---
    def close(self) -> None:
        self.analytics.__exit__(None, None, None)

        analytics_shutdown()
        self.db.close()

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

    def search_session(self) -> list[dict[str, Any]]:
        """Search for sessions, optionally filtered by the current selection."""
        # Get query conditions from selection
        conditions = self.selection.get_query_conditions()
        return self.db.search_session(conditions)

    def get_session_images(self, session_id: int) -> list[dict[str, Any]]:
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
        # First get the session details
        session = self.db.get_session_by_id(session_id)
        if session is None:
            raise ValueError(f"Session with id {session_id} not found")

        # Query images that match ALL session criteria including date range
        conditions = {
            Database.FILTER_KEY: session[Database.FILTER_KEY],
            Database.IMAGETYP_KEY: session[Database.IMAGETYP_KEY],
            Database.OBJECT_KEY: session[Database.OBJECT_KEY],
            Database.TELESCOP_KEY: session[Database.TELESCOP_KEY],
            "date_start": session[Database.START_KEY],
            "date_end": session[Database.END_KEY],
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

    def test_processing(self):
        """A crude test of image processing pipeline - FIXME move into testing"""
        self.run_all_stages()

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

        # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
        task_definitions = self.repo_manager.merged.getall("stage")
        all_tasks = list(itertools.chain.from_iterable(task_definitions))

        logging.info(
            f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority."
        )

        self.start_session()
        # 4. Iterate through the sorted pipeline and execute the associated tasks.
        for step in sorted_pipeline:
            step_name = step.get("name")
            if not step_name:
                raise ValueError("Invalid pipeline step found: missing 'name' key.")

            logging.info(
                f"--- Running pipeline step: '{step_name}' (Priority: {step['priority']}) ---"
            )
            # Find all tasks that should run during this pipeline step.
            tasks_to_run = [task for task in all_tasks if task.get("when") == step_name]
            for task in tasks_to_run:
                self.run_stage(task)

    def start_session(self) -> None:
        """Do common session init"""

        # Context is preserved through all stages, so each stage can add new symbols to it for use by later stages
        self.context = {}

        # Update the context with runtime values.
        runtime_context = {
            "process_dir": "/workspaces/starbash/images/process",  # FIXME - create/find this more correctly per session
            "masters": "/workspaces/starbash/images/masters",  # FIXME find this the correct way
        }
        self.context.update(runtime_context)

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
        stage_context = stage.get("context", {})
        self.context.update(stage_context)

        # Assume no files for this stage
        if "input_files" in self.context:
            del self.context["input_files"]

        input_files = []
        input_config = stage.get("input")
        input_required = False
        if input_config:
            # if there is an "input" dict, we assume input.required is true if unset
            input_required = input_config.get("required", True)
            if "path" in input_config:
                # The path might contain context variables that need to be expanded.
                # path_pattern = expand_context(input_config["path"], context)
                path_pattern = input_config["path"]
                input_files = glob.glob(path_pattern, recursive=True)

            self.context["input_files"] = (
                input_files  # Pass in the file list via the context dict
            )

        if input_required and not input_files:
            raise RuntimeError("No input files found for stage")

        tool.run_in_temp_dir(script, context=self.context)
