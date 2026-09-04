# stage c1: Generalized crop stage

## Status

**C1 and C2 implemented.**

Extract the current OSC-specific centered crop into reusable code and expose it
as a default recipe stage. The stage consumes the FITS outputs of a preceding
`stack_.*` stage, creates new `crop_...` files, and optionally rotates them with
Siril. It must never modify the stack output in place.

The recipe is multiplexed over upstream files: a stack producing one file
creates one crop task, while a stack producing Ha/OIII/Sii files creates one
independent crop task per file.

## Decisions

- Remove the old in-place crop from `src/starbash/recipes/osc.py`.
- Run the new `crop` stage after `stack_.*`.
- Include `common/crop.toml` in the default recipe manifest.
- Process every FITS output from the selected upstream stack stage; do not add
  filename exclusions.
- Declare the upstream job input with `multiplex = true`.
- Crop first, then rotate.
- Use Lanczos-4 interpolation (`-interp=lanczos4`) when rotation is requested.
- Do not expose a separate `nocrop` option. `crop_percent = 100` retains the
  complete image.
- Keep `crop_percent` integer-only, defaulting to `90`.
- Default `rotate_deg` to `0`.
- Preserve the input extension: `.fit` remains `.fit` and `.fits` remains
  `.fits`.
- Update stages that currently follow `stack_.*` to follow `crop` instead, so
  downstream processing uses the cropped outputs.

## Findings from the current implementation

The existing code and recipe conventions support this design:

- `src/starbash/recipes/osc.py` currently contains `_crop_rectangle()` and
  `_crop_final_files()`. The rectangle is centered and retains the requested
  percentage independently in both dimensions. For `6248x4176` at 90%, it
  returns `(312, 209, 5623, 3758)`.
- `src/starbash/fits.py::read_dimensions()` reads `NAXIS1` and `NAXIS2` from
  the primary FITS HDU and validates positive dimensions.
- `starbash-recipes/common/thumbnail.toml` is the closest model: it consumes a
  prior job output, sets `multiplex = true`, and derives output names from the
  input.
- `starbash-recipes/common/starnet.toml` and
  `starbash-recipes/post/merge_stars.toml` demonstrate explicit load/process/
  save behavior for processed outputs.
- `starbash-recipes/osc/stack_single_duo.toml` demonstrates a Python recipe
  importing code from `starbash.recipes` and assigning the runtime `context`
  and `logger`.
- In `src/starbash/processing.py`, a multiplexed job input is resolved as a
  collection and then split into one task per upstream image row. The crop
  script should therefore handle one input/output pair per invocation.
- `starbash-recipes/graxpert/background.toml` currently follows
  `stack_.*`; it is the known downstream dependency that must be migrated to
  `crop` if it remains in the default chain.

## Goals

1. Move crop geometry and Siril command generation into
   `src/starbash/recipes/crop.py`.
2. Remove crop-specific helpers and in-place cropping from `osc.py`.
3. Add `starbash-recipes/common/crop.toml` and register it in the default
   manifest.
4. Generate one new processed `crop_...` output for each upstream FITS file.
5. Read dimensions from each input FITS file before creating its crop command.
6. Make crop percentage and rotation configurable through stage parameters.
7. Preserve source files, input extensions, and relevant FITS metadata.
8. Add unit, recipe wiring, task graph, and integration coverage.

## Non-goals

- Content-aware or black-border detection.
- Interactive or user-drawn selections.
- Cropping raw frames or sequences; the first version operates on individual
  upstream FITS outputs.
- In-place modification of upstream files.
- A separate `nocrop` parameter.

## Proposed implementation

### 1. Extract reusable crop code

Create `src/starbash/recipes/crop.py`, following the runtime conventions of
`osc.py`:

- `crop_rectangle(width, height, crop_percent=90)` returns
  `(x, y, width, height)` for a centered crop.
- `crop_files(input_paths, output_paths, crop_percent=90, rotate_deg=0)`
  validates inputs, reads dimensions, builds Siril commands, and invokes the
  Siril tool. When `rotate_deg = 0`, it omits `rotate` because Siril treats
  zero-degree rotation as a no-op and rejects the interpolation argument.
- Keep module-level `context`, `logger`, and Siril tool injection compatible
  with RestrictedPython recipe execution.
- Although `crop_files()` may accept lists for reuse and testing, the default
  recipe calls it with one input and one output because its job input is
  multiplexed.

Validate before invoking Siril:

- input and output collections are non-empty and have equal lengths;
- `crop_percent` is an `int` and satisfies `1 <= crop_percent <= 100`;
- input dimensions are positive, using `read_dimensions()`;
- integer crop dimensions remain at least one pixel;
- `rotate_deg` is numeric and finite.

At `crop_percent = 100`, return the full input rectangle. This is the supported
way for a user to request no size reduction.

### 2. Remove OSC-specific cropping

Update `src/starbash/recipes/osc.py` so `make_renormalize()` no longer calls
`_crop_final_files()` and no longer owns `_crop_rectangle()` or
`_crop_final_files()`. OSC stack outputs remain unchanged. The new crop stage
becomes the only workflow-level crop operation.

This is an intentional behavior change. Existing downstream stages must be
rewired to consume `crop` outputs rather than the unmodified stack outputs.

### 3. Add the default multiplexed recipe

Create `starbash-recipes/common/crop.toml` with one stage:

- `name = "crop"`;
- `tool.name = "python"`;
- inline Python importing `starbash.recipes.crop`, assigning `logger` and
  `context`, and invoking the helper for the current input/output pair;
- one `job` input with `after = "stack_.*"` and `multiplex = true`;
- `min_count = 1`;
- one `processed` output with `auto.prefix = "crop_"`;
- `crop_percent` parameter with integer default `90`;
- `rotate_deg` parameter with default `0`.

The recipe must be added to `starbash-recipes/starbash.toml`. Its placement
must ensure it sorts after all matching stack stages and before downstream
stages that now consume `crop` outputs.

The output resolver currently derives `auto.prefix` names from the input. The
implementation must preserve the input suffix instead of forcing `.fits`, so
`stacked.fits` becomes `crop_stacked.fits` and `stacked.fit` becomes
`crop_stacked.fit`.

No filename filter is required. Every FITS output selected from the prior stack
stage is valid input for the generalized crop stage, including multiple
outputs from a duo stack.

### 4. Siril command sequence

For each multiplexed input/output pair, generate commands equivalent to:

1. `load "<input>"`
2. `crop <x> <y> <width> <height>`
3. `rotate <rotate_deg> -interp=lanczos4` when `rotate_deg != 0`
4. `save "<output>"`

The order is deliberately crop then rotate. Do not use `boxselect` for this
stage: the explicit `crop` command makes the selected geometry unambiguous.
Do not add `-nocrop`; users who want to retain the complete image use
`crop_percent = 100`.

The command builder must quote paths consistently and avoid overwriting the
input. If Siril creates intermediate files in `process_dir`, use safe
`temporaries` declarations and verify cleanup on both success and failure.

The supported Siril documentation lists the relevant forms as:

```text
crop [x y width height]
rotate degree [-nocrop] [-interp=] [-noclamp]
```

Siril supports `lanczos4` as a rotation interpolation mode. The stage should
use the explicit long form `-interp=lanczos4` for non-zero rotations and omit
the no-op rotation command when `rotate_deg = 0`.

### 5. Dependency migration

Search all recipe repositories for `after = "stack_.*"`. Change downstream
stages that are intended to operate on final stack products to follow `crop`
instead. In the current default recipes, this includes the GraXpert
background stage. Verify whether any non-final or alternate workflow should
remain attached directly to a stack stage before changing it.

The resulting normal path is:

```text
stack_* -> crop -> background -> later post-processing
```

The crop stage itself must not follow `background`, `veralux`, `merge_stars`,
or another later stage, because that would make the default dependency graph
ambiguous and could create duplicate crop outputs.

## Test plan

### Unit tests

Create `tests/unit/test_crop.py` covering:

- centered 90% geometry, retaining the current expected result;
- 100% geometry for the no-size-reduction setting;
- odd dimensions and small images;
- invalid dimensions;
- non-integer, zero, negative, and greater-than-100 percentages;
- mismatched and empty input/output collections;
- invalid or non-finite rotation values;
- command order, crop coordinates, Lanczos-4 option, quoted paths, and output
  paths;
- multiple pairs passed to the helper, while confirming each pair is handled
  independently.

Remove or relocate the crop-specific tests from `tests/unit/test_osc.py` and
retain OSC tests only for OSC behavior that remains after extraction.

### Recipe and processing tests

Add recipe wiring tests confirming:

- the recipe name and Python tool;
- `after = "stack_.*"`;
- `multiplex = true`;
- `min_count = 1`;
- integer/default parameters;
- `auto.prefix = "crop_"`;
- the default manifest includes `common/crop.toml`.

Add processing coverage with a fake stack stage that emits multiple FITS files
and verify that the crop stage creates one task and one target per input. Also
verify that excluding the upstream stage does not leave orphan crop tasks and
that downstream stages resolve crop outputs.

### Integration test

When Siril is available, process a small FITS fixture and verify:

- the source remains unchanged;
- the output is created with the preserved extension;
- 90% cropping is centered;
- `crop_percent = 100` retains the full dimensions;
- rotation is applied with Lanczos-4;
- the resulting dimensions match the crop-then-rotate behavior;
- relevant FITS metadata is retained.

Mark the test as requiring the external Siril installation when it cannot run
in the normal test environment.

## Implementation sequence

1. Remove `_crop_rectangle()` and `_crop_final_files()` from `osc.py`, remove
   the in-place crop call, and migrate existing OSC crop tests.
2. Implement `src/starbash/recipes/crop.py` and its unit tests.
3. Add `starbash-recipes/common/crop.toml` with multiplexed input handling.
4. Add the recipe to the default manifest.
5. Update downstream `after` dependencies from `stack_.*` to `crop` where
   appropriate.
6. Add processing tests for one-task-per-input behavior, outputs, exclusions,
   and dependency ordering.
7. Run focused tests, type/lint checks, and the complete test suite.
8. Run the optional Siril integration test and manually inspect a representative
   multi-output stack.
9. Update the TOML recipe documentation to describe the default stage,
   parameter overrides, extension preservation, and `crop_percent = 100`.

## Acceptance criteria

- The default recipe manifest includes `common/crop.toml`.
- The crop recipe follows `stack_.*` with a multiplexed job input.
- Every FITS output from the prior stack stage produces one independent crop
  task and one independent `crop_...` output.
- The source stack output is never modified.
- Default crop geometry retains a centered 90% of both dimensions.
- `crop_percent = 100` retains the complete image without a separate `nocrop`
  setting.
- `rotate_deg` defaults to zero; non-zero rotations use `-interp=lanczos4`.
- `.fit` and `.fits` input extensions are preserved.
- Invalid parameters fail before Siril is invoked with actionable errors.
- Downstream stages that previously consumed stack outputs consume crop outputs.
- Excluded upstream stages do not create orphan crop tasks.

# stage c2: improvements

## C2: maximum pixel dimensions

Add optional `crop_width` and `crop_height` parameters to
`starbash-recipes/common/crop.toml`. They specify maximum output dimensions in
pixels and intentionally have no defaults: when both are omitted, the existing
centered `crop_percent` behavior remains unchanged.

### Behavior

- If both dimensions are omitted, retain `crop_percent` percent of the source
  width and height, centered independently.
- If either dimension is supplied, use dimension mode and ignore
  `crop_percent`.
- If only one dimension is supplied, use that value for both axes and emit one
  warning identifying the missing dimension.
- Treat the values as maximum dimensions. Clamp each requested dimension to the
  corresponding source dimension rather than enlarging the image.
- Reject booleans, non-integers, zero, and negative values before invoking
  Siril. The error must identify the invalid parameter.
- Emit the percentage-precedence warning once per `crop_files()` invocation,
  even when several input/output pairs are processed.

The resulting rectangle remains centered and the existing crop-then-rotate
command order is unchanged. `crop_percent = 100` remains the supported way to
retain the complete image when pixel dimensions are not configured.

### Implementation and verification

1. `crop_rectangle()` and `crop_files()` accept optional pixel dimensions,
  validate them, clamp them to the source dimensions, and log precedence and
  one-axis fallback warnings.
2. `common/crop.toml` declares the two no-default parameters and passes them
  through the recipe script; `crop_percent` defaults to `90`.
3. Unit coverage verifies both-dimension, one-dimension, clamped, invalid, and
  percentage-precedence cases, including warning counts and multiple pairs.
4. Recipe wiring coverage verifies the declarations, defaults, script arguments,
  multiplexing, and output naming. Existing processing tests continue to cover
  the task graph and extension preservation.
5. The TOML recipe guide documents the sizing modes and per-target overrides.
