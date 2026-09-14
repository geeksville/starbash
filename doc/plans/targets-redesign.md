# Plan: Targets screen redesign (sequenced execution plan)

> **Status:** Implemented (2026-09-13) — kept as the record of *how* it was built.
> `just lint` clean (0 basedpyright errors); full suite green.
> The screen *design* lives in `gui.md` §5.5 and the data model in
> `session-masters.md`; this file is the step-by-step execution order.

## [Overview]

Redesign the GUI **Targets** screen (launched by `sb gui`) so the left column is
a narrow target picker while the right ~75 % is a target explorer, and in the
same pass replace the comment-carried calibration "reason" strings in
`sessions.toml` with a structured, machine-parseable per-session master
selection that becomes authoritative on re-run.

Scope, context and approach:

- **Context.** `TargetsPage` (`src/starbash/ui/qt/pages/targets.py`) currently
  shows a 2-column table (Target + Output) at ~66 % width on the left and a
  single stages tree + option editor on the right. Downstream, `Processing`
  (`src/starbash/processing.py`) records the calibration candidates it scored for
  each session into `sessions.toml` under `[sessions.masters.<type>]` as two
  string arrays whose explanation lives in a TOML **comment** — not parseable, and
  with no way to express (or honour) a human choice.
- **Approach.** (1) Shrink the target list to the Target column only. (2) Turn
  the right pane into one `QTreeWidget` with two top-level groups — `Stages`
  (existing behaviour) and `Sessions` (new; shown only when `sessions.toml`
  records sessions with masters) — over a `QStackedWidget` detail pane that
  swaps between the existing option editor and a new `MasterPicker`. (3) Read
  sessions/masters through new `ProcessedTarget` accessors, on a worker (the file
  is multi-MB). (4) Replace the masters schema with one `candidates` array of
  tables plus `selected` / `selected_by`, accepting the legacy shape on read, and
  make `selected_by = "user"` authoritative in `_resolve_input_master()`.
- **Design docs.** `doc/plans/gui.md` §5.5 is the screen design; the data-model
  change is specified in the new `doc/plans/session-masters.md`. This file is the
  sequenced execution plan.
- **Non-goals.** Per-session *stage* exclusion editing, an in-app TOML editor, a
  "Reprocess target" button, and a CLI flag for choosing a master.

## [Types]

New dataclasses in `src/starbash/processed_target.py` (re-exported from
`src/starbash/ui/qt/services.py`, mirroring the existing
`StageOption`/`ParameterOption` pattern):

```python
@dataclass
class MasterCandidate:
    path: str                      # repo-relative master path
    score: float | None
    selected: bool
    reasons: list[str]             # human summary, kept as data
    details: dict[str, Any]        # structured evidence (see below)

@dataclass
class SessionMasterOption:
    type: str                      # "bias" | "dark" | "flat"
    selected: str | None           # repo-relative path of the chosen master
    selected_by: str               # "auto" | "user"
    candidates: list[MasterCandidate]

@dataclass
class SessionOption:
    label: str                     # "2025-08-25 · None · OnStep"
    key: tuple[str, ...]           # ProcessedTarget._session_key(...)
    masters: list[SessionMasterOption]
```

Extended type in `src/starbash/score.py`:

```python
@dataclass
class ScoredCandidate(AsTomlMixin):
    candidate: dict[str, Any]
    score: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)  # NEW
    def to_toml_table(self) -> Table: ...                  # NEW
```

`details` keys (all optional; written only when computed):
`gain_match: bool`, `gain_delta: float`, `temp_delta_c: float`,
`time_delta_days: float`, `in_future: bool`, `instrument_match: bool`,
`camera_match: bool`, `dimensions_match: bool`, `filter_match: bool`
(flat candidates only).

On-disk `sessions.toml` shape written by processing:

```toml
[sessions.masters.bias]
selected = "<repo-relative path>"
selected_by = "auto"            # or "user"

[[sessions.masters.bias.candidates]]
path = "<repo-relative path>"
score = 31479.0
gain_match = true
gain_delta = 0.0
temp_delta_c = 0.3
time_delta_days = -0.0
in_future = false
instrument_match = true
camera_match = true
dimensions_match = true
reasons = ["gain match", "temp Δ=0.3°C", "time Δ=-0.0d"]
```

Legacy shape (read-only compatibility): `[sessions.masters.<type>]` with
`used = [<string>, ...]` / `excluded = [<string>, ...]`; `selected` = first
`used` entry, `selected_by = "auto"`, each entry becomes a candidate with
`reasons = [<comment>]` and `details = {}`.

A new type alias for a save edit lives in `processed_target.py`:

```python
MasterSelectionEdit = tuple[tuple[str, ...], str, str]  # (session_key, type, path)
```

## [Files]

**New files**

- `src/starbash/ui/qt/widgets/master_picker.py` — `MasterPicker` widget: one
  `(session, calibration type)`'s candidate list with a radio-style check column,
  a score/evidence row, "Reset to automatic", and a `selectionChanged` signal.
- `tests/unit/test_processed_target_sessions.py` — read/write round-trip +
  legacy parsing for the new `sessions.masters` schema.
- `tests/unit/test_processing_masters.py` — `_resolve_input_master()` honours a
  user selection and writes the new shape.
- `doc/plans/session-masters.md` (already written) — the data-model design doc.

**Modified files**

- `src/starbash/score.py` — add `ScoredCandidate.details` +
  `to_toml_table()`; rankers record structured values.
- `src/starbash/processing.py` — `_resolve_input_master()` honours
  `selected_by = "user"` and writes the structured shape.
- `src/starbash/processed_target.py` — new dataclasses, `session_options()`,
  `save_master_selections()`, `_parse_master_entry()`; export the new names in
  `__all__`.
- `src/starbash/ui/qt/services.py` — import/re-export the new dataclasses; add
  `load_session_options()` and `save_master_selections()`.
- `src/starbash/ui/qt/models.py` — `TARGET_COLUMNS` becomes the single
  `Target` column (drop `Output`).
- `src/starbash/ui/qt/pages/targets.py` — the redesign: narrow list, grouped
  tree (`Stages` + `Sessions`), detail `QStackedWidget`, dirty/save/undo across
  both files, async session load with `BusyIndicator`.
- `tests/unit/test_targets_page.py` — update the affected tests and add new
  coverage (see [Testing]).
- `doc/plans/gui.md` — §5.5, Phase 5 and the follow-ups list (already updated).
- `.clinerules/plans.md` — register `session-masters.md` (already updated).
- `.clinerules/memory-bank/{activeContext,progress}.md` — record the redesign
  and the schema change once implemented.

**Removed / moved**

- `TARGET_COLUMNS`'s `Output` column and its `link_key="path_url"` (the output
  path stays as the right pane's clickable `_path` label; `load_targets()`
  keeps returning `path`/`path_url`).
- `test_target_table_output_column_is_a_link` is deleted (superseded by the
  path-label link test).

## [Functions]

**New**

- `score.py`: `ScoredCandidate.to_toml_table() -> tomlkit.items.Table`.
- `processed_target.py`:
  - `_parse_master_entry(raw: Any) -> SessionMasterOption | None`
  - `ProcessedTarget.session_options() -> list[SessionOption]`
  - `ProcessedTarget.save_master_selections(edits: list[MasterSelectionEdit]) -> None`
- `services.py`:
  - `load_session_options(target_path: str) -> list[SessionOption]`
  - `save_master_selections(target_path: str, edits: list[MasterSelectionEdit]) -> None`
- `master_picker.py`: `MasterPicker.set_context(label, option)` /
  `MasterPicker.selection()`.

**Modified**

- `score.py::score_candidates` — thread the shared `details` dict through each
  `rank_*` closure (signature and ordering unchanged).
- `processing.py::_resolve_input_master` — after scoring, consult the prior
  `self.session["masters"][imagetyp]`; pick a user selection when
  `selected_by == "user"` and the path is still a candidate, else the top
  scorer; write `selected` / `selected_by` / `candidates`.
- `processed_target.py::__init__` / `open()` — nothing structural; the new
  accessors use the lazily-loaded `sessions` document as-is.
- `services.py::__all__` — add the new names.
- `targets.py`:
  - `_build()` — splitter share `_TARGET_LIST_SHARE` 0.66 → ~0.22; build the
    grouped tree and the detail `QStackedWidget`.
  - `_rebuild_tree()` — insert the `Stages` group, stage rows as its children;
    add the `Sessions` group when session options are present.
  - `_on_tree_selection_changed()` — dispatch: stage → description; param →
    editor; master type → `MasterPicker`; session → summary.
  - `_is_dirty()` / `_save()` / `_undo()` / `_load_target()` — include the
    master-selection model, writing `sessions.toml` only when it changed.
- `targets.py::_on_item_changed` — unchanged logic, but must ignore the new
  non-stage group items (guard on `_stage(name) is None`).

**Removed**

- None (no public function is deleted).

## [Classes]

**New**

- `MasterPicker(QWidget)` — `ui/qt/widgets/master_picker.py`. Holds a
  `QTableWidget` with columns `[✓, Master, Score, Why]`, a radio-style exclusive
  check column, a header label and a *Reset to automatic* button; emits
  `selectionChanged(object)` with `(session_key, type, path)`.
- `MasterCandidate`, `SessionMasterOption`, `SessionOption` (dataclasses, above).

**Modified**

- `ScoredCandidate` — new `details` field and `to_toml_table()`.
- `TargetsPage` — new state (`_sessions_original` / `_sessions_current`,
  `_session_items`, `_master_items`, `_busy`), new `_detail` stack, and the
  context-sensitive selection dispatch.
- `DictTableModel` — no change (the narrower `TARGET_COLUMNS` is data).

**Removed**

- None.

## [Dependencies]

None. All new code uses libraries already in the project (`tomlkit`, PySide6)
and existing internal modules (`workers.run_async`, `BusyIndicator`, `theme`).
No new package, no version bump.

## [Testing]

- **Core schema** — `tests/unit/test_processed_target_sessions.py` (new):
  legacy `used`/`excluded` parsing; new-shape round-trip via
  `save_master_selections`; `selected_by` becomes `"user"`; a missing
  `masters.<type>` table is created; a no-op edit list leaves the file
  unchanged.
- **Scoring** — extend `tests/unit/test_score.py`: rankers populate `details`;
  `to_toml_table()` preserves score/flags/`reasons`.
- **Processing** — `tests/unit/test_processing_masters.py` (new): a prior
  `selected_by = "user"` entry wins over the top scorer; an `"auto"` entry is
  recomputed; the written entry uses the new shape.
- **Page** — update `tests/unit/test_targets_page.py`:
  - delete `test_target_table_output_column_is_a_link`;
  - update `test_target_list_defaults_to_two_thirds_of_the_width` →
    narrow-share assertion, and any `topLevelItemCount`/`topLevelItem` accesses
    for the new `Stages` group;
  - add: `Sessions` group appears only with masters; selecting a master node
    shows the `MasterPicker`; choosing a candidate marks the page dirty; Save
    writes `selected_by = "user"`; Undo restores the previous selection; the
    detail pane hides when nothing applies;
  - keep the existing stage/param/editor/dirty/nav-guard tests green.
- **Validation gates** — `just lint` (format + `ruff check` + `basedpyright`,
  which rewrites files) then `poetry run pytest -q`; re-run tests after lint if
  it reformatted anything. GUI tests use `QT_QPA_PLATFORM=offscreen` and the
  `gui` marker.

## [Implementation Order]

1. **Schema core (independent of the GUI).** Add `ScoredCandidate.details` +
   `to_toml_table()` and ranker recording; extend `test_score.py`.
2. **Model API.** Add the dataclasses, `_parse_master_entry()`,
   `ProcessedTarget.session_options()` and `save_master_selections()`; add
   `test_processed_target_sessions.py`.
3. **Processing honours the selection.** Update `_resolve_input_master()` to
   pick/write the new shape; add `test_processing_masters.py`.
4. **GUI services.** Re-export the dataclasses and add
   `load_session_options()` / `save_master_selections()`; extend
   `test_gui.py` service coverage.
5. **Narrow target list.** Reduce `TARGET_COLUMNS` and `_TARGET_LIST_SHARE`;
   update/adjust the affected page tests.
6. **Grouped tree + detail stack.** Build the `Stages`/`Sessions` groups and
   the `QStackedWidget`; wire selection dispatch; keep stage/param behaviour
   intact.
7. **`MasterPicker`.** Build the widget, wire loading (async + `BusyIndicator`),
   dirty tracking, Save/Undo across both files, and the new page tests.
8. **Docs + memory bank.** Confirm `gui.md` §5.5, `session-masters.md` and
   `.clinerules/plans.md` match the implementation; update
   `.clinerules/memory-bank/{activeContext,progress}.md`.
9. **Gate.** `just lint` → `poetry run pytest -q` (GUI tests included) → fix
   anything lint rewrote and re-run.