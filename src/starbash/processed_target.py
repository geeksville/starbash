import logging
from pathlib import Path
from typing import Any, Protocol

import tomlkit

from repo import Repo, repo_suffix
from starbash.app import ScoredCandidate, Starbash
from starbash.database import SessionRow
from starbash.toml import AsTomlMixin, CommentedString, toml_from_template

__all__ = [
    "ProcessedTarget",
]


class ProcessingLike(Protocol):
    """Minimal protocol to avoid importing Processing and creating cycles.

    This captures only the attributes used by ProcessedTarget.
    """

    context: dict[str, Any]
    sessions: list[SessionRow]
    recipes_considered: list[Repo]
    sb: Starbash

    def add_result(self, result: Any) -> None: ...


class ProcessedTarget:
    """The repo file based config for a single processed target.

    The backing store for this class is a .toml file located in the output directory
    for the processed target.

    FIXME: currently this only works for 'targets'.  eventually it should be generalized so
    it also works for masters.  In the case of a generated master instead of a starbash.toml file in the directory with the 'target'...
    The generated master will be something like 'foo_blah_bias_master.fits' and in that same directory there will be a 'foo_blah_bias_master.toml'
    """

    def __init__(self, p: ProcessingLike, output_kind: str = "processed") -> None:
        """Initialize a ProcessedTarget with the given processing context.

        Args:
            context: The processing context dictionary containing output paths and metadata.
        """
        self.p = p
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

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

    def set_used(self, name: str, used: list[AsTomlMixin]) -> None:
        """Set the used lists for the given section."""
        node = self.repo.get(name, {}, do_create=True)
        node["used"] = used

    def set_excluded(self, name: str, excluded: list[AsTomlMixin]) -> None:
        """Set the excluded lists for the given section."""
        node = self.repo.get(name, {}, do_create=True)
        node["excluded"] = excluded

    def get_excluded(self, name: str) -> list[str]:
        """Any consumers of this function probably just want the raw string"""
        node = self.repo.get(name, {})
        excluded: list[CommentedString] = node.get("excluded", [])
        return [a.value for a in excluded]

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context.

        Call this **after** processing so that output path info etc... is in the context."""

        # Update the sessions list
        proc_sessions = self.repo.get("sessions", default=tomlkit.aot(), do_create=True)
        proc_sessions.clear()
        for sess in self.p.sessions:
            # record the masters considered
            masters: dict[str, list[ScoredCandidate]] | None = sess.get("masters")

            to_add = sess.copy()
            if False:  # auto serialization works?
                to_add.pop("masters", None)  # masters is not serializable

                # session_options = self.repo.get("processing.session.options")
                t = tomlkit.item(to_add)

                if masters:
                    # a dict from masters k to as_toml values
                    masters_out = tomlkit.table()
                    for k, vlist in masters.items():
                        array_out = tomlkit.array()
                        for v in vlist:
                            array_out.add_line(v.candidate["path"], comment=v.get_comment)
                        array_out.add_line()  # MUST add a trailing line so the closing ] is on its own line
                        masters_out.append(k, array_out)

                    options_out = tomlkit.table()
                    options_out.append("master", masters_out)

                    t.append("options", options_out)
                    proc_sessions.append(t)
            else:
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

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> "ProcessedTarget":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
