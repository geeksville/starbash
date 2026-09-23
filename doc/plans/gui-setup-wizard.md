# Plan: GUI first-run setup wizard (and bare `sb` opens the GUI)

**Status:** **implemented 2026-09-16** (proposed 2026-09-15, revised the same day; no
longer "awaiting review"). The wizard is a multi-page **`QWizard`** (§3; Qt's own
reference is <https://doc.qt.io/qt-6/qwizard.html> — `nextId()`, `IndependentPages`,
`isComplete()` and the custom-button row are the parts used here), first-run
detection is the **username check** (§5.4), and the last page **cannot be finished
without Siril** (§3.3).
**Relates to:** `gui.md` §5.9 (*first-run wizard* — that section is the original
sketch and stays as the design record), `tool-warnings.md`, `gui-github-publish.md`.

### What landed, and where

| Piece | File |
|---|---|
| Six `QWizardPage`s + `SetupWizard` + `run_setup_dialog` (returns the action) | `ui/qt/pages/wizard.py` |
| Module helpers: `_output_folders_base`, `_raw_image_repos`, `_repo_path`, `_required_tools_missing` | `ui/qt/pages/wizard.py` |
| `setup_checklist` + `is_wizard_complete` — the one definition of "set up", shared by the last page and the start-up test (§5.4) | `ui/qt/pages/wizard.py` |
| `MainWindow.run_setup_wizard` / `_apply_setup_action` / `show_page_of_type` | `ui/qt/main_window.py` |
| `is_wizard_complete(sb)` + `QTimer.singleShot(0, window.run_setup_wizard)` in `run()` | `ui/qt/app.py` |
| `ProcessingPage.start_run()` (was `_start`, now public for the wizard) | `ui/qt/pages/processing.py` |
| `Tool.invalidate_availability()` (the *Re-check* button needs it) | `tool/base.py` |
| `desktop_session_available()` + bare-`sb` launch (`--no-gui` opts out) | `ui/qt/__init__.py`, `main.py` |
| `wizard_logo_pixmap` / `wizard_watermark_pixmap` / `WIZARD_*` sizes | `ui/qt/theme.py` |
| Tests: 31 in `test_setup_wizard.py` plus 9 in `test_gui_launch.py`, the two old wizard tests moved out of `test_gui.py`, and a `--no-gui` case in `test_cli.py` | `tests/unit/` |

Two things that were wrong on the first pass and are easy to get wrong again:

- **`setCurrentId()` needs a *shown* wizard.** Qt ignores it while the wizard is
  hidden, so the page-flow tests `show()` it (offscreen) first.
- **A raw-image repo is not merely "whatever `regular_repos` returns".** That list
  only hides a plain `"recipe"`, while the default recipes Starbash installs for
  itself are marked `"std-recipe"` — so `_raw_image_repos()` excludes an explicit
  kind set (`master`, `processed`, `recipe`, `std-recipe`, `preferences`) instead.

## 1. Goal

Make the GUI's first run feel like the CLI's first run, and remove the last
"you must know the CLI first" step:

1. The GUI walks the user through setup **step by step** in a Qt `QWizard`, with
   the same information the CLI collects, plus the one thing the CLI cannot do
   nicely: a **file picker** for the folder that holds the raw images.
2. The wizard **shows itself automatically** while the machine still has no
   username set — no hunting for *File ▸ Run setup wizard…*.
3. The wizard ends with a **checklist** and, once every blocking item is ticked,
   two buttons: *Process all my targets* and *Pick a target to process*. It cannot
   be finished while a **required** tool (Siril) is missing.
4. **`sb` with no subcommand opens the GUI** (falling back to today's behaviour
   where there is no desktop session), so a brand-new user can just run `sb`.

## 2. Today, in both front ends

### 2.1 The CLI first-run flow (what we are mirroring)

`starbash.main` with no subcommand and no user config → `Starbash("app.first")`
→ `user.do_reinit(sb)` (`src/starbash/commands/user.py:155`), which:

- publishes `EVENT_FIRST_RUN` with a subtitle that explains *what* the questions
  are for and that everything is optional;
- asks **name**, **email**, *include email in reports*, *enable analytics*
  (each with a default taken from the user repo);
- asks *"Create default output folders under ~/Documents/starbash/repos"*, then
  for a `master` and a `processed` folder (creating them via
  `add_local_repo(..., repo_type="master"/"processed")`);
- prints an *"Almost done!"* panel of **recommended next steps**: add the folder
  with your raw images (`sb repo add ~/your/images`), then
  `sb process auto`, and mentions the GUI (`sb gui`) as an alternative.

So the CLI's own flow has the same two-part ending we want: do the small stuff
now, then point at *"add images → process"*.

### 2.2 The GUI today

`src/starbash/ui/qt/pages/wizard.py` is a **single-shot form**: a plain `QDialog`
(`SetupWizard`, shown by `run_setup_dialog`) collecting
name/email/analytics/`_create_dirs`, and `MainWindow._on_setup` (File menu)
reloads the app context when it returns `True`. It already writes exactly the same
config keys as `do_reinit`, so the write half is reusable — the *shape* becomes a
`QWizard` of six pages (§3), the *ending* gains a checklist + two actions, and the
existing writes move into each page's `validatePage()`. There is **no** images page
and nothing surfaces the wizard on first run. The two tests that poke its private
widgets (`test_gui.py:1582`, `:1602`) move to a new module and speak the wizard's
`field()` API instead (§3.1, §7).

Two existing pieces set the house style for the new dialog:

- `ui/qt/widgets/github_login.py` — how a *long-running* step is done here
  (`_set_busy`, a status line, `run_async` job, `_closed` flag so a late callback
  is dropped). Its own `_show_step` paging is **not** the model any more:
  `QWizard` owns Back/Next (§3.1), so `github_login` is cited only for the
  async/teardown patterns the new pages copy.
- `ui/qt/widgets/selection_panel.py` / `pages/repositories.py` — repo adding and
  live index progress driven by the event bus.

## 3. What we will build

### 3.1 Wizard shape — a `QWizard` of six pages

The dialog **is** a `QWizard` subclass (`SetupWizard`), owned by `MainWindow` so
the File-menu entry keeps working and the wizard stays reachable later. This
replaces the plain `QDialog` + hand-rolled footer of the first draft: `QWizard`
gives us Back/Next/Finish, per-page validation, a `field()` store for anything a
later page needs to read, and the custom-button row — for a task Qt describes as
exactly this kind ("wizards are useful for complex or infrequent tasks that users
may find difficult to learn").

The mechanics relied on are the ones at
<https://doc.qt.io/qt-6/qwizard.html#details>: `setPage()` and page ids,
`initializePage()`/`cleanupPage()`, one `nextId()` for the dynamic edges,
`isComplete()` → `completeChanged()` for Next/Finish gating (not the
mandatory-field asterisk — see §3.2), and `setButton`/`HaveCustomButtonN` for the
two closing actions.

Why the native chrome is safe here (verified against our QSS theme, not assumed):

- `theme.py`'s palette styles `QDialog`/`QLabel`/`QPushButton`, so the page body
  and the button row already look right; `QWizard` does not use
  `QDialogButtonBox` at all.
- `ModernStyle` draws a header banner with its own hard-coded colours, but with our
  dark palette it resolves to `#1b1f24` — the same colour as the window body — with
  the title in the ordinary label colour `#d7dde3`. It therefore does not fight the
  theme. (`setWizardStyle(ModernStyle)` is set explicitly, so the look is identical
  on Windows/macOS/Linux instead of becoming `MacStyle` — a radically different
  assistant layout — if the app is ever run with a native style rather than Fusion.)
- Of the four `WizardPixmap` roles we set **two**, from the art already in
  `doc/icon`: `LogoPixmap` (the small mark `ModernStyle` puts at the top
  right of the header) and `WatermarkPixmap` (the tall mark on the left below the
  header). Both are the **transparent** telescope (`doc/icon/icon.svg`, packaged as
  `starbash/assets/icon.svg`), whose light-grey fills are drawn *for* a dark UI —
  which is exactly why the earlier draft's "set no pixmap at all" rule is now
  replaced by "set these two, and nothing that paints a background".
- `BannerPixmap` is deliberately left **null**: it would cover the themed header
  colour above with an opaque image, and `BackgroundPixmap` (the macOS-only
  wallpaper) likewise. Those two are the roles that would clash, and we do not
  touch them.

Every API named in this section exists in the PySide6 we ship (probed:
`QWizard`/`QWizardPage` expose `setPage`, `pageIds`, `startId`, `setWizardStyle`,
`setOption(s)`, `setPixmap`/`pixmap`, `setButton`/`setButtonText`/
`setButtonLayout`/`button`, `nextId`, `validateCurrentPage`, `initializePage`,
`cleanupPage`, `hasVisitedPage`, `visitedIds`, `field`/`setField`,
`currentIdChanged`, `customButtonClicked`; the page side exposes `registerField`,
`isComplete`, `completeChanged`, `validatePage`), and the four `WizardPixmap`
roles are null on a fresh wizard.

Wizard-level setup:

| Setting | Why |
|---|---|
| `setPage(Page.<NAME>, …)` with an `IntEnum` of page ids | Named ids; `setStartId(Page.WELCOME)` |
| `setWizardStyle(ModernStyle)` | Platform-independent look, with the logo/banner header (§ above) |
| `setOption(NoBackButtonOnStartPage)` | Nothing to go back to on page 1 |
| `setOption(IndependentPages)` | A page the user returns to must keep what they typed — the default `cleanupPage()` *resets* fields on Back. This is the option Qt documents for exactly that: "If you want the Back button to be non-destructive and keep the values entered by the user" |
| `NoCancelButton` left **off** | The wizard is cancellable at any point: each page commits its own part in `validatePage()`, so a half-finished wizard still leaves a usable config — the same "each answer is saved as you go" property the CLI has |
| `setButtonText(FinishButton, "Finish")` | Otherwise our copy of the button reads oddly on macOS (`Done`) |

`nextId()` is implemented **once on the wizard** (Qt's own suggested alternative
to per-page copies) so the two dynamic edges below live in one readable `switch`.

| # | Page | Content | Next enabled when |
|---|---|---|---|
| 1 | **Welcome** | What Starbash does; "nothing here is written into your images folder"; the telescope in the left pane is **centred** by `_centre_pane_mark` (§3.6). | always |
| 2 | **You** | name, email, *include email in reports*, analytics checkbox (defaults from the repo, exactly as today). The name is required. | `user.name` non-empty (§3.2) |
| 3 | **Output folders** | Two radios — *create the default output folders under `~/Documents/starbash/repos`* (pre-selected, so the one-click path is unchanged) or *under a folder I choose* + *Choose folder…* — with the resolved `master`/`processed` paths, or "you already have these" when `get_repo_by_kind()` finds them. | **answered**: the default, or the custom radio with a folder actually picked (§3.6) |
| 4 | **Your images** | A `QFileDialog.getExistingDirectory` picker; the known folders are listed, each marked with whether FITS files were found directly inside it. | **at least one raw-image folder** exists — picked here or already added (§3.6) |
| 5 | **Tools** | One row per missing required/recommended tool with *Install*, *Re-check* and (where `can_be_ignored`) *Ignore* — the logic of `ToolWarningBar` (§3.3). | only when every `ToolSeverity.REQUIRED` tool is available — **this is the Siril gate** |
| 6 | **Done** | The checklist and the two closing actions (§3.4). | Finish enabled per §3.4 |

**Dynamic edges** (all in `nextId()` plus a small `refresh()` protocol):

- Page 5 is **skipped entirely** when `missing_tool_statuses()` is empty, so a
  user who already has Siril never sees a tools page at all. Implemented in
  `nextId()` (page 4 → 6 when nothing is missing), *plus* an empty-state label
  inside page 5 for the case where the user reaches it and then installs the
  tool: a page whose children are all fine must not trap them.
- Re-checking on page 5 **re-runs the probe**, because
  `ExternalTool.is_available` is **cached** (`tool/base.py:824`, `_is_available`
  is `None` only until the first access): a naive re-read would keep reporting the
  old answer after the user installed Siril. There is no way to clear that cache
  today, so §4 adds `Tool.invalidate_availability()` (a no-op on the base,
  `_is_available = None` on `ExternalTool`) and the *Re-check* button calls it for
  that tool before repainting the row. This is the one place in the wizard where
  "just re-read it" is wrong. A tool that caches its answer somewhere *else* has to
  override `invalidate_availability()` for this to reach it — `StarnetTool` does
  (`_starnet_available`), see §3.3.
- **Pages 4 and 6 must re-read the world every time they are shown**, and this is
  *not* what `initializePage()` does here: we set `IndependentPages` (§3.1), whose
  documented meaning is that `initializePage()` is "only called the first time the
  page is shown". Relying on it would leave page 6 reporting a stale checklist
  after the user went back and added a folder. So those two pages implement
  `refresh()`, and the wizard connects `currentIdChanged` to
  `self.currentPage().refresh()` (the same `refresh()` convention `MainWindow`
  uses for nav pages) rather than overriding `initializePage()`. `initializePage()`
  is still the right hook for one-off first-time work — page 6 uses it to populate
  its rows — and `hasVisitedPage()` distinguishes "came forward through the
  wizard" from "jumped straight here".

### 3.2 Page 2 asks for a username, and requires one

First-run detection is the **username** (§5.4), so the page that collects it must
not be skippable — otherwise "no name yet" and "setup finished" are
indistinguishable and the wizard re-appears on every launch.

- The page implements **`isComplete()`** instead of using a mandatory field:
  `return bool(self._name.text().strip())`, with `completeChanged` emitted from
  the name field's `textChanged`. The asterisk form
  (`registerField("user.name*", …)`) is deliberately **not** used, because Qt
  defines "filled" as *different from the value the field had in
  `initializePage()`* — so on a re-run (name already saved) the field would start
  out "unfilled" and *Next* would be **disabled for exactly the user who is
  already set up*. The fields are still registered (plain names, so page 6 can
  read them with `field()`); completeness is computed from the widget's own text.
- `email` stays optional (blank and skipped are the same thing here), but if the
  user typed one the *include email in reports* checkbox is offered, as today.
- `validatePage()` writes `user.name` / `user.email` / `analytics.*` through
  `sb.user_repo` + `write_config()` — the existing body of `SetupWizard.apply()`,
  moved to the page where it belongs.
- The page's subtitle says why it is required: *"Starbash credits this name in
  the images it produces."*

### 3.3 Page 5 — the Siril gate (a required tool cannot be skipped past)

The user's requirement is blunt: **do not let the user finish the wizard until
Siril is installed.** Concretely, three independent mechanisms, so it holds no
matter how the user travels:

1. **`ToolsPage.isComplete()`** returns `False` while any
   `ToolSeverity.REQUIRED` tool is missing, and emits `completeChanged()` — Qt
   then keeps *Next* disabled, which is the documented mechanism for this
   ("disable the Next or Finish button … rather than reimplement
   validateCurrentPage()").
2. **`validatePage()`** re-checks before leaving the page and, when a required
   tool is still missing, shows the tool's own `missing_message()` in the page's
   status area and returns `False` (the wizard stays put). With `isComplete()`
   already blocking *Next* this is the belt to that page's braces — it catches the
   [Return]/auto-advance paths, and it is how the *re-run* case fails loudly.
3. **`DonePage.isComplete()`** re-checks the same condition, so a required tool
   that went missing after page 5 leaves *Finish* disabled (§3.4) — the loop is
   closed by the button state, not by overriding `validateCurrentPage()`, which Qt
   advises against for this.

The gate counts *availability*, not the buttons: a missing **required** tool is
never ignorable here either — `ToolStatus.can_be_ignored` is `severity <
ToolSeverity.REQUIRED`, which is why there is no *Ignore* button on the Siril row
and why `tool.<key>.ignored` cannot be used to sneak past it.

What the page shows per tool, reusing what already exists rather than new UI:

- `tool_status(key).name`, its `severity.label`, `status.summary` (the first line
  of `missing_message()`, already plain-text — see `ToolStatus.summary`) and an
  **Install** button that opens `install_url` through the existing
  `widgets/file_links.py::open_with_status` — the same helper `ToolWarningBar`'s
  own *Install* button already calls (`tool_warning.py:111`). No new link
  plumbing.
- For a `RECOMMENDED` (StarNet) or `OPTIONAL` tool the row is **advisory**: it
  gets the install link but does **not** block. A non-required missing tool also
  offers *Ignore*, which writes `tool.<key>.ignored` exactly as
  `MainWindow._on_ignore_tool` does, so the choice silences the CLI too.
- A *Re-check* button per row clears **that row's own** tool's cached availability
  and re-probes (§3.1) — *not* the page's gating tools only. Re-checking is per tool
  because the button sits on a row: a `RECOMMENDED` tool (StarNet) has a row and a
  button too, so narrowing the invalidation to `severity >= REQUIRED` left its row
  reading a cached answer for the rest of the session. The same trap exists on the
  tool side, where a tool may keep a cache of its own beside `ExternalTool`'s
  (`StarnetTool._starnet_available`, so it overrides
  `Tool.invalidate_availability()`).
- **Leaving the page re-probes *every* tool** (`validatePage()` →
  `_reprobe_tools()`), for the same reason one step wider out: the probe results are
  cached process-wide, and the main window's warning bar re-reads exactly those
  answers (`ToolWarningPanel.refresh()`, via `reload_context()` as soon as the wizard
  closes). Gating-only invalidation would leave a StarNet installed during the wizard
  showing its old "missing" bar for the rest of the session unless the user happened
  to press *Re-check* on that very row — *Next* has to be enough. It is cheap enough
  for the GUI thread (filesystem lookups; no tool is ever executed to test it).

Wording for the gate, kept next to the disabled button so it is never a mystery:
*"Starbash needs Siril to calibrate and stack your images."* with the install link
right there. `install_url` for Siril is already declared on `SirilTool`
(`SIRIL_INSTALL_URL`, `tool/siril.py`).

### 3.4 Checklist and the two closing actions (page 6)

Page 6 renders one row per item with `✓`/`○` and a one-line caption:

| Item | Complete when | Gates *Finish*? | Gates the actions? |
|---|---|---|---|
| Your details | `user.name` is set (guaranteed by §3.2 on any forward pass) | no (page 2 already) | **yes** |
| Output folders | a `master` **and** a `processed` repo exist | no | **yes** |
| Your raw images | at least one input repo exists (pre-existing, or added on page 4) **and** it found at least one FITS file (`.fit`/`.fits`, so a folder of JPEGs correctly reads as zero) | no | **yes** |
| Tools | every `ToolSeverity.REQUIRED` tool is available — a missing Siril blocks (§3.3) | **yes** — `DonePage.isComplete()` | **yes** |

**Only a required tool can hold the wizard open — and it does.** `DonePage.isComplete()`
returns exactly one condition, *no `ToolSeverity.REQUIRED` tool is missing*, and Qt
turns that into a disabled *Finish* (measured below), so the rule the user asked for
travels through the documented mechanism ("disable the Next or Finish button …
rather than reimplement `validateCurrentPage()`") instead of a `validateCurrentPage()`
override. Everything else on the checklist deliberately does **not** gate *Finish*:
images may genuinely not be on this machine yet, and "let me look around first, then
cancel" must not be a trap. What those items gate is the two **action buttons** —
they stay disabled until every row is ticked, with the caption naming what is still
missing ("Add the folder with your raw images first"). So *you cannot finish until
Siril is installed*, and nothing else can. This is the "click *this* button" moment;
it replaces `do_reinit`'s "Almost done!" panel:

- **Process all my targets** → `sb.selection.clear()` (empty selection == every
  session, i.e. `sb select any`) → save → switch to the Processing page and
  `ProcessingPage.start_run()`.
- **Pick a target to process** → switch to the Targets page (the user picks a
  target/session there; no run starts).
- **Finish / close** → just close (the config is already saved). While anything
  blocking is missing, *Finish* is **disabled** (see below) and the caption points
  back at the incomplete item ("Add the folder with your raw images").

The two action buttons are the wizard's `CustomButton1` / `CustomButton2` (via
`setButton`/`setButtonText` + `HaveCustomButton1|2`, handled in
`customButtonClicked`), **not** extra entries built out of `Finish`, so `QWizard`
keeps owning the button row and *Finish* stays the plain "just close" path. (Qt
pre-creates hidden placeholder buttons — `button(CustomButton1)` is already a
`QPushButton` named `__qt__passive_wizardbutton6` before we touch it — so
`setButton` *replaces* ours into that slot and `HaveCustomButtonN` makes it
visible; do not read a non-`None` button as "ours is showing".)

**Gating, as measured rather than assumed** (probed against the PySide6 we ship):

- `DonePage.isComplete()` — returning "no **required** tool is missing" —
  **automatically disables *Finish***, because Qt drives the Next *and* Finish
  buttons from `currentPage().isComplete()`: with a page reporting `False` on the
  last page, `button(FinishButton)` stays visible but `isEnabled()` is `False`, and
  clicking it does nothing (the wizard never accepts). So requirement 5 — *no
  finishing the wizard without Siril* — costs one method returning one condition,
  and it is the *item*, not the button, that decides.
- Qt does **not** apply that to custom buttons: it never consults `isComplete()` for
  them, and it creates them **enabled** and shows them on **every** page — so the
  wizard used to offer a live *Process all my targets* on page 1. Gating is therefore
  two halves, and both are the wizard's, not the page's (§3.6 says why):
  `SetupWizard._disable_action_buttons()` switches both buttons off at construction
  and again on entering any page but the last (`currentIdChanged`), and
  `DonePage.refresh()` is the *only* code that arms them, from the freshly-computed
  checklist, on every visit. Disabled rather than hidden: Qt re-shows a hidden custom
  button on the next page change, and the tooltip ("Finish the setup first — the last
  page has this action.") still explains a greyed one. `SetupWizard.action_buttons()`
  owns "which buttons are ours"; `DonePage._action_buttons()` just delegates to it.
  Both buttons and *Finish* must move together, or the user gets a live *Process all*
  next to a dead *Finish*.

`SetupWizard.action` records which button was used; `run_setup_dialog()` returns it
so `MainWindow` — not the wizard — performs the navigation, after the reload.

### 3.5 Bare `sb` opens the GUI

`starbash.main.main_callback` already has `invoke_without_command=True` and, when
no subcommand was given, checks `get_user_config_path().exists()`: absent → the
CLI's guided setup, present → print help. New behaviour, in order:

1. If a desktop session looks available **and** the user has not opted out
   (`--no-gui`, `STARBASH_NO_GUI=1`) → `run_gui()`.
2. Otherwise fall back to exactly today's behaviour: no config → `do_reinit`,
   config → help.

The GUI then shows the wizard by itself (no username yet), which is how
requirement 2 and requirement 4 meet: `sb` on a fresh machine goes *GUI → wizard →
images → process*, and on an SSH box it still goes *CLI → the same questions*.

The "is there a desktop session?" test must be **Qt-free** so `sb` on a headless
box never imports PySide6: a new `desktop_session_available()` in
`ui/qt/__init__.py` (that module is already Qt-free) that

- returns `False` when `STARBASH_NO_GUI` is set, or when `QT_QPA_PLATFORM` is
  `offscreen`/`minimal` (no visible window: this is also what keeps the test
  suite — which sets `QT_QPA_PLATFORM=offscreen` in `tests/conftest.py` — from
  ever trying to open a window),
- on Linux requires `DISPLAY` or `WAYLAND_DISPLAY`,
- returns `True` elsewhere (macOS/Windows always have a session).

`run_gui()` is still wrapped in `GuiUnavailableError` handling: a broken install
falls back to the CLI rather than printing a traceback.

### 3.6 Follow-ups from the review (2026-09-16)

Three behaviours were flagged for correction once the wizard was running (`attn ai`
notes in the first implementation). What each one *was*, and what it is now:

#### 3.6.1 The Welcome watermark is not top-left

The telescope used to sit in the upper third of the left pane. Qt's
`ModernStyle` paints `WatermarkPixmap` at the **top-left** of a label that runs the
full height of the page body — that is Qt's placement, not our layout. Qt builds
that label *during* the first show, i.e. after our constructor returned, so it
cannot be touched there. `_centre_pane_mark(wizard)` finds it by the pixmap we
handed Qt (`QPixmap.cacheKey()` identifies the *contents*; the label's copy of the
watermark shares ours, while the logo's differs) and changes only its alignment to
`AlignCenter`, which keeps the mark centred by itself as the window is resized or
restyled. `SetupWizard.showEvent()` calls it after `super().showEvent(event)`.
A Qt that paints the watermark some other way leaves this a no-op, and a null
watermark returns immediately.

#### 3.6.2 The Output-folders page must be answered

The folder was chosen with a checkbox, and leaving it unchecked counted as an
answer, which left Starbash with nowhere to write. It is now a pair of
`QRadioButton`s: *create the default output folders under
`~/Documents/starbash/repos`* (**pre-selected while the folders are missing**, so a
user who reads nothing and presses *Next* is still fine) or *create them under a
folder I choose instead* + *Choose folder…* (`QFileDialog.getExistingDirectory`,
prefilled at the documents dir). The page is complete only when the answer is one
of those two (`FoldersPage.isComplete()`), and `validatePage()` refuses the one
answer with nothing behind it ("somewhere else" with no folder picked) rather than
walking on. `refresh()` re-describes what the current answer will do — including
the "Press *Choose folder…*" note — and is driven off the *radio*, never off
widget visibility, because it runs while the wizard is hidden (in tests, and for a
frame during a page change).

#### 3.6.3 The Images page, and the closing actions

The page could be left with no folder, and the closing actions were live far too
early. `ImagesPage.isComplete()` now requires at least one raw-image folder — picked
on the page (`self._chosen`) or already added — and
`validatePage()` refuses to walk on while `_raw_image_repos()` is empty: it adds
the pick, reports the outcome in the status line, and if there is still nothing
(including "the folder could not be added") it stays put so the next *Next*
retries. The requirement is the **folder**, not FITS files inside it:
`_has_fits_images()` only looks one level down and plenty of people keep their
lights in `raw/M31/lights` — so the page *warns* ("No FITS images … directly
inside") but does not block on it. The two closing buttons are no longer theirs
from page 1 — see the gating bullet in §3.4; `SetupWizard._disable_action_buttons()`
is why.

The tests that pin all three (and the folders/images `validatePage` refusals) are in
§7; the review notes themselves are gone from the source, replaced by the comments
explaining the behaviour.

## 4. Components and files

| File | Change |
|---|---|
| `src/starbash/ui/qt/pages/wizard.py` | **rewrite** into a `QWizard`: an `IntEnum` of page ids, `SetupPage(QWizardPage)` base (`isComplete()`, `initializePage()`, `refresh()`, `validatePage()`), `WelcomePage`, `YouPage`, `FoldersPage`, `ImagesPage`, `ToolsPage`, `DonePage`, and `SetupWizard(QWizard)` (widget-level setup of §3.1, the single `nextId()`, `currentIdChanged` → `refresh()`, `action`); `run_setup_dialog(sb, parent=None, bus=None) -> str \| None` keeps its name so both call sites stay short. Stays in `pages/` — `gui.md` §4.5 places it there. |
| `src/starbash/tool/base.py` | add `Tool.invalidate_availability()` (base: a no-op returning `None`; `ExternalTool` overrides it to reset `_is_available = None`) — the *only* way to make a re-probe possible, since `is_available` caches on first access (`base.py:824`). Three lines, no behaviour change for existing callers. |
| `src/starbash/ui/qt/main_window.py` | `_on_setup` reloads the context and then applies the returned action; new `_apply_setup_action(action)` and a public `show_page_of_type(page_class) -> bool` (the loop currently inlined in `_on_reindex_requested`, which becomes a one-liner call to it). |
| `src/starbash/ui/qt/pages/processing.py` | rename `_start` → `start_run` (the public "run everything now" entry point); update the two call sites in `tests/unit/test_gui.py` (`:1435`, `:1520`). |
| `src/starbash/ui/qt/app.py` | `run()` schedules the wizard with `QTimer.singleShot(0, window.run_setup_wizard)` after `window.show()`, guarded by `is_wizard_complete(sb)` (imported from `pages/wizard.py` — the checklist is the one definition of "set up", §5.4). |
| `src/starbash/ui/qt/__init__.py` | add `desktop_session_available()` (+ `__all__`). |
| `src/starbash/main.py` | the no-subcommand branch described in §3.5; new global `--no-gui` option. |
| `tests/unit/test_setup_wizard.py` | **new** (`gui` marker) — see §7. |
| `tests/unit/test_gui_launch.py` | **new** (Qt-free, always runs) — `desktop_session_available()` and the `sb` no-arg decision. |
| `tests/unit/test_gui.py` | the two wizard tests move to the new module; `page._start()` → `page.start_run()`. |
| `tests/unit/test_cli.py` | `test_help_commands` (`:402`) asserts today's "bare `sb` prints help" — rewrite to pin the *new* contract (no display → help; the wizard decision is covered in `test_gui_launch.py`). |
| `AGENTS.md`, `README.md`/`doc/development.md` (wherever `sb` usage is listed) | one line: bare `sb` opens the GUI; `--no-gui` / `STARBASH_NO_GUI=1` force the CLI. |

## 5. Engine details that matter

### 5.1 Adding the images folder (worker + progress)

**What shipped is not this** (see §3.6.3): `ImagesPage` adds the picked folder
**synchronously** in `validatePage()` — `sb.add_local_repo(str(path))`, with the
outcome in the page's status line and nothing added to block on — so there is no
`add_repo_job`, no `run_async`, no `BusyIndicator` and no reindex progress. That
keeps the page and its tests simple; the cost to accept knowingly is the one this
paragraph was written to avoid: a genuinely large folder indexes on the GUI thread,
so *Next* sits there until it finishes. The design below is the fix if that ever
bites (the Repositories page already has the machinery), and it is deliberately left
as the recorded design rather than silently dropped.

Reuse `jobs.add_repo_job(report, token, path, kind)` (`ui/qt/jobs.py:47`) through
`workers.run_async` — never on the GUI thread (`add_local_repo` indexes FITS, and
a big folder takes minutes). The page:

- calls the picker (`QFileDialog.getExistingDirectory(self, "Choose the folder with your raw images")`),
  prefilled at the user's pictures dir when it exists;
- runs the job; shows a `BusyIndicator`/progress bar fed by the **event bus**
  (`EVENT_REINDEX_PROGRESS` / `EVENT_REINDEX_FINISHED`, the same events
  `RepositoriesPage` renders) when a `bus` was passed, else by the job's own
  `report()` strings (so the page is testable with no bridge);
- lists each added folder with its outcome and the count from the
  `EVENT_REINDEX_FINISHED` payload — `indexed`, which is the number of
  `.fit`/`.fits` files found (`app.py:844-881`), so a folder of JPEGs correctly
  reads as zero. It counts files *scanned*, not rows added, so a folder whose
  frames all fail to parse still reads as non-zero; the DB row count is the
  authoritative check if we ever need to be stricter;
- offers *Add another folder* (a second drive / camera folder is normal), and
  says "No images found in that folder — is that where your camera wrote them?"
  rather than ticking the item anyway.

The same page covers the re-run case: a pre-existing input repo is shown as
already done, so re-running the wizard does not nag.

### 5.2 The app context goes stale — reload once, afterwards

`add_repo_job` builds its **own** `Starbash` (its own SQLite connection), so the
GUI's shared context does not see the new repo until `MainWindow.reload_context()`
runs. Therefore:

- the wizard does **not** reload mid-flow. Nothing in pages 4–5 needs the shared
  repo manager: "did we add images?" is answered by the job result + the reindex
  events, and "have we got output folders?" is answered at open time (page 3) or
  by what this dialog itself created;
- `MainWindow` reloads once when the dialog closes (today's behaviour, kept even
  on Cancel — an early page may already have been committed, and the reload is
  cheap);
- the action (`start_run`, or navigating to Targets) runs **after** the reload,
  so the Processing page plans against the fresh context.

### 5.3 Qt lifetimes (this repo's favourite bug class)

- The dialog connecting to `EventBusBridge.received` must disconnect on close —
  the bridge is owned by `MainWindow` and outlives the dialog, so else a late
  `EVENT_REINDEX_*` calls into a dead widget. Connect a **bound method** (Qt drops
  it when the dialog's C++ object dies) *and* `disconnect()` in
  `reject()`/`done()`. The test-side half already exists (`tests/conftest.py`
  drains the pool and flushes `DeferredDelete`; see `qt-object-lifetimes.md`,
  `gui-widget-teardown.md`).
- Job callbacks passed as `partial`/lambda go through `workers.guard_callback`,
  and `github_login.py`'s `_closed` flag is copied, so closing the wizard
  mid-scan cannot raise `Internal C++ object already deleted`.

### 5.4 Start-up detection — `is_wizard_complete`, from the checklist

**As first built, the test was just the username**: `first_run(sb) = no
`user.name``. It was the second of the two options this plan originally listed
(config-file absence vs "not really set up"), chosen over the config-file check
because the *file* is created by any `Starbash()` context — `sb info`, even a
failed command — so its absence only ever means "Starbash has never run here",
and a user who aborted the wizard on the first screen would never see it again.

**Revised 2026-09-16: the test is the wizard's own checklist.** A name is only
one of four requirements — the output folders, a raw-image folder and Siril are
all equally required by the pages — so "has a name" declared a user set up who
then had nowhere to write and nothing to process with. The single source of truth
is now `setup_checklist(sb)` in `wizard.py`: a list of
`(title, complete, what to do about it)` rows, which the *closing page* draws and
`is_wizard_complete(sb)` folds into one bool::

```python
def is_wizard_complete(sb: Starbash) -> bool:
    return all(complete for _title, complete, _hint in setup_checklist(sb))
```

`app.run()` asks it (`if not is_wizard_complete(sb): QTimer.singleShot(...)`) and
`DonePage._checklist()` returns the same list, so **what the last page shows and
what reopens the wizard cannot drift** — the failure mode of two lists is a tick
beside a wizard that comes back every morning. The four rows, and the page each
mirrors:

| Row | Complete when | Mirrors |
|---|---|---|
| Your details | `user.name` is set | `YouPage.validatePage()` |
| Output folders | a `master` **and** a `processed` repo exist | `FoldersPage.validatePage()` |
| Your raw images | a raw-image repo exists at all | `ImagesPage.validatePage()` |
| Tools | no **required** tool (Siril) is missing | `ToolsPage.isComplete()` |

Two deliberate loosenesses, both to avoid re-asking a user who is fine:

- The raw-image row wants a *folder*, not FITS files inside it — exactly the bar
  `ImagesPage` enforces. Plenty of people keep lights a level down
  (`raw/M31/lights`), which the page itself says is normal; making the file count
  the start-up test would reopen the wizard on every launch for them.
- Only **required** tools block, matching `ToolsPage` and *Finish*: a missing
  *recommended* tool (GraXpert, StarNet, rc-astro) is a warning bar, not a
  wizard.

Consequences worth stating, because they shape §3.2:

- The username is no longer the completion marker, but page 2 is still blocking
  (via `isComplete()`, *not* a mandatory field — §3.2 explains why the asterisk
  form is actively wrong here): every row of the checklist has exactly one page
  that satisfies it, and a row that no page asks for would wedge the user out of
  the window entirely.
- The shipped *Welcome* copy makes no "every page can be skipped except your
  name" promise ("This wizard will guide you through the initial setup."), which
  is just as well: by §3.6.2/§3.6.3 the output folders and the raw-image folder
  are required too.
- A user who genuinely wants no name has the CLI's own out: it is not a
  supported state for the GUI, and `sb`'s CLI setup path keeps its current
  behaviour (this change does not touch `do_reinit`).
- The check reads the already-open user repo plus the repo manager and the tool
  registry, so `app.run()` can ask *after* constructing `Starbash("gui")` — no
  ordering trick needed (which also removes the "read it before the context
  creates the file" wart). All four probes are cheap and none of them scans a
  folder: the two repo lookups are in memory, and `init_tools()` has already run
  `Tool.preflight()` during `Starbash()` (app.py:210), so the tool statuses are
  cached by the time `run()` asks.

### 5.5 The launch guard (headless guarantee)

`tests/unit/test_cli_headless.py` proves `sb info` never imports Qt. The
no-subcommand path may import `starbash.ui.qt` (Qt-free) to ask
`desktop_session_available()`, and the env check happens **before** any
`import PySide6`. A new subprocess case in that module (`sb`, no args, `DISPLAY`
stripped, `PySide6` unimportable) will pin that: it must print the setup
questions / help and never load Qt.

## 6. Phased implementation

Each phase is independently reviewable and leaves the suite green.

- **Phase A — the `QWizard` skeleton (no behaviour loss).** `SetupPage` base +
  the six `QWizardPage` subclasses, the wizard-level options of §3.1, the single
  `nextId()`, `YouPage` keeping today's exact writes (name/email/analytics) and
  `FoldersPage` today's `_create_dirs` logic. `run_setup_dialog` keeps working
  from the File menu. Tests: page order, `Back`/`Next`, persistence, folder
  creation, the `IndependentPages` non-destructive-Back property.
- **Phase B — the images page.** File picker, `add_repo_job` via `run_async`,
  progress from `report()` and (when a bus is passed) the reindex events, the
  "no images found" case, multi-folder, re-run case. Tests with a stubbed
  `QFileDialog` and a recorded-then-really-run job (the `test_publish_page.py`
  pattern).
- **Phase C — the tools page and the Siril gate.** `ToolsPage` (rows from
  `tool_status`/`missing_tool_statuses`, *Install*/*Re-check*/*Ignore*),
  `isComplete()` gating on `ToolSeverity.REQUIRED`, the
  `Tool.invalidate_availability()` re-probe, and `validatePage()`. Tests: missing
  Siril blocks *Next*;
  installing (stubbed available) unblocks; a `RECOMMENDED`-only gap does not
  block; *Re-check* picks up a newly-installed tool (this is the test that fails
  if someone re-reads the cached flag).
- **Phase D — the checklist and the closing actions.** `DonePage`,
  `isComplete()` gating, the `action` result, `ProcessingPage.start_run()`,
  `MainWindow.show_page_of_type` + `_apply_setup_action`, `selection.clear()` on
  "process all". Tests: gating, each action, the refactored
  `_on_reindex_requested`.
- **Phase E — auto-show + bare `sb`.** `setup_checklist` + `is_wizard_complete(sb)`
  (the start-up test folded out of the closing page's own list — §5.4),
  `QTimer.singleShot` in `app.run()`, `desktop_session_available()`, the
  `main.py` branch and `--no-gui`, plus the doc lines and the rewritten/added
  test modules.
- **Phase F — docs & memory bank.** `gui.md` §5.9 gets a pointer to this plan and
  its status row updated; `AGENTS.md` (GUI + CLI surface) and
  `activeContext.md`/`progress.md` note the change.

## 7. Testing plan

The names below are the **shipped** ones — the table was written with working
titles, and anyone reading the plan against the tests needs the real names. All are
in `tests/unit/test_setup_wizard.py` unless another file is named.

| Test | What it pins |
|---|---|
| `test_the_wizard_has_the_six_documented_pages` | The six ids exist, in order, with `WELCOME` as the start page. |
| `test_next_id_skips_the_tools_page_when_nothing_is_missing` / `…_visits_the_tools_page_when_siril_is_missing` | The one dynamic edge in `nextId()`: page 4 → 6 with every tool present, page 4 → 5 when Siril is missing. |
| `test_the_username_is_required` | Empty name → page 2 incomplete; typing one completes it (page 2 is the first-run test, so this is §5.4's hinge). |
| `test_you_page_writes_the_same_keys_as_sb_user_setup` | `validatePage()` writes the CLI's keys through the real repos. |
| `test_you_page_refuses_a_blank_name` / `test_you_page_shows_the_documented_analytics_defaults` / `test_the_email_checkbox_needs_an_email` | The page's own refusals and defaults — the email checkbox stays inert until there is an email. |
| `test_the_left_pane_mark_is_centred` | **§3.6.1**: the label Qt built for the watermark is `AlignCenter` (found by `cacheKey`), and the logo's key differs, so the match is watermark-specific. |
| `test_folders_page_creates_the_default_output_folders` | **§3.6.2**: the default radio is pre-selected, `isComplete()` is True, and `validatePage()` creates a `master` **and** a `processed` repo through the real `add_local_repo`; both radios then hide and the caption reads "You already have these". |
| `test_folders_page_refuses_somewhere_else_with_no_folder` | **§3.6.2**: the custom radio with nothing picked → `isComplete()` *and* `validatePage()` False, no repo created, and the note says "Press *Choose folder…*". This is the case the old checkbox allowed. |
| `test_folders_page_uses_the_folder_it_was_given` | **§3.6.2**: a stubbed `QFileDialog` → the pick ticks the custom radio itself, and `master/`+`processed/` are created *inside* the chosen folder and registered as repos. |
| `test_images_page_reports_a_folder_of_fits_files` | The status line and the folder list report what the pick contains, before anything is added. |
| `test_images_page_notices_a_folder_without_fits_files` | **§3.6.3**: a folder of JPEGs says "No FITS images … directly inside" but is still a complete answer — one level down (`raw/M31/lights`) is normal. |
| `test_images_page_will_not_go_on_without_a_folder` | **§3.6.3**: nothing known and nothing picked → `isComplete()`/`validatePage()` False, the status names the requirement, and picking a folder unblocks it. |
| `test_images_page_adds_the_chosen_folder_once` | **§3.6.3**: `validatePage()` registers the pick (synchronously — §5.1), and leaving the page again does not add the same folder twice. |
| `test_tools_page_blocks_the_wizard_while_siril_is_missing` | Siril stubbed unavailable → `ToolsPage.isComplete()` False, so Qt disables *Next*; the page names Siril and offers its `install_url`. |
| `test_tools_page_is_complete_when_everything_is_present` | The happy path — it stubs `tool_statuses`, so it does not depend on what happens to be installed on the machine running the suite. |
| `test_tools_page_recheck_notices_a_tool_installed_meanwhile` | *Re-check* clears the cached probe (`Tool.invalidate_availability()`): fails if the page just re-reads `is_available`. |
| `test_done_page_gates_the_actions_but_not_finish` | Only a required tool gates *Finish*; the other three rows gate the two action buttons. |
| `test_done_page_enables_the_actions_once_the_checklist_is_ticked` | …and they come alive together once every row is ticked, with the caption naming what was missing. |
| `test_the_closing_checklist_refreshes_when_it_is_visited_again` | `IndependentPages` means `initializePage()` runs once, so the checklist is `refresh()`ed from `currentIdChanged`. |
| `test_the_closing_actions_start_disabled` | **§3.4 gating**: a freshly-built wizard has both custom buttons disabled, each with an explanatory tooltip — Qt builds them enabled and never consults `isComplete()`. |
| `test_the_closing_actions_are_armed_on_the_last_page_only` | **§3.4 gating**: the checklist arms them on page 6, and a page change back to page 1 disarms them again. |
| `test_the_custom_buttons_record_which_action_was_used` / `test_a_click_on_something_else_is_not_an_action` | The actions really are the wizard's own `CustomButton1`/`CustomButton2`, and only those two values become an action. |
| `test_run_setup_dialog_reports_the_closing_action` / `…_returns_none_when_cancelled` | `run_setup_dialog()` hands the action back to `MainWindow` instead of navigating itself. |
| `test_is_wizard_complete_needs_every_minimum` | **§5.4**: the start-up test asks each of the four minimums in turn — a username alone is *not* set up — and the raw-image row is satisfied by the *folder*, with only JPEGs inside it. |
| `test_is_wizard_complete_needs_the_required_tools` | Siril still missing → not set up, with everything else in place: the one thing that can block. |
| `test_the_last_page_and_the_start_up_test_share_one_definition` | `DonePage.blockers()` and `is_wizard_complete()` are the same list, before and after the minimums are met (the drift guard — two lists would show a tick beside a wizard that reopens). |
| `test_a_bare_sb_launches_the_gui_in_a_desktop_session` … `test_an_offscreen_platform_is_not_a_desktop_session` (`test_gui_launch.py`) | The `desktop_session_available()` guard: the opt-out flag, the offscreen/minimal platform, and Linux needing `DISPLAY`/`WAYLAND_DISPLAY`. |
| `test_a_broken_qt_install_falls_back_to_the_cli` (`test_gui_launch.py`) | `GuiUnavailableError` is caught and reported, never propagated. |
| `test_run_opens_the_wizard_on_a_first_run` / `test_run_reopens_the_wizard_when_a_minimum_is_missing` / `test_run_skips_the_wizard_once_setup_is_complete` (`test_gui_launch.py`) | The `QTimer.singleShot` trigger: a first run gets the wizard, a user *with* a name but without output folders/image folder gets it again, and a user whose whole setup is complete is never asked again. |
| `test_help_commands` (`test_cli.py`) | Bare `sb` without a session still prints the help output and exits 0, and `--no-gui` keeps exactly that behaviour whatever the session. |
| `test_sb_info_works_when_qt_is_unavailable` / `test_cli_never_imports_qt` (`test_cli_headless.py`) | The headless guarantee: `DISPLAY` stripped and `PySide6` unimportable → the CLI still works and imports neither Qt nor the GUI package. |

**Promised here but never shipped** — worth knowing before trusting the plan over
the tests: a `wizardStyle()`/pixmap-roles test (only the watermark alignment is
pinned, by `test_the_left_pane_mark_is_centred`), an *Ignore*-writes-the-user-config
case, a *Back*-keeps-the-answers round trip (`IndependentPages` is only pinned
indirectly), a recommended-tool-does-not-block case (covered only by
`test_tools_page_is_complete_when_everything_is_present` stubbing every status), and
the two `MainWindow._apply_setup_action` cases — *Process all* clearing the selection
and starting a run, and *Pick a target* navigating. The actions are currently
exercised only through `run_setup_dialog()`'s return value.

Mark the wizard/launch tests `gui` (except the two Qt-free modules) so
`-m "not gui"` still skips them; keep the Qt-free ones in the default set.

## 8. Risks and open questions

1. **Bare `sb` stops printing help** (whenever a display is available). Today
   `sb` is a discovery path for the command list. Recommended: it is exactly what
   was asked for, and `sb --help` keeps the list one keystroke away — but confirm,
   since an alias/script that runs `sb` with no args would now open a window.
2. **First-run detection is the username** (§5.4) — **decided**. Consequence to
   accept knowingly: a user who wants no name at all cannot dismiss the wizard in
   the GUI (the CLI path is unaffected). If that ever bites, the escape hatch is
   a *Skip for now* that writes a sentinel, not a return to the config-file test.
3. **"Process all my targets" clears the selection.** Correct for a genuine first
   run (the selection is empty anyway) and it is what `sb select any` means, but a
   user re-running the wizard loses a narrow selection. Alternative: keep the
   selection and just start the run — then the button does not literally mean
   *all*. Recommend clearing, with a tooltip saying "clears the current selection
   and processes every target".
4. **Starting a run from *Done* is a UI jump.** The wizard closes first and the
   Processing page starts planning immediately (`start_run`), so the user sees the
   task tree rather than a frozen dialog. Confirm that beats "navigate to
   Processing and let the user press Run".
5. **Modal at startup.** `QTimer.singleShot(0, …)` shows the wizard once the main
   window is visible; the window behind it is empty (no repos yet), so nothing is
   lost, but it is not disabled while open. Decide whether the automatic first-run
   wizard should be application-modal. Recommend yes for that case only.
6. **The skip-everything path.** If pages 3 and 4 are both skipped nothing can be
   processed, so *Done* then offers only *Finish* plus a link back to the images
   page ("Add your images to get started"). The wizard stays re-runnable from the
   File menu.
7. **Siril is a hard gate** — **decided** (§3.3): the user cannot leave the tools
   page, or finish the wizard, while a `REQUIRED` tool is missing. The cost to
   accept knowingly: a user on a machine where Siril *cannot* be installed is
   stuck (until [Cancel], which keeps whatever earlier pages wrote). We judged
   that better than today's outcome — a first run that fails mysteriously at the
   first Siril stage — and the page has the install link and *Re-check* right
   there. The narrower alternative (gate only *Process all*, let *Finish* pass) is a
   one-line change in `DonePage.isComplete()`, not a new override — §3.4.
8. **`QWizard`'s chrome on other platforms.** Verified on Linux with our theme
   (§3.1) and pinned by `ModernStyle`, but this has not been eyeballed on
   Windows/macOS. If the banner ever looks wrong there, the fix is
   `setPixmap`/`IgnoreSubTitles`/QSS for `QWizard > QLabel#qt_wizard_title`, not a
   return to a hand-rolled footer — flag it if a screenshot looks off.

## 9. Out of scope

- Any change to the CLI's own guided-setup text or questions (§2.1).
- The Settings page layout; it keeps the same keys (a *Run setup again* button
  there is optional).
- Bundling/downloading Siril or StarNet — the Tools row links to the existing
  `install_url` / *Ignore* flow from `tool-warnings.md`.
- The `targets-redesign` navigation model: *Pick a target* simply lands on the
  existing Targets page.