from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import tomlkit

from repo import Repo, repo_suffix
from starbash import StageDict, to_shortdate
from starbash.database import SessionRow
from starbash.doit_types import TaskDict, cleanup_old_contexts, get_processing_dir
from starbash.parameters import ParameterStore
from starbash.processing_like import ProcessingLike
from starbash.safety import get_safe
from starbash.toml import CommentedString, toml_from_list, toml_from_template

__all__ = [
    "ProcessedTarget",
]


def stage_with_comment(stage: StageDict) -> CommentedString:
    """Create a CommentedString for the given stage."""
    name = stage.get("name", "unnamed_stage")
    description = stage.get("description", None)
    return CommentedString(value=name, comment=description)


def set_used(self: dict, used_stages: list[StageDict]) -> None:
    """Set the used lists for the given section."""
    name = "stages"
    used = [stage_with_comment(s) for s in used_stages]
    node = self.setdefault(name, {})
    node["used"] = toml_from_list(used)


def set_excluded(self: dict, stages_to_exclude: list[StageDict]) -> None:
    """Set the excluded lists for the given section."""
    name = "stages"
    excluded = [stage_with_comment(s) for s in stages_to_exclude]

    node = self.setdefault(name, {})
    node["excluded"] = toml_from_list(excluded)


def get_from_toml(self: dict, key_name: str) -> list[str]:
    """Any consumers of this function probably just want the raw string (key_name is usually excluded or used)"""
    dict_name = "stages"
    node = self.setdefault(dict_name, {})
    excluded: list[CommentedString] = node.get(key_name, [])
    return [a.value for a in excluded]


def task_to_stage(task: TaskDict) -> StageDict:
    """Extract the stage from the given task's context."""
    return task["meta"]["stage"]


def task_to_session(task: TaskDict) -> SessionRow | None:
    """Extract the session from the given task's context."""
    context = task["meta"]["context"]
    session = context.get("session")
    return session


def tasks_to_stages(tasks: list[TaskDict]) -> list[StageDict]:
    """Extract unique stages from the given list of tasks, sorted by priority."""
    stage_dict: dict[str, StageDict] = {}
    for task in tasks:
        stage = task["meta"]["stage"]
        stage_dict[stage["name"]] = stage

    # Sort stages by priority (if priority not present assume 0), higher priority first
    stages = sorted(stage_dict.values(), key=lambda s: s.get("priority", 0), reverse=True)
    logging.debug(f"Stages in priority order: {[s.get('name') for s in stages]}")
    return stages


def set_used_stages_from_tasks(tasks: list[dict]) -> None:
    """Given a list of tasks, set the used stages in each session touched by those tasks."""

    # Inside each session we touched, collect a list of used stages (initially as a list of strings but then in the final)
    # cleanup converted into toml lists with set_used.
    # We rely on the fact that a single session row instance is shared between all tasks for that session.

    if not tasks:
        return

    typ_task = tasks[0]
    pt: ProcessedTarget | None = typ_task["meta"]["processed_target"]
    assert pt, "ProcessedTarget must be set in Processing for sessionless tasks"

    # step 1: clear our temp lists
    default_stages: list[StageDict] = []
    for task in tasks:
        session = task_to_session(task)
        if session:
            session["_temp_used_stages"] = []

    # step 2: collect used stages
    for task in tasks:
        stage = task_to_stage(task)
        session = task_to_session(task)
        used = session["_temp_used_stages"] if session else default_stages
        if stage not in used:
            used.append(stage)

    # step 3: commit used stages to toml (and remove temp lists)
    for task in tasks:
        session = task_to_session(task)
        if session:
            used_stages: list[StageDict] = session.pop("_temp_used_stages", [])
            if used_stages:
                set_used(session, used_stages)

    # Commit our default used stages too
    if default_stages:
        set_used(pt.default_stages, default_stages)


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
            log_path = dir / "starbash.log"
            repo_path = dir
        else:
            # Master file paths are just the base plus .toml
            config_path = dir.with_suffix(".toml")
            log_path = dir.with_suffix(".log")
            repo_path = config_path

        self.log_path: Path = log_path  # Let later tools see where to write our logs

        # Blow away any old log file
        if log_path.exists():
            log_path.unlink()

        template_name = f"target/{output_kind}"
        self.template_name = template_name
        # Note: we are careful to delay overrides (for the 'about' section) until later
        default_toml = toml_from_template(template_name, overrides=None)
        self.repo = Repo(
            repo_path, default_toml=default_toml
        )  # a structured Repo object for reading/writing this config
        self._init_from_toml()

        # Contains "used" and "excluded" lists - used for sessionless tasks
        self.default_stages: dict[str, Any] = {}
        self._set_default_stages()

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

        p.processed_target = self  # a backpointer to our ProcessedTarget

        self.parameter_store = ParameterStore()
        self.parameter_store.add_from_repo(self.repo)

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
        excluded = get_from_toml(self.default_stages, "excluded")
        used: list[str] = get_from_toml(self.default_stages, "used")

        # Rebuild the list of stages we need to exclude, so we can rewrite if needed
        stages_to_exclude: list[StageDict] = []
        changed = False
        for stage in self.p.stages:
            stage_name = get_safe(stage, "name")

            if stage_name in excluded:
                stages_to_exclude.append(stage)
            elif stage.get("exclude_by_default", False) and stage_name not in used:
                # if we've never seen this stage name before
                logging.debug(
                    f"Excluding stage '{stage_name}' by default, edit starbash.toml if you'd like it enabled."
                )
                stages_to_exclude.append(stage)
                changed = True

        if changed:  # Only rewrite if we actually added something
            set_excluded(self.default_stages, stages_to_exclude)

    def _init_from_toml(self) -> None:
        """Read customized settings (masters, stages etc...) from the toml into our sessions/defaults."""

        proc_sessions = self.repo.get("sessions", default=[], do_create=False)
        # When populated in the template we have just a bare [sessions] section, which per toml spec
        # means an array of ONE empty table. We ignore that case by skipping over any session that has no id.
        for sess in self.p.sessions:
            # look in proc_sessions for a matching session by id, copy certain named fields accross: such as "stages", "masters"
            id = get_safe(sess, "id")
            for proc_sess in proc_sessions:
                if proc_sess.get("id") == id:
                    # copy accross certain named fields
                    for field in ["stages", "masters"]:
                        if field in proc_sess:
                            sess[field] = proc_sess[field]
                    break

        self.default_stages = {
            "stages": self.repo.get("stages", default={})
        }  # FIXME, I accidentally have a nested dict named stages

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context.

        Call this **after** processing so that output path info etc... is in the context."""

        blacklist: list[str] = self.p.sb.repo_manager.get("repo.metadata_blacklist", default=[])

        # Update the sessions list
        proc_sessions = self.repo.get("sessions", default=tomlkit.aot(), do_create=True)
        proc_sessions.clear()
        for sess in self.p.sessions:
            sess = sess.copy()

            metadata = sess.get("metadata", {})
            # Remove any blacklisted metadata fields
            for key in blacklist:
                if key in metadata:
                    metadata.pop(key, None)

            # Record session info (including what masters and stages were used for that session)
            proc_sessions.append(sess)

        # Store our non specific stages used/excluded - FIXME kinda yucky, I was not smart about how to use dicts
        for key in ["used", "excluded"]:
            value = self.default_stages["stages"].get(key)
            if value:
                self.repo.set(f"stages.{key}", value)

    def _generate_report(self) -> None:
        """Generate a summary report about this processed target."""

        overrides: dict[str, Any] = {}

        # Gather some summary statistics
        num_sessions = len(self.p.sessions)
        total_num_images: int = 0
        total_exposure_hours = 0.0
        filters_used: set[str] = set()
        observation_dates: list[str] = []

        # Some fields should be the same for all sessions, so just grab them from the first one
        if num_sessions > 0:
            first_sess = self.p.sessions[0]
            metadata = first_sess.get("metadata", {})
            overrides["target"] = metadata.get("OBJECT", "N/A")
            overrides["target_ra"] = metadata.get("OBJCTRA") or metadata.get("RA", "N/A")
            overrides["target_dec"] = metadata.get("OBJCTDEC") or metadata.get("DEC", "N/A")

        for sess in self.p.sessions:
            num_images = sess.get("num_images", 0)
            total_num_images += num_images
            exptime = sess.get("exptime", 0.0)
            exposure_hours = (num_images * exptime) / 3600.0
            total_exposure_hours += exposure_hours

            filter = sess.get("filter")
            if filter:
                filters_used.add(filter)

            obs_date = sess.get("start")
            if obs_date:
                observation_dates.append(to_shortdate(obs_date))

        overrides["num_sessions"] = num_sessions
        overrides["total_exposure_hours"] = round(total_exposure_hours, 2)
        overrides["filters_used"] = ", ".join(sorted(filters_used))
        if observation_dates:
            sorted_dates = sorted(observation_dates)
            overrides["observation_dates"] = ", ".join(sorted_dates)
            overrides["earliest_date"] = sorted_dates[0]
            overrides["latest_date"] = sorted_dates[-1]
        else:
            overrides["earliest_date"] = "N/A"
            overrides["latest_date"] = "N/A"

        report_toml = toml_from_template(
            self.template_name, overrides=overrides
        )  # reload the about section so we can snarf the updated version

        # Store the updated about section
        self.repo.set("about", report_toml["about"])

    def close(self) -> None:
        """Finalize and close the ProcessedTarget, saving any updates to the config."""
        self._update_from_context()
        self._generate_report()
        self.parameter_store.write_overrides(self.repo)
        if self.config_valid:
            self.repo.write_config()
        else:
            logging.debug("ProcessedTarget config marked invalid, not writing to disk")

        self._cleanup_processing_dir()
        self.p.processed_target = None

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> ProcessedTarget:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
