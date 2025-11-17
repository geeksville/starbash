"""New processing implementation for starbash (under development)."""

from starbash.app import Starbash
from starbash.doit import StarbashDoit
from starbash.processing import Processing, ProcessingResult


class ProcessingNew(Processing):
    """New processing implementation (work in progress).

    This is a placeholder for the refactored processing architecture.
    """

    def __init__(self, sb: Starbash) -> None:
        super().__init__(sb)
        self.doit: StarbashDoit = StarbashDoit()

    def __enter__(self) -> "ProcessingNew":
        return self

    def process_target(self, target: str) -> ProcessingResult:
        """Do processing for a particular target (i.e. all sessions for a particular object)."""
        raise NotImplementedError("ProcessingNew.process_target() is not yet implemented")

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.

        Raises:
            NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("ProcessingNew.run_master_stages() is not yet implemented")
