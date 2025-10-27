# Copilot instructions for starbash

These rules help AI coding agents work effectively in this repo. Keep answers concrete and project-specific.

## Big picture
- Starbash orchestrates astrophotography processing via TOML “repos” that define stages and recipes. Runtime merges multiple repos and runs tasks with external tools.
- Entry: `starbash.main:main` initializes `Starbash`, loads `appdefaults.sb.toml`, builds a `RepoManager`, and executes stages in priority order.
- Core modules:
  - `starbash.repo.manager` — loads/merges repos, resolves precedence, exposes `union()` (MultiDict) and `get()`.
  - `starbash.tool` — tool runners: Siril, GraXpert, Python (RestrictedPython). Handles safe template expansion and temp dirs.
  - `starbash.app` — reads stage/recipe TOML, expands context, finds input files, and executes tools.
- Canonical examples live in `doc/toml/example/recipe-repo/**` (see `starbash.toml` files and `osc_dual_duo/starbash.py`).

## Repos and precedence
- A “repo” is a directory rooted by `starbash.toml` (see `doc/toml/example/recipe-repo`).
- Default repos are listed in `src/starbash/appdefaults.sb.toml` under `[[repo.ref]]`.
- Only `file://` repos are supported currently. Repos listed later have higher precedence (last wins for `get()`).
- `RepoManager.union()` returns a MultiDict of all top-level keys; TOML items are monkey-patched with `source` (the repo) so stages can read relative files (e.g., `stage.source.read(script-file)`).

## Stages, tasks, and context
- Pipeline order comes from top-level `[[stages]]` with `name` and `priority` (example in `.../recipe-repo/starbash.toml`).
- Work items are `[[stage]]` tables found across repos; they include:
  - `tool`: one of `siril`, `graxpert`, `python` (see `starbash.tool.tools`).
  - `when`: matches a stage name (e.g., `session-config`, `session-light`, `session-stack`).
  - `script` or `script-file` (if file, resolved relative to `stage.source`).
  - Optional `context` (merged into the runtime context) and `input`:
    - `input.path` uses glob patterns; files are symlinked into a temp dir for tools.
    - `input.required` defaults to true; missing inputs raise.
- Context expansion uses Python `str.format_map` with safe placeholders. Unexpanded `{vars}` raise `KeyError`. Nested expansion is supported.
- Python tool runs code in RestrictedPython with globals: `context`, `logger`, builtins (`list`, `dict`, etc.). Default script file is `starbash.py`.

## External tool integration
- Siril is executed via Flatpak ID `org.siril.Siril` with `-d <workdir> -s -`, reading commands from stdin. See `starbash.tool.siril_run`.
- GraXpert is invoked as `graxpert -cmd ...` and expects CLI to be on PATH.
- Both tools run in temp dirs; input files are symlinked. Failures raise `RuntimeError`; stderr is logged.

## Runtime paths and data
- Runtime context is initialized in `Starbash.start_session()`:
  - `process_dir`: defaults to `/workspaces/starbash/images/process` (WIP).
  - `masters`: defaults to `/workspaces/starbash/images/masters` (WIP).
- Examples under `images/` and `poc/process.py` show expected folder layouts (e.g., raw frames under `images/from_astroboy/...`).

## Build, test, run (via Poetry)
- Python 3.12 is required (see `pyproject.toml`). Use Poetry for env and commands; don’t create/activate venvs manually.
- Install deps (including dev): `poetry install --with dev`
- Run tests: `poetry run pytest` (unit tests live in `tests/`; focus is repo precedence logic).
- Run the app:
  - Preferred: `poetry run starbash` (console script from `[tool.poetry.scripts]`).
  - Alternative: `poetry run python -m starbash.main` (only if you need module-style execution).
- Logging uses Rich; INFO is the default. Keep style consistent; no linters configured.

## Patterns to follow (with examples)
- Add a new tool: subclass `Tool` in `starbash.tool`, implement `run()`, and register it in `tools` dict.
- Add a new recipe: create a repo dir with `starbash.toml` and `[[stage]]` entries; place scripts alongside and reference with `script-file`. See `.../osc_dual_duo/starbash.toml` and its `starbash.py`.
- Define stage ordering in a higher-level repo (e.g., `.../recipe-repo/starbash.toml` `[[stages]]`).

## Gotchas
- `Repo` currently supports only `file://` URLs; HTTP repos are aspirational.
- Unset context variables in templates cause hard failures; prefer explicit defaults or guard logic.
- Siril/GraXpert must be installed locally; tests don’t cover tool invocation.

If anything above is unclear or missing (e.g., preferred repo locations, default paths, or adding HTTP repos), tell me which section to refine and I’ll update this file accordingly.