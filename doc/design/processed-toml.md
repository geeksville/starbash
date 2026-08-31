# Processed-target metadata layout

## Goal

The `.starbash/` layout is the only supported processed-target layout. Runtime
Make each processed target easier to inspect, publish, and maintain by separating
runtime logs, workflow configuration, target provenance, and session metadata.
Malformed files should produce a useful error naming the file and section instead of silently discarding user configuration.

## Proposed on-disk layout

For a processed target such as `images/processed/M42/`, keep generated FITS,
PNG, and other image products at the target root. Put Starbash-managed metadata
under a hidden `.starbash/` directory:

```text
M42/
├── stacked.fits
├── ... generated image files ...
└── .starbash/
	 ├── starbash.log
	 ├── main.toml
	 ├── about.toml
	 └── sessions.toml
```

### File responsibilities

#### `.starbash/main.toml`

The authoritative target workflow configuration. It contains the target
configuration sections other than `about` and `sessions`, including repository
metadata, target-level `[[stages]]` selections and exclusions, processing
parameter overrides, and processing citation information if present.

User edits to this file must survive subsequent processing runs. Automatic stage
discovery may add missing stage entries, but must not overwrite explicit choices.

#### `.starbash/about.toml`

Generated report-oriented information about the target:


This file should contain no per-frame data.

#### `.starbash/sessions.toml`

Generated session and frame provenance: sessions in chronological order, selected
equipment and approved session metadata, and frame metadata needed for reports and
timeline charts. Continue applying the configured metadata blacklist. Do not
persist source paths, database IDs, or other private identifiers unless explicitly
approved by the report data contract.

#### `.starbash/starbash.log`

The processing log for this target. It should be created and cleared during the
same processing lifecycle, but must no longer share a directory with user-facing
image products and metadata files.
Replace `src/starbash/templates/target/processed.toml` with:

```text
src/starbash/templates/target/processed/
├── main.toml
├── about.toml
└── sessions.toml
```

Template responsibilities should mirror the files above:

  overrides, and citation data;

Avoid generating placeholder sections that are not needed. In particular, an
empty `[[sessions]]` entry should not be written merely because the template is
loaded.

## Processing changes

### 1. Introduce explicit metadata paths

Add small path helpers or constants for the processed-target metadata directory
and its four files. Keep master-output handling separate unless there is a
concrete requirement to migrate master metadata too.

### 2. Update `ProcessedTarget`

In `src/starbash/processed_target.py`:

1. Create `<target>/.starbash/` when a processed target is initialized.
2. Set `log_path` to `.starbash/starbash.log`.
3. Load `main.toml`, `about.toml`, and `sessions.toml` as separate logical
	sections. The new layout is authoritative.
4. Preserve the existing `self.repo` interface where practical so stage helpers
	and parameter overrides do not need an unnecessary rewrite.
5. Load stage selections and parameter overrides from `main.toml`.
6. Load prior session-specific stage/master information from `sessions.toml`.
	Session-specific `stages` and `masters` remain in that file.

The logical configuration should be represented in memory as separate sections,
then written back to the corresponding files. Avoid pretending the three files
are one writable TOML document unless the repository abstraction supports that
safely.

### 3. Update report generation

Split the current `_generate_report()` and `_update_from_context()` behavior:

  `schema_version`;

Use one explicit report schema version for the initial split. The first write
should be deterministic so repeated processing with unchanged inputs produces
stable TOML apart from `generated_at`.

## Publishing `main.toml`

The published site should expose the workflow used to generate each target while
keeping private runtime details out of the page.

During site generation, copy the target's `.starbash/main.toml` into its published
asset directory, for example:

```text
site/assets/targets/<target-slug>/main.toml
```

Treat the copy as a publication artifact, not as a source of truth. Do not publish
`starbash.log`, `sessions.toml`, or any file excluded by the site publication
policy.

Update `src/starbash/templates/report/target.md.jinja` to include a clearly
labeled **View processing workflow** link. The publisher should supply the URL
from the target slug and asset path rather than having the template assemble it
from filesystem paths.

The link must work for target names containing spaces or punctuation and remain
valid when served from a project-page subpath.

## Implementation sequence

1. **Lock down the contract.** Use the finalized contract: `.starbash` only,
	session-specific settings stay in `sessions.toml`, complete `main.toml` is
	public, and master outputs are out of scope.
2. **Split templates.** Add the three target templates and tests for their
	rendered sections.
3. **Add metadata path handling.** Create `.starbash/` and centralize config and
	log paths.
4. **Refactor `ProcessedTarget`.** Read, update, and write the three files while
	preserving stage exclusions, overrides, and session metadata.
5. **Update the publisher.** Discover only `.starbash/main.toml`, copy it as a
	site asset, and pass its URL to the report template.
6. **Update documentation and fixtures.** Keep processed-target references
	consistent with `.starbash`; leave unrelated user/repository configuration
	references unchanged.
7. **Run regression validation.** Run processed-target, publisher, report, CLI,
	and full test suites; manually inspect a generated target and site.

## Tests

Add or update tests for:

- clear errors for incomplete target metadata;
- publisher discovery of the new layout;
- copying `main.toml` into the site;
- correct workflow links for safe slugs and nested site paths;
- session report rendering with missing optional fields.


## Resolved decisions

- **Migration:** Complete. All processed targets use the `.starbash` layout.
- **Precedence:** Use only the `.starbash` files; do not merge alternate layouts.
- **Session ownership:** Keep session-specific `stages` and `masters` in
  `sessions.toml`.
- **Citation:** Keep `[processing.citation]` in `main.toml`.
- **Publication:** Publish the complete `main.toml`.
- **Existing publisher:** Publish only targets using the `.starbash` layout.
- **Scope:** Processed targets only. Generated master metadata remains unchanged.
