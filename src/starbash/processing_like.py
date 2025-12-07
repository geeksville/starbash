from typing import Any, Protocol

from rich.progress import Progress

from starbash import StageDict
from starbash.app import Starbash
from starbash.database import SessionRow


class ProcessingLike(Protocol):
    """Minimal protocol to avoid importing Processing and creating cycles.

    This captures only the attributes used by ProcessedTarget.
    """

    context: dict[str, Any]
    sessions: list[SessionRow]
    sb: Starbash
    processed_target: Any | None  # FIXME, actually a ProcessedTarget

    @property
    def stages(
        self,
    ) -> list[StageDict]: ...

    progress: Progress

    def add_result(self, result: Any) -> None: ...

    # kinda nasty shouldn't be here - FIXME, needed by ProcessedTarget constructor due to init sequence
    def _set_output_by_kind(self, kind: str) -> None: ...
