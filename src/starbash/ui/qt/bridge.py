"""Bridge the core event bus onto Qt signals.

The core publishes plain :class:`starbash.events.Event` objects.  Widgets want Qt
signals.  :class:`EventBusBridge` is the single adapter between the two: it
subscribes to the bus and re-emits every event as one generic Qt signal.

Because the core may publish from a worker thread while the bridge lives in the
GUI thread, Qt's automatic (queued) cross-thread connection delivers the signal
on the GUI thread - so handlers can safely touch widgets.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from starbash import events

logger = logging.getLogger(__name__)

__all__ = ["EventBusBridge"]


class EventBusBridge(QObject):
    """Re-emit every core event as ``received(kind, data)`` on the GUI thread."""

    #: ``(kind: str, data: dict)`` for every published core event.
    #:
    #: Deliberately *not* named ``event``: ``QObject.event()`` is the virtual Qt's
    #: own event loop calls, and shadowing it with a Signal breaks event delivery.
    received = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unsubscribe = events.subscribe(self._on_event)

    def _on_event(self, event: events.Event) -> None:
        self.received.emit(event.kind, event.data)

    def close(self) -> None:
        """Stop bridging (idempotent)."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None  # type: ignore[assignment]
