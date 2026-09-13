# Active Context

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
  which parses stdout for ≥10 rows containing `Success`.  Now
  `rich.supports_live_display(console)` gates the `Live`; when false,
  `ProcessingView` skips `Live` entirely and prints `rich.runs_to_table(...)` on
  `finish()` — a flat one-row-per-task table with plain status words
  (`Success`/`Failed`/`Skipped`/`Excluded`/…) plus a row for any task-less stage.
  Real terminals are unchanged (still the live tree).  Tests in
  `tests/unit/test_run_tree_rich.py` (`TestSupportsLiveDisplay`, `TestRunsToTable`,
  the dumb-sink `TestProcessingView` cases).

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


- **Targets page split defaults to a 66/34 layout** (`ui/qt/pages/targets.py`): the
  target list now starts at ~2/3 of the page width via `_TARGET_LIST_SHARE = 0.66`
  plus an explicit `QSplitter.setSizes(...)` (stretch factors 2:1). Regression
  covered by `tests/unit/test_targets_page.py`.
- **Analytics preference defaults centralized** (`src/starbash/analytics.py`): `DEFAULT_ANALYTICS_ENABLED = True` / `DEFAULT_ANALYTICS_INCLUDE_USER = False` plus `analytics_enabled(repo)` / `analytics_include_user(repo)` helpers. The core (`app.py`), GUI Settings page, first-run wizard and `sb user setup` all read through these now, so an unset preference is consistent. Fixes the GUI showing analytics *off* while the backend treated it as *on*.
- Split processed-target metadata into three files under `.starbash/`: `main.toml` (config/stages/masters/overrides), `about.toml` (generated report), `sessions.toml` (per-session processing state). See `src/starbash/processed_target.py`.
- Added `about.generated_at` / `schema_version` report metadata and `DATE-OBS` to persisted frame metadata (for publishing charts).
- Added publishing subsystem (`src/starbash/publish/`), `sb publish` command, Jekyll/Pygal templates for a GitHub Pages site.
- Added rc-astro (`bxt`/`nxt` JSON streaming), Starnet star removal, live Siril progress, automatic crop stage, and GitHub publishing with concurrent uploads (all in alpha 3).
- Added safe `config_changed` fingerprinting so recipe/parameter edits invalidate and rebuild dependent tasks.

## Next steps

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
