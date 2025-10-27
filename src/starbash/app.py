import logging
from importlib import resources
from pathlib import Path

import tomlkit
from tomlkit.toml_file import TOMLFile
import glob
from typing import Any
from astropy.io import fits
import itertools
from rich.progress import track
from rich.logging import RichHandler
from starbash.database import Database
from starbash.repo.manager import Repo
from starbash.tool import Tool
from starbash.repo import RepoManager
from starbash.tool import tools
from starbash.paths import get_user_config_dir


def setup_logging():
    """
    Configures basic logging.
    """
    logging.basicConfig(
        level="INFO",  # don't print messages of lower priority than this
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


setup_logging()


def create_user() -> Path:
    """Create user directories if they don't exist yet."""
    config_dir = get_user_config_dir()
    userconfig_path = config_dir / "starbash.toml"
    if not (userconfig_path).exists():
        tomlstr = (
            resources.files("starbash")
            .joinpath("templates/userconfig.toml")
            .read_text()
        )
        toml = tomlkit.parse(tomlstr)
        TOMLFile(userconfig_path).write(toml)
        logging.info(f"Created user config file: {userconfig_path}")
    return config_dir


class Starbash:
    """The main Starbash application class."""

    def __init__(self):
        """
        Initializes the Starbash application by loading configurations
        and setting up the repository manager.
        """
        setup_logging()
        logging.info("Starbash application initializing...")

        # Load app defaults and initialize the repository manager
        self.repo_manager = RepoManager()
        self.repo_manager.add_repo("pkg://defaults")

        # Add user prefs as a repo
        self.user_repo = self.repo_manager.add_repo("file://" + str(create_user()))

        logging.info(
            f"Repo manager initialized with {len(self.repo_manager.repos)} default repo references."
        )
        # self.repo_manager.dump()

        self.db = Database()
        # FIXME, call reindex somewhere and also index whenever new repos are added
        # self.reindex_repos()

    # --- Lifecycle ---
    def close(self) -> None:
        self.db.close()

    # Context manager support
    def __enter__(self) -> "Starbash":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reindex_repo(self, repo: Repo):
        """Reindex all repositories managed by the RepoManager."""
        logging.info("Reindexing all repositories...")
        config = self.repo_manager.merged.get("config")
        if not config:
            raise ValueError(f"App config not found.")
        whitelist = config["fits-whitelist"]

        # FIXME, add a method to get just the repos that contain images
        if repo.is_scheme("file") and repo.kind != "recipe":
            logging.debug("Reindexing %s...", repo.url)
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
                    # Read and log the primary header (HDU 0)
                    with fits.open(str(f), memmap=False) as hdul:
                        # convert headers to dict
                        hdu0: Any = hdul[0]
                        items = hdu0.header.items()
                        headers = {}
                        for key, value in items:
                            if key in whitelist:
                                headers[key] = value
                        logging.debug("Headers for %s: %s", f, headers)
                        self.db.add_from_fits(f, headers)
                except Exception as e:
                    logging.warning("Failed to read FITS header for %s: %s", f, e)

    def reindex_repos(self):
        """Reindex all repositories managed by the RepoManager."""
        logging.info("Reindexing all repositories...")

        for repo in track(self.repo_manager.repos, description="Reindexing repos..."):
            self.reindex_repo(repo)

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
