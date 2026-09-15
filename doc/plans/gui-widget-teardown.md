# Plan: destroy a `gui` test's widgets on the GUI thread (the xdist SIGSEGV)

## Goal & summary

Stop the sporadic, **xdist-only SIGSEGV in `tests/unit/test_gui.py`** — the one that
killed `gw31` in `test_every_page_refreshes_without_error` after the Masters-tree
work added tests ("more widgets, more tests → the crash went from rare to likely").

It is a *third* crash in the same area as
[`qt-object-lifetimes.md`](qt-object-lifetimes.md) but with a different cause, and it
is **not** about the Masters change: the tests that shift xdist's load balancing only
made a latent harness bug probable.

**Root cause.** A Qt widget must be destroyed on the GUI thread. Nothing in the
suite ever destroyed the test widgets:

1. `qtbot.addWidget()` makes pytest-qt call `close()` + `deleteLater()` at teardown.
2. Qt delivers a `DeferredDelete` event **only from a running event loop** — the event
   records the loop level it was posted at and is skipped while no loop runs. A pytest
   session never enters one, so `deleteLater()` did nothing:

   ```
   valid after close + deleteLater + processEvents():  True    # still alive in C++
   valid after sendPostedEvents(DeferredDelete):        False   # actually deleted
   ```
3. The widget therefore stayed alive in C++ while its Python wrapper became garbage
   (the window/page wrappers form cycles — `window ↔ bridge`, page ↔ worker callbacks).
4. Whoever next ran a **cyclic collection** dropped the wrapper, and shiboken then
   destroyed the *still-live* C++ widget tree **on that thread**. Under xdist that was
   routinely a `QThreadPool` thread running a later test's job (the Publish page's
   keyring identity job allocates heavily, so it triggers collections).

Qt's item views make that fatal: `QAbstractItemView::~QAbstractItemView` stops seven
timers — `QBasicTimer::stop: Failed. Possibly trying to stop from a different thread`
is the calling card — and then calls `d->disconnectAll()`, which walks connections
whose owners the concurrently-busy GUI thread has already freed → SIGSEGV in
`QObject::disconnectImpl`, from a stack whose bottom is a QThreadPool thread.

## Evidence

| what | how |
|---|---|
| native crash stack | `LD_PRELOAD` handler (`/tmp/nativebt.c`) chained to faulthandler |
| faulting frame | `~QAbstractItemView` → `QAbstractItemViewPrivate::disconnectAll()` (Qt 6.7 source, `qabstractitemview.cpp:681`) |
| faulting thread | `QThreadPoolPrivate::stealAndRunRunnable` region + `start_thread` = **a pool thread** |
| why the warning | the seven `QBasicTimer::stop()` calls in that very destructor; Qt warns when the calling thread has no event dispatcher |
| the widget was never deleted | the `deleteLater`/`processEvents` experiment above |
| wrappers are garbage | `gc.DEBUG_SAVEALL` probe: a test-built `MainWindow` is in `gc.garbage` after the test drops it, and `gc.collect()` frees it |
| it is the *same* bug serially | with the fix disabled (`-p noflush`), `pytest tests/unit/test_gui.py -n0` segfaults (exit 139, 2 of 3 runs): the faulting thread is the **main** thread "Garbage-collecting" inside `pytestqt._process_events` → `QTimerInfoList::activateTimers`, while the pool thread runs `workers.py:131 run → github_identity_job → keyring` |

## Fix

`tests/conftest.py`, in the existing teardown hook — the natural place, next to the
drain that already exists for the sibling crash:

| where | change |
|---|---|
| `_destroy_pending_gui_widgets()` (new) | `QApplication.processEvents()`, then `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`, then `processEvents()` again, then `gc.collect()` — all on the GUI thread, after the pool is idle and before fixtures are finalized |
| `pytest_runtest_teardown` (existing, `tryfirst`) | calls it for `gui` tests, right after `_drain_qt_thread_pool` |
| `ui/qt/workers.py::guard_callback` (new) | wraps a job callback so it is dropped once its receiver's C++ object is gone, for the callbacks PySide cannot tie to a receiver |

The event order matters: pending reports are delivered **before** the deletes, because a
job that finished during the drain has a queued report whose callback may be a
`partial` (`TargetsPage._request_sessions`). Such an opaque receiver is not
auto-disconnected by Qt, so deleting the widget first made that report raise
`RuntimeError: Internal C++ object ... already deleted` from inside the event loop —
a teardown error pytest-qt reports as a failure. `guard_callback` covers the residual
case (the drain times out, or a report is queued between the two `processEvents()`
calls), and is applied where a callback cannot be a bound method:
`Page.start_job`, `TargetsPage._request_sessions`, `_PreviewPopup._load_text/_load_image`.
It mirrors `Worker.run`'s and `EventBusBridge._on_event`'s `shiboken6.isValid` guards —
a late report is now dropped rather than raised into a dead widget.

Why this is the right layer:

- **The drain and the flush belong together.** Waiting for the pool removes the race
  with a live job; destroying the widgets here removes the "destruction happens later,
  somewhere else" race. Both are harness-only concerns.
- **The product is not exposed the same way.** Its widgets are C++-owned (pages live in
  `MainWindow`'s `QStackedWidget`, dialogs get a parent), and shiboken never deletes a
  C++-owned object, so an off-thread GC cannot destroy them — which is why this only
  ever bit the suite, where tests create top-level, parentless widgets.
- **`gc.collect()` is safe here**: it frees only unreachable objects, so a widget a
  still-running job refers to is untouched (and the drain has already waited for those).

The flush also makes the suite *destroy* its widgets at all: a page/window destruction
log shows **0** destructions during a run before, and **58, all on `MainThread`** after.

## Testing strategy

| test | pins |
|---|---|
| `test_gui.py::test_a_tests_widgets_are_destroyed_here_not_by_another_threads_gc` | `deleteLater()` alone leaves the C++ object alive, and the teardown flush deletes it (fails if the flush is removed — verified with the `noflush` plugin) |
| `test_gui.py::test_a_late_report_is_dropped_for_an_opaque_callback` | `guard_callback` delivers while the receiver lives and drops afterwards |
| `pytest tests/unit/test_gui.py -n0` (**with the fix**) | 64 passed; the same command with the flush disabled segfaults |
| detector loop, `-n auto -p poollgc` (a GC at the start of every pool job = worst case) | 0 crashes after; the same configuration reproduces the crash before |

## Risks / open questions

- **Cost**: one extra `gc.collect()` per `gui` test. Measured nil (`test_gui.py -n0`:
  10.7 s with the flush vs 10.7 s without, run-to-run noise dominates).
- **Unregistered widgets**: a widget a test creates but never passes to
  `qtbot.addWidget()` is only swept by the `gc.collect()` — which is why that call is
  there too. A widget dropped *mid-test* is still exposed until the next teardown; the
  convention to follow is to register every widget with `qtbot`.
- **Deleting widgets pytest-qt will touch again**: not possible — pytest-qt's
  `_close_widgets` deletes `item.qt_widgets` as it closes them, and it wraps the hook,
  so it has already run when the flush does.