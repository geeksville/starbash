"""Base class for processing operations in starbash."""

import logging
import shutil
import tempfile
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.progress import Progress

import starbash
from repo import Repo
from starbash.aliases import get_aliases, normalize_target_name
from starbash.app import Starbash
from starbash.database import (
    Database,
    SessionRow,
    get_column_name,
    metadata_to_camera_id,
    metadata_to_instrument_id,
)
from starbash.exception import UserHandledError
from starbash.paths import get_user_cache_dir

__all__ = [
    "Processing",
    "ProcessingResult",
    "ProcessingContext",
    "update_processing_result",
]


@dataclass
class ProcessingResult:
    target: str  # normalized target name, or in the case of masters the camera or instrument id
    sessions: list[SessionRow] = field(
        default_factory=list
    )  # the input sessions processed to make this result
    success: bool | None = None  # false if we had an error, None if skipped
    notes: str | None = None  # notes about what happened
    # FIXME, someday we will add information about masters/flats that were used?


def update_processing_result(result: ProcessingResult, e: Exception | None = None) -> None:
    """Handle exceptions during processing and update the ProcessingResult accordingly."""

    result.success = True  # assume success
    if e:
        result.success = False

        if isinstance(e, UserHandledError):
            if e.ask_user_handled():
                logging.debug("UserHandledError was handled.")
            result.notes = e.__rich__()  # No matter what we want to show the fault in our results

        elif isinstance(e, RuntimeError):
            # Print errors for runtimeerrors but keep processing other runs...
            logging.error(f"Skipping run due to: {e}")
            result.notes = f"Aborted due to possible error in (alpha) code, please file bug on our github: {str(e)}"
        else:
            # Unexpected exception - log it and re-raise
            logging.exception("Unexpected error during processing:")
            raise e


max_contexts = 3  # FIXME, make customizable


class ProcessingContext:
    """For processing a set of sessions for a particular target.

    Keeps a shared temporary directory for intermediate files.  We expose the path to that
    directory in context["process_dir"].

    We keep the processing directory in our cache directory, so that the most recent contexts can be reprocessed
    quickly.

    Arguments:
    p: The Processing instance
    target: The target name (used to name the processing directory - MUST BE PRE normalized), or None to create a temporary
    """

    def __init__(self, p: "Processing", target: str | None = None):
        cache_dir = get_user_cache_dir()
        processing_dir = cache_dir / "processing"
        processing_dir.mkdir(parents=True, exist_ok=True)

        # Set self.name to be target (if specified) otherwise use a tempname
        if target:
            self.name = processing_dir / target
            self.is_temp = False
        else:
            # Create a temporary directory name
            temp_name = tempfile.mkdtemp(prefix="temp_", dir=processing_dir)
            self.name = Path(temp_name)
            self.is_temp = True

        exists = self.name.exists()
        if not exists:
            self.name.mkdir(parents=True, exist_ok=True)
            logging.info(f"Creating processing context at {self.name}")
        else:
            logging.info(f"Reusing existing processing context at {self.name}")

        # Clean up old contexts if we exceed max_contexts
        self._cleanup_old_contexts(processing_dir)

        self.p = p

        self.p.init_context()
        self.p.context["process_dir"] = str(self.name)
        if target:  # Set it in the context so we can do things like find our output dir
            self.p.context["target"] = target

    def __enter__(self) -> "ProcessingContext":
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Returns true if exceptions were handled"""
        logging.debug(f"Cleaning up processing context at {self.name}")

        # unregister our process dir
        self.p.context.pop("process_dir", None)

        # Delete temporary directories
        if self.is_temp and self.name.exists():
            logging.debug(f"Removing temporary processing directory: {self.name}")
            shutil.rmtree(self.name, ignore_errors=True)

    def _cleanup_old_contexts(self, processing_dir: Path) -> None:
        """Remove oldest context directories if we exceed max_contexts."""
        if not processing_dir.exists():
            return

        # Get all subdirectories in processing_dir
        contexts = [d for d in processing_dir.iterdir() if d.is_dir()]

        # If we have more than max_contexts, delete the oldest ones
        if len(contexts) > max_contexts:
            # Sort by modification time (oldest first)
            contexts.sort(key=lambda d: d.stat().st_mtime)

            # Calculate how many to delete
            num_to_delete = len(contexts) - max_contexts

            # Delete the oldest directories
            for context_dir in contexts[:num_to_delete]:
                logging.debug(f"Removing old processing context: {context_dir}")
                shutil.rmtree(context_dir, ignore_errors=True)


class Processing:
    """Abstract base class for processing operations.

    Implementations must provide:
    - run_all_stages(): Process all stages for selected sessions
    - run_master_stages(): Generate master calibration frames
    """

    def __init__(self, sb: Starbash) -> None:
        self.sb: Starbash = sb
        self.context: dict[str, Any] = {}

        self.sessions: list[SessionRow] = []  # The list of sessions we are currently processing
        self.recipes_considered: list[Repo] = []  # all recipes considered for this processing run

        # We create one top-level progress context so that when various subtasks are created
        # the progress bars stack and don't mess up our logging.
        self.progress = Progress(console=starbash.console, refresh_per_second=2)
        self.progress.start()

    @abstractmethod
    def _process_job(self, job_desc: str, output_kind: str) -> ProcessingResult:
        """Do processing for a particular target (i.e. all sessions for a particular object)."""

    @abstractmethod
    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.
        """
        pass

    # --- Lifecycle ---
    def close(self) -> None:
        self.progress.stop()

    # Context manager support
    def __enter__(self) -> "Processing":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def init_context(self) -> None:
        """Do common session init"""

        # Context is preserved through all stages, so each stage can add new symbols to it for use by later stages
        self.context = {}

        # Update the context with runtime values.
        runtime_context = {}
        self.context.update(runtime_context)

    def _run_all_targets(
        self, sessions: list[SessionRow], targets: list[str | None]
    ) -> list[ProcessingResult]:
        """Run all processing stages for the indicated targets.

        Args:
            targets: List of target names (normalized) to process, or None to process
            all the master frames."""

        job_task = self.progress.add_task("Processing targets...", total=len(targets))

        results: list[ProcessingResult] = []
        try:
            for target in targets:
                desc_str = f"Processing target {target}..." if target else "Processing masters..."

                self.progress.update(job_task, description=desc_str)

                if target:
                    # select sessions for this target
                    sessions = self.sb.filter_sessions_by_target(sessions, target)

                    auto_process_masters = True
                    if auto_process_masters:
                        self._add_master_sessions(sessions)

                # we only want sessions with light frames
                # NOT NEEDED - because the dependencies will end up ignoring sessions where all frames are filtered
                # target_sessions = self.sb.filter_sessions_by_imagetyp(target_sessions, "light")

                if target:
                    # We are processing a single target, so build the context around that, and process
                    # all sessions for that target as a group
                    with ProcessingContext(self, target):
                        self.sessions = sessions
                        result = self._process_job(target, "processed")
                        results.append(result)
                else:
                    for s in sessions:
                        # For masters we process each session individually
                        with ProcessingContext(self):
                            self._set_session_in_context(s)
                            # Note: We need to do this early because we need to get camera_id etc... from session

                            self.sessions = [s]
                            job_desc = f"master_{s.get('id', 'unknown')}"
                            result = self._process_job(job_desc, "master")
                            results.append(result)

                # We made progress - call once per iteration ;-)
                self.progress.advance(job_task)
        finally:
            self.progress.remove_task(job_task)

        return results

    def _get_master_sessions(self) -> list[SessionRow]:
        """Get all sessions that are relevant for master frame generation.

        Returns:
            List of SessionRow objects for master frame sessions.
        """
        sessions = self.sb.search_session([])  # for masters we always search everything

        # Don't return any light frame sessions

        sessions = [
            s for s in sessions if get_aliases().normalize(s.get("imagetyp", "light")) != "light"
        ]

        return sessions

    def _add_master_sessions(self, sessions: list[SessionRow]) -> None:
        """Add master frame sessions to the provided list of sessions if they are not already included.

        Args:
            sessions: List of SessionRow objects to which master sessions will be added."""
        existing_session_ids = {s["id"] for s in sessions}
        master_sessions = self._get_master_sessions()
        for s in master_sessions:
            sid = s["id"]
            if sid not in existing_session_ids:
                sessions.append(s)
                existing_session_ids.add(sid)

    def run_all_stages(self) -> list[ProcessingResult]:
        """On the currently active session, run all processing stages

        * for each target in the current selection:
        *   select ONE recipe for processing that target (check recipe.auto.require.* conditions)
        *   init session context (it will be shared for all following steps) - via ProcessingContext
        *   create a temporary processing directory (for intermediate files - shared by all stages)
        *   create a processed output directory (for high value final files) - via run_stage()
        *   iterate over all light frame sessions in the current selection
        *     for each session:
        *       update context input and output files
        *       run session.light stages
        *   after all sessions are processed, run final.stack stages (using the shared context and temp dir)

        """
        sessions = self.sb.search_session()
        targets = list(
            {
                normalize_target_name(obj)
                for s in sessions
                if (obj := s.get(get_column_name(Database.OBJECT_KEY))) is not None
            }
        )

        return self._run_all_targets(sessions, targets)

    def _set_session_in_context(self, session: SessionRow) -> None:
        """adds to context from the indicated session:

        Sets the following context variables based on the provided session:
        * target - the normalized target name of the session
        * instrument - the telescope ID for this session
        * camera_id - the camera ID for this session (cameras might be moved between telescopes by users)
        * date - the localtimezone date of the session
        * imagetyp - the imagetyp of the session
        * session - the current session row (joined with a typical image) (can be used to
        find things like telescope, temperature ...)
        * session_config - a short human readable description of the session - suitable for logs or filenames
        """
        # it is okay to give them the actual session row, because we're never using it again
        self.context["session"] = session

        target = session.get(get_column_name(Database.OBJECT_KEY))
        if target:
            self.context["target"] = normalize_target_name(target)

        metadata = session.get("metadata", {})
        # the telescope name is our instrument id
        instrument = metadata_to_instrument_id(metadata)
        if instrument:
            self.context["instrument"] = instrument

        # the FITS INSTRUMEN keyword is the closest thing we have to a default camera ID.  FIXME, let user override
        # if needed?
        # It isn't in the main session columns, so we look in metadata blob

        camera_id = metadata_to_camera_id(metadata)
        if camera_id:
            self.context["camera_id"] = camera_id

        logging.debug(f"Using camera_id={camera_id}")

        # The type of images in this session
        imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))
        if imagetyp:
            imagetyp = get_aliases().normalize(imagetyp)
            self.context["imagetyp"] = imagetyp

            # add a short human readable description of the session - suitable for logs or in filenames
            session_config = f"{imagetyp}"

            metadata = session.get("metadata", {})
            filter = metadata.get(Database.FILTER_KEY)
            if (imagetyp == "flat" or imagetyp == "light") and filter:
                # we only care about filters in these cases
                session_config += f"_{filter}"
            if imagetyp == "dark":
                exptime = session.get(get_column_name(Database.EXPTIME_KEY))
                if exptime:
                    session_config += f"_{int(float(exptime))}s"
            gain = metadata.get(Database.GAIN_KEY)
            if gain is not None:  # gain values can be zero
                session_config += f"_gain{gain}"

            self.context["session_config"] = session_config

        # a short user friendly date for this session
        date = session.get(get_column_name(Database.START_KEY))
        if date:
            from starbash import (
                to_shortdate,
            )  # Lazy import to avoid circular dependency

            self.context["date"] = to_shortdate(date)
