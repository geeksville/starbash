# System Patterns

## System architecture

Starbash is a Typer-based CLI that glues together four subsystems:

1. **Repo/Config layer** (`toml_repo` external package + `src/repo`): loads and merges TOML repos with precedence (last repo wins). Repos can be `file:///...` (input/master/processed/recipe trees), `pkg://defaults` (built-in config), or remote HTTP/GitHub (recipe repos). Supports `[import]` for TOML reuse. A `MultiDict` (`union()`) exposes merged values; `get(key, default)` reads the highest-precedence value.

2. **Data layer** (`src/starbash/database.py`): SQLite. Tables:
   - `repos` (id, url)
   - `images` (id, repo_id, path, date_obs, date, imagetyp indexed; all other FITS metadata as JSON) — path is relative to repo root; unique (repo_id, path).
   - `sessions` (aggregated by filter/imagetyp/object/telescop/exptime/date; one representative `image_doc_id` backpointer).
   - Row factory is `sqlite3.Row`. Search via `SearchCondition` objects (column_name, comparison_op, value).

3. **Processing pipeline** (`src/starbash/processing.py`, `stages.py`, `doit.py`, `filtering.py`): recipes are `[[stage]]` TOML entries turned into `doit` task graphs. `Processing` orchestrates: select sessions → build context → expand stages into tasks → run via `StarbashDoit`.

4. **Tool layer** (`src/starbash/tool/`): `Tool` base class + `ExternalTool` (probes PATH/common install dirs). Runners: Siril (Flatpak, stdin script), GraXpert (CLI), Python (RestrictedPython sandbox), rc-astro (`bxt`/`nxt` with `--json` progress streaming), Starnet. `tool_run_streaming` streams stdout/stderr with timeout and live Rich display.

## Key technical decisions

- **CLI-first, Typer + Rich**: `main.py` creates a `typer.Typer` app with rich markup; subcommands registered from `src/starbash/commands/`. `Starbash` is a context manager that handles logging, analytics, error remapping (OSError/SQLite errors → `NonSoftwareError`/`UserHandledError`).
- **Recipes as data (TOML), not code**: each `[[stage]]` declares `name`, `tool.name` (+optional `parameters`, `timeout`), `script` (inline) or `script-file`, `context`, `inputs` (with `kind`, `merge_to`, `after`, `requires`), `outputs`, `temporaries`, `priority`.
- **Context expansion**: `str.format_map` with a safe `_SafeFormatter` preserves unexpanded `{vars}`; restricted expression expansion uses RestrictedPython (`expand_context_unsafe`). Iterative expansion (up to 10 passes) supports nesting.
- **Stages multiplex per-session or per-input**: a stage with a `session` input creates one task per session; `multiplex` over a `job` input creates one task per input image. Task names append target (`_<target>`) and session id (`_s<id>`) and multiplex index (`_i<n>`).
- **Doit handles dependency/rebuild logic**: file deps from resolved inputs, targets from stage outputs, `config_changed` fingerprint for recipe/parameter edits (`_stage_fingerprint` hashes effective params, tool name, tool params, script content).
- **`ProcessedTarget`** wraps the target's output dir (`.starbash/main.toml`, `about.toml`, `sessions.toml` in the new split layout) and holds `default_stages` for sessionless tasks.
- **Masters are just another processing flow**: bias/dark/flat sessions processed individually (target=None), output to the master repo, `[stages]` gate them.

## Design patterns in use

- **Context manager lifecycle** everywhere: `Starbash`, `Processing`, `ProcessedTarget`, `Database`.
- **Lazy singleton-ish state** via module globals: `starbash.console`, `force_regen`, `verbose_output`, `process_masters`, `log_filter_level`; the `Aliases` singleton via `set_aliases`/`get_aliases`.
- **Context dictionary shared across stages**, with `_clone_context()` deep-copying per task but sharing `session` and `update_image_metadata` (the DB bound method) so mutations propagate.
- **Backpointers on TOML items**: stages carry `.source` (the repo they came from) so scripts can be resolved and attributed.
- **Exception taxonomy**: `UserHandledError` (clean message, exit code 1), `NonSoftwareError` (OS/db), `NonFatalException` (skip silently), `NotEnoughFilesError`/`FallbackToImageException` (skip or degenerate copy), `NoPriorTaskException` (missing `after` dependency).

## Component relationships

- `Starbash` owns `RepoManager`, `Database` (lazy), `Selection`, analytics.
- `Processing(ProcessingLike)` uses `Starbash` + `StarbashDoit`; creates one `ProcessedTarget` per target and per master.
- `ProcessedTarget` holds a `Repo` wrapper for `main.toml`, plus `about_config`/`sessions_config` for split metadata files, and a `ParameterStore` of user overrides.
- Stage → Tool via `tools` registry (`init_tools(prefs)` in `app.py`).
- `filtering.py` `_apply_filter` implements input `requires` kinds: `metadata`, `camera`, `unprocessed`, `filename`, `min_count`.

## Critical implementation paths

- **Auto-process path**: `sb process auto` → `Processing.run_all_stages()` → (`run_master_stages()` if `process_masters`) → for each target `_create_tasks` → `_job_to_tasks` (creates `ProcessedTarget`) → `_stages_to_tasks` → `_stage_to_tasks` (resolve inputs, build task dicts) → `_run_jobs` (doit runs `process_all`).
- **Stage exclusion flow** (common bug source): recipe `[[stage]]` has `name`; target `starbash.toml` `[stages].excluded` lists names to skip. `ProcessedTarget.__init__` reads them into `self.default_stages`; `remove_excluded_tasks()` filters tasks by matching `stage["name"]` against the excluded list. If exclusions "don't take", verify `default_stages` is populated before `remove_excluded_tasks()` runs.
- **Master selection/scoring**: `score_candidates()` in `score.py` (not named here beyond this) ranks candidate sessions by gain/date/temperature proximity (see `Starbash.guess_sessions`).
- **Per-frame FITS registration reporting**: `src/starbash/siril/import_registration.py` parses `.seq`/conversion files and updates image rows via `Database.update_images_metadata()` with whitelisted keys (FWHM, Amplitude, Roundness, Background, Stars).

## Important patterns & preferences (from AGENTS.md)

- Keep typing hints and docstrings; don't introduce new linter warnings.
- Tests assert on real resulting state, not just that a mock "was called".
- Rich markup on for Typer; SQLite row factory is `sqlite3.Row`.
- Use `paths.set_test_directories(...)` in tests for isolation.