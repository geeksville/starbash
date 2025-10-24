import logging
from importlib import resources

from astroglue.repo import RepoManager


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
