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
- **Publishing**: `sb publish` generates a GitHub Pages-compatible Jekyll site (Jinja2 + Pygal charts), and `sb publish github` uploads to `starbash-public`.  The upload sequence (sign in via device flow → check the Starbash GitHub App → create/verify the repo → upload blobs → commit → configure Pages) lives in the front-end-agnostic `src/starbash/publish/github_publish.py`; the CLI renders its `StepReporter` with Rich and the GUI drives a progress bar and a step-by-step setup dialog from it (`doc/plans/gui-github-publish.md`).  The GUI's *Publish to GitHub* handles the two first-run states itself — `needs_sign_in` / `needs_install` come back as *results*, the page runs the setup dialog, then re-runs the publish.  The GUI Publish page has no username field to fill in: the account is GitHub's (`GitHubCredential.login`, recorded at install/publish time and read back by `github_identity_job`) and *Open in browser* only lights up after a publish returns the `https://<owner>.github.io/starbash-public/` Pages URL.
- **External tools**: Siril (Flatpak stdin script), GraXpert (CLI), Starnet2, rc-astro (`bxt`/`nxt` with JSON progress streaming), Python (RestrictedPython sandbox).
- **Missing-tool warnings with severity + ignore** (`doc/plans/tool-warnings.md`): `ToolSeverity` / `ToolStatus` / `missing_tool_statuses()` in `src/starbash/tool/` drive a severity-matched startup log line in the CLI (`Tool.preflight()`) and dismissible per-tool bars in the GUI (`ui/qt/widgets/tool_warning.py`), whose *Ignore* button persists `tool.<key>.ignored = true` to the user config (and therefore silences the CLI too). StarNet detection also validates the configured `starnet_exe` (a dangling path counts as missing) — a non-empty Siril setting alone used to report StarNet as available, so removing `starnet2` warned nobody.
- **Desktop GUI** (`sb gui`, `feat-gui` branch): PySide6 app providing Dashboard, Sessions (filter/browse/export + FITS & raster preview), Masters, Targets (narrow target picker whose single column stretches to the scrollbar + a `Sessions`-then-`Stages` explorer tree of stage toggles, overridable recipe parameters and per-session calibration-master selection via a radio `MasterPicker`, with unsaved-change protection and clickable recipe/folder links plus hover-previewable master frames), live Processing (task tree with per-task collapsible Log/Out nodes, underlined file/recipe links, closable, movable (drag its title row) and user-resizable hover previews + streamed log + progress), Repositories (add/remove/re-index with live progress), Publish (local site) and Settings + first-run wizard. PySide6 is a normal dependency; the CLI never imports Qt. Backed by the new `starbash.events` bus and `starbash.interaction` protocol.
- **Targets page drives `sb select`** (`doc/plans/targets-selection-sync.md`): the
  target list always shows every processed target, pre-highlights the rows the
  selection names (every row when no target filter is set, since "no filter" means
  every target is in effect), and writes a click straight back through
  `Selection.set_targets()` — plain click = only that target, Ctrl+click = toggle —
  so the CLI and the Sessions page stay in step with no Save button.  The explorer
  is shown only while exactly one row is highlighted; otherwise the right column
  carries a hint and nothing stale stays loaded.

- Image previews decode on a worker thread and show a rotating-arc `BusyIndicator`
  (`ui/qt/widgets/busy_indicator.py`) over the pane while loading, so selecting a big
  FITS frame no longer freezes the window.
- **Structured per-session master selection** (`doc/plans/session-masters.md`):
  `sessions.toml` records `[sessions.masters.<type>]` as `selected` +
  `selected_by` (`"auto"`/`"user"`) plus a `[[…candidates]]` table per scored
  master, carrying typed evidence (gain/temp/time/instrument/camera/dimensions/
  filter match flags and deltas) instead of a `# reason` comment. `score.py`'s
  `ScoredCandidate` emits it (`details` + `to_toml_table()`);
  `ProcessedTarget.session_options()` / `save_master_selections()` read/write it
  (legacy `used`/`excluded` arrays still parse); and
  `Processing._resolve_input_master()` honours a `selected_by = "user"` pick on
  the next run, falling back to the top scorer if that master is gone.
- **Auto re-index before a run** (`doc/plans/` — see `activeContext.md`): `Processing.reindex_if_needed()`
  scans the user's image folders before planning (opt-out via the `reindex.auto`
  preference + GUI Settings checkbox), reusing the `reindex.progress` /
  `reindex.finished` events that both front ends already render.
- **Run-status vocabulary** (see `activeContext.md` → *up-to-date skips are not
  failures*): doit's up-to-date skip (`success=None`) is reported as **up-to-date**
  everywhere — the GUI Processing caption (`ResultSummary`, which never counts it
  as a failure), the GUI/CLI run-tree status words and the CLI's flat results
  table — while `run-log.toml` keeps the stable `"skipped"` value.
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

Alpha `v0.3.1` (tag `90529fe`, 2026-08-31); `main` has moved well past the
`d9eb338` noted here originally — the GUI work
(including the split live display: tool log pane + run tree), the missing-tool
warning model, the real GitHub publish flow, and the **Targets explorer**
(narrow target picker + `Stages`/`Sessions` tree + calibration `MasterPicker`)
with the **structured `sessions.masters` schema** that makes a user's master pick
authoritative on re-run, and now the **Targets page editing `sb select`** (its
highlighted rows *are* the selection, and the explorer appears only for a single
target). OSC workflows are the supported path; the R3 per-frame
registration reporting generalization is the other recent thread. The Memory
Bank was initialized on top of `21dac19` and extended since.

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