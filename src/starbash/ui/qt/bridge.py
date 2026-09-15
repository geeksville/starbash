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
from collections.abc import Callable

import shiboken6
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
        #: Detaches us from the bus; ``None`` once detached.
        self._unsubscribe: Callable[[], None] | None = events.subscribe(self._on_event)
        # Detach when the C++ object dies, whatever route it takes - a window Qt
        # deletes, or one whose ``closeEvent`` a page vetoed so ``close()`` never ran.
        # A subscription is a plain Python reference to ``self._on_event``, so without
        # this it outlives the QObject: the next publish from *anywhere* in the process
        # then calls into the deleted object and raises ``RuntimeError: Signal source
        # has been deleted`` (which became a ``RecursionError`` in an unrelated test on
        # CI, once an in-process tool's log forwarder republished that error record).
        #
        # The handler is a lambda rather than a method: PySide does not deliver
        # ``destroyed`` to a slot *defined on the object being destroyed* (measured -
        # a bound method never ran, a plain callable always did).
        self.destroyed.connect(lambda *_: self.close())

    def _on_event(self, event: events.Event) -> None:
        if not shiboken6.isValid(self):
            # Qt already deleted our C++ object and the ``destroyed`` connection did
            # not reach us first (it is emitted from the destructor, so nothing about
            # this should be relied on twice): drop the dead subscription here rather
            # than emitting into freed memory.
            self.close()
            return
        self.received.emit(event.kind, event.data)

    def close(self) -> None:
        """Stop bridging (idempotent)."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
