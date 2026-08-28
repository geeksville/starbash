# stage R1: Target report metadata

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

# Stage R2: Generate a local Jekyll site

## Status and scope

**Proposed plan — stage R2.**

Generate a local, GitHub Pages-compatible Jekyll site from processed targets.
The site will be written to the platform-specific Starbash state directory,
which is normally:

```text
~/.local/state/starbash/publish/site
```

R2 generates files only. It does not authenticate with GitHub, commit changes,
push a repository, or call the GitHub API. The existing publisher package should
be structured so those capabilities can be added later without changing the
site-generation contract.

## Confirmed decisions

- The CLI command is `sb publish`.
- `sb publish` uses the GitHub/Jekyll-compatible publisher by default.
- The first implementation requires exactly one local processed repository. It
  fails clearly when there are zero or multiple processed repositories.
- Generated target pages are Markdown Jekyll posts.
- The site includes an index page and one post per valid processed target.
- Target pages include summary information, a hero JPG/JPEG where available,
  session information, equipment links, and session charts.
- Charts are generated with Pygal as SVG assets.
- Templates control page layout; Python publisher code prepares normalized data,
  links, filenames, and chart context.
- Add `site-view` to the Justfile; it runs `sb publish` first, then builds and
  serves the generated site locally.

The following decisions are confirmed: use `PlatformDirs.user_state_dir`, copy
images into the site, regenerate every post on every `sb publish`, use fake
FWHM data for the initial charts, and use a self-contained Jekyll layout/CSS
rather than an external theme.

## Current architecture and gaps

`src/starbash/publish/__init__.py` and `src/starbash/publish/github.py` are
placeholders. There is no publisher interface, site writer, target discovery,
Jinja environment, chart generation, CLI command, publish path, or test suite.

R1 already persists report data in each target's `starbash.toml` under
`about.sessions`, and `ProcessedTarget` exposes the corresponding runtime model.
R2 should read the persisted TOML rather than instantiate `ProcessedTarget` or
query the database. This keeps publishing read-only and allows publication after
the processing environment is gone.

The processed repository template uses target directories beneath a processed
repository root. Discovery must require a target directory containing the
expected `starbash.toml`; malformed or unrelated entries must not crash the
whole publish operation.

The existing path module has config, data, cache, and documents directories but
no state-directory helper. Tests likewise do not isolate state paths yet.

## Site contract

The generated tree should be a valid Jekyll site:

```text
site/
  _config.yml
  index.md
  _posts/
    YYYY-MM-DD-target-slug.md
  assets/
    targets/<target-slug>/
      hero.jpg
      charts/session-<stable-id>.svg
  .starbash-publish.json
```

Use only plain Markdown, Liquid-compatible front matter, CSS, and supported
Jekyll features so the result remains suitable for GitHub Pages. Do not require
custom Jekyll plugins in R2.

The root page should introduce the collection in a warm, modern tone: these
are images processed with the project's tools, shared so others can enjoy them
and help improve the workflow together. It should also provide a visual index
of published targets.

Each target post should contain:

1. YAML front matter with a valid `layout`, title, date, and stable slug.
2. Target identity, coordinates, summary, and processing timestamp.
3. A copied hero image when one is available.
4. Sessions ordered chronologically.
5. Equipment records with safe hyperlinks when `url.info` is present.
6. Session metadata and frame-derived timeline charts.

## Report data contract

Add `about.generated_at` while generating R1 reports as part of R2. Use UTC ISO
8601 with an explicit `Z` or offset. Also add `about.schema_version = 1` so
future publishers can reject or adapt incompatible report data.

Add `DATE-OBS` to persisted frame metadata so the R2 chart x-axis has a stable
timestamp. Continue applying the existing metadata blacklist and do not persist
frame paths or database IDs.

The publisher should normalize TOML nodes into ordinary Python values before
passing context to Jinja. It should support older target files that lack
`schema_version`, `generated_at`, or `about.sessions` by warning and publishing
the available summary where possible.

## Publisher architecture

Introduce a small publisher-neutral layer, for example:

```text
src/starbash/publish/base.py
src/starbash/publish/models.py
src/starbash/publish/site.py
src/starbash/publish/github.py
```

Define a `Publisher` protocol or abstract base class and a `PublishResult`
containing created, updated, skipped, and warning information. The GitHub
publisher means “GitHub Pages-compatible Jekyll output” in R2; remote upload is
explicitly deferred.

Add a read-only target loader, possibly in `src/starbash/target.py`, rather than
making `ProcessedTarget` handle publishing concerns. It should:

- load and normalize a target `starbash.toml`;
- validate the minimum `about` structure;
- expose summary, target, sessions, metadata, and schema version;
- discover candidate JPG/JPEG files without retaining paths in persisted report
  data;
- derive a safe, deterministic display slug;
- keep source paths separate from site-relative asset paths.

Refactor shared report parsing only when it reduces duplication. Do not move
processing-specific lifecycle, stage, or override behavior out of
`ProcessedTarget` merely to support publishing.

## Paths and lifecycle

Extend `src/starbash/paths.py` with a platform-aware state path and publish-site
helper, such as:

```python
get_user_state_dir()
get_publish_site_dir()
```

Use `PlatformDirs.user_state_dir`; do not construct `.local/state` manually.
Extend `set_test_directories()` and the test fixtures with a state override so
publisher tests never write to a real user directory. Create the site directory
only when publishing starts.

`sb publish` should:

1. open `Starbash("publish")`;
2. locate the processed repository;
3. fail clearly if no suitable local processed repository exists;
4. discover valid target directories in deterministic order;
5. generate or update the site;
6. print the site path and a concise result summary.

The command should not initialize the database unless a future fallback requires
it.

## Templates and presentation

Add Jinja2 as a runtime dependency and load packaged templates with
`importlib.resources`. Use the existing:

```text
src/starbash/templates/report/index.md.jinja
src/starbash/templates/report/target.md.jinja
```

as the primary Markdown templates. Add a self-contained layout/CSS and minimal
`_config.yml` as needed.

Python should prepare presentation-ready context, including:

- escaped display text and URLs;
- relative asset URLs compatible with a GitHub Pages base URL;
- equipment hyperlink data;
- formatted dates/durations;
- deterministic chart filenames;
- hero image information;
- flags for missing metadata and unavailable charts.

Templates should control layout and wording, but should not perform database
queries, filesystem discovery, or complex equipment/chart logic. Leave room for
future user template overrides, ideally via a publisher/template-directory
option, without making overrides mandatory in R2.

## Hero images and assets

Copy selected JPG/JPEG files into:

```text
assets/targets/<target-slug>/
```

Use a deterministic selection policy: prefer a conventional hero filename if
one exists, otherwise choose the largest valid JPG/JPEG, breaking ties by name.
Preserve a safe extension and never link to an arbitrary source filesystem path.
Use Jekyll's `relative_url` behavior (or equivalent prepared relative URLs) so
project-site deployments work with a non-root base URL.

## Session charts

Add Pygal as a runtime dependency and generate one SVG per session under the
target's asset directory. Use frame `DATE-OBS` as the x-axis and plot `WINDGUST`.
Plot `wFWHM` only when at least one measured value is not `-1`; otherwise show an
explicit unavailable state in the page instead of a misleading flat line.

Charts must have deterministic filenames and configuration, handle empty or
partially missing data, and include useful titles/labels. Equipment hyperlinks
should use `url.info` only after validating that the value is an HTTP(S) URL.

## Incremental generation

R2 intentionally has no incremental publishing or freshness checks. Every
`sb publish` invocation regenerates the complete site and all target posts.
`about.generated_at` is display/schema metadata only in this stage. A manifest,
source hashes, `--force`, and stale-output cleanup are deferred until a later
incremental-publishing stage. Preserve unrelated files by writing only the
known generated site paths.

## Implementation phases

### Phase 1 — contracts, paths, and timestamp

- Add `get_user_state_dir()` and `get_publish_site_dir()` with test overrides.
- Add `about.generated_at` and `about.schema_version` to R1 report generation.
- Add `DATE-OBS` to persisted frame report metadata.
- Define normalized publisher models and slug rules. Do not add incremental
  manifest behavior in R2.

### Phase 2 — read-only target loading and discovery

- Implement target TOML loading and ordinary-value normalization.
- Discover valid processed targets in deterministic order.
- Define warning/skip behavior for malformed or incomplete targets.
- Add tests for old target files, missing sections, invalid TOML, and safe slugs.

### Phase 3 — templates and site skeleton

- Add Jinja2 and packaged template loading.
- Implement `_config.yml`, `index.md`, `_posts/`, and asset directories.
- Render valid front matter and Markdown.
- Add self-contained modern CSS/layout and the welcoming root-page text.

### Phase 4 — assets and charts

- Implement hero-image selection and copying.
- Implement Pygal session charts and missing-data behavior.
- Render equipment links and chart/image references through prepared context.
- Add tests that inspect actual generated files and SVG output.

### Phase 5 — CLI and publisher

- Implement the publisher abstraction and GitHub/Jekyll-compatible publisher.
- Add `src/starbash/commands/publish.py` and register `sb publish`.
- Regenerate all target posts on every invocation.
- Preserve unrelated site files by limiting writes to known generated paths.

### Phase 6 — local validation

- Add `site-view` to the Justfile, preferably using `bundle exec jekyll serve`.
- Add unit tests for paths, models, templates, assets, charts, and manifest
  decisions.
- Add an optional integration test running `jekyll build` into a temporary
  destination.
- Document that `sb publish` should run before `just site-view`.

## Acceptance criteria

- `sb publish` generates a valid site in the platform-specific publish path.
- The site contains `_config.yml`, `index.md`, and one post for each valid target.
- Posts have valid Jekyll front matter and use safe deterministic slugs.
- Target summaries, timestamps, sessions, equipment, images, and charts render.
- Hero images and SVGs are copied into deployable site-relative asset paths.
- Initial charts use the agreed fake FWHM data until real measurements are
  available.
- Missing repositories, malformed targets, missing images, and missing metadata
  produce clear warnings/errors without corrupting the site.
- Unrelated site files survive generation.
- Tests isolate the platform state directory.
- The generated site builds with Jekyll when the optional external-tool test is
  enabled.
- R2 performs no GitHub authentication or upload.

## Confirmed implementation decisions

1. Add `about.generated_at` and `about.schema_version` as part of R2.
2. Do not implement incremental checks, a manifest, or `--force`; always
  regenerate all posts and assets.
3. Require exactly one local processed repository; fail for zero or multiple.
4. Skip malformed targets with warnings and continue publishing valid targets.
5. If any `hero*.jpg` files exist, publish those named heroes and do not publish
  other JPGs. If none exist, publish all JPG/JPEG files in the target directory.
6. Use fake FWHM data in charts temporarily; real FWHM support will replace it
  later.
7. Do not support user template overrides in R2.
8. `just site-view` runs `sb publish` before serving the site.
9. R2 is local generation only; GitHub upload/API integration is deferred.

The remaining implementation must define only deterministic details such as
hero filename ordering, target slug collisions, malformed-target warning text,
and the exact fake FWHM values used by charts.