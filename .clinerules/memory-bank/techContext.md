# Tech Context

## Technologies used

- **Language**: Python `>=3.12,<3.15` (RestrictedPython doesn't yet work on 3.15). Target `py312`.
- **CLI**: Typer `^0.20.0` (+ Click `<8.5`), Rich `>=14.2,<15` (live spinners, progress, tables, markup). Rich markup mode is ON.
- **Packaging**: Poetry (`poetry-core>=2.0`); `pyproject.toml`; scripts `starbash` and `sb` both map to `starbash.main:app`.
- **Build/task engine**: doit `^0.36.0` (+ `doit-graph` for `sb process doit graph`).
- **Config**: `toml_repo` (`^0.1.6`) — external/git-submodule package at `toml-repo/`. Repo config suffix `starbash.toml`; `pkg://defaults` resources.
- **Data**: SQLite (`sqlite3`, row factory `sqlite3.Row`); FITS via `astropy` (`>=7.1.1,<8`).
- **Sandboxing**: RestrictedPython `>=8.1,<9` for recipe Python and template expressions.
- **Scientific/deps**: `numpy 2.2.6`, `pyqt6` (siril-script experiment), `graxpert` (`^3.2.0a2` cpuonly).
- **Publishing**: Jinja2, Pygal (SVG charts), keyring (GitHub auth), sentry-sdk (analytics), update-checker.
- **Platform dirs**: platformdirs `>=4.5,<5`.
- **Dev tooling**: pytest `>=8.4.2,<10` (with `-n auto` xdist), pytest-cov, pre-commit, ruff `^0.14.4`, basedpyright `^1.33`, textual-dev.

## Development setup

- Install: `poetry install --with dev`
- Test: `poetry run pytest` (tests in `tests/`, isolated via `paths.set_test_directories`)
- Run: `sb <command>` (via poetry venv). Also `pipx install starbash` for end users.
- Handy workflows in `justfile` (e.g. `just process`, `just reinit`, `just select-*`, `just site-view`).
- pytest defaults in `pyproject.toml`: `-m 'not slow and not integration' -n auto --tb=short -rfE --ignore=GraXpert --ignore=textual --ignore=starbash-recipes`.

## Technical constraints

- **OSC-only recipes today**: mono-camera workflows not yet implemented.
- **Python version ceiling <3.15** due to RestrictedPython.
- **Recipe repo versioning**: recipes fetched from `https://raw.githubusercontent.com/geeksville/starbash-recipes/v${version}`, with local `starbash-recipes/` git submodule fallback (`force_local_recipes` flag in `app.py`).
- **PII safety**: `SITELONG` / `SITELAT` blacklisted from reports/TOML output.
- **External tools optional**: Siril (Flatpak), GraXpert, Starnet2, rc-astro (`bxt`/`nxt`) probed on PATH/common dirs; graceful warnings when missing.
- **Headless safety**: `force_no_gui` flag exists for CI/headless environments.
- **Doit cache**: `doit.db` moved to app cache dir; `STARBASH_CACHE_DIR` env var can override cache location.

## Dependencies

- Runtime (non-obvious): `tomlkit` (TOML parse/write with AoT support), `multidict` (RepoManager merged view).
- Recipe/tool data: built-in defaults under `src/starbash/defaults/starbash.toml` (aliases, equipment catalog, recipe_default URL, metadata blacklist).
- Template assets: `src/starbash/templates/` (user config, repo, target/processed, report/Jekyll).

## Tool usage patterns

- **Tool registry**: `init_tools(tool_prefs)` in `app.py` populates the global `tools` dict; stages reference tools by `tool.name`.
- **ExternalTool** probes `commands` list + `extra_dirs` (homebrew, flatpak, `/Applications/*.app/Contents/MacOS`); `preflight()` warns with an install URL.
- **tool_run_streaming** runs via `subprocess.Popen(shell=True)` with threaded stdout/stderr readers feeding a shared queue; stderr lines color red, stdout yellow; timeout kills the process.
- **Siril** runs via stdin script (`tool_run` writes `commands` to stdin); live progress via streaming.

## Build / lint conventions

- ruff: line-length 100, rules E/F/I/W/UP/B/ANN; ignores E501, B904, B006, ANN401, ANN204; per-file ignores for `tests/*`.
- basedpyright: standard mode, `extraPaths = ["GraXpert", "toml-repo"]`, pythonVersion 3.12, platform Linux.
- Format only `src/` and `tests/` (ruff.format excludes everything else).