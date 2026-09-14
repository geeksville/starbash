# Python recipe engines

Python modules that Starbash recipes import, via the sandboxed `python` tool - a
recipe stage's `script` does `from starbash.recipes import <module>` and calls
into it (see e.g. `starbash-recipes/post/astro-color-stretch.toml`). The recipe
*declarations* (stages, parameters, defaults, wiring) live in the
[starbash-recipes](https://github.com/geeksville/starbash-recipes) repo; this
package holds only the implementation code those declarations import.

`__init__.py` is intentionally empty - import a module by name, never rely on
side effects of importing the package.

| Module | Imported by (in `starbash-recipes`) | Purpose |
|---|---|---|
| `astro_color_stretch.py` | `post/astro-color-stretch.toml` | A port of David M. Jones' GPL **astro-color-stretch** 1.2 (an adaptation of Roger N. Clark's rnc-color-stretch) - per-channel zero-sky black point, root-power/asinh/log stretch, S-curve, ratio/HSV colour restore, optional chromatic-aberration/vignette/gradient correction, white balance, star reduction and Richardson-Lucy deconvolution. `StretchParams` + `stretch_array()` are pure (no file I/O), so a front end can reuse them for a preview. |
| `osc.py` | `osc/stack_single_duo.toml`, `osc/stack_dual_duo.toml` | One-shot-colour stacking helpers - builds the Siril `stack` invocation for the duo-band variants (drizzle, filter bands, ...). |
| `crop.py` | `common/crop.toml` | Reusable crop/rotation helpers, so several recipes trim with the same code and parameter semantics. |
| `report_registration.py` | `osc/report_registration.toml` | Parses Siril's `.seq`/conversion output and records per-frame registration metrics (FWHM, amplitude, roundness, background, stars) in the image database. |

## Adding an engine

1. Put the implementation here. House style: `logger = logging.getLogger(__name__)`
   (the runtime assigns the recipe's logger onto it), type hints and docstrings,
   `logger` instead of `print`, and exceptions instead of `sys.exit()`.
2. Declare the stage and its `[[stages.parameters]]` in the recipe TOML in
   `starbash-recipes`, and import the module from the stage's `script`.
3. Keep I/O on the documented paths - FITS reads/writes go through
   `starbash.sim_siril.SirilInterface`, tools through `starbash.tool` - so the
   same module works in the sandbox, in tests and (later) in a GUI preview.
4. Add unit tests under `tests/unit/`. `TestRecipeParameterDefaults` in
   `tests/unit/test_tool.py` scans every recipe TOML and fails if a script
   references a parameter the stage never declares; the ACS port additionally
   asserts full dataclass/TOML name+default parity in
   `tests/unit/test_astro_color_stretch.py::TestParameterParity`.

## Where these scripts should live (FIXME)

For the time being these engines live in the Starbash package rather than in the
`starbash-recipes` tree. That is a stopgap: recipe engines are *recipes*, and the
goal is for a recipe repo to ship its own Python (as `siril-scripts/` already
does for Siril scripts) without waiting for a Starbash release. Until the
packaging/sandbox story supports that, new engines go here - so keep them small,
tool-focused and free of assumptions about where the recipe repo is checked out.

## Credits

`astro_color_stretch.py` is a port of **astro-color-stretch** by
**[David M. Jones](https://dmjonesphotography.com/)** (GPL v3), itself an
adaptation of **Roger N. Clark**'s original **rnc-color-stretch**. The upstream
copyright, licence conditions and disclaimer are retained in the module header,
which also lists every deliberate deviation from the reference; the port's
design and build record is `doc/plans/astro-stretch.md`.
