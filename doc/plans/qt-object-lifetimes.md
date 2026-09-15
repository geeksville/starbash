# Plan: Qt object lifetimes vs. background work (two crashes, one cause)

## Goal & summary

Make Starbash's Qt objects safe to outlive — in both directions — so that neither a
**worker outliving its report target** nor a **listener outliving its window** can
turn into a crash or a bogus test failure.

Two reports looked unrelated:

1. `tests/unit/test_gui.py::test_every_page_refreshes_without_error` died with
   **SIGSEGV (exit 139)** — repeatably under load, sporadically otherwise, and on the
   slow CI runners too. Sometimes it hung at interpreter exit (exit 124) instead.
2. CI showed a non-GUI test failing for no reason of its own:
   `tests/unit/test_tool.py::TestPythonTool::test_python_tool_executes_simple_code`
   → `RuntimeError: Signal source has been deleted` at
   `ui/qt/bridge.py: _on_event` → then `RecursionError`.

Both are the same defect: **a Python reference to a Qt object kept alive after Qt had
deleted the C++ object behind it.** PySide tolerates the first call into such a
wrapper with `RuntimeError: Signal source has been deleted`; once the freed memory
has been handed to anything else, the same call **writes into arbitrary memory**.

## Bug 1 — a worker outliving the session (fixed)

`run_async` submits jobs to the global thread pool and nothing waits for them.
`PublishPage.refresh()` starts `github_identity_job`, whose keyring scan is slow —
`keyring.core.get_password` → `get_keyring` → `get_all_keyring()` → `entry_points()`
→ reading every installed distribution's metadata. A thread dump taken in
`pytest_runtest_teardown` caught it exactly there:

```
workers.py:95 run  ←  jobs.py:199 github_identity_job  ←  credentials.py load
  ← keyring get_password → get_all_keyring → importlib_metadata.entry_points
```

So the worker was **always** still running when the session ended (measured
`QThreadPool.activeThreadCount() == 1` before *every* teardown), and at interpreter
shutdown Python dropped the `WorkerSignals` it emits from. The late
`finished`/`done` emit then hit freed memory: `RuntimeError`, SIGSEGV, or (while
holding the import lock) a hang.

Fix, in three parts:

| where | change |
|---|---|
| `tests/conftest.py` | `pytest_runtest_teardown` (`tryfirst`) drains the global pool for `gui` tests before any fixture finalizer runs; `pytest_sessionfinish` drains once more. Bounded (10 s per test / 30 s session) and it warns if a job looks stuck. |
| `ui/qt/workers.py` | `Worker.run` drops an outcome whose `signals` no longer exist (`shiboken6.isValid`), and `_report` is a guarded progress reporter. `setAutoDelete(False)` so Qt cannot delete the runnable under the wrapper `_live_workers` (or a caller such as `github_login._stop_worker`) holds. |
| `ui/qt/bridge.py` | see Bug 2. |

## Bug 2 — a listener outliving its window (fixed)

`EventBusBridge` subscribes `self._on_event` to the global bus and only ever detaches
in `close()`, which `MainWindow.closeEvent` calls — except when it returns early
because a page refused to leave. The subscription is a plain Python reference, so it
**outlives the QObject**:
`tests/unit/test_targets_page.py::test_navigation_is_blocked_when_a_page_refuses_to_leave`
creates a `MainWindow` (hence a bridge) and that module has no `clear_subscribers`
fixture — measured `subscriber_count() == 1` at session end after that one test.

Once such a bridge's C++ object is gone, every later `publish` anywhere in the
process calls into it. On its own that is only a logged `RuntimeError` — but
`publish`'s error path is `logger.exception`, and during an in-process python-tool run
the tool's log forwarder accepts *every* record (`_ToolSourceFilter(None)` →
`from_tool = True`) and republishes it as a `tool.output` event. So the report
publishes, the stale subscriber fails again, and the recursion never ends. That is
the CI traceback, and why it surfaced in a *tool* test in a different module.

Fix:

- `EventBusBridge.__init__` connects `destroyed` → `self.close()` (via a **lambda**:
  PySide does not deliver `destroyed` to a slot defined on the dying object — a bound
  method never ran in a controlled experiment, a plain callable always did).
- `EventBusBridge._on_event` also self-heals: `shiboken6.isValid(self)` fails →
  detach and return, instead of emitting.
- `events._report_subscriber_failure` refuses to log a failure while a failure report
  is already in flight on this thread, so `logging` can never re-enter `publish`
  recursively. The outermost failure is still logged.

## Testing strategy (what was measured)

`PYTHONPATH=/tmp/slowimport` (a `sitecustomize` that sleeps 0.1–0.4 s per
`keyring`/`importlib_metadata` import) widened the race; a pytest plugin drained the
pool (or did not) for an A/B.

| arm | late `emit` errors per run |
|---|---|
| no drain, hostile 0.4 s | 2, 2, 2, 2 |
| drain, hostile 0.4 s | 0, 0, 0 |
| no drain, 0.1 s | 2, 2, 2 |
| drain, 0.1 s | 0, 0, 0 |
| no drain, no shim | 2 |
| **repo fix only** (conftest drain, no plugin), 0.4 s | **0, 0, 0** |

Beyond the flake: `-m gui` across six GUI modules under hostile timing → **159
passed, 0 late emits**; the whole suite as CI runs it (xdist) → **1206 passed, 1
skipped, 0 late emits** (twice). Regression tests added:

| test | pins |
|---|---|
| `test_events.py::test_a_failing_subscriber_does_not_recurse_through_logging` | one failure report, no recursion, when a log handler publishes |
| `test_gui.py::test_a_destroyed_bridge_detaches_itself_from_the_bus` | a bridge Qt deleted is no longer a subscriber |
| `test_gui.py::test_a_worker_whose_qt_objects_died_drops_its_report` | `_report`/`run` are no-ops once the signals are gone |
| `test_gui.py::test_a_worker_is_still_usable_by_its_caller_after_it_finishes` | `setAutoDelete(False)` keeps a kept worker valid (pre-fix: `isValid == False`) |

## Open question — should closing the GUI wait for in-flight jobs?

`MainWindow.closeEvent` closes the bus and the app context, then returns; a job that
is still running keeps going against a closed `Database` and a dying interpreter.
With the guards above that is now *harmless* (the report is dropped), but the work is
silently lost, and a job that writes files can still write them after
`Starbash.close()`.

- **A — leave it**: nothing to do; the guard already prevents the crash.
- **B — `workers.shutdown(timeout)`** (cancel every token, then `waitForDone`),
  called from `closeEvent` after `_bus.close()`: the close blocks for up to
  `timeout`, so quitting mid-job shows a short delay; cancellation is cooperative, so
  a job that ignores its token still outlives the timeout.
- **C — cancel and abandon** (`token.cancel()` only): instant close, but the job
  still touches the filesystem/database afterwards.

Recommendation: **B with a short timeout** (a second or two) — but it is a
user-facing UX call, so it needs an explicit decision rather than being slipped in
with this fix. Nothing in the code above depends on the answer.

## Risks / notes

- The drain adds a bounded wait per `gui` test. Measured cost is nil (the identity
  job finishes in ~30 ms; a stuck job costs the timeout and logs a warning, and the
  guards keep it harmless).
- `setAutoDelete(False)` means a worker whose `done` is never delivered is not freed
  until its wrapper is collected — the same lifetime the caller's own reference has;
  `run_async`'s `done` connection is what drops the internal one.