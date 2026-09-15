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

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)

__all__ = ["CancelToken", "JobCancelled", "WorkerSignals", "Worker", "run_async"]

#: Workers that are still in flight.
#:
#: Python keeps a reference to every submitted :class:`Worker` until its ``done``
#: signal has been delivered, so a caller that ignores the return value of
#: :func:`run_async` (a very natural thing to do) still hears back.  Measured before
#: this set existed: with no reference kept, only 7 of 60 callbacks arrived.
#:
#: That is also why :class:`Worker` sets ``autoDelete(False)``: when Qt owned the
#: runnable, C++ deleted it - and its signal object - the moment the job returned,
#: *underneath* the wrapper this set keeps, leaving a dangling object that a caller
#: (``github_login._stop_worker`` cancels its worker, say) or this very set could
#: still reach.  Releasing the reference on ``done`` is what frees it now.
_live_workers: set[Worker] = set()


def _signal_source_is_alive(signals: QObject) -> bool:
    """Whether ``signals`` still has a live C++ object behind its Python wrapper.

    PySide keeps the wrapper of a deleted C++ object around, but calling into it
    raises (``RuntimeError: Signal source has been deleted``) - and, once the freed
    memory has been handed to something else, can crash the process instead.  A job
    can outlive the Qt objects it reports to (the window closed, or the interpreter
    is shutting down while the job is still running), so a worker checks before it
    emits; see :meth:`Worker.run`.
    """
    return shiboken6.isValid(signals)


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
        # Python owns this runnable (it created it, and it has no parent), so Qt must
        # not delete the C++ side from under the wrapper :data:`_live_workers` holds
        # until ``done`` has been delivered - that left a dangling wrapper whose
        # signals had already gone.  With auto-delete off the runnable lives exactly
        # as long as the Python reference does, and shiboken frees it on the GUI
        # thread (where the reference is dropped).
        self.setAutoDelete(False)

    def _report(self, payload: Any) -> None:
        """Forward a progress payload, unless the Qt signal object is already gone."""
        if _signal_source_is_alive(self.signals):
            self.signals.progress.emit(payload)

    @Slot()
    def run(self) -> None:  # noqa: D401 - QRunnable API
        """Execute the job, translating outcomes into signals.

        An outcome is *dropped* rather than delivered when the Qt signal object has
        been destroyed while the job was running: emitting into a deleted
        ``WorkerSignals`` raises, and - when the freed memory has been handed to
        anything else since - can segfault the process instead.  That is how a
        harmless late report (the common case on a slow CI runner, or for a user who
        quits the GUI mid-job) turns into a crash.
        """
        try:
            payload: Any = self._job(self._report, self.token)
            failed = False
        except JobCancelled:
            payload, failed = "Cancelled.", True
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.error("Background job failed:\n%s", traceback.format_exc())
            payload, failed = str(exc) or exc.__class__.__name__, True

        if not _signal_source_is_alive(self.signals):
            logger.debug("Job finished after its Qt objects were destroyed: dropping the report")
            return
        if failed:
            self.signals.failed.emit(payload)
        else:
            self.signals.finished.emit(payload)
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
