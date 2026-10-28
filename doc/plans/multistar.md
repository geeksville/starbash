# Broadband stars for a narrowband target

Status: **phase 1–3 implemented 2026-10-28, not yet run on a real target.** The
Siril command order below is the one a real 1.4.4 run accepted. Do not "simplify"
it back to a single script: each split exists because the obvious order fails.
(`private/processed/ngc7822/`). The expensive part of a full `sb process auto`
is the existing dual-duo stack, so this plan must not force that to rerun.

## Goal

When a narrowband target also has broadband lights, stack those lights onto the
narrowband plate and use *their* stars when the stretched starless image is
recombined. A target with no broadband lights keeps today's behaviour exactly.

`ngc7822` is the motivating case: five nights of HaOiii/SiiOiii plus one night
of Tri (`sb select list`, session 233, 89 frames, 7h 25m). The dual-duo stack
already produces three mutually registered mono plates,

| file | shape | `FILTER` |
|---|---|---|
| `stacked_Ha.fits` | 4176 × 6248 | Ha |
| `stacked_OIII.fits` | 4176 × 6248 | Oiii |
| `stacked_Sii.fits` | 4176 × 6248 | Sii |

and `crop` then rotates all three to 5920 × 3328. The finished SHO/HOO images
are built from those narrowband plates, so their stars are the narrowband stars.
The Tri night should instead supply the stars.

## Why the obvious file is not the answer

`private/processed/ngc7822/stacked.fits` already exists. It is a colour stack of
the Tri night (`FILTER=Tri`, 3 × 4794 × 6628, 381 MB). It is **not** a product
this feature may depend on:

- `stack_osc` has no filter gate. It stacks every light session of the target,
  so on a target whose only lights are HaOiii/SiiOiii the file it writes is a
  stack of the duo frames, not a broadband plate. On `ngc7822` the file happens
  to be Tri only because `stack_osc` was left enabled for that run.
- It is registered to its own best frame (`register osc -2pass`), so it is
  neither the same size nor the same framing as `stacked_Ha.fits`.
- `preflight_tasks()` keeps one writer per output file. A second stage that
  also declared `stacked.fits` would be excluded, or would exclude `stack_osc`.

So `stacked.fits` is evidence that the Tri frames calibrate and stack, not an
input. The new product is a different file, `stacked_bb.fits`, and it is absent
when there is no broadband data.

## The one hard constraint

The three narrowband plates agree because `make_renormalize()` registers the
three channel stacks against one reference and then saves each registered
result. A fourth image only matches them if it is registered against that same
reference and exported with the same framing.

Siril cannot be told "register this sequence against that other file". `register`
picks its reference from inside the sequence (`sequence_find_refimage()`), and
`setref sequencename image_number` only chooses which member that is. The
reference therefore has to be a member of the sequence being registered. The
whole feature reduces to one trick:

1. Calibrate the broadband lights the way every other light is calibrated.
2. Append the already-finished Ha plate as the last member of that sequence.
3. `setref` it, register, apply the registration with the same framing the
   narrowband stack used, and stack **only the broadband members**.
4. The applied Ha member is the dimension check: it must come back the same
   shape it went in as. Save the broadband stack beside it.

That is also why the feature is a new stage rather than a fourth call inside
`osc.osc_process()`. The dual-duo stage's fingerprint does not cover the Python
it calls (`_stage_fingerprint` hashes the recipe script, not the helper). Editing
`osc.py` and hoping the old task looks stale would either silently do nothing or,
if the recipe text changed, redo the whole 30-minute stack. A new stage depends
on `stacked_Ha.fits` and the calibrated broadband sequences, so doit reruns only
the new work.

## What gets reused

`stack_osc.toml` is the right *procedure* and the wrong *stage*. Its script is
the calibration-to-stack path we want, but its inputs, outputs, registration
reference and drizzle setting are all wrong for this job. Copying that script
into a second recipe would be the third copy of the same Siril sequence (the
file already says `FIXME - share these options via the repo import mechanism`).

Share the procedure, not the stage:

- add `osc.register_and_stack(...)` in `src/starbash/recipes/osc.py`, containing
  the `register` / `seqapplyreg` / `stack r_...` / `mirrorx_single` sequence that
  `make_stacked()` and `stack_osc.toml` both already spell out;
- give it the options those two callers already disagree about: drizzle,
  framing, filtering, rejection, stack options, and an optional reference index;
- leave `stack_osc.toml` calling it only if that replacement is behaviour-exact
  (same commands, same `r_osc_.seq` output, same defaults). That recipe's
  defaults are *not* the duo defaults: drizzle is off because Siril cannot
  drizzle a colour sequence, framing is `max`, filtering is `-filter-wfwhm=80%`,
  and the stack adds `-rgb_equal`. Do not "improve" them while moving the code.

The new stage calls the same helper with the duo stage's options and one extra
argument: the reference member. Calibration is not part of the helper. The
`light_vs_*` stages already calibrated every session, including the Tri night,
and wrote `bkg_pp_*.seq`. Reusing those sequences is the reuse that actually
saves the long run.

## Phase 1 — `stack_broadband`

New recipe: `starbash-recipes/osc/stack_broadband.toml`, registered in
`starbash-recipes/starbash.toml` immediately after `stack_dual_duo.toml`.

```toml
name = "stack_broadband"
tool.name = "python"
# No role = "stack". stack_dual_duo owns that role, and select_stages() keeps
# one stage per role. Joining it would drop this stage before it ever ran.
# No priority either: with no role, priority only breaks sort ties.
```

The script sets `osc.logger` and `osc.context`, then calls `osc.stack_broadband()`.

Inputs, in three blocks:

| block | `after` | gate | required? |
|---|---|---|---|
| `ha` | `stack_(dual_duo|single_duo|osc)` | `filename = "_Ha"` | yes, `min_count = 1` |
| `lights` | `(?:seqextract_haoiii|light.*)` | sequence name starts with `bkg_pp_light`, and no `seqextract_haoiii` task exists for that session | yes, `min_count = 1` |

`optional = true` is the existing way to let a stage run when one input is
absent (`palette_sho`'s Sii block; `processing.py` returns an empty `FileInfo`
instead of rejecting the stage). It is the wrong tool for these two gates.
If either the Ha plate or a broadband light sequence is missing, the stage must
be **skipped**, not run. `min_count` already does that. Whether the plate came
from a duo stack is recorded on the plate input itself (the producing task
name), so the script does not need a third input to decide which registration
options to copy.

The broadband gate follows `seqextract_haoiii`, not `light.*`. The light stage
writes `bkg_pp_light_*.seq` for every night, including a duo night; the
extraction stage is what rewrites that night to `r_Ha_bkg_pp_light_*.seq` and
`r_OIII_bkg_pp_light_*.seq` and leaves a broadband night untouched. A filter
on the light stage's declared output therefore accepts the duo sequences.
Following both stages and keeping names that start with `bkg_pp_light` is
not enough. The extraction stage only *publishes* the rewritten sequences, so
the untouched name is still a light-stage output, and the light task for a
rewritten night is still in the graph. The filter therefore also drops a
light task when a `seqextract_haoiii` task exists for the same session. The
`light.*` alternative remains so a broadband-only target, which never runs
extraction, still has a producer. A metadata filter cannot say this either:
a calibrated sequence does not carry its own filter, and on a mixed target
the shared task context is HaOiii.

The `lights` input is the calibrated per-session sequence (`bkg_pp_*.seq` from
`light_vs_bias` / `light_vs_dark` / `light_no_darks`), not the raw frames. The
helper reads those sequence paths the same way `make_stacked()` reads
`r_Ha_bkg_pp_*` paths from its named inputs.

The only declared output is:

```toml
[[stages.outputs]]
kind = "processed"
name = ["stacked_bb.fits"]
```

Declare nothing else. In particular do not declare `stacked.fits`, and do not
declare a registered sequence as a `job` output unless a report stage actually
consumes it. A declared output that the script does not write makes doit treat
the task as permanently out of date.

`osc.stack_broadband()` does this and nothing else. The Siril script is two
halves with a Python step between them, because one script cannot do it:

1. Resolve the Ha plate from `input["ha"]`. It is `stacked_Ha.fits` here; the
   helper matches the `_Ha` suffix rather than assuming the producer.
2. Collect the broadband `bkg_pp_light_*.seq` files. One sequence is used as it
   is. Several are handed to `merge_to = "bb"`, which turns every sequence into
   one ordered directory of frame links. Siril's `merge` refuses sequences that
   differ in size, so it is the wrong tool for nights that may not match.
3. Copy that sequence, and only that sequence, into a fresh `broadband`
   directory, then copy the plate in as the next numbered frame. `convert`
   reads every FITS file in the working directory. The shared process directory
   holds every night, so converting there turned 89 Tri frames into 4832 and
   registration failed on a frame from another night. The copy is what
   `convert` rewrites; the original sequence is left as the stage found it.
   Siril is started with `-d` in the copy. A scripted `cd` does not move the
   sequence `register` looks up.
4. `convert <seq> -out=.`, then `setref <seq> <n+1>`, then `register`. Siril
   numbers members from 1, so 89 lights put the plate at 90. The pin has to
   precede `register`: doing it afterwards rewrites the reference member's
   registration data. A bare `register <seq>` is also rejected (Siril strips the
   line and then sees no argument), so the helper passes `-noclamp` instead of
   `-2pass`. `-2pass` would replace the reference just pinned.
5. Stop. The reference's own matrix is an identity, and `seqapplyreg` will not
   export a reference whose index is unset. `write_reference_identity()` records
   that identity in the sequence file (the last `R0` row, nine coefficients
   after the `H` marker) before the second script starts.
6. `unselect` the plate, then `setref` it again. `unselect` clears
   `reference_image`, which is exactly the unset index `seqapplyreg` aborts on,
   so the pin has to be the last command before the apply. `seqapplyreg` uses
   the duo framing. `framing=cog` recentres the canvas, so the exported plate
   is not pixel-identical to the input; it is the same framing the narrowband
   plates already have, which is what makes them agree.
7. `unselect` the plate in the *applied* sequence (`r_<seq>`), then stack that
   sequence with `-filter-included`. `setref` forced the plate included, and
   the applied sequence copies that selection, so the exclusion has to happen
   after the apply. Stacking the original sequence would put the plate in the
   result.
8. Compare the applied reference member's shape with the plate. A mismatch
   means the framing diverged; fail rather than save a plate `crop` cannot line
   up. The applied file is in the broadband directory, not the process
   directory. `mirrorx_single`, `update_key FILTER Broadband`, and save
   `{output}/stacked_bb.fits`.

The stage is skipped, not failed, when no broadband sequence matches. That is
what keeps an ordinary duo target unchanged.

## Phase 2 — let it through crop, then stop

`common/crop.toml` already says `after = "stack_.*"` and multiplexes one task
per stack output. `stack_broadband` matches that pattern, so a produced
`stacked_bb.fits` becomes `crop_stacked_bb.fits` at the same crop rectangle and
`rotate_deg` as the three narrowband plates. On `ngc7822` that is the rotation
from 4176 × 6248 to 5920 × 3328. No crop change is needed, and the crop is what
makes the later mask line up with `SHO.fits`.

`crop` follows `stack_.*`, so `stacked_bb.fits` becomes `crop_stacked_bb.fits`
at the same crop and rotation as the narrowband plates. `background` multiplexes
every crop output, so the plate then continues through deblur and denoise like
the other plates. `palette_broadband` is a different feature and still excludes
the filename: its metadata gate only rejects the plate while the inherited
filter happens to be narrowband.

## Phase 3 — stars from the broadband plate

`merge_stars` currently loads the stretched starless image, loads its sibling
`starmask_<palette>.fits`, stretches that mask, and screen-blends it back. The
mask is the right *shape* and the wrong *stars*: starnet ran on the narrowband
palette, so the mask contains the narrowband star field.

The starnet mask is still the object to project through. It was made on the
cropped palette, so it is on the finished plate by construction. Projecting the
broadband image through that mask gives broadband star colours at the positions
and sizes of the stars the palette actually has. Running starnet a second time
on `crop_stacked_bb.fits` and hoping the two masks coincide is the worse
version: two detections, two sets of holes, and another StarNet invocation.

Add the cropped broadband plate as an optional third input of `merge_stars`:

```toml
[[stages.inputs]]
kind = "job"
name = "broadband"
after = "(denoise|crop)"
optional = true

[[stages.inputs.requires]]
kind = "filename"
value = "stacked_bb\\.fits$"
```

`denoise` is the role, so whichever denoiser ran supplies the plate. `crop` is
the fallback when that stage did not run. The filename filter keeps the other
channels out, and it prefers the denoised name because that task is the later
producer. Both SHO and HOO see the same one file. When `input["broadband"]` is
empty, the script emitted is the script emitted today.
When it is present, the star layer changes and the base does not:

```text
load <denoised plate>
save broadband
rgbcomp broadband broadband broadband -out=broadband_rgb
pm "$broadband_rgb$ * $starmask$"
save starmask
```

The plate is one layer. PixelMath will not multiply that into the three-layer
mask, and `$loaded$` is not an image variable, so the plate is named and copied
into RGB first. The screen blend stays as it is.

This needs a small, general change in the Siril tool runner, not a recipe-only
conditional. A Siril script is text; it cannot ask whether a file exists. The
recipe runtime already expands `{...}` expressions before Siril sees them, so
the script needs a truthful expansion. Writing

```text
{"" if not input["broadband"].full_paths else "load ..."}
```

by hand in every recipe is the wrong shape: the quoting is fragile, and the
following line is still in the script when the input is empty. Add a
`siril_line` helper used as `{siril_line(input["broadband"], "load {path}")}`.
Empty `FileInfo.full_paths` is already how an optional input is represented, so
the helper is a one-line predicate over a list the recipe can see. That is the
generalisation worth having: later recipes need "include this command only when
this optional input resolved", and they should not each invent a TOML-quoted
`if`.

Do not instead make the mask by subtracting a starless broadband image from the
broadband image. That reintroduces a second star detection and makes the mask
depend on StarNet having run on a file the palette never used.

## Phase 4 — tests, all of them cheap

No test in this phase runs `sb process auto`. The full run is the user's, and
it is the acceptance check at the end rather than the development loop.

Unit tests:

- `stack_broadband` is skipped when every light sequence is HaOiii or SiiOiii,
  and created when one sequence is Tri. Assert the resolved inputs, not that a
  mock was called.
- the command builder places the Ha plate last, calls `setref` with Siril's
  1-based index, and the stack selection does not include that index;
- the builder fails, before launching Siril, when the applied reference shape
  differs from the plate shape;
- `palette_broadband` rejects a file named `crop_stacked_bb.fits`;
- `merge_stars` emits today's script when the optional input is empty, and emits
  the mask-projection load when it resolves;
- `register_and_stack()` with `stack_osc`'s options reproduces the current
  `stack_osc` command string, so the extraction cannot quietly change it.

One real-Siril test, skipped when Siril is absent, following
`TestCropFilesWithSiril`: a tiny synthetic Ha plate and a tiny shifted broadband
frame. Assert the saved broadband stack has the plate's shape and that a star
planted in the broadband frame lands on the plate's star. This tests the
registration trick on seconds of data, which is the part a unit test cannot
reach.

## Acceptance on `ngc7822`

After the unit tests and the synthetic Siril test are green, the user runs the
real target. The agent does not. Before that run, `sb process doit` (or the
task graph printed by a dry run) should show `stack_broadband` depending on the
existing `stacked_Ha.fits` and the Tri session's calibrated sequence, and show
no `stack_dual_duo` task as needing a rerun. If the graph wants to redo the
dual-duo stack, stop; the stage boundary is wrong.

The run should then add `stacked_bb.fits`, `crop_stacked_bb.fits`, and
regenerated `merged_SHO.fits` / `merged_HOO.fits`. The cropped broadband plate
must be 5920 × 3328, the same shape as `crop_stacked_Ha.fits`. The thing worth
looking at in the merged image is a bright star: its colour should come from
the Tri stack, while the nebulosity is unchanged.

## Out of scope

- Continuum subtraction, RGB-star recombination beyond the screen blend, and any
  change to `palette_sho` / `palette_hoo`. Those palettes keep building colour
  from Ha, Sii and OIII.
- Replacing `stack_osc` for broadband-only targets. A target whose only lights
  are broadband still ends at `stacked.fits` and `palette_broadband`.
- Forcing a reference other than the Ha plate. Ha is the reference
  `make_renormalize()` already uses, and it is the one channel both duo recipes
  produce. A parameter can select another plate later; it is not needed to land
  this.
- A second StarNet pass over the broadband plate.

## Risks

- **The reference member changes the registration solution.** `register -2pass`
  chooses a reference from the sequence; with `setref` the Ha plate is a legal
  member, but it is one frame of a different filter and a much higher SNR. If
  Siril rejects it or aligns badly, the synthetic-Siril test is where that shows
  up. The fallback is to register the broadband sequence normally and then
  register the finished stack against the plate. That fallback is worse (two
  interpolations) and is not the plan unless the first attempt fails.
- **Drizzle plus a mono reference.** The duo stage drizzles CFA sequences. A
  sequence whose last member is already a stacked mono plate may make Siril
  refuse `-drizzle`. If it does, drizzle the broadband members, apply the solved
  transform to the reference without drizzle, and compare shapes. Do not silently
  drop drizzle for the frames.
- **Inherited metadata.** A metadata `invert` gate cannot see the filter of a
  calibrated sequence: the row inherits `FILTER` from the shared upstream task,
  which on a mixed target is HaOiii, so the Tri night would be rejected with the
  duo nights. The lights gate is therefore a filename gate on the sequence name
  (`bkg_pp_light`, excluding `Ha_bkg` and `OIII_bkg`). The Ha gate is also a
  filename. Neither gate reads the inherited `FILTER`.
- **Fingerprint.** Changing `osc.py` does not by itself invalidate `stack_osc` or
  `stack_dual_duo`. That is intended. A change to either recipe's TOML does
  invalidate that recipe, so the extraction into `register_and_stack()` should
  land only when its command-string test proves the script text is equivalent.
