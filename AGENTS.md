# AGENTS.md

Quick orientation for AI agents. For deep details see `.github/copilot-instructions.md`.

## What this is

Starbash automates astrophotography workflows: it indexes FITS image metadata,
organizes imaging sessions, and runs processing "recipes" (Siril/GraXpert/Python)
to calibrate and stack images per target. CLI-first (Typer), commands `sb` / `starbash`.

## Architecture (the parts you'll touch most)

- **Entry**: `src/starbash/main.py` — Typer app; subcommands registered from `src/starbash/commands/`
  (`select`, `info`, `process`, `repo`, `user`).
- **App context**: `src/starbash/app.py` (`Starbash`) — wires up database, repo manager,
  selection state, analytics. Context manager.
- **Data layer**: `src/starbash/database.py` — SQLite. `images` table (FITS metadata as JSON),
  `sessions` table (aggregated by target/filter/imagetyp/date).
- **Selection**: `src/starbash/selection.py` — persistent JSON filter state (target, telescope,
  date range, filter, image type). Feeds `Database.search_session()`.
- **Repos/config**: `src/repo` (aka `toml_repo`) — loads/merges TOML "repos" with precedence
  (last wins). `union()` returns a MultiDict; `get(key, default)` reads highest-precedence value.
  Repo URLs: `file:///...` and `pkg://defaults`. Supports `[import]` for TOML reuse.
- **Processing pipeline**: `src/starbash/processing.py` + `src/starbash/stages.py` +
  `src/starbash/doit.py`. Stages defined via `[[stage]]` TOML entries (`tool`, `when`, `script`/
  `script-file`, `context`, `input`, `temporaries`). Context expansion uses `str.format_map`
  with a safe formatter that preserves unexpanded `{vars}` (see `expand_context`).
  Input `requires` filters live in `src/starbash/filtering.py` (`_apply_filter`): kinds
  `metadata`, `camera`, `unprocessed`, `filename`, `min_count`. `filename` keeps candidates whose
  basename matches a regex `value`, with `mode = "include"` (default) or `"exclude"` (used by
  VeraLux to stretch only `starless`, and by `merge_stars` which blends the linear starmask back
  into the stretched starless).
- **Per-target config**: `src/starbash/processed_target.py` (`ProcessedTarget`). Backed by a
  `starbash.toml` in each target's output dir (e.g. `images/processed/<target>/starbash.toml`).
  Holds `[stages]` `used`/`excluded` lists that control which recipes run. `_init_from_toml()`
  reads them into `self.default_stages`; `remove_excluded_tasks()` (in `stages.py`) applies them.
- **Tools**: `src/starbash/tool/` — runners for Siril (Flatpak, stdin script), GraXpert (CLI),
  Python (RestrictedPython sandbox), and rc-astro (BlurXTerminator `bxt` + NoiseXTerminator `nxt`
  CLI; always passes `--json` and streams JSON progress events to a live Rich progress bar via
  `tool_run_streaming`).
- **Paths**: `src/starbash/paths.py` — platformdirs-based; override in tests via
  `paths.set_test_directories(...)`.

## Stage exclusion flow (common source of bugs)

Recipe `[[stage]]` entries have a `name`. A target's `starbash.toml` `[stages].excluded`
list holds stage names to skip. `ProcessedTarget.__init__` populates `self.default_stages`
from that TOML; `remove_excluded_tasks()` filters tasks by matching `stage["name"]` against
the excluded list. If exclusions "don't take", check that `default_stages` is actually
populated (not reset) before the filter runs.

## Build / test / run

- Install: `poetry install --with dev`
- Test: `poetry run pytest` (tests in `tests/`, isolated via `paths.set_test_directories`)
- Run: `sb <command>` (via poetry venv)
- Handy workflows live in `justfile` (e.g. `just process`, `just reinit`, `just select-*`).

## Conventions

- Keep typing hints and docstrings on code you change; don't introduce new linter warnings.
- Add/adjust unit tests for behavior changes. Tests that only assert a mock "was called"
  don't verify real behavior — assert on actual resulting state.
- Rich markup mode is on for the Typer app; SQLite row factory is `sqlite3.Row`.
