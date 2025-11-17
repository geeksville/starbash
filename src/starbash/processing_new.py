"""New processing implementation for starbash (under development)."""

from starbash.app import Starbash
from starbash.doit import StarbashDoit
from starbash.processing import Processing, ProcessingResult


class ProcessingNew(Processing):
    """New processing implementation (work in progress).

    This is a placeholder for the refactored processing architecture.
    """

    def __init__(self, sb: Starbash) -> None:
        self.sb: Starbash = sb
        self.doit: StarbashDoit = StarbashDoit()

    def __enter__(self) -> "ProcessingNew":
        return self

    def run_all_stages(self) -> list[ProcessingResult]:
        """Run all processing stages on currently selected sessions.

        Returns:
            List of ProcessingResult objects, one per target processed.

        Raises:
            NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("ProcessingNew.run_all_stages() is not yet implemented")

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.

        Raises:
            NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("ProcessingNew.run_master_stages() is not yet implemented")
