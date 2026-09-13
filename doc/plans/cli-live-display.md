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

## Files

* `src/starbash/tool/base.py` — drop `ToolLiveDisplay`, `Tool._active_display`,
  `Tool.manages_own_progress` and the `Live`/`nullcontext` block in `Tool.run`;
  keep publishing events.
* `src/starbash/tool/rcastro.py` — drop the now-meaningless
  `manages_own_progress = True`.
* `src/starbash/commands/process.py` — event-smart `ProcessingView`
  (spinner/status/tail + `_tool_label` helper), the `Layout` split in `_render()`
  and the `_RunTail` region renderable.
* `src/starbash/rich.py` — render run-tree log lines as literal `Text` so a tool
  line containing `[` cannot raise `MarkupError` inside the live refresh thread
  (which would freeze the display).
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
