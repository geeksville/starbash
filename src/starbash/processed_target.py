from __future__ import annotations

import logging
import shutil
import tempfile
import types
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import tomlkit
from toml_repo import Repo
from tomlkit.items import Table
from tomlkit.toml_document import TOMLDocument
from tomlkit.toml_file import TOMLFile

from starbash import to_shortdate
from starbash.doit_types import cleanup_old_contexts, get_processing_dir
from starbash.parameters import ParameterStore
from starbash.processing_like import ProcessingLike
from starbash.report import (
    IMAGE_SCALE_KEY,
    SESSION_METADATA_KEYS,
    SessionInfo,
    frame_info,
    image_scale_arcsec_per_pixel,
    match_equipment,
    selected_metadata,
    sort_datetime,
)
from starbash.safety import get_safe
from starbash.target_migration import migrate_legacy_target
from starbash.toml import toml_from_template

__all__ = [
    "ProcessedTarget",
]


class ProcessedTarget:
    """The repo file based config for a single processed target.

    Processed-target metadata is stored in separate files below the target's
    ``.starbash`` directory. ``self.repo`` remains the repository wrapper for
    ``main.toml`` so stage and parameter code can continue to use its existing
    interface.

    FIXME: currently this only works for 'targets'.  eventually it should be generalized so
    it also works for masters.  In the case of a generated master instead of a starbash.toml file in the directory with the 'target'...
    The generated master will be something like 'foo_blah_bias_master.fits' and in that same directory there will be a 'foo_blah_bias_master.toml'
    """

    def __init__(self, p: ProcessingLike, target: str | None) -> None:
        """Initialize a processed target or generated master configuration."""
        self.p = p
        self.sessions_info: list[SessionInfo] = []
        self._init_processing_dir(target)

        output_kind = "master" if target is None else "processed"
        self.p._set_output_by_kind(output_kind)

        dir = Path(self.p.context["output"].base)
        if output_kind != "master":
            metadata_dir = dir / ".starbash"
            legacy_config_path = dir / "starbash.toml"
            config_path = metadata_dir / "main.toml"
            if legacy_config_path.exists():
                if config_path.exists():
                    logging.warning(
                        "Removing stale legacy processed-target configuration at %s; using %s",
                        legacy_config_path,
                        config_path,
                    )
                    legacy_config_path.unlink()
                else:
                    migrate_legacy_target(dir)
            metadata_dir.mkdir(parents=True, exist_ok=True)
            log_path = metadata_dir / "starbash.log"
            repo_path = config_path
            about_path = metadata_dir / "about.toml"
            sessions_path = metadata_dir / "sessions.toml"
        else:
            # Master file paths are just the base plus .toml
            config_path = dir.with_suffix(".toml")
            log_path = dir.with_suffix(".log")
            repo_path = config_path
            about_path = None
            sessions_path = None

        self.log_path: Path = log_path  # Let later tools see where to write our logs

        # Blow away any old log file
        if log_path.exists():
            log_path.unlink()

        template_name = "target/processed/main" if output_kind == "processed" else "target/master"
        self.template_name = template_name
        default_toml = toml_from_template(template_name, overrides=None)
        default_toml = self._as_toml_document(default_toml)
        self.repo = Repo(
            repo_path, default_toml=default_toml
        )  # a structured Repo object for reading/writing this config

        if output_kind != "master":
            assert about_path is not None and sessions_path is not None
            self.about_path = about_path
            self.sessions_path = sessions_path
            self.about_config = self._load_metadata_file(self.about_path, "target/processed/about")
            self.sessions_config = self._load_metadata_file(
                self.sessions_path, "target/processed/sessions"
            )
        else:
            self.about_path = None
            self.sessions_path = None
            self.about_config = tomlkit.document()
            self.sessions_config = tomlkit.document()

        # Contains "used" and "excluded" lists - used for sessionless tasks.
        # Populated by _init_from_toml() from the target's main.toml.
        self.default_stages: dict[str, Any] = {}
        self._init_from_toml()
        self._set_default_stages()
        if output_kind != "master" and not config_path.exists():
            TOMLFile(config_path).write(default_toml)

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

        p.processed_target = self  # a backpointer to our ProcessedTarget

        self.parameter_store = ParameterStore()
        # Load any user-activated per-stage overrides from this target's main.toml.
        self.parameter_store.add_overrides_from_repo(self.repo)

    @staticmethod
    def _as_toml_document(document: Any) -> TOMLDocument:
        """Normalize a TOML document returned by a template provider."""
        if isinstance(document, TOMLDocument):
            return document
        converted = tomlkit.document()
        converted.update(document)
        return converted

    @classmethod
    def _load_metadata_file(cls, path: Path, template_name: str) -> TOMLDocument:
        """Load a split target metadata file, creating it from its template."""
        if path.exists():
            return tomlkit.parse(path.read_text(encoding="utf-8"))

        document = cls._as_toml_document(toml_from_template(template_name, overrides=None))
        TOMLFile(path).write(document)
        return document

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

        proc_sessions = self.sessions_config.get("sessions", [])
        # Match persisted session state using public session attributes rather than
        # database identifiers, which are intentionally not written to sessions.toml.
        for sess in self.p.sessions:
            for proc_sess in proc_sessions:
                if self._session_key(sess) == self._session_key(proc_sess) or (
                    sess.get("start")
                    and sess.get("end")
                    and sess.get("start") == proc_sess.get("start")
                    and sess.get("end") == proc_sess.get("end")
                ):
                    for field in ["stages", "masters"]:
                        if field in proc_sess:
                            sess[field] = proc_sess[field]
                    break

        self.default_stages = {
            # The single [[stages]] array-of-tables (name / excluded / overrides).
            # do_create stores it back in the repo config so mutations persist on write.
            "stages": self.repo.get("stages", default=tomlkit.aot(), do_create=True)
        }

    @staticmethod
    def _session_key(session: dict[str, Any]) -> tuple[str, ...]:
        """Return stable public fields used to match a processed session."""
        metadata = session.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return tuple(
            str(session.get(key) or metadata.get(key.upper()) or "")
            for key in ("start", "end", "filter", "imagetyp", "object", "telescop")
        )

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context.

        Call this **after** processing so that output path info etc... is in the context."""

        blacklist: list[str] = self.p.sb.repo_manager.get("repo.metadata_blacklist", default=[])

        # Keep a sanitized copy for callers and compatibility with the previous
        # in-memory update behavior. The persisted copy is written by _generate_report().
        proc_sessions = self.sessions_config.get("sessions", [])
        if hasattr(proc_sessions, "clear"):
            proc_sessions.clear()
        for sess in self.p.sessions:
            sanitized = deepcopy(sess)
            metadata = sanitized.get("metadata", {})
            if isinstance(metadata, dict):
                for key in blacklist:
                    metadata.pop(key, None)
            if hasattr(proc_sessions, "append"):
                proc_sessions.append(sanitized)

        # Keep compatibility with callers that inspect the old in-memory Repo
        # document. Real processed-target state lives in sessions.toml.
        legacy_sessions = self.repo.get("sessions", default=None, do_create=False)
        if legacy_sessions is not None and legacy_sessions is not proc_sessions:
            if hasattr(legacy_sessions, "clear"):
                legacy_sessions.clear()
            for sess in self.p.sessions:
                sanitized = deepcopy(sess)
                metadata = sanitized.get("metadata", {})
                if isinstance(metadata, dict):
                    for key in blacklist:
                        metadata.pop(key, None)
                if hasattr(legacy_sessions, "append"):
                    legacy_sessions.append(sanitized)

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

        report_toml = toml_from_template("target/processed/about", overrides=overrides)
        report_toml = self._as_toml_document(report_toml)

        about = cast(Table, report_toml["about"])
        about["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        about["schema_version"] = 1
        sessions = tomlkit.aot()
        for info in self.sessions_info:
            session = tomlkit.table()
            for key in ("date", "start", "end"):
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

            source_session = next(
                (
                    candidate
                    for candidate in self.p.sessions
                    if candidate.get("start") == info.start and candidate.get("end") == info.end
                ),
                None,
            )
            if source_session:
                for key in ("filter", "imagetyp", "object", "telescop"):
                    value = source_session.get(key)
                    if value is not None:
                        session[key] = value
                for key in ("stages", "masters"):
                    if key in source_session:
                        session[key] = source_session[key]
            sessions.append(session)

        self.about_config = report_toml
        self.sessions_config = tomlkit.document()
        self.sessions_config.add("sessions", sessions)

    def _write_metadata_files(self) -> None:
        """Write the split processed-target metadata documents."""
        if self.sessions_path is None or self.about_path is None:
            return
        if isinstance(self.about_config, TOMLDocument):
            TOMLFile(self.about_path).write(self.about_config)
        if isinstance(self.sessions_config, TOMLDocument):
            TOMLFile(self.sessions_path).write(self.sessions_config)

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
            session_metadata = selected_metadata(metadata, SESSION_METADATA_KEYS, blacklist)
            image_scale = image_scale_arcsec_per_pixel(metadata)
            if image_scale is not None:
                session_metadata[IMAGE_SCALE_KEY] = image_scale
            infos.append(
                SessionInfo(
                    id=session.get("id"),
                    date=to_shortdate(start) if start else None,
                    start=start,
                    end=session.get("end"),
                    equipment=match_equipment(metadata, catalog),
                    metadata=session_metadata,
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
            self._write_metadata_files()
        else:
            logging.debug("ProcessedTarget config marked invalid, not writing to disk")

        self._cleanup_processing_dir()
        self.p.processed_target = None

    # FIXME - i'm not yet sure if we want to use context manager style usage here
    def __enter__(self) -> ProcessedTarget:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        self.close()
