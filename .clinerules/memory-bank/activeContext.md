# Active Context

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
  `ProcessingView` (one shared `rich.live.Live` hosting the `Progress` bar and the
  tree); `rich.run_tree_to_rich()` renders `target → stage → task` with status
  glyphs, clickable output/recipe/config links and the log tail. `Processing`
  now accepts an external `Progress` so there is only one render loop.
- **GUI** — `ui/qt/pages/processing.py` builds the same nested tree from the
  plain `run` snapshots (`_render_run`), coloured by status.  There is **no
  separate log pane**: tool/log lines are appended live under the running stage
  node.  Master (calibration) runs get a descriptive label
  (`ProcessedTarget.run_label`, e.g. `Master flat_Ha · 2024-01-01 · canon`) and
  their root is **collapsed by default** (`RunTree.is_master`).  Stage rows come
  from the doit task list, **not** the target's `[[stages]]` config:
  `Processing._job_to_tasks` calls `pt.set_run_stages(tasks_to_stages(tasks))`,
  so only stages that actually produced a doit task appear.
- **Consumers migrated** — `ui/qt/services.py` (`load_targets`,
  `load_stage_options`, `save_stage_options`) and `publish/github.py` (`_targets`)
  now go through the model.
- Tests: `tests/unit/test_run_state.py`, `tests/unit/test_processed_target_model.py`,
  `tests/unit/test_run_tree_rich.py`; `test_emit_hooks.py`/`test_gui.py` updated.

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
- **Phase 7 (polish/docs)** — `tests/unit/test_gui.py` (27 tests, `gui` marker,
  offscreen), `tests/unit/test_targets_page.py` (11 tests) and
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
- **Tree rows carry their own vertical padding** (`QTreeView::item { padding: 4px 0; }`).
  The indicator is 16px but an unpadded tree row was only ~16px tall, so the stage
  checkboxes in the Targets list touched each other. A test measures the *rendered*
  row height against the indicator size read out of `theme.STYLESHEET`
  (`test_stage_rows_are_tall_enough_to_separate_their_checkboxes`) — it fails if the
  rule is removed, and applies the theme itself (`theme.apply_theme(qapp)`), since
  `test_targets_page.py` otherwise runs unstyled. Horizontal padding stays 0 so the
  indentation and checkbox inset are unchanged.
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

- Split processed-target metadata into three files under `.starbash/`: `main.toml` (config/stages/masters/overrides), `about.toml` (generated report), `sessions.toml` (per-session processing state). See `src/starbash/processed_target.py`.
- Added `about.generated_at` / `schema_version` report metadata and `DATE-OBS` to persisted frame metadata (for publishing charts).
- Added publishing subsystem (`src/starbash/publish/`), `sb publish` command, Jekyll/Pygal templates for a GitHub Pages site.
- Added rc-astro (`bxt`/`nxt` JSON streaming), Starnet star removal, live Siril progress, automatic crop stage, and GitHub publishing with concurrent uploads (all in alpha 3).
- Added safe `config_changed` fingerprinting so recipe/parameter edits invalidate and rebuild dependent tasks.

## Next steps

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
- Recipe `.seq` parsing lives in `src/starbash/siril/import_registration.py`; DB updates go through atomic `Database.update_images_metadata()`.

## Learnings and project insights

- `toml_repo` is an external/git-submodule package (`toml-repo/`); repo config suffix is `starbash.toml` (set in `starbash/__init__.py`).
- Recipes are versioned remote repos fetched from `https://raw.githubusercontent.com/geeksville/starbash-recipes/v${version}` with a local `starbash-recipes/` git submodule fallback during development.
- Session ↔ frame relation is NOT stored explicitly in the DB; frame lookup reconstructs from session criteria (date range, target, filter, telescope, imagetyp).