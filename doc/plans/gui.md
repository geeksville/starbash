# Plan: Optional GUI for Starbash (`sb gui`)

> **Status:** Proposed (not yet implemented) — for review
> **Owner:** Kevin Hester
> **Last updated:** 2026-09-10
> **Scope:** New desktop GUI covering the full `sb` CLI surface

## 1. Summary & recommendation

Add a first-class desktop GUI launched by `sb gui`, built on **PySide6 (Qt 6)**. It reuses the existing Python core directly (`Starbash`, `Database`, `Selection`, `RepoManager`, `Processing`, `GitHubPublisher`) rather than shelling out to the CLI, so there is one implementation of behavior. PySide6 ships as a **normal dependency** (not an extra): the GUI is a first-class way to drive Starbash, and "optional" only means users may ignore it and keep working from the CLI. `sb gui` still degrades gracefully with a reinstall hint if Qt cannot be imported (a broken install).

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

Doc: PySide6 is a normal dependency of `starbash`, so no extra is needed. Dev testing adds `pytest-qt` to the dev group. *(Originally planned as a `gui` extra; changed to a normal dependency — see §10.)*

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
| `sb process masters` | *(no GUI equivalent — masters-only is deliberately CLI-only)* |
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
    theme.py           # QSS dark theme + palette + asset paths (icon, checkbox tick)
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
      busy_indicator.py  # rotating arc + caption, centred over any parent widget
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
    """Launch the graphical user interface."""
    try:
        from starbash.ui.qt.main import run_gui
    except ImportError:
        # PySide6 is a normal dependency, so this means a broken install.
        console.print("[red]The GUI could not load PySide6.[/red] "
                      "Your install looks incomplete; reinstall starbash.")
        raise typer.Exit(1)
    run_gui(no_wizard=no_wizard, initial_target=target)
```

Registered in `main.py` alongside the other subcommands. (The sketch above is the
original command shape; the shipped command takes no options today. The wizard is
*not* driven by `--no-wizard` — it shows itself while the user repo has no
`user.name`, and bare `sb` grows a `--no-gui`/`STARBASH_NO_GUI` opt-out. See
`gui-setup-wizard.md` §3.5 and §5.4.)

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
|           |  | [ > Process selection ] [ ~ Reindex ]                       | |
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
- **Master (calibration) runs are grouped** under one dim, bold `Masters` node that
  is **collapsed by default** (`ProcessingPage._masters_item` / `_file_run`), so the
  dozen `Master <config> · <date> · <camera>` rows no longer crowd the targets out
  of the tree. The page never scrolls to a row inside a collapsed ancestor
  (`_scroll_to`), because Qt's `scrollToItem` expands it — which would pop the group
  open on the first log line. Culling (`EVENT_PREFLIGHT_FINISHED`) removes a master
  row and drops the group itself once it is empty.

### 5.5 Targets (processed results + config) — the persistent browser

**Redesigned 2026-09-13.** The left column is now a **narrow target picker**
(Target names only — the Output link moved to the right pane's path label); the
right ~75 % is a **target explorer**: a tree of `Stages` and `Sessions`, over a
detail pane that swaps between the stage-option editor and a session master
picker.

```
+------+---------------------------------------------------------------------+
| Dash | Target explorer — m13                                               |
| Sess | +----------+ v Sessions                                             |
| Mast | | lbn354   |   v 2025-08-25 · None · OnStep                         |
| Targ | | m100     |       Bias  master_bias_gain100.fit      (auto)        |
| Proc | | m101     |       Dark  master_dark_120s_gain100.fit (auto)        |
| Repo | | m13      |       Flat  master_flat_None_gain100.fit (auto)        |
| Publ | | m20      | v Stages                                               |
| Sett | | m31      |   [x] master_dark    blur_width=4                      |
|      | | ...      |   [x] master_bias                                      |
|      | +----------+   [x] stack_osc                                        |
|      |            +------------------------------------------------------+ |
|      |            | Bias master — 2025-08-25     [auto-selected]         | |
|      |            | (o) master_bias_gain100.fit  -169472 gain✓ timeΔ16d  | |
|      |            | ( ) master_bias_gain100.fit  -169500 gain✓ in future | |
|      |            | ( ) ...          [ Reset to automatic ]              | |
|      |            +------------------------------------------------------+ |
|      |            | [ Save options ] [ Undo changes ]   /path/to/m13     | |
+------+---------------------------------------------------------------------+
```

- **Left table**: `TARGET_COLUMNS` shrinks to the single **Target** column
  (`_TARGET_LIST_SHARE ≈ 0.22`, and the one column *stretches* —
  `setStretchLastSection(True)`, overriding `make_table`'s deliberately
  un-stretched last section so it fills the pane right up to the scrollbar); the
  splitter stays user-resizable. The output directory remains visible — and
  clickable — in the right pane's path label, so nothing is lost.
- **The list edits the session selection** (added 2026-09-14): it always lists every
  processed target, but its *highlighted rows* mirror `sb select` — the targets named
  by `Selection.targets`, or every row when no target filter is set (no filter means
  every target is in effect, exactly as the CLI has it). A plain click makes that row
  the only selected target and Ctrl+click toggles one in or out
  (`ExtendedSelection`; Qt already collapses an unmodified click to the clicked row
  and toggles on Ctrl, so the page adds only the write-back). Every change goes
  straight through `Selection.set_targets()`, so the CLI and the Sessions page agree
  without a Save button — see `targets-selection-sync.md`.
- **Right pane visibility**: the explorer describes exactly one target, so the right
  column is a `QStackedWidget` that shows the explorer while a *single* row is
  highlighted and a one-line hint otherwise (nothing stays loaded, so no stale
  stages/masters remain editable). Swapping rather than hiding keeps the splitter at
  its 22 % share instead of letting the list jump to the full page width.
  Unsaved edits are settled before the highlight leaves a dirty target, and a
  cancelled prompt restores both the highlight and the in-memory edits.
- **Right tree**: one `QTreeWidget` with two top-level groups, **`Sessions`
  first** (the master choice is the more common edit and the stage list is long):
  - **`Sessions`** — added only when `sessions.toml` records at least one
    session with a `[sessions.masters.<type>]` entry (the "suitable sessions"
    from the prior run). One child per such session (labelled
    `date · filter · telescope`), and under it one child per calibration type
    present (`Bias`, `Dark`, `Flat`) showing the selected master's basename and
    whether it is `auto` or a `user` pick. That basename cell is a **link**: hover
    previews the frame, activate (double-click/Enter) opens it.
  - **`Stages`** — the current stage/parameter tree, unchanged in behaviour
    (checkable stage rows whose children are the recipe-declared parameters).
- **Master links**: `services.master_url(sb, path)` turns a recorded
  repo-relative master into a `file://` URL via the master repo's
  `resolve_path()`, and returns `None` when there is no local master repo or the
  frame is not on disk — a name that could neither preview nor open stays plain
  text rather than an underlined dead link. The picker's Master cells use it too
  (via `set_link`, which now handles `QTableWidgetItem` as well as
  `QTreeWidgetItem`), with `open_on="activated"` so a plain click still only
  *chooses* a master.
- **Hover previews are user-resizable and movable**: the popup carries a small drag
  handle (`_PreviewGrip`) in its own row at the card's bottom-right — a *row*, not an
  overlay on the body's corner, which would swallow the text view's scrollbar arrow
  — and its title row is a `_TitleBar` drag bar (hand-rolled `window().move()`, since a
  frameless `Qt.Tool` has no window-manager titlebar). It remembers the size the user
  dragged it
  to across previews (`_PreviewPopup._user_size`, clamped to a floor and to the
  screen), and re-scales a previewed image to the new size (debounced; rendered
  from the kept source frame). Once the user owns the size, the popup no longer
  shrink-wraps small images. A resize keeps the window where the user moved it
  (`_keep_on_screen()` only pulls it back from an edge it has outgrown) rather than
  snapping it back beside the hovered cell.
  See `ui/qt/widgets/hover_preview.py`.
- **Detail pane**: a `QStackedWidget` holding (a) the existing **option editor**
  (stage/param selection, unchanged) and (b) a new **`MasterPicker`**; it hides
  entirely when neither applies.
- **`MasterPicker`** (`ui/qt/widgets/master_picker.py`, new): lists the scored
  candidates for one `(session, calibration type)`. A radio-style check column
  marks the current selection; columns show the master's basename, its score and
  the structured evidence (gain ✓/✗, temp Δ, time Δ / "in future",
  instrument / camera / filter match). Clicking a row selects it (and marks the
  page dirty); **Reset to automatic** reverts to the scorer's pick. It loads via
  `services.load_session_options` and saves via
  `services.save_master_selections`, which records `selected_by = "user"` — see
  `session-masters.md` for the schema and the re-run semantics.
- **Async load**: `sessions.toml` can be multi-MB, so `load_session_options`
  runs through `workers.run_async` with a `BusyIndicator` over the Sessions area
  (the `ImageViewer.show_file()` pattern); a stale result is dropped if the user
  has since picked another target.
- **Dirty / Save / Undo now spans both files.** `_is_dirty()` is true when the
  stage model *or* the master selections differ from disk. Save writes
  `main.toml` (stages) and, only when the masters changed, `sessions.toml` via a
  single read-modify-write (`ProcessedTarget.save_master_selections`); Undo
  restores both. The unsaved-change prompts are unchanged.
- Reads the split `.starbash/{main,about,sessions}.toml` layout via `ProcessedTarget`.
- **Image viewer**: JPEG/PNG natural; FITS via astropy -> normalized `QImage` with stretch controls and SII/Ha/OIII (or R/G/B) channel toggles, zoom/pan in `QGraphicsView`.
- **Non-goals for this pass**: per-session *stage* exclusion editing, in-app
  TOML editor, and a "Reprocess target" button.

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

Managed repos (the bundled `std-recipe` / `recipe` checkouts, the preferences repo and `pkg://defaults`) may be *listed* (with *Show all repositories*) but are never offered for removal: the *Remove selected* button is gated on `Starbash.is_repo_removable(url)`, i.e. "the user config has a `[[repo-ref]]` for it" — exactly the condition under which `remove_repo_ref()` succeeds.

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

> **Superseded sketch (kept as the design record).** The doodle below is the
> original single-form idea; the agreed shape is a six-page **`QWizard`**
> (welcome → you → output folders → raw-image picker → tools → checklist) — see
> the *Implementation plan* note under it and `gui-setup-wizard.md` §3.

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

**Implementation plan: `gui-setup-wizard.md`** (2026-09-15, revised same day) — the
dialog becomes a six-page **`QWizard`** (welcome → you → output folders → raw-image
file picker → tools → checklist), it shows itself while the user has no **username**
set, page 5 cannot be passed without a required tool (Siril), and the checklist's
two closing actions (*Process all my targets* / *Pick a target*) stay disabled until
the folders, the images and the required tools are ready. Also makes bare `sb` open
the GUI.

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
14. Targets page: preview + metadata from `about.toml`; stage used/excluded toggles writing `main.toml`; in-app TOML editor; "Reprocess target". *(Follow-up: the 2026-09-13 redesign — narrow target list, `Stages`/`Sessions` explorer tree and the per-session master picker — see §5.5 and `session-masters.md`.)*

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
- **CI** — GUI tests carry a `gui` marker so they can be deselected (`-m "not gui"`), but they run by default now that PySide6 is a normal dependency; `QT_QPA_PLATFORM=offscreen` keeps them headless and the module skips if Qt cannot start.
- No GUI test should ever open a real window or run a real tool.

---

## 9. Risks & open decisions

1. **PySide6 vs PyQt6** — recommend PySide6 (LGPL, official). Requires dropping the `pyqt6` dep used by the siril-script experiment. *Decision needed.* → **Resolved (kept both): see §10.**
2. **Event bus is the crux** — bad thread marshaling = UI freezes or crashes. Mitigation: Phase 0 first, all core work off the GUI thread, signals carry plain data only.
3. **SQLite across threads** — one connection per thread; worker owns the processing `Starbash`, GUI owns a read connection. Confirm WAL/journal behavior under concurrent read (worker writes frame metrics while GUI browses).
4. **FITS rendering cost** — large stacks are slow to decode; render on the worker and cache downsampled previews; never block the GUI thread.
5. **Packaging weight / pipx** — Qt is heavy. *Resolved:* PySide6 is a normal dependency (the GUI is first-class; "optional" only means users may keep using the CLI), so no extra is needed and there is no "GUI not installed" state to design for. Some users may still lack system Qt libs on Linux (bundled wheels usually cover this).
6. **Cancellation semantics** — doit subprocesses need the cancel token to actually kill children (`tool_run_streaming` already has a timeout/kill path to reuse).
7. **Publish/App-install interactivity** — depends on the callback refactor (section 4.4); if we skip it, publishing stays terminal-only initially.
8. **Scope** — full coverage is large. The plan is deliberately phased so Phases 0-4 already deliver the headline value ("pick target, run, watch, see result"), with the rest incremental.

---

### Proposed first move
Execute **Phase 0 + Phase 1**: add `events.py` + emit hooks + interaction protocol with tests, add the `gui` extra *(later changed to a normal dependency — see §10)* and `sb gui` command, stand up the themed shell, and remove Textual — all reviewable without committing to the later screens.

---

## 10. Implementation status

Landed on branch `feat-gui`. Phases 0–7 are implemented except where noted.

| Phase | Status | Notes |
|---|---|---|
| 0 Core seams | ✅ | `src/starbash/events.py` + emit hooks (`tool/base`, `doit`, `processing`, `app`); `src/starbash/interaction.py` protocol + Rich default; guided prompts in `commands/user.py` routed through it. Tests: `tests/unit/test_events.py`, `test_emit_hooks.py`. |
| 1 Skeleton + Textual removal | ✅ | `pyside6` added as a **normal dependency** (no extra — see §10); `pytest-qt` dev dep; `gui` marker; `sb gui`; Textual file, deps and justfile recipes removed. |
| 2 Read-only browsing | ✅ | Dashboard, Sessions list, Repositories list, Masters; `ImageViewer` renders FITS (percentile stretch) and raster formats. |
| 3 Selection & export | ✅ | `SelectionPanel` bound to `Selection` (apply/clear/persist, DB-suggested completion); session export via `copy_images_to_dir`. *Export-to-Siril dir tree not surfaced.* |
| 4 Processing (live) | ✅ | Worker runs `run_all_stages`/`run_master_stages`; the event bus drives the task tree, log pane, progress bar and per-target caption. Cooperative cancel at phase boundaries. *Result links/thumbnails not added.* |
| 5 Targets editor | ✅ | Targets list; a **tree** of stages whose child rows are the parameters the recipe declares (`[[stages.parameters]]`). Overridden values are shown bright yellow, recipe defaults dim; a stage's summary column lists its overridden values (not option counts). Selecting a param opens an editor with two tabs, **Use default** vs **Edit override**; nothing selected hides the editor pane entirely (a stage row shows just its description). Edits save to `.starbash/main.toml` via `services.load_stage_options`/`save_stage_options`; Save/Undo appear only when dirty and leaving with unsaved edits prompts (via `Page.can_leave()`). The row for the currently selected target (`sb select target …`) is pre-selected. The two columns are separated by a 12px gap (`_COLUMN_GAP`). *In-app TOML editor and "Reprocess target" not added.* **2026-09-13:** the §5.5 redesign landed — narrow (Target-only) target list, a `Stages`/`Sessions` explorer tree and a per-session `MasterPicker` that writes `selected_by = "user"` (see `session-masters.md`). **2026-09-14 polish:** the picker's single column stretches to the scrollbar, `Sessions` is listed above `Stages`, master names are hover-previewable/openable links in both the tree and the picker, and the hover-preview popup itself is user-resizable with a remembered size. |
| 6 Settings, wizard, publish | ✅ partial | Settings (profile/analytics/paths) + first-run wizard. The Publish page publishes to GitHub Pages for the signed-in account (the job/dialog flow is shared with the CLI, see `gui-github-publish.md`); the account field is read-only and *Open in browser* only appears after a successful publish. *Aliases editor / Tools tab not added.* |
| 7 Polish & docs | ✅ partial | `tests/unit/test_gui.py` (27 tests, `gui` marker), `tests/unit/test_targets_page.py` (11 tests: recipe/override merge, save round-trip + idempotency, dirty tracking, unsaved prompts, nav guard), `tests/unit/test_gui_command.py` (broken-install path), `tests/unit/test_desktop_entry.py` (`sb` desktop integration) and `tests/unit/test_cli_headless.py` (subprocess proof that `sb info` works with no display and Qt unimportable, and that the CLI never imports Qt). App icon + Linux `.desktop`/hicolor install (`src/starbash/assets/`). AGENTS.md + memory bank updated. *Command palette, shortcuts, demo GIF not added.* |

**§9.1 resolved — kept `pyqt6`.** We added PySide6 as a normal dependency instead of
dropping `pyqt6`. `pyqt6` is referenced only by the out-of-process `siril-scripts/`
experiments and is never imported by Starbash, so the two bindings cannot conflict
in-process; removing it would break that experiment for no benefit.

**§9.5 resolved — no `gui` extra.** The plan originally proposed a `gui` extra to keep
the base install lean. That was wrong: the GUI is a first-class way to drive Starbash,
and "optional" only ever meant *users may keep using the CLI instead*. `pyside6` is now
a normal dependency, and GUI tests run by default. The only remnant is defensive: if
PySide6 cannot be imported (broken install), `sb gui` prints a reinstall hint rather
than an `ImportError` traceback.

**Known simplifications / follow-ups**

- Preview decoding (FITS and raster) runs on a worker thread with a `BusyIndicator`
  arc over the image pane (§9.4 is partly addressed); downsampled preview caching is
  still not implemented, so each selection re-decodes the file.
- Cancellation is cooperative at phase boundaries; in-flight doit subprocesses are
  not killed (§9.6). An in-flight preview decode is likewise not cancelled - its
  result is discarded instead (see `_request` in `widgets/image_viewer.py`).
- GUI tests run as part of the default suite (PySide6 is a normal dependency);
  deselect them with `poetry run pytest -m "not gui"`.
- Missing-tool warnings (the severity model, the *Ignore* preference and the
  dismissible bars above the pages) are planned and recorded separately in
  `doc/plans/tool-warnings.md`.
- **Targets screen redesign (landed 2026-09-13).** Narrow (Target-only) left
  list, a `Stages` + `Sessions` explorer tree over a detail pane, and a new
  per-session master picker that writes a structured, user-authoritative
  selection. See §5.5 and `doc/plans/session-masters.md`; §10's Phase 5 row is
  the implementation. Follow-up polish (2026-09-14): `Sessions` above `Stages`,
  the picker's column stretched to the scrollbar, master names as hover
  preview/open links, and a user-resizable hover-preview popup whose size is
  remembered and which can be dragged around by its title row.

