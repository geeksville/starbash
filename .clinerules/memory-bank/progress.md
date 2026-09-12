# Progress

## What Works

- **Core CLI** (`sb` / `starbash`, Typer + Rich): `user`, `repo`, `select`, `info`, `process`, `publish` subcommands all registered and functional.
- **Repo/config layer**: local and remote (HTTP/GitHub) repos, `pkg://defaults`, recipe repo versioning + local submodule fallback, `[import]` support, merged MultiDict view.
- **Data layer**: SQLite `repos` / `images` / `sessions` tables; FITS indexing with JSON metadata blob, whitelist filtering, malformed-header skip, Dwarf3 header extension.
- **Application context**: `Starbash` context manager with analytics (Sentry), error remapping (`UserHandledError` / `NonSoftwareError`), OS init.
- **Selection & filtering**: target/date/telescope/filter/imagetyp selection persisted to user config; `sb select` + tab completion.
- **Processing pipeline**: doit task graph from TOML `[[stage]]` recipes; per-session and per-input multiplexing; `after` (regex) dependency wiring; `config_changed` fingerprinting for recipe/parameter invalidation.
- **Calibration & auto-process**: automatic master bias/dark/flat generation (scored by gain/date/temperature), `sb process auto` multi-session OSC stacking.
- **OSC stacking recipes**: `stack_osc` (basic), `stack_single_duo` (Ha/OIII), `stack_dual_duo` (Sii/Ha/OIII), crop, background elimination (GraXpert), star removal (Starnet2).
- **Per-frame registration reporting**: `.seq`/conversion parsing (`import_registration.py`) + atomic `Database.update_images_metadata()` (FWHM, Amplitude, Roundness, Background, Stars).
- **Processed-target persistence**: split `.starbash/main.toml` / `about.toml` / `sessions.toml` layout; `about.generated_at` + `schema_version = 1`.
- **Publishing**: `sb publish` generates a GitHub Pages-compatible Jekyll site (Jinja2 + Pygal charts), and `sb publish github` uploads to `starbash-public`.
- **External tools**: Siril (Flatpak stdin script), GraXpert (CLI), Starnet2, rc-astro (`bxt`/`nxt` with JSON progress streaming), Python (RestrictedPython sandbox).
- **Desktop GUI** (`sb gui`, `feat-gui` branch): PySide6 app providing Dashboard, Sessions (filter/browse/export + FITS & raster preview), Masters, Targets (per-target options tree: stage toggles + overridable recipe parameters, with unsaved-change protection, a target list that defaults to ~2/3 of the page width, and clickable recipe/folder links), live Processing (task tree with per-task collapsible Log/Out nodes, underlined file/recipe links, closable hover previews + streamed log + progress), Repositories (add/remove/re-index with live progress), Publish (local site) and Settings + first-run wizard. PySide6 is a normal dependency; the CLI never imports Qt. Backed by the new `starbash.events` bus and `starbash.interaction` protocol.
- Image previews decode on a worker thread and show a rotating-arc `BusyIndicator`
  (`ui/qt/widgets/busy_indicator.py`) over the pane while loading, so selecting a big
  FITS frame no longer freezes the window.
- **Type checking covers `src/` *and* `tests/`**: `just lint` runs `ruff check --fix`,
  `ruff format` and `basedpyright` over both trees (0 errors).  `Starbash.__exit__`
  propagates exceptions under pytest (a mocked `analytics_exception` used to suppress
  them), so tests can no longer pass vacuously.


## What's Left to Build

- **Complete R3 migration** (in progress): route all three OSC stacking variants through `report_registration.toml`, remove `_update_ha_registration_metrics()` from `recipes/osc.py`, confirm per-variant `.seq` basenames (Phase 0 in `doc/design/report.md`).
- **Merge `feat-report2`** branch WIP ("report2 plan", "wip") into `main`, or decide against it.
- **Mono-camera workflows** (currently OSC-only).
- **Drizzle by default** (currently opt-in/disabled; "uses LOTS of disk space").
- **Recipe `[import]`/inheritance** to eliminate copy-paste across OSC recipes.
- **Per-frame report regeneration** so users can reprocess with different culling thresholds.
- **Recipes writer's guide** doc.
- **Misc uncheckmarked TODO.md items**: private equipment list, readable per-run/user summary reports + activity calendar, `.sbignore` support, color balance/correction stage, pixelmath merge, parallel doit execution, cache size limit, IPFS sharing, master relative path by camera ID, etc.

## Current Status

Alpha `v0.3.1` (tag `90529fe`, 2026-08-31), plus one commit on `main` (`21dac19` "fix lint"). OSC workflows are the supported path. Active development is on generalizing per-frame registration reporting across stacking variants (R3). The Memory Bank has been initialized on top of this commit.

## Known Issues

- Session ↔ frame relation is not stored explicitly in the DB; frame lookup reconstructs from session criteria (date range, target, filter, telescope, imagetyp). This is documented as a limitation in `doc/design/report.md`.
- `ProcessedTarget` only fully supports targets, not masters (FIXME in docstring); generated master metadata lives beside the master file.
- Recipe Python is still broadly unsafe (RestrictedPython `my__import__` allows all imports — "FIXME very unsafe").
- `tool_run_streaming` runs via `subprocess.Popen(shell=True)` — shell injection risk is inherent to the current tool invocation model.
- Stale `fixme-ai ... fwhm.md` comment in `recipes/osc.py` pending the R3 cleanup (mapping ownership to the new stage).

## Evolution of Project Decisions

- **Recipes moved out of the Python package** into a separate `starbash-recipes` GitHub repo, fetched by version tag with a local git-submodule fallback.
- **DB approach evolved** from glob-based file scanning (then TinyDB) to FITS-metadata-driven SQLite (`images` + `sessions` + `repos`).
- **doit selected** as the build/task engine (replacing hand-rolled dependency logic); `doit.db` relocated to the app cache dir.
- **Processed-target config split** from a single `starbash.toml` into `main.toml` / `about.toml` / `sessions.toml` under `.starbash/` (alpha 3).
- **Reporting generalized** from a hardcoded, Ha-only inline function toward a shared TOML `report_registration` stage usable by all stacking variants (R3, in progress).
- **Security hardening incremental**: `eval()` → RestrictedPython sandbox with a guarded globals policy (still permissive).
- **Tool layer expanded** from Siril-only to GraXpert, Starnet2, rc-astro (`bxt`/`nxt`), and sandboxed Python.
- **Publishing added** (alpha 3) as an optional GitHub Pages output path.