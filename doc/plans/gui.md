# Plan: Optional GUI for Starbash (`sb gui`)

> **Status:** Proposed (not yet implemented) — for review
> **Owner:** Kevin Hester
> **Last updated:** 2026-09-10
> **Scope:** New optional desktop GUI covering the full `sb` CLI surface

## 1. Summary & recommendation

Add a first-class, **optional** desktop GUI launched by `sb gui`, built on **PySide6 (Qt 6)**. It reuses the existing Python core directly (`Starbash`, `Database`, `Selection`, `RepoManager`, `Processing`, `GitHubPublisher`) rather than shelling out to the CLI, so there is one implementation of behavior. The GUI is a new optional dependency extra so the base `pipx install starbash` stays lean; `sb gui` degrades gracefully with an install hint if Qt isn't present.

The GUI covers **every existing command**: onboarding, user settings, repos, selection/sessions, info, processing (auto/masters/siril export), and publishing — plus a persistent **targets/results browser** that the CLI can't offer (image thumbnails, FITS preview, per-target stage include/exclude editing, one-click reprocess).

Textual is removed (image display is a hard requirement it can't meet).

---

## 2. Library selection

| Candidate | Image display | Desktop polish | Widgets we need (tables/forms/trees/logview) | License | Weight | Verdict |
|---|---|---|---|---|---|---|
| **PySide6** (Qt6, official) | Excellent — `QImageReader` (JPEG/PNG), FITS via numpy->`QImage`, `QGraphicsView` zoom/pan | Native, themeable via QSS | Complete (`QTableView`+models, `QTreeView`, `QPlainTextEdit`, docks) | **LGPLv3** | ~120-200 MB extra | **Recommended** |
| PyQt6 (already a dep) | Same as Qt | Same | Same | GPL-only | heavy | Reuse only if we refuse a 2nd Qt binding |
| Flet (from TODO) | Good (Flutter) | Pretty, material | Tree/table ok, weaker for huge tables + local file perf | Apache | heavy (bundled runtime) | Runner-up, not chosen |
| Tkinter | Poor/ugly | Poor | Poor | stdlib | none | Reject |
| Dear PyGui | GPU image viewer great | Gamer-style, not native | Weak forms/tables | MIT | light | Reject for a "clean" app |
| Web (FastAPI+React) | Great | Great | Great | — | heavy, split stack | Reject, overkill |

**Choice: PySide6**, for (a) official, forward-supported Qt binding; (b) **LGPL** — more permissive than PyQt6's GPL for downstream packagers even though Starbash itself is GPLv3; (c) best-in-class native image + large-table performance, which is exactly what an astro app needs (session tables with thousands of rows, FITS/JPEG previews).

**PyQt6 conflict caveat:** `pyproject.toml` currently carries `pyqt6 = "^6.10.1"` used only by the temporary "run siril scripts directly" experiment (a subprocess, not mixed into our process). Two Qt bindings can't be imported in the same process. Recommendation: **standardize on PySide6 and drop `pyqt6`** (migrate/guard the experiment), to avoid shipping two Qt stacks. This is an open decision (section 9).

**Packaging:** add as an optional extra, not a hard dep:

```toml
pyside6 = { version = "^6.8", optional = true }
[tool.poetry.extras]
gui = ["pyside6"]
```

Doc: `pipx install "starbash[gui]"` (or `poetry install -E gui`). Dev testing adds `pytest-qt` to the dev group.

---

## 3. CLI surface -> GUI screen map (full coverage)

| CLI | GUI location |
|---|---|
| `sb user setup` / first-run wizard | **Wizard** dialog on first launch (name, email, analytics, create master/processed dirs) |
| `sb user name/email/analytics` | **Settings > Profile** |
| `sb repo list` | **Repositories** list |
| `sb repo add [--master/--processed]` | Repositories > **Add** (path picker + kind) |
| `sb repo remove <n>` | Repositories > row **Remove** |
| `sb repo reindex [url]` | Repositories > **Reindex** (worker + progress) |
| `sb select any/target/telescope/date` | **Sessions > Filter panel** (persists via `Selection`) |
| `sb select list [--brief]` | **Sessions** table (default landing tab) |
| `sb select export <n> <dir>` | Sessions > row **Export...** |
| `sb select` (show selection) | Selection summary bar at top of Sessions & Dashboard |
| `sb info` | **Dashboard** stat cards |
| `sb info target/telescope/filter` | **Dashboard** breakdown widgets (click -> filters Sessions) |
| `sb info master [kind]` | **Masters** sub-tab (table + date/type/filename) |
| `sb process auto [--no-masters]` | **Processing > Run** (Auto / Auto without masters) |
| `sb process masters` | Processing > Run (**Generate masters**) |
| `sb process siril <n> <dir> [--run]` | Sessions > row **Export to Siril...** |
| `sb process doit` (dev) | Hidden dev drawer (optional; likely omit) |
| `sb publish github rewrite` (+ `--dry-run`, `--login`) | **Publish > Generate site / Publish / Sign in** |
| `--debug`, `--force`, `--verbose` | **Settings > Advanced** toggles (map to `starbash.*` globals) |
| **Processed targets** (no CLI equiv) | **Targets** screen: thumbnails, FITS preview, stage toggles, reprocess |

---

## 4. Architecture

### 4.1 Principle
The GUI is a **thin presentation layer over the existing core**. Core modules stay GUI-agnostic (no Qt imports anywhere in `starbash/` except under `starbash/ui/`).

### 4.2 Threading model (critical)
- **GUI thread**: only widgets/models. Never run tool subprocesses, reindexing, or `Processing` here.
- **Worker objects** (`QObject` moved to a `QThread`, or `QRunnable` + `QThreadPool`): own their **own** `Starbash` context and **own SQLite connection** (SQLite connections are not safe to share across threads). They push **plain `dict`/dataclass payloads** back via signals — never `sqlite3.Row` or live `Repo` objects.
- **Browsing** (Sessions/Targets/Repos/Dashboard): short queries run on a dedicated read worker; results cached in Qt models. A second `Starbash` opened read-mostly is fine against the same SQLite file.
- **Cancellation**: cooperative — a `cancel_token` checked between tasks (doit reporter hook + tool loop). The CLI stays synchronous.

### 4.3 Live progress/log events (the one core change)
Today progress goes to Rich (`Processing.progress`, `MyReporter`, `tool_run_streaming` -> `ToolLiveDisplay`). Add a tiny, dependency-free **event bus** `src/starbash/events.py`:

```python
# core emits; CLI ignores (no subscribers); GUI subscribes
publish(Event(kind="tool.output", data={"task": ..., "stream": "stdout", "line": ...}))
publish(Event(kind="tool.progress", data={"task": ..., "percent": 0.0..1.0}))
publish(Event(kind="task.started"/"task.finished", data={...}))
publish(Event(kind="stage.result", data=ProcessingResult-payload))
publish(Event(kind="reindex.progress", data={"done": n, "total": m}))
```

Emit at the existing seams only: `tool_run_streaming` (per line + rc-astro JSON %), `MyReporter.execute_task` (task start/finish), `Processing.add_result`, `Starbash.reindex_repo` (per file), `run_all_stages` target loop. The GUI bridges the bus to Qt signals via a thread-safe marshaler (`QMetaObject.invokeMethod`/signal emit). This is the highest-risk item and is scheduled early (section 7, Phase 0).

### 4.4 Interactive-prompt refactor
`sb publish` and `sb user setup` use Rich `Confirm`/`Prompt` and `typer.prompt` (deep inside `_require_app_installation`, `_ask_masters`, `_ask_user_config`). Refactor these to accept an injectable **`ui` callback object** (`ask_confirm`, `ask_text`, `open_url`, `notify`) with a **CLI implementation (Rich)** and a **Qt implementation (dialogs)**. Behavior and CLI output are preserved; the GUI drives the same logic.

### 4.5 Proposed file layout
```
src/starbash/commands/gui.py        # new Typer command; lazy Qt import + friendly error
src/starbash/events.py              # new: tiny observer bus (no deps)
src/starbash/ui/
  __init__.py
  qt/
    __init__.py
    main.py            # entry: build QApplication, theme, MainWindow
    main_window.py     # QMainWindow: nav rail + QStackedWidget + status bar
    theme.py           # QSS dark theme + palette constants (mirrors CLI colors)
    bridge.py          # event-bus -> Qt signal marshaler; logging.Handler -> Qt
    workers.py         # QObject workers: browse, reindex, process, publish
    models/
      session_table_model.py   # QAbstractTableModel over SessionRow
      image_table_model.py
      repo_list_model.py
      target_list_model.py
      task_tree_model.py       # live task/stage tree
    widgets/
      filter_panel.py    # builds Selection (target/telescope/date/filter/imagetyp)
      session_table.py
      stat_cards.py
      image_viewer.py    # JPEG/PNG via QImageReader; FITS via astropy+numpy->QImage
      log_view.py        # QPlainTextEdit, colored stdout/stderr, follow-tail
      task_list.py
      results_table.py
      toml_editor.py     # QPlainTextEdit + syntax highlight + save/validate
      aliases_editor.py  # tree + add/remove
      wizard.py          # first-run dialog
    pages/
      dashboard.py  sessions.py  masters.py  targets.py
      processing.py  repositories.py  publish.py  settings.py
```
Replaces the Textual stub `src/starbash/ui/main.py`.

### 4.6 `sb gui` command
```python
@app.command()
def gui(no_wizard: bool = False, target: str | None = None) -> None:
    """Launch the optional graphical user interface."""
    try:
        from starbash.ui.qt.main import run_gui
    except ImportError:
        console.print("[red]The GUI requires extra packages.[/red] "
                      "Install with: [cyan]pipx install \"starbash[gui]\"[/cyan]")
        raise typer.Exit(1)
    run_gui(no_wizard=no_wizard, initial_target=target)
```

Registered in `main.py` alongside the other subcommands. If no user config exists and `--no-wizard` isn't passed, the wizard runs first (mirrors the CLI callback).

---

## 5. UI design + sketches

### 5.1 Design language
Dark, calm, "observatory at night" — matches the CLI palette so screenshots/GIFs stay consistent:

| Token | Hex | Use |
|---|---|---|
| `bg` | `#0d1117` | window background |
| `panel` | `#151a21` | cards/panels |
| `border` | `#2a313c` | 1px borders, section titles |
| `accent` (cyan) | `#2ad4e6` | targets, links, selection |
| `header` (magenta) | `#d16bd6` | table headers / titles |
| `ok` (green) | `#5fd75f` | success |
| `warn` (yellow) | `#f5d76e` | current/skipped |
| `err` (red) | `#e06c75` | failure |
| `muted` | `#8a8f98` | secondary text |

Fonts: UI = system sans; tables/logs/TOML = monospace. Section headers mimic the CLI's bordered tables (Qt: `QGroupBox` with styled title). Window icon = `doc/icon/icon.svg` / `assets/favicon.ico`. A **left nav rail** (icons + labels) switches pages via `QStackedWidget`; a **status bar** shows current selection summary + background-task spinner.

> Note: the sketches below are ASCII mockups (legible in-repo). In a follow-up these can be rendered to PNG (an `excalidraw`/VHS-adjacent workflow is already used in `doc/vhs/`) and stored under `doc/design/img/gui/`.

### 5.2 Shell + Dashboard (landing)
```
+------------------------------------------------------------------------------+
|  * Starbash                                                       -  []  X    |
+-----------+------------------------------------------------------------------+
| # Dash    |  Selection:  [ Target: M31 v ] [ 2025-09-01 ... ]  [ clear ]       |
| = Sessions|  +- Index ---------+ +- Storage --------+ +- Processing ---------+ |
| * Process |  | 412 sessions    | | 12 repos        | | 8 targets done       | |
| @ Targets |  | 18,204 images   | | 2 output repos  | | 1 running...         | |
| o Repos   |  | 41h 12m total   | |                 | |                      | |
| ^ Publish |  +-----------------+ +-----------------+ +----------------------+ |
| * Settings|  +- Targets by sessions -----------+ +- Recent activity --------+ |
|           |  | m31         ############ 142     | | ok m31   stacked+dbe    | |
|           |  | ic434       ######## 96          | | ok m20   veralux+thumb  | |
|           |  | m20         ###### 74            | | ~  reindex asiair/...   | |
|           |  | m81         ### 38               | | ~  masters (darks) 42%  | |
|           |  +----------------------------------+ +-------------------------+ |
|           |  +- Quick actions ---------------------------------------------+ |
|           |  | [ > Process selection ] [ o Generate masters ] [ ~ Reindex ] | |
|           |  +--------------------------------------------------------------+ |
+-----------+------------------------------------------------------------------+
| o idle | Repos ready | 3 tools found (Siril ok GraXpert ok rc-astro no)        |
+------------------------------------------------------------------------------+
```
Maps to `sb info` + `sb info target/telescope/filter` + quick entry to process/reindex. Clicking a target bar filters Sessions.

### 5.3 Sessions (selection + list) — maps to `sb select *`
```
+-----------+------------------------------------------------------------------+
| # Dash    | +- Filters (Selection) ---------------------------------------+    |
| = Sessions| | Target [ M31 v ] Telescope [ Vespera v ] Filter [ Ha v ]     |    |
| * Process | | Image  [ LIGHT v ] Date from [2025-09-01] to [2025-10-01]    |    |
| @ Targets | |                      [ Apply ]  [ Clear all ]  [ Save v ]   |    |
| o Repos   | +--------------------------------------------------------------+    |
| ^ Publish | +- Sessions (142 of 412) --------------------------------------+    |
| * Settings| |  #   Date         Imgs   Exptime  Type       Scope    Object |    |
|           | |  1   2025-10-18    74    1h 14m   Ha         Vespera  M31    |    |
|           | |  2   2025-09-23    61    1h 01m   Sii/OIII   Vespera  M31    |    |
|           | |  3   2025-09-22    53    53m      L          EdgeHD   M31    |    |
|           | |  ...                                                         |    |
|           | |                                   SUM 142   18h 04m          |    |
|           | +--------------------------------------------------------------+    |
|           | [ Export... ] [ Export to Siril... ] [ Show reference frame ]  ~   |
+-----------+------------------------------------------------------------------+
| 142 sessions, 9,321 images, 18h 04m total                                     |
+------------------------------------------------------------------------------+
```
- Table = `QTableView` + a custom `SessionTableModel` (sunken totals row like the CLI).
- `Export...` -> `copy_images_to_dir`; `Export to Siril...` -> the `sb process siril` dir-tree logic (incl. `--run` checkbox).
- Multi-select enables bulk export.

### 5.4 Processing (live run) — the flagship screen
```
+-----------+------------------------------------------------------------------+
| # Dash    |  Run: (o) Auto  ( ) Auto (no masters)  ( ) Masters only  [ > Start]|
| = Sessions|  +- Tasks ----------------------+ +- Output - siril / thumbnail --+ |
| * Process |  | v m31                        | | [14:02:11] load hms_bk.fits   | |
| @ Targets |  |   ok light_vs_dark_s23       | | [14:02:11] resample -maxdim=. | |
| o Repos   |  |   ok stack_osc               | | [14:02:12] savejpg ....jpg 95 | |
| ^ Publish |  |   ok background_i0           | | [14:02:12] Saving ...         | |
| * Settings|  |   ~  veralux      -- 62% ... | |                               | |
|           |  |   .  thumbnail               | | > stderr (0)                  | |
|           |  | v m20                        | |                               | |
|           |  |   ok ... (5)                 | |                               | |
|           |  +------------------------------+ +-------------------------------+ |
|           |  +- Results ----------------------------------------------------+ |
|           |  | Target  Session               Status   Outputs              | |
|           |  | m31     2025-10-18:light_Ha    ok       -> stacked.fits       | |
|           |  | m31     2025-10-18:light_Ha    ok       -> hms_bk_stacked.jpg | |
|           |  +--------------------------------------------------------------+ |
+-----------+------------------------------------------------------------------+
| ~ Processing m31 - target 2/7 - veralux 62%        [ Cancel ]   elapsed 3:41  |
+------------------------------------------------------------------------------+
```
- Left `QTreeView` = live task/stage tree (from the event bus). Selecting a row filters the right **log** pane to that task's stdout/stderr (colored via `color_line` `BAD_WORDS` logic). Thumbnails of completed outputs shown inline where possible.
- Progress: per-target bar + per-task bar + rc-astro JSON % streaming.
- On finish, `Results` table mirrors `print_results` (target/session/status/notes with clickable output links -> open file/folder).
- `Cancel` -> cooperative token; partial results preserved.

### 5.5 Targets (processed results + config) — the persistent browser
```
+-----------+------------------------------------------------------------------+
| # Dash    | +- Processed targets -+ +- m31 ---------------------------------+ |
| = Sessions| | v m31      2025-10   | | +-------------+  Segmented: [R|G|B] | |
| * Process | |   m20      2025-09   | | |             |  Zoom ---  Fit 1:1  | |
| @ Targets | |   ic434    2025-10   | | |  thumbnail  |                     | |
| o Repos   | |   m81      2025-07   | | |   (jpg)     |  Object M31         | |
| ^ Publish | |   m13      2025-08   | | |             |  Scope  Vespera     | |
| * Settings| |                     | | +-------------+  Filters Ha,Sii,OIII| |
|           | |  [ Reprocess ]       | |  9,321 imgs - 18h 04m - recipe osc  | |
|           | +---------------------+ +-------------------------------------+ |
|           |                          | Stages         incl excl  note     | |
|           |                          | [x] light_vs_dark  X           calib| |
|           |                          | [x] stack_dual_duo X           stack| |
|           |                          | [x] background     X           dbe  | |
|           |                          | [ ] veralux                         | |
|           |                          | [x] thumbnail      X           jpg  | |
|           |                          |          [ Save & Reprocess ]       | |
|           |                          +-------------------------------------+ |
|           |                          | main.toml / about.toml / sessions   | |
|           |                          | [Open folder][Open report][TOML]    | |
|           |                          +-------------------------------------+ |
+-----------+------------------------------------------------------------------+
| m31 - 5 stages, 3 outputs, generated 2025-10-18 14:07                        |
+------------------------------------------------------------------------------+
```
- Reads the split `.starbash/{main,about,sessions}.toml` layout via `ProcessedTarget`.
- Stage include/exclude toggles edit `main.toml` `[stages].used/excluded` (the known bug-prone flow — GUI gives it validation + a save that calls `write_config()`).
- **Image viewer**: JPEG/PNG natural; FITS via astropy -> normalized `QImage` with stretch controls and SII/Ha/OIII (or R/G/B) channel toggles, zoom/pan in `QGraphicsView`.
- "Reprocess" runs `Processing` scoped to that target.

### 5.6 Repositories — maps to `sb repo *`
```
+-----------+------------------------------------------------------------------+
| ...       |  [ + Add repository ]   [ ~ Reindex all ]                        |
| o Repos   | +- Repositories -----------------------------------------------+ |
|           | |  #  URL                                   Kind       Status  | |
|           | |  1  file:///home/u/astro/raw              input      ok idx  | |
|           | |  2  ~/Documents/starbash/repos/master     master     ok idx  | |
|           | |  3  ~/Documents/starbash/repos/processed  processed  ok idx  | |
|           | |  4  github://.../starbash-recipes         recipe     ok      | |
|           | +--------------------------------------------------------------+ |
|           | [ Open ]  [ Reindex ]  [ Remove ]                                |
+-----------+------------------------------------------------------------------+
| Reindexing repo 2/4 - 1,204/3,900 files ...                                   |
+------------------------------------------------------------------------------+
```
Add dialog: path picker + radio kind (Input / Master / Processed / Recipe). Enforces the single-master/single-processed rule (`get_repo_by_kind`) with the same error copy as `repo add`.

### 5.7 Publish
```
+-----------+------------------------------------------------------------------+
| ^ Publish |  +- Local site -----------------+ +- GitHub ---------------------+ |
|           |  | [ Generate site ]            | | account:  (sign in)          | |
|           |  | site: ~/.local/state/.../site| | [ Sign in with GitHub ]      | |
|           |  | [ Open in browser ]          | | [ Dry run ]  [ Publish ]     | |
|           |  +------------------------------+ +------------------------------+ |
|           |  +- Log --------------------------------------------------------+ |
|           |  | ok Authenticated as kevinmac                                | |
|           |  | !  GitHub App not installed -> [ Open install page ]        | |
|           |  +-------------------------------------------------------------+ |
+-----------+------------------------------------------------------------------+
```
Reuses `GitHubPublisher`/`GitHubService`; the two-step App-install prompt becomes a dialog with an **Open install page** button (calls `webbrowser.open`) and a **Recheck** button. Progress bar reflects the existing 8+N step plan.

### 5.8 Settings
```
+-----------+------------------------------------------------------------------+
| * Settings|  Profile | Tools | Aliases | Advanced | Config files            |
|           | +- Profile ----------------------------------------------------+ |
|           | | Name  [ Kevin Mac                    ]                       | |
|           | | Email [ kevinh@geeksville.com        ]                       | |
|           | | [x] Include email with crash reports   [ ] Analytics enabled  | |
|           | |                                            [ Save ]          | |
|           | +--------------------------------------------------------------+ |
|           | Tools:  Siril [ /usr/bin/siril ok ]  GraXpert [ ok ]  rc-astro[no]|
|           |         [ Re-detect tools ]          install rc-astro ^         |
+-----------+------------------------------------------------------------------+
| Config: ~/.config/starbash/starbash.toml  -  DB: ~/.local/share/.../db.sqlite3|
+------------------------------------------------------------------------------+
```
- **Tools** tab writes `Tool.Preferences` paths (the `path` override in `tool/base.py`) and shows availability probes.
- **Aliases** tab: tree editor + raw TOML editor (ideas captured in `doc/textual.md`, remapped to Qt).
- **Advanced**: `--debug`, `--force`, `--verbose`, `max_contexts` (`doit_types.configure_max_contexts`).
- **Config files**: reveal/open `starbash.toml`, tool prefs, DB.

### 5.9 First-run wizard (mirrors `sb user setup`)
```
+---------------------------------------------------------------+
|  * Welcome to Starbash                              step 1/4   |
|                                                               |
|  Let's get you set up. You can skip any step.                 |
|                                                               |
|  Your name      [                            ]                |
|  Your email     [                            ]                |
|  [ ] Include my email with crash reports                      |
|  [x] Enable anonymous crash reports / analytics               |
|                                                               |
|  Where should processed & master files go?                    |
|  [x] Create default folders in Documents/starbash/repos       |
|      master    [ ~/Documents/starbash/repos/master    ] ...   |
|      processed [ ~/Documents/starbash/repos/processed ] ...   |
|                                                               |
|                                     [ Skip ]  [ Next > ]      |
+---------------------------------------------------------------+
```
Final step shows the "add raw repo -> process auto" next-steps panel from `do_reinit`.

---

## 6. Removing Textual

- Delete `src/starbash/ui/main.py` (Textual demo) and replace the `ui/` package as in section 4.5.
- `pyproject.toml`: remove `textual = ">=6.8.0"` and dev `textual-dev`; add `pyside6` extra (+ `pytest-qt` dev).
- `justfile`: remove `textual-demo`, `textual-code-demo`, `download-textual`; repoint `ui:` to `python -m starbash.ui.qt` (or `sb gui`).
- Remove `--ignore=textual` from pytest `addopts` if the `textual/` checkout is gone; drop the `reference/textual` docs.
- `doc/textual.md` -> supersede with this plan (and a `doc/design/gui.md` when implemented). Keep `doc/design/ui.md` pointing at the new doc.
- Leave `templates/target/master.toml` untouched — its "textual" hit is a coincidental word match (verify, don't blindly edit).

---

## 7. Phased implementation plan

**Phase 0 — Core seams (no UI yet, fully testable via unit tests)**
1. `events.py` bus + emit hooks at the 6 seams (section 4.3). CLI behavior unchanged.
2. Refactor publish/setup interactive prompts behind a `UserInteraction` protocol with a Rich-backed default (section 4.4).
3. Unit tests: events fire with expected payloads; CLI still works with no subscribers.

**Phase 1 — Skeleton (`sb gui` opens an empty shell)**
4. Optional extra wiring; `commands/gui.py` with lazy import + friendly error.
5. `QApplication` + `theme.py` QSS + `MainWindow` nav rail + placeholder pages + status bar + window icon.
6. Remove Textual deps/files in the same PR.
7. Headless guard: clear error if no display / `QT_QPA_PLATFORM` missing; support `offscreen` (tests).

**Phase 2 — Read-only browsing**
8. Browse worker + `SessionTableModel`, `RepoListModel`, `TargetListModel` -> Dashboard, Sessions (list only), Repositories (list), Masters.
9. `ImageViewer` for existing `.jpg` thumbnails + FITS preview; **validate the image display requirement explicitly** (JPEG + a real stacked FITS).

**Phase 3 — Selection & export**
10. `FilterPanel` bound to `Selection` (apply/clear/persist); live session table + totals.
11. Export (symlink/copy) and **Export to Siril** dir-tree (with `--run` checkbox).

**Phase 4 — Processing (live)**
12. Worker runs `Processing.run_all_stages` / `run_master_stages`; wire event bus -> `TaskTreeModel` + `LogView` + progress + `ResultsTable`.
13. Cancel; results links open files/folders; thumbnail preview of outputs.

**Phase 5 — Targets editor**
14. Targets page: preview + metadata from `about.toml`; stage used/excluded toggles writing `main.toml`; in-app TOML editor; "Reprocess target".

**Phase 6 — Settings, wizard, publish**
15. Settings tabs (Profile/Tools/Aliases/Advanced/Config) + `AliasesEditor`.
16. First-run wizard; hook into `sb gui` and the DB `Starbash` context.
17. Publish page (generate/publish/dry-run/login + App-install dialog).

**Phase 7 — Polish & docs**
18. Icons/shortcuts/command palette (Qt `QShortcut`), empty/loading/error states, keyboard nav, HiDPI.
19. `doc/design/gui.md` + README section + install docs; optional demo GIF into `doc/vhs/`.

---

## 8. Testing strategy

- **Core (Phase 0)** — plain pytest: assert the event bus emits correct payloads (real state, not "was called" — per AGENTS.md), and that the Rich `UserInteraction` default still drives `publish`/`setup`.
- **Models** — pure `QAbstractTableModel` logic (row/column mapping, totals, sorting) tested with `pytest-qt` under `QT_QPA_PLATFORM=offscreen`; no display needed.
- **Smoke** — a `qapp` fixture constructing `MainWindow` and switching pages; `sb gui` lazy-import test asserts a clean error when Qt is absent.
- **Isolation** — reuse `paths.set_test_directories(...)` for any GUI test touching config/DB; point the read worker at a temp DB.
- **CI** — keep GUI tests behind a marker (`-m "not gui"` default) so headless CI without Qt still passes; run the offscreen suite in a dedicated job with the `gui` extra installed.
- No GUI test should ever open a real window or run a real tool.

---

## 9. Risks & open decisions

1. **PySide6 vs PyQt6** — recommend PySide6 (LGPL, official). Requires dropping the `pyqt6` dep used by the siril-script experiment. *Decision needed.*
2. **Event bus is the crux** — bad thread marshaling = UI freezes or crashes. Mitigation: Phase 0 first, all core work off the GUI thread, signals carry plain data only.
3. **SQLite across threads** — one connection per thread; worker owns the processing `Starbash`, GUI owns a read connection. Confirm WAL/journal behavior under concurrent read (worker writes frame metrics while GUI browses).
4. **FITS rendering cost** — large stacks are slow to decode; render on the worker and cache downsampled previews; never block the GUI thread.
5. **Packaging weight / pipx** — Qt is heavy; must stay an extra. Some users may lack system Qt libs on Linux (bundled wheels usually cover this) — document `starbash[gui]`.
6. **Cancellation semantics** — doit subprocesses need the cancel token to actually kill children (`tool_run_streaming` already has a timeout/kill path to reuse).
7. **Publish/App-install interactivity** — depends on the callback refactor (section 4.4); if we skip it, publishing stays terminal-only initially.
8. **Scope** — full coverage is large. The plan is deliberately phased so Phases 0-4 already deliver the headline value ("pick target, run, watch, see result"), with the rest incremental.

---

### Proposed first move
Execute **Phase 0 + Phase 1**: add `events.py` + emit hooks + interaction protocol with tests, add the `gui` extra and `sb gui` command, stand up the themed shell, and remove Textual — all reviewable without committing to the later screens.
