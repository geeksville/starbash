# Registration metrics from Siril

## Status

**Design plan — implementation not started.**

This plan builds on [`doc/design/report.md`](report.md), which already defines
the generated `about.sessions` report structure and the `SessionInfo`/
`FrameInfo` model.

The feature should record Siril registration measurements against the original
input-image database rows after the OSC stacking stages run. The measurements
will then be available to later processing tools and to generated reports.

The first implementation is deliberately limited to the OSC processing path in
`src/starbash/recipes/osc.py`. Other recipes, including
`starbash-recipes/osc/stack_osc.toml`, are out of scope for this change.

## Confirmed decisions

The following decisions were made while preparing this plan:

1. Store the five metrics using the names from the existing Siril parsing
	 example:

	 ```text
	 FWHM
	 Amplitude
	 Roundness
	 Background
	 Stars
	 ```

2. Expose all five metrics in the generated report, not only `FWHM`.
3. Update only source database rows represented by selected, mapped members of
	 the merged sequence. Do not update every source row merely because it was a
	 candidate input.
4. For now, support the merged Ha sequence only:

	 ```text
	 all_r_Ha_bkg_pp_light_.seq
	 ```

	 Single-input stacks, OIII, and the Sii-only intermediate Ha-named stack are
	 deferred.
5. Use the existing application-owned database connection. Do not construct a
	 second `Database` instance inside `osc.py`.
6. If parsing or provenance validation fails, log a warning and leave existing
	 metadata unchanged. The update must still use assertions to detect incorrect
	 counts and duplicate/missing mappings before any write occurs.

## Current implementation relevant to this work

### Report model

The report work from `doc/design/report.md` is already partially implemented:

- `src/starbash/report.py` defines `FrameInfo` and `SessionInfo`.
- `frame_info()` currently adds the placeholder `wFWHM = -1`.
- `src/starbash/processed_target.py` collects session/frame metadata in
	`_collect_sessions_info()` and writes `about.sessions` in `_generate_report()`.
- `src/starbash/publish/github.py` reads `about.sessions`, but currently plots a
	constant `1` for every FWHM point.

The FWHM implementation should replace these placeholders with real values and
omit registration keys that are not present. It must not write fake values such
as `-1` or `1` to indicate missing data.

### OSC processing

`src/starbash/recipes/osc.py` contains the relevant `fixme-ai` guidance:

- In `make_stacked()`, filtering and merging changes the mapping between source
	images and the final merged sequence. The mapping must not be reconstructed
	from the final sequence number alone.
- In `osc_process()`, parse only the merged Ha sequence needed for this feature.

The current flow is approximately:

```text
source FITS files
	-> per-session Siril sequences
	-> r_Ha_bkg_pp_light_s<ID>_NNNNN.fit
	-> merge into all_r_Ha_bkg_pp_light_NNNNN.fit
	-> register all_r_Ha_bkg_pp_light_
	-> write all_r_Ha_bkg_pp_light_.seq
	-> stack
```

The registration sequence is created by the `register` command in
`make_stacked()`. It exists only after the Siril command completes.

### Database

`src/starbash/database.py` stores arbitrary image metadata as JSON in the
`images.metadata` column. No schema migration is needed for these five keys.

Relevant existing APIs are:

- `Database.upsert_image()` — suitable for importing a complete FITS record,
	but not for merging a small update into an existing row.
- `Database.get_image()` — retrieves one row by repository URL and relative
	path.
- `Starbash.get_session_images()` — retrieves source image rows and adds
	absolute paths.
- `Starbash.db` — provides the application-owned `Database` instance.

Add a dedicated metadata-update API rather than calling `upsert_image()` with a
partial record. The update must preserve every unrelated metadata key and must
not modify `path`, `date_obs`, `date`, or `imagetyp`.

## Data contract

### Registration result

`src/starbash/siril/import_registration.py` should return a list of frozen
dataclasses rather than dictionaries. A suitable shape is:

```python
@dataclass(frozen=True)
class RegistrationResult:
		sequence_index: int
		selected: bool
		fwhm: float
		amplitude: float
		roundness: float
		background: float
		stars: int
```

The public field names may use the project's preferred style, but the parser
must retain both the sequence index and selected state. The five values in the
sample `R0` line are:

| Token | Meaning | Stored metadata key |
| ---: | --- | --- |
| `parts[1]` | FWHM | `FWHM` |
| `parts[2]` | amplitude / weighted registration value | `Amplitude` |
| `parts[3]` | roundness | `Roundness` |
| `parts[5]` | background | `Background` |
| `parts[6]` | detected stars | `Stars` |

`parts[4]` is the shift/angle field and is not part of the five requested
metrics. `parts[7]` is the transformation method, followed by transformation
matrix values.

The parser should not silently discard additional columns. It may ignore the
transformation matrix for this feature, but should document that choice and
validate that the required columns are present.

### Database metadata

On a successful update, the source image row receives:

```python
{
		"FWHM": result.fwhm,
		"Amplitude": result.amplitude,
		"Roundness": result.roundness,
		"Background": result.background,
		"Stars": result.stars,
}
```

Use the native numeric types from the parser: floating-point values for the
first four metrics and an integer for `Stars`.

### Report metadata

`src/starbash/report.py` should include all five keys in frame metadata when
they exist in the database row. Missing keys must be omitted:

```toml
[[about.sessions.frames]]
[about.sessions.frames.metadata]
FWHM = 3.42
Amplitude = 8.91
Roundness = 0.82
Background = 0.0012
Stars = 528
```

The existing metadata blacklist continues to apply. No placeholder `wFWHM`
field should be emitted after this change; use the real `FWHM` key consistently
in the database, report, and chart.

## Siril `.seq` parser plan

### File and symbol

Implement the parser in:

```text
src/starbash/siril/import_registration.py
```

Replace the current FIXME/sample `parse_siril_seq()` implementation with a
typed parser and an exported `RegistrationResult` dataclass.

### Format handling

The supplied sequence begins with records similar to:

```text
#S 'sequence_name' start_index nb_images nb_selected fixed_len reference_image version variable_size fz_flag drizzle
S 'all_r_Ha_bkg_pp_light_' 1 387 386 5 91 6 0 0 0
L 1
I 1 1
I 2 1
...
R0 4.20596 10.2803 0.842826 0 0.00130915 528 H ...
```

The parser should:

1. Read the `S` header and capture the declared sequence image count and
	 selected count.
2. Read `I <index> <selected>` records, retaining the index and boolean
	 selected state.
3. Read `R0` records and parse the five required numeric values.
4. Associate each registration row with its sequence member by the format's
	 documented/order-preserving relationship, retaining the actual sequence
	 index rather than assuming a final merged filename number is a source index.
5. Return one `RegistrationResult` per valid registration row.
6. Raise a clear parser error for malformed numeric fields, missing required
	 columns, duplicate sequence indexes, or an impossible record relationship.

The implementation must first verify the exact relationship between `I` and
`R0` records using the checked-in sample and Siril reference behavior. The
sample has 387 images but 386 selected images, so a naïve assumption that only
selected `I` records have `R0` records would be unsafe.

### Parser validation

Validate the declared count against parsed records where the Siril format
guarantees that they correspond. If Siril permits a sequence to contain
registration rows for unselected members, preserve those rows in the parser and
filter them at the update boundary according to the confirmed “selected mapped
members” policy.

Do not use a filename-only regular expression to infer the original source
image. The `.seq` file contains positional sequence information, not database
IDs.

## Provenance and reverse mapping

This is the central design problem.

The merged sequence renumbers and compacts files. For example, the conversion
map in the current processing output contains mappings like:

```text
'./r_Ha_bkg_pp_light_s171_00008.fit' -> 'all_r_Ha_bkg_pp_light_00008.fit'
'./r_Ha_bkg_pp_light_s171_00010.fit' -> 'all_r_Ha_bkg_pp_light_00009.fit'
```

The missing source frame means merged member `00009` cannot be mapped back by
simply changing the number to `00009`. The conversion file must be treated as a
real mapping, or provenance must be carried explicitly through the pipeline.

### Preferred implementation

Use explicit provenance data already available in the processing context where
possible:

1. Preserve the original source `ImageRow`, especially its database `id`, while
	 generating each per-session sequence member.
2. Preserve the generated per-session filename associated with that source row.
3. Parse Siril's conversion mapping produced by the merge operation.
4. Map the merged sequence member to its per-session generated filename.
5. Map that generated filename to exactly one original database image ID.
6. Pair the registration result with that source ID.

If the current `FileInfo` model cannot carry this information, extend it with a
narrow provenance structure instead of relying on filename heuristics. Likely
locations to inspect are:

- `src/starbash/doit.py` — `FileInfo`
- `src/starbash/processing.py` — input resolution, merge inputs, and output
	construction
- `src/starbash/recipes/osc.py` — filtering and merge setup

The plumbing may be generic internally, but activation remains restricted to
the OSC recipe path for this feature.

### Conversion-file fallback

If explicit provenance cannot be threaded through the existing stages without
changing unrelated recipes, parse the conversion file generated beside the
merged sequence. The parser should:

- accept the conversion file path explicitly;
- normalize `./` prefixes and path separators;
- use basenames only after confirming that the processing directory is the
	correct namespace;
- reject duplicate merged names or duplicate source names;
- return a deterministic merged-to-source mapping;
- never infer a source frame from the merged numeric suffix alone.

The conversion mapping still needs a second lookup from generated per-session
filename to the original database row. That lookup should use carried
provenance, not a new database search based only on a filename pattern.

### Selected-frame policy

Only update source rows that satisfy all of the following:

- the source row exists in the current database;
- the source row is mapped from a merged sequence member;
- the corresponding sequence member is selected by Siril;
- the registration result is valid.

Rows omitted during per-session filtering or merge must remain untouched.

## Database update plan

### API

Add a batch method to `Database`, for example:

```python
def update_images_metadata(
		self,
		updates_by_id: dict[int, dict[str, Any]],
) -> int:
		"""Merge metadata updates into existing image rows atomically."""
```

Required behavior:

1. Begin one transaction.
2. Fetch each existing row by image ID.
3. Merge only the five registration keys into the existing JSON metadata.
4. Preserve all other metadata unchanged.
5. Update only existing rows.
6. Roll back the entire transaction if any expected row is missing or invalid.
7. Return the number of updated rows.
8. Commit only after every update has been validated.

Do not use `upsert_image()` for this operation: an incomplete record could
overwrite indexed fields or discard metadata.

### Assertions and failure behavior

Before calling the database API, build and validate the complete update set.
Use assertions to catch programmer/data-model mistakes, including:

```python
assert len(parsed_selected_results) == len(mapped_source_rows)
assert len({result.sequence_index for result in parsed_selected_results}) == len(parsed_selected_results)
assert len({row["id"] for row in mapped_source_rows}) == len(mapped_source_rows)
```

After resolving source rows and after the database call, assert the expected
counts:

```python
assert found_count == expected_count
assert updated_count == expected_count
```

Assertions must run before any database write. Because Python assertions can be
disabled with optimization, also raise a normal, descriptive exception for
configuration/data errors and catch it at the OSC integration boundary. The
boundary should log a warning and skip the update as a unit, preserving any
previously stored metrics.

The intended behavior is therefore:

```text
parse -> map -> validate/count -> update atomically
											 \-> failure: warn, no partial update
```

### Idempotency

Running the same OSC stage again should update the same image IDs in place. It
must not create duplicate image rows or append duplicate metadata structures.

If a future run cannot parse or map the complete sequence, leave previous
registration values untouched rather than clearing them.

## OSC integration plan

### Database access

The Python recipe currently receives `context` and `logger`, but the active
`Database` is owned by `Starbash`. Expose the existing database connection to
the recipe runtime through the processing context or a narrow runtime service.
The service should be bound to `sb.db` and must not instantiate `Database()`.

Prefer a narrow interface, such as an injected updater, if exposing the full
application object would make the RestrictedPython boundary unnecessarily large.
If the implementation exposes the database object directly, document that the
object is the active app-owned connection and restrict the recipe to the
metadata-update method.

### Exact hook

The registration parser must run only after the Ha call to `make_stacked()` has
completed its `siril.run()` call. Do not parse before Siril has written the
registration data.

The preferred control flow in `osc_process()` is:

```text
if has_sii_oiii:
		make_stacked(["sii"], "Ha", ...)

if has_ha_oiii:
		make_stacked(["ha"], "Ha", ...)
		parse/update all_r_Ha_bkg_pp_light_.seq

if has_ha_oiii or has_sii_oiii:
		make_stacked(["ha", "sii"], "OIII", ...)
```

This placement matters because both the Sii and Ha paths can use a Ha-named
variant, while the feature must target the Ha sequence specified above. It also
ensures that OIII registration output is not accidentally parsed.

Do not parse these files for this feature:

- `r_all_r_Ha_bkg_pp_light_.seq`;
- `all_r_OIII_bkg_pp_light_.seq`;
- per-session `r_Ha_bkg_pp_light_s<ID>_.seq`;
- stale or unrelated `.seq` files in the processing directory;
- the single-input/non-merged sequence path.

If the expected merged Ha sequence does not exist, treat that as an integration
failure: warn and skip the metadata update.

## Report changes

### `src/starbash/report.py`

Update the frame metadata policy:

- replace the provisional `wFWHM = -1` behavior;
- include `FWHM`, `Amplitude`, `Roundness`, `Background`, and `Stars` in the
	frame whitelist;
- omit any of those keys not present in the database row;
- retain blacklist and deep-copy behavior;
- preserve numeric types.

The report collector in `ProcessedTarget._collect_sessions_info()` should not
perform new database queries. It already calls `get_session_images()`, so the
new values should flow naturally from the updated image rows.

### `src/starbash/processed_target.py`

Keep the existing lifecycle:

```text
close()
	-> _collect_sessions_info()
	-> _update_from_context()
	-> _generate_report()
```

Only adjust tests and any serialization assumptions needed for the new keys.
Do not add registration-specific logic to `_generate_report()`.

### `src/starbash/publish/github.py`

Replace the constant chart series:

```python
chart.add("FWHM", [1 for _ in frames])
```

with real frame values. If no frame in a session has `FWHM`, omit the FWHM
series. For partially missing data, use chart gaps (`None`) or the publisher's
supported missing-point representation; never substitute `1`.

The report should continue to render if old target files contain the legacy
`wFWHM` placeholder or have no registration metrics. Backward compatibility is
important because existing processed target TOML files will not all have been
reprocessed.

## Test plan

### Parser tests

Add `tests/unit/test_import_registration.py` covering:

- parsing the supplied sequence header;
- parsing `I <index> 0` and `I <index> 1` selection states;
- parsing all five metric values with correct `float`/`int` types;
- retaining sequence indexes;
- malformed numeric fields;
- missing required columns;
- duplicate indexes;
- declared image/selection count validation;
- the sample case where image count and selected count differ;
- any supported Siril variation encountered while validating the fixture.

### Mapping/provenance tests

Create a small synthetic merge mapping where source frame numbers are not
contiguous:

```text
session 1 frame 1 -> merged frame 1
session 1 frame 3 -> merged frame 2
session 2 frame 1 -> merged frame 3
```

Verify that:

- each registration result reaches the intended database ID;
- merged index `2` is not mapped to source frame `2` by accident;
- omitted source frames remain unchanged;
- duplicate source IDs fail validation;
- missing conversion/provenance mappings fail without a partial update.

### Database tests

Extend `tests/unit/test_database.py` with tests for:

- updating one existing image by ID;
- batch updating all five fields;
- preserving unrelated metadata;
- preserving path and indexed columns;
- rejecting an unknown image ID;
- atomic rollback when one batch member is invalid;
- returning the exact updated-row count;
- idempotent repeated updates.

### OSC integration tests

Add focused tests for `src/starbash/recipes/osc.py` with mocked Siril,
parser, provenance mapper, and active database updater. Verify that:

- parsing occurs after the Ha `siril.run()` call;
- only `all_r_Ha_bkg_pp_light_.seq` is parsed;
- OIII output is ignored;
- the Sii-only intermediate Ha call does not trigger the update;
- the single-input path does not trigger the merged-sequence feature;
- the active application database/updater is used;
- count assertions are checked;
- a parse/map/count failure logs a warning and performs no partial update.

### Report tests

Update `tests/unit/test_processed_target.py` and add or extend report tests to
verify:

- real registration values appear in `FrameInfo.metadata`;
- all five metrics are serialized when present;
- absent metrics are omitted;
- the old `wFWHM = -1` placeholder is not generated;
- metadata blacklist behavior remains intact;
- old reports without registration values remain readable.

### Publisher tests

Add publisher coverage, likely in `tests/unit/test_publish.py`, for:

- real FWHM values being passed to the chart;
- no fake constant FWHM values;
- no FWHM series when all values are missing;
- gaps for partially missing values;
- legacy reports without FWHM still publishing successfully.

## Implementation phases

### Phase 1 — Confirm and fixture the Siril format

- Inspect the complete checked-in `.seq` and conversion outputs.
- Confirm how `I` selection records correspond to `R0` rows.
- Add parser fixtures and tests before wiring the processing path.
- Document any Siril-version assumptions.

### Phase 2 — Add typed parser and provenance mapping

- Implement `RegistrationResult` and strict `.seq` parsing.
- Identify the existing point where source `ImageRow` identity is available.
- Add explicit provenance or a conversion-file parser as needed.
- Prove the non-contiguous mapping with unit tests.

### Phase 3 — Add atomic database updates

- Add the batch metadata update API.
- Add transaction, count validation, assertions, and rollback behavior.
- Test that only existing rows are modified and all unrelated metadata survives.

### Phase 4 — Wire the OSC Ha stack

- Expose the existing app-owned database/update service to the recipe runtime.
- Add the post-Ha-stack parse/map/update hook in `osc_process()`.
- Gate the hook to the merged Ha path only.
- Log and skip the complete update on parse or mapping failure.

### Phase 5 — Replace report placeholders

- Update `frame_info()` and the frame metadata whitelist.
- Remove `wFWHM = -1` generation.
- Update chart generation to use real FWHM values and missing-point behavior.
- Preserve compatibility with existing reports.

### Phase 6 — Integration validation

- Run parser, database, OSC, processed-target, and publisher tests.
- Run the relevant workflow fixture without external Siril if possible.
- Verify that the expected number of source DB rows changed.
- Inspect generated `about.sessions` TOML and ensure it parses correctly.

## Acceptance criteria

- `parse_siril_seq()` returns typed registration results with sequence indexes,
	selection state, and all five metrics.
- The merged Ha sequence is mapped back to original source image IDs without
	relying on merged filename numbering.
- Only selected, successfully mapped merged members update the database.
- The existing application-owned database connection is used.
- Updates are atomic, idempotent, and preserve unrelated metadata.
- Assertions verify parsed, mapped, found, and updated counts before completion.
- A failure produces a warning and no partial metadata update.
- The feature runs only for the requested `osc.py` Ha path.
- Generated reports contain real `FWHM`, `Amplitude`, `Roundness`, `Background`,
	and `Stars` values when available.
- Missing registration metadata is omitted from reports rather than represented
	by fake `-1` or `1` values.
- Existing reports without registration metadata remain publishable.
- Tests cover parser behavior, non-contiguous provenance, database updates, OSC
	gating, report serialization, and chart generation.

## Remaining implementation notes

The two details that must be verified from the actual Siril artifacts before
coding are:

1. Whether every `R0` row corresponds positionally to every `I` record, or
	 whether Siril emits registration rows only for a subset.
2. Whether the conversion file is guaranteed to be produced for every merge
	 invocation and is stable enough to be the fallback provenance source.

These are implementation checks, not open product decisions. The product
decisions are fixed above: use the five sample metric names, report all five,
update selected mapped members only, use the existing DB connection, support
the merged Ha path only, and warn without partial writes on failure.

