# CLI live display (one widget, event-driven)

## Goal

During `sb process auto` / `sb process masters` the terminal should show **one**
live widget: the run tree, a **spinner + status line** ("what is happening now"),
the last few tool output lines, and the existing progress bars.  Everything is
driven by `starbash.events`, exactly like the GUI.

## Problem

Rich 15 stacks live displays per console (`Console.set_live` returns
`len(stack) == 1`).  While `ProcessingView`'s live tree was running, every tool
run (`Tool.run` → `ToolLiveDisplay`) started a **second** `Live` on
`starbash.console`:

* a nested `Live.refresh()` calls `console._live_stack[0].refresh()`, so the
  tool's 8 Hz refresh force-repainted the CLI tree 8 times a second, and
* on `stop()` the nested display printed its block *over* the live region.

Net effect (reproduced under a PTY): the tree and the tool block tear each other
apart, leaving orphaned red stderr lines — the "broken CLI output" report.

## Approach

Delete the tool's own display. `starbash.tool` only *publishes* events
(already the case for `EVENT_TOOL_STARTED/FINISHED/OUTPUT/PROGRESS`); the CLI's
`ProcessingView` is the single owner of the console's `Live` and renders every
piece of state from those events.

* `ProcessingView` becomes the live renderable itself (`Live(self)`), so the
  `Live`'s own 4 Hz refresh thread repaints the current state — no per-event
  `update()` storms from high-volume tool output, and no thread-unsafe rendering
  (state is snapshotted at the top of `_render()`).
* Status line: `Spinner("arc")` + a `Text` caption composed from
  `process.target` / `run.started` / `task.started` / `task.finished` /
  `tool.started` / `tool.progress` / `tool.finished`.
* Tool tail: last 3 `tool.output` lines (stderr red, stdout yellow, ellipsised to
  one row), cleared on `tool.started`; structured streams (`stdout.json`) are
  skipped.
* Final frame: `finish()` leaves `✓ <title>: done` on screen, or
  `✗ Failed: <task>` when any task failed (the last frame is what a user walks
  away with, so it must not read as success).
* Progress bars: one bar, shared with `Processing` (`Processing(progress=view.progress)`).
  **Superseded by Fix 7** — `Processing` has no bar at all now, and the view's
  single bar follows the run's *phase* (indexing → planning → tasks) from events.

Because it is only ever fed by the bus, the same widget works for any sink: a
real terminal gets the live view, a pipe/dumb terminal gets the flat table.

## Fix 2: the status must survive a tree of hundreds of runs (Layout split)

Goal 1 was met, but the result still looked broken in real use: users saw three
red `...` dots and only a **flash** of the spinner/status line.

### Problem

A full `sb process auto` accumulates hundreds of `Master ...` runs, so the
combined tree is far taller than the terminal — measured under a real PTY at
**212 lines median / 327 max against a 24-50 row terminal**, i.e. **93-97% of
frames overflowed**.  Rich handles a live renderable that is too tall by keeping
the *top* and appending its red `live.ellipsis` (`...`) marker — so the single
`Group(header, *trees, status, progress)` threw away precisely the status line,
the tool tail and the progress bars (they were *last*) and left only its `...`
overflow marker.  The `...` count matched the frame count (245 vs 251) exactly,
which is what identified it: the dots were not a progress indicator at all.
(Note: the tree also grew monotonically during a run, so the display got worse
the longer it ran.)

### Approach

Split the screen with a `rich.layout.Layout` instead of one `Group`:

* a **pinned status region** on top (title, spinner + caption, tool + percentage,
  the tool output tail, the progress bars) sized to exactly what it needs, and
* the **run trees below it**, given every remaining row.

(The 3-line tail here is superseded by Fix 3's log pane.)

`Layout` renders each region's renderable with that region's height, which is
what makes the split work.  Rich's crop keeps the *top* of an overflow, which is
the wrong end for a live log, so the tree region is a small private renderable
(`_RunTail`) that measures the **most recent** runs from the newest backwards
until the region is full, then reports `… N earlier runs`.  Runs that do not fit
are never rendered, so the per-frame cost is proportional to the screen rather
than to the run count (a nice side effect on a 300-run job).

A run region one row shorter than its box is deliberate: it keeps room for the
"earlier runs" note so the layout does not jump when runs appear or are culled.

### Verification (real PTY, 100x30, 75 s of `sb process auto`)

* Live block shape was a **constant** 29-30 rows for all 266 frames (before:
  median 212, max 327, varying) — it now fits the terminal, so no crop happens.
* Rich's `...` marker count went **245 → 13**, and all 13 remaining are real text
  (`Starting...` 6, `Processing tasks...` 1, `Linking input files...` 3, a Siril
  `...up-to-date...` log line 3).
* The spinner, caption, tool percentage, 3 log-tail lines and both progress bars
  are on screen in **every** sampled frame (0%/35%/70%/100%), not 2 frames.
* The tree shows the newest run plus `… 8 earlier runs`.

## Fix 3: bring back the tool log, and scroll the tree to the running task

Fix 2 made the layout hold together, but it over-corrected: the only tool output
on screen was a **3-line tail** (`TOOL_TAIL_LINES`), and the tree region always
scrolled to the **newest** runs.  Two things were wrong with that:

* a stack runs for minutes, so the line the user needs ("Error: cannot open
  master flat") is usually *not* among the last three — the useful live output
  that `ToolLiveDisplay` used to show had been thrown away; and
* while a stage is building, the run being worked on is the *newest* run, so a
  pane anchored to the newest rows shows its **last** rows — the stages still to
  come — and the `⏳` running task can scroll off the bottom of the pane.

### Approach — two body panes under the header

`_render()` now splits the screen again, but the body is split **in two**:

```
┌ Auto-processing ────────────────────────────────────────────┐  header: title,
│ ⠋ stack: Stack lights · Siril 42%                           │  spinner/caption/tool
│ ███████████░░░░░░░░░░░░░  calibrate 42%                     │  + the phase bar
│                          12/40 0:01:23                      │    (Fix 7)
├──────────────────────────────┬──────────────────────────────┤
│ ──── Siril ────────────────  │ ├── ✓ calibrate              │  body: log (left),
│ reading frame 31.fits        │ └── ⏳ stack ← calibrate       │  run tree (right)
│ reading frame 32.fits        │     ├── working 42%          │
│ Error: cannot open master    │     └── ⏳ Stack lights        │
│ … 21 earlier lines           │          … 3 earlier runs     │
└──────────────────────────────┴──────────────────────────────┘
```

* **Log pane (left)** — `_LogTail` over a `deque(maxlen=LOG_LINES)` (500) filled
  from every non-structured `tool.output`.  It is the *run's* log, so it is **not**
  cleared when the next tool starts; `tool.started` just appends a dim
  `──── <tool> ────` rule so a tool's output stays attributable.  Lines are
  literal `Text` (never markup — see the `MarkupError` hardening in fix 1): stderr
  red, plain stdout left alone, and any line containing a
  `starbash.tool.base.BAD_WORDS` entry also red, because Siril does not reliably
  mark its own errors.  The pane is tail-anchored (newest line on screen) and
  reports `… N earlier lines`.
* **Run tree pane (right)** — `_RunWindow` measures runs from the newest
  backwards (so per-frame cost still tracks the screen, not the 300-run count),
  then windows that text so the `⏳` (`RunStatus.RUNNING.glyph`) row of the run
  that is building is visible, with `ANCHOR_CONTEXT = 2` rows of context above it
  (its stage header) and the stages still to come below.  `_building_index()`
  finds that run from the plain run snapshots (no rendering needed).  When the
  run fits it is shown from its root, so the **target name stays on screen**;
  when nothing is building the pane falls back to the newest run (fix 2's
  behaviour) — **superseded by fix 4**, which anchors on the newest run's last
  *finished* row instead (the root only wins when that run has no finished row
  yet).  Notes: `… N earlier runs` and, when a window has content on both
  sides, `… N more runs`.
* **Narrow terminals** (`< MIN_SIDE_BY_SIDE_WIDTH`, 100 cols) stack the two panes
  instead of sitting them side by side, so neither the log nor the tree is lost.
  Below `MIN_SPLIT_HEIGHT` (6 rows) the header alone is rendered.

### Verification

* `tests/unit/test_run_tree_rich.py` — `TestLiveStatusLine` asserts the
  scrollback keeps 500 lines and drops the oldest, that stderr/bad-word lines are
  red, and that a new tool keeps history and adds a separator; `TestLiveLayout`
  asserts the wide layout really is side by side (the log's separator and the
  tree's first row share a row), that a narrow terminal still shows both panes,
  and that a tall run's `⏳ Stack lights` is on screen with `… 3 earlier runs`.
* Live PTY run of `ProcessingView` under a real `Live` (120x30): no traceback and
  no Rich internal error; the final screen still reads
  `✓ Auto-processing: done` with both panes.

## Fix 4: the tree never saw a *running* task (the pane looked frozen)

Fix 3 anchored the tree pane on the `⏳` row — but the view never received a
snapshot that contained one, so that anchoring was dead code:

* `Processing.add_result()` publishes `EVENT_STAGE_RESULT` with
  `pt.record_result(result)` + `pt.run_tree().to_plain()`, i.e. the snapshot is
  taken when a task has **just finished**: nothing in it is running.
* `doit.py:MyReporter.execute_task()` called `pt.task_started(task)` (which does
  create the in-memory `RUNNING` placeholder) but published `task.started`
  **without** a run snapshot, so the placeholder never left the process.

Two user-visible symptoms, both reproduced:

1. `run_tree_to_rich` never drew a `⏳`, and `_building_index()` always returned
   `None` — the run being worked on was not even in the tree.
2. With no anchor, the fallback showed the newest run from its **top**; a real
   run's tree is taller than the pane, so the pane stayed on the finished
   stages and never moved — "it fills the screen once and never changes again".

### Approach — publish the running snapshot, and follow progress

```
task.started  →  {..., "run": <pt.run_tree().to_plain()>}      ← new: task is ⏳
stage.result  →  {..., "run": <snapshot after record_result>}   ← nothing running
```

* **`src/starbash/doit.py`** — `EVENT_TASK_STARTED` carries the fresh run
  snapshot taken right after `pt.task_started(task)`.  It is the *only* snapshot
  that can contain a running node, and it is what makes the CLI tree (and any
  future consumer, e.g. a GUI tree rebuild) able to see the current task.
* **`src/starbash/commands/process.py`** — the pane follows the run that holds a
  `running` node (`_building_index()`, now newest-first so a run whose last task
  was never recorded cannot pin the pane), else the newest run;
  `_RunWindow._anchor_row()` prefers the `⏳` row and otherwise anchors on the
  run's **last finished** row (`✓`/`Ø`/`✗` — never `⊘`, excluded stages are not
  progress and usually sit *below* the work).  Anchoring on progress instead of
  the root is what stops the pane snapping back to the finished top in the gap
  between two tasks.

### Verification

* New tests — `test_emit_hooks.py::test_my_reporter_publishes_the_started_task_as_running`
  (the payload's snapshot has `status == "running"`) and, in
  `test_run_tree_rich.py`, `test_the_reporter_starting_a_task_lands_the_running_task_in_the_tree`
  (reporter → real `ProcessedTarget` → view renders `⏳`),
  `test_tree_pane_stays_where_progress_was_between_tasks` and
  `test_the_newest_running_run_wins_over_a_stale_one`.  The first two were
  confirmed to **fail** with the `run` key removed.
* Live PTY run (120×30) driven by the real producer path (`MyReporter.execute_task`
  + the snapshot `Processing.add_result` publishes, 12 stages): `⏳` rows in the
  stream **0 → 28**, no traceback, final screen all `✓`.
* Trade-off: in a degenerate 10-row terminal the run's root can scroll off; the
  header above still names the target being worked, and
  `test_one_run_taller_than_its_region_still_renders` now asserts the anchored row
  rather than the root.

## Fix 5: the last core-side display (`Starbash.reindex_repo`)

Fix 1 removed the *tool's* Rich displays, but `Starbash.reindex_repo()` /
`reindex_repos()` still drew their own `rich.progress.track()` bars.  Those render on
Rich's **global** console while a run's `ProcessingView` lives on `starbash.console`,
and Rich only nests `Live`s that share one console — so the pre-run re-index had to be
passed a `show_progress=False` flag to keep quiet during a run.

That flag was scaffolding around a core that draws to the terminal, and it did not even
hold for the GUI: *Re-index* and *Add repository* call the same methods with the default
`show_progress=True`, so a worker thread opened a Rich display on the process's stdout
while the Repositories page was already drawing the very same scan from the events.

### Approach

Delete the bars *and* the flag.  The events were already there — `reindex.progress` per
repo (a first `0/N`, then one every 25 files) and `reindex.finished` per repo — and three
observers already rendered them (the CLI's `ProcessingView`, the GUI's processing page,
the GUI's Repositories page).  Only `sb repo reindex` and `sb repo add` had no observer of
their own, because they leaned on the `track()` bar, so they get one:
`src/starbash/ui/cli.py::ReindexView`.

* `Starbash.reindex_repo()` / `reindex_repos()` — plain loops that only publish; no
  `rich.progress` import left in `app.py`.
* `ReindexView` — one `Live` (the console's only one) plus a determinate `Progress` task
  per repo, dropped and re-added as each repo's first event arrives so folders of very
  different sizes are not summed into one meaningless total.  Each finished repo leaves a
  plain `Indexed N file(s) in <repo>` line, printed as it happens.  On a pipe, a redirect
  or a dumb terminal it creates no `Live` at all, so those lines are the whole output —
  the fallback `ProcessingView` makes via `supports_live_display()`.
* `commands/repo.py` — `reindex` (all repos and one repo) and `add` wrap their scan in the
  view, drawing on `starbash.console` (the console `Starbash.__init__` installs, the same
  one `add_local_repo()` prints to, so its lines land above the bar).
* `Processing.reindex_if_needed()` — just calls `reindex_repos()`.

### Verification

* `tests/unit/test_reindex_view.py` (7 tests) — the bar follows the events and shows the
  current repo, it resets per repo (the finished repo's task is gone, not left at 100%),
  each finished repo leaves its line, a pipe gets exactly those lines and no escape codes,
  `finish()` replaces the bar with the totals, unrelated events are ignored, and the view
  stops observing after its block.
* `test_app.py::test_the_core_draws_no_progress_bar` — captures stdout across a real
  `reindex_repos()` and fails on the `━` glyph, so a core-side `track()` cannot come back.
  Checked to have teeth: a direct `track()` under the same capture writes
  `Indexing … ━━━ 100%`.
* `test_app.py::test_reindex_repos_reports_progress_on_the_event_bus` — asserts the
  progress/finished events the observers depend on really are published (replaces the two
  tests that mocked `track()` to check the `disable` flag).
* Trade-off: on a terminal `sb repo reindex` looks the same as before (a bar, plus a
  result line per repo); on a pipe the old single flat `track()` line per repo becomes
  `Indexed N file(s) in <repo>`, which is the wording the GUI already shows.
* Verified live under a PTY (not just asserted through a string console): the result
  lines print *above* the frame, the two-line bar frame is erased
  (`\r\x1b[2K\x1b[1A\x1b[2K`) and succeeded by the one-line totals frame, the cursor is
  restored and no bar is left behind.  Two things that only show up in a *rendered*
  run: the per-repo line's number and URL carry Rich's highlighter codes (so the
  no-`track()` test asserts on the `━` glyph, and the CLI test strips ANSI before
  matching), and `Live` nests `console.print` output correctly only because the view
  draws on the same console it owns.

## Fix 6: a built-in tool's own log lines bypassed the bus (GraXpert, python stages)

### Problem

The observers above all render from `starbash.events`, and an *external* tool's output
reaches them because `tool_run_streaming` captures its stdout/stderr.  A tool implemented
as Python *inside* Starbash had no such capture: GraXpert's built-in `api_run` logs with
the module-level helpers (`logging.info`, so its records land on the **root logger**),
which meant the GUI showed nothing — and the root logger's `RichHandler` drew every line
*straight onto the console*, i.e. over the live display the observer owns.  The same was
true of a `tool.name = "python"` stage (used by `crop`, `report_registration`,
`stack_dual_duo`, `stack_single_duo`, …).

Measured live under a PTY (real `ProcessingView` + `setup_logging`), a python stage gave
`tool events published: NONE`, and the script's line arrived as a frame drawn by the root
handler — the tear Fix 3 had removed for external tools.

### Approach — `tool_run_in_process()`

`src/starbash/tool/base.py` gains a context manager that makes an in-process tool look
exactly like a streamed one: `tool.started` / `tool.output` / `tool.progress` /
`tool.finished` on the bus, plus the raw lines in `log_out`.  It installs

* a `_ToolLogForwarder` (a `logging.Handler` on the root logger) that republishes each
  record as one `tool.output` line (parsing a percentage into `tool.progress`, tagging
  `WARNING`+ as `stderr` so the panes colour it), and
* a `_ToolSourceFilter(invert=True)` silencer on every *existing* root handler, so the
  same lines cannot also be drawn directly beside the live display.

Which records count as "the tool's" is the one real design question, and the answer
differs per tool:

* **GraXpert** logs from its own package, so `source=os.path.dirname(graxpert.__file__)`
  matches on `record.pathname`.  A logger *name* cannot be used — the module-level
  `logging.info` helper creates the record on the root logger.
* **A python stage** emits from Starbash's own modules — the sandbox's `print` goes
  through `MyPrinter.write` → `logger.info("Script print: …")` in
  `starbash.tool.context`, and Siril commands log from `starbash.sim_siril` — so there is
  no directory to name.  `source=None` therefore means "every record emitted during this
  call is the tool's output", which also picks up the tool's own
  `Executing python script …` line (it is what the stage is doing).

Because `print` already funnels into a log record, nothing needed to change in the sandbox
or `MyPrinter`: hooking the *record* stream covers prints, the injected `logger`,
`sim_siril` and Starbash's own line in one place — a `print` hook would have seen only the
first, and would also have fired on the TOML-expression path (`expand_context_unsafe`
calls the same `make_safe_globals`).

Nested runs are safe: each forwarder defers to one installed inside it
(`_owned_by_an_inner_run`), so a line is republished exactly once even when the outer call
reroutes everything.

### Verification

* Unit tests in `tests/unit/test_emit_hooks.py` (lifecycle/output/progress, stderr
  tagging, failure, "keeps the tool's lines off the console", handler restore, built-in
  GraXpert publishes its output, `source=None` reroutes everything, nested runs publish
  once, a python stage publishes both a `print` and a `logger` line).
* Falsified both halves by temporarily reverting the wrapper, then the silencer: the
  python-stage test reports `tool.output lines=0 drawn-on-console=4` without the fix and
  `lines=4 drawn=0` with it.
* Live under a PTY: `tool.started` + 4 × `tool.output` + `tool.finished`, **0** frames
  drawn by the root handler (was 3), with the script's line still on screen — drawn by
  `ProcessingView` from the bus.  GraXpert under the same harness reaches the live pane
  promptly, root handler draws **0**.

## Fix 7: the core's own bar (`Processing.progress`), and one bar that follows the phase

Fix 5 removed the last *core* bar drawn on Rich's global console, but `Processing`
still owned a `Progress`: the CLI handed it its own bar
(`Processing(sb, progress=view.progress)`), and with no bar supplied the core
started one of its own (`Progress(console=starbash.console)` + `start()`).
`MyReporter` then wrote *display strings* into it per task (`Subtask: <title>`)
and advanced it on every completion.

### Problem

* **The GUI got a display it never asked for.** Its worker builds a `Processing`
  inside a `QThread` and renders the run itself from the bus, so it passed no
  `progress=` — `_owns_progress` was true and the worker started a Rich `Live` on
  `starbash.console`: a second renderer painting the process's stdout while the Qt
  window drew the very same run.
* **The core decided a presentation string.** `MyReporter` relabelled a
  *caller-owned* bar with `Subtask: <title>`; that string existed only for a bar
  the core no longer draws, and it was the sole reason `Progress` sat in
  `ProcessingLike`'s protocol.
* **There were two bars for one job.** `Processing.run_all_stages()` created
  "Processing targets..." and `doit.py` maintained a second, per-task bar next to
  it — with the per-task relabelling making it read as a third thing.

### Approach — publish the size of the run; the view owns the one bar

Delete the core's bar and give the view the *numbers* it needs instead.

* `Processing.__init__(sb)` — the `progress` parameter, `self.progress`,
  `_owns_progress` and the matching `start()`/`stop()` are gone; `close()` only
  unsubscribes. `ProcessingLike.progress` leaves the protocol.
* `MyReporter` — `job_task`, the `Subtask: …` label update and `advance()` are
  gone. `execute_task()` still publishes the running-run snapshot, and the
  task's own name already travels on `task.started`, so both front ends name the
  running task from that event (`ProcessingView._task_caption`, the GUI's row).
  The completion path still calls `add_result()`, now guarded by
  `if self.processing and task.meta` — which is all that guard ever meant.
* **`EVENT_TASKS_PLANNED`** (`tasks.planned`, `{tasks}`) — new, published by
  `MyReporter.initialize()`. Every loaded task ends with exactly one
  `task.finished` (one doit decided not to run reports through
  `skip_uptodate`/`skip_ignore`), so this is the denominator a bar needs.
* `EVENT_PROCESS_TARGET` / `EVENT_RUN_STARTED` now carry `index` alongside
  `total`, so an observer measures planning from the boundaries the core already
  publishes instead of counting them itself.
* **`EVENT_MERGE_PROGRESS` / `EVENT_MERGE_FINISHED`** (`merge.progress`,
  `merge.finished`) — new, published by `doit.merge_to()`, which used to wrap its
  symlink loop in `rich.progress.track()`: a `Live` on Rich's *global* console,
  i.e. exactly the Fix 5 bug class (a second renderer painting over the run view,
  plus a display a GUI worker never asked for).  `merge.progress` reports the
  counts (`{name, done, total}`) every 25 frames and always on the last one, the
  way the reindex scan does; `merge.finished` (`{name, files}`) closes the phase.
  The GUI needs no handler — its row already names the task and the tool — and
  `doit.py` no longer imports Rich at all.  The two *publishers* are both input
  collectors: `tool/siril.py::link_or_copy_to_dir()` (which had the identical
  `track()` bar, on **every** Siril stage) publishes the same pair — one concept,
  "this stage is collecting its inputs", so one event kind and one phase.
* **`ProcessingView` owns the bar**: explicit columns
  (`TextColumn`/`BarColumn`/`MofNCompleteColumn`/`TimeElapsedColumn`) and one
  task, aimed at a *phase* —

  | phase | description | counts from |
  |---|---|---|
  | (none) | `Starting...` | indeterminate (pulses, `0/?`) |
  | `indexing:<repo>` | `Indexing files` | `reindex.progress` `done`/`total` |
  | `planning` | `Planning` | `process.target` `index`/`total` |
  | `tasks` | `Processing tasks` | `tasks.planned`; `+1` per `task.finished` |
  | `merge:<name>` | `Collecting inputs` | `merge.progress` `done`/`total` |

  `_set_bar(phase, description, completed, total)` resets the bar only when the
  *phase changes*, so a phase keeps one `TimeElapsedColumn` clock while its
  events stream in; a phase that reports no total leaves the previous one in
  place (Rich cannot move a task back to an unknown total, so the bar simply
  keeps pulsing), and `_advance_bar()` never passes the total, so a plan/event
  mismatch cannot draw past the bar's column.
* **A collection borrows the bar and hands it back.** `merge_to()` and Siril's
  `link_or_copy_to_dir()` both run *inside* a task (they collect the next stage's
  inputs before its tool starts), so
  `merge.progress` points the bar at the frames being collected while the caption
  keeps naming the running task; `merge.finished` then points the bar back at
  `tasks`, because that is what progresses for the (much longer) tool run that
  follows — leaving a full `Collecting inputs` bar up would read as done until
  the next phase.  The run's task counts therefore live in the view
  (`_tasks_done`/`_tasks_total`, set by `tasks.planned` and advanced per
  `task.finished`) rather than being read back off the bar, which some other
  phase may be holding.
* The caption keeps the *words* (`Indexing file:///img`) and the bar keeps the
  *numbers* (`12/40`): both used to print the same counts on adjacent lines.

### Verification

* `tests/unit/test_run_tree_rich.py::TestLiveStatusLine` — the bar counts the
  tasks of the *current* run (not the whole job), it pulses until a phase knows
  its size, it takes planning from the target boundaries, it puts reindex counts
  on the bar rather than in the caption, a task event past the plan cannot
  overflow it, and one phase keeps one clock across its events.
* `tests/unit/test_doit.py::test_a_run_reports_one_finish_per_planned_task` — a
  **real** doit run (`load_doit_config` installs `MyReporter`, so this drives the
  actual reporter rather than a mock): `tasks.planned` says 2, exactly two
  `task.finished` events follow, and one of them is the `Current` (up-to-date)
  skip — i.e. the denominator stays reachable when doit has nothing to do.
* `tests/unit/test_emit_hooks.py::test_my_reporter_publishes_the_size_of_the_run`
  and `…::test_a_skipped_task_still_reports_task_finished`.
* `tests/unit/test_doit.py::TestMergeToReportsProgress` — a **real** `merge_to()`
  call over 26 frames: the bus sees `merge.progress` at 0, 25 and 26 (the
  interval *and* the last frame, so the phase never falls short of its total)
  then `merge.finished`, and the merged sequence really holds one symlink per
  input in collection order.
* `tests/unit/test_tool.py::TestLinkOrCopyToDir` — the same contract for Siril's
  collector: 26 frames report 0, 25, 26 then `merge.finished`, the links it claims
  really exist, and a re-run that meets its own links still counts every frame
  (the skip must not shorten the phase).
* `TestLiveStatusLine` — `test_a_merge_phase_borrows_the_bar_and_gives_it_back`
  (the bar shows `Collecting inputs 25/120` while the caption still names the
  running task, then returns to `Processing tasks 1/3` and continues to `2/3`
  rather than restarting at zero) and
  `test_an_empty_merge_leaves_the_task_counts_alone` (a sequence that matched
  nothing reports `0/0`, which takes the description but not the counts).
* `tests/unit/test_processing.py::TestProcessingOwnsNoDisplay` — a real
  `Processing(sb)` has no `progress` attribute at all, so the GUI cannot get a
  stray display; `test_run_boundaries_say_which_target_of_how_many` asserts the
  `(index, total)` pairs on both run-boundary events.
* `tests/unit/test_events.py::test_every_event_kind_is_exported_and_unique` — the
  new kind is in `__all__` and no two kinds share a string.
* `TestLiveLayout`'s crop-marker test now renders through `LiveRender` (what
  actually inserts the marker) and asserts no *whole row* reads `...`. Its old
  `"..." in row` form passed only because it rendered the layout directly, where
  Rich can never add the marker — it was vacuous, and the label `Starting...`
  would have tripped it.

### Risks / notes

* The bar measures a **phase**, not a stage: it deliberately collapses the run
  from "a whole job" to "this doit run's tasks", because that is the only size
  the core knows before the run starts. A target's own stage progress is on the
  status line (`stack: Stack lights · Siril 42%`) and in the tree.
* Between phases the bar resets rather than summing, so `MofNCompleteColumn`
  always refers to the phase named to its left.
* **One Rich bar outside the run is left, deliberately.**  After Fix 7 no
  `rich.progress.track()` call remains anywhere in `src/`; the only `Progress`
  widgets are the CLI's own (`commands/process.py`, `ui/cli.py`) — plus
  `publish/github.py::GitHubPublisher.publish()`, which opens one on
  `starbash.console` for site generation and is called **from the GUI's publish
  job** (`ui/qt/jobs.py::publish_github_job`), i.e. the Fix 5 bug class in the
  publish subsystem.  Out of Fix 7's scope (the *run* bar), and left visible here
  rather than half-fixed: the fix is to give `publish()` a reporter the way
  `github_publish.publish_site()` already has one, and let `sb publish` draw its
  own bar.  Note `github_publish.py` — the sign-in/upload sequence the GUI shares
  — is already Rich-free.

## Files

* `src/starbash/tool/base.py` — drop `ToolLiveDisplay`, `Tool._active_display`,
  `Tool.manages_own_progress` and the `Live`/`nullcontext` block in `Tool.run`;
  keep publishing events.
* `src/starbash/tool/rcastro.py` — drop the now-meaningless
  `manages_own_progress = True`.
* `src/starbash/commands/process.py` — event-smart `ProcessingView`
  (spinner/status + `_tool_label` helper), the `Layout` split in `_render()`, the
  `_LogTail` scrollback pane and the `_RunWindow` tree pane (which replaced
  `_RunTail` in Fix 3), plus `_building_index()` and the `LOG_LINES` /
  `MIN_SIDE_BY_SIDE_WIDTH` / `MIN_SPLIT_HEIGHT` sizing constants.  Fix 4 made the
  window follow the *running* run (or, between tasks, the row where progress was)
  instead of the newest run's top.  Fix 7 added the view's own phase bar
  (`_set_bar()` / `_advance_bar()` and the `Progress` column list), so the CLI no
  longer passes a bar into `Processing`.
* `src/starbash/processing.py` (Fix 7) — `Processing` has no `progress` at all:
  the `progress=` parameter, `self.progress`, `_owns_progress` and the
  `start()`/`stop()` pair are gone, as are the "Processing targets..." /
  "Processing: <target>" bars in `run_all_stages()` (which now enumerates its
  targets so the run boundaries can carry `index`).
* `src/starbash/processing_like.py` (Fix 7) — the `progress: Progress` member
  leaves the protocol.
* `src/starbash/doit.py` — `MyReporter.execute_task()` publishes the live run
  snapshot (with this task `running`) in the `task.started` payload (Fix 4).
  Fix 7 removed its bar work (`job_task`, the `Subtask: …` relabelling and the
  `advance()`), so it now only publishes — and `initialize()` publishes the new
  `tasks.planned` size.  Fix 7 also took the `track()` bar out of `merge_to()`
  (the last Rich display in the core): it publishes `merge.progress` /
  `merge.finished` instead, every 25 frames and on the last one.
* `src/starbash/tool/siril.py` (Fix 7) — `link_or_copy_to_dir()` had the identical
  `rich.progress.track()` bar (`Linking input files...` / `Copying input files
  (fix your OS settings!)...`), drawn for **every** Siril stage; it now publishes
  the same `merge.progress` / `merge.finished` pair (phase name = the directory it
  fills) and the no-symlinks hint is a log line.  `import rich.progress` is gone.
* `src/starbash/events.py` — documents that snapshot on `EVENT_TASK_STARTED`,
  adds `EVENT_TASKS_PLANNED` (`tasks.planned`), the merge pair
  (`merge.progress` / `merge.finished`), and documents the `index` that the
  run-boundary events carry (Fix 7).
* `src/starbash/rich.py` — render run-tree log lines as literal `Text` so a tool
  line containing `[` cannot raise `MarkupError` inside the live refresh thread
  (which would freeze the display); `log_line_to_text()` (Fix 3) reuses that
  hardening for the log pane, adding the stderr/`BAD_WORDS` red styling.
* `src/starbash/app.py` — Fix 5: `reindex_repo()` / `reindex_repos()` only *publish*
  (`reindex.progress` / `reindex.finished`) any more; the `track()` bars and the
  `show_progress` flag that silenced them are gone.
* `src/starbash/ui/cli.py` (Fix 5) — `ReindexView`, the CLI's observer for a bare repo
  scan (a per-repo `Live` bar; plain per-repo lines when the sink cannot animate), used
  by `sb repo reindex` and `sb repo add` in `src/starbash/commands/repo.py`.
* Tests: `tests/unit/test_run_tree_rich.py` (`TestLiveStatusLine` for fix 1,
  `TestLiveLayout` for fix 2 — it renders at a given terminal size and asserts
  the row count never exceeds it, that no `...` is drawn and that the status
  stays on the first row with 200 runs).  Fix 5 adds
  `tests/unit/test_reindex_view.py` and the two reindex tests in
  `tests/unit/test_app.py`.  Fix 7 adds six bar tests to `TestLiveStatusLine`,
  `tests/unit/test_processing.py::TestProcessingOwnsNoDisplay` (plus the
  run-boundary `index` assertions), the two event-hook tests in
  `tests/unit/test_emit_hooks.py`, the real-doit
  `tests/unit/test_doit.py::test_a_run_reports_one_finish_per_planned_task`, and
  `tests/unit/test_events.py::test_every_event_kind_is_exported_and_unique`.
* `src/starbash/tool/base.py` (Fix 6) — `tool_run_in_process()`, `_ToolSourceFilter`,
  `_ToolLogForwarder` and the `_active_forwarders` nesting rule.
* `src/starbash/tool/graxpert.py` (Fix 6) — the built-in `api_run` runs inside
  `tool_run_in_process(..., source=<the graxpert package>)`.
* `src/starbash/tool/python.py` (Fix 6) — `_run` wraps the sandbox in
  `tool_run_in_process(f"python {script_filename}", source=None, log_out=log_out)`,
  which also honours the `log_out` that the old FIXME comment said it ignored.

## Risks / notes

* **The CLI run bar is a *phase* bar (Fix 7).** A run's bar restarts at each
  phase (`Starting...` → `Indexing files` → `Planning` → `Processing tasks`), and
  its `MofNCompleteColumn` always refers to the phase named beside it — there is
  deliberately no "percent of the whole job", because the job's size is unknown
  until the last target's tasks are planned.  An observer that wants a per-stage
  percentage still gets it from `tool.progress` / the run snapshot.
* Tools run without a live view (GUI worker thread, `sb process doit`) no longer
  draw a terminal spinner; their output still reaches the log file, the logger
  and the event bus.
* `Tool.manages_own_progress` disappears; nothing else consumed it.
* The live region is now exactly terminal-sized, so Rich scrolls the terminal one
  row per frame (its standard fullscreen-`Layout`-in-`Live` behaviour).  This is
  stable — the shape does not vary frame to frame — unlike the previous growth.
* **Fix 6 reroutes a *window*, not a message pattern.**  For a python stage every
  record emitted while the script runs (including Starbash's own) becomes tool output and
  stops reaching the existing root handlers.  That is deliberate — it is what makes the
  stage legible in the run tree — and the only root handler in a CLI run is the console
  `RichHandler` (there is no file handler that could lose lines); `log_out` still receives
  them, so the stage's log file is complete.  GraXpert keeps the narrower
  directory-scoped match, so Starbash's own messages are unaffected there.
