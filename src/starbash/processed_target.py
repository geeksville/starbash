import logging
import shutil
import tempfile
from pathlib import Path

import tomlkit

from repo import Repo, repo_suffix
from starbash import StageDict
from starbash.doit import cleanup_old_contexts, get_processing_dir
from starbash.processing_like import ProcessingLike
from starbash.safety import get_safe
from starbash.toml import AsTomlMixin, CommentedString, toml_from_list, toml_from_template

__all__ = [
    "ProcessedTarget",
]


def stage_with_comment(stage: StageDict) -> CommentedString:
    """Create a CommentedString for the given stage."""
    name = stage.get("name", "unnamed_stage")
    description = stage.get("description", None)
    return CommentedString(value=name, comment=description)


class ProcessedTarget:
    """The repo file based config for a single processed target.

    The backing store for this class is a .toml file located in the output directory
    for the processed target.

    FIXME: currently this only works for 'targets'.  eventually it should be generalized so
    it also works for masters.  In the case of a generated master instead of a starbash.toml file in the directory with the 'target'...
    The generated master will be something like 'foo_blah_bias_master.fits' and in that same directory there will be a 'foo_blah_bias_master.toml'
    """

    def __init__(self, p: ProcessingLike, target: str | None) -> None:
        """Initialize a ProcessedTarget with the given processing context.

        Args:
            context: The processing context dictionary containing output paths and metadata.
        """
        self.p = p
        self._init_processing_dir(target)

        output_kind = "master" if target is None else "processed"
        self.p._set_output_by_kind(output_kind)

        dir = Path(self.p.context["output"].base)
        if output_kind != "master":
            # Get the path to the starbash.toml file
            config_path = dir / repo_suffix
            repo_path = dir
        else:
            # Master file paths are just the base plus .toml
            config_path = dir.with_suffix(".toml")
            repo_path = config_path

        template_name = f"target/{output_kind}"
        default_toml = toml_from_template(template_name, overrides=self.p.context)
        self.repo = Repo(
            repo_path, default_toml=default_toml
        )  # a structured Repo object for reading/writing this config
        self._update_from_context()
        self._set_default_stages()

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

    def set_used(self, name: str, used: list[AsTomlMixin]) -> None:
        """Set the used lists for the given section."""
        node = self.repo.get(name, {}, do_create=True)
        node["used"] = toml_from_list(used)

    def set_excluded(self, name: str, stages_to_exclude: list[StageDict]) -> None:
        """Set the excluded lists for the given section."""
        excluded = [stage_with_comment(s) for s in stages_to_exclude]

        node = self.repo.get(name, {}, do_create=True)
        node["excluded"] = toml_from_list(excluded)

    def get_from_toml(self, dict_name: str, key_name: str) -> list[str]:
        """Any consumers of this function probably just want the raw string (key_name is usually excluded or used)"""
        node = self.repo.get(dict_name, {})
        excluded: list[CommentedString] = node.get(key_name, [])
        return [a.value for a in excluded]

    def _init_processing_dir(self, target: str | None) -> None:
        processing_dir = get_processing_dir()

        # Set self.name to be target (if specified) otherwise use a tempname
        if target:
            self.name = processing_dir / target
            self.is_temp = False

            exists = self.name.exists()
            if not exists:
                self.name.mkdir(parents=True, exist_ok=True)
                logging.debug(f"Creating processing context at {self.name}")
            else:
                logging.debug(f"Reusing existing processing context at {self.name}")
        else:
            # Create a temporary directory name
            temp_name = tempfile.mkdtemp(prefix="temp_", dir=processing_dir)
            self.name = Path(temp_name)
            self.is_temp = True

        self.p.context["process_dir"] = str(self.name)
        if target:  # Set it in the context so we can do things like find our output dir
            self.p.context["target"] = target

    def _cleanup_processing_dir(self) -> None:
        logging.debug(f"Cleaning up processing context at {self.name}")

        # unregister our process dir
        self.p.context.pop("process_dir", None)

        # Delete temporary directories
        if self.is_temp and self.name.exists():
            logging.debug(f"Removing temporary processing directory: {self.name}")
            shutil.rmtree(self.name, ignore_errors=True)

        cleanup_old_contexts()

    def _set_default_stages(self) -> None:
        """If we have newly discovered stages which should be excluded by default, add them now."""
        excluded = self.get_from_toml("stages", "excluded")
        used: list[str] = self.get_from_toml("stages", "used")

        # Rebuild the list of stages we need to exclude, so we can rewrite if needed
        stages_to_exclude: list[StageDict] = []
        changed = False
        for stage in self.p.stages:
            stage_name = get_safe(stage, "name")

            if stage_name in excluded:
                stages_to_exclude.append(stage)
            elif stage.get("exclude_by_default", False) and stage_name not in used:
                # if we've never seen this stage name before
                logging.info(
                    f"Excluding stage '{stage_name}' by default, edit starbash.toml if you'd like it enabled."
                )
                stages_to_exclude.append(stage)
                changed = True

        if changed:  # Only rewrite if we actually added something
            self.set_excluded("stages", stages_to_exclude)

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context.

        Call this **after** processing so that output path info etc... is in the context."""

        # Update the sessions list
        proc_sessions = self.repo.get("sessions", default=tomlkit.aot(), do_create=True)
        proc_sessions.clear()
        for sess in self.p.sessions:
            # Record session info (including what masters were used for that session)
            proc_sessions.append(sess)

        proc_options = self.repo.get("processing.recipe.options", {})

        # populate the list of recipes considered
        proc_options["url"] = [recipe.url for recipe in self.p.recipes_considered]

    def close(self) -> None:
        """Finalize and close the ProcessedTarget, saving any updates to the config."""
        self._update_from_context()
        if self.config_valid:
            self.repo.write_config()
        else:
            logging.debug("ProcessedTarget config marked invalid, not writing to disk")

        self._cleanup_processing_dir()

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> "ProcessedTarget":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
