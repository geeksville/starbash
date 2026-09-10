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
  VeraLux to skip `starmask` files, and by `merge_stars` to keep only `hms_starless` files when
  blending the linear starmask back into the stretched starless). Any boolean-match `requires`
  node may add `invert = true` to keep
  the non-matching candidates (used by `palette/broadband.toml` to select non-narrowband sessions).
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

- **This project uses Poetry, NOT uv/uvx.** If a skill, doc, or habit suggests
  `uvx <tool>` or `uv run <cmd>`, use the Poetry equivalent instead:
  - `uvx <tool>` → `poetry run <tool>` (run a tool in the project venv)
  - `uv run <cmd>` → `poetry run <cmd>`
  - `uv add <pkg>` / `uv pip install <pkg>` → `poetry add <pkg>`
  - `uv sync` → `poetry install --with dev`
- Install: `poetry install --with dev`
- Test: `poetry run pytest` (tests in `tests/`, isolated via `paths.set_test_directories`)
- Run: `sb <command>` (via poetry venv)
- Handy workflows live in `justfile` (e.g. `just process`, `just reinit`, `just select-*`).

## Conventions

- Keep typing hints and docstrings on code you change; don't introduce new linter warnings.
- Add/adjust unit tests for behavior changes. Tests that only assert a mock "was called"
  don't verify real behavior — assert on actual resulting state.
- Rich markup mode is on for the Typer app; SQLite row factory is `sqlite3.Row`.

## Code Search

Use `semble search` to find code by describing what it does or naming a symbol/identifier, instead of grep:

​```bash
semble search "authentication flow" ./my-project --max-snippet-lines 10  # first 10 lines only, concise
semble search "save_pretrained" ./my-project                          # full chunk content
semble search "save model to disk" ./my-project --top-k 10           # more results
​```

The index is built on first run (and cached for subsequent runs) and invalidated automatically when files change.

Use `--content docs` to search documentation and prose, `--content config` for config files (yaml, toml, etc.), or `--content all` to search code, docs, and config:

​```bash
semble search "deployment guide" ./my-project --content docs
semble search "database host port" ./my-project --content config
semble search "authentication" ./my-project --content all
​```

Use `semble find-related` to discover code similar to a known location (pass `file_path` and `line` from a prior search result):

​```bash
semble find-related src/auth.py 42 ./my-project
​```

`path` defaults to the current directory when omitted; git URLs are accepted.

If `semble` is not on `$PATH`, use `uvx --from "semble[mcp]" semble` in its place.

### Workflow

1. Start with `semble search` to find relevant chunks. The index is built and cached automatically.
2. Use `--content docs` for documentation, `--content config` for config files, or `--content all` for everything.
3. Navigate directly to the returned file and line — do not re-search or grep for the same content.
4. Optionally use `semble find-related` with a promising result's `file_path` and `line` to discover related implementations.
5. Use grep only when you need every occurrence of a literal string across the whole repo (e.g., all callers of a renamed function).

## Workspace search safety

- Do not run unrestricted recursive `grep` or similar searches in data-heavy
  directories such as `private/`, processed-image trees, caches, or build
  outputs. These directories can contain very large FITS, image, database, and
  log files and searches may take an excessive amount of time.
- When searching those directories, restrict the search to the relevant text
  file types (for example `*.toml`, `*.py`, `*.md`, or explicitly selected log
  extensions) and scope the search to the smallest useful subtree.
- Prefer targeted file listing and inspection over searching binary or large
  generated files.

