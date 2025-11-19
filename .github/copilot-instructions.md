# Copilot instructions for starbash

These rules help AI coding agents work effectively in this repo. Keep answers concrete and project-specific.

## Big picture
- **Starbash** automates and standardizes astrophotography workflows by organizing FITS image data, managing processing recipes via TOML "repos", and orchestrating external tools (Siril, GraXpert).
- **Entry point**: `starbash.main:app` is a Typer CLI application. Top-level commands: `select`, `info`, `process`, `repo`, `user`.
- **Core architecture**:
  - `starbash.main` — Typer CLI app with Rich markup, registers subcommand modules from `starbash.commands/`
  - `starbash.app.Starbash` — main application context manager, initializes database, repo manager, selection state, and analytics
  - `starbash.database.Database` — SQLite3-backed storage for FITS metadata (images table) and session aggregates (sessions table)
  - `starbash.selection.Selection` — persistent JSON-based state for filtering sessions by target, telescope, date range, filter, image type
  - `repo.manager.RepoManager` — separate package, loads/merges TOML repos with precedence rules, exposes `union()` (MultiDict) and `get()`
  - `starbash.tool` — tool runners for Siril, GraXpert, Python (RestrictedPython); handles safe template expansion
  - `starbash.paths` — centralized path management with test override support for config/data directories
  - `starbash.analytics` — optional Sentry.io integration for crash reports and usage analytics

## Data persistence and paths
- **User directories** (via platformdirs):
  - Config: `~/.config/starbash/` (or platform equivalent) — stores `starbash.toml` user preferences
  - Data: `~/.local/share/starbash/` (or platform equivalent) — stores `db.sqlite3` and `selection.json`
- **Test isolation**: `paths.set_test_directories(config_dir, data_dir, documents_dir_override=documents_dir)` overrides paths for test fixtures
- **Database schema**:
  - `images` table: stores FITS metadata as JSON in `metadata` column, indexed by `path`
  - `sessions` table: aggregates images by (start, end, filter, imagetyp, object, num_images, exptime_total)
  - Key constants defined in `Database` class: `EXPTIME_KEY`, `FILTER_KEY`, `START_KEY`, `OBJECT_KEY`, etc.

## CLI commands (via Typer)
- **select** — manage session filtering and display
  - `select` — show current selection summary
  - `select list` — list sessions filtered by current selection, shows totals row with bold counts
  - `select any` — clear all filters
  - `select target NAME` — filter by target name
  - `select telescope NAME` — filter by telescope/instrument name
  - `select date after|before|between DATE [DATE]` — filter by date range
  - `select export SESSION_NUM DESTDIR` — export session images via symlinks/copy
- **info** — display system and filtered data summaries
  - `info` — show user preferences location and app info
  - `info target` — list targets in current selection (with counts)
  - `info telescope` — list instruments in current selection (with counts)
  - `info filter` — list optical filters in current selection
- **process** — automated processing workflows
  - `process siril SESSION_NUM DESTDIR [--run]` — generate Siril directory tree, optionally launch GUI
- **repo add/remove/list/reindex** — manage TOML repo references
- **user name/email/analytics/setup** — manage user profile and analytics opt-in
- Console script aliases: `starbash` and `sb` (defined in `pyproject.toml`)

## Selection and filtering system
- **Selection class** (`starbash.selection.Selection`):
  - Persists state to `~/.local/share/starbash/selection.json`
  - Tracks: `targets` (list), `telescopes` (list), `date_start`, `date_end`, `filters` (list), `image_types` (list)
  - `get_query_conditions()` returns dict with keys: `OBJECT`, `TELESCOP`, `FILTER`, `date_start`, `date_end`
  - Used by `Starbash.search_session()` to filter database queries
- **Database filtering** (`Database.search_session()`):
  - Accepts conditions dict from `Selection.get_query_conditions()`
  - Extracts `date_start`/`date_end` for special `>=`/`<=` filtering on `start` column
  - Standard keys (OBJECT, TELESCOP, FILTER, IMAGETYP) use exact match

## Repos and precedence
- A "repo" is a directory with `starbash.toml` at root (examples in `doc/toml/example/recipe-repo/`)
- **Repo URLs**:
  - `file:///path/to/dir` — local directory
  - `pkg://defaults` — internal package resources (`src/starbash/defaults/`)
- Default repos listed in package defaults under `[[repo-ref]]`
- **RepoManager**:
  - Loads repos in order; later repos have higher precedence (last wins for `get()`)
  - `union()` returns MultiDict of all top-level keys
  - `get(key, default)` returns value from highest-precedence repo
  - TOML items monkey-patched with `source` (Repo instance) for relative file resolution
- **TOML Imports** (for config reuse and inheritance):
  - Repos support `[import]` tables to import nodes from other TOML files
  - Import syntax: `[target.import]` with required `node = "path.to.source"`, optional `file = "path/to/file.toml"`, optional `repo = "url"`
  - Imports are resolved during repo loading, replacing import tables with deep copies of referenced content
  - Files are cached during import resolution (stored in `Repo._import_cache`)
  - Enables stage template reuse: define common configs once, import with variations
  - Works in array-of-tables: imports merge into existing table items (preserves other keys)
  - See `doc/toml/example/imports/` for usage examples and patterns
  - Tests in `tests/unit/test_repo_imports.py` cover all import scenarios

## Stages, tasks, and context (recipe processing)
- Pipeline stages defined in TOML with `[[stages]]` having `name` and `priority`
- Work items are `[[stage]]` tables across repos:
  - `tool`: one of `siril`, `graxpert`, `python` (see `starbash.tool.tools`)
  - `when`: matches stage name (e.g., `session.config`, `session.light`, `session.stack`)
  - `script` or `script-file` (resolved relative to repo via `stage.source`)
  - `context` (dict merged into runtime context), `input` (glob patterns for files)
- **Context expansion** (`expand_context()`):
  - Uses Python `str.format_map` with `_SafeFormatter` that preserves unexpanded `{vars}`
  - Iterative expansion (max 10 iterations) for nested placeholders
  - Raises `KeyError` if variables remain unexpanded after processing
- **Python tool**: RestrictedPython sandbox with globals: `context`, `logger`, builtins (list, dict, str, int, all)

## External tool integration
- **Siril**: executed via Flatpak `org.siril.Siril -d <workdir> -s -` (commands via stdin)
- **GraXpert**: invoked as `graxpert -cmd ...` (expects CLI on PATH)
- Tools run in temp dirs with symlinked inputs; failures raise `RuntimeError`

## Analytics and crash reporting
- Optional Sentry.io integration (opt-in via `starbash user analytics on|off`)
- Stored in user config: `analytics.enabled` (bool), `analytics.include_user` (bool)
- Development environment detection (VSCODE_ env vars, STARBASH_ENV=development) disables auto-reporting
- `analytics_exception()` reports to Sentry and generates GitHub issue links
- Docs: `doc/analytics.md`

## Build, test, run (via Poetry)
- **Python**: 3.12-3.14 required (RestrictedPython not yet compatible with 3.15)
- **Dependencies**: tomlkit, multidict, rich, restrictedpython, astropy, platformdirs, typer, sentry-sdk
- **Install**: `poetry install --with dev` (includes pytest)
- **Run**: `sb [command]` (which is provided by poetry's venv)
- **Test**: `poetry run pytest` (auto-deselects slow tests via marker)
  - **300 tests total** across 10 test modules, comprehensive coverage
  - Tests use isolated directories via `paths.set_test_directories(config_dir, data_dir, documents_dir_override=documents_dir)`
  - `tests/test_cli.py` — CLI invocation tests (select, repo, user commands)
  - `tests/test_database.py` — SQLite operations and schema
  - `tests/test_repo_manager.py` — repo loading and precedence
  - `tests/test_analytics.py` — Sentry.io integration and environment detection
  - `tests/test_app.py` — Starbash lifecycle and context management
  - `tests/test_selection.py` — filter state persistence
  - `tests/test_tool.py` — external tool execution and template expansion
- **Logging**: Rich handler with INFO level default, tracebacks enabled

## Key file locations
- `src/starbash/main.py` — CLI app definition, session command with totals row
- `src/starbash/app.py` — Starbash context manager, orchestrates DB/repos/selection/analytics
- `src/starbash/database.py` — SQLite persistence layer (471 lines)
- `src/starbash/selection.py` — filter state management (216 lines)
- `src/repo/manager.py` — TOML repo loading with precedence (separate package)
- `src/starbash/tool.py` — external tool runners and template expansion
- `src/starbash/paths.py` — path management with test overrides
- `src/starbash/analytics.py` — Sentry.io integration
- `src/starbash/commands/` — subcommand modules (repo.py, user.py, selection.py, info.py, process.py)
- `src/starbash/recipes/` — built-in processing recipes (OSC dual-duo, single-duo, master frames)
- `tests/test_cli.py` — comprehensive CLI test suite

## Patterns to follow
- **Add a CLI command**: Create subcommand in `src/starbash/commands/`, register with Typer app, add test in `test_cli.py`
- **Add database field**: Update `Database` class constants, modify schema in `_init_tables()`, update `upsert_*` methods
- **Add selection filter**: Extend `Selection` class properties, update `get_query_conditions()`, modify `Database.search_session()` filtering logic
- **Add external tool**: Subclass `Tool` in `starbash.tool`, implement `run()`, register in `tools` dict
- **Add recipe**: Create repo dir with `starbash.toml`, define `[[stage]]` entries with `tool`/`when`/`script-file`
- **Use TOML imports**: For reusable stage templates, create library files and use `[stage.import]` syntax to reduce duplication
- **Test new feature**: Add test fixture using `setup_test_environment`, ensure `paths.set_test_directories()` called for isolation
- **When adding/changing code**: Update or add docstrings, maintain typing hints, follow existing code style.  Ensure that you don't introduce new linter warnings. Add new or update unit tests as appropriate.

## Current status (see TODO.md)
- **Working**: session listing with filtering, repo management, user settings, database indexing, export functionality, Siril prep, CLI with 300 passing tests
- **In progress**: processing automation (see `poc/process.py`), master frame generation, multi-session support
- **Planned**: HTTP repos, automated quality tracking, GUI (Flet), target reports, shell autocompletion

## Gotchas
- **Test isolation**: Always use `paths.set_test_directories()` in fixtures; manual cleanup with `set_test_directories(None, None)`
- **Rich markup**: Typer app initialized with `rich_markup_mode="rich"` for hyperlink support
- **SQLite row factory**: Set to `sqlite3.Row` for dict-like column access
- **RestrictedPython**: Still unsafe (imports allowed); needs policy implementation (see `make_safe_globals()` FIXME)
- **Template expansion**: Unexpanded `{vars}` cause hard failures; always provide defaults or guard with try/except
- **Repo schemes**: Only `file://` and `pkg://` supported; HTTP repos are aspirational
- **Date filtering**: Uses ISO 8601 strings (`YYYY-MM-DD`) stored in SQLite TEXT columns
- **Analytics**: Auto-disabled in development environments (VS Code detection)
- **TOML imports**: Import replaces entire table; in AoT imports merge with existing keys; cannot rewrite files with imports after resolution

## Image data examples
- Sample data under `images/from_astroboy/`, `images/from_seestar/`, `images/from_asiair/`
- FITS metadata docs in `doc/fits/` (bias, dark, flat, light headers from NINA)
- Processing examples in `poc/` (process.py, example_*.py, Siril scripts)

If you need clarification on database queries, selection filtering, test isolation, or analytics integration, ask specifically about those subsystems.
