# Target report metadata

## Status

**Proposed plan — stage R1**

This change enriches the generated target `starbash.toml` with structured,
machine-readable information about the observations that produced the target.
The information will be used by a later stage to generate human-friendly
reports.

## Goals

When processing a target, Starbash should generate an `about` section containing:

- the existing target summary and coordinates;
- one structured record per imaging session;
- the equipment used by each session, resolved against the merged equipment
  catalog;
- selected session-level FITS metadata;
- one structured record per source frame, including selected environmental and
  camera metadata;
- a stable in-memory domain model exposed as
  `ProcessedTarget.sessions_info`.

The generated data must be safe to persist, deterministic enough for tests and
diffs, and useful without requiring the original database to be available.

## Current architecture

`ProcessedTarget._generate_report()` currently renders only summary fields from
`self.p.sessions`. It obtains target identity and aggregate values from the
representative metadata attached to each session, then replaces the generated
`about` section in the target repository.

`ProcessedTarget` currently combines target configuration persistence, processing
state, cleanup, and report generation. It receives aggregate session rows from
`Processing`, while complete frame metadata is available separately through
`Starbash.get_session_images(session)`.

The database does not store an explicit session-to-frame relation. Frame lookup
therefore continues to use the existing session criteria (date range, target,
filter, telescope, and image type). This limitation should be documented and
covered by tests.

## Proposed domain model

Add report-specific dataclasses, preferably in `src/starbash/report.py`:

```python
@dataclass
class FrameInfo:
    metadata: dict[str, Any]


@dataclass
class SessionInfo:
    id: int | None
    date: str | None
    start: str | None
    end: str | None
    equipment: dict[str, Any]
    metadata: dict[str, Any]
    frames: list[FrameInfo]
```

The exact field names may change, but the model should keep report data separate
from raw SQLite rows. `metadata` should contain ordinary Python dictionaries,
not `tomlkit` nodes, and the model should not retain mutable references to
database or repository objects.

`ProcessedTarget` should expose:

```python
ProcessedTarget.sessions_info: list[SessionInfo]
```

The collection should be built after processing sessions are known and before
`close()` writes the target configuration. `_generate_report()` should consume
this model rather than perform database queries or equipment matching itself.

## Data collection

Add a focused collector, for example
`ProcessedTarget._collect_sessions_info()`, with this flow:

1. Iterate over `self.p.sessions` in the existing stable session order.
2. For each session, call `self.p.sb.get_session_images(session)` to retrieve
   its raw source frames.
3. Copy the session's identifying values and representative metadata.
4. Select the approved session metadata fields.
5. Select the approved fields from every source frame and add `wFWHM = -1` until
   FWHM measurement is available in the database.
6. Resolve equipment from the merged equipment catalog.
7. Construct `SessionInfo` and `FrameInfo` instances.

Missing FITS keys should be omitted rather than serialized as `None`, except for
the explicitly required placeholder `wFWHM = -1`. This keeps the generated file
compact and distinguishes missing measurements from real zero values.

### Session metadata

The initial whitelist is:

```text
FOCALLEN
FOCRATIO
GAIN
XPIXSZ
YPIXSZ
```

The source is the existing representative session metadata. If later work shows
that these values can vary within a session, the collector should define and
test an explicit policy rather than silently choosing a value.

### Frame metadata

The initial whitelist is:

```text
DEWPOINT
HUMIDITY
AMBTEMP
WINDGUST
WINDSPD
CCD-TEMP
```

Each frame record also contains:

```text
wFWHM = -1
```

The spelling and case of FITS keys should be preserved in the generated report.
Use the existing metadata blacklist, including site location fields, so the
report does not accidentally persist sensitive location data.

## Equipment matching

Create a reusable matcher outside `_generate_report()`, for example:

```python
match_equipment(metadata, equipment_catalog) -> dict[str, Any] | None
```

The matcher should:

- read the merged catalog from `sb.repo_manager.get("equipment", default=[])`;
- return a complete copy of each matching catalog record;
- match camera, telescope, filter, and filter wheel records against their FITS
  metadata fields;
- support both exact values and regular expressions (for example,
  `Askar V.*`);
- normalize the catalog's existing `fits.instrumen` spelling consistently with
  FITS `INSTRUME` without changing the catalog format in this stage;
- define deterministic behavior when multiple records match;
- represent unmatched equipment explicitly, either as `None` or a small record
  containing the observed FITS value.

The catalog currently contains equipment types such as `camera`, `filter`,
`mount`, `filterwheel`, and `telescope`. R1 should only emit equipment that can
be matched from metadata, while preserving the full matched catalog records.

## Persisted TOML shape

Keep the current summary format and add structured session data. The preferred
shape is an array of tables rather than an inline array of deeply nested
dictionaries because it is easier to read, extend, and round-trip with
`tomlkit`:

```toml
[about]
summary = """Processed data for Sh2 91.
Generated from 6 imaging sessions.
Total of 19.67 hours of exposure.
Filters used: HaOiii.
Observation dates: 2026-08-09, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-25, 2026-08-26.
"""

[about.target]
id = "Sh2 91"
ra = "19 35 44"
dec = "+29 51 09"

[[about.sessions]]
date = "2026-08-09"
start = "2026-08-09T20:00:00"
end = "2026-08-10T03:00:00"

[about.sessions.equipment]
telescope = { type = "telescope", vendor = "...", model = "...", fits = { telescop = "Askar V.*" } }

[about.sessions.metadata]
FOCALLEN = 600.0
FOCRATIO = 7.5
GAIN = 100
XPIXSZ = 3.76
YPIXSZ = 3.76

[[about.sessions.frames]]
[about.sessions.frames.metadata]
DEWPOINT = 12.2
HUMIDITY = 94.0
AMBTEMP = 13.1
WINDGUST = 5.400432
WINDSPD = 2.200176
CCD-TEMP = -9.9
wFWHM = -1
```

The exact TOML layout is an implementation detail, but the logical hierarchy
must remain `about -> sessions -> frames`. The generated section should replace
previous generated session records on each run, just as the current summary is
regenerated.

## Persistence and compatibility

Do not discard existing processing state in `[[sessions]]`, especially per-session
`stages` and `masters` data. Keep report data under `about.sessions` so it is
clearly generated report output and cannot collide with the existing processing
session state. `ProcessedTarget.sessions_info` remains the single source for
building that section.

Generated report data should be written only when the target has usable session
data. Existing user-authored configuration outside generated sections must be
preserved.

## Implementation phases

### Phase 1 — model and metadata policy

- Add `FrameInfo` and `SessionInfo`.
- Add metadata whitelist and sanitization helpers.
- Add `ProcessedTarget.sessions_info` initialization.
- Add unit tests for missing fields, preserved types, blacklist handling, and the
  `wFWHM` placeholder.

### Phase 2 — equipment resolution

- Implement the catalog matcher.
- Add exact-match and regex-match tests for each supported FITS key.
- Add tests for no match and deterministic multiple matches.
- Return copied ordinary dictionaries from the matcher.

### Phase 3 — session collection

- Implement `_collect_sessions_info()` using `get_session_images()`.
- Define ordering and duplicate/missing-frame behavior.
- Populate `sessions_info` before report generation.
- Test representative metadata versus per-frame metadata sources.

### Phase 4 — TOML generation

- Refactor `_generate_report()` to render summary fields and serialize
  `sessions_info`.
- Use explicit `tomlkit` tables/AoTs for nested data instead of interpolating
  nested structures into the text template.
- Preserve existing processing state and user configuration.
- Add write/read round-trip tests for equipment, metadata, frames, and repeated
  regeneration.

### Phase 5 — integration validation

- Run the existing `ProcessedTarget`, database, TOML, and workflow tests.
- Add one end-to-end fixture with multiple sessions and multiple frames.
- Verify that generated reports contain no site-location metadata and remain
  valid TOML.
- Document the generated schema for the future report generator.

## Acceptance criteria

- `ProcessedTarget.sessions_info` contains one `SessionInfo` per processed
  session and the expected `FrameInfo` records.
- Session and frame metadata follow the whitelists above.
- `wFWHM` is present with value `-1` when no measured value exists.
- Equipment records are matched from the merged defaults/catalog, including
  regex-based catalog entries.
- Unmatched equipment and missing metadata do not crash processing.
- Generated TOML parses successfully after writing and reloading.
- Existing stages, masters, overrides, and user-authored configuration survive
  report regeneration.
- Existing summary output remains compatible unless intentionally revised.

## Decisions required before implementation

The following decisions are confirmed for R1:

1. Store the generated records under `about.sessions`.
2. Use the representative image's metadata for session-level values. R1 does
  not need to detect or report metadata conflicts between frames.
3. Emit matched `telescope`, `camera`, `filter`, and `filterwheel` records. Do
  not emit `mount` records yet; mount support is reserved for a later stage.
4. For unmatched equipment, create the appropriate equipment entry from the
  observed FITS value and leave the catalog-specific fields unset. This keeps
  the report useful while making missing catalog coverage visible.
5. Do not persist frame paths or database IDs in `FrameInfo`; frame reports only
  need the selected metadata.
6. Sort sessions chronologically by session date/start time and frames
  chronologically by frame datetime (`DATE-OBS`, with the existing date fields
  as fallback where necessary).
7. Apply the existing metadata blacklist. No separate report-specific privacy
  policy is needed for R1.

These decisions remove the corresponding implementation choices from scope.
The plan should still define deterministic fallback behavior for missing dates,
missing FITS values, and duplicate equipment matches in the tests.
