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
  The split `.starbash/{main,about,sessions}.toml` layout also carries the per-session
  calibration choice: `[sessions.masters.<type>]` holds `selected` + `selected_by`
  (`"auto"`/`"user"`) and a `[[…candidates]]` table per scored master with typed evidence
  (gain/temp/time/instrument/camera/dimensions/filter). `ProcessedTarget.session_options()` /
  `save_master_selections()` read/write it, and `Processing._resolve_input_master()` **honours a
  `selected_by = "user"` pick on the next run** (falling back to the top scorer if that master
  is gone). Legacy `used`/`excluded` string arrays still parse. See `doc/plans/session-masters.md`.
- **Auto re-index before a run**: `Processing.reindex_if_needed()` is called by
  `sb process auto` / `sb process masters` and the GUI's `process_job` before any planning,
  so frames added since the last run are picked up. It honours the `reindex.auto` user
  preference (default true; helper + default in `src/starbash/preferences.py`, checkbox on
  the GUI Settings page) and the scan then emits the same `EVENT_REINDEX_PROGRESS` /
  `EVENT_REINDEX_FINISHED` events as `sb repo reindex`, which every front end renders
  (the run's own view/page, the GUI Repositories page, and `ui/cli.py::ReindexView` for
  `sb repo reindex` / `sb repo add`). The core owns no display at all: `reindex_repos()`
  reports through the bus and nothing else, so a run's live view cannot be torn by a
  second `track()` bar (see `doc/plans/cli-live-display.md`).
- **Tools**: `src/starbash/tool/` — runners for Siril (Flatpak, stdin script), GraXpert (CLI),
  Python (RestrictedPython sandbox), and rc-astro (BlurXTerminator `bxt` + NoiseXTerminator `nxt`
  CLI; always passes `--json` and streams JSON progress events onto the event bus via
  `tool_run_streaming`). When a tool's stdout is a *machine-readable* protocol
  (rc-astro declares `stdout_mime="json"`), `tool_run_streaming` names its
  `EVENT_TOOL_OUTPUT` stream `stdout.<mime>` (e.g. `stdout.json`); log renderers
  (`Processing._on_log_event` → the CLI/GUI run tree, and the GUI Log node) skip
  those frames via `events.is_structured_stream()`, since the useful content is
  already republished as `EVENT_TOOL_PROGRESS`. `log_out` still gets the raw lines.
- **Tool availability**: each tool declares a `severity`
  (`ToolSeverity.REQUIRED`/`RECOMMENDED`/`OPTIONAL`); `Tool.status()` (and
  `missing_tool_statuses()`) reports availability, `install_url` and the fix-up
  message to both front ends. At startup `init_tools()` calls `Tool.preflight()`,
  which logs at a severity-matched level (error/warning/debug), and the GUI adds a
  dismissible warning bar per missing tool (`ui/qt/widgets/tool_warning.py`). A
  `tool.<key>.ignored = true` entry in the user config (written by the GUI's
  *Ignore* button) silences both. See `doc/plans/tool-warnings.md`.
- **Paths**: `src/starbash/paths.py` — platformdirs-based; override in tests via
  `paths.set_test_directories(...)`.
- **Events**: `src/starbash/events.py` — dependency-free pub/sub bus. The core
  *publishes* (tool output, task transitions, stage results, reindex/target
  progress); observers render from it — the CLI's `ProcessingView` is the single
  live widget for a run, and the GUI bridges the same events to Qt. Nothing in
  the core (or in a tool) draws to the terminal itself; see
  `doc/plans/cli-live-display.md`. Also see *Desktop GUI* below.
- **Interaction**: `src/starbash/interaction.py` — `UserInteraction` protocol
  (`confirm`/`text`/`notify`/`open_url`) with a Rich default (identical CLI
  behaviour), an `AutoAccept` headless impl, and a process-wide accessor. Guided
  prompts go through `get_interaction()` rather than reading stdin directly.
- **GUI**: `src/starbash/ui/qt/**` — the PySide6 desktop app, launched by
  `sb gui`. Never imported by the CLI unless the command is used.
  `src/starbash/ui/cli.py` is the CLI's counterpart: the terminal views that
  observe the event bus (`ReindexView`, used by `sb repo reindex` / `sb repo add`).

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

## Interactive debugging (debugmcp MCP)

This dev container ships the `debugmcp` MCP server, so a live bug can be chased
with a real debugger (breakpoints, logpoints, stepping, stack/variable
inspection) instead of print statements or guesswork:

- Invoke the **`debug-live` skill first** (required by the tool contract), then
  `start_debugging`. Pass one of the existing `.vscode/launch.json`
  configuration names (e.g. `Python Debugger: starbash process auto`) to reuse
  the Poetry interpreter (`get_poetry_python.sh`) and the right args — or pass
  `fileFullPath` (+ optional `testName`) to debug a single test.
- While paused: `add_breakpoint` / `add_logpoint`, `get_debug_status` (with
  `waitForPauseSeconds` to wait for the hit), `list_variable_names`,
  `get_variables_values`, `evaluate_expression`, `step_over`/`step_into`/`step_out`,
  `continue_execution`, then `stop_debugging`.
- Additive to the normal loop, not a replacement: `just lint` and
  `poetry run pytest` are still the gate before reporting a fix.
- **The configs drift.** They were last audited 2026-09-13 and two were dead
  (a removed `poc/process.py` and a removed Textual `src/starbash/ui/main.py`);
  they are now `current file` and `starbash gui`. Before trusting an entry's
  args, check `sb <cmd> --help`, and edit `.vscode/launch.json` if it is stale —
  do not assume a config still matches the CLI.
- **Check `list_breakpoints` before starting a session.** The workspace had ~27
  lingering breakpoints from earlier sessions (`app.py`, `processing.py`, …),
  which would pause a fresh run in unexpected places; they were **cleared
  2026-09-13**. They are workspace state, not `launch.json` — re-check and
  `clear_all_breakpoints` when done (ask first if unsure whose they are).
  Verified working: breakpoint → `start_debugging` (test) →
  `get_variables_values` → `continue_execution` → `remove_breakpoint`.

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
  `selection_panel.py`, `stat_card.py`, `tool_warning.py` for the missing-tool
  warning bars), `ui/qt/models.py`
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
- **Theme gotcha (specificity)**: Qt applies CSS2 specificity, so an id selector
  outranks a pseudo-class — a button given `setObjectName("Primary")` kept its accent
  fill even when disabled, because `QPushButton#Primary` beat the generic
  `QPushButton:disabled`. Any id-styled control (`#Primary`, `#Danger`) therefore needs
  its **own** `...:disabled` rule placed *after* the `:hover` rules (equal specificity →
  later wins). `test_a_styled_button_looks_disabled_when_it_is_disabled` renders both
  states and fails if the face colour stops changing.
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
    return value. This matters: with no reference kept only **7 of 60** callbacks
    arrived. Don't remove `_live_workers` from `workers.py`.
  - *A late report is dropped, never emitted into a dead object.* A job can outlive
    the Qt objects it reports to (the window was closed, or the interpreter is
    shutting down while the job still runs in the keyring), and PySide keeps the
    wrapper of a deleted C++ object while raising `RuntimeError: Signal source has
    been deleted` — or **segfaulting** — on `emit`. `Worker.run` therefore checks
    `shiboken6.isValid(self.signals)` first, and `WorkerSignals` is Python-owned
    (`setAutoDelete(False)`) so a worker its caller keeps stays valid.
  - *The same guard on the receiving side is `workers.guard_callback`.* PySide ties a
    connection to the receiver object only when the slot **is** one of its bound
    methods; a `partial(self._on_loaded, path)` or a `lambda result: self._…(result)`
    is opaque to it, so Qt cannot drop the connection when that widget dies and a late
    report raises `RuntimeError: Internal C++ object ... already deleted` from inside
    the event loop. Wrap those (as `Page.start_job` and the preview/Targets pages do),
    not the bound methods — Qt disconnects those for us.
  - *`EventBusBridge` detaches itself when Qt deletes it.* Its bus subscription is a
    plain Python reference, so it used to outlive the QObject: the next publish from
    anywhere then called into the deleted object, and — with an in-process tool's log
    forwarder republishing that error record — recursed into a `RecursionError` in an
    unrelated test. The `destroyed` handler must be a lambda/plain callable: PySide
    does not deliver `destroyed` to a slot defined on the dying object.
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
  `tests/conftest.py` also **drains Qt's global thread pool** before a `gui` test's
  fixtures are finalized and again at session end (`pytest_runtest_teardown` with
  `tryfirst`, `pytest_sessionfinish`): a `run_async` job left in flight while the app
  context, the widgets and finally the interpreter were torn down is what produced
  the sporadic `test_every_page_refreshes_without_error` SIGSEGV — the job emitted
  into Qt objects Python had already freed. Keep the drain: it is the cheap half of
  the fix (the other half is `Worker.run` dropping a report whose signals are gone).
  The same hook then **destroys the test's widgets on the GUI thread**
  (`_destroy_pending_gui_widgets`: deliver pending events, `sendPostedEvents(None,
  DeferredDelete)`, `gc.collect()`). Qt delivers a `DeferredDelete` event only from a
  *running* event loop, which a pytest session never enters, so pytest-qt's
  `deleteLater()` left every `qtbot.addWidget()` widget alive in C++ while its Python
  wrapper became garbage — and whoever ran the next cyclic collection (a `QThreadPool`
  thread under xdist) destroyed that live widget tree off the GUI thread, which is a
  SIGSEGV inside `QAbstractItemView`'s destructor ("`QBasicTimer::stop: Failed.
  Possibly trying to stop from a different thread`" is its calling card). Keep that
  too — see `doc/plans/gui-widget-teardown.md`.
  `tests/unit/test_cli_headless.py` **locks in the headless guarantee**: it runs
  `sb info` in a subprocess with `DISPLAY` stripped and `PySide6` made
  unimportable, and asserts the CLI never loads Qt or the GUI package. If you ever
  make the CLI import Qt (even transitively), that test will fail — that is the
  point, since SSH users must keep working.
  `tests/unit/test_qt_environment_guard.py` covers the same for the *suite*: PySide6
  wheels bundle Qt but not the OS libraries it links against (libEGL/...), and
  pytest-qt imports `QtGui` while pytest is still configuring — so a missing library
  used to kill the whole run with an `INTERNALERROR` before collection. Both
  `tests/conftest.py` (which refuses to run with the fix printed; see
  `doc/development.md` → *Running the tests*) and `.github/workflows/ci.yml`
  (which installs `libegl1 libgl1 libxcb-cursor0 ...` on the Linux runner) deal with
  this; keep the CI package list in sync with `integration.yml`.
  Two suites are **platform-sensitive**, so keep it that way: `test_desktop_entry.py`
  is skipped off Linux (the `.desktop`/XDG installer no-ops there by design) and the
  guard test asserts the Linux advice only on Linux. Both run on the
  ubuntu/macos/windows matrix.

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
- **Keep each command a single simple statement.** Do not bolt backgrounding
  (`nohup ... &`, `& echo $!`) onto a long `&&` chain: a single mis-escaped quote
  drops bash to its `dquote>`/`quote>` secondary prompt, which hangs forever and
  the intended command never starts. For long work, write a temp script and run
  it, or use `timeout` in the foreground and poll a redirected log — never
  background a composite line. If a command appears to hang, first check whether
  it actually started (`ps aux | grep -c '[p]ytest'`) and consult its log before
  retrying. Multi-line scripts belong in a correctly terminated heredoc
  (`python - <<'EOF' ... EOF`).

## Conventions

- **After editing _python_ code, run `just lint` and confirm it builds clean**
  (`format` + `ruff check` + `basedpyright`; it rewrites files, so re-run the tests
  after it). `ruff` alone is not enough — see `.clinerules/collaboration.md`.
- Keep typing hints and docstrings on code you change; don't introduce new linter warnings.
- Add/adjust unit tests for behavior changes. Tests that only assert a mock "was called"
  don't verify real behavior — assert on actual resulting state.
- Rich markup mode is on for the Typer app; SQLite row factory is `sqlite3.Row`.
