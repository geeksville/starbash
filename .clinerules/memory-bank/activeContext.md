# Active Context

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
  default as the starting value.
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