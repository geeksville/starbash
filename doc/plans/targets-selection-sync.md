# Plan: Targets page ⇄ `sb select` synchronisation

**Status:** implemented (2026-09-14) — `just lint` clean, full suite **1094 passed**.
Design record for the Targets screen:
[`gui.md`](gui.md) §5.5; the build record of the redesign itself:
[`targets-redesign.md`](targets-redesign.md).

## Goal

Make the **Targets page** a second *editor* of the persistent session selection, so
its target list, its single-target detail pane, and `sb select` can never disagree:

1. The target list **always lists every processed target**.  The rows named by the
   current selection are **pre-highlighted**, so arriving at the page shows the
   current selection and a click edits it (nothing is ever hidden).
2. A **plain click** on a row makes that target the *only* selected target;
   **Ctrl+click** toggles a row in/out of the set.  The resulting set is written
   straight into `sb.selection` - the same object `sb select` and the Sessions
   page read/write - so the CLI agrees immediately.
3. The **right pane** (the target explorer: `Sessions`/`Stages` tree, option
   editor / master picker, path label, Save/Undo) is shown **only when exactly one
   target row is highlighted**.  With zero or several highlighted the pane holds a
   short hint instead, and the previously loaded target is cleared so no stale
   stages/masters stay editable.
4. With **no target filter** set (`sb select any`, or a fresh install), *every* row
   is pre-highlighted: no filter means every target is in effect, which is what
   `sb select` says too.

## Decisions (confirmed with the user, 2026-09-14)

- **Never narrow the list.**  The page is a picker, so a row set filtered to the
  current selection would leave every other target unreachable.  Filtering is out;
  pre-highlighting is in.
- **Empty selection = all rows highlighted** (on arrival), faithful to
  `sb select`'s "no filter selects everything".  The page then opens with the hint
  pane (no single target to edit) until the user clicks one.
- **The pre-highlight is a refresh-time default only.**  If the user ctrl+clicks
  the last highlighted row off (writing an empty target filter), the page shows an
  empty highlight - it does *not* immediately re-expand to all rows, which would
  look like a feedback loop.  Navigating away and back re-applies the default.
- **Right pane shows a hint, not nothing.**  Hiding the pane outright would make
  the target list jump between 22 % and 100 % of the page width as rows are
  clicked (the splitter's `_TARGET_LIST_SHARE` default), so the pane stays put and
  carries a one-line explanation instead.  The *explorer* (stages, sessions,
  editor, path, Save/Undo) is genuinely absent, which is the substantive point.
- **Qt already provides the click semantics.**  A throwaway offscreen probe
  confirmed that with `ExtendedSelection` Qt fires `pressed` *then*
  `selectionChanged`, collapses a plain click on an already-highlighted row to that
  row, and leaves `currentIndex()` on the clicked row - so no custom
  collapse/event-filter code is needed; the page simply follows the highlight.

## Approach

One shared object makes the sync possible at all: every GUI page is handed the same
`Starbash`, so `sb.selection` is the one `Selection` instance the CLI writes via
`sb select` and that `SelectionPanel` writes on the Sessions page.  The Targets
page therefore only has to *read* it (to pre-highlight) and *write* it (on a click);
no cross-page signal is needed, because `MainWindow` refreshes the arriving page on
navigation and `SessionsPage.refresh()` re-reads the selection through
`SelectionPanel.load()`.

### `src/starbash/ui/qt/services.py`

- Replace `preferred_target(sb) -> str | None` (only used by the Targets page, to
  pick `targets[0]`) with `selected_targets(sb) -> list[str]`, returning the whole
  selection target list.  Update `__all__`.

### `src/starbash/ui/qt/pages/targets.py`

- **Table**: `ExtendedSelection` after `make_table()` (which sets
  `SingleSelection`, right for the other pages); everything else stays.
- **Right pane**: wrap the existing explorer `QWidget` and a new hint `QLabel` in a
  `QStackedWidget`, so the pane keeps its width and swaps content.
- **State**: `self._selected_names: list[str]` - the highlighted target names, i.e.
  the set last read from or written to the selection.  It answers "did the user
  change anything?" and lets a cancelled unsaved-edit prompt restore the previous
  highlight.
- **`refresh()`**: load all rows, take `selected_targets(sb)`, expand an empty
  target list to every row's name (decision above), and `_select_targets(names)`.
- **`_select_targets(names)`**: highlight exactly the matching rows under
  `_guard` (so the resulting `selectionChanged` does not write back), then
  `_sync_pane()`.
- **`_sync_pane()`**: exactly one name -> show the explorer and `_load_target(that
  row)`, skipping the reload when it is already the loaded target so a cancelled
  prompt cannot discard in-memory edits; otherwise -> show the hint and
  `_load_target(None)`.
- **`_on_target_selected()`** (the user-driven path): read the highlighted names;
  when the set changed, resolve unsaved edits for the target being left (cancelling
  restores the previous highlight and stops); then write `set_targets(names)`
  (best-effort, failures reported via `status`) and apply `_select_targets(names)`.
- **Delete the vestigial `_desired_target`** - nothing has assigned it since the
  redesign; `refresh()` is its only reader.

## Phased sequence

1. `services.py`: `preferred_target` -> `selected_targets` (+ `__all__`).
2. `targets.py`: multi-select, right-pane stack, highlight/write logic, pane sync.
3. Tests in `tests/unit/test_targets_page.py`; update the two existing selection
   tests whose meaning changed.
4. `just lint`, then `poetry run pytest -q`; update `gui.md` §5.5 and the memory
   bank (`activeContext.md`, `progress.md`).

## Testing strategy

GUI tests in `tests/unit/test_targets_page.py` (marked `gui`, headless through
`QT_QPA_PLATFORM=offscreen`), asserting resulting *state* rather than calls:

- `sb select target X` pre-highlights X's row, and only that row.
- No target filter -> every row highlighted, hint pane shown, nothing loaded.
- A target filter matching no processed target -> no highlight, hint pane, nothing
  loaded, and **no** write back to the selection.
- A plain click on a row -> `selection.targets == [that]` (including collapsing a
  second, ctrl+clicked row).
- Ctrl+click toggles a second target in and back out; two highlighted -> hint pane.
- Exactly one highlighted -> explorer pane visible with that target's stages;
  zero/several -> hint pane, `_loaded_target is None`.
- Multi-selecting away from a dirty target asks first, and Cancel restores both the
  previous highlight and the in-memory edits.

## Risks / open questions

- **A write per click.**  `Selection.set_targets()` persists to the user config
  immediately; that is the point (the CLI must see it) and the file is small, but
  it does mean the *selection* needs no Save button while stage edits still do.
- **Persisted-but-unprocessable targets.**  A selection naming a target with no
  output directory highlights nothing; the page says so through the hint, rather
  than faking a selection.  Explicitly out of scope.
- **Keyboard-driven selection changes** (arrows/Shift+arrows) also write, since the
  highlight *is* the selection; that is consistent, but worth watching in review.