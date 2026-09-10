# AGENTS.md

Quick orientation for AI agents. For deep details see `.github/copilot-instructions.md`.

## What this is

Starbash automates astrophotography workflows: it indexes FITS image metadata,
organizes imaging sessions, and runs processing "recipes" (Siril/GraXpert/Python)
to calibrate and stack images per target. CLI-first (Typer), commands `sb` / `starbash`.

## Architecture (the parts you'll touch most)

- **Entry**: `src/starbash/main.py` — Typer app; subcommands registered from `src/starbash/commands/`
  (`select`, `info`, `process`, `repo`, `user`, `publish`, `gui`).
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
- **Events**: `src/starbash/events.py` — dependency-free pub/sub bus. The core
  *publishes* (tool output, task transitions, stage results, reindex/target
  progress); the CLI subscribes to nothing, so its behaviour is unchanged. See
  *Desktop GUI* below.
- **Interaction**: `src/starbash/interaction.py` — `UserInteraction` protocol
  (`confirm`/`text`/`notify`/`open_url`) with a Rich default (identical CLI
  behaviour), an `AutoAccept` headless impl, and a process-wide accessor. Guided
  prompts go through `get_interaction()` rather than reading stdin directly.
- **GUI**: `src/starbash/ui/qt/**` — the PySide6 desktop app, launched by
  `sb gui`. Never imported by the CLI unless the command is used.

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

## Desktop GUI (`sb gui`)

A PySide6 desktop app. PySide6 is a **normal dependency** — "optional" here only
means that users may keep driving Starbash entirely from the CLI instead. The CLI
never imports Qt (every Qt import is lazy), so CLI start-up is unaffected.

- **Install**: nothing extra to do — PySide6 ships with Starbash.
  (Dev: `poetry install --with dev`.)
- **Entry**: `src/starbash/commands/gui.py` → `starbash.ui.qt.run_gui()` →
  `starbash.ui.qt.app.run()`. `run_gui()` raises `GuiUnavailableError` when Qt
  cannot be imported, i.e. the install is incomplete or broken; the command prints
  it as a reinstall hint instead of an `ImportError` traceback.
- **Layout**: `ui/qt/main_window.py` (nav rail + `QStackedWidget`), `ui/qt/pages/**`
  (one page per nav entry), `ui/qt/widgets/**` (reusable widgets — `image_viewer.py`
  for FITS/raster previews, `busy_indicator.py` for the loading arc, `log_view.py`,
  `selection_panel.py`, `stat_card.py`), `ui/qt/models.py`
  (dict-backed `QAbstractTableModel`s), `ui/qt/services.py` (GUI-thread reads),
  `ui/qt/jobs.py` (long operations), `ui/qt/workers.py` (`QThreadPool` +
  cooperative `CancelToken`), `ui/qt/bridge.py` (event bus → Qt signals),
  `ui/qt/interaction.py` (Qt `UserInteraction`), `ui/qt/theme.py` (QSS + the app
  icon), `ui/qt/desktop.py` (Linux `.desktop` entry + hicolor icons). Binary/assets
  (icon, favicon, checkmark, `.desktop` template) live in the packaged
  `src/starbash/assets/`.
- **Theme gotcha**: `theme.py`'s dark palette makes Qt's *native* control indicators
  invisible (Fusion draws a dark checkbox on the dark panel), so `QCheckBox::indicator`
  and the item-view indicators are drawn explicitly in the QSS — a visible outline off,
  the accent plus `assets/check.png` on. Keep new styled controls away from
  palette-derived colours, which have no contrast against this theme.
- **Threading rule (important)**: the shared `Starbash`/SQLite connection belongs
  to the GUI thread. Every long operation runs in a worker that builds its **own**
  `Starbash` (hence its own SQLite connection) and reports through the event bus.
  Never use one SQLite connection from two threads.
- **`run_async` rules (important)**: anything slow — including image decoding, which
  is why `ImageViewer.show_file()` is asynchronous — goes through
  `workers.run_async()`. Two invariants make it safe:
  - *Callbacks are delivered on the GUI thread*, so a callback may touch widgets;
    the job itself must only compute and **return data** (a `QImage` is fine, a
    `QPixmap` is not — it needs the GUI thread).
  - *`run_async` retains the `Worker` until it finishes*, so callers may ignore its
    return value. This matters: a `Worker` is a `QRunnable` with `autoDelete`, so a
    dropped reference let C++ destroy it (and its signals) before the queued
    `finished`/`failed` signal was delivered — measured at **7 of 60** callbacks
    arriving. Don't remove `_live_workers` from `workers.py`.
- **Busy states**: long work in a view shows
  `ui/qt/widgets/busy_indicator.py` (`BusyIndicator`), an understated arc plus
  caption that centres itself over any parent widget and only animates while
  visible. Use `BusyIndicator(widget)` + `start()`/`stop()` rather than a frozen
  window or a modal dialog.
- **Live updates**: the core publishes on `starbash.events`; `EventBusBridge`
  re-emits each event as one Qt signal delivered on the GUI thread, so pages can
  update widgets directly. To add live feedback, publish an event in the core and
  handle it in the relevant page — do not poll.
- **Unsaved edits**: a page with editable state implements `Page.can_leave()`.
  `MainWindow` calls it before switching pages (and on close); returning `False`
  cancels the navigation. The Targets page uses this for its stage/option editor
  (Save/Undo appear only when dirty; see `pages/targets.py`).
- **Linux desktop integration**: `ui/qt/desktop.py` writes
  `~/.local/share/applications/starbash.desktop` plus hicolor icons
  (`~/.local/share/icons/hicolor/{512x512,scalable}/apps/starbash.{png,svg}`) on
  GUI start-up. It is idempotent (rewrites only on change, which repairs the entry
  after a pipx upgrade moves the executable) and best-effort
  (`QGuiApplication.setDesktopFileName("starbash")` makes the window join the
  entry; failures are logged, never raised). Opt out with
  `STARBASH_NO_DESKTOP_INSTALL=1`. The template is
  `src/starbash/assets/starbash.desktop.in`.
- **Tests**: Qt tests live in `tests/unit/test_gui.py`, are marked `gui`, and run
  as part of the default suite (deselect with `-m "not gui"`). They use
  `QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`) so they pass headless,
  and the module skips cleanly if Qt cannot start at all.
  `tests/unit/test_targets_page.py` and `tests/unit/test_image_viewer.py` cover the
  Targets option editor and the preview/busy-arc paths respectively (the latter
  stubs the decoder with a `threading.Event` so a load can be held open and the
  "GUI stays responsive" / "stale result is dropped" behaviours are testable).
  `tests/unit/test_gui_command.py` covers the broken-install path, and
  `tests/unit/test_desktop_entry.py` (Qt-free, so it always runs) covers the
  `.desktop` install.
  `tests/unit/test_cli_headless.py` **locks in the headless guarantee**: it runs
  `sb info` in a subprocess with `DISPLAY` stripped and `PySide6` made
  unimportable, and asserts the CLI never loads Qt or the GUI package. If you ever
  make the CLI import Qt (even transitively), that test will fail — that is the
  point, since SSH users must keep working.

## Terminal commands (never block on a prompt)

An agent cannot press `q`, answer `y`, or edit a commit message, so any command
that prompts will hang until it times out. This environment sets `PAGER=less`, so
**every unpiped `git` command that pages will stall at `(END)` forever**.

- **Always pass `git --no-pager <subcommand>`** for `log`, `diff`, `show`,
  `branch -v`, `stash list`, `tag`, etc.
  Verified here: `git log --oneline -3` hangs (exit 124 under `timeout`), while
  `git --no-pager log --oneline -3` returns cleanly. Piping (`| cat`, `| head`)
  also suppresses the pager, but `--no-pager` is explicit and preferred — note
  that piping also hides decorations such as `(HEAD -> main)`.
- Prefer non-interactive flags everywhere: `git commit --no-edit`,
  `--non-interactive`, `-y`/`--yes`, `DEBIAN_FRONTEND=noninteractive`.
- Never launch an editor or pager (`less`, `vi`, `nano`, `man`) directly; redirect
  stdout or pass the tool's own no-pager flag.
- When unsure a command terminates, run it as `timeout <seconds> <cmd>`.

## Conventions

- Keep typing hints and docstrings on code you change; don't introduce new linter warnings.
- Add/adjust unit tests for behavior changes. Tests that only assert a mock "was called"
  don't verify real behavior — assert on actual resulting state.
- Rich markup mode is on for the Typer app; SQLite row factory is `sqlite3.Row`.

## Code Search

**Default tool: `semble`.** It is a dev dependency, so always run it through Poetry.
(Do **not** use `uvx`/`pip install` — see *Build / test / run* above.)

Use it to find code by describing what it does, or by naming a symbol/identifier, instead of grep:

```bash
poetry run semble search "where sessions are aggregated"          # describe behaviour
poetry run semble search "get_column_name"                        # name a symbol
poetry run semble search "stage exclusion" --top-k 10             # widen results
poetry run semble search "safe formatter" --max-snippet-lines 10  # shorter output
```

The index is built on first run (and cached for subsequent runs) and invalidated automatically when files change.

Use `--content docs` to search documentation and prose, `--content config` for config files (yaml, toml, etc.), or `--content all` to search code, docs, and config:

```bash
poetry run semble search "how releases are cut" --content docs
poetry run semble search "repo precedence" --content config
poetry run semble search "processing pipeline" --content all
```

Use `semble find-related` to discover code similar to a known location (pass `file_path` and `line` from a prior search result):

```bash
poetry run semble find-related src/starbash/app.py 270
```

`path` defaults to the current directory (the repo root), so you can omit it. The
`./my-project` argument in semble's upstream docs is a placeholder — never copy it
into a command here. `--top-k N` widens results; `--max-snippet-lines N` shortens
output.

**Prefer scoping to `src` / `tests`.** The first run indexes whatever tree you
point at; scoping keeps it fast and keeps large non-source trees (`reference/`,
`test-data/`, `starbash-recipes/`) out of the index:

```bash
poetry run semble search "stage exclusion" src     # just the package
poetry run semble search "fixture setup" tests     # just the tests
```

(`file_path` in the JSON results is relative to the path you passed.)

If `semble` is missing it is a dev dependency: run `poetry install --with dev`
(or `poetry run semble ...`). Do not reach for `uvx` or a bare `pip install`.

### Choosing a tool (read this before reaching for `grep`)

| You need… | Use |
|---|---|
| "where is X handled / what does this do" | `poetry run semble search "<description>"` |
| a symbol by name (`get_column_name`, `class Tool`) | `poetry run semble search "<symbol>"` |
| **every** occurrence of a literal string repo-wide (rename/migration sweep) | `grep -rn` (bounded — see *Workspace search safety*) |
| a structural outline of one already-known file (list its `def`s) | read the file, or `grep -n '^\s*def ' <file>` |
| a literal/regex sweep semble keeps missing | `grep -rn` or the `search_codebase` tool |

Rules of thumb:

1. Start with `semble search` for anything semantic or symbol-shaped.
2. Navigate straight to the returned `file:line` — don't re-search or re-grep for the same content.
3. `grep` is for the two carve-outs above *only*: an exhaustive literal sweep, or outlining a single file you already know.
4. When in doubt, `semble` first — it's ranked, quieter, and won't dump huge generated output.
5. Keep sweeps out of `starbash-recipes/`, `.venv/`, `reference/`, `siril-scripts/`, `test-data/`, and image trees.

### Workflow

1. `semble search` first — for anything semantic or symbol-shaped.
2. Use `--content docs` for prose, `--content config` for TOML/YAML, `--content all` for everything.
3. Navigate directly to the returned `file:line` — do not re-search or `grep` for the same content.
4. `semble find-related <file> <line>` to find sibling implementations.
5. `grep` only for an exhaustive literal sweep (e.g. every caller of a renamed
   function) or to outline a single already-known file — never for semantic/symbol lookups.

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

