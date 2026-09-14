# Plan: structured per-session master selection (`sessions.masters`)

> **Status:** Implemented (2026-09-13) — see the tests listed in §6
> **Owner:** Kevin Hester
> **Last updated:** 2026-09-13
> **Depends on:** nothing (core data-model change; consumed by the GUI Targets screen — see `gui.md` §5.5)
> **Scope:** Replace the comment-carried "reason" strings in `sessions.toml` with a
> structured, machine-parseable per-session master selection, and make that
> selection authoritative on re-run.

## 1. Goal / summary

Today `Processing._resolve_input_master()` (`src/starbash/processing.py`) writes
the calibration candidates it scored into each session as two arrays of strings,
carrying the human explanation in a TOML **comment**:

```toml
[sessions.masters.bias]
used = [
    "zwoasi2600mcduo/2025-09-03_04-33-21/bias/master_bias_gain100.fit", # -169472 gain match, time Δ=9.0d (in future!), instrument mismatch
    ]
excluded = [
    "zwoasi2600mcduo/2025-09-03_04-53-21/bias/master_bias_gain100.fit", # -169472 gain match, time Δ=9.0d (in future!), instrument mismatch
    ]
```

The comment is for humans only: reading it back means scraping trivia off a
`tomlkit` item, and none of the individual match signals
(gain/temp/time/instrument/camera/filter/dimensions) survive as data. There is
also no way to say "the user chose this one" versus "the scorer picked it", so a
hand/GUI selection cannot be honoured on the next `sb process`.

This plan replaces the two string arrays with one **array-of-tables of scored
candidates** plus an explicit `selected` / `selected_by` pair, and makes
`selected_by = "user"` authoritative when processing re-runs.

## 2. Proposed schema (the thing to review)

Per session, per calibration type (`bias`, `dark`, `flat`):

```toml
[sessions.masters.bias]
# Repo-relative path of the master this session will use.
selected = "zwoasi2600mcduo/2026-07-03_05-54-41/bias/master_bias_gain100.fit"
# "auto" = the scorer's top pick; "user" = an explicit choice (GUI/CLI) that
# processing MUST honour on re-run.  Absent is read as "auto".
selected_by = "auto"

[[sessions.masters.bias.candidates]]
path = "zwoasi2600mcduo/2026-07-03_05-54-41/bias/master_bias_gain100.fit"
score = 31479.0
# Structured scoring evidence (all optional for legacy entries):
gain_match = true
gain_delta = 0.0
temp_delta_c = 0.3
time_delta_days = -0.0
in_future = false
instrument_match = true
camera_match = true
dimensions_match = true
# `filter_match` is only meaningful (and only written) for FLAT candidates.
# Human summary, kept as data (not a comment) so a reader can still print one line.
reasons = ["gain match", "temp Δ=0.3°C", "time Δ=-0.0d"]
```

Notes / rationale:

- **One list, not two.** `used` + `excluded` allowed the same master to drift
  between the two lists; a single `candidates` list plus `selected` has one
  authority. Ordering is by score so the file still reads "best first".
- **`selected_by` is the automation hook.** `"auto"` means "recompute freely on
  the next run"; `"user"` means "do not silently change this".
- **Structured evidence, not a comment.** Every signal the ranker computes is
  written as a typed key. The GUI can render "gain ✓ · temp Δ0.3°C · time
  Δ0.0d" without re-running the scorer or parsing English.
- **`reasons` is retained** as a TOML array of strings so the human-readable
  summary is still parseable data (and cheap to display) — it is *derived* from
  the structured keys, never the other way round.
- **Paths stay repo-relative** (as today) so the file is portable across
  machines and root moves.
- Optional fields (`camera`, `date`) were deliberately left out for now: they
  are derivable from the path plus the master's own metadata, and adding them
  bloats a file that already carries every frame.

### 2.1 Back-compatibility

Old files must keep loading. A legacy `[sessions.masters.<type>]` with
`used`/`excluded` string arrays is read as:

- `selected` = first entry of `used` (or `None`),
- `selected_by` = `"auto"`,
- one candidate per entry (used first, then excluded), with `path` set and all
  structured keys left unset (unknown).  **tomlkit does not preserve a comment
  written after an inline array item**, so the old `# reason` text is not
  recoverable — legacy candidates simply carry no `reasons`.  That lost evidence
  is itself the argument for the new table shape.

On the next write of that session the entry is upgraded in place to the new
shape. Reading never rewrites the file.

## 3. Core changes

### 3.1 `src/starbash/score.py` — emit structured candidates

- `ScoredCandidate` gains `details: dict[str, Any]` (default empty) alongside
  `score` / `reason`.
- Each ranker closure also writes its structured contribution into a shared
  `details` dict (the `reasons` list already works this way):
  - `rank_gain` → `gain_match`, `gain_delta`
  - `rank_temp` → `temp_delta_c`
  - `rank_time` → `time_delta_days`, `in_future`
  - `rank_instrument` → `instrument_match`
  - `rank_camera` → `camera_match`
  - `rank_camera_dimensions` → `dimensions_match`
  - `rank_flat_filter` → `filter_match` (only set when the candidate is a FLAT)
- Add `ScoredCandidate.to_toml_table() -> Table` building the
  `[[…candidates]]` table above (`path` from `candidate["path"]`, `score`
  rounded, structured keys, `reasons` as an array). `get_comment`/`__str__`
  stay for the human string.
- Keep `score_candidates()`'s signature and ordering unchanged.

### 3.2 `src/starbash/processing.py` — honour a user selection

In `_resolve_input_master()` (currently ~line 1587–1633):

1. Score candidates exactly as today.
2. Read the prior per-session entry: `self.session.get("masters", {}).get(imagetyp)`
   (already merged from `sessions.toml` by `ProcessedTarget._init_from_toml`).
3. Choose:
   - if prior `selected_by == "user"` and `selected` matches one of today's
     candidates (by `path`) → use that candidate, keep `selected_by = "user"`;
   - otherwise → `scored_masters[0]`, `selected_by = "auto"`; log a warning if a
     user selection no longer exists among the candidates.
4. Write `session_masters[imagetyp]` in the new shape:
   `selected`, `selected_by`, and `candidates` as an AoT of
   `ScoredCandidate.to_toml_table()`.
5. Keep populating `ci[imagetyp]` and the `abspath` call for the chosen master.

### 3.3 `src/starbash/processed_target.py` — the model view

New dataclasses (mirroring the `StageOption`/`ParameterOption` pattern;
re-exported from `ui/qt/services.py`):

```python
@dataclass
class MasterCandidate:
    path: str
    score: float | None
    selected: bool
    reasons: list[str]
    details: dict[str, Any]

@dataclass
class SessionMasterOption:
    type: str            # "bias" | "dark" | "flat"
    selected: str | None
    selected_by: str     # "auto" | "user"
    candidates: list[MasterCandidate]

@dataclass
class SessionOption:
    label: str           # e.g. "2025-08-25 · None · OnStep"
    key: tuple[str, ...] # _session_key(): (start, end, filter, imagetyp, object, telescop)
    masters: list[SessionMasterOption]
```

New methods:

- `ProcessedTarget.session_options() -> list[SessionOption]` — walks
  `self.sessions["sessions"]`, parses `[sessions.masters.<type>]` in both the
  new and legacy shapes (one `_parse_master_entry()` helper), and keeps only
  sessions that have at least one master entry (the "suitable sessions" the GUI
  shows). Ordered by `start`.
- `ProcessedTarget.save_master_selections(edits) -> None` — one read + one write
  of `sessions.toml` for a batch of `(session_key, master_type, path)` edits.
  Sets `selected` / `selected_by = "user"` on the matching `[[sessions]]` entry,
  creating the `masters.<type>` table when missing, and preserves every other
  key (frames, stages, metadata, comments). Never rewrites when `edits` is
  empty.
- A module-level `_parse_master_entry(raw) -> SessionMasterOption | None` used by
  both `session_options()` and tests.

### 3.4 GUI services

- `services.load_session_options(target_path) -> list[SessionOption]` — opens
  `ProcessedTarget.open(target_path)` and calls `session_options()`. **Runs on a
  worker** (see §5): it only touches files (no SQLite), so it is thread-safe,
  and `sessions.toml` can be multi-MB.
- `services.save_master_selections(target_path, edits)` — delegates to
  `ProcessedTarget.save_master_selections`.

## 4. Migration / rollout

- No on-disk migration step is required: readers accept both shapes and the
  first re-run (or first GUI save) of a session rewrites it in the new shape.
- No bump of `about.toml` `schema_version` is needed for this alone;
  `sessions.toml` has no schema marker today.

## 5. Risks / open questions

1. **`sessions.toml` size.** The file carries every frame's metadata (tens of
   thousands of lines). Parsing it on the GUI thread would visibly stall, so the
   GUI read must go through `workers.run_async` with a `BusyIndicator`; the
   write is a single read-modify-write and should run on a worker too
   (Save is an explicit button click, so a short busy state is acceptable).
2. **Where does an explicit selection come from?** This plan exposes
   `selected_by = "user"` and honours it. The GUI's picker (see `gui.md` §5.5)
   is the first producer; a CLI flag (`sb process --master ...`) could follow.
   *Confirm the GUI is enough for v1.*
3. **Naming.** `SessionOption` sits next to `StageOption`; `MasterCandidate` is
   distinct from `ScoredCandidate` (the scorer's runtime object). Open to
   renaming if confusing.
4. **`selected` as path vs index.** Path chosen — stable under re-scoring,
   readable, and robust if the candidate list is reordered.

## 6. Testing

- `tests/unit/test_score.py`: rankers populate the structured `details`; a
  round-trip through `to_toml_table()` preserves `score`, flags and `reasons`.
- `tests/unit/test_processed_target_sessions.py` (new): `_parse_master_entry`
  reads both shapes; `session_options()` filters to sessions with masters and
  preserves order; `save_master_selections()` round-trips, sets
  `selected_by = "user"`, creates a missing `masters.<type>` table, and leaves
  the rest of the document stable when no edits are supplied.
- `tests/unit/test_processing_masters.py` (new or extended): a prior
  `selected_by = "user"` entry is chosen over the top scorer; an `"auto"` entry
  is recomputed; the written entry uses the new shape.
- Existing `tests/unit/test_processed_target.py` / GUI / publish tests must stay
  green (legacy parsing keeps them working).

## 7. Phases

1. `score.py` structured `details` + `to_toml_table()` (+ tests).
2. `_resolve_input_master()` writes the new shape (+ test).
3. `ProcessedTarget` read/write API + legacy parsing (+ tests).
4. `_resolve_input_master()` honours `selected_by = "user"` (+ test).
5. GUI consumes it (see `gui.md` §5.5).
