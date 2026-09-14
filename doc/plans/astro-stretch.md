# astro-color-stretch (ACS) — port plan

Status: **in progress** (decisions resolved 2026-09-14; phases 1-4 landed).
Owner: Kevin Hester. Reference upstream: `reference/astro-color-stretch/astro-color-stretch-1.2.py`.

## 1. Goal / summary

Port David M. Jones' **astro-color-stretch** (`rnc-color-stretch` in Python) into
Starbash as a first-class post-processing stage that sits **where VeraLux
HyperMetric Stretch sits today**, so a target can be stretched with either engine
(or both, for comparison) and so that ACS' richer feature set (black-point
zero-sky estimation, ratio/HSV color correction, CA / vignette / gradient
correction, star-size reduction, RL deconvolution) becomes available to recipe
authors and to the GUI.

Deliverables:

| Deliverable | Path |
|---|---|
| Recipe (stage, options + defaults) | `starbash-recipes/post/astro-color-stretch.toml` |
| Engine (ported Python, `acs_` stage) | `src/starbash/recipes/astro_color_stretch.py` |
| Recipe registered in the default manifest | `starbash-recipes/starbash.toml` (`[[repo-ref]]`) |
| Attribution | GPL header in the engine file + `README.md` → *Credits* |
| Tests | `tests/unit/test_astro_color_stretch.py`, `tests/unit/test_tool.py` (recipe wiring) |
| Docs | this plan; a short section in `doc/toml/guide.md`-adjacent docs if needed |

Explicitly requested upstream behaviours we are **keeping**:

* output files are prefixed `acs_` (VeraLux uses `hms_`),
* copyright/GPL statement for **both** upstream authors at the head of the ported file,
* credit for both authors in the project `README.md`,
* initially reachable **only via recipes/workflow steps** (a future, separate task may
  drive it from the GUI image viewer for a prettier preview — the engine is therefore
  designed as a pure array-in/array-out function).

## 2. Sources

* Reference source: `reference/astro-color-stretch/astro-color-stretch-1.2.py` (1847 lines).
* `reference/astro-color-stretch/README.md` — the task brief + license text.
* Setup & parameter guide 1.2: <https://dmjonesphotography.com/astro-color-stretch-setup-and-parameter-guide-1-2/>
* Rationale / background article: <https://dmjonesphotography.com/fast-image-stretching-with-astro-color-stretch/>
* License: <https://dmjonesphotography.com/astrophotography-software-downloads/>

### License & attribution

Upstream is **GPL** (`Copyright (c) 2025/2026, David M. Jones, dmjonesphotography.com`,
plus the inherited terms of Roger N. Clark's original `rnc-color-stretch`).
Starbash itself is **GPL-3.0** (`LICENSE`), so there is no licence conflict. Required:

1. The ported file starts with the upstream program name/version, both copyright
   lines (Jones; and the "adaptation of Roger Clark's rnc-color-stretch" note) and
   an `SPDX-License-Identifier: GPL-3.0-or-later` line, mirroring how
   `siril-scripts/processing/VeraLux_HyperMetric_Stretch.py` does it.
2. A note that the file is a port, with the upstream file/version it was ported from,
   so future merges of upstream fixes are possible.
3. `README.md` → *Credits* gains entries for David M. Jones and Roger N. Clark.
   The licence also forbids using the authors' names to endorse derivatives —
   the credit text must stay factual (no "recommended by", no marketing).
4. `starbash-recipes/post/astro-color-stretch.toml` carries `[recipe] author.name/email`
   for the *recipe* (the port) — attribute the port to Starbash, keep upstream
   credit in the engine header, in the recipe `description`, and in the README.

## 3. Reference inventory → port map

The reference is a single top-level script (there is no function for the file-level
flow). Everything below keeps the **same algorithm and the same defaults**; only I/O,
channel order, logging, error handling and matplotlib/histogram-file output change.

| Reference (line) | Port | Notes |
|---|---|---|
| `check_parameters` (184) | `StretchParams.validate()` | ranges kept verbatim; `print`+`sys.exit` → `ValueError` listing every problem |
| `print_parameters` (278) | `StretchParams.describe()` + `logger.info` | the effective-settings echo stays — it replaces the `write_full` filename feature |
| `read_file` (388) | `load_image()` adapter | no `cv2.imread`, no extension checks; reads FITS from the pipeline and scales to 0–65535 float64 |
| `build_output_basename` (475) / `get_unique_filename` (544) | *dropped* | replaced by the stage's `auto.prefix = "acs_"` + Starbash's non-overwriting naming |
| `write_file` (556) | `save_image()` via `SirilInterface.set_image_pixeldata` | preserves the input FITS header (same as VeraLux) |
| `image_stats` (582) | `log_image_stats()` | same numbers, `logger.info` instead of `print` |
| `plot_rgb_histograms` (596) | *dropped* | matplotlib-only; not needed, and we do not want the dependency |
| `split` (630) | `split_channels()` | `RED, GREEN, BLUE = 2, 1, 0` becomes `0, 1, 2` (see §5.3) |
| `convert_seconds` (640) | `_human_seconds()` | tiny local helper |
| `align_channels` / `ca_correction` (655/677) | same names | `cv2.merge([b, g, r])` → `cv2.merge([r, g, b])` |
| `subtract_vignetting` / `vignette_correction` (693/733) | same | 1:1 |
| `subtract_gradient` / `gradient_correction` (753/795) | same | 1:1 |
| `fix_out_of_bounds` (812) | same | 1:1 |
| `select_dark_region` (858) | `select_dark_region()` | **drops** the debug TIFF writes (`*-selected-dark-sky-region.tif`, `*-selected-dark-sky-location.tif`) and the histogram plots; **adds** bounds validation of `ulx/uly/win_width/win_height`; `COLOR_BGR2GRAY` → `COLOR_RGB2GRAY` |
| `plot_sky_zero_histograms` (937) | *dropped* | debug plotting only |
| `rgb_sky_zero` (950) | `rgb_sky_zero()` | 1:1 — this is the black-point core |
| `max_histogram` / `smooth_histogram` (1070/1090) | same | 1:1 |
| `set_minimum` (1110) | `set_minimum()` | 1:1 |
| `image_stretch` (1133) / `s_curve` (1264) | same | 1:1 (root-power/asinh/log, 1–2 passes, 4 s-curve levels) |
| `color_correct` (1310) | `color_correct()` | ratio + HSV methods; `COLOR_BGR2HSV_FULL` / `COLOR_HSV2BGR_FULL` → RGB variants |
| `hsv_adjust` (1510) | `apply_hsv_adjust()` | renamed so the parameter can keep the name `hsv_adjust`; RGB cvtColor codes |
| `apply_white_balance` (1546) | same | `cv2.merge((b, g, r))` → `(r, g, b)` |
| `detect_stars` / `preserve_core_shrink_halo` / `reduce_star_sizes` (1602/1629/1669) | same | `COLOR_BGR2GRAY` → `COLOR_RGB2GRAY` |
| `richardson_lucy_deconvolution` (1724) | same | `skimage.restoration.richardson_lucy`; local constants `lum_blur_sigma = 0.5`, `moffat_beta = 4.0` stay module constants (not parameters) |
| `MAIN` (1803–1847) | `stretch_array()` | call order preserved exactly: ca → vignette → gradient → dark region → rgb_sky_zero → (copy) → stretch → s_curve → set_minimum → color_correct → hsv_adjust → white balance → RL → star reduction |

## 4. Integration design

### 4.1 Where the stage sits

A mirror of the VeraLux stage — same slot, different engine:

* `tool.name = "python"` (like VeraLux) — no Siril binary needed; FITS I/O goes
  through `starbash.sim_siril`, again exactly like VeraLux.
* `[[stages.inputs]] kind = "job"`, `after = "(starnet|palette_broadband).*"`,
  `multiplex = true` — one task per upstream file, so multi-file palettes each stretch.
* `[[stages.inputs.requires]]`: `min_count = 1`, plus the `filename`/`exclude`
  `starmask` filter (identical to VeraLux) so the star mask is never stretched.
* `[[stages.outputs]] kind = "processed"` with `auto.prefix = "acs_"`.
* **Enabled by default** (decided — no `exclude_by_default`; see §10). A target that has the
  stage gets it, like every other stage in the default recipe; a user who does not want it
  unticks it per target in the GUI *Targets* tree or sets it in `.starbash/main.toml`.

  Note the deliberate consequence, recorded so it is not a surprise in review: a target whose
  `starbash.toml` *excludes* `veralux` (the stage it replaces) will now run ACS instead, and a
  target that runs VeraLux produces both `hms_*` and `acs_*` outputs. That A/B is useful for
  tuning, but it means the stage will appear in existing targets' pipelines on the next run.
  If that proves noisy the one-line change is `exclude_by_default = true` (precedent:
  `graxpert/denoise.toml`, `graxpert/deconv-obj.toml`).

ACS does its own black point, stretch and colour restore (plus optional star-size
reduction and deconvolution), so it is deliberately **not** chained after VeraLux: it
replaces the stretch rather than refining it. Running both stages is legal and yields
`hms_*` **and** `acs_*` files for the same input — that is the A/B comparison path.

### 4.2 Recipe TOML skeleton (`starbash-recipes/post/astro-color-stretch.toml`)

```toml
[repo]
kind = "recipe"

[recipe]
description = "Stretch a stacked image with astro-color-stretch (David M. Jones, GPL) - black point, stretch and colour restore in one pass."

[[stages]]
name = "astro_color_stretch"
description = "astro-color-stretch: zero-sky black point, stretch, colour restore"
tool.name = "python"

script = '''
    from starbash.recipes import astro_color_stretch
    astro_color_stretch.logger = logger
    astro_color_stretch.run(context)
    '''

[[stages.inputs]]
kind = "job"
after = "(starnet|palette_broadband).*"
multiplex = true

[[stages.inputs.requires]]
kind = "min_count"
value = 1

[[stages.inputs.requires]]
kind = "filename"
value = "starmask"
mode = "exclude"

[[stages.outputs]]
kind = "processed"
auto.prefix = "acs_"

# ... ~40 [[stages.parameters]] tables (see section 4.3) ...
```

Notes on this idiom:

* This is the `common/crop.toml` pattern (thin inline `script` to packaged module), not the
  VeraLux `script-file` pattern. Rationale: the port is ~1500 lines of numpy/OpenCV;
  keeping it in `src/starbash/recipes/` means it is `ruff`/`basedpyright` checked,
  importable in unit tests, and free of RestrictedPython restrictions (`_`-prefixed names,
  guarded attribute access, no file I/O via `cv2.imread` entry points).
  `src/starbash/recipes/README.md` already documents that such helpers live in the package
  "until they are refactored" into the recipes repo, so this follows the current convention.
  If they later move, only the inline `script` changes.
* The inline script passes `context` (not 40 individual parameters) so
  `test_tool.py::TestRecipeParameterReferences` - which requires every `parameters.x`
  reference in a recipe `script` to be declared - stays satisfied trivially, and so the
  module remains the single source of truth for parameter names. A dedicated test compares
  `StretchParams` field names against the TOML's declared parameter names instead.
* `[[repo-ref]] dir = "post/astro-color-stretch.toml"` must be added to
  `starbash-recipes/starbash.toml`. The recipes repo is a *separate* GitHub repo
  (`geeksville/starbash-recipes`), and Starbash fetches it from
  `.../starbash-recipes/v${version}` with the local submodule as the dev fallback. Until the
  new file is pushed and a matching version exists, local testing uses the submodule -
  either `force_local_recipes = True` in `app.py`, or `sb repo add file://...`/a temporary
  `[[repo-ref]] url`. Coordination step, not a code step (see section 7).

### 4.3 Parameters (all declared, defaults = upstream 1.2)

Every user-modifiable variable of the reference becomes a `[[stages.parameters]]` entry
with the **upstream default and the upstream valid range** (the range is enforced in
`StretchParams.validate()` and also stated in the parameter `description`, so a GUI tooltip
matches the guide). Names are snake_case; where a rename corresponds to a symbol in the
setup guide, the guide's symbol is named in the description.

File/flow variables of the reference (`dirpath`, `infile`, `ftype`, `write_full`,
`plot_hist`, `ofname_skyzero`) are deliberately **not** parameters - Starbash owns input,
output path, output name and format.

| TOML name | Guide symbol | Type | Default | Range / choices |
|---|---|---|---|---|
| `stretch_type` | `stretch_type` | int | `1` | 0 none, 1 root-power, 2 asinh, 3 log |
| `rootiter` | `rootiter` | int | `1` | 1 or 2 |
| `rootpower` | `rootpower` | float | `20` | 1-600 |
| `rootpower2` | `rootpower2` | float | `2` | 1-600 |
| `asinhiter` | `asinhiter` | int | `1` | 1 or 2 |
| `k1` | `K1` | float | `100` | 1-1000 |
| `k2` | `K2` | float | `5` | 1-1000 |
| `logiter` | `logiter` | int | `1` | 1 or 2 |
| `log_k1` | `logK1` | float | `100` | 1-500 |
| `log_k2` | `logK2` | float | `5` | 1-500 |
| `scurve` | `scurve` | int | `1` | 0-4 (0 none, 1 s1, 2 s1+s2, 3 s1+s2+s1, 4 s1+s2+s1+s2) |
| `color_correction_type` | `color_correction_type` | int | `1` | 0 none, 1 ratio, 2 HSV |
| `colorenhance` | `colorenhance` | float | `1.0` | 0.0-2.0 |
| `gamma` | `gamma` | float | `5.0` | 0.1-10.0 (HSV method only) |
| `hsv_adjust` | `HSVadjust` | bool | `false` | on/off |
| `hue_adjust` | `hue_adjust` | float | `0` | -180 to 180 degrees |
| `sat_adjust` | `sat_adjust` | float | `1.0` | 0.0-2.0 |
| `val_adjust` | `val_adjust` | float | `1.0` | 0.1-2.0 |
| `vib_adjust` | `vib_adjust` | float | `0.0` | -1.0 to 1.0 |
| `wb_mode` | `wb_mode` | int | `0` | 0 none, 1 gray world, 2 temp/tint |
| `temp` | `temp` | float | `1.0` | 0.8-1.2 (`wb_mode = 2`) |
| `tint` | `tint` | float | `1.0` | 0.7-1.3 (`wb_mode = 2`) |
| `ca_correct` | `ca_correct` | bool | `false` | on/off — deviation 7: upstream defaults to `true`, but this stage receives the *starless* frame |
| `vn_correct` | `vn_correct` | bool | `false` | on/off |
| `vn_strength` | `vn_strength` | float | `30` | 0-100 (%) |
| `lg_correct` | `lg_correct` | bool | `false` | on/off |
| `lg_strength` | `lg_strength` | float | `100` | 0-100 (%) |
| `star_reduction` | `star_reduction` | bool | `false` | on/off |
| `reduction_strength` | `reduction_strength` | float | `1.0` | 0.0 (none) - 1.0 (full) |
| `rl_deconvolve` | `rl_deconvolve` | bool | `false` | on/off |
| `rl_iterations` | `rl_iterations` | int | `15` | 1-40 |
| `psf_sigma` | `psf_sigma` | float | `0.8` | 0.1-3.0 |
| `skylevelfactor` | `skylevelfactor` | float | `0.06` | > 0; "0.06 for most cases" |
| `zeroskyred` / `zeroskygreen` / `zeroskyblue` | same | float | `4096` | 0-25000 |
| `setmin` | `setmin` | bool | `false` | on/off |
| `setminr` / `setming` / `setminb` | same | float | `4096` | 0-20000 |
| `rgbskyzero_method` | same | int | `0` | 0 full image, 1 auto-scan, 2 manual window |
| `ulx`, `uly` | same | int | `1000`, `1000` | >= 0, window must fit the image (method 2) |
| `win_width`, `win_height` | same | int | `500`, `700` | >= 1 and <= image size (methods 1/2) |
| `win_frac` | same | int | `10` | 1-10 |

Validation parity notes:

* The reference's `check_range`/`check_choice` feedback is preserved but collected:
  `validate()` raises a single `ValueError` naming *all* out-of-range parameters (upstream
  printed each and called `sys.exit()`).
* Conditional checks stay conditional (`root*` only for `stretch_type = 1`, `temp`/`tint`
  only for `wb_mode = 2`, `vn_strength` only when `vn_correct`, and so on).
* `k1`/`k2`/`log_k1`/`log_k2` are the only parameter renames; their descriptions carry the
  guide's `K1`/`K2`/`logK1`/`logK2` names.

### 4.3.1 Tuning notes carried over from the setup guide

These come from the guide and become the wording of the parameter `description` strings (and
are what makes the defaults defensible):

* **Stretch choice is data- and taste-dependent.** Root-power (`rootpower = 20`), asinh
  (`k1 = 100`) and log (`log_k1 = 100`) are all in the same family of monotonic
  dynamic-range compressions; the guide's advice is to try one and vary the exponent, not to
  hunt for a "correct" type. Aesthetic/quick-start defaults come from the 1.2 source
  (`stretch_type = 1`, `rootpower = 20`, `scurve = 1`).
* **`skylevelfactor = 0.06` and `zerosky* = 4096` are the "for most cases" values.** The black
  point is per channel on purpose: the guide's own example (moonlit sky pushing light
  pollution into blue) needed a *different* `zeroskyblue`. Exposing all three is essential,
  not decorative.
* **`rgbskyzero_method`**: `0` (full image) is the baseline, `1` (auto-scan) is recommended
  when gradients/light pollution make the whole-frame histogram unrepresentative, `2`
  (manual) when the user knows the darkest patch. For the auto-scan, `win_frac = 1` steps the
  window by its own size (fastest, least accurate); `win_frac = 10` steps by 1/10 of the
  window (more accurate, still quick).
* **Window sizing**: the guide starts around 700 px per side for a 45 MP frame - too small is
  noisy/pixelated, too large picks up sky glow. Our defaults keep upstream's `500 x 700`, and
  the added bounds validation (section 5.4) turns a nonsense window on a small image into a
  clear error instead of a crash.
* **`setmin`** is the safety net against crushed blacks (0-20000 DN), off by default.
* **Fast iteration is expected**: upstream notes runs of "less than a second for small
  dark-region images" and encourages repeated runs with tweaked `zerosky*`. In Starbash a
  re-run replaces the same `acs_*` file (upstream instead wrote `-1`, `-2`, ... suffixes and
  embedded parameters in the name). That difference is why the parameter echo
  (`StretchParams.describe()`) and the optional FITS provenance cards matter: they are how a
  user knows what produced a given `acs_*` file. (If A/B iteration on one target turns out to
  be a common need, a follow-up could add an opt-in suffix parameter - out of scope here.)

### 4.4 Output naming, GUI behaviour

* Output: `auto.prefix = "acs_"` - e.g. input `starless_broadband.fits` becomes
  `acs_starless_broadband.fits` in the target's processed dir, matching the `hms_` shape that
  `merge_stars` already works with. No `write_full`-style parameter list in the name; instead
  the effective settings are logged (`StretchParams.describe()`) so a run is reproducible.
  (FITS header provenance was considered and dropped - §10 Q6.)
* The GUI *Targets* tree needs no new code: it already renders every declared parameter of a
  stage, colours overridden rows, and coerces typed edits (`coerce_override`) - bools, ints
  and floats all round-trip (`"true"`/`"false"` -> bool, numeric text -> int/float). The
  40 new parameters therefore appear automatically under the `astro_color_stretch` stage,
  and the stage checkbox (checked by default — see §10) enables it.

## 5. Engine design (`src/starbash/recipes/astro_color_stretch.py`)

### 5.1 Public API

```python
@dataclass
class StretchParams:
    """Every user-tunable ACS setting (field names == TOML parameter names)."""
    stretch_type: int = 1
    ...                                   # see 4.3, all with upstream defaults

    @classmethod
    def from_context(cls, context: dict) -> "StretchParams": ...
    @classmethod
    def from_parameter_object(cls, parameters: Any) -> "StretchParams": ...
    def validate(self) -> None: ...        # raises ValueError listing every problem
    def describe(self) -> list[str]: ...   # the print_parameters() echo, one line per setting

def stretch_array(im: "np.ndarray", params: StretchParams, logger=logger) -> "np.ndarray":
    """Run the full ACS pipeline on float64 (H, W, 3) data in 0..65535."""

def load_image() -> "np.ndarray": ...   # FITS -> float64 (H, W, 3) in 0..65535
def save_image(im: "np.ndarray") -> None: ...  # 0..65535 (H, W, 3) -> FITS float32 0..1
def run(context: dict) -> None: ...     # load -> validate -> describe -> stretch -> save
```

* `stretch_array` is pure (no context, no filesystem, no Siril): it can be unit-tested on
  synthetic arrays and reused later by a GUI preview widget ("someday I might use it directly
  in the gui"), which is why the dataclass + pure function split matters.
* `run(context)` is the only context-aware entry point; the recipe's inline script calls
  `astro_color_stretch.logger = logger` (the `crop.py` convention) and then `run(context)`.
* Ported algorithm helpers stay module-level and keep the upstream names (`split_channels`,
  `rgb_sky_zero`, `max_histogram`, `smooth_histogram`, `set_minimum`, `image_stretch`,
  `s_curve`, `color_correct`, `apply_hsv_adjust`, `apply_white_balance`, `detect_stars`,
  `preserve_core_shrink_halo`, `reduce_star_sizes`, `richardson_lucy_deconvolution`,
  `subtract_vignetting`, `subtract_gradient`, `fix_out_of_bounds`, `select_dark_region`,
  `align_channels`, `ca_correction`, `vignette_correction`, `gradient_correction`,
  `log_image_stats`, `_human_seconds`) so a future upstream diff is mechanical.
* Parameters are threaded explicitly rather than as module globals (the reference's
  user-variables-are-globals style). This is a port-level refactor, not a semantic one - and
  it is what makes the module import-safe and re-entrant.

### 5.2 FITS / numpy adaptation (the important part)

`starbash.sim_siril.connection.SirilInterface` is the FITS boundary, exactly as VeraLux:

| Step | Reality | Handling |
|---|---|---|
| `get_image_pixeldata()` | astropy `fits.getdata` -> **planar** `(3, H, W)` (Siril's colour-FITS layout) `uint16` for linear stacks, `float32` 0..1 for already-stretched inputs (e.g. `hms_*`), `(H, W)` for mono | transpose to `(H, W, 3)`, scale to 0..65535, `astype(np.float64)` |
| scaling | reference rules: `uint8 * 257`; `float32` with `max <= 1` -> `(x * 65535).round()`; otherwise `astype(float64)` | keep verbatim so all guide-referenced numbers (`4096`, `skylevelfactor`, `setmin*`) mean the same thing |
| mono input | reference errors out ("not a 3 color RGB image") | **out of scope for this port** (decided, §10 Q2): the stage targets OSC/palette colour stacks. A 2-D input raises a clear `ValueError` naming the file and saying ACS needs 3 channels; no silent channel replication. Making mono work (and/or offering a linear-stack variant) is a follow-up |
| `set_image_pixeldata(img)` | writes `PrimaryHDU(data=img, header=<input header>)` with astropy | output `float32`, `(3, H, W)`, range 0..1 (clip + `/65535`), i.e. exactly what VeraLux writes and what the shipped `merge_stars` recipe already `load`s |
| white/black point semantics | ACS works in 0..65535 DN internally | unchanged; only the file boundary is normalised |

### 5.3 Channel order (RGB, not BGR) - audit list

The reference reads with `cv2.imread` (BGR) and compensates with `RED, GREEN, BLUE = 2, 1, 0`.
Our data arrives RGB, so the port keeps an **RGB-internal** convention. Required edits
(complete list - these are the only order-sensitive sites):

1. `split_channels`: channel indices `0, 1, 2` (drops the reused `RED/GREEN/BLUE` constants).
2. `align_channels`: `cv2.merge([b_aligned, g, r_aligned])` -> `[r_aligned, g, b_aligned]`.
3. `apply_white_balance`: `cv2.merge((b, g, r))` -> `(r, g, b)` (the `temp`/`tint` maths on the
   named `r`/`b` arrays is unchanged and therefore now applies to the right channels).
4. `COLOR_BGR2GRAY` -> `COLOR_RGB2GRAY` (3 sites: dark-region scan, star detection, star-halo
   detection) - otherwise the R/B luma weights are swapped.
5. `COLOR_BGR2HSV(_FULL)` / `COLOR_HSV2BGR(_FULL)` -> `COLOR_RGB2HSV(_FULL)` /
   `COLOR_HSV2RGB(_FULL)` (HSV adjust, HSV colour-correction method, white balance).
6. `richardson_lucy_deconvolution`: luminance weights `0.2126/0.7152/0.0722` are applied to
   `im[..., 0/1/2]`. In the reference (BGR) the blue channel got the red weight - a latent
   bug. With RGB order the standard Rec.709 weights now land on the right channels: a
   deliberate, documented fix (opt-in path, default off).

Documenting this list matters: it is the only place where a reviewer must think about the
port's fidelity.

### 5.4 Behaviour dropped or added on purpose

Dropped: `cv2.imread`/`cv2.imwrite`, input extension/format checks, unique-filename logic,
matplotlib histograms (`plot_rgb_histograms`, `plot_sky_zero_histograms`), the two debug
TIFFs written by `select_dark_region`, `sys.exit()` in favour of exceptions.

Added: parameter validation that names every offender; bounds validation for the manual
dark-region window (the reference did not check `ulx`/`uly`, and its defaults
`1000/1000/500x700` are meaningless on a small image); `logger`-based progress output
(the reference's `print` progress is kept but routed through `logger`, so it lands in the
CLI/GUI run tree); timing summary at the end.

## 6. Dependencies

Add to `[tool.poetry.dependencies]` in `pyproject.toml` (all three resolve today through
transitive deps, but the port must not depend on `graxpert`'s dependency tree):

| Package | Why | Status today |
|---|---|---|
| `opencv-python-headless` | ECC channel alignment, morphology for star reduction, HSV conversions, histograms | present at 4.11.0.86 as a transitive dep |
| `scikit-image` | `skimage.restoration.richardson_lucy` | present at 0.26.0 |
| `scipy` | `scipy.ndimage` smoothing/box filters | present at 1.18.1 |

Deliberately **not** added: `matplotlib` (only used by the dropped histogram plots).
`opencv-python-headless` (not `opencv-python`) is the right variant because the engine never
opens a window - and `opencv-python` would collide with Qt/bundled GTK on some platforms.

Pin style: match the existing file (caret ranges such as `^4.11`/`^0.26`/`^1.18`) and let
`poetry lock` choose exact versions. The module is imported lazily (only from the recipe
script), so CLI start-up and `sb gui` start-up are unaffected; still verify the offscreen Qt
suite afterwards.

## 7. Phased implementation sequence

1. **Recipe skeleton + wiring test.** Write `starbash-recipes/post/astro-color-stretch.toml`
   (stage/inputs/outputs/parameters, with an inline `script` importing the module), add the
   `[[repo-ref]]` to `starbash-recipes/starbash.toml`, and add
   `tests/unit/test_tool.py::TestAstroColorStretchRecipe` mirroring `TestCropRecipe`
   (stage name, `tool.name`, `after`, `multiplex`, the `starmask` exclude,
   `auto.prefix == "acs_"`, not excluded by default, manifest membership). It stays red until
   the module exists, so land the module's `StretchParams` (defaults only) in the same step.
2. **Engine, part 1 - scaffolding, I/O, validation.** Module header (license/attribution),
   `StretchParams` (+ `from_context`, `validate`, `describe`), `load_image`/`save_image`
   via `SirilInterface`, `run(context)`, logging helpers; `stretch_array` starts as
   pass-through. Tests: scaling rules, planar->HWC transpose, 0..65535 -> float32 0..1
   round trip, validation messages, parameter-name/TOML parity.
3. **Engine, part 2 - core algorithm.** `split_channels`, `max_histogram`,
   `smooth_histogram`, `select_dark_region` (+ bounds validation), `rgb_sky_zero`,
   `set_minimum`, `image_stretch`, `s_curve`, `log_image_stats`. Tests on synthetic images:
   the black point really darkens the sky window; each stretch type is monotonic and stays
   in 0..65535; two-pass co-operates; `scurve` levels 0-4 all run.
4. **Engine, part 3 - colour and corrections.** `color_correct` (ratio + HSV),
   `apply_hsv_adjust`, `apply_white_balance`, `ca_correction`/`align_channels`,
   `vignette_correction`, `gradient_correction`, `fix_out_of_bounds`, `reduce_star_sizes`,
   `richardson_lucy_deconvolution`. Tests: the ratio method preserves channel ratios (a
   red-dominant pixel stays red-dominant), gray-world equalises channel means, `temp`/`tint`
   move the intended channels, every correction is a no-op when disabled, CA alignment
   improves a deliberately mis-registered synthetic channel.
5. **End-to-end stage test.** Run the stage through the processing machinery on a small
   generated FITS (or `test-data/`), asserting an `acs_*.fits` appears with the expected
   shape/dtype/range, that the input FITS header survives, and that a `starmask_*` input
   never gets an `acs_` output.
6. **Recipes-repo coordination.** The new `starbash-recipes/post/astro-color-stretch.toml` and
   its `starbash.toml` manifest entry are prepared in the submodule working tree; the **human
   developer commits and pushes them** (and bumps the submodule pointer in starbash) — see
   `.clinerules/collaboration.md`. Until that lands, dev runs use `force_local_recipes`/a
   `file://` repo.
7. **Polish.** A real-data sanity run (`sb process` on a target with the stage enabled);
   `README.md` credits; memory-bank `activeContext.md`/`progress.md` update pointing at this
   plan. **Status 2026-09-14:** the READMEs and the memory-bank entry are done; the
   `acs_*`-vs-`hms_*` real-data comparison was dropped by the user as unnecessary.

Gate for every code step: `just lint` (format + ruff + basedpyright), then
`poetry run pytest -q`.

## 8. Testing strategy

Follow the house rules: tests assert on **real resulting state**, not "a mock was called".

* `tests/unit/test_astro_color_stretch.py` (new, Qt-free, fast):
  * *params*: defaults match the upstream table; `validate()` rejects each out-of-range value
    (parametrised) and accepts the defaults; the `ValueError` text lists every offender;
    conditional checks only fire in the right mode.
  * *I/O adapter*: `uint8` -> `x257`; `uint16` unchanged; `float32` 0..1 -> `x65535` rounded;
    `(3, H, W)` -> `(H, W, 3)`; output `float32` `(3, H, W)` in 0..1;
    mono `(H, W)` -> `ValueError` naming the file (see §10 Q2 - mono is out of scope);
    header preserved (round-trip a header keyword).
  * *algorithm* (synthetic, seeded): sky window mean drops after `rgb_sky_zero`; each
    `stretch_type` is monotonic and stays in range; `scurve = 0` is a no-op while
    `scurve = 1` raises midtones; ratio colour correction keeps a red-dominant patch
    red-dominant and grey patches grey; `wb_mode = 1` equalises channel means;
    `hsv_adjust`/`ca_correct`/`vn_correct`/`lg_correct`/`star_reduction`/`rl_deconvolve`
    are exactly no-ops when off and *change* the image when on.
  * *parity*: the set of `StretchParams` field names == the set of
    `[[stages.parameters]]` names in `starbash-recipes/post/astro-color-stretch.toml`
    (guards against a parameter that the module reads but the recipe never declares, or a
    declared knob the engine ignores).
  * *regression*: a small seeded synthetic image with a fixed parameter set pinned to a
    checksum/mean tolerance, so a future "small refactor" cannot silently change the maths.
    Keep tolerances loose enough to survive OpenCV/skimage version bumps, and comment why.
* `tests/unit/test_tool.py::TestAstroColorStretchRecipe`: recipe wiring (as in phase 1) plus
  "the manifest lists it" and "the stage sorts after the palette stages it follows".
* Existing suites: `TestRecipeParameterReferences` already scans `starbash-recipes/**/*.toml`
  and will cover the new file automatically; `test_cli_headless.py` guards that the CLI still
  never imports Qt/OpenCV at start-up.
* Manual: one real run (`sb process` on a target with the stage enabled, or
  `force_local_recipes` dev path). The visual `acs_*`/`hms_*` A/B comparison originally
  planned here was **dropped by the user (2026-09-14)** as unnecessary.

## 9. Risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Memory / runtime on large frames | the pipeline works in `float64` `(H, W, 3)`; a 45 MP frame is ~1.1 GB **per copy** and the reference makes several | document it; avoid gratuitous copies where the maths allows (`np.copy` only where the reference needed it - `imagezf`); expose progress logging so a slow frame is visible. If it proves painful, a follow-up can downcast intermediate steps to `float32` (numerically invisible at 16-bit input) - explicitly out of scope for the first port |
| Channel-order mistakes | the reference is BGR; sloppy porting silently swaps R/B in a subset of corrections | the §5.3 audit list is complete and each item gets a test that fails on a swap (e.g. red-dominant patch) |
| Behaviour drift from upstream | users follow the upstream guide; if our numbers diverge, the guide is wrong about us | keep defaults/ranges/formulas verbatim, keep upstream function names, and document every deliberate deviation in the module docstring — currently seven: RGB channel order, RL luma weights, the HSV scaling fix, the dropped no-op `rgb_sky_zero`, mono raising, the skimage keyword, and `ca_correct` defaulting off (§12) |
| `exclude_by_default` decision (§10 Q1) | this stage will start running in existing targets' pipelines on the next run, and a target that excludes `veralux` but not ACS switches stretch engine | decided: **not** excluded by default; the consequence is documented in §4.1 and the change is one line if it proves noisy |
| GPL/attribution slip | the licence requires retention of copyright and conditions | header + README credits are phase-1/phase-7 checklist items, not afterthoughts |
| Big parameter surface | 40 knobs in the GUI tree | all are documented upstream, the description strings carry the guide wording; trimming can be a later, purely cosmetic decision |

## 10. Decisions (resolved 2026-09-14)

1. **`exclude_by_default` — NO.** ACS is enabled by default, like the rest of the recipe.
   The consequence (see §4.1) is accepted knowingly: existing targets pick the stage up on
   the next run, and a target that excludes `veralux` switches engine from VeraLux to ACS.
   Flipping it later is a one-line change.
2. **Mono input — out of scope.** No channel replication, no linear-stack variant in this
   port; the stage is for colour (OSC/palette) stacks. A 2-D input fails loudly with a
   `ValueError` that names the file. A mono/linear-stack variant is a follow-up.
3. **Stage name — `astro_color_stretch`** (matches the engine module and the upstream tool).
4. **Parameter renames — `k1`/`k2`/`log_k1`/`log_k2`** (snake_case house style); the
   description string names the guide's `K1`/`K2`/`logK1`/`logK2` symbol so a reader of the
   setup guide can map them one-to-one.
5. **RL luma weights — fixed.** Rec.709 weights now land on the R/G/B channels instead of the
   reference's B/G/R mix-up (§5.3 item 6). Opt-in path (default off), documented in the
   module docstring.
6. **FITS header provenance — dropped from this port.** The effective settings are logged via
   `StretchParams.describe()`, which is enough to reproduce a run; extra header cards can be
   added later without a format change. (The reference encoded parameters in the *filename*;
   we deliberately do not, so re-running with new settings replaces the same `acs_*` file -
   see §4.4.)
7. **`ca_correct` default — OFF** (decided 2026-09-14, after the first port landed). Upstream
   defaults it to `true`; the port defaults both the dataclass field and the recipe TOML
   parameter to `false` (deviation 7 in the module header). The stage occupies the VeraLux
   slot, i.e. its input is the *starless* frame StarNet produced (the stars come back later
   via `merge_stars`), so channel fringing — a star-centric defect — has nothing left to fix
   while the ECC solve costs an extra pass over two channels and can fail to converge. The
   parameter is fully honoured when set to `true` (a test asserts the misfit halves on a
   deliberately mis-registered channel and that an already-aligned frame is untouched), so a
   user chasing upstream parity can simply turn it on.

## 11. Follow-ups / documentation

* **Documentation — done (2026-09-14).** The root `README.md` credits David M. Jones
  (astro-color-stretch) and Roger N. Clark (rnc-color-stretch, which ACS adapts), and lists
  astro-color-stretch under *Supported tools* plus a stretching bullet in *Automatic
  stacking/preprocessing*; `src/starbash/recipes/README.md` replaced its FIXME with a real
  engine index (module → recipe table, "adding an engine" steps, credits, and the remaining
  "where should scripts live" note); the recipes-repo `README.md` gained a layout + credits
  section naming `post/astro-color-stretch.toml`.
* `doc/plans/` this file; reference it from `.clinerules/memory-bank/activeContext.md` when
  the work starts, and record the outcome in `progress.md`.
* If a future task wires ACS into the GUI image viewer, it should use `stretch_array` +
  `StretchParams` directly (no FITS I/O, no context) - that is the reason for the split in
  §5.1. A follow-up plan should cover proxy scaling for interactive use.

## 12. Implementation status (2026-09-14)

Phases 1-5 of §7 are done, and the engine is complete; phase 6 needs the human (see below).

| Artifact | State |
|---|---|
| `src/starbash/recipes/astro_color_stretch.py` | complete - 1453 lines: header/attribution, `StretchParams` (46 fields), validation, dark-region selection, sky zero, the three stretch families, S-curve, minimum floor, colour correction (ratio + HSV), HSV adjust, white balance, CA/vignette/gradient corrections, star reduction, RL deconvolution, `stretch_array`, `load_image`/`save_image`/`run` |
| `starbash-recipes/post/astro-color-stretch.toml` | complete - 46 parameters (names + defaults + descriptions), `after = "(starnet\|palette_broadband).*"`, `multiplex`, `starmask` exclude, `auto.prefix = "acs_"` |
| `starbash-recipes/starbash.toml` | `[[repo-ref]] dir = "post/astro-color-stretch.toml"` added |
| `tests/unit/test_astro_color_stretch.py` | 51 tests: TOML/dataclass parameter + default parity, recipe wiring, FITS boundary, validation, dark-region bounds, CA default + real ECC realignment (deviation 7), pipeline behaviour (incl. deviation 3 as a near-no-op round trip and seeded regression pins), four end-to-end `run()` cases against real FITS files, and one that runs the recipe's own script through the real RestrictedPython sandbox |

**Deliberate deviations from upstream — seven.** All are documented in the module docstring;
the channel-order ones are enumerated in §5.3. In short: (1) RGB, not BGR, internals;
(2) the RL Rec.709 luma weights land on the right channels; (3) `hsv_adjust`'s HSV scaling
fixed; (4) the s-curve loop's discarded `rgb_sky_zero` call dropped; (5) mono input raises;
(6) scikit-image's `num_iter=` keyword; (7) `ca_correct` defaults **off** (§10 Q7) because
this stage's input is the starless frame.

Two port-level notes worth knowing when reading the code:

* **OpenCV stub friction.** `opencv-python-headless`'s type stubs declare several entry points
  (`calcHist`, `meanStdDev`, `threshold`) for `UMat`, which basedpyright rejects for the
  ndarray form that OpenCV's own Python docs use. Those call sites carry a narrow
  `# pyright: ignore[reportArgumentType]` with a comment; everything else is type-clean.
  Numpy array conversions use `.astype(...)` rather than `np.float32(...)`/`np.float64(...)`
  because the latter are typed as *scalars* in current numpy stubs.
* **Verified versions** for the environment this was developed against: opencv 4.11,
  scikit-image 0.26 (`num_iter=`), scipy 1.18, numpy 2.x. `just lint` (format + ruff +
  basedpyright) is clean and the full suite is green (1113 passed).

**Remaining hand-offs.** (1) The human commits the submodule TOML + manifest + README and
bumps the pointer (phase 6). (2) Phase 7 is otherwise complete: the READMEs are updated, the
memory-bank entry is done (`activeContext.md` / `progress.md`), and the real-data `acs_*`
vs `hms_*` A/B comparison was dropped by the user on 2026-09-14 (§8). (3) The "where should
these Python engines live" question is no longer a bare FIXME: it is documented as an open
item in `src/starbash/recipes/README.md`.
