from __future__ import annotations

import logging
import shutil
import tempfile
import types
from pathlib import Path
from typing import Any

import tomlkit
from toml_repo import Repo, get_config_suffix

from starbash import to_shortdate
from starbash.doit_types import cleanup_old_contexts, get_processing_dir
from starbash.parameters import ParameterStore
from starbash.processing_like import ProcessingLike
from starbash.report import (
    SessionInfo,
    frame_info,
    match_equipment,
    selected_metadata,
    sort_datetime,
)
from starbash.safety import get_safe
from starbash.toml import toml_from_template

__all__ = [
    "ProcessedTarget",
]


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
        self.sessions_info: list[SessionInfo] = []
        self._init_processing_dir(target)

        output_kind = "master" if target is None else "processed"
        self.p._set_output_by_kind(output_kind)

        dir = Path(self.p.context["output"].base)
        if output_kind != "master":
            # Get the path to the starbash.toml file
            config_path = dir / get_config_suffix()
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

        # Contains "used" and "excluded" lists - used for sessionless tasks.
        # Populated by _init_from_toml() from the target's starbash.toml.
        self.default_stages: dict[str, Any] = {}
        self._init_from_toml()
        self._set_default_stages()

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

        p.processed_target = self  # a backpointer to our ProcessedTarget

        self.parameter_store = ParameterStore()
        # Load any user-activated per-stage overrides from this target's starbash.toml.
        self.parameter_store.add_overrides_from_repo(self.repo)

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
        from starbash.stage_utils import find_stage_entry, upsert_stage

        # Ensure every known stage has a [[stages]] entry. Newly discovered stages that
        # are 'exclude_by_default' get marked excluded; existing entries (and any user
        # edits/overrides) are left untouched.
        for stage in self.p.stages:
            stage_name = get_safe(stage, "name")
            if find_stage_entry(self.default_stages, stage_name) is not None:
                continue  # respect whatever the user already has for this stage

            excluded = bool(stage.get("exclude_by_default", False))
            if excluded:
                logging.debug(
                    f"Excluding stage '{stage_name}' by default, edit starbash.toml if you'd like it enabled."
                )
            upsert_stage(self.default_stages, stage, excluded=excluded)

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
            # The single [[stages]] array-of-tables (name / excluded / overrides).
            # do_create stores it back in the repo config so mutations persist on write.
            "stages": self.repo.get("stages", default=tomlkit.aot(), do_create=True)
        }

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

        # The target-level [[stages]] AoT (self.default_stages["stages"]) is the same object
        # stored in the repo config, so used/excluded edits already persist. Nothing else to do.

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

        about = report_toml["about"]
        sessions = tomlkit.aot()
        for info in self.sessions_info:
            session = tomlkit.table()
            for key in ("id", "date", "start", "end"):
                value = getattr(info, key)
                if value is not None:
                    session[key] = value
            session["equipment"] = tomlkit.item(info.equipment)
            session["metadata"] = tomlkit.item(info.metadata)
            frames = tomlkit.aot()
            for frame_info_value in info.frames:
                frame = tomlkit.table()
                frame["metadata"] = tomlkit.item(frame_info_value.metadata)
                frames.append(frame)
            session["frames"] = frames
            sessions.append(session)
        about["sessions"] = sessions

        # Store the updated about section
        self.repo.set("about", about)

    def _collect_sessions_info(self) -> None:
        """Collect sanitized, reportable session and frame information."""
        blacklist: list[str] = self.p.sb.repo_manager.get("repo.metadata_blacklist", default=[])
        catalog = self.p.sb.repo_manager.get("equipment", default=[])
        infos: list[SessionInfo] = []
        sessions = sorted(self.p.sessions, key=lambda s: sort_datetime(s.get("start")))
        for session in sessions:
            metadata = session.get("metadata", {})
            images = self.p.sb.get_session_images(session)
            images = sorted(images, key=lambda image: sort_datetime(image.get("DATE-OBS")))
            start = session.get("start")
            infos.append(
                SessionInfo(
                    id=session.get("id"),
                    date=to_shortdate(start) if start else None,
                    start=start,
                    end=session.get("end"),
                    equipment=match_equipment(metadata, catalog),
                    metadata=selected_metadata(metadata, ("FOCALLEN", "FOCRATIO", "GAIN", "XPIXSZ", "YPIXSZ"), blacklist),
                    frames=[frame_info(image, blacklist) for image in images],
                )
            )
        self.sessions_info = infos

    def close(self) -> None:
        """Finalize and close the ProcessedTarget, saving any updates to the config."""
        self._collect_sessions_info()
        self._update_from_context()
        self._generate_report()
        self.parameter_store.write_stage_overrides(self.repo)
        # Drop the template's placeholder empty [[stages]] entry before writing.
        from starbash.stage_utils import prune_empty_stages

        prune_empty_stages(self.default_stages)
        if self.config_valid:
            self.repo.write_config()
        else:
            logging.debug("ProcessedTarget config marked invalid, not writing to disk")

        self._cleanup_processing_dir()
        self.p.processed_target = None

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> ProcessedTarget:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: types.TracebackType | None) -> None:
        self.close()
