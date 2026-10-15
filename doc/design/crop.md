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
3. `rotate <angle> -interp=lanczos4 [-nocrop]` when the angle is not a full turn,
   where `angle` is `rotate_deg` normalized into `[0, 360)` and `-nocrop` is
   added for exact quarter turns (see "C3: exact quarter turns" below)
4. `save "<output>"`

The order is deliberately crop then rotate. Do not use `boxselect` for this
stage: the explicit `crop` command makes the selected geometry unambiguous.
Do not add `-nocrop` for an arbitrary angle; users who want to retain the
complete image use `crop_percent = 100`. Exact quarter turns are the exception,
because Siril's default would otherwise throw away most of the rotated image.

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
- `rotate_deg` defaults to zero; non-zero rotations use `-interp=lanczos4`. An
  exact quarter turn is a lossless, whole-canvas rotation (see C3), so 90 and 270
  swap the output width and height.
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

# stage c3: Simplified crop sizing parameters

## Status

**Planned.** C3 replaces the C2 crop parameter interface while preserving the
existing centered crop, crop-then-rotate behavior, and multiplexed task graph.

The current `crop_percent`, `crop_width`, and `crop_height` combination is more
complicated than necessary. The crop stage should expose exactly two sizing
parameters: `crop_width` and `crop_height`.

## Proposed interface

Declare both parameters in `starbash-recipes/common/crop.toml` with the same
defaults:

```toml
[[stages.parameters]]
name = "crop_width"
default = "80%"

[[stages.parameters]]
name = "crop_height"
default = "80%"
```

Remove `crop_percent` entirely. There should be no separate percentage-mode,
dimension-mode, or `nocrop` switch: the units in each value select the sizing
behavior.

### Accepted values

Each parameter accepts either an integer or a string:

| Value | Meaning |
| --- | --- |
| Positive integer, such as `1000` | Maximum size in pixels |
| Numeric string, such as `"1000"` | Maximum size in pixels |
| Percent string, such as `"80%"` | Retain that percentage of the source dimension |

For percentage values, calculate the retained width and height independently
and center the resulting rectangle on the source image. For pixel values,
clamp each requested maximum to the corresponding source dimension; never
enlarge an image. A string that does not end in `%` is pixel-based for now.
This deliberately leaves room for future units without changing the recipe
parameter names.

The default configuration therefore retains the centered inner 80% of both
dimensions. Users can request the complete image with:

```toml
[[stages.overrides]]
name = "crop_width"
value = "100%"
[[stages.overrides]]
name = "crop_height"
value = "100%"
```

Width and height are resolved independently, so mixed configurations such as
`crop_width = "80%"` and `crop_height = 1200` are valid.

## Implementation plan

1. **Centralize value parsing.** Add a small parser in
  `src/starbash/recipes/crop.py` that converts each parameter into an explicit
  sizing representation (percentage or pixels). Reject booleans, empty
  strings, malformed numeric strings, non-positive values, and unsupported
  percent values before invoking Siril. Keep the parser separate from the
  geometry calculation so it can be unit tested directly.
2. **Update crop geometry.** Change `crop_rectangle()` and `crop_files()` to
  accept only `crop_width` and `crop_height` for sizing. Compute each axis
  from its parsed value, clamp pixel dimensions to the source image, and
  retain the existing centered rectangle and minimum-one-pixel validation.
3. **Update the recipe script.** Remove the `crop_percent` argument from
  `starbash-recipes/common/crop.toml`. Pass the two new values directly to
  `crop_files()` and set both recipe defaults to `"80%"`.
4. **Migrate target configuration.** Add a throwaway Python migration script
  outside the runtime package to update existing
  `private/processed/**/.starbash/main.toml` files:
  - remove `crop_percent` overrides;
  - create `crop_width` and `crop_height` overrides with equivalent values;
  - preserve unrelated stages, comments where practical, and existing
    explicitly configured crop dimensions;
  - make the script idempotent and print every changed file.
5. **Update documentation and examples.** Replace references to
  `crop_percent`, optional pixel dimensions, and percentage-precedence rules
  in the crop design document and TOML recipe documentation. Document the
  accepted integer/string forms, defaults, clamping, and future-unit rule.

## Validation and error behavior

Validate the complete parameter set before reading or processing any input.
Errors should identify the parameter name and the invalid value, for example
`crop_width must be a positive pixel value` or `crop_height has an invalid
percentage`. A non-finite or non-numeric rotation value remains invalid under
the existing C1/C2 behavior.

The existing warning about percentage precedence is no longer needed because
there is no precedence rule. Do not emit a warning merely because the two
axes use different units.

## Test plan

Update `tests/unit/test_crop.py` and recipe wiring tests to cover:

- default `"80%"` behavior on both axes;
- integer and numeric-string pixel values;
- percentage strings, including `"100%"`;
- mixed percentage/pixel configurations;
- odd and small dimensions, centered geometry, and pixel-value clamping;
- booleans, empty strings, malformed strings, zero, negative values, and
  unsupported percent forms;
- command order, preserved extensions, quoted paths, and rotation behavior;
- multiple multiplexed input/output pairs;
- absence of the `crop_percent` parameter and its script argument;
- migration of representative existing `main.toml` files, including an
  idempotent second run.


# stage c3: exact quarter turns

## Status

**C3 implemented.**

Reported symptom: with `rotate_deg = 90` the `crop_...` output kept the crop
dimensions instead of swapping width and height (a 95%x80% crop of a landscape
frame stayed landscape and looked squeezed).

## Why it happened

Siril's `rotate degree [-nocrop] [-interp=] [-noclamp]` command is *crop-to-fit*
by default: it rotates the pixels and then fits the result back into the source
rectangle (`GetMatrixReframe(..., cropped=1, ...)` keeps `area.w`/`area.h`), so
`rotate 90` on a 640x360 image saves a 640x360 image with the rotated corners
discarded. Starbash never passed `-nocrop`, per the C1 decision above, so a
rotation could never change the canvas.

Measured on Siril 1.4.4 with a 640x360 fixture (the real-Siril test in
`tests/unit/test_crop.py::TestCropFilesWithSiril` asserts the same behaviour):

| command | 640x360 input |
|---|---|
| `rotate 90 -interp=lanczos4` | 640x360 (unchanged -- the bug) |
| `rotate 90 -interp=lanczos4 -nocrop` | 360x640 |
| `rotate 270 -interp=lanczos4 -nocrop` | 360x640 |
| `rotate 180 -interp=lanczos4 -nocrop` | 640x360 |
| `rotate 12 -interp=lanczos4` | 640x360 |

Two further Siril behaviours were confirmed at the same time and are now handled:

- `rotate` accepts only `[0, 360)`. A negative angle (`rotate -7`) or `360`
  prints `Angle ... not allowed` / `Angle is 0.0 or 360.0 degrees. Doing
  nothing...` and **aborts the whole script** ("Exiting batch processing"), so
  the C1-era `rotate -7 -interp=lanczos4` broke any negative `rotate_deg`.
- `-nocrop` at an exact quarter turn is a *pixel-exact* permutation: for 90, 180
  and 270 degrees the resampled output matches `numpy.rot90` bit-for-bit, for odd
  and even widths, heights and sums, and for extreme aspect ratios (a 0.5-pixel
  mis-alignment would make Lanczos4 blur the whole frame; it does not happen).
  Measured with fixture values inside `[0, 1]` so Siril's FITS loader leaves them
  alone: an out-of-range image is instead scaled by 1/65535 on load
  (pre-existing, linear and unrelated to the rotation -- undoing that factor, the
  output is still an exact permutation).

## Decision

`crop.py` normalizes the angle into `[0, 360)` (a full turn is a no-op, logged at
info when the user's value changed) and, for exact multiples of 90 degrees, adds
`-nocrop`. That keeps the whole rotated canvas: 90/270 swap width and height
(which is what a user means by "rotate 90"), while 180 keeps the dimensions.

Arbitrary angles keep crop-to-fit, because a rotated rectangle cannot fill a
larger one without black corners and the C1 rule is that this stage must not grow
the canvas (a crop stage that grows an image would feed black borders into every
downstream tool). So `-nocrop` is still not a user-facing option.

The canvas swap is safe for the shipped pipeline: every file that gets compared
with a crop output also derives from that same crop stage, so they all change
dimensions together (the starless/starmask pair, for instance, comes from a single
`starnet` run over the crop-derived palette output). Verified the stage graph in
`starbash-recipes`: `crop` follows `stack_.*` and every later stage -- the GraXpert
stages, rc-astro, the palettes, `merge_stars`, `thumbnail` -- follows `crop`
(directly or transitively) or only reads a stack's `.seq` for reporting. The
in-between `veralux` stage (another recipe repo) likewise follows the palette.

## Files changed

- `src/starbash/recipes/crop.py` -- `normalize_rotation()`, `is_quarter_turn()`,
  `rotation_command()`; `crop_files()` emits one shared rotate command.
- `tests/unit/test_crop.py` -- command-builder unit tests plus a real-Siril
  `TestCropFilesWithSiril` class (skipped where Siril is absent) asserting the
  output dimensions and pixel-exact rotation.
- `starbash-recipes/common/crop.toml` -- the `rotate_deg` description now states
  the normalization and the 90/270 dimension swap.
- `doc/toml/guide.md` -- the same in the crop section of the TOML guide.

## Note for existing targets

The stage fingerprint (`_stage_fingerprint`) hashes the recipe script, the tool
and the effective parameters -- not the Python helper the script calls. An
already-cropped target therefore still has an up-to-date `crop` task and must have
its `crop_...` outputs deleted (or `rotate_deg` changed) for the corrected crop to
be regenerated.

Run the focused crop and recipe tests first, then the complete test suite.
Optionally run the existing Siril integration test to confirm that the default
80% output, `100%` output, metadata preservation, and rotation behavior remain
correct.