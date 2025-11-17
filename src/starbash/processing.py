"""Base class for processing operations in starbash."""

import logging
import tempfile
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

from rich.progress import Progress

import starbash
from repo import Repo
from starbash.aliases import normalize_target_name
from starbash.app import Starbash
from starbash.database import (
    Database,
    SessionRow,
    get_column_name,
)
from starbash.exception import UserHandledError
from starbash.paths import get_user_cache_dir


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


class ProcessingContext(tempfile.TemporaryDirectory):
    """For processing a set of sessions for a particular target.

    Keeps a shared temporary directory for intermediate files.  We expose the path to that
    directory in context["process_dir"].
    """

    def __init__(self, p: "Processing"):
        cache_dir = get_user_cache_dir()
        super().__init__(prefix="sbprocessing_", dir=cache_dir)
        self.p = p
        logging.debug(f"Created processing context at {self.name}")

        self.p.init_context()
        self.p.context["process_dir"] = self.name

    def __enter__(self) -> "ProcessingContext":
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        """Returns true if exceptions were handled"""
        logging.debug(f"Cleaning up processing context at {self.name}")

        # unregister our process dir
        self.p.context.pop("process_dir", None)

        super().__exit__(exc_type, exc_value, traceback)
        # return handled


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
    def process_target(self, target: str) -> ProcessingResult:
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
        targets = {
            normalize_target_name(obj)
            for s in sessions
            if (obj := s.get(get_column_name(Database.OBJECT_KEY))) is not None
        }

        target_task = self.progress.add_task("Processing targets...", total=len(targets))

        results: list[ProcessingResult] = []
        try:
            for target in targets:
                self.progress.update(target_task, description=f"Processing target {target}...")
                # select sessions for this target
                target_sessions = self.sb.filter_sessions_by_target(sessions, target)

                # we only want sessions with light frames
                target_sessions = self.sb.filter_sessions_with_lights(target_sessions)

                if target_sessions:
                    self.sessions = target_sessions
                    result = self.process_target(target)
                    results.append(result)

                # We made progress - call once per iteration ;-)
                self.progress.advance(target_task)
        finally:
            self.progress.remove_task(target_task)

        return results
