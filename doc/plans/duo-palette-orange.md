# Duo (HaOiii/SiiOiii) palette — why SHO/HOO come out orange, and how to fix it

## Status

**Diagnosed 2026-10-14, not yet implemented.** Reproduced target: `ngc7822`
(`private/processed/ngc7822/`). User decisions: use `just use-local-recipes`;
fix input-range handling in `background.toml`; background extraction must run on
all workflows including duo; retain the `palette_sho` name and current channel
mapping. **Implementation decision 2026-10-14:** remove inverted SCNR; do not add a second channel match. Use the user's live Starbash configuration for validation, never force a full stack/recalibration run. Scope reprocessing to background and later tasks via doit after checking the graph (the current graph has three `seqextract_haoiii` tasks marked for rebuild).

## Summary

`palette_sho` / `palette_hoo` are not the *origin* of the orange cast. The major
imbalance appears two stages earlier at `graxpert/background.toml`. Inspection of
the installed GraXpert code reveals **range-dependent loading**, not a no-op:
images already in `[0,1]` retain their scale; images with any value outside that
range are min/max-rescaled to `[0,1]` *before* the AI sees them. Background
subtraction then preserves the mean of that **rescaled** image. GraXpert does
extract a spatial gradient in either case; the earlier claim that it did nothing
for `max <= 1` was incorrect (we checked the mean difference, not per-pixel
differences, and mean preservation is intentional).

The Ha channel leaves `stack_single_duo` clipped at exactly `1.0`; the OIII
channel leaves it at `2.08` because `osc.make_renormalize()`'s MAD-matching
PixelMath can exceed 1. GraXpert keeps Ha's scale, but globally rescales OIII,
so post-background channel medians differ by 2.7×. The fix belongs inside the
background stage, where it can handle *every* workflow without disabling
background removal.
The palette's `-rescale 0.0 1.0` cannot repair it (it is a global min→max
normalisation pinned by one saturated star pixel, i.e. a no-op), and its
`invert → rmgreen → invert` block silently throws away the `ha_weight` /
`oiii_weight` parameters. VeraLux then *faithfully preserves* the colour ratios,
so the orange arrives at the thumbnail untouched.

Non-duo `sh2126` is unaffected: its three channels arrive in `[0,1]`, so
GraXpert keeps their scale while removing background. This is *not* a no-op.

## Evidence (all measured on this machine, 2026-10-14)

Reproduce with `poetry run python` + `astropy.io.fits`; every number below is
from the files in `private/processed/ngc7822/` and `private/processing/ngc7822/`.

### 1. The stack output is balanced

`osc.make_renormalize()` MAD-matches OIII to Ha, and it works:

| file | p50 | max |
|---|---|---|
| `stacked_Ha.fits` | 2.8433e-4 | **1.000** |
| `stacked_OIII.fits` | 2.8352e-4 | **2.081** |

Medians agree to 0.3 %. **But the maxima differ**, and that is the trigger.

### 2. GraXpert `background` destroys the balance

| file | p50 | max |
|---|---|---|
| `crop_stacked_Ha.fits` | 3.0111e-4 | 1.000 |
| `bk_crop_stacked_Ha.fits` | 3.0185e-4 | 1.000 |
| `crop_stacked_OIII.fits` | 2.7838e-4 | 1.964 |
| `bk_crop_stacked_OIII.fits` | 1.1010e-4 | 1.000 |

**Correction to earlier diagnosis:** a near-zero *mean* of input minus output
is *not* a zero model. GraXpert uses `image − background + mean(background)`
(`graxpert/background_extraction.py:155-157`), so for inputs already within
`[0,1]` the mean difference is approximately zero by construction. On a sampled
set of Ha pixels, `bk − crop` has standard deviation **7.8e-6** (not zero).
OIII's lower median comes from input min/max rescaling before that correction.

Isolated experiment (`/tmp/bktest`, 1024×1024 cut of `crop_stacked_Ha.fits`,
`graxpert -cmd background-extraction`, GraXpert 3.2.0a3):

| input | max | mean(out − in) | std(out − in) |
|---|---:|---:|---:|
| `sub_Ha` (as-is) | 1.000 | ~0 | **5.43e-5** (gradient removed) |
| `sub_Ha * 0.5` | 0.500 | ~0 | **2.72e-5** (gradient removed) |
| `sub_Ha * 1.5` | 1.500 | −5.02e-4 | 2.48e-3 (rescaled + gradient removed) |
| `sub_Ha` with **one** pixel set to 1.5 | 1.500 | −3.35e-4 | 1.72e-3 (rescaled + gradient removed) |
| `sub_OIII` (as-is) | 1.964 | −2.80e-4 | 3.79e-3 |
| `sub_OIII` clipped to 1.0 | 1.000 | ~0 | **4.54e-6** (gradient removed) |

Source: `.venv/lib/python3.12/site-packages/graxpert/astroimage.py:67-73`
converts to float32 and uses `exposure.rescale_intensity(..., out_range=(0,1))`
if **min < 0 or max > 1**. `graxpert/background_extraction.py:155-169` then
subtracts the spatial background, adds its mean, and clips to `[0,1]`. A single
out-of-range pixel changes the scale of the entire input, not whether the AI
runs. The numbers above compare to the *original* input; `in − out` is not the
estimated background model for out-of-range images.

### 3. The palette's `-rescale 0.0 1.0` is a no-op

Siril source, `reference/siril/src/pixelMath/pixel_math_runner.c:832`:

```c
fit->fdata[i] = (((args->max - args->min) * (fit->fdata[i] - minimum)) / (maximum - minimum)) + args->min;
```

`minimum` / `maximum` are **global over the whole result**, not per channel and
not robust. The palette's inputs (`nx_bx_bk_crop_stacked_Ha.fits`, min 2.076e-4,
max 1.0 — one pixel) therefore get *exactly* `x − 2.076e-4`. Measured transfer
function input → `private/processing/ngc7822/Ha.fit`: slope 1.000 in every
brightness bin above the min, offset −2.076e-4. The recipe comment
("Rescale each to 0..1 so all three channels enter rgbcomp on the same
footing") describes an intent that this command cannot deliver while a star
saturates.

Post-palette channel amplitudes over background pixels: `mean(Ha) = 1.35e-4`,
`mean(OIII) = 4.15e-5` → **3.3× imbalance**.

### 4. `invert → rmgreen → invert` is destructive and cancels the parameters

`reference/siril/src/core/command.c:5803` (`process_scnr`): `rmgreen` is
SCNR *average neutral* with `args->preserve = TRUE` by default. With `preserve`,
`reference/siril/src/filters/scnr.c` runs linRGB → XYZ → Lab → clamp green →
Lab → XYZ → linRGB and then `set_float_in_interval(..., 0, 1)`. Consequences,
measured against `Ha.fit` / `SynGreen.fit` / `OIII.fit` in the process dir:

* `SHO.R = 0.9433·Ha − 5.3e-6` and `SHO.B = 0.9317·OIII − 1.02e-5` — the
  Lab round trip **rescales red and blue**, which SCNR is not supposed to touch.
* `SHO.G = 1.0014·(R+B)/2` — green is *overwritten* by the average-neutral
  clamp, so `ha_weight` / `oiii_weight` have **no effect** on the output.
* Clipped pixels go from 1 (input) to 108 in `Ha.fit` / 252 in `OIII.fit`.
* It is applied to an image whose values are all ≈ 1.0 (it is inverted), i.e.
  at the top of the gamut where the Lab round trip is least accurate.
* It does not even fix the hue: `G = avg(R,B) = 0.62·R` vs the blend's `0.59·R`.

For contrast `HOO.fits` is byte-identical to `rgbcomp(Ha.fit, OIII.fit,
OIII.fit)` — HOO has no `rmgreen` block, and its channels are untouched.

### 5. VeraLux preserves the ratios, so the orange survives the stretch

`hms_starless_SHO.fits` medians: R 0.160, G 0.094, B 0.039 (1 : 0.59 : 0.24).
`merged_SHO.fits`: 0.161 / 0.095 / 0.039. `hms_starless_HOO.fits`:
0.210 / 0.0587 / 0.0587. A neutral background would have R ≈ G ≈ B; VeraLux's
stated design is "Preserve original vector color ratios during extreme
stretching", so it is doing its job on bad input.

### 6. Non-duo keeps its scale and stays balanced

`sh2126`: `crop_stacked.fits` ch0/1/2 medians 0.001944 / 0.001945 / 0.001945,
all values in `[0,1]` → `bk_crop_stacked.fits` medians 0.001946 / 0.001944 /
0.001943, `broadband.fits` 0.001943 / 0.001942 / 0.001941. GraXpert still
removes spatial background, but does not globally rescale these inputs.

### 7. Latent bug found on the way: the two palettes race on shared scratch names

From `private/processed/ngc7822/.starbash/run-log.toml`:

* `palette_hoo_ngc7822` — 2.47 s, final `save` at t=1791997898
* `palette_sho_ngc7822` — 3.10 s, final `save` at t=1791997901
* both with `Setting CWD ... to '/home/vscode/.cache/starbash/processing/ngc7822'`

Both scripts `save Ha`, `save OIII` and `rgbcomp ... -out=results` into that one
directory, and both end with `load results`. Their windows overlap. This run got
lucky (HOO's output is exactly `Ha.fit`/`OIII.fit`), but `results.fit` is a
shared file written by two concurrent tasks — one palette can ship the other's
composition. It also means the leftover intermediates cannot be trusted for
forensics in general.

## Root causes

| # | Cause | Where |
|---|---|---|
| RC1 | GraXpert's FITS loader auto-rescales only images outside `[0,1]`; background extraction runs in *both* cases, but on different intensity scales. Per-channel multiplexing exposes the difference | `graxpert/astroimage.py:67-73`, `starbash-recipes/graxpert/background.toml` |
| RC2 | `osc.make_renormalize()`'s MAD match leaves OIII with `max > 1` while Ha is pinned at 1.0 — the asymmetry that triggers RC1; do not change its output merely to work around GraXpert | `src/starbash/recipes/osc.py:183` |
| RC3 | `-rescale 0.0 1.0` is global min→max, so it cannot equalise channels | `palette/sho.toml`, `palette/hoo.toml` |
| RC4 | No real channel balancing anywhere in the palette; whatever imbalance arrives is rendered | same |
| RC5 | `rmgreen` with default `preserve` rescales R/B, overwrites G and discards the weight parameters | `palette/sho.toml:47-51` |
| RC6 | `palette_sho` and `palette_hoo` share scratch names in one process dir | both palette recipes |
| RC7 | This recipe's `R=Ha, G=syn, B=OIII` is an HOS-ish mapping, not classic SHO (`R=Sii, G=Ha, B=OIII` — see `siril-scripts/processing/Hubble_Palette_from_Dual-Band_OSC.py:704`). This is a naming convention, **not** a demonstrated cause of the orange cast; the user chose to retain it | `palette/sho.toml` |


## Attack plan

### Phase 0 — reproduce safely with local recipes (no behaviour change)

**Already available and configured:** `just use-local-recipes` runs
`sb repo add /workspaces/starbash/starbash-recipes`; `sb repo list` currently
shows `file:///workspaces/starbash/starbash-recipes` as the active `std-recipe`.
The prior suggestion to add it manually, or assume the remote tag is active,
was wrong. Verify this state before a run; never edit the user's repo config
just to turn local testing on.

1. Use the user's live config/selection (`ngc7822` is already selected); inspect
   the resolved graph with `sb process doit list --status` and the task file deps.
   Snapshot selected output statistics and timestamps before regeneration.
2. **No full auto run or forced rebuild.** Three `seqextract_haoiii` tasks are
   already marked for rebuild, unrelated to this fix. To avoid hours of
   calibration/stacking, use `sb process doit run -s <task...>` for only the
   background stage and its downstream dependency closure, in graph order;
   `-s` skips upstream dependencies. Verify all preexisting `crop_` inputs are
   present first. Let each explicitly chosen downstream task run using its
   existing file dependencies; check its status and outputs before proceeding.
3. Record channel ratios and spatial-gradient metrics in `crop_`, `bk_`,
   `nx_`, `SHO.fits`, and thumbnails for before/after comparisons. Verify the
   effective recipe URL in the next run-log or task metadata. Never delete the
   existing stacked frames to force a rerun.

Deliverable: reproducible local recipe run and a script for per-channel
statistics; use `just use-local-recipes` only if the file repo is absent.

### Phase 1 — pin down the GraXpert contract (1 h)

The installed GraXpert source already pins down the branch:
`graxpert/astroimage.py:67-73` auto-rescales out-of-range images; the AI
background code subtracts a model but adds its mean back
(`graxpert/background_extraction.py:155-169`). Do not diagnose a no-op using
only the mean input/output difference again.

1. Re-run the cut-out probes through **`GraxpertBuiltinTool`** (in-process
   `api_run`) with the recipe's actual `smoothing_option = 0.5` and
   `ai_version = 1.0.1` (the CLI probe used stored smoothing 0.0). Measure the
   standard deviation of per-pixel input/output differences, not just the mean.
2. Confirm the loader's `[0,1]` boundary on both sides: `max = 1.0001` and
   `min = -1e-5`, including a full-size mono and RGB sample. Check that the
   intended fix does not crush highlights or change spatial background removal.
3. Audit the image loading/normalisation in the GraXpert deconvolution and
   denoising paths too; if they use the same loader, flag their scale change as
   a separate follow-up. Avoid changing them as part of the palette fix unless
   comparisons show it is necessary.

Exit criterion: same spatial gradient-removal behaviour on a predictable
intensity scale across mono and RGB input ranges.

### Phase 2 — stop the imbalance at the background stage (chosen)

**2a. Fix `starbash-recipes/graxpert/background.toml`, for every input.**
Preserve the input's physical scale across GraXpert's `[0,1]` FITS loader
contract. Work out the exact implementation during Phase 1, then implement a
recipe-local pre/post-processing wrapper (a small helper under
`src/starbash/recipes/` if required). Do **not** change
`osc.make_renormalize()` or turn off background extraction for any workflow.
The `background` stage must still run the GraXpert AI for *every* mono/RGB
input, including each `_Ha`, `_OIII` and optional `_Sii` frame and broadband
stacks. Keep its output names and downstream dependencies unchanged.

Implementation: `background.toml` passes `preserve_input_range = "true"` as a
tool parameter. `GraxpertBuiltinTool` accepts that opt-in only for
`background-extraction`, computes `offset = min(0, input_min)` and
`scale = max(1, input_max - offset)` for finite float FITS, writes
`(input - offset) / scale` to a temporary FITS if needed, calls the same
GraXpert `api_run` (preserving the tool log and progress bus), then restores
`output * scale + offset` with GraXpert's FITS header. Inputs already inside
`[0,1]` follow the original unmodified path. Unique `TemporaryDirectory`
per task cleans up on success or failure. Stage outputs remain `bk_*`.
Tests cover in-range, over-1, negative, constant and RGB images, metadata,
invalid pixels, and a real GraXpert 1024×1024 OIII cut. A fix that divides
by a channel's maximum and *does not restore the scale* is not acceptable:
it reproduces the current colour skew intentionally.

Acceptance is **not** "all RGB medians match": GraXpert removes a *spatial*
background and preserves each channel's mean; genuine Ha/OIII signal can
remain different. Instead verify mean-scale preservation to numerical tolerance,
non-zero spatial correction, dynamic-range preservation, no unexpected clipping,
and no new channel skew attributable to the wrapper. Test both `max = 1` and
`max > 1`, negative minima, mono and RGB with gradients and highlights.

**2b. No second palette balance (decided).** Re-run
ngc7822 after fixing the source and measure the background and signal
separately; do not add another channel normalisation. The current
`-rescale 0.0 1.0` comment/premise is misleading; remove or replace that step
only on measured evidence. Do *not* automatically median+MAD match the
palette: the stack already does this and a second match after denoise can
amplify noise or erase real Ha-dominant structure. See the explanation and
question below.

**2c. Remove `rmgreen` (decided).** The inverted default destroys the
user-facing green weights. Remove the block and compare the resulting SHO
against the old image after applying 2a; keep the weights functional. Switching
instead to `-nopreserve` would still clamp synthetic G when below `(R+B)/2`,
so it is not a fix for the weight parameters.

### Phase 3 — remove the scratch-name race (small, independent)

Give each palette task unique intermediates. The context already carries a
per-task identity (the multiplex suffix / stage name), so either:

* `save Ha_{stage}` / `save OIII_{stage}` / `rgbcomp ... -out=results_{stage}`,
  or
* derive the scratch names from `{output.full_paths[0].stem}` and declare them
  in the stage's `temporaries`.

`palette/broadband.toml` and `post/merge_stars.toml` also `save starless` /
`save stars` / `save results` — audit every Siril recipe for shared scratch
names written into `process_dir` while multiplexed/parallel tasks are in flight,
and fix them in one pass.

### Phase 4 — preserve the SHO naming and mapping (decided)

Keep `palette_sho`, `SHO.fits` and today's mapping (`R=Ha`, `G=real Sii or
synthetic blend`, `B=OIII`). Do not introduce `palette_hos` or swap R/G in
this fix. Note only as a documentation caveat: conventional SHO maps real Sii
to red and Ha to green (reference:
`siril-scripts/processing/Hubble_Palette_from_Dual-Band_OSC.py:703-708`), but
this recipe intentionally retains the user's current palette/naming contract.

### Phase 5 — regression tests

1. **Unit, background wrapper** — use synthetic mono/RGB float FITS with
   realistic gradients, an out-of-range highlight, negative minimum and an
   all-zero case. Assert that after a real or stubbed GraXpert call, corrected
   pixels retain their original dynamic range/mean to defined tolerance and
   the spatial gradient is reduced in all cases. Verify temporary files and
   headers; do not test by comparing *only* input/output means.
2. **Unit, recipe contract** — render the `background.toml` and `sho.toml`
   scripts with the existing context-expansion machinery and verify the scale
   wrapper, unique scratch names, original output paths, and stable mapping.
3. **Numerical palette test (only if balancing is chosen)** — compare star and
   diffuse-nebula signals separately, assert no NaN/Inf or excess clipping, and
   test against an unbalanced fixture. Do not require all channels' p50 or p99
   to agree exactly: actual Ha-dominant signal is allowed.
4. **Integration** — `tests/integration/test_workflow.py` already runs the duo
   path (target `m20`, HaOiii + SiiOiii) and already fails on any `Failed` row.
   Check `crop_` versus `bk_` channel scale, *within each channel*, for
   unintended max-dependent rescaling; measure removed spatial gradients.
   Assert pipeline finishes with intact outputs. Do not enforce neutral palette
   medians, because Ha-dominant targets legitimately have unequal channel signal.
5. **Manual acceptance** — re-run ngc7822, compare `hms_starless_SHO.jpg` /
   `merged_SHO.jpg` against `/tmp/before/`, and record the before/after medians
   in this file.


## 2026-10-14 follow-up — real Sii was not reaching SHO; blue still dims at BXT

The user's newer `sb process auto` built `stack_dual_duo` and generated
`stacked_Sii.fits` plus all `*_Sii.fits` downstream, but the run-log listed
only Ha/OIII as inputs to `palette_sho`. The palette recipe maps **R=Ha,
G=Sii (or synthetic green), B=OIII**; Sii is not the blue channel.

The `sii` input in `palette/sho.toml` required both upstream
`FILTER=SiiOiii` and an `_Sii` filename. A multiplexed noise task that outputs
`nx_bx_bk_crop_stacked_Sii.fits` inherits `FILTER=HaOiii` from the shared
stack/target context. `_import_from_prior_stages` applied the metadata gate to
that inherited value *before* testing the actual output's filename, so the
optional Sii input came back empty and synthetic green was used. The recipe
now selects the actual `_Sii` output by filename alone. A unit test covers
both presence (despite inherited HaOiii) and absence (synthetic fallback).
The live task graph was checked: `palette_sho_ngc7822` now depends on all
three `nx_bx_bk_crop_stacked_{Ha,OIII,Sii}.fits`. Only the SHO branch was
rerun (`sb process doit run -s` per task). Comparing current `SHO.fits` to
scratch `SHO_{Ha,SynGreen,OIII}.fit`, all three channels match exactly; green
is now derived from real Sii. SHO, starnet, VeraLux, merge, and both SHO JPEG
thumbnail tasks completed; no stack or master tasks were rerun in this pass.

**Blue is still dim** in the current output. Measured sampled medians:

| channel | after `background` | after `blur_exterminator` | after `denoise` | `SHO.fits` |
|---|---:|---:|---:|---:|
| Ha → red | 3.47e-4 | 3.43e-4 | 3.40e-4 | 8.83e-5 |
| OIII → blue | 3.23e-4 | 1.60e-4 | 1.57e-4 | 2.23e-5 |
| Sii → green | 3.34e-4 | 1.50e-4 | 1.46e-4 | 2.66e-5 |

The drop at BXT is close to dividing by each out-of-range channel's **global
maximum**: BXT's median output/input ratio for representative faint pixels is
0.4987 for OIII (input max 1.9996), 0.4542 for Sii (input max 2.1870), but
0.9978 for Ha (max 0.9800). The blue channel is present — its OIII image
was attenuated before palette composition. `-rescale 0.0 1.0` in the palette
subtracts the input minimum (for OIII ≈1.35e-4) and further reduces its
linear pedestal; its global max is pinned at 1. Do not confuse these medians
with a pixelwise comparison of a nebula region: this documents scale loss,
not a desired colour balance.

**Next decision, separate from the background fix:** do we extend
range-preserving pre/post handling to the rc-astro deblur stage, preserving
BXT tool progress/metadata and existing outputs? Confirm the BXT loader or
run a controlled small comparison before changing it. Avoid blindly matching
SHO channel medians or swapping Sii and OIII: that does not repair the
upstream loss of signal. This plan records the finding; BXT code was not
changed by the Sii fix.

## 2026-10-14 follow-up — optional sky-anchored SHO colour strengths

Implemented in `starbash-recipes/palette/sho.toml`: `green_strength` and
`blue_strength`, both default `1.0` (identity). The suggested *target-specific*
starting point for ngc7822 is green `1.5`, blue `2.0`; these are **not** global
defaults. After the existing per-channel `-rescale`, each non-red channel
`x` with median `b` receives a monotone highlight-tapered boost:

```text
t = max(x - b, 0) / (1 - b)
boosted = x + (1 - b) * ((k * t) / (1 + (k - 1) * t) - t)
```

The equivalent Siril PixelMath expression uses `max()`, `median()` and arithmetic.
For `k=1` it leaves the pixels unchanged; for `k>1` it leaves pixels <= `b`
unchanged, lifts positive signal increasingly less near the white point, and
fixes 1 at 1. Median is an approximation to the sky (not a spatial model),
so some noise above the median is boosted too. This is *artistic control*, not
an attempted repair of the outstanding BXT scale loss noted above.

Green is still produced from real Sii when present and the original Ha/OIII
blend otherwise. **Blue is boosted only after green was saved**, so changing
blue strength cannot affect synthetic green on single-duo targets. No additional
min/max rescale follows the boost: doing so would undo it. The original stage
name, channel mapping and output name remain unchanged. Tests in
`tests/unit/test_sho_palette.py` run the actual recipe through installed Siril
on tiny synthetic FITS with real Sii and without it: sky pixels stay put,
nebula pixels rise, white pixels stay white, RGB remains within range, red
stays fixed, and the blue control is independent of green. `just lint` and
109 focused tests passed. No live target outputs were regenerated for this
change.

## 2026-10-14 follow-up — optional red suppression in OIII-rich pixels

The user tried `green_strength = 2`, `blue_strength = 8` in the local recipe;
bright OIII regions looked violet because they also carried strong Ha. The
user subsequently tuned the recipe defaults to **green=2, blue=4.0 and
red_suppression=0.5**. Preserve those choices rather than reverting to earlier
recommended defaults. A sampled 8×8 view of the current ngc7822 `SHO.fits`
shows blue-bright pixels with median R≈4.80e-4 and B≈5.57e-4 (G≈1.76e-4).
A red-vs-blue overlap, not missing OIII, explains the purple cast.

Implemented an optional `red_suppression` parameter in `palette/sho.toml`.
It was introduced at neutral default 0.0, but the user then changed the
recipe default to **0.5** during validation; preserve that user choice.
An explicit per-target override of 0.0 restores the previous red channel.
After green synthesis and blue boost, red is reduced in proportion to
**the stronger of real Sii/green and OIII/blue above-median signals**. Synthetic
green is Ha/OIII-derived and is deliberately excluded from the mask, otherwise
Ha-only nebula would suppress itself:

```text
r = max(R - median(R), 0); b = max(B - median(B), 0)
g = max(G - median(G), 0) if real Sii is present else 0
c = max(b, g)
R_new = R - red_suppression * r * c / (r + c + 1e-6) * (1 - R)
```

G and B are **already boosted**. Using `max` rather than adding G+B prevents
double-counting overlapping OIII/Sii. If R or both independent colour signals
are at/below their median, or if R=1 (white star core), red is unchanged.
For 0..1 strength, R_new stays between the red median and R, with the taper
protecting highlights; G/B and the stage's channel mapping are unchanged.
On a previous ngc7822 sample (blue default 8), blue-bright median R went
4.80e-4 → 3.69e-4 at 0.5 while B stayed 5.57e-4. These figures do not predict
the current appearance at blue=4. The formula does not neutralize a red sky
cast or restore the separate BXT scale loss.

`tests/unit/test_sho_palette.py` now drives the complete recipe through real
Siril at explicit green=2, blue=8 (the prior high-blue experiment), comparing
suppression=0/0.5/1 for both real Sii and synthetic green. It verifies red
decreases in OIII-bright regions and in real-Sii-only emission, while sky,
Ha-only structure, white cores, G/B and synthetic-green independence are
preserved. An additional test verifies increasing `green_strength` strengthens
the red reduction only in real-Sii regions. No full run or large target
regeneration was performed for this tweak.

## Files expected to change

| File | Repo | Phase |
|---|---|---|
| `starbash-recipes/graxpert/background.toml` | submodule | 2a |
| `src/starbash/tool/graxpert.py` | main | 2a |
| `starbash-recipes/palette/sho.toml` | submodule | 2b/2c (if needed), 3, 4 |
| `starbash-recipes/palette/hoo.toml` | submodule | 2b (if needed), 3 |
| `starbash-recipes/post/merge_stars.toml`, `common/starnet.toml` | submodule | 3 (audit) |
| `tests/unit/test_graxpert_background.py`, `tests/integration/test_workflow.py` | main | 5 |
| this file | main | all |

Note the two repos: `starbash-recipes` is a **submodule**, so recipe edits are a
separate working tree and a separate commit the user makes there. The active
runtime uses that checkout via `just use-local-recipes`; a future published
release will need an appropriate recipe tag/version and main-repo submodule
pointer update, at the user's chosen time.

## Risks

* **Changing `background` changes every target**, broadband included. The AI
  runs today even when `max <= 1`; preserving the old scale for inputs already
  in range should leave those outputs unchanged, while correcting out-of-range
  inputs will visibly change their colours/highlights. Check representative
  broadband and duo targets before release.
* **Per-channel balancing can amplify noise** in a genuinely faint channel
  (matching OIII's MAD to Ha's multiplies OIII's noise by the same factor).
  Consider balancing the *background/median* only and leaving the MAD alone, or
  balancing after denoise (which is where the palette already taps in).
* **A real colour cast can be signal.** Ha-dominant nebulosity *should* look red
  in HOO; over-balancing flattens the astrophysics. The threshold in test 5.4
  must stay loose enough to allow a genuinely Ha-bright target.
* GraXpert's loader auto-rescales on `max > 1` **or** `min < 0`; this is an
  upstream implementation detail that may change, so the stage wrapper must
  detect/verify the contract, preserve the FITS metadata, and never silently
  clip or overflow restored values. Keep true background *gradients* removable.
* Phase 3 touches filenames inside recipe scripts — a stale `results.fit` in an
  existing `process_dir` could satisfy a doit dependency by accident. Verify the
  scratch names are not declared as outputs anywhere.

## Decisions and remaining questions

**Settled by the user (2026-10-14):** use the existing
`just use-local-recipes` path; fix range handling in `background.toml`;
background removal must run for *all* workflows, including duo; keep the
recipe/output named SHO with today's channel mapping.

**Q3 — What to do with the inverted `rmgreen` step?** Siril's `rmgreen` removes
*green* when it exceeds `(R+B)/2`. We invert to make magenta count as green,
then invert back. That translates into `G_final = max(G_before, (R+B)/2)`.
With `-nopreserve` it keeps R/B unchanged but still imposes that green floor.
Current default also preserves Lab lightness by adjusting R/B; this mutates
colour ratios and can clip. On this target `G = 0.4 Ha + 0.6 OIII` is *below*
`(Ha+OIII)/2` in nearly all Ha-rich pixels, so the floor replaces the blend:
changing `ha_weight`/`oiii_weight` does not change visible output there.

- **Decided:** remove the SCNR block entirely; keep synthetic green from
  its explicit blend parameters. Compare before/after SHO after the background
  fix, and add an optional tint control later if a magenta case really needs it.
- Alternative: `rmgreen -nopreserve` keeps R/B exact but **still overrides
  synthetic green** wherever it is below the floor; it is not a solution for
  users who expect the green weights to work.

**Q5 — Does the palette need a second channel match at all?** Separate
*background* (sky pedestal), *spread/noise* (MAD), and *signal* (nebulosity and
stars). `make_renormalize()` has already matched Ha/OIII median and MAD at the
stack. The divergence here was an accidental later scale conversion; fix and
measure that first. To explain the optional choices:

- **Median-only:** add an offset until the channel *sky* medians agree. Neutral
  sky, but it changes the black point and does not equalise nebulosity.
- **Median+MAD:** also multiply the channel's contrast/noise to match the
  reference. Stronger hue change, but amplifies faint-channel noise and may
  undo the real relative Ha/OIII brightness.
- **Percentile (p99):** match upper brightness including nebula/stars; a few
  bright stars can dominate it, and legitimate Ha-rich nebulosity is flattened.

**Decided:** no automatic second match by default. Keep `R=Ha`,
`G=Sii/synthetic`, `B=OIII`, repair the background stage, then compare sky
background and actual nebula regions in ngc7822. Only add a bounded,
user-adjustable palette strength/colour control if the corrected image still
needs it. Ask for a specific visual example before choosing which signal to
normalise; a forced `median(R)=median(B)` is *not* an acceptance criterion.

## Quick verification snippets

Per-channel medians of any palette output (a diagnostic for before/after; do not demand equality):

```bash
poetry run python - private/processed/ngc7822/{SHO.fits,hms_starless_SHO.fits,merged_SHO.fits} <<'EOF'
from astropy.io import fits
import numpy as np
import sys
for f in sys.argv[1:]:
    d = np.asarray(fits.getdata(f), dtype=float)
    chans = d if d.ndim == 3 else d[None]
    print('%-40s' % f.split('/')[-1],
          ' '.join('ch%d med=%.4g' % (i, np.median(c)) for i, c in enumerate(chans)))
EOF
```

GraXpert range probe (Phase 1), on a small cut so it finishes in seconds:

```bash
graxpert -cmd background-extraction -output out.fits in.fits
```

then measure the *pixelwise* difference `out − in` (standard deviation, median
and bright-pixel changes). A zero **mean** alone is expected with GraXpert's
background-mean-preserving subtraction and does **not** mean it skipped work.

