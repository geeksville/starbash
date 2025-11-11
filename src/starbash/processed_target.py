from pathlib import Path
from typing import Any, Protocol

from repo import Repo, repo_suffix
from starbash.toml import toml_from_template


class ProcessingLike(Protocol):
    """Minimal protocol to avoid importing Processing and creating cycles.

    This captures only the attributes used by ProcessedTarget.
    """

    context: dict[str, Any]
    sessions: list[Any]
    recipes_considered: list[Any]


class ProcessedTarget:
    """The repo file based config for a single processed target.

    The backing store for this class is a .toml file located in the output directory
    for the processed target.
    """

    def __init__(self, p: ProcessingLike) -> None:
        """Initialize a ProcessedTarget with the given processing context.

        Args:
            context: The processing context dictionary containing output paths and metadata.
        """
        self.p = p
        dir = Path(self.p.context["output"]["base_path"])

        # Get the path to the starbash.toml file
        config_path = dir / repo_suffix

        self._init_from_template(config_path)
        self.repo = Repo(dir)  # a structured Repo object for reading/writing this config
        self._update_from_context()

    def _init_from_template(self, config_path: Path) -> None:
        """Create a default starbash.toml file from template.

        Uses the processed_target template and expands it with the current context.
        """

        # Create the config file from template
        # If starbash.toml does not exist, create it from template
        if not config_path.exists():
            toml_from_template("processed_target", config_path, overrides=self.p.context)

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context.

        Call this **after** processing so that output path info etc... is in the context."""

        # Update the sessions list
        proc_sessions = self.repo.get("sessions")
        assert proc_sessions is not None, "sessions must exist in the repo config"
        proc_sessions.clear()
        for sess in self.p.sessions:
            proc_sessions.append(sess)

        proc_options = self.repo.get("processing.recipe.options")
        assert proc_options is not None, "processing.recipe.options must exist in the repo config"

        # populate the list of recipes considered
        proc_options["url"] = [recipe.url for recipe in self.p.recipes_considered]

        # fixme - create earlier and add a p.set_output_dir() that can run earlier - before recipies

        pass  # placeholder don't implement yet

    def close(self) -> None:
        """Finalize and close the ProcessedTarget, saving any updates to the config."""
        self._update_from_context()
        self.repo.write_config()

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> "ProcessedTarget":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
