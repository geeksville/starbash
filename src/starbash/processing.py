"""Base class for processing operations in starbash."""

import logging
from abc import abstractmethod
from dataclasses import dataclass, field

from starbash.database import SessionRow
from starbash.exception import UserHandledError


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


class Processing:
    """Abstract base class for processing operations.

    Implementations must provide:
    - run_all_stages(): Process all stages for selected sessions
    - run_master_stages(): Generate master calibration frames
    """

    @abstractmethod
    def run_all_stages(self) -> list[ProcessingResult]:
        """Run all processing stages on currently selected sessions.

        Returns:
            List of ProcessingResult objects, one per target processed.
        """
        pass

    @abstractmethod
    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.
        """
        pass

    # --- Lifecycle ---
    def close(self) -> None:
        pass

    # Context manager support
    def __enter__(self) -> "Processing":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
