# Active Context

## Current work focus

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