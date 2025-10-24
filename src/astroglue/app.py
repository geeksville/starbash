import logging
from importlib import resources

from astroglue.repo import RepoManager
from astroglue.tool import tools


class AstroGlue:
    """The main AstroGlue application class."""

    def __init__(self):
        """
        Initializes the AstroGlue application by loading configurations
        and setting up the repository manager.
        """
        logging.info("AstroGlue application initializing...")

        # Load app defaults and initialize the repository manager
        app_defaults_text = (
            resources.files("astroglue").joinpath("appdefaults.ag.toml").read_text()
        )
        self.repo_manager = RepoManager(app_defaults_text)
        logging.info(
            f"Repo manager initialized with {len(self.repo_manager.repos)} default repo references."
        )
        self.repo_manager.dump()
        self.run_all_stages()

    def run_all_stages(self):
        """On the currently active session, run all processing stages"""
        logging.info("--- Running all stages ---")

        # 1. Get all stage definitions from all repos and flatten the list.
        # The `union()` method returns a MultiDict, and `getall()` retrieves all
        # values for the 'stages' key, which are arrays of tables from the TOML files.
        all_stage_arrays = self.repo_manager.union().getall("stages")
        all_stages = [
            stage for stage_array in all_stage_arrays for stage in stage_array
        ]

        # 2. Sort the collected stages by their 'priority' field.
        try:
            sorted_stages = sorted(all_stages, key=lambda s: s["priority"])
        except KeyError as e:
            # Re-raise as a ValueError with a more descriptive message.
            raise ValueError(
                f"invalid stage definition: a stage is missing the required 'priority' key"
            ) from e

        logging.info(f"Found {len(sorted_stages)} stages to run, in order of priority.")

        # 3. Iterate through the sorted stages and execute them.
        for stage in sorted_stages:
            stage_name = stage.get("name", "Unnamed Stage")
            logging.info(
                f"Executing stage: '{stage_name}' (Priority: {stage.get('priority', 'N/A')})"
            )
            # Placeholder for actual stage execution logic

        logging.info("--- End of stages ---")
