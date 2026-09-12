from __future__ import annotations

import logging
import shutil
import tempfile
import types
from copy import deepcopy
from dataclasses import dataclass
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
from starbash.run_state import (
    LOG_TAIL_LINES,
    FileRef,
    RunState,
    RunStatus,
    RunTree,
    TaskNode,
    document_to_tree,
)
from starbash.safety import get_safe
from starbash.toml import toml_from_template
from starbash.url import make_file_url

__all__ = [
    "ProcessedTarget",
    "ParameterOption",
    "StageOption",
    "coerce_override",
    "stage_declarations",
]


@dataclass
class ParameterOption:
    """One overridable stage parameter, with its declared default and current value.

    ``value is None`` means "not overridden", i.e. the recipe default applies.
    """

    name: str
    description: str | None
    default: Any
    value: Any | None = None

    @property
    def is_overridden(self) -> bool:
        """True when the user has set an explicit value."""
        return self.value is not None


@dataclass
class StageOption:
    """A stage of a processed target: whether it runs, plus its parameters."""

    name: str
    description: str | None
    excluded: bool
    parameters: list[ParameterOption]
    #: URL (``https://`` or ``file://``) of the recipe that declares this stage.
    recipe_url: str | None = None


def _comment_of(table: Any, key: str) -> str | None:
    """Return the ``#`` comment attached to ``table[key]``, if any."""
    item = table.get(key) if table is not None else None
    comment = getattr(getattr(item, "trivia", None), "comment", None)
    if not comment:
        return None
    return comment.lstrip("#").strip() or None


def _toml_literal(value: Any) -> str:
    """Render a value the way the scaffold writes its commented-out ``value =`` line."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def coerce_override(text: str, default: Any) -> Any:
    """Convert user-typed text to the type of the parameter's declared default.

    Parameter values are substituted into tool scripts, so preserving the declared
    type matters (a number must stay a number).  Input that cannot be parsed falls
    back to the raw string rather than raising.
    """
    text = text.strip()
    if isinstance(default, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(text)
        except ValueError:
            pass
    if isinstance(default, (int, float)):
        try:
            return float(text)
        except ValueError:
            return text
    if isinstance(default, str):
        return text
    # No declared default to learn from: infer the most specific type that fits.
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            continue
    return text


def stage_declarations(recipes: Any) -> dict[str, dict[str, Any]]:
    """Map stage name -> its declared description and parameters.

    Recipes are the authoritative source of a parameter's default and description
    (declared as ``[[stages.parameters]]``).  Scanning the recipe repos is cheap
    because their config is already loaded; later definitions win, mirroring repo
    precedence.
    """
    declarations: dict[str, dict[str, Any]] = {}
    for repo in recipes:
        try:
            stages = repo.config.get("stages")
        except Exception:  # noqa: BLE001 - one malformed recipe must not break the page
            continue
        if not stages:
            continue

        for stage in stages:
            name = stage.get("name")
            if not name:
                continue
            entry = declarations.setdefault(
                str(name), {"description": None, "parameters": {}, "recipe_url": None}
            )
            if stage.get("description"):
                entry["description"] = stage.get("description")
            source = getattr(stage, "source", None)
            recipe_url = getattr(source, "url", None) if source is not None else None
            if recipe_url:
                entry["recipe_url"] = str(recipe_url)
            for param in stage.get("parameters") or []:
                param_name = param.get("name")
                if not param_name:
                    continue
                entry["parameters"][str(param_name)] = {
                    "default": param.get("default"),
                    "description": param.get("description"),
                }
    return declarations



def _file_url(path: Any) -> str | None:
    """Best-effort ``file://`` URL for a path-like value."""
    if path is None:
        return None
    try:
        return make_file_url(Path(str(path)))
    except Exception:  # noqa: BLE001 - a bad path must not break the tree
        return None


def _status_from_success(success: bool | None) -> RunStatus:
    """Map doit's tri-state ``success`` onto a :class:`RunStatus`."""
    if success is True:
        return RunStatus.OK
    if success is False:
        return RunStatus.FAILED
    return RunStatus.SKIPPED


def _file_refs_from_fileinfo(fi: Any) -> list[FileRef]:
    """Build clickable :class:`FileRef`s from a doit ``FileInfo`` (if any)."""
    if fi is None:
        return []
    refs: list[FileRef] = []
    fulls = list(getattr(fi, "full_paths", None) or [])
    labels = list(getattr(fi, "short_paths", None) or [])
    relative = getattr(fi, "relative", None)
    for index, path in enumerate(fulls):
        if len(fulls) == 1 and relative:
            label = str(relative)
        elif index < len(labels):
            label = Path(str(labels[index])).name
        else:
            label = Path(str(path)).name
        refs.append(FileRef(label=label, url=_file_url(path)))
    if not refs:
        base = getattr(fi, "base", None)
        if base is not None:
            label = relative or Path(str(base)).name
            refs.append(FileRef(label=str(label), url=_file_url(getattr(fi, "full", None) or base)))
    return refs


def _result_inputs(context: dict[str, Any]) -> list[FileRef]:
    """Collect the input file references recorded in a task's context."""
    refs: list[FileRef] = []
    stage_input = context.get("stage_input")
    if isinstance(stage_input, dict):
        for fi in stage_input.values():
            refs.extend(_file_refs_from_fileinfo(fi))
    if not refs:
        for path in context.get("input_files") or []:
            refs.append(FileRef(label=Path(str(path)).name, url=_file_url(path)))
    return refs



class ProcessedTarget:
    """The repo file based config for a single processed target.

    Processed-target metadata is stored in separate files below the target's
    ``.starbash`` directory. ``self.repo`` remains the repository wrapper for
    ``main.toml`` so stage and parameter code can continue to use its existing
    interface.

    FIXME: currently this only works for 'targets'.  eventually it should be generalized so
    it also works for masters. In the case of a generated master, metadata is
    stored beside the generated master file.
    The generated master will be something like 'foo_blah_bias_master.fits' and in that same directory there will be a 'foo_blah_bias_master.toml'
    """

    #: The parsed ``about.toml`` / ``sessions.toml`` documents.  ``None`` means "not
    #: loaded yet"; the :attr:`about` / :attr:`sessions` properties load them lazily.
    about_config: TOMLDocument | None
    sessions_config: TOMLDocument | None

    def __init__(self, p: ProcessingLike, target: str | None) -> None:
        """Initialize a processed target or generated master configuration."""
        self.p = p
        self.read_only = False
        self.sessions_info: list[SessionInfo] = []
        self._init_processing_dir(target)

        output_kind = "master" if target is None else "processed"
        # Masters are processed one session at a time in throwaway temp dirs; they
        # are not real targets, so they are excluded from the live run tree/log.
        self.is_master = output_kind == "master"
        self.p._set_output_by_kind(output_kind)

        dir = Path(self.p.context["output"].base)
        #: Persisted, human-readable record of the most recent run (processed only).
        run_log_path: Path | None
        if output_kind != "master":
            metadata_dir = dir / ".starbash"
            self.config_path = metadata_dir / "main.toml"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            log_path = metadata_dir / "starbash.log"
            repo_path = self.config_path
            about_path = metadata_dir / "about.toml"
            sessions_path = metadata_dir / "sessions.toml"
            run_log_path = metadata_dir / "run-log.toml"
        else:
            # Master file paths are just the base plus .toml
            self.config_path = dir.with_suffix(".toml")
            log_path = dir.with_suffix(".log")
            repo_path = self.config_path
            about_path = None
            sessions_path = None
            run_log_path = None

        self.log_path: Path = log_path  # Let later tools see where to write our logs
        self.run_log_path = run_log_path
        self.run: RunState | None = None
        #: The stages the doit layer kept for this target (set by Processing before
        #: the run).  None means "not yet known" (fall back to the target's config).
        self._run_stages: list[Any] | None = None

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
        if output_kind != "master" and not self.config_path.exists():
            TOMLFile(self.config_path).write(default_toml)

        self.config_valid = (
            True  # You can set this to False if you'd like to suppress writing the toml to disk
        )

        p.processed_target = self  # a backpointer to our ProcessedTarget

    @property
    def parameter_store(self) -> ParameterStore:
        """The target's stage-parameter store, built lazily on first use.

        Building it reads the target's overrides, which is unnecessary (and slow)
        when just listing or inspecting targets, so it is deferred.
        """
        store = getattr(self, "_parameter_store", None)
        if store is None:
            store = ParameterStore()
            try:
                # Load any user-activated per-stage overrides from main.toml.
                store.add_overrides_from_repo(self.repo)
            except Exception as e:  # noqa: BLE001 - a partial config must not break us
                logging.debug(f"Could not load stage overrides for {self.name}: {e}")
            self._parameter_store = store
        return store

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

        if self.p is None:
            # Read-only open: the [[stages]] entries already exist on disk.
            return

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
                    f"Excluding stage '{stage_name}' by default, edit .starbash/main.toml if you'd like it enabled."
                )
            upsert_stage(self.default_stages, stage, excluded=excluded)

    def _init_from_toml(self) -> None:
        """Read customized settings (masters, stages etc...) from the toml into our sessions/defaults."""

        proc_sessions = (
            self.sessions_config.get("sessions", []) if self.sessions_config is not None else []
        )
        # Match persisted session state using public session attributes rather than
        # database identifiers, which are intentionally not written to sessions.toml.
        for sess in self.p.sessions if self.p is not None else []:
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
        # (`self.sessions` loads the document if it has not been parsed yet.)
        proc_sessions = self.sessions.get("sessions", [])
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
        if self.read_only:
            # Opened read-only (GUI/publish): there is nothing to finalize or write.
            return
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
    # --- read-only model view (GUI / publish) -----------------------------

    @classmethod
    def open(cls, target_dir: str | Path) -> ProcessedTarget:
        """Open an existing processed-target directory **read-only**.

        Nothing is created and nothing is ever written: this is the model view
        used by the GUI and the publish tooling.  The ``[[stages]]`` entries and
        the most recent ``run-log.toml`` (if any) are loaded for inspection.
        """
        self = cls.__new__(cls)
        self.p = None
        self.read_only = True
        self.is_master = False
        self.is_temp = False
        self.sessions_info = []
        self.name = Path(target_dir)
        metadata_dir = self.name / ".starbash"
        self.config_path = metadata_dir / "main.toml"
        self.run_log_path = metadata_dir / "run-log.toml"
        self.log_path = metadata_dir / "starbash.log"
        self.about_path = metadata_dir / "about.toml"
        self.sessions_path = metadata_dir / "sessions.toml"
        self.template_name = "target/processed/main"

        default_toml = cls._as_toml_document(toml_from_template(self.template_name, overrides=None))
        self.repo = Repo(self.config_path, default_toml=default_toml)
        # ``about``/``sessions`` (and the parameter store) are loaded lazily: a
        # ``sessions.toml`` carries per-frame metadata and can be large, and we
        # open every target when listing them, so parsing them here would stall
        # the GUI thread.  See the ``about``/``sessions`` properties.
        self.about_config = None
        self.sessions_config = None

        self.default_stages = {}
        self._init_from_toml()
        self.config_valid = False
        self.run = None
        self._run_stages = None
        return self

    @classmethod
    def discover(cls, root: str | Path) -> list[ProcessedTarget]:
        """Open (read-only) every processed target directory beneath ``root``."""
        root_path = Path(root)
        targets: list[ProcessedTarget] = []
        if not root_path.is_dir():
            return targets
        for child in sorted(root_path.iterdir()):
            if not child.is_dir() or not (child / ".starbash" / "main.toml").exists():
                continue
            try:
                targets.append(cls.open(child))
            except Exception as e:  # noqa: BLE001 - one bad target must not hide the rest
                logging.warning(f"Skipping unreadable processed target {child}: {e}")
        return targets

    @staticmethod
    def _read_or_template(path: Path | None, template_name: str) -> TOMLDocument:
        """Read an existing metadata file, or return (without writing) its template."""
        if path is not None and path.exists():
            try:
                return tomlkit.parse(path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001 - corrupt file shouldn't crash a listing
                logging.debug(f"Could not parse {path}: {e}")
        return ProcessedTarget._as_toml_document(toml_from_template(template_name, overrides=None))

    @property
    def config_url(self) -> str | None:
        """A clickable URL for this target's ``main.toml`` (or None)."""
        repo = getattr(self, "repo", None)
        return repo.config_url if repo is not None else None

    @property
    def output_dir(self) -> Path:
        """The target's output directory (same as ``self.name``)."""
        return self.name

    @property
    def about(self) -> TOMLDocument:
        """The parsed ``about.toml`` document (loaded lazily)."""
        document = self.about_config
        if document is None:
            document = self._read_or_template(self.about_path, "target/processed/about")
            self.about_config = document
        return document

    @property
    def sessions(self) -> TOMLDocument:
        """The parsed ``sessions.toml`` document (loaded lazily)."""
        document = self.sessions_config
        if document is None:
            document = self._read_or_template(self.sessions_path, "target/processed/sessions")
            self.sessions_config = document
        return document


    # --- stage / option accessors (shared by GUI + publishing) ------------

    def stage_entries(self) -> list[tuple[str, bool]]:
        """Return ``(name, excluded)`` for every ``[[stages]]`` entry."""
        from starbash.stage_utils import get_stages_aot

        entries: list[tuple[str, bool]] = []
        for entry in get_stages_aot(self.default_stages):
            name = entry.get("name")
            if not name:
                continue
            entries.append((str(name), bool(entry.get("excluded", False))))
        return entries

    def stage_counts(self) -> tuple[int, int]:
        """Return ``(active, excluded)`` stage counts."""
        used = excluded = 0
        for _name, is_excluded in self.stage_entries():
            if is_excluded:
                excluded += 1
            else:
                used += 1
        return (used, excluded)

    def stage_options(self, declarations: dict[str, dict[str, Any]]) -> list[StageOption]:
        """Load this target's stages, merged with the parameters each recipe declares.

        Declared parameters are listed first, in declaration order, so the UI is
        consistent between targets.  Any override present in the file but *not*
        declared by a recipe is still surfaced, so hand-edited files are never
        silently dropped.
        """
        from starbash.stage_utils import get_stages_aot

        stages: list[StageOption] = []
        for entry in get_stages_aot(self.default_stages):
            name = entry.get("name")
            if not name:
                continue
            name = str(name)
            declared = declarations.get(name, {})
            declared_params: dict[str, Any] = declared.get("parameters", {})

            overrides: dict[str, Any] = {}
            for override in entry.get("overrides") or []:
                override_name = override.get("name")
                if override_name:
                    overrides[str(override_name)] = override

            parameters: list[ParameterOption] = []
            for param_name, param_decl in declared_params.items():
                override = overrides.pop(param_name, None)
                parameters.append(
                    ParameterOption(
                        name=param_name,
                        description=param_decl.get("description") or _comment_of(override, "name"),
                        default=param_decl.get("default"),
                        value=override.get("value") if override is not None else None,
                    )
                )
            for param_name, override in overrides.items():
                parameters.append(
                    ParameterOption(
                        name=param_name,
                        description=_comment_of(override, "name"),
                        default=None,
                        value=override.get("value"),
                    )
                )

            stages.append(
                StageOption(
                    name=name,
                    description=declared.get("description") or _comment_of(entry, "name"),
                    excluded=bool(entry.get("excluded", False)),
                    parameters=parameters,
                    recipe_url=declared.get("recipe_url"),
                )
            )
        return stages

    def save_stage_options(self, stages: list[StageOption]) -> None:
        """Write the stage/parameter selection back to this target's config file.

        The ``stages`` array-of-tables is rebuilt from ``stages`` in exactly the shape
        :meth:`starbash.parameters.ParameterStore.write_stage_overrides` scaffolds, so
        repeated saves are stable and the file stays hand-editable.  The rest of the
        document (repo header, citation, ...) is preserved untouched.
        """
        config = Path(self.name) / ".starbash" / "main.toml"
        document = (
            tomlkit.parse(config.read_text(encoding="utf-8"))
            if config.exists()
            else tomlkit.document()
        )

        stages_aot = tomlkit.aot()
        for stage in stages:
            entry = tomlkit.table()
            name_item = tomlkit.string(stage.name)
            if stage.description:
                name_item.comment(stage.description)
            entry["name"] = name_item
            if stage.excluded:
                entry["excluded"] = True

            if stage.parameters:
                overrides_aot = tomlkit.aot()
                for parameter in stage.parameters:
                    override = tomlkit.table()
                    param_name = tomlkit.string(parameter.name)
                    if parameter.description:
                        param_name.comment(parameter.description)
                    override["name"] = param_name
                    if parameter.value is not None:
                        override["value"] = parameter.value
                    else:
                        # Keep the default visible to hand-editors, as the scaffold does.
                        override.add(tomlkit.comment(f"value = {_toml_literal(parameter.default)}"))
                    overrides_aot.append(override)
                entry["overrides"] = overrides_aot

            stages_aot.append(entry)

        document["stages"] = stages_aot
        config.parent.mkdir(parents=True, exist_ok=True)
        TOMLFile(config).write(document)

    # --- live run state ---------------------------------------------------

    def run_label(self, context: dict[str, Any] | None = None) -> str:
        """A human-readable name for this run.

        Normal targets use their directory name; a master run (which lives in a
        throwaway ``temp_*`` dir) instead describes the calibration frames it was
        built from, e.g. ``Master flat_Ha · 2024-01-01 · canon``.
        """
        if not self.is_master:
            return self.name.name

        context = context or {}
        config = str(context.get("session_config") or context.get("imagetyp") or "frames")
        parts = [f"Master {config}"]
        date = context.get("date")
        if date:
            parts.append(str(date))
        camera = context.get("camera_id") or context.get("instrument")
        if camera:
            parts.append(str(camera))
        return " · ".join(parts)

    def set_run_stages(self, stages: list[Any]) -> None:
        """Record the stages the doit layer kept for this target.

        The merged recipe catalog contains every stage from every recipe, so
        seeding the run tree from the target's ``main.toml`` lists stages that are
        irrelevant to it (e.g. ``noise_exterminator`` for a master, or
        ``master_dark`` for a light target).  Only stages that actually produced a
        doit task are relevant — the caller passes exactly those here.
        """
        self._run_stages = list(stages)

    def _ensure_run(self, label: str | None = None) -> RunState:
        """Create (and seed) the live run state for this target if needed."""
        if self.run is None:
            self.run = RunState(
                label or self.run_label(),
                config_url=self.config_url,
                log_tail_lines=LOG_TAIL_LINES,
                is_master=self.is_master,
            )
            if self._run_stages is not None:
                from starbash.stage_utils import is_excluded

                for stage in self._run_stages:
                    name = str(stage.get("name") or "")
                    if not name:
                        continue
                    source = getattr(stage, "source", None)
                    self.run.register_stage(
                        name,
                        description=stage.get("description"),
                        recipe_url=getattr(source, "url", None) if source is not None else None,
                        excluded=is_excluded(self.default_stages, name),
                    )
            else:
                # No doit task list was supplied: fall back to the target's config.
                for name, excluded in self.stage_entries():
                    self.run.register_stage(name, excluded=excluded)
        return self.run

    @staticmethod
    def _describe_task(task: Any, node: TaskNode) -> None:
        """Fill a task node's raw inputs/outputs from the doit task itself."""
        file_dep = [str(p) for p in (getattr(task, "file_dep", None) or [])]
        targets = [str(p) for p in (getattr(task, "targets", None) or [])]
        node.file_dep = file_dep
        node.targets = targets
        node.inputs = [FileRef(label=Path(p).name, url=_file_url(p)) for p in file_dep]
        node.outputs = [FileRef(label=Path(p).name, url=_file_url(p)) for p in targets]

    @staticmethod
    def _find_running_task(state: RunState, stage_name: str, task_name: str) -> TaskNode | None:
        """Find the placeholder ``RUNNING`` node created by :meth:`task_started`."""
        stage = state.stage(stage_name)
        if stage is None:
            return None
        for node in stage.tasks:
            if node.name == task_name and node.status == RunStatus.RUNNING:
                return node
        return None

    def task_started(self, task: Any) -> None:
        """Note that a doit task is about to run (live ``RUNNING`` state)."""
        meta = getattr(task, "meta", None) or {}
        stage = meta.get("stage") or {}
        stage_name = str(stage.get("name") or getattr(task, "name", "unknown"))
        source = getattr(stage, "source", None)
        recipe_url = getattr(source, "url", None) if source is not None else None

        state = self._ensure_run(self.run_label(meta.get("context") or {}))
        state.register_stage(
            stage_name,
            description=stage.get("description") if hasattr(stage, "get") else None,
            recipe_url=recipe_url,
        )
        name = str(getattr(task, "name", ""))
        title = task.title() if hasattr(task, "title") else name
        node = TaskNode(name=name, title=title, status=RunStatus.RUNNING)
        self._describe_task(task, node)
        state.add_task(stage_name, node)
        state.set_current_stage(stage_name)
        state.set_current_task(node)

    def record_log(self, line: str) -> None:
        """Append a log line to the currently-running stage (live tail)."""
        if self.run is not None:
            self.run.add_log(line)

    def record_result(self, result: Any) -> None:
        """Fold one doit result into this target's live run state."""
        task = getattr(result, "task", None)
        meta = (getattr(task, "meta", None) or {}) if task is not None else {}
        stage = meta.get("stage") or {}
        stage_name = str(stage.get("name") or getattr(task, "name", "unknown"))
        source = getattr(stage, "source", None)
        recipe_url = getattr(source, "url", None) if source is not None else None

        state = self._ensure_run(self.run_label(meta.get("context") or {}))
        state.register_stage(
            stage_name,
            description=stage.get("description") if hasattr(stage, "get") else None,
            recipe_url=recipe_url,
        )

        task_name = str(getattr(task, "name", ""))
        node = self._find_running_task(state, stage_name, task_name)
        if node is None:
            title = task.title() if task is not None and hasattr(task, "title") else task_name
            node = TaskNode(name=task_name, title=title)
            self._describe_task(task, node)
            state.add_task(stage_name, node)

        node.status = _status_from_success(getattr(result, "success", None))
        node.reason = getattr(result, "reason", None)
        session = getattr(result, "session_desc", None)
        if session:
            node.session = session

        context = getattr(result, "context", {}) or {}
        outputs = _file_refs_from_fileinfo(context.get("output"))
        if outputs:
            node.outputs = outputs
        inputs = _result_inputs(context)
        if inputs:
            node.inputs = inputs

        final = context.get("final_output")
        base = getattr(final, "base", None) if final is not None else None
        if base:
            state.output_url = _file_url(base)

        state.set_current_stage(None)
        state.set_current_task(None)

    def run_tree(self) -> RunTree | None:
        """The live run tree for this target (or None if nothing ran yet)."""
        return self.run.tree() if self.run is not None else None

    def save_run_log(self) -> None:
        """Persist the current run tree to ``run-log.toml`` (processed targets only)."""
        if self.read_only or self.run_log_path is None or self.run is None:
            return
        if not self.run.stages:
            return
        if not self.run.timestamp:
            self.run.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        tree = self.run.tree()
        self.run.success = tree.stages_failed == 0
        try:
            self.run_log_path.parent.mkdir(parents=True, exist_ok=True)
            TOMLFile(self.run_log_path).write(self.run.to_document())
        except OSError as e:
            logging.debug(f"Could not write run log for {self.name}: {e}")

    def latest_run(self) -> RunTree | None:
        """Load the most recent persisted run for this target (or None)."""
        if self.run_log_path is None or not self.run_log_path.exists():
            return None
        try:
            document = tomlkit.parse(self.run_log_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - a corrupt log must not break the GUI
            logging.debug(f"Could not read run log {self.run_log_path}: {e}")
            return None
        return document_to_tree(document)

