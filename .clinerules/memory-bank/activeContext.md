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
- **`sessions.telescop` is `NOT NULL`** while `filter`/`object` are nullable, so `_add_session` must always write a value (it uses `""` for "unknown").  `get_session()` only filters on a column when the candidate value is *truthy*, so an empty telescope means "match any" — that is what makes TELESCOP-less frames merge into the same rig's session instead of being split off.