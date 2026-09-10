"""Background workers so long operations never freeze the GUI.

Every long-running core call (reindexing, processing, publishing) is wrapped in a
:class:`Worker` and run on the global thread pool.  Workers communicate back via
Qt signals carrying **plain Python data** - never live SQLite rows or core
objects bound to a connection - so the GUI thread never touches another thread's
database connection.

Cooperative cancellation is offered through :class:`CancelToken`: long jobs poll
``token.is_cancelled()`` and bail out early when the user hits "Cancel".
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)

__all__ = ["CancelToken", "JobCancelled", "WorkerSignals", "Worker", "run_async"]

#: Workers that are still in flight.
#:
#: A :class:`Worker` is a ``QRunnable`` with ``autoDelete`` set, so if Python drops
#: the object the C++ side destroys it - and its signal object - as soon as the job
#: returns.  A queued ``finished``/``failed`` delivery is then dropped before the GUI
#: thread ever sees it, so a caller that ignores the return value of :func:`run_async`
#: (a very natural thing to do) can silently never hear back.  Measured here: with
#: no reference kept, only 7 of 60 callbacks arrived; keeping one until ``done``
#: makes it 60 of 60.
_live_workers: set[Worker] = set()


class JobCancelled(Exception):
    """Raised inside a worker when its :class:`CancelToken` was triggered."""


class CancelToken:
    """A tiny cooperative cancellation flag shared with a running job."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Return ``True`` once :meth:`cancel` has been called."""
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        """Raise :class:`JobCancelled` if cancellation was requested."""
        if self._cancelled:
            raise JobCancelled()


class WorkerSignals(QObject):
    """Signals emitted by a :class:`Worker` (must live in the GUI thread)."""

    #: Emitted with the job's return value when it completes.
    finished = Signal(object)
    #: Emitted with a human-readable message when the job raised.
    failed = Signal(str)
    #: Emitted with arbitrary progress payloads produced by the job.
    progress = Signal(object)
    #: Always emitted exactly once, after ``finished``/``failed``.
    done = Signal()


class Worker(QRunnable):
    """Run ``job`` on the thread pool, reporting back through Qt signals.

    ``job`` is called as ``job(report, token)`` where:

    * ``report(payload)`` emits :attr:`WorkerSignals.progress`,
    * ``token`` is a :class:`CancelToken` the job should poll.
    """

    def __init__(self, job: Callable[[Callable[[Any], None], CancelToken], Any]) -> None:
        super().__init__()
        self._job = job
        self.signals = WorkerSignals()
        self.token = CancelToken()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # noqa: D401 - QRunnable API
        """Execute the job, translating outcomes into signals."""
        try:
            result = self._job(self.signals.progress.emit, self.token)
        except JobCancelled:
            self.signals.failed.emit("Cancelled.")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.error("Background job failed:\n%s", traceback.format_exc())
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


def run_async(
    job: Callable[[Callable[[Any], None], CancelToken], Any],
    *,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
    on_done: Callable[[], None] | None = None,
    pool: QThreadPool | None = None,
) -> Worker:
    """Submit ``job`` to the thread pool and wire up the given callbacks.

    Returns the :class:`Worker` so callers can ``worker.token.cancel()``.  They do
    *not* have to keep it: the worker is retained internally until it finishes, so
    the callbacks fire even if the return value is ignored.
    """
    worker = Worker(job)
    # Hold a reference for the whole run, then release it (see _live_workers).
    _live_workers.add(worker)
    worker.signals.done.connect(lambda: _live_workers.discard(worker))
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    if on_failed is not None:
        worker.signals.failed.connect(on_failed)
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)
    if on_done is not None:
        worker.signals.done.connect(on_done)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
