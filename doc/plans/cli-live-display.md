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
* Progress bars: unchanged `Progress` shared with `Processing`
  (`Processing(progress=view.progress)`).

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
│ ███████████░░░░░░░░░░░░░  calibrate 42%                     │  + progress bars
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
  instead of the newest run's top.
* `src/starbash/doit.py` — `MyReporter.execute_task()` publishes the live run
  snapshot (with this task `running`) in the `task.started` payload (Fix 4).
* `src/starbash/events.py` — documents that snapshot on `EVENT_TASK_STARTED`.
* `src/starbash/rich.py` — render run-tree log lines as literal `Text` so a tool
  line containing `[` cannot raise `MarkupError` inside the live refresh thread
  (which would freeze the display); `log_line_to_text()` (Fix 3) reuses that
  hardening for the log pane, adding the stderr/`BAD_WORDS` red styling.
* Tests: `tests/unit/test_run_tree_rich.py` (`TestLiveStatusLine` for fix 1,
  `TestLiveLayout` for fix 2 — it renders at a given terminal size and asserts
  the row count never exceeds it, that no `...` is drawn and that the status
  stays on the first row with 200 runs).

## Risks / notes

* Tools run without a live view (GUI worker thread, `sb process doit`) no longer
  draw a terminal spinner; their output still reaches the log file, the logger
  and the event bus.
* `Tool.manages_own_progress` disappears; nothing else consumed it.
* The live region is now exactly terminal-sized, so Rich scrolls the terminal one
  row per frame (its standard fullscreen-`Layout`-in-`Live` behaviour).  This is
  stable — the shape does not vary frame to frame — unlike the previous growth.
