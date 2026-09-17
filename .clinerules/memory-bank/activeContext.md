# Active Context

## Current work focus — richer per-target report pages (**implemented 2026-09-16**, not committed)

The per-target markdown pages that `sb publish` / the GUI write to
`site/targets/<slug>.md` (then upload to GitHub Pages) now carry a **pretty HTML
tree of the processing stages with their parameters**:

- Renderer: `stage_tree_html()` in `src/starbash/publish/github.py` (plus
  `_param_row`/`_stage_row` helpers and the scoped `_STAGE_TREE_CSS`).  It turns
  `ProcessedTarget.stage_options()` into a `<div class="sb-stages">` block that
  embeds in the kramdown page (flush-left lines, no blank lines inside, so
  kramdown passes it through raw).  **Recipe defaults render in a grey class
  (`.sb-default`), per-target overrides in a bold amber accent
  (`.sb-override`)**, with the grey default shown beside the override it
  replaced; a legend explains the two.  Excluded stages stay visible but dimmed,
  struck through, with a dashed *skipped* pill — so the tree shows exactly which
  stages were used.  Stage headers also carry the recipe's declared `tool`
  (e.g. *siril*) and `role` as pills and the stage description.  **The stage
  name itself is a link to the recipe its TOML came from** whenever
  `recipe_url` is an http(s) URL (dotted underline, colour inherited); local or
  `pkg://` sources render as plain text.  All text is `html.escape`d.
- To feed it, `stage_declarations()` (`processed_target.py`) now also captures
  the recipe stage's `tool` (from `stage.tool.name`) and `role`, and
  `StageOption` gained additive `tool`/`role` fields that `stage_options()`
  populates (GUI consumers ignore unknown fields, so nothing else changed).
- `GitHubPublisher.publish()` builds the declarations **once** via the new
  guarded `_stage_declarations()` (`getattr(self.sb, "get_recipes", None)`; a
  context without it — the tests' `SimpleNamespace` — gets `{}` and the report
  just omits defaults), and `_targets()` now also returns the `ProcessedTarget`
  per target instead of dropping it.  The template `target.md.jinja` renders
  `{{ stage_tree }}` under the *Workflow* heading and also shows
  **Coordinates: RA / Dec** when `about.toml` carries them (skipping the `"N/A"`
  placeholder).
- CSS colours are tuned for the site's dark `jekyll-theme-midnight` theme
  (`_config.yml`): defaults `#9fb0c3`, overrides `#ffb454`.
- Tests: six new cases in `tests/unit/test_publish_github.py` (tree classes,
  escaping, empty-tree, publish with recipe declarations, publish without
  recipes, coordinates).  Full suite 1342 passed / 1 skipped after `just lint`.

## Previous work — GUI first-run setup wizard (**implemented 2026-09-16**, not committed)

`doc/plans/gui-setup-wizard.md` is done: the GUI's first run is a six-page
**`QWizard`** (welcome → you → output folders → raw-image folder picker → tools →
checklist) in `ui/qt/pages/wizard.py`, replacing the single-form `QDialog`.

- **Flow.** `Page` is an `IntEnum` of the six ids, and one `SetupWizard.nextId()` holds
  both dynamic edges (page 4 → 6 whenever no required tool is missing).
  `SetupPage.refresh()` re-reads the world and is called from `currentIdChanged` —
  *not* `initializePage()`, which `IndependentPages` only ever runs once.
- **Page 2 requires a username** (`isComplete()` computed from the field's own text,
  deliberately *not* a `user.name*` mandatory field, which Qt would count as
  "unfilled" for an already-configured user on a re-run). `validatePage()` writes the
  same keys as `sb user setup`, so each page saves as it is left.
- **Page 5 is the Siril gate:** `isComplete()` is False while a
  `ToolSeverity.REQUIRED` tool is missing (Qt turns that into a disabled
  *Next*/*Finish*), `validatePage()` re-checks and refuses, and *Re-check* calls the
  new `Tool.invalidate_availability()` — `ExternalTool.is_available` caches its probe,
  so a naive re-read kept reporting the old answer after the user installed Siril.
- **Page 6 is the checklist.** Only the *Tools* row gates *Finish*; the other three
  gate the two custom closing buttons — Qt does **not** gate custom buttons on
  `isComplete()`, so `SetupWizard` disables them at construction and again on every
  page change that is not the last, and `DonePage.refresh()` is the only thing
  allowed to arm them (see §3.6.3 of the plan).
- **Wiring:** `run_setup_dialog()` returns an action (`ACTION_PROCESS` /
  `ACTION_TARGETS` / `None`); `MainWindow.run_setup_wizard` + `_apply_setup_action`
  (reload context first, then `sb.selection.clear()` + `ProcessingPage.start_run()`)
  and `show_page_of_type()`; `ui/qt/app.py` schedules the wizard with
  `QTimer.singleShot(0, …)` after `window.show()`, guarded by
  **`is_wizard_complete(sb)`** — not by "is there a name" (revised 2026-09-16, §5.4
  of the plan): `wizard.setup_checklist(sb)` is the single list of setup minimums
  (`(title, complete, hint)` rows: your details / output folders / your raw images /
  tools), the closing page draws it and `is_wizard_complete()` folds it into one
  bool, so a tick and a re-opening wizard cannot disagree. The raw-image row wants a
  *folder*, not FITS inside it, and only a **required** tool blocks — both to match
  the pages and to avoid re-asking a user who is fine. Bare `sb` opens the GUI
  (Qt-free `desktop_session_available()` in `ui/qt/__init__.py`, honoured by
  `main.py`; `--no-gui` opts out), so an SSH box keeps the CLI path.
- **Tests:** `tests/unit/test_setup_wizard.py` (31 cases: the cached-probe *Re-check*
  regression, `nextId` skips, per-page saving, checklist gating, the watermark
  centring, the folders/images `validatePage` refusals, the closing-button gating,
  and three that pin `is_wizard_complete`/`setup_checklist` — each minimum in turn,
  the required-tool gate, and that `DonePage.blockers()` is the very same list),
  `tests/unit/test_gui_launch.py` (the bare-`sb` decision + three start-up triggers:
  first run, "has a name but no folders", and fully set up),
  the two old wizard tests removed from `test_gui.py`, `--no-gui` added to
  `test_cli.py`.
- **The three `attn ai` review notes were fixed the same day** (plan §3.6):
  - *Welcome watermark.* ModernStyle paints `WatermarkPixmap` top-left in a
    full-height label Qt builds *during* the first show, so
    `_centre_pane_mark(wizard)` (called from `SetupWizard.showEvent()`) finds that
    label by `QPixmap.cacheKey()` — the label's copy shares the watermark's key, the
    logo's differs — and sets only its alignment to `AlignCenter`.
  - *Output-folders page had a skip-an-answer path.* The checkbox's unticked state
    counted as "I keep them elsewhere", so the wizard walked on with nowhere to
    write. It is now two `QRadioButton`s (*the default folders*, pre-selected, or
    *somewhere else* + *Choose folder…*); `isComplete()`/`validatePage()` refuse the
    somewhere-else-with-no-folder answer, and picking a folder ticks the custom radio
    itself.
  - *Images page could be empty, and the closing buttons were live from page 1.*
    `ImagesPage.isComplete()`/`validatePage()` now require **a folder** (not FITS
    inside it — a folder of JPEGs only *warns*, since `raw/M31/lights` is normal),
    and `SetupWizard._disable_action_buttons()` runs at construction and on every
    non-`DONE` page change, because Qt creates custom buttons enabled and never
    consults `isComplete()` for them (hiding them does not work either — Qt re-shows
    them).
- **Two traps found while testing:** `setCurrentId()` is a no-op until the wizard is
  *shown* (the tests `show()` it offscreen first); and a raw-image repo is **not**
  simply "anything `regular_repos` returns" — that list hides only a plain `"recipe"`,
  while the default recipes Starbash installs for itself are `"std-recipe"`, so
  `_raw_image_repos()` filters an explicit kind set instead. A third, from the
  follow-ups: `tools_ok` must patch `tool_statuses` as well as
  `_required_tools_missing`, or a host without Siril fails the tools-page happy path.
- **Verified 2026-09-16:** `just lint` → *0 errors, 0 warnings, 0 notes*; full suite
  **1286 passed, 1 skipped**, the only failure being
  `test_tool.py::TestSirilToolRun::test_siril_tool_run_with_empty_script` — that test
  is deliberately mandatory (CI installs Siril) and this container has no `siril`
  binary, so it is environmental, not a regression.
- **Plan doc synced the same day:** `gui-setup-wizard.md` gained §3.6 (the three
  follow-ups above), §5.1 now opens with "what shipped is not this" (the images
  folder is added *synchronously* in `validatePage()` — no `add_repo_job`/worker), and
  §7's test table was rewritten with the real test names (the original list used
  working titles that never existed) plus a note listing what the plan promised but
  never shipped.
- **Next up:** nothing outstanding for this plan; the open questions elsewhere are the
  cancel-and-wait one in `qt-object-lifetimes.md` and phase 2 of `stage-roles.md`.

## Previously — StarNet detection inside Siril's flatpak sandbox

**Implemented 2026-09-15**, **not committed**.

- **The gap.** `StarnetTool` read Siril's settings from one place — platformdirs'
  `~/.config/siril` — so on Linux, where Siril is normally the flatpak app, the probe
  looked at a directory that Siril cannot see: flatpak gives its sandbox a private
  config home (`XDG_CONFIG_HOME=$HOME/.var/app/$FLATPAK_ID/config`), so
  `config.<version>.ini` really lives in
  `~/.var/app/org.siril.Siril/config/siril/`.  StarNet was therefore reported missing
  (and the star-removal stage skipped) on exactly the install most Linux users have,
  while macOS/Windows (native Siril) were fine — this closes the *Known issue* in
  `progress.md` and the *Open question* under *Integration CI* below.
- **`src/starbash/tool/starnet.py`** — `SIRIL_FLATPAK_APP_ID`;
  `_siril_flatpak_config_dir()` (the sandbox XDG path), `_siril_is_flatpak()` (the app
  id appears in the resolved `executable_path` — `SirilTool`'s candidate commands
  include it — or in a `siril.path` override, guarded by `MissingToolError`), and
  `_siril_config_dirs()`: **both** directories, the likely-live one first, de-duped,
  returned whether or not they exist (so a probe can say where it looked).
  `_starnet_configured()` scans every one of them — a dangling `starnet_exe` in one
  install must not hide a usable one in the other — and a newly found `starnet2` is
  written into the live directory's newest `config.*.ini` only
  (`_siril_config_to_write()`), rather than into whichever file happened to sort last
  in one directory's glob.  The miss path gained a `logger.debug` naming the
  directories scanned and whether `starnet2` was on the PATH, since "StarNet was not
  detected" was otherwise indistinguishable from "we looked in the wrong place".
- **The write's *timing* is unchanged.** The preference order only decides which
  existing file the auto-configuration fills in; a blank `starnet_exe` plus a
  `starnet2` on the PATH still fills it, and a non-blank one is still never rewritten
  (the deliberate side effect `tool-warnings.md` documents).
- **Tests** (`tests/unit/test_tool.py`, 10 new cases in `TestStarnetTool`): a
  flatpak-only config found (native dir present but empty), either directory's setting
  honoured, a flatpak dangling path not hiding a native usable one, the write landing
  in the flatpak file *and* inventing nothing in the other install's directory, only
  the live directory written when both hold a config, the newest `config.*.ini`
  version chosen, the diagnostic line, plus the search order itself (flatpak first for
  an app-id/`siril.path`-overridden Siril, native first otherwise, and identical
  directories not scanned twice).  `_make_tool()` now stubs `_siril_config_dirs`,
  which also keeps a real Siril config on the developer's machine out of the result.
- **Verified** (2026-09-15): `just lint` → *0 errors, 0 warnings, 0 notes*; full unit
  suite **1253 passed, 1 skipped**.  The *real* methods (nothing stubbed but
  `$HOME`) were also run against a temp home holding only the sandbox layout: both
  directories came back, the flatpak `config.1.4.ini` was found and filled with the
  `starnet2` from the PATH, and a value already set there was honoured.
- **Not done**: still unverified against a real flatpak run (this container has no
  flatpak), and the three-platform CI difference has not been re-measured.
  `just install-starnet` still installs 2.5.4 while the integration CI pins 2.6.2
  (pre-existing and unrelated — see the *Integration CI* note below).

## Current work focus — piped runs keep their log (`ui/cli_events.py`)

**Implemented 2026-09-15**, **not committed**.

- **The gap it closes.**  Fix 5/6 of the CLI-live-display thread gated the live display on
  `supports_live_display()` and, on a sink that cannot animate, printed only
  `runs_to_table()` at the end.  So `sb process auto > run.log` kept a table and *nothing
  else*: no `Target 1/3: M31` banner, no `Running: siril-cli -s -`, no tool stdout/stderr,
  no per-task status lines — the log you redirected the run for was the part that went
  missing.  Both `ReindexView` and `ProcessingView` also carried their own copy of the
  policy (`_interactive`, `Live(...) if ... else None`, `__enter__`/`__exit__`, `_finished`,
  `_refresh()`, `finish()`), and the choice of handler was invisible at the call site.
- **`src/starbash/ui/cli_events.py` (new)** — `CliEventHandler`: the lifecycle
  (subscribe/unsubscribe, at most one `Live`), the run model (`_note_run()`/`_drop_runs()`
  folding the bus's `run` snapshots into `_runs`/`_order`, `_run_caption()`/`_task_caption()`,
  `print_summary()` → `rich.runs_to_table`), and the policy as a hook:
  `_make_live()` returning `None` means "this sink cannot animate"; `interactive` reports a
  frame is owned; `__exit__` records `_aborted` and always calls `finish()` *before* the
  frame stops (so the settled frame is what remains).  `for_console(title, console)` is the
  one place the choice is made — a terminal gets `cls(...)`, anything else
  `SimpleLoggingEventHandler`.
- **`SimpleLoggingEventHandler`** — the fallback, and now a real log: one plain line per
  notable event (`Processing N task(s)`, run/target banners, `stage: title`,
  `Running: <cmd>`, tool stdout/stderr, `Success`/`Failed`/`Up-to-date`/`Ignored` per task,
  `Indexing <repo>` announced once + `Indexed N file(s) in <repo>`, rc-astro's status text),
  then `<title>: done` (or `: interrupted` when the block raised) and the flat summary.
  Tool lines print `markup=False, highlight=False` so a `[2024-01-01]` stays literal and the
  file greps; structured `stdout.<mime>` frames are skipped via
  `events.is_structured_stream()` (already republished as `tool.progress`); a bare `%`
  progress is skipped while its `message` is not; the table is omitted when no run was
  planned (an empty "No results" would read as a finding).  Reindex's sentence is
  deliberately identical to `ReindexView`'s, so one grep covers a bare scan and a run's
  pre-run scan.
- **Views keep only their painting.**  `ReindexView(CliEventHandler)`
  (`_make_live()` → `Live(self, ...)`, `REFRESH_PER_SECOND = 8`) and
  `ProcessingView(CliEventHandler)` (`_make_live()` → `Live(self, ...)`, 4).  `auto()` /
  `masters()` / `repo.py`'s three scan sites now build through `for_console()`.
  `ProcessingView._on_finish()` stays terminal-specific: it repaints the final frame with the
  run's verdict (`Failed: …`, `<title>: interrupted`, `<title>: done`) and prints the table
  only when it owns no `Live` (reachable only by constructing it directly on a dumb sink).
- **Tests**: `tests/unit/test_cli_events.py` (new) — `TestForConsole` (terminal → subclass,
  pipe → fallback), `TestSimpleLoggingEventHandler` (exact line lists for a run, stderr, a
  literal `[`, a skipped structured stream, a skipped percentage, the end-of-run table with
  its borders and status word, an interrupted run, a repo scan with no table, a run that
  planned nothing, stop-observing-after-exit) and `TestPrintSummary`.  One assertion added to
  the piped-scan test in `tests/unit/test_cli.py` (no empty table in a scan's output).
  Full unit suite: **1203 passed**.
- **Docs**: `doc/plans/cli-live-display.md` → new *Fix 8* section (+ Files/Risks updates);
  `AGENTS.md` → new *CLI observers* bullet; `.github/copilot-instructions.md` → the reindex
  paragraph; `systemPatterns.md` / `progress.md` → the factory + base-class pattern.
- **Verified** (2026-09-15): `just lint` → *0 errors, 0 warnings, 0 notes*; full unit suite
  **1203 passed**; `pytest tests/integration/test_workflow.py -m integration -n0` (the outside
  consumer — it runs `sb process masters`/`sb process auto` for real and scrapes stdout for
  ≥10 `Success` rows) → **13 passed in 650.84s**, so the fallback neither lost the table nor
  invented lines around it.
## Current work focus — Masters grouping, and the xdist SIGSEGV its tests triggered

**Implemented 2026-09-15**, both **not committed** (suggested split: the GUI grouping,
then the crash fix).

- **Masters grouping** in the Processing page's run tree (full map in the bullet further
  down): every master (calibration) run is nested under one lazily-created, collapsed
  `Masters` group, with `_scroll_to` replacing `QTreeWidget.scrollToItem` (Qt's
  `scrollToItem` expands collapsed ancestors — that would pop the group open on the
  first streamed log line).
- **The xdist-only SIGSEGV** the extra tests made likely is a *third* Qt-lifetime bug,
  written up in [`doc/plans/gui-widget-teardown.md`](../../doc/plans/gui-widget-teardown.md).
  Root cause: **nothing ever destroyed a test's widgets.** Qt delivers a
  `DeferredDelete` event only from a *running* event loop, and a pytest session never
  enters one — measured: `close() + deleteLater() + processEvents()` leaves the C++
  object alive, while an explicit `sendPostedEvents(None, DeferredDelete)` deletes it.
  So pytest-qt's `deleteLater()` for `qtbot.addWidget()` was a no-op: the widget stayed
  alive in C++ while its Python wrapper became garbage, and **whichever thread next ran
  a cyclic collection** destroyed that live widget tree there. Under xdist that was a
  `QThreadPool` thread running a later test's keyring job — hence
  `~QAbstractItemView` executing on a thread with no event dispatcher
  (`QBasicTimer::stop: Failed. Possibly trying to stop from a different thread` is its
  calling card, from the seven timer stops that destructor begins with) and a SIGSEGV
  in `QAbstractItemViewPrivate::disconnectAll()`; serially the same thing happened on
  the *main* thread, mid-`processEvents()` (`QTimerInfoList::activateTimers`).
  - Fix: `tests/conftest.py`'s teardown hook destroys them on the GUI thread
    (`_destroy_pending_gui_widgets`: deliver pending events → `sendPostedEvents(None,
    DeferredDelete)` → `processEvents()` → `gc.collect()`), after the pool drain and
    before fixture finalization.
  - The flush then exposed a *latent* bug it made deterministic: a job callback that
    PySide cannot tie to a receiver (`partial(self._on_sessions_loaded, path)`) is not
    auto-disconnected, so its report still ran against the deleted page and raised
    `RuntimeError: Internal C++ object ... already deleted` **from inside the event
    loop** — two teardown errors in `test_targets_page.py`, reproducibly. Fix: the new
    `workers.guard_callback` (same `shiboken6.isValid` idea as `Worker.run`), applied
    in `Page.start_job`, `TargetsPage._request_sessions` and the preview popup's two
    lambdas.
  - Evidence: with the flush disabled, `pytest tests/unit/test_gui.py -n0` segfaults
    (exit 139, 2 of 3 runs) and the new test fails; with it, 64 passed, and a
    page/window destruction log (the `/tmp` `qtdestroy` plugin) shows **58 destructions,
    all on `MainThread`** — previously *zero* widgets were destroyed during a run. The
    native stack (an `LD_PRELOAD` handler chained to faulthandler, plus
    `python3.12-dbg`) bottoms out in `QThreadPoolPrivate::stealAndRunRunnable` +
    `start_thread`, i.e. a pool thread.
  - Full suite **1228 passed / 1 skipped**; `just lint` 0 basedpyright errors.

## Current work focus — one event-driven CLI bar (Fix 7: `Processing.progress` removal)

**Implemented 2026-09-15**, recorded in `doc/plans/cli-live-display.md` (Fix 7).
The core no longer owns *any* Rich progress bar: every bar was the CLI's one live
widget or a second renderer fighting it (the Fix 5 bug class).

- **`Processing` has no `progress`**: the `progress=` parameter, `self.progress`,
  `_owns_progress` and `start()`/`stop()` are gone, as are the "Processing
  targets..." / "Processing: <target>" bars — `run_all_stages()` now enumerates its
  targets so the run boundaries can carry `index`.  `ProcessingLike.progress` is
  removed too; `test_processing.py::TestProcessingOwnsNoDisplay` asserts a real
  `Processing` has no `progress` attribute, so a GUI cannot pick up a stray display.
- **The run's size comes from the core, not a bar**: `doit.MyReporter.initialize()`
  publishes the new `EVENT_TASKS_PLANNED` (`tasks.planned`), and
  `EVENT_PROCESS_TARGET` / `EVENT_RUN_STARTED` now carry `index` (+ `total`).
- **`ProcessingView` owns the one bar**, aimed at a *phase*:
  `Starting...` (indeterminate) → `Indexing files` → `Planning` → `Processing tasks`
  → `Collecting inputs`.  `_set_bar()` resets only when the *phase* changes (one
  clock per phase), `_advance_bar()` never passes the total, and the run's task
  counts live in the view (`_tasks_done`/`_tasks_total`) because another phase may be
  holding the bar.
- **`EVENT_MERGE_PROGRESS` / `EVENT_MERGE_FINISHED`** (`merge.progress` /
  `merge.finished`, every 25 frames **and** always the last) replaced
  `rich.progress.track()` in **both** input collectors: `doit.merge_to()` and
  `tool/siril.py::link_or_copy_to_dir()` (the latter drew the identical bar on
  *every* Siril stage, and its "no symlinks here" hint is now a log line).  A
  collection *borrows* the bar mid-task and `merge.finished` hands it back to
  `tasks`, so the much longer tool run that follows keeps advancing.
- **Verified scope**: no `track(` call remains anywhere in `src/`, and the only
  `Progress` widgets left are the CLI's own (`commands/process.py`, `ui/cli.py`)
  plus one deliberate leftover — `publish/github.py::GitHubPublisher.publish()`
  opens a `Progress` on `starbash.console` and *is* called from the GUI's
  `publish_github_job` (same bug class, publish subsystem, out of Fix 7's scope;
  documented in the plan's *Risks / notes* with the fix sketch).
- **Tests**: `test_doit.py::TestMergeToReportsProgress` (a real 26-frame
  `merge_to()`), `test_tool.py::TestLinkOrCopyToDir` (the same contract for Siril's
  collector, including that a re-run meeting its own links still counts every
  frame), the merge-phase cases in `TestLiveStatusLine`, plus `test_emit_hooks`,
  `test_events`, `test_processing` and `test_run_tree_rich`.  Full suite
  **1224 passed / 1 skipped**, `just lint` 0 basedpyright errors.
- **Not committed** — the working tree holds the change for the developer to commit
  (suggested split: core/view change, then the two collector changes).

## Current work focus — Qt object lifetimes (the SIGSEGV and the CI RecursionError)

**Fixed 2026-09-15**, recorded in `doc/plans/qt-object-lifetimes.md`. Two
"unrelated" failures were one bug: a Python reference kept after Qt deleted the C++
object behind it (PySide then raises `Signal source has been deleted`, or — once the
freed memory is reused — segfaults).

- **Bug 1 (the SIGSEGV):** `run_async` jobs were never waited for. A thread dump in
  `pytest_runtest_teardown` shows `test_every_page_refreshes_without_error`'s identity
  job sitting in `keyring → get_all_keyring → entry_points()` **every single run**
  (`activeThreadCount() == 1` before teardown), so at interpreter shutdown Python
  dropped the `WorkerSignals` it emits from and the late emit hit freed memory.
  Fix: `tests/conftest.py` drains the global pool before `gui`-test fixture finalizers
  and at session end; `Worker.run` drops an outcome whose signals are gone
  (`shiboken6.isValid`) and `_report` is guarded; `Worker.setAutoDelete(False)` so Qt
  cannot delete the runnable under `_live_workers` (or a caller's `_stop_worker`).
  Measured: late-emit errors 2/2 per run before → **0/8** after, and the whole suite
  (xdist, as CI runs it) is 1206 passed / 0 late emits.
- **Bug 2 (the CI `RecursionError`):** `EventBusBridge`'s bus subscription is a plain
  Python reference, and `MainWindow.closeEvent` skips `_bus.close()` when a page
  refuses to leave — so a bridge outlives its window
  (`test_targets_page.py`'s navigation test leaks one; measured
  `subscriber_count() == 1` after it). Every later `publish` then called into the dead
  object, and because `publish`'s error path is `logger.exception` **and** an
  in-process tool's log forwarder republishes *every* record
  (`_ToolSourceFilter(None)` accepts all), the report published, failed again, and
  recursed. Fix: a `destroyed` → `close()` **lambda** (PySide does not deliver
  `destroyed` to a slot defined on the dying object — measured), a `shiboken6.isValid`
  self-heal in `_on_event`, and `events._report_subscriber_failure` refusing to log
  while a failure report is already in flight.
- Three new GUI/event regression tests, each verified to fail against the pre-fix code
  (e.g. the late emit raises `RuntimeError: Signal source has been deleted`; with
  `autoDelete(True)` a finished worker's wrapper is `isValid == False`).
- **Open (needs a decision, not implemented):** should `MainWindow.closeEvent` cancel
  and wait for in-flight jobs (`workers.shutdown(timeout)`)? Options and trade-offs
  are in the plan's *Open question*; the guards above already make the current
  behaviour safe, so this is purely about not silently losing work on quit.
- Debugging lesson worth keeping: a helper that swallowed `ImportError` hid a wrong
  import (`QApplication` from `QtCore`, not `QtWidgets`), which made a "validated"
  drain silently do nothing for several rounds. Check the probe, not just the result.

## Current work focus — stage roles (Phase 1 implemented)

`doc/plans/stage-roles.md` Phase 1 is **implemented** (2026-09-14): a stage may
declare an optional `role` and only the best-priority *available* implementation
runs, with `after` generalized to name a role. Both blocking questions were settled
2026-09-14 and are on record in the plan (§7.1, §7.2):

- **§7.1 — a *higher* `priority` wins** (the code's existing `reverse=True` rule), so
  no recipe renumbering and no risk to the conflicting-output resolver;
  `doc/toml/guide.md` ("lower runs earlier") was the doc that needed fixing, not the
  code.
- **§7.2 — `exclude_by_default` was dropped** rather than honoured: roles subsume it.
  The read in `ProcessedTarget._set_default_stages()` is gone (a stage the user has
  not touched is now enabled), the two GraXpert stages became ordinary role
  candidates (`priority = 300` vs rc-astro's `350`), and the flag was deleted from
  both recipes and from `doc/design/new-params.md`.

What landed, in one pass: `select_stages()` + `StageSelection`/`resolve()` in
`stages.py`, the `resolve=` hook on `sort_stages()`, the `select_stages()` call in
`Processing._job_to_tasks()` (before any task exists, so the losing branch never
materialises), role resolution in `_get_prior_tasks()` (providers become literals,
so the alternation-slicing hack is gone), and six palette `after` values switched
from `noise_exterminator` to the `denoise` role. New tests:
`tests/unit/test_stage_roles.py` (unit + recipe + pipeline fallback) and
`TestGetPriorTasksWithRoles` in `tests/unit/test_processing.py`.

Two facts verified while reviewing (written into the plan so they are not
re-derived): `sort_stages()` ties break by **earlier** catalog order (stable sort
over the default `0` — *not* later-wins), and the role name `denoise` **does**
collide with the GraXpert stage of the same name, which the union +
canonicalisation rule resolves to exactly one provider per branch.

Phase 2 (GUI grouping, per-session role resolution) and Phase 3 remain open; the
recipe edits live in the `starbash-recipes` submodule, which is committed separately
by the human.

## Current work focus — the Targets page drives `sb select`

The Targets page is now a second *editor* of the persistent session selection, so
its list, its single-target detail pane and `sb select` cannot disagree:

- **The list always shows every processed target** (it is a picker); the rows named
  by the selection are **pre-highlighted**, and with no target filter *every* row is
  highlighted, because "no filter" means every target is in effect — the same thing
  the CLI says. Reading and writing both go through the one `Selection` instance the
  GUI already shares with the CLI.
- **Qt's `ExtendedSelection` already implements the wanted click semantics**: a probe
  confirmed a plain click collapses the selection to the clicked row (even on an
  already-highlighted row) and Ctrl+click toggles, with `currentIndex()` already on
  the clicked row when `selectionChanged` fires. So no event filter or custom
  collapse logic — the page only adds the write-back (`_write_selection`) and, on a
  refresh, never rewrites a selection the user did not touch.
- **The explorer is shown only while exactly one row is highlighted**; otherwise the
  right column (`self._pane`, a `QStackedWidget` over the explorer and a hint label)
  explains itself and nothing stays loaded. A stack rather than hiding the pane keeps
  the splitter at its 22 % share instead of letting the list jump to the full width.
- Unsaved edits are settled *before* the highlight leaves a dirty target, and a
  cancelled prompt restores both the highlight and the in-memory edits (the pane
  skips reloading an already-loaded target).
- `services.preferred_target` became `services.selected_targets()` (the whole list),
  and the never-assigned `_desired_target` field is gone.
- Tests: 3 new GUI cases plus 2 rewritten ones in `tests/unit/test_targets_page.py`
  (37 pass) covering the pre-highlight, the empty-filter and unmatched-target hints,
  click/Ctrl+click toggling, and the dirty-target prompt. `just lint` clean
  (basedpyright 0 errors). Plan/design: `doc/plans/targets-selection-sync.md`,
  `doc/plans/gui.md` §5.5.
## Current work focus — up-to-date skips are not failures

A no-op re-run used to announce *"92 stage(s) run, 0 succeeded, 92 failed."* and
show every task as `skipped`, which reads like a broken run.  Both came from
treating doit's tri-state `success` as a boolean:

- **Caption** — `ui/qt/jobs.py::process_job` computed
  `failed = len(results) - succeeded`, so an up-to-date skip (`success=None`,
  published by `MyReporter.skip_uptodate` with `reason="Current"`) was counted as
  a failure.  The counting now lives in the dependency-free
  `run_state.ResultSummary` (`total` / `succeeded` / `up_to_date` / `failed` plus a
  `message` line), returned by `process_job` as `count` / `succeeded` /
  `up_to_date` / `failed` / `message` and rendered by the Processing page's
  caption.  The noun was corrected to `task(s)`: a `ProcessingResult` is one doit
  **task**, not a stage.
- **Status word** — `RunStatus.SKIPPED.label` is now `up-to-date`, via the new
  module-level `_LABELS` map (which also carries the pre-existing
  `PENDING → unused`), and `rich._STATUS_WORDS["skipped"]` is `Up-to-date` for the
  CLI's flat results table.  The **persisted value stays `"skipped"`**, so
  `run-log.toml` and older logs are untouched — only display words changed.  Stage
  rows roll up the same way (all tasks skipped → stage reads `up-to-date`), and
  `RunTree.success` already treated skips as non-failures.
- Deliberately unchanged: the `Ø` glyph and the amber styling for `SKIPPED` (still
  visually distinct from `✓`), and the `(Current)` reason the CLI live tree
  appends per task.  `skip_ignore` (reason `Ignored`) would now also read
  `up-to-date`, but starbash never calls `doit ignore`, so it is unreachable.
- Tests: `TestResultSummary` and the `SKIPPED` label case in
  `tests/unit/test_run_state.py`,
  `TestRunsToTable::test_up_to_date_skips_are_not_reported_as_failures`, and
  `test_processing_page_labels_up_to_date_tasks` in `test_gui.py`.  Also verified
  the real render path (`RunState.to_plain()` → `runs_to_table` → `Up-to-date`).
  `just lint` clean (basedpyright 0 errors); full suite **1090 passed**.

## Current work focus — auto re-index before each processing run

A run now scans the user's image folders first, so frames added since the last run
are not silently dropped by `search_session()`. It is a **user preference, on by
default**, and there is a GUI checkbox for it.

- **Core**: `src/starbash/preferences.py` (new) holds `DEFAULT_AUTO_REINDEX = True`
  and `auto_reindex_enabled(repo)` (reads `reindex.auto`), mirroring
  `analytics.py`'s canonical-defaults pattern. `Processing.reindex_if_needed()`
  (`processing.py`) consults it and calls `Starbash.reindex_repos()`, returning
  whether a pass ran. Documented as a commented `[reindex] auto = true` line in
  `templates/userconfig.toml`.
- **Call sites**: `sb process auto` (the non-`session_num` branch) and
  `sb process masters` call it inside the `with view, Processing(...)` block;
  the GUI calls it at the top of `jobs.process_job` (before
  `token.raise_if_cancelled()` / `run_all_stages()`).
- **Progress**: no new events — the pass reuses `reindex.progress` /
  `reindex.finished`, already published by `Starbash.reindex_repos()`, and every
  front end now renders them: `ProcessingView._on_event` (caption
  `Indexing <repo> — done/total`), `ProcessingPage._on_event` (bar range/value +
  caption) and the GUI's Repositories page. `ProcessingPage` also resets the bar to
  indeterminate on `EVENT_PROCESS_TARGET`, so a finished scan cannot leave a full
  bar looking done.
- **The core draws nothing** (follow-up to the tool migration in
  `doc/plans/cli-live-display.md`): `reindex_repos()` / `reindex_repo()` lost their
  `rich.progress.track()` bars *and* the `show_progress` flag that had been added to
  silence them, because a bar drawn from the core renders on Rich's *global* console
  while the CLI's live view runs on the separate `starbash.console` — and the GUI's
  re-index/add jobs were opening a display from a worker thread onto the process's
  stdout even though the page already drew the scan. `sb repo reindex` and
  `sb repo add` needed a replacement observer, so `ui/cli.py::ReindexView` (new) is
  it: a `Live` + a per-repo bar, plain `Indexed N file(s) in <repo>` lines when the
  sink cannot animate, and no `Live` at all on a pipe.
- **GUI settings**: `SettingsPage` gained `_auto_reindex` ("Scan my image folders
  before each processing run", form row *Indexing*), read in `refresh()` through
  `auto_reindex_enabled()` and written on save as `reindex.auto`.
- **Tests**: `tests/unit/test_preferences.py` (new), `TestAutoReindex` /
  `TestAutoReindexIntegration` in `test_processing.py` (default-on, opt-out,
  explicit-true; the integration pair drives a real `Starbash` so the preference is
  read from the real user config), `tests/unit/test_reindex_view.py` (new, 7 tests
  for the CLI view), the core's event-reporting test plus
  `test_the_core_draws_no_progress_bar` in `test_app.py` (replaces two tests that
  mocked `track()`), the reindex branches in `test_run_tree_rich.py` and the
  settings/processing-page cases in `test_gui.py`.

## Current work focus — Targets explorer + structured session masters

Implemented the Targets-screen redesign and the structured `sessions.masters`
schema (see `doc/plans/gui.md` §5.5 and the new `doc/plans/session-masters.md`;
the sequenced build order is recorded in `doc/plans/targets-redesign.md`).

- **Targets page** (`ui/qt/pages/targets.py`): the left list is now a **narrow
  picker** (`TARGET_COLUMNS` = Target only, `_TARGET_LIST_SHARE = 0.22`); the
  right pane is one tree with two top-level groups — `Stages` (unchanged
  checkable stage/param tree) and `Sessions` (only when `sessions.toml` records
  masters). Under each session are `Bias`/`Dark`/`Flat` rows showing the chosen
  master + `auto`/`user`. The detail pane is a `QStackedWidget` swapping the
  existing option editor with a new `MasterPicker`
  (`ui/qt/widgets/master_picker.py`): a radio list of scored candidates with
  score + reason, and *Reset to automatic*.
- **Async sessions load**: `services.load_session_options` parses the (possibly
  multi-MB) `sessions.toml` through `workers.run_async` with a `BusyIndicator`
  over the tree; a stale result is dropped by comparing the path. Stage-only
  edits never rewrite `sessions.toml`.
- **New `sessions.masters` schema**: `[sessions.masters.<type>]` now carries
  `selected` + `selected_by` (`"auto"`/`"user"`) and one `[[…candidates]]`
  table per scored candidate with structured evidence (`gain_match`,
  `temp_delta_c`, `time_delta_days`, `in_future`, `instrument_match`,
  `camera_match`, `dimensions_match`, `filter_match`, `reasons`). Legacy
  `used`/`excluded` string arrays still load — tomlkit drops inline-array
  comments, so legacy entries carry no `reasons`.
- **Processing honours a user pick**: `_resolve_input_master()` uses
  `_pick_master()` — a prior `selected_by = "user"` entry wins as long as that
  master is still a candidate, otherwise the top scorer — and writes the new
  shape via `_master_selection_table()`.
- Model accessors: `ProcessedTarget.session_options()` /
  `save_master_selections()` (+ `_parse_master_entry`), re-exported by
  `ui/qt/services.py`. `score.py`'s `ScoredCandidate` gained `reasons`/`details`
  and `to_toml_table()`.
- **Polish (2026-09-14)** — four follow-ups on the explorer:
  - **Sessions are listed above Stages** (`_rebuild_tree` calls
    `_build_sessions_group()` before building the stage group), because picking a
    session's calibration master is the more common edit and the stage list is long.
  - **The one-column target picker stretches** (`setStretchLastSection(True)` on
    `_table`): `make_table` deliberately leaves the last section fixed (right for the
    multi-column tables, where stretching gave a bare number a huge empty cell),
    which left the 180px Target column stranded ~40px short of the scrollbar.
  - **Master names are links** — in the tree (the *value* cell of a `Bias`/`Dark`
    row; the type cell is not a file) and in every `MasterPicker` row (its Master
    cell): hovering previews the frame, activating opens it. A plain click in the
    picker still only *chooses*, so the picker's `LinkDecorator` uses
    `open_on="activated"`. `services.master_url(sb, path)` resolves a recorded
    repo-relative master via `repo.resolve_path()` and returns `None` when there is
    no local master repo or no real file — so a dead name is never underlined.
    `widgets/file_links.set_link()` now takes a `QTableWidgetItem` too; the two Qt
    item APIs differ (a table item *is* one cell and takes no column argument).
  - **Hover previews are user-resizable**: `_PreviewGrip` is a small painted handle
    at the card's bottom-right that resizes the popup by hand — `QSizeGrip`
    asks the platform to run a resize loop, which a frameless `Qt.Tool` window does
    not reliably get (and the offscreen test platform has no equivalent for). It sits
    in its **own right-aligned layout row** below the body, not overlaid on the body's
    corner: an overlay swallowed the corner of the text view's own scrollbar (its
    down-arrow became undraggable), so `_CHROME_H` budgets the extra row instead.
    The dragged size is remembered process-wide (`_PreviewPopup._user_size`), clamped to
    `MIN_WIDTH`/`MIN_HEIGHT` and to the screen, re-placed beside the hovered cell,
    and a previewed image is re-scaled to the new size (debounced by
    `RESCALE_DELAY_MS`, re-rendered from the kept source `QImage` so growing stays
    sharp). Hugging is skipped once the user owns the size, so the next hover of a
    small thumbnail cannot shrink their window back down. Because `_user_size` is
    class-level state, `test_hover_preview.py` has an autouse fixture that resets it.
    The floor is really `_PreviewPopup._minimum_size()` — `max(MIN_WIDTH/MIN_HEIGHT,
    the window's own minimum)`. A top-level `QLayout` pins the window's `minimumSize`
    to its contents, and the text view's share of that is font/platform dependent:
    ~88px of height on Linux, ~194px on macOS, where Qt then refuses to shrink the
    popup to `MIN_HEIGHT`. Clamping only to the constants therefore recorded a
    `_user_size` the window could not take (fixed 2026-09-15, after the macOS CI run
    failed `test_dragging_the_grip_inwards_stops_at_the_minimums` with 280x194 vs
    280x180); the test now reads the floor back from the popup, with a second test
    covering the above-`MIN_HEIGHT` case.
  - **Hover previews are movable**: the title row is a `_TitleBar` widget
    (`SizeAllCursor`, own-row QSS-transparent widget) that translates a left-drag
    into `window().move()` — the same hand-rolled approach as the grip, because a
    frameless `Qt.Tool` window gets no window-manager titlebar and
    `QWindow.startSystemMove()` is not dependable for it. The title *label* is
    `WA_TransparentForMouseEvents` so dragging the file name itself moves the popup
    (not just the blank space beside it); the ✕ button is a sibling child and keeps
    working. Resizing no longer re-anchors to the hovered cell (that would teleport
    a popup the user moved) — `_on_grip_dragged` calls `_keep_on_screen()`, which
    only nudges the window back if growth pushed an edge off the screen; `_anchor`
    is gone.
- **Latent test bug exposed and fixed**: `test_targets_page.py`
  ::`test_master_picker_is_exclusive_and_resettable` constructed a `QWidget` with no
  `QApplication` alive and only passed when the xdist worker happened to run another
  Qt test first (Qt *aborts* — not raises — in that case). It now takes `qapp`;
  adding tests shifted xdist's load balancing and made the crash reproducible.
- Tests: `tests/unit/test_processed_target_sessions.py`,
  `tests/unit/test_processing_masters.py`, extended `test_score.py` and
  `test_targets_page.py`. Full suite **1049 passed**; `just lint` clean
  (0 basedpyright errors).

## Previous focus — GUI "Publish to GitHub"

Implemented [`doc/plans/gui-github-publish.md`](../../doc/plans/gui-github-publish.md):
the GUI Publish page can now publish for real, including the first-run sign-in +
App-install steps, sharing the publish sequence with the CLI.

- **Core extraction**: `src/starbash/publish/github_publish.py` (new) holds the
  whole sign-in → App-check → create-repo → upload-blobs → commit → configure-Pages
  sequence with **no** Rich/terminal/Qt imports.  Callers pass a `StepReporter`
  (`(description, completed, total)`) and do their own user-facing work.  It owns
  `CLIENT_ID` / `APP_SLUG` / `APP_INSTALLATION_URL` / `PUBLISH_REPOSITORY`
  (`"starbash-public"`) / `UPLOAD_PATH_BLACKLIST` / `MAX_BLOB_UPLOADS`,
  `PublishResult`, `GitHubAppNotInstalledError`, and `collect_site_files`,
  `upload_blobs`, `publish_site`, `finish_device_login`, `credential_service`,
  `refresh_if_needed`, `save_credential`, `pages_url_for`.
  `publish_site(..., require_app=True)` exists for front ends that already guided
  the user past installation (the GUI passes `False`); `finish_device_login(...,
  sleeper=...)` lets a cancellable front end interrupt GitHub's poll interval.
- **CLI**: `commands/publish.py`'s `_publish_github` is now only prompts + Rich
  rendering (its `_upload_blobs` and the rest of the sequence were deleted) —
  behaviour unchanged, existing command tests untouched and green.
- **GUI jobs** (`ui/qt/jobs.py`): `github_sign_in_job` (device flow; reports
  `{"user_code","verification_uri"}` early so the dialog can show/open it while
  polling, and **deliberately does not save** the credential — the App must be
  installed first), `github_install_job` (loads/checks the credential off the GUI
  thread and only then `save_credential`s — saving it **with** the account name
  GitHub reports; returns `{"signed_in","installed","login"}`, with
  `signed_in=False` meaning "start over"), `github_identity_job` (reads the stored
  credential off the GUI thread and returns `{"signed_in","login"}` for the page —
  no network call), `publish_github_job` (full publish for the account GitHub
  reports, so **no username argument**; reports `(description, completed, total)`
  tuples that drive the page's progress bar, and records the account name beside
  the token), and `_cancel_aware_sleeper`.  The dead `publish_job` (local
  generation, no upload) is gone.
- **Key decision — `needs_sign_in` / `needs_install` are *returned*, not raised.**
  Neither is an error; the page opens the setup dialog and then simply calls
  `_on_publish()` again (the credential is re-read from the store, so no state is
  threaded back).
- **Key decision — the GitHub account is never typed.**  `GitHubCredential` gained
  a persisted `login` (empty for credentials saved before it existed);
  `credential_service`'s rotate callback and `refresh_if_needed`'s **return value**
  both carry it across a token refresh, and `refresh_if_needed` now returns the
  credential in effect so a caller cannot save the expired one back over a rotated
  token.
- **Dialog** (`ui/qt/widgets/github_login.py`, new): `GitHubSetupDialog` runs
  `STEP_WELCOME → STEP_WAITING → STEP_INSTALL → STEP_DONE` off one widget set
  (`_show_step` + `_on_primary`/`_on_secondary` dispatch); its contract is just
  `ready`.  `run_github_setup(parent, *, start_at_install=False)` is the entry
  point (`start_at_install=True` skips straight to installing when a token exists
  but the App does not).  Closing the window is treated as Cancel — both call
  `_stop_worker()` and set `_closed`, and every callback early-returns on
  `_closed`, so a late result can never touch a dead window.  `theme.py` gained a
  `DeviceCode` rule (large monospace) because the code must be transcribed
  accurately.
- **Dialog re-fit after a step reveals text** (`_refit()`, called at the end of
  `_show_step`; `_set_status()` routes every `_status.setText(...)` through it).
  The dialog is shown once, on `STEP_WELCOME`, so each later step has to grow the
  window itself — without this the device code and the install step's
  instructions were **vertically clipped**.  `adjustSize()` alone does not fix it
  (a word-wrapped `QLabel.sizeHint()` under-reports height at the layout's real
  width), and `heightForWidth()` is accurate but **sticky**: `QLabel` clamps its
  hints by the minimum height it was last given, so a window that grew would never
  shrink again.  `_refit()` therefore zeroes the wrapped labels' minimums, lets
  the layout settle (`_box.activate()`), re-measures each with
  `heightForWidth(label.width())` (`max(0, …)` — an empty label reports `-1`),
  settles again, and only then calls `adjustSize()`.
  `test_github_setup_dialog.py::test_a_revealed_step_is_not_clipped` renders each
  step and asserts the text fits; it calls `theme.apply_theme(qapp)` first, because
  the metrics that expose the bug come from the themed fonts (the default test
  platform styles the `DeviceCode` label with a smaller font, hiding it).
- **Page** (`ui/qt/pages/publish.py`): a `#Primary` *Publish to GitHub* button, a
  compact `Spinner`, *Open in browser*, and a progress bar hidden unless a publish
  is in flight.  Buttons lock during the job and success emits the page's `status`
  signal.  Two follow-up behaviours (user request, same session):
  - the GitHub account box is **read-only** — `refresh()` runs
    `github_identity_job` and shows the account recorded with the credential
    (`"Signed in to GitHub"` placeholder when a pre-`login` credential has no
    name), and the publish job uses the account GitHub reports instead;
  - *Open in browser* **starts disabled** and is enabled only after a publish
    returns a `pages_url` (`https://<owner>.github.io/starbash-public/`), which it
    opens; a later failed publish keeps the link to the live site.  The
    *Generate report site* and *Open site folder* buttons were removed (generating
    without publishing was a dead end) — so `publish_job` is gone too.
- **Tests**: `tests/unit/test_github_publish.py` (core sequence, plus the
  credential round trip / TOML fallback / pre-`login` back-compat and the
  login-preserving rotation), `tests/unit/test_github_jobs.py` (new: the identity
  readback and the account recorded by install/publish, with
  `credential_service`/`GitHubCredentialStore` stubbed),
  `tests/unit/test_github_setup_dialog.py` (every step transition, the two
  "return to an earlier step" paths, cancel/close cancelling the worker *and*
  ignoring a late result, `run_github_setup`'s return value, and
  `test_a_revealed_step_is_not_clipped` — it applies the real theme, renders each
  step and asserts no wrapped text is cut off, which is what pins `_refit()`) and
  `tests/unit/test_publish_page.py` (publish flow, the read-only account field,
  *Open in browser* gating/URL, the dialog handoff + re-run for both `needs_*`
  states, failure path).  Both GUI modules monkeypatch `run_async` with a
  **recorder** (`_RecordedJob` + `_FakeWorker`) that also captures the job
  callable, so tests can run the real job with a stub `report` and assert what was
  passed in — no network, callbacks invoked directly on the GUI thread.
  `test_publish_page.py` stubs `Page.show_error` autouse so a regression cannot
  raise a **modal dialog and hang a headless run**.
  Full suite: **1028 passed**; `just lint` clean.

## Current work focus — Repositories page uses the CLI's repo list

GUI fix for `ui/qt/pages/repositories.py` + `ui/qt/services.py`:

- **`load_repos(sb, *, show_all=False)`** now defaults to
  `RepoManager.regular_repos` — the exact set `sb repo list` shows (it goes
  through the same property, so the two cannot drift) — and returns
  `RepoManager.repos` (the CLI's verbose listing, incl. preferences / recipe /
  `pkg://`) only when `show_all=True`.
- **Page**: a *Show all repositories* `QCheckBox` toggles `refresh()` between the
  two; it is the only other caller of `load_repos`.
- **Add-kind limits**: `_update_add_kinds()` disables the *Master frames* /
  *Processed output* entries in the add-kind combo once
  `repo_manager.get_repo_by_kind(kind)` finds one — the same test
  `sb repo add` uses to refuse a second (`commands/repo.py`), so the GUI no longer
  offers an action the CLI rejects.  Raw input (`value=None`) is never disabled.
  If the *current* choice just became unselectable it falls back to an enabled
  entry, otherwise *Add folder…* would add a kind we already have.
  Qt detail: `QComboBox` entries are disabled via the model's
  `QStandardItemModel.item(i).setEnabled(False)` — hence the `_kind_enabled(i)`
  helper reading `item.isEnabled()` back.
- **Remove selected** starts disabled, follows `selectionChanged`, and is
  re-evaluated in `_busy()` via a `_busy_state` flag (the old code blanket-enabled
  it during a job) — so it is enabled only with a selection *and* no running job.
- **Managed repos are never removable**: the button is additionally gated on the
  new `Starbash.is_repo_removable(url)`, which answers "is there a `[[repo-ref]]`
  for this URL in the user config?" — the exact condition `remove_repo_ref()`
  needs, sharing a `_find_user_repo_ref()` helper with it so the two cannot
  drift.  The bundled `starbash-recipes` checkout is `kind = "std-recipe"`, which
  `regular_repos` does *not* filter out, so it really does appear in the default
  view (observed as row 0 in tests) — previously the button was enabled and the
  click produced an error toast (plus, before this change, deleted that repo's
  indexed DB rows and then refused).  A `toolTip` explains the disabled state.
  Also gated: preferences and `pkg://defaults`, which only appear with *Show all*.
- **`remove_repo_ref` validates before touching the DB** (it now resolves the
  ref first, then calls `db.remove_repo`), so refusing to remove a repo no longer
  silently drops its indexed rows/sessions.  Unreachable from the GUI (the
  page's `_on_remove` re-checks and emits a status instead) but it also fixes
  `sb repo remove <managed-url>`, which used to delete rows and then raise.
- **Tests**: `tests/unit/test_repositories_page.py` (9 tests, `gui`-marked)
  covering the default-vs-show-all listing, the master/processed kind limits
  (including the fallback), the remove-button rules for both removable and
  managed repos, and that a refused removal leaves the user config alone; the
  two new core tests live in `tests/unit/test_app.py::TestRemoveRepoRef`.  All
  three new behaviours were mutation-checked (reverting the page logic fails them
  cleanly).  Note the "refused removal" test stubs `show_error`, because a
  regression there would otherwise raise a **modal dialog and hang a headless
  run** — the first mutation run did exactly that.
- **Test hygiene**: `test_unavailable_when_configured_path_is_gone` used to
  hardcode `/usr/bin/starnet2` as its "gone" path, which failed on any host where
  StarNet is actually installed (this dev container installs it via
  `just install-starnet`).  It now uses a `tmp_path`-derived path that is
  guaranteed absent, so it no longer depends on the host's package state — the
  full suite is **981 passed** and `just lint` is clean (0 errors/warnings).

## Current work focus — missing-tool warnings (severity + ignore)

Implemented [`doc/plans/tool-warnings.md`](../../doc/plans/tool-warnings.md): one
core model for "a tool Starbash needs is missing", rendered by both front ends.

- **Core** (`tool/base.py`): `ToolSeverity` (`IntEnum`, so the ordering *is* the
  rule: `OPTIONAL < RECOMMENDED < REQUIRED`, and `severity < REQUIRED` means "may be
  dismissed") plus a frozen `ToolStatus` (`name`, `key`, `severity`, `available`,
  `install_url`, `ignored`, `detail`) with derived `needs_attention`,
  `can_be_ignored` and `summary` (first line of `detail`).  `plain_message()` turns
  Rich `[link=URL]x[/link]` into `x (URL)` so Qt labels/tooltips/log files never
  show markup.
- **Severities**: Siril `REQUIRED`; Starnet `RECOMMENDED`; GraXpert / rc-astro /
  Python `OPTIONAL` — the base default (`Tool.severity = ToolSeverity.OPTIONAL`), so
  a newly added tool is quiet until someone proves otherwise.
- **Registry** (`tool/__init__.py`): `tool_statuses()`, `tool_status(key)`,
  `missing_tool_statuses(*, include_ignored=False)` (missing ones, most important
  first), and `set_tool_ignored(key)` which only touches the in-memory preferences —
  persisting is the caller's job, keeping the tool module free of repo knowledge.
  `init_tools()` calls `Tool.preflight()`, which logs at a severity-matched level
  (error / warning / debug), so the CLI needed **no** front-end-specific code.
- **GUI**: `ui/qt/widgets/tool_warning.py` (`ToolWarningBar` + `ToolWarningPanel`)
  sits above the nav rail and page stack, so a warning is visible from any page and
  the panel hides itself when nothing needs attention.  One bar per missing tool:
  severity badge, `<Name> was not found`, the one-line `summary`, *How to install*
  (only when the tool has an `install_url`) and *Ignore* (only when
  `can_be_ignored`); the long explanation stays as the tooltip.  Severity colours
  come from a `severity` **dynamic property** set on *both* the frame and the badge,
  because a Qt selector cannot read the parent's property.
- **Ignore preference**: `Tool.is_ignored` reads the tool's own `[tool]` section of
  the user config, i.e. `tool.<key>.ignored` — the same key
  `MainWindow._on_ignore_tool` writes via `user_repo.set` + `write_config()`, which
  is why ignoring in the GUI also silences the CLI startup warning.  A failed write
  keeps the bar and reports it to the status bar instead of pretending it stuck.
  `src/starbash/templates/userconfig.toml` documents the key.
- **Detection must be honest**: `StarnetTool.is_available` validates the configured
  `starnet_exe` via `_starnet_exe_usable()` (bare name → `shutil.which`, explicit path
  → must still exist).  Before, *any* non-empty value counted as configured, and
  because Starbash itself writes that value when it finds `starnet2` on the PATH,
  deleting the binary left a dangling setting that reported StarNet as available —
  so neither front end warned.  A stale path now reports missing, and
  `missing_message()` names the dead path rather than telling the user to configure
  something Siril already has configured.  Starbash still never rewrites a non-blank
  `starnet_exe` (only a blank one is auto-filled).
- **Tests**: `tests/unit/test_tool_warning.py` (new), `TestToolSeverity` in
  `tests/unit/test_tool.py`, and a GUI end-to-end ignore test in
  `tests/unit/test_gui.py` that reads the written config back with `tomllib`.
  Those three files = 187 tests; full suite **970 passed**; `just lint` clean.

## Current work focus — one live CLI widget (event-driven)

Implementing [`doc/plans/cli-live-display.md`](../../doc/plans/cli-live-display.md):
the CLI now has **exactly one** live display, driven only by `starbash.events`.

- **Root cause of the "torn CLI output"** — Rich 15 *stacks* live displays per
  console (`Console.set_live` returns `len(stack) == 1`); a nested `Live.refresh()`
  calls `console._live_stack[0].refresh()`.  So the per-tool `ToolLiveDisplay`
  (`Tool.run` wrapped `Tool._run` in its own 8 Hz `Live`) force-repainted the
  `ProcessingView` tree 8×/s and then printed its block *over* the live region.
  rc-astro did the same thing with its own `Progress(...)` context manager.
- **Removed** — `ToolLiveDisplay`, `Tool._active_display`,
  `Tool.manages_own_progress`, the `Live`/`nullcontext` block in `Tool.run` and
  the rc-astro `Progress` bar.  Tools only publish events now (unchanged
  payloads: `tool.started/finished/output/progress`).
- **`ProcessingView`** (`commands/process.py`) is the single owner of the console
  `Live` and *is* the live renderable (`Live(self)`), so Rich's own 4 Hz refresh
  thread paints current state: no per-event `update()` storm (Siril emits
  thousands of lines) and nothing can outpace the terminal.  `__rich__` =
  `_render()`.
- **`_render()` returns a `rich.layout.Layout`, not a `Group`** (fix 2, see
  below).  A pinned header (title + spinner/caption/tool/percentage + progress
  bars) is sized to its content; the body below it is **two panes** (fix 3): the
  tool log on the left, the run tree on the right.
- **Status line** — `Spinner("arc", text=Text)` + a literal `Text` caption built
  from `process.target` / `run.started` / `task.started` / `task.finished` /
  `tool.started` / `tool.progress` / `tool.finished`, e.g.
  `stack: Stack lights · Siril 45%`.  `finish()` leaves `✓ <title>: done` on
  screen — or `✗ Failed: <task>` if anything failed (the final frame must not
  claim success).
- **`tool_label(cmd)`** (`commands/process.py`) shortens a command line
  (`flatpak run --command=siril-cli org.siril.Siril …` → `Siril`).
- **Hardening** — `rich.run_tree_to_rich` renders log lines as literal `Text`
  (a `[` in tool output used to raise `MarkupError` *inside the refresh thread*,
  which froze the display); task `reason` is `rich.markup.escape`d.
- **Verified** — PTY repro (`/tmp/sb_live_repro2.py` + a mini terminal emulator)
  shows one clean pane: tree, spinner/status, tool tail, progress bars, no
  orphans.  **Gotcha:** read `script`/pty recordings with `newline=""` — Python's
  universal newlines rewrite `\r` as `\n` and make a *correct* live display look
  like it drifts; this sandbox's pty layer also mangles termios.
- Tests: `tests/unit/test_run_tree_rich.py` (`TestToolLabel`,
  `TestLiveStatusLine`, bracketed-log-line case).  Docs updated: `AGENTS.md`,
  `events.py`, `.github/copilot-instructions.md`, `doc/design.md` (superseded
  notes).
- **Fix 2 — three red `...` everywhere and no spinner.**  Rich crops a live
  renderable that is too tall by keeping the *top* and appending its red
  `live.ellipsis` marker, so the old single `Group(header, *trees, status,
  progress)` did exactly the wrong thing: a real auto run has hundreds of
  `Master ...` runs (**212 lines median / 327 max** vs a 24-50 row terminal,
  **93-97% of frames overflowed**), so the status/tail/bars — being *last* —
  were cropped away and `...` was left.  The dots were not a progress indicator.
  **Fix:** split the screen with `rich.layout.Layout` — a top region sized to the
  status, run trees below — and make the tree region a small `_RunTail`
  renderable that takes the **newest runs** until the region is full and prints
  `… N earlier runs` (Rich's crop keeps the top, which is the wrong end for a
  live log).  Unfitted runs are never rendered, so cost tracks the screen, not
  the run count.  (Its always-show-the-bottom anchoring is superseded by fix 3's
  `_RunWindow`, which still measures newest-first but then scrolls *to the task
  that is building*.)
- **Verified after fix 2** (real PTY 100x30, 75 s of `sb process auto`): the
  live shape is *constant* (~29-30 rows) across all 266 frames instead of growing
  212→327; Rich's `...` count fell **245 → 13**, and all 13 are real text
  (`Starting...`, `Processing tasks...`, `Linking input files...`, a Siril log
  line).  Spinner + percentage + log tail + both progress bars are present in
  every sampled frame.  Regression tests: `TestLiveLayout` (renders at a given
  size and asserts the row count never exceeds it, no `...`, status on row 1
  with 200 runs).
- **`just lint` is the real gate** — `ruff check` + `ruff format` + `basedpyright`
  (Pylance's engine).  It caught what a ruff-only pass missed: Rich's
  `ConsoleOptions.update_height(None)` is typed `int` (`reset_height()` is the
  correct unbounded-height API), and `_RunTail` must take
  `Sequence[RenderableType]` because `list[Tree]` is invariant.  It also surfaced
  a pre-existing error in `tests/unit/test_processing.py` (a test assigning
  `remove_processing_dir` on a fake; the method exists nowhere in `src` any more),
  fixed by declaring it on `FakePt` as a raising tripwire.  **Rule added** to
  `.clinerules/collaboration.md`, with a pointer in `AGENTS.md` → *Conventions*:
  after editing code, run `just lint` and confirm it is clean (it rewrites files,
  so re-run the tests afterwards).
- **Fix 3 — the tool log came back, and the tree scrolls to the running task.**
  Fix 2 over-corrected: the only tool output was a **3-line tail**, and the tree
  pane always showed the **newest rows**.  A stack runs for minutes, so the line
  a user needs is rarely among the last three; and while a stage builds, the run
  being worked on is the newest one, so bottom-anchoring showed its *last* rows
  (the stages still to come) and could push the `⏳` row off the pane.  Now the
  body is two panes:
  - **Log (left)** — `_LogTail` over `deque(maxlen=LOG_LINES)` (500), fed by every
    non-structured `tool.output`.  It is the *run's* log, so it is **not** cleared
    per tool; `tool.started` appends a dim `──── <tool> ────` rule instead.
    `rich.log_line_to_text()` builds a literal `Text` (never markup — a `[` in
    output must not raise `MarkupError` in the refresh thread), stderr red, plain
    stdout untouched, and any `tool.base.BAD_WORDS` hit also red (Siril does not
    mark its own errors; compare case-insensitively — the list holds `"No image"`).
    Tail-anchored, `… N earlier lines`.
  - **Tree (right)** — `_RunWindow` (replaced `_RunTail`) measures runs from the
    newest backwards (still screen-proportional cost), then windows the text so
    the `RunStatus.RUNNING.glyph` (`⏳`) row of the run that is building is visible,
    keeping `ANCHOR_CONTEXT = 2` rows of context above it; `_building_index()`
    finds that run in the plain snapshots (no rendering).  If the run fits it is
    shown from its root so the **target name stays on screen**; with nothing
    building it falls back to the newest run.  Notes: `… N earlier runs` (above)
    and `… N more runs` (below).  *(Superseded by fix 4: with nothing running the
    pane now anchors on the newest run's **last finished** row, and the
    degenerate case (one run taller than its pane) shows that anchored region
    rather than the root — the header above still names the target.)*
  - **Sizing** — `< MIN_SIDE_BY_SIDE_WIDTH` (100 cols) **stacks** the panes rather
    than dropping one; `< MIN_SPLIT_HEIGHT` (6 rows) renders the header alone.
  - Tests (`tests/unit/test_run_tree_rich.py`): scrollback keeps 500 / drops the
    oldest, stderr + bad-word red, a new tool keeps history and adds a separator,
    wide layout is genuinely side by side (log separator and tree row share a
    row), narrow still shows both, tall run shows `⏳ Stack lights` +
    `… 3 earlier runs`.  Also verified under a real PTY `Live` (120x30): no
    traceback/Rich error, final frame `✓ Auto-processing: done`.
- **PTY-debugging kit** (kept in `/tmp`, per-session): `/tmp/pty_win.py` runs a
  command under a pty with a real `TIOCSWINSZ` size (a 0x0 pty makes Rich fall
  back to 80x24 and hides overflow), `/tmp/vt.py` is a mini VT screen emulator,
  `/tmp/check_cap.py` counts `...`/frames and prints the screen at several replay
  points.  Measure the live shape per frame by counting consecutive
  `\x1b[1A\x1b[2K` runs (Rich emits one per rendered line).
- **Fix 4 — the tree never saw a *running* task, so the pane looked frozen.**
  `EVENT_STAGE_RESULT` snapshots are published when a task has *just finished*
  (`Processing.add_result` → `pt.record_result()` then `run_tree().to_plain()`),
  and `MyReporter.execute_task()` published `task.started` **without** a snapshot
  — so the in-memory `RUNNING` placeholder from `pt.task_started()` never left the
  process.  Consequences: `run_tree_to_rich` drew no `⏳` at all,
  `_building_index()` always returned `None` (fix 3's anchoring was dead code), and
  the no-anchor fallback showed the newest run from its **top** — i.e. the frozen
  pane the user reported ("fills the screen once and never changes again").
  **Fix:** `task.started` now carries `"run"`, the fresh `run_tree().to_plain()`
  taken right after `pt.task_started(task)` — the only snapshot that can contain a
  running node.  On the view side `_building_index()` scans **newest-first** (a run
  whose last task was never recorded can hold a stale running node), the window
  follows that run (else the newest), and `_RunWindow._anchor_row()` anchors on the
  **last finished** row (`✓`/`Ø`/`✗`; never `⊘` — excluded stages are not progress
  and usually sit below the work) when nothing is running, so the gap between two
  tasks no longer snaps the pane back to the run's top.  Tests:
  `test_emit_hooks.py::test_my_reporter_publishes_the_started_task_as_running` and
  `test_run_tree_rich.py::TestLiveLayout::test_the_reporter_starting_a_task_lands_the_running_task_in_the_tree`
  (both verified to **fail** with the `run` key removed),
  `…::test_tree_pane_stays_where_progress_was_between_tasks`,
  `…::test_the_newest_running_run_wins_over_a_stale_one`; the degenerate-region
  test now asserts the anchored row instead of the root.  Live PTY (120x30, driven
  by the real reporter + the snapshot `add_result` publishes): `⏳` rows **0 → 28**,
  no traceback, final screen all `✓`.  Harness kept for re-runs:
  `/tmp/sb_e2e_child.py` (feeds the real producer path) + `/tmp/sb_e2e_pty.py`
  (runs it under a PTY and counts `⏳`/`✓`/tracebacks).

- **Fix 6 — a built-in tool's own lines never reached the bus (the last tear).**
  `tool_run_streaming` streams an *external* tool, but a tool implemented in Python
  inside Starbash logs through `logging` instead: GraXpert's built-in `api_run` uses the
  module-level helpers (so its records land on the **root logger**), which meant the GUI
  saw nothing and the root `RichHandler` drew the lines *beside* the live display.  Fix:
  **`tool_run_in_process(cmd, *, source, cwd, log_out)`** in `tool/base.py` — publishes
  `tool.started/finished`, installs a `_ToolLogForwarder` (root-logger handler) that
  republishes each record as `tool.output` (plus `tool.progress` for a percentage, and
  `stderr` for `WARNING`+), and silences the *existing* root handlers with an inverted
  `_ToolSourceFilter`.  `source` is the tool package's directory (GraXpert matching on
  `record.pathname` — a logger name is useless, the record is on root); **`source=None`
  means "every record in this window"**, which is what a `tool.name = "python"` stage
  needs because its output comes from *Starbash's own* modules (the sandbox's `print`
  goes through `MyPrinter` → `logger.info` in `starbash.tool.context`, and Siril commands
  log from `sim_siril`).  Hooking `print`/`MyPrinter` was therefore rejected: it would see
  only prints (missing the injected `logger` and `sim_siril`), fire on the TOML-expression
  path (`expand_context_unsafe` uses the same `make_safe_globals`), and duplicate what the
  record hook already covers.  Nested runs de-duplicate via `_active_forwarders` +
  `_owned_by_an_inner_run()`.  `python.py::_run` now wraps the sandbox (honouring the
  `log_out` its FIXME said it ignored) and `graxpert.py` wraps `api_run`.  Nine tests in
  `test_emit_hooks.py`, each half falsified by reverting it: a python stage goes from
  `tool.output lines=0, drawn-on-console=4` to `lines=4, drawn=0`, and live under a PTY
  the stage publishes `tool.started` + 4 × `tool.output` + `tool.finished` with
  root-handler frames `3 → 0` (GraXpert likewise: prompt pane lines, root draws `0`).

## Current work focus — `ProcessedTarget` model + live run tree

Implementing [`doc/plans/processed-target-model.md`](../../doc/plans/processed-target-model.md):
make `ProcessedTarget` the single model for a processed target's ``.starbash``
files, expose live doit run state, and drive a live tree in both the CLI and GUI.

Landed (all phases):

- **`src/starbash/run_state.py`** (new) — dependency-free dataclasses
  (`RunStatus`, `FileRef`, `TaskNode`, `StageNode`, `RunTree`) + `RunState`
  accumulator: per-task results, stage status aggregation, **dependencies from
  doit data only** (`file_dep` ∩ other stages' `targets`), a bounded per-stage
  log tail, and `to_document()` / `document_to_tree()` (``run-log.toml``).
- **`src/starbash/processed_target.py`** — read-only model view
  `ProcessedTarget.open(dir)` / `discover(root)` (never writes; `close()` is a
  no-op), accessors `config_url`/`output_dir`/`about`/`sessions`,
  `stage_entries()`/`stage_counts()`, `stage_options()`/`save_stage_options()`
  (moved here from `ui/qt/services.py`, with `StageOption`/`ParameterOption`/
  `coerce_override`/`stage_declarations`), and the run API
  `task_started()`/`record_log()`/`record_result()`/`run_tree()`/`save_run_log()`/
  `latest_run()` (persists ``.starbash/run-log.toml``).
- **Events** — `events.py` gains `EVENT_RUN_STARTED`/`EVENT_RUN_FINISHED`;
  `doit.py:MyReporter` enriches task events with `target`/`stage`/`is_master` and
  calls `pt.task_started`; `processing.py:add_result` folds results into the run
  state (`pt.record_result`), publishes a plain-data `run` snapshot, subscribes to
  `tool.output`/`log.message` to feed the per-stage log tail, and `_finish_runs()`
  persists + announces each target's run.
- **CLI** — `commands/process.py` replaces the end-of-run table with a live
  `ProcessingView` (one shared `rich.live.Live` hosting the `Progress` bar, the
  tree and the live status line — see the section above); `rich.run_tree_to_rich()`
  renders `target → stage → task` with status glyphs, clickable output/recipe/
  config links and the log tail. `Processing` now accepts an external `Progress`
  so there is only one render loop.
- **GUI** — `ui/qt/pages/processing.py` builds the same nested tree from the
  plain `run` snapshots (`_render_run`), coloured by status.  There is **no
  separate log pane**: the tree is `target → stage → task`, and each task carries
  two collapsible children — a `Log` node (its own bounded `TaskNode.logs` tail)
  and an `Out` node (its files).  Live tool lines attach to the *running task's*
  `Log` via `_on_task_started`/`_append_log_line`; the `Log` is auto-opened while
  the task runs and auto-closed when it finishes, except on failure (kept open so
  the error is visible).  `RunState` attributes each line to the current
  `_current_task` (and still keeps the stage's flat tail for the CLI).  Master
  (calibration) runs get a descriptive label
  (`ProcessedTarget.run_label`, e.g. `Master flat_Ha · 2024-01-01 · canon`) and
  their root is **collapsed by default** (`RunTree.is_master`).  Stage rows come
  from the doit task list, **not** the target's `[[stages]]` config:
  `Processing._job_to_tasks` calls `pt.set_run_stages(tasks_to_stages(tasks))`,
  so only stages that actually produced a doit task appear.
- **Consumers migrated** — `ui/qt/services.py` (`load_targets`,
  `load_stage_options`, `save_stage_options`) and `publish/github.py` (`_targets`)
  now go through the model.  `ProcessedTarget.open()` is **lazy**: `about`/
  `sessions` are properties and `parameter_store` is a cached property, so
  `discover()` (the GUI Targets page) only parses each target's small `main.toml`
  — parsing every `sessions.toml` there hung the GUI thread.
- Tests: `tests/unit/test_run_state.py`, `tests/unit/test_processed_target_model.py`,
  `tests/unit/test_run_tree_rich.py`; `test_emit_hooks.py`/`test_gui.py` updated.
- **Non-interactive output fallback** — a `rich.live.Live` renders *nothing* to a
  pipe/file/dumb terminal, so the live tree silently produced no CLI output for
  tools.  That broke
  `tests/integration/test_workflow.py::TestProcessMastersWorkflow::test_process_masters_executes`,
  which parses stdout for ≥10 rows containing `Success`.  `rich.supports_live_display(console)`
  gates the `Live`, and a sink that fails it gets no live frame.  Originally that meant
  `ProcessingView` skipped `Live` and printed only `rich.runs_to_table(...)` on `finish()`
  (a flat one-row-per-task table with plain status words
  (`Success`/`Failed`/`Up-to-date`/`Excluded`/…) plus a row for any task-less stage) — so a
  redirected run lost every line it produced *while* running.  **Superseded by Fix 8**
  (see the top of this file): the fallback is now
  `ui/cli_events.py::SimpleLoggingEventHandler`, chosen by
  `CliEventHandler.for_console()`, which prints those lines as they happen and then the
  same table.  Tests in `tests/unit/test_cli_events.py` (plus
  `test_run_tree_rich.py::TestSupportsLiveDisplay`/`TestRunsToTable`).

## Current work focus — Phase GUI (branch `feat-gui`)

Implementing [`doc/plans/gui.md`](../../doc/plans/gui.md): a **PySide6 desktop GUI**
launched by `sb gui`, and the removal of the Textual prototype.
Status (all phases 0–7 landed except GitHub upload from the GUI):

- **Phase 0 (core seams)** — added `src/starbash/events.py` (dependency-free
  pub/sub bus) with emit hooks in `tool/base.py` (`tool_run_streaming`:
  started/finished/output/progress%), `doit.py` (`MyReporter`: task
  started/finished), `processing.py` (`add_result` → stage.result; target loop →
  process.target) and `app.py` (`reindex_repo`: throttled progress + finished).
  Added `src/starbash/interaction.py` (`UserInteraction` protocol, Rich default,
  `AutoAccept`, `get/set_interaction`) and routed the guided prompts in
  `commands/user.py` through it. Tests: `tests/unit/test_events.py`,
  `tests/unit/test_emit_hooks.py`.
- **rc-astro JSON progress → events** — `tool/base.py` gained
  `publish_tool_progress(cmd, *, percent, message, line)` (the single shaper of
  `EVENT_TOOL_PROGRESS` payloads; clamps percent; `_publish_tool_line` reuses it).
  `tool/rcastro.py`'s `on_line` now publishes parsed `progress`/`status` info
  through it (status is message-only, so the GUI leaves the bar untouched and
  shows the phase on the running task's details column). Previously the CLI's
  Rich bar worked but the GUI never saw rc-astro progress. Tests:
  `test_emit_hooks.py::test_rc_astro_json_progress_is_published_as_tool_progress`,
  `test_gui.py::test_processing_page_tool_phase_does_not_reset_progress`.
- **Structured tool streams stay out of the log** — rc-astro's `--json` frames were
  being echoed verbatim into the run-tree log tails (and so into the GUI `Log`
  nodes, which are rebuilt from the core's run snapshots). Fix: `tool_run_streaming`
  gained `stdout_mime`; when a tool declares one (rc-astro passes `"json"`) its
  `EVENT_TOOL_OUTPUT` stream is named `stdout.<mime>` (e.g. `stdout.json`), and both
  log renderers — `Processing._on_log_event` (feeds the CLI *and* GUI trees plus the
  persisted `run-log.toml`) and `ProcessingPage._on_event` (live GUI append) — skip
  it via the new `events.is_structured_stream(stream)` helper
  (`STRUCTURED_STREAM_MIMES = {"json"}`; unknown mimes stay human log text). The raw
  lines still land in `log_out`, and the parsed progress still arrives as
  `EVENT_TOOL_PROGRESS`. Tests:
  `test_emit_hooks.py::test_tool_run_streaming_tags_structured_stdout_with_its_mime`,
  `::test_tool_run_streaming_leaves_plain_stdout_untagged`,
  `::test_rc_astro_declares_its_stdout_is_json`,
  `test_processing.py::TestRunLogAttribution::test_skips_structured_stream_frames`,
  `test_gui.py::test_processing_page_skips_structured_tool_stream_lines`,
  `test_events.py::test_is_structured_stream_recognises_known_mimes`.
- **Phase 1 (skeleton + Textual removal)** — `pyside6` is a **normal dependency**
  (no `gui` extra: the GUI is first-class, "optional" only meant users may keep using
  the CLI), `pytest-qt` dev dep, `gui` pytest marker (runs by default, deselect with
  `-m "not gui"`), `commands/gui.py`, `sb gui` registered. Deleted
  `src/starbash/ui/main.py` and the `textual` / `textual-dev` deps; removed the
  justfile `textual-*`/`ui`/`download-textual` recipes and added a `gui` recipe;
  marked `doc/textual.md` superseded.
- **Phases 2–6** — `ui/qt/**`: main window (nav rail + stacked pages), theme QSS,
  event bridge, workers (`QThreadPool` + `CancelToken`), jobs, services, dict table
  models, widgets (stat card, log view, FITS/raster image viewer, selection panel)
  and pages (dashboard, sessions+browse+export, masters, targets options tree,
  live processing, repositories w/ progress, publish, settings, setup wizard).
- **Phase 7 (polish/docs)** — `tests/unit/test_gui.py` (37 tests, `gui` marker,
  offscreen), `tests/unit/test_targets_page.py` (20 tests) and
  `tests/unit/test_gui_command.py` (graceful no-PySide6 path, runs in the default
  suite).

Targets page specifics (recent tweak round):

- The stage list is a **`QTreeWidget`**: top-level rows are stages (ticked = active),
  children are the parameters the recipe declares (`[[stages.parameters]]`), showing
  the recipe default, the description (tooltip) and any override. Overridden values
  are bright yellow, defaults dim; a stage's summary column lists its **overridden
  values** (e.g. `crop_width=85%, crop_height=4150`), not option counts.
- Selecting a parameter opens an editor with two tabs, **Use default** vs **Edit
  override** (no checkbox): the former clears the override, the latter adopts the
  default as the starting value. The editor is height-floored
  (`_EDITOR_MIN_HEIGHT`, grown when a description wraps) so the tab pane is never
  clipped by the tree above, and the output-directory label uses the padded
  `PathLabel` style. The stages column keeps a `_COLUMN_GAP` (12px) left margin so
  it is not flush against the target list's vertical scrollbar, and the option
  editor pane is hidden (not just disabled) until a row is selected.
- The targets/stages `QSplitter` defaults to **`_TARGET_LIST_SHARE` = 0.66**, i.e.
  the target list gets ~2/3 of the width (long output paths were truncated
  otherwise). Note the subtlety: `setStretchFactor` only divides *extra* space, so
  the proportion is set with an explicit `splitter.setSizes([660, 340])` (stretch
  factors 2:1 then keep that ratio on resize). `test_targets_page.py`
  ::`test_target_list_defaults_to_two_thirds_of_the_width` locks this in — without
  the `setSizes` call the measured share was 0.57.
  **Superseded (2026-09-13, Targets redesign):** the list is now a narrow picker —
  `_TARGET_LIST_SHARE = 0.22` with the Output link moved to the right pane's path
  label, and `test_target_list_is_a_narrow_picker` replaced the 2/3 test. The
  `setSizes`-plus-stretch-factor subtlety above still applies.
- **Image previews are asynchronous.** `widgets/image_viewer.py` decodes on a worker
  thread via `workers.run_async` and shows `widgets/busy_indicator.py`
  (`BusyIndicator` — a self-centring rotating arc + caption) over the image pane
  meanwhile; `show_file()` no longer raises, it reports a broken frame in the view.
  A `_request` counter drops stale loads. `Sessions` and `Masters` are the two
  pages that show JPEG/FITS previews.
- **`run_async` retains its `Worker`** (`workers._live_workers`) until it finishes.
  Without that, a dropped reference let C++ destroy the `QRunnable` and its signals
  before the queued callback was delivered — only **7 of 60** callbacks arrived.
  The unit test for this fails loudly if the retention is removed.
- **Checkbox indicators are drawn explicitly in `theme.STYLESHEET`** (visible
  outline off, accent + `assets/check.png` tick on). Qt's native indicator was a dark
  box on the dark panel — invisible. `theme.checkmark_path()` resolves the glyph with
  `importlib.resources`; if it cannot be found the tick is simply omitted (solid
  accent box), so a packaging slip degrades rather than breaks. The same rules cover
  the Targets/Processing tree indicators.
- **An id-styled button needs its own `:disabled` rule** (`theme.py`). Qt applies CSS2
  specificity, so `QPushButton#Primary` (id) outranked the generic
  `QPushButton:disabled` and the disabled "Run auto pipeline" button kept its full
  accent fill — pixel-identical to the enabled state (user-visible bug). `#Primary`
  and `#Danger` now declare `...:disabled` **after** their `:hover` rules (equal
  specificity, so later wins). Regression:
  `test_gui.py::test_a_styled_button_looks_disabled_when_it_is_disabled`, which grabs
  the rendered face colour in both states — it fails against the old stylesheet.
- **Tree rows carry their own vertical padding *and* a height floor**
  (`QTreeView::item { padding: 4px 0; min-height: 16px; }`). The indicator is 16px
  but an unpadded tree row was only ~16px tall, so the stage checkboxes in the
  Targets list touched each other. A row's *natural* height follows the font
  metrics, which are platform-dependent — on Windows (shorter Segoe UI rows) the
  padded row rendered at 22px, only 6px taller than the box, so `min-height` (set
  to the same 16px constant as the indicator, `theme.INDICATOR_SIZE`) floors the
  row's *content* box; padding is added on top, giving 24px on every platform.
  A test measures the *rendered* row height against the indicator size read out
  of `theme.STYLESHEET` and also asserts the theme declares the `min-height` floor
  (`test_stage_rows_are_tall_enough_to_separate_their_checkboxes`) — it fails if
  the rule is removed, and applies the theme itself (`theme.apply_theme(qapp)`),
  since `test_targets_page.py` otherwise runs unstyled. Horizontal padding stays 0
  so the indentation and checkbox inset are unchanged.
- **`QUrl.toLocalFile()` returns `/`-separated paths on Windows** while
  `str(Path)` uses `\`, so `test_file_links.py`'s `_FakeDesktop` (and its `fail`
  set) normalises both sides with `os.path.normpath`. Without that the Windows run
  recorded `C:/...` against expected `C:\...`, so the fake never failed the paths
  the tests asked it to and three tests failed (`assert True is False`).
- **Qt needs OS libraries the wheel does not ship.** CI failed with
  `INTERNALERROR> ImportError: libEGL.so.1: cannot open shared object file` because
  `pytest-qt` imports `QtGui` while pytest is still configuring, so a missing system
  library kills the session before collection — even for non-GUI tests.
  Fixed in `.github/workflows/ci.yml` (and `integration.yml`) by installing
  `libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1`;
  `tests/conftest.py` now detects it and prints the fix, and `doc/development.md`
  has the per-distro commands plus the no-Qt workaround
  (`STARBASH_SKIP_QT_LOAD_CHECK=1 pytest -p no:pytest-qt -m "not gui"`).
- **Platform-sensitive tests**: `test_desktop_entry.py` is skipped off Linux (the
  XDG `.desktop` installer no-ops there by design) and the Qt-load guard test only
  asserts the Linux `apt-get` advice on Linux (macOS/Windows get "reinstall" advice,
  since Qt ships in the wheel there). The CI matrix runs ubuntu + macos + windows.
- `services.load_stage_options()` merges recipe declarations with the target's
  `.starbash/main.toml` overrides; `save_stage_options()` rewrites only
  `[[stages]]` (round-trip idempotent, preserves other sections such as citation).
- **Save options / Undo changes** are visible only while the page is dirty. Leaving
  the page (or picking another target) with unsaved edits prompts Save/Discard/Cancel
  via `Page.can_leave()`, which `MainWindow` consults before switching pages and on
  close.
- The table row for the currently selected target (`sb select target …`) is
  pre-selected on load.
- The Targets list's **Target** column is 160px (target names are ~20 chars max).

Still open: uploading to GitHub Pages from the GUI (still needs the CLI's
interactive device flow; the GUI page builds the site locally and points at
`sb publish github --login`).

Decision made: **`pyside6` is a normal dependency, not an extra.** The GUI is a
first-class way to drive Starbash; "optional" only meant users may keep working from
the CLI. (An earlier `gui` extra was reverted.)

Decision made: **keep `pyqt6`**. `pyqt6` is only used by out-of-process
`siril-scripts/` experiments, not by Starbash itself, so the two bindings cannot
conflict in-process — dropping it would have broken that experiment for no benefit.

## Previous focus (report R3)

The codebase is on `main` at commit `21dac19` ("fix lint"), one commit past the `v0.3.1` release tag (`90529fe`). Recent commits center on:

- **Reporting (R3-style) work**: generalizing per-frame registration reporting across all OSC stacking variants. Landed commits include "fix duo stacking", "oops i was using the wrong duo channels", "crop fixes", "improve crop", "generalize reporting to all osc runs".
- A local branch `feat-report2` exists with additional unpublished WIP ("report2 plan", "wip") that has not been merged to `main`.

Open tabs / files being touched suggest active work in:
- `src/starbash/siril/import_registration.py` + `tests/unit/test_import_registration.py` — per-frame FWHM/registration metric parsing and DB updates.
- `starbash-recipes/osc/report_registration.toml`, `stack_osc.toml`, `stack_single_duo.toml`, `stack_dual_duo.toml` — TOML stages driving Siril registration reporting.
- `doc/design/report.md` — the end-to-end design covering target report metadata (R1), Jekyll publishing (R2), and per-frame registration TOML stages (R3).

## Recent changes
- **Fixed the two Windows-only unit-test failures (file URLs, site upload order)** —
  `starbash.url.make_file_url()` built its URL by hand as `file://` +
  `quote(str(path))`, which percent-encodes a Windows path's backslashes and drive
  colon into an unusable `file://C%3A%5C...` — very visible in the GUI, since
  `master_url()`/`load_targets()`/`_path_link()` feed it to `QUrl`, which cannot
  resolve that.  It now delegates to `Path.as_uri()` (making a relative path
  absolute first, because `as_uri()` *raises* on relative ones), so a drive path
  reads `file:///C:/dir/file` and POSIX output is unchanged.
  `FileInfo.rich_links` (`doit.py`) hand-built the same broken URL for the run
  tree's clickable outputs and now uses the helper.  Separately,
  `collect_site_files()` sorted the `Path` objects themselves, and `Path`
  comparison is case-*insensitive* on Windows — so the site upload order (and the
  test asserting it) differed per platform; it now sorts by the site-relative
  posix path.  New tests lock this in: two in `tests/unit/test_url.py`, a
  case-order one in `tests/unit/test_github_publish.py`, and
  `TestFileInfoRichLinks` in `tests/unit/test_doit.py`.
- **…and that grew into one canonical `file://` spelling across both repos** —
  see `doc/plans/canonical-file-urls.md` (implemented 2026-09-15).  `toml_repo`
  now *owns* the spelling (`toml_repo/urls.py`: `make_file_url()` ==
  `Path.as_uri()` and `path_from_file_url()`), `starbash.url` re-exports both, and
  every hand-built URL *and* every `url[len("file://"):]` slice is gone from both
  trees (5 sites in `toml_repo/repo.py`, plus `app.py`'s repo-URL producers,
  `doit.py`, `github_publish.py` and the GUI hover/link parsers).  The **legacy
  spelling is refused, not translated** (`ValueError`: `file://C:\dir` is
  indistinguishable from a URL host) — the owner recreates the databases instead
  of migrating them.  `_find_user_repo_ref()` now accepts the recorded dir *or*
  the canonical URL, since the CLI passes user input and the GUI passes `repo.url`.
  Because starbash must consume the *updated* parser, the dependency floor is
  `toml-repo = ">=0.1.7"`: **0.1.7 was released to PyPI on 2026-09-15** (Option B
  in plan §7 — the `develop = true` path dep is gone), so the lock pins 0.1.7 and
  a fresh resolve cannot fall back to 0.1.6, which has no helpers.  `starbash.url`
  is a **re-export** of both helpers (`from toml_repo import make_file_url as
  make_file_url`), pinned by `test_url.py`'s `is`-identity test, so Starbash's
  writer and toml_repo's reader cannot drift.  Gates: `just lint` clean, starbash
  **1202 passed**, toml-repo **39 passed**.
- **The Windows CI run exposed six platform-dependent *assertions* in those URL
  tests (2026-09-15) — the code was right, the tests were not.**  `path_from_file_url()`
  is deliberately platform-independent (it always yields a `/`-separated string to
  `Path()`), but `str(Path(...))` renders with the **platform's** separator, so
  `"/data"`, `"/C:/x"`, `"/a b/c&d"` and `"C:/Users/runner/data"` become `"\\data"`,
  `"\\C:\\x"`, `"\\a b\\c&d"` and `"C:\\Users\\runner\\data"` on Windows.  Those
  assertions now compare **`.as_posix()`** (`tests/unit/test_url.py` ×2,
  `toml-repo/tests/test_urls.py` ×4, including the submodule's own drive-letter,
  localhost, percent-decoding and `/C:`-looks-like-a-drive cases) — and
  `test_path_from_file_url_handles_a_windows_unc_share` was already safe because it
  compared `str()` against `str()`.  The seventh failure was worse than cosmetic:
  `test_hover_preview.py`'s parametrised fixture wrote a file named `q?mark.txt`,
  which **Windows cannot create at all** (`OSError [Errno 22]`), so `?` left that
  parametrisation and its real point — a `?` must be percent-encoded to `%3F` rather
  than starting a query — is now asserted on the URL itself, with no filesystem
  access, by `test_make_file_url_percent_encodes_a_question_mark` (so it guards
  Windows too).  Lesson worth keeping: **assert on `.as_posix()` (or compare like
  with like), never `str(Path)`, when the expected value is POSIX-spelled; and never
  name a fixture file after a character Windows forbids** (`? * : " < > |`).
  Gates: `just lint` clean, and the three touched test modules pass
  (`70 passed, 1 skipped`; the toml-repo tests run in-process against the installed
  0.1.7, which is byte-identical to the submodule's `urls.py`).
- **Integration CI runs the whole three-OS matrix, with StarNet2 installed on each** —
  see [`.github/workflows/integration.yml`](../../.github/workflows/integration.yml):
  the strategy is now `fail-fast: false` with `os: [ubuntu-latest, macos-latest,
  windows-latest]`, so one platform's breakage can no longer cancel the others'
  results.  All three install the *same* CLI release, pinned once in the job-level
  `STARNET2_VERSION: "2.6.2-0241"` env var (bumped from the `2.5.4-0214` that
  `just install-starnet` still gives the dev container) from
  https://download.starnetastro.com/: Linux `.deb` (drops `/usr/bin/starnet2` +
  `/usr/lib/starnet2`; `Depends: libc6, libstdc++6` only, installed exactly as
  `just install-starnet` does), macOS `.pkg` (`/usr/local/bin/starnet2` +
  `/usr/local/lib/starnet2`, the Apple-Silicon CoreML build via `sudo installer -pkg
  … -target /`, behind an `uname -m` guard for a future Intel image) and the Windows
  Inno Setup installer (`/VERYSILENT /NORESTART`; the binary lands in
  `C:\Program Files\StarNet2\bin`, which the step adds to `GITHUB_PATH` because
  Starbash resolves `starnet2` through the PATH).  Each step fails loudly if the
  install produced no usable binary — `command -v starnet2` + `starnet2 --version`
  on Linux/macOS, an exe search + `& starnet2 --version` on Windows.
  **Why the version pin is safe** (so it need not be re-derived): the recipe runs
  StarNet through Siril 1.4.x's deprecated C `starnet` command, and
  `starnet_executablecheck()` (`src/filters/starnet.c`) classifies the CLI purely
  from `starnet2 --version`: `"StarNet++ v2"` → `V2`, `" version:"` → `TORCH`.  Both
  2.5.4 and 2.6.2 alike print that marker (`starnet2  version: 2.5.4` /
  `starnet2  version: 2.6.2`), so we take the `TORCH` branch,
  which passes `-i/-o/-m/-s/-u/-w` — all still present in 2.6.x.  2.6.0 did remove
  `-e/--eight`, but Siril never passes it on that path.
  Verified without a runner: the `.deb` extracted to `/tmp` and its binary run; the
  `.pkg`'s XAR Payload listed with a small Python cpio scan (confirmed
  `/usr/local/bin/starnet2` + the CoreML `.mlpackage`); the Windows step body
  executed under PowerShell 7.6.6 with download/installer stubbed (URL string, exe
  discovery, `GITHUB_PATH` write, installer-failure branch, cleanup); test-step
  shell blocks through `bash -n`; and `actionlint` 1.7.7 clean on
  `.github/workflows/`.
  **Resolved 2026-09-15** (was an open question): flatpak Siril on Linux keeps its
  config *inside* its sandbox
  (`~/.var/app/org.siril.Siril/config/siril/config.1.4.ini`) while
  `StarnetTool._siril_config_dir()` read only `~/.config/siril`, so StarNet could be
  detected on macOS/Windows (native Siril; GLib's config dir matches platformdirs'
  on both — LocalAppData on Windows, `~/Library/Application Support` on macOS) and
  *skipped* on Linux.  Nothing asserts on star removal
  (`tests/integration/test_workflow.py` only wants exit 0 and ≥10 `Success` rows), so
  the run stayed green either way — but the three platforms exercised different
  stages.  `StarnetTool` now scans the flatpak directory as well, preferring whichever
  install Starbash would actually run, so the Linux job detects the `starnet2` it
  installs; see the newest *Current work focus* section at the top of this file.  Two
  things remain unmeasured: no flatpak exists in this dev container, so the fix is
  verified against a stubbed sandbox layout rather than a real flatpak Siril, and the
  three-platform stage difference has not been re-measured on a CI run.
- **Up-to-date skips are no longer reported as failures** — see the section at the
  top of this file: `ResultSummary` (new, `run_state.py`) buckets doit's tri-state
  `success`, so `success=None` counts as *up-to-date* instead of failed, and
  `RunStatus.SKIPPED.label` / `rich._STATUS_WORDS` now read `up-to-date` (the
  persisted `run-log.toml` value is unchanged).
- **Auto re-index preference** (default true) + GUI checkbox — see the section at
  the top of this file: runs now call `Processing.reindex_if_needed()` before
  planning, gated on `reindex.auto`, and both front ends render the existing
  `reindex.progress` / `reindex.finished` events (`preferences.py` is new).
- **Fixed the frozen run-tree pane in `sb process auto`** (fix 4 of
  [`doc/plans/cli-live-display.md`](../../doc/plans/cli-live-display.md)): the pane
  "filled the screen once and never changed again" because no event ever carried a
  *running* node -- `stage.result` snapshots are taken just after a task finished,
  and `MyReporter.execute_task()` published `task.started` with no snapshot, so
  `pt.task_started()`'s `RUNNING` placeholder never escaped the process.  So the
  tree drew no `⏳`, fix 3's anchoring was dead code, and the fallback parked the
  pane on the newest run's finished top.  `task.started` now carries the fresh
  `run_tree().to_plain()`; the view scans runs newest-first and anchors on the
  running task -- or, between tasks, on the run's last finished row -- instead of
  its root.  Verified by two new tests that fail without the payload key, plus a
  live PTY run of the real producer path (`⏳` rows `0 → 28`).
- **Fixed the `sessions.telescop` collation typo** (`src/starbash/database.py`): the
  column was declared `telescop TEXT COLLATENOCASE NOT NULL` — the missing space made
  SQLite treat `COLLATENOCASE` as part of the *type name*, so no `NOCASE` collation was
  applied and telescope matching was case-*sensitive* (unlike its `filter`/`imagetyp`
  neighbours, which are `COLLATE NOCASE`).  Now `telescop TEXT COLLATE NOCASE NOT NULL`.
  This only affects **newly created** databases: `CREATE TABLE IF NOT EXISTS` never
  alters an existing table and the project has no migration framework (`just reinit`
  rebuilds the DB).  Regression test:
  `tests/unit/test_database.py::test_session_telescop_matches_case_insensitively`
  (fails with the typo, passes with `COLLATE NOCASE`).
- **Fixed the latent `sessions.telescop` crash** (`src/starbash/app.py`): the
  `sessions` table declares `telescop TEXT COLLATENOCASE NOT NULL`, but
  `_add_session` only set the key when the FITS header carried `TELESCOP`.  A frame
  without it (legitimate - `_extend_image_header` even falls back to `CREATOR`) made
  `upsert_session` insert NULL and abort the **entire repo scan** with
  `sqlite3.IntegrityError`.  `_add_session` now always supplies a telescope, using
  `""` ("unknown") as the default; `get_session` already treats an empty telescope as
  "match any", so such frames still join the same rig's existing session when one
  exists and only create an empty-telescope session on their own.  This removed the
  `TELESCOP = "Test"` workarounds the earlier test-repair pass had added to the
  `test_app.py` fixtures, and a new regression test
  (`test_reindex_repo_handles_frames_without_telescop`) fails without the fix.  A
  follow-up then repaired the column's misspelled collation (see the entry above).
- **Type checking now covers the tests — and it immediately paid off**
  (`pyproject.toml`, `justfile`): `[tool.basedpyright] include` is now
  `["src", "tests"]` and `_typecheck` runs bare `basedpyright`.  Fixing the ~390
  errors it revealed uncovered a **real bug**: `Starbash.__exit__` returned
  `analytics_exception(exc)`, and under tests that name is a `MagicMock` (truthy),
  so *every* `with Starbash():` silently swallowed its exception.  That made
  `TestProcessing` / `TestAddOutputPath` vacuous — they called methods that no
  longer exist on `Starbash` (`start_session`, `run_stage`, `run_all_stages`,
  `init_context`, `add_output_path`) yet "passed".  `__exit__` now returns `False`
  explicitly in test env (production behaviour unchanged); the two stale classes
  were deleted (the behaviour lives in `Processing`, covered by
  `test_processing.py`) and `test_app.py`'s other stale tests were repaired to the
  current APIs: `_add_session(header)` needs `header["id"]` plus FITS-cased keys,
  session rows are read with lowercase `get_column_name(...)` keys,
  `get_session_images` takes a `SessionRow` (not an id) and no longer raises for an
  unknown id, `reindex_repo` has no `force` argument (force comes from
  `starbash.force_regen`), `db.get_image(repo_url, path)` takes two args, and
  `Repo.add_repo_ref(manager, dir)`.  Most of the remaining errors were tomlkit /
  Qt stub gaps, fixed in the tests with small local helpers (`_config(repo) -> Any`
  for `Repo.config`, `_top`/`_row` for `QTreeWidget` children, `_loaded`-style
  `assert isinstance(...)` narrowing) rather than blanket suppressions.
- **`ruff format` now actually formats the Python sources** (`pyproject.toml`): the
  `[tool.ruff.format]` `exclude` list contained `"*.py"`, which (ruff's globset
  treats `*` as crossing `/`) excluded **every** Python file - so `just lint`'s
  format step silently did nothing. Removed that entry and ran `ruff format src
  tests` once, normalising 53 files (all 154 are now format-clean; `just lint` is a
  no-op on a clean tree).  Note the format step reformatted a long call in
  `score.py` and detached an `# type: ignore[arg-type]` from the line it guarded;
  replaced it with a proper `"None"` default (matching the neighbouring filter
  lookups), which also removes a latent `normalize(None)` crash.  Also fixed 9
  pre-existing `basedpyright` errors in `processed_target.py` (unbound
  `metadata_dir`, undeclared `config_path`, annotated attribute assignments outside
  `__init__`, `Path | None` into `_read_or_template`, and a possibly-`None` task) so
  `basedpyright src/` is clean.
- **Hover previews stay open + Targets links** (`ui/qt/widgets/hover_preview.py`,
  new `ui/qt/widgets/file_links.py`, `ui/qt/pages/targets.py`, `ui/qt/models.py`,
  `ui/qt/services.py`, `processed_target.py`): the preview is now an interactive
  `Qt.Tool` window with its own **close adornment** (✕, plus Escape).  It **stays
  open** when the cursor leaves the link (so the popup's scrollbars are usable) -
  moving away only cancels a *pending* preview; a click/scroll in the view closes
  it, and it never reopens for a link the user just closed until the cursor leaves
  it.  **At most one** preview exists (a module-level `WeakSet` hides others, and
  `_safe_hide` tolerates already-destroyed windows).  Opening a file with no
  handler (`No applications found for mimetype`) now **falls back to the
  containing folder** in the file manager.
  Link handling moved into the shared `file_links.py` (`LINK_ROLE`, `set_link`,
  `open_link`, `LinkDecorator`), backed by `models.LINK_ROLE`/`Column.link_key`.
  `LinkDecorator(open_on=...)` picks the signal that opens a link: `"clicked"`
  (Processing) or `"activated"` (double-click/Enter).  The **Targets page** uses
  it: each `Stage / option` cell links to the recipe that declares it (via the new
  `StageOption.recipe_url`), so hovering previews the recipe and activating the row
  opens it - a plain click still just selects/toggles, so it never fights the stage
  checkbox or the option editor.  The target list's `Output` cell links to the
  folder and the path label is a clickable anchor.  Tests:
  `tests/unit/test_file_links.py` (8) + expanded
  `test_hover_preview.py`/`test_targets_page.py`.

- **Processing page: clickable links + hover previews** (`ui/qt/pages/processing.py`,
  new `ui/qt/widgets/hover_preview.py`): link cells (a stage's recipe, a task's
  output files, the target output) are underlined; clicking one opens it with the
  desktop default app (`QDesktopServices.openUrl`, external process) and resting
  the cursor on a *local* file pops up a frameless, shadowed preview (~25% of the
  owning window, placed beside — never over — the hovered cell). Text, FITS and
  raster are rendered; decoding runs off the GUI thread (`run_async` +
  `BusyIndicator`) and reuses `image_viewer.load_image_file`. HTTP(S) links keep a
  native tooltip instead. The run tree also splits its columns ~50/50 on first show
  (`_RunTree`). *Superseded details (mouse-transparent, auto-dismiss) replaced by
  the entry above.* Tests: `tests/unit/test_hover_preview.py` + `test_gui.py`.

- **Processing page run feedback** (`ui/qt/pages/processing.py`,
  `ui/qt/widgets/busy_indicator.py`): clicking "Run auto pipeline" now disables that
  button and shows a compact inline `Spinner` (21×21 px, `WA_TransparentForMouseEvents`)
  in the button row; `Cancel` becomes enabled and the spinner keeps turning until
  `_finish()` (which also runs on failure). Masters-only processing deliberately has
  **no GUI button** — it stays CLI-only (`sb process masters`, `Processing.run_master_stages()`),
  and `jobs.process_job()` no longer takes a `masters_only` flag; the GUI always runs the
  full pipeline. Unlike `BusyIndicator` (a self-centring overlay panel + caption),
  `Spinner` is laid out in the row and reuses the `BUSY_ACCENT`/`BUSY_TRACK` theme colours.
  It **always keeps its layout slot** — while idle it stays visible and paints nothing
  (`paintEvent` returns early), because hiding it collapsed the slot and slid `Cancel`
  27px left the instant a run began, i.e. the button moved out from under the cursor that
  had just clicked Run. Covered by
  `test_gui.py::test_processing_page_disables_buttons_and_shows_spinner`,
  `test_processing_page_run_button_starts_a_job`,
  `test_processing_page_offers_no_masters_only_button` and
  `test_processing_page_button_row_does_not_shift_when_a_run_starts` (measures real
  geometry; fails if the spinner hides again), plus `test_image_viewer.py`'s
  `test_spinner_only_animates_while_running` (`_accent_pixels` renders onto a solid
  image and counts only accent-coloured pixels — rendering always fills the palette
  background first, and a dark theme's panel colour sits within tolerance of
  `BUSY_TRACK`, so only the accent is a palette-independent signal).
- **Per-task log grouping in the Processing page** (`ui/qt/pages/processing.py`,
  `run_state.py`, `processed_target.py`): tool output is now attributed to the
  running *task* (`RunState.set_current_task`/`TaskNode.add_log`) and rendered
  under a per-task collapsible `Log` node (plus an `Out` node for its files) —
  instead of a flat list under the stage. Live lines are capped at
  `LOG_TAIL_LINES` (8), the running task's `Log` auto-opens and auto-closes on a
  clean finish (kept open on failure). Covered by four new
  `test_gui.py::test_processing_page_*` tests plus `test_run_state.py`/
  `test_processed_target_model.py` log-attribution tests.
- **Master runs are grouped under a collapsed `Masters` node in the Processing
  page** (`ui/qt/pages/processing.py`): every master (calibration) run — the rows
  whose label reads `Master <config> · <date> · <camera>`, i.e. `is_master` on the
  run snapshot / task event — is now nested under one lazily-created, **dim and
  bold** top-level `Masters` group that starts **collapsed**, instead of sitting
  at the top level beside the targets where a dozen of them crowded the tree out.
  `ProcessingPage._ensure_target(target, is_master=…)` files a row via `_file_run`
  (group or top level; master-ness is *sticky* per label), `_on_task_started`
  forwards the event's `is_master` so a master's live row is grouped from its
  first log line, and `_drop_run` removes a culled (preflight) row from whatever
  parent it has — taking the group away with the last master, so no empty
  container is left behind. Crucially the new `_scroll_to` helper replaces every
  `QTreeWidget.scrollToItem` call: Qt's `scrollToItem` **expands collapsed
  ancestors** on the way (verified against PySide6: a collapsed parent came back
  `isExpanded()`), which would have popped the group open behind the user's back
  on the first streamed log line, so a row with a collapsed ancestor is simply
  never scrolled to. Covered by
  `test_gui.py::test_processing_page_groups_masters_under_a_collapsed_node`,
  `test_processing_page_keeps_real_targets_out_of_the_masters_group`,
  `test_processing_page_groups_a_master_task_reported_live` (the regression
  guard for both the grouping and the auto-expand) and the updated
  `test_processing_page_drops_unneeded_master_runs`.


- **Targets page split defaults to a 66/34 layout** (`ui/qt/pages/targets.py`): the
  target list now starts at ~2/3 of the page width via `_TARGET_LIST_SHARE = 0.66`
  plus an explicit `QSplitter.setSizes(...)` (stretch factors 2:1). Regression
  covered by `tests/unit/test_targets_page.py`.
  *Superseded 2026-09-13 by the Targets redesign: `_TARGET_LIST_SHARE` is 0.22 (a
  narrow picker), and 2026-09-14 the picker's single column was made to stretch to
  the scrollbar.*
- **Analytics preference defaults centralized** (`src/starbash/analytics.py`): `DEFAULT_ANALYTICS_ENABLED = True` / `DEFAULT_ANALYTICS_INCLUDE_USER = False` plus `analytics_enabled(repo)` / `analytics_include_user(repo)` helpers. The core (`app.py`), GUI Settings page, first-run wizard and `sb user setup` all read through these now, so an unset preference is consistent. Fixes the GUI showing analytics *off* while the backend treated it as *on*.
- Split processed-target metadata into three files under `.starbash/`: `main.toml` (config/stages/masters/overrides), `about.toml` (generated report), `sessions.toml` (per-session processing state). See `src/starbash/processed_target.py`.
- Added `about.generated_at` / `schema_version` report metadata and `DATE-OBS` to persisted frame metadata (for publishing charts).
- Added publishing subsystem (`src/starbash/publish/`), `sb publish` command, Jekyll/Pygal templates for a GitHub Pages site.
- Added rc-astro (`bxt`/`nxt` JSON streaming), Starnet star removal, live Siril progress, automatic crop stage, and GitHub publishing with concurrent uploads (all in alpha 3).
- Added safe `config_changed` fingerprinting so recipe/parameter edits invalidate and rebuild dependent tasks.

## Next steps

- Done (this session): **the core owns no display at all** — the follow-up to
  `doc/plans/cli-live-display.md`, now written up there as *Fix 5*.
  `Starbash.reindex_repo()` / `reindex_repos()` lost their `rich.progress.track()`
  bars *and* the `show_progress` flag that had been added to quiet them, so the scan
  only publishes `reindex.progress` / `reindex.finished`. `sb repo reindex` would
  then have had no observer, so `src/starbash/ui/cli.py::ReindexView` (new) is it: one
  `Live` + a bar that resets per repo, `Indexed N file(s) in <repo>` lines kept as each
  repo finishes, and no `Live` at all on a pipe/redirect/dumb terminal (that mode is the
  whole output). Wired into both `sb repo reindex` branches and `sb repo add` in
  `commands/repo.py`, drawing on the console `Starbash.__init__` installs.  The GUI's
  re-index/add jobs (`ui/qt/jobs.py`, default `show_progress=True`) were opening a Rich
  display from a worker thread onto process stdout while the page drew the same scan —
  that class of bug is gone with the flag.
  Validated end-to-end under a PTY (120×N): result lines print *above* the live frame,
  the two-line bar frame is erased (`\r\x1b[2K\x1b[1A\x1b[2K`) and replaced by the
  single-line totals frame, cursor restored, no stray bar.  Note for prose: `console.print`
  applies Rich's default *highlighting*, so ANSI sits inside the URL/number —
  `test_the_core_draws_no_progress_bar` therefore asserts on the `━` glyph, not on a
  literal line.  Tests: `tests/unit/test_reindex_view.py` (7), the event-reporting +
  no-bar tests in `test_app.py`, and `test_cli.py::test_repo_reindex_reports_each_repo`
  (the output contract of the all-repos path, which the older smoke test only asserted
  as "exit code 0").  `just lint` clean; full suite **1084 passed**.
- Done: [`doc/plans/master-cull.md`](../../doc/plans/master-cull.md) — after
  phase 1 (master regeneration) cull the displayed master runs that no selected
  target depends on, via an explicit **preflight** (plan) phase. Approach **A** is
  implemented end-to-end: `cleanup_old_contexts()` moved out of
  `ProcessedTarget.close()` (pruning now only at the run boundary), and
  `Processing.run_all_stages()` now (1) runs masters, (2) builds **every** target's
  tasks without running anything, computes needed masters with
  `masters_needed_by()` and publishes `events.EVENT_PREFLIGHT_FINISHED`
  (`{"drop": [labels]}`), then (3) runs the prebuilt tasks with `prune=False` and
  prunes once at the end (`cleanup_old_contexts()`).
  **Correction (after an in-the-field regression):** a named target's
  `~/.cache/starbash/processing/<target>` dir is the *reuse cache* — deleting it
  after the run made the next `sb process` redo every stage from scratch. The
  initial implementation did exactly that via a since-removed
  `ProcessedTarget.remove_processing_dir()`; targets now keep their processing
  dir, and the single end-of-run prune honours `max_contexts` (the reference
  user config sets `80` so every target's cache survives). Regression tests:
  `TestRunAllStagesPreflight::test_target_processing_dir_is_kept_after_run`,
  `TestProcessedTarget::test_named_processing_dir_is_a_reuse_cache`.
  Front-ends: `ProcessingView` (CLI) and
  `ProcessingPage._on_preflight_finished` (GUI). Targets now run in stable
  session order (deduped dict, not a `set`). The full `tests/unit` suite passes.
- Complete the R3 migration: route all three OSC stacking variants through `report_registration.toml` stages, remove `_update_ha_registration_metrics()` from `src/starbash/recipes/osc.py`, and verify `.seq` basenames per stack variant (Phase 0 in `doc/design/report.md`).
- Decide whether to merge the in-progress `feat-report2` branch work into `main`.
- Long-term (from TODO.md, uncheckmarked): mono-camera workflow recipes, drizzle by default, recipe `[import]`/inheritance to reduce copy-paste, per-frame report regeneration, and a recipes writer's guide.

## Active decisions and considerations

- **Processed target layout has moved to split files** (`main.toml` / `about.toml` / `sessions.toml`). Code that assumes everything lives in a single `starbash.toml` is stale — prefer `ProcessedTarget.about_config` / `sessions_config` / `repo` (main.toml wrapper).
- **`[[stages]]` are AoT (array-of-tables)** and live in `main.toml`; `default_stages` on `ProcessedTarget` maps `"stages"` to that AoT for sessionless tasks.
- **Exclusion flow** remains the most common bug source: stage `name` in the recipe ↔ `[stages].excluded` in `main.toml`; if exclusions don't take, verify `default_stages` is populated before `remove_excluded_tasks()`.
- **Report schema versioning** exists (`schema_version = 1`), so future publishers should reject/adapt incompatible report data.

## Important patterns and preferences

- Follow AGENTS.md: keep type hints/docstrings, don't introduce new linter warnings, tests assert on real resulting state (not mocks).
- Rich markup is on for Typer; SQLite row factory is `sqlite3.Row`.
- Tests isolate filesystem via `paths.set_test_directories(...)`.
- **Interactive debugging is available** via the `debugmcp` MCP server added to
  this container (breakpoints, logpoints, stack/variable inspection, stepping on
  the running app). Invoke the `debug-live` skill, then `start_debugging` —
  ideally with one of the existing `.vscode/launch.json` configuration names so
  the Poetry interpreter/args are picked up automatically. Details in
  `techContext.md` → *Tool usage patterns*.
- Recipe `.seq` parsing lives in `src/starbash/siril/import_registration.py`; DB updates go through atomic `Database.update_images_metadata()`.

## Learnings and project insights

- `toml_repo` is an external/git-submodule package (`toml-repo/`); repo config suffix is `starbash.toml` (set in `starbash/__init__.py`).
- Recipes are versioned remote repos fetched from `https://raw.githubusercontent.com/geeksville/starbash-recipes/v${version}` with a local `starbash-recipes/` git submodule fallback during development.
- Session ↔ frame relation is NOT stored explicitly in the DB; frame lookup reconstructs from session criteria (date range, target, filter, telescope, imagetyp).
- **Never batch a "patch then restore" pair as two commands in one `run_commands`
  call.** The tool runs the commands in a call *concurrently* (its own guidance:
  batch commands "safe to run concurrently").  Restoring a temporarily-patched file
  in the same call as the patch is therefore a race: the restore ran first, the
  patch landed last, and `src/starbash/doit.py` was left silently broken (the
  `"run"` key I had just added was gone; the `git diff` in that same call even
  reported the *pre-race* line count).  Keep a mutation and its undo in **separate**
  calls — or better, verify a test fails without a change by *inspecting* the
  payload (`KeyError`) rather than by reverting the source at all.  A `&&`-chained
  single command string (e.g. `git diff ... && pytest ...`) is fine; it is one
  statement executed sequentially.
- **`sessions.telescop` is `NOT NULL`** while `filter`/`object` are nullable, so `_add_session` must always write a value (it uses `""` for "unknown").  `get_session()` only filters on a column when the candidate value is *truthy*, so an empty telescope means "match any" — that is what makes TELESCOP-less frames merge into the same rig's session instead of being split off.
- **Never let a shell command line end at a secondary prompt.** A composite one-liner
  that mixed `&&`, `nohup ... &` and a quoted `echo "$!"` left bash at its
  `dquote>` prompt, which blocks forever (the agent cannot type the closing
  quote) and the intended command never even starts — verified by `ps` showing no
  process and no redirected log being created. The fix is not to retry but to
  simplify: one simple statement per command, long work via a temp script or
  `timeout` in the foreground, multi-line via a correctly terminated heredoc.
  Captured as a standing rule in `.clinerules/terminal.md` and AGENTS.md →
  *Terminal commands (never block on a prompt)*.
- **pytest-qt tracks widgets by *weak* reference**, so a parentless test host is
  garbage-collected mid-test and takes its child widgets with it — the failure
  surfaces as `Internal C++ object (X) already deleted`, not as a test error you can
  read.  `test_tool_warning.py` keeps an explicit strong reference (`_KEEPALIVE`)
  to each host it creates.  (Also: a widget's `parentWidget()`/a window's
  `centralWidget()` is `QWidget | None` to the type checker even when it cannot be
  `None` at that point, so tests need an `assert ... is not None` helper rather than
  `# type: ignore`.)
- **`.clinerules/memory-bank/` is the memory bank's real location** (the six core
  files are git-tracked there); the rule file is `.clinerules/memory-bank.md`, a
  sibling of the directory — not the directory itself.  Looking for a bare
  `memory-bank/` at the repo root finds nothing, which is an easy way to conclude
  "this repo has no memory bank" and then edit the wrong (or a new) place.  The
  shared, cross-agent docs are `AGENTS.md` / `.github/copilot-instructions.md`
  plus `doc/`; `.clinerules/` is Cline-only.
