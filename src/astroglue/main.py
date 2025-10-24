import logging
import sys
from importlib import resources

from astroglue.repo import RepoManager


def setup_logging():
    """
    Configures basic logging.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    """Main entry point for the astroglue application."""
    setup_logging()
    logging.info("astroglue starting up")

    # Load app defaults and initialize the repository manager
    app_defaults_text = (
        resources.files("astroglue").joinpath("appdefaults.ag.toml").read_text()
    )
    repo_manager = RepoManager(app_defaults_text)
    logging.info(
        f"Repo manager initialized with {len(repo_manager.repos)} default repo references."
    )
    repo_manager.dump()


if __name__ == "__main__":
    main()
