"""A tiny, dependency-free event bus used to observe long-running work.

Starbash is CLI-first: the core modules (``tool.base``, ``doit``, ``app``,
``processing``) must not import a UI toolkit.  Instead they *publish* small,
structured events here, and any interested observer *subscribes*.

Observers render whatever they need: the CLI's ``ProcessingView``
(``commands/process.py``) keeps one live tree/status widget up to date for the
duration of a run, and the desktop GUI (`sb gui`) bridges the same events onto Qt
signals so its widgets update live.  Nothing in the core draws to the terminal --
a tool that drew its own Rich ``Live`` would fight the observer for the console
(see ``doc/plans/cli-live-display.md``).

Design notes
------------
* ``publish`` is deliberately infallible: a misbehaving subscriber must never
  break a processing run, so exceptions are logged and swallowed.
* Subscribers are snapshotted under a lock before being called, so a subscriber
  may (un)subscribe during dispatch without mutating the iteration.
* Events carry plain data.  Where a rich object is more convenient (e.g. a
  ``ProcessingResult``) the producer may pass it through ``data``; it is the
  *subscriber's* responsibility to only touch it on a safe thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "Event",
    "Subscriber",
    "subscribe",
    "unsubscribe",
    "publish",
    "clear_subscribers",
    "subscriber_count",
    # Stream naming for EVENT_TOOL_OUTPUT payloads.
    "STRUCTURED_STREAM_MIMES",
    "is_structured_stream",
    # Well-known event kinds (kept here so producers/consumers can't typo them).
    "EVENT_TOOL_OUTPUT",
    "EVENT_TOOL_PROGRESS",
    "EVENT_TOOL_STARTED",
    "EVENT_TOOL_FINISHED",
    "EVENT_TASK_STARTED",
    "EVENT_TASK_FINISHED",
    "EVENT_STAGE_RESULT",
    "EVENT_REINDEX_PROGRESS",
    "EVENT_REINDEX_FINISHED",
    "EVENT_PROCESS_TARGET",
    "EVENT_PREFLIGHT_FINISHED",
    "EVENT_RUN_STARTED",
    "EVENT_RUN_FINISHED",
    "EVENT_LOG_MESSAGE",
]

# ---------------------------------------------------------------------------
# Well-known event kinds
# ---------------------------------------------------------------------------

#: One line of output from an external tool. data: {cmd, stream, line}
#:
#: ``stream`` is normally ``"stdout"`` or ``"stderr"``.  A tool whose stdout is a
#: machine-readable protocol (e.g. rc-astro's ``--json`` event stream) names it
#: ``"stdout.<mime>"`` instead, so log renderers can skip it - see
#: :func:`is_structured_stream`.
EVENT_TOOL_OUTPUT = "tool.output"
#: A parsed progress percentage streamed by a tool. data: {cmd, percent, message?}
EVENT_TOOL_PROGRESS = "tool.progress"
#: An external tool started running. data: {cmd, cwd}
EVENT_TOOL_STARTED = "tool.started"
#: An external tool finished. data: {cmd, returncode, success}
EVENT_TOOL_FINISHED = "tool.finished"
#: A doit task is about to run. data: {task, title, target?, stage?, is_master?,
#: run: {..plain run-tree..}} -- the ``run`` snapshot carries this task as
#: ``running``, so a live tree can scroll to it (the snapshot published with a
#: stage result has nothing running).
EVENT_TASK_STARTED = "task.started"
#: A doit task finished. data: {task, title, success, reason, target?, stage?, is_master?}
EVENT_TASK_FINISHED = "task.finished"
#: A processing stage produced a result. data: {result, run: {..plain run-tree..}}
EVENT_STAGE_RESULT = "stage.result"
#: Reindexing progress for a repo. data: {repo, done, total, file?}
EVENT_REINDEX_PROGRESS = "reindex.progress"
#: Reindexing of a repo completed. data: {repo, indexed}
EVENT_REINDEX_FINISHED = "reindex.finished"
#: A whole target is about to be processed. data: {target, index, total}
EVENT_PROCESS_TARGET = "process.target"
#: The preflight (plan) phase finished, before any target task runs.  data:
#: {drop: [run label, ...]} where ``drop`` lists master runs the selected targets
#: do not need, so observers can remove them from the displayed pipeline.
EVENT_PREFLIGHT_FINISHED = "preflight.finished"
#: A processing run started (for the target in data). data: {target, total}
EVENT_RUN_STARTED = "run.started"
#: A processing run finished. data: {target, run: {..plain run-tree..}}
EVENT_RUN_FINISHED = "run.finished"
#: A log record was emitted (for the GUI log pane). data: {level, message}
EVENT_LOG_MESSAGE = "log.message"

#: ``<stream>.<mime>`` suffixes that mark a machine-readable protocol stream
#: rather than human-readable log text.  See :func:`is_structured_stream`.
STRUCTURED_STREAM_MIMES = frozenset({"json"})


def is_structured_stream(stream: str) -> bool:
    """Whether a tool output ``stream`` name carries machine-readable protocol data.

    ``tool_run_streaming`` names a tool's stdout ``"stdout.<mime>"`` (e.g.
    ``"stdout.json"``, as rc-astro does for its ``--json`` event stream) when the
    tool declares that stream is structured.  Such lines are protocol frames, not
    messages meant for a human - the interesting parts are republished as
    :data:`EVENT_TOOL_PROGRESS` - so log renderers (the CLI run tree, the GUI Log
    nodes) skip them instead of echoing them verbatim.

    Args:
        stream: The ``stream`` field of an :data:`EVENT_TOOL_OUTPUT` payload.

    Returns:
        True if the stream is structured (has a known mime suffix).
    """
    _, _, mime = stream.partition(".")
    return mime in STRUCTURED_STREAM_MIMES


Subscriber = Callable[["Event"], None]

_subscribers: list[Subscriber] = []
_lock = threading.RLock()


@dataclass(frozen=True)
class Event:
    """A single event: a ``kind`` string plus a plain-data payload."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)


def subscribe(callback: Subscriber) -> Callable[[], None]:
    """Register ``callback`` to receive every future event.

    Returns:
        A zero-argument function that unsubscribes ``callback`` again.  Handy
        for ``try/finally`` cleanup or for Qt signal teardown.
    """

    with _lock:
        _subscribers.append(callback)

    def _unsubscribe() -> None:
        unsubscribe(callback)

    return _unsubscribe


def unsubscribe(callback: Subscriber) -> None:
    """Remove ``callback`` if it is registered.  Missing callbacks are ignored."""
    with _lock:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass


def clear_subscribers() -> None:
    """Remove every subscriber.  Intended for tests and GUI shutdown."""
    with _lock:
        _subscribers.clear()


def subscriber_count() -> int:
    """Return the number of currently registered subscribers (mainly for tests)."""
    with _lock:
        return len(_subscribers)


def publish(kind: str, data: dict[str, Any] | None = None) -> None:
    """Publish an event of ``kind`` to all current subscribers.

    This function never raises: a failing subscriber is logged and skipped so a
    buggy observer can't abort a processing run.
    """
    event = Event(kind=kind, data=data or {})
    with _lock:
        # Snapshot so subscribers can safely (un)subscribe while we dispatch.
        targets = list(_subscribers)

    if not targets:
        return

    for callback in targets:
        try:
            callback(event)
        except Exception:  # noqa: BLE001 - a UI bug must never kill processing
            logger.exception("Event subscriber failed while handling %r", kind)
