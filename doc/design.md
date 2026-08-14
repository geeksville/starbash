
## stage m1: delete temporary files

After a stage runs, delete any intermediate files it declared via the `temporaries`
key in its TOML. This keeps the shared `process_dir` clean between stages/runs and
reduces disk usage.

### Declaration syntax (already present in recipe TOML)

Each `[[stages]]` may declare a list of **glob patterns**:

```toml
temporaries = ["in*", "r_in*"]           # stack_osc.toml
temporaries = ["pp_{light_base}*"]        # light_vs_bias.toml (uses context vars)
temporaries = []                          # seqextract_haoiii.toml (explicit "none")
```

Semantics: each entry is a **glob pattern** matched against the top level of the
stage's working directory (`process_dir`). Both files and directories that match are
removed after the stage completes. For example `"in*"` removes the `in/` sequence
directory plus `in.seq`, and `"r_in*"` removes `r_in.seq`, `r_in_0001.fit`, etc.

Patterns are run through the normal context expansion (`expand_context_list`)
so `"pp_{light_base}*"` expands to e.g. `pp_light_s23*` before matching.

### Where it plugs in

- Stage → task creation: `Processing._create_task_dict()`
  ([src/starbash/processing.py](../src/starbash/processing.py)) already snapshots
  the stage and context into `task_dict["meta"]`.
- Post-run hook: `doit_post_process()` in
  ([src/starbash/doit.py](../src/starbash/doit.py)) already runs as the final action
  of every task. The cleanup will be added to its `closure()`, so it runs **after
  each stage** that declared temporaries.
- Working dir: the expanded `process_dir` in the task's snapshot context is the
  directory to clean. Matching is **top-level only** (non-recursive) within that dir.

### Proposed behavior (decisions locked in)

1. Read `temporaries = stage.get("temporaries", [])`. If absent or empty, do nothing.
2. Expand each entry against the task's snapshot context.
3. For each entry: `glob(process_dir/pattern)` and remove matches (`os.remove` for
   files, `shutil.rmtree` for directories).
4. Run cleanup **unconditionally** after the stage — regardless of success or
   failure. Log each removed path at debug level.
5. Guard against unsafe patterns: skip empty/whitespace entries and refuse any
   pattern that would escape `process_dir` (e.g. contains `/`, `..`, or is absolute).

### Docs / tests to update

- `.github/copilot-instructions.md` "Stages, tasks, and context" — document the
  `temporaries` key.
- Recipe examples: uncomment/enable `temporaries` in `light_vs_bias.toml`.
- Add a unit test that creates matching files/dirs in a temp `process_dir`, runs the
  cleanup, and asserts only the declared patterns are removed (and non-matching files
  are preserved).

### Open questions for review

All decisions are now locked in:

- **Timing** — after each stage that declared temporaries.
- **On failure** — always delete (do not retain on failure).
- **Match scope** — top level of `process_dir` only (non-recursive).
- **Interpretation** — plain glob patterns; recipe TOML entries use explicit
  wildcards (e.g. `"in*"`, `"r_in*"`), so no implicit `*` handling is needed.

## stage m2: rc-astro tool support

Add first-class support for running the [rc-astro](https://www.rc-astro.com/) CLI
(BlurXTerminator, and later NoiseXTerminator) from recipes, with live progress
driven by the CLI's JSON event stream.

**Scope (this stage): BlurXTerminator (`bxt`) only.** NoiseXTerminator (`nxt`) is
documented at the end for reference but is deferred to a later stage.

### Goals

1. New `RCAstroTool` class (subclass of `ExternalTool`) that runs the `rc-astro`
   CLI, always passing `--json`, and passes all other arguments via the command
   line (mirroring `GraxpertExternalTool`).
2. Parse the CLI's streaming JSON output line-by-line to drive a **live Rich
   progress bar** (percent complete + ETA) and to surface status/errors.
3. Implement `starbash-recipes/rc-astro/blur-exterminator.toml` using the new tool,
   with `--sharpen-stars` / `--sharpen-nonstellar` exposed as recipe parameters
   (defaults `0.5`).
4. By default, blur-exterminator runs **after background elimination**, analogous to
   `siril-scripts/processing/VeraLux_HyperMetric_Stretch.toml` (which uses
   `after = "background.*"`).

### Decisions (locked in)

- **Registered tool name:** `rc-astro` (used as `tool.name` in recipes).
- **Executable:** `rc-astro` (discovered via the existing `ExternalTool`
  `executable_path` PATH/extra-dirs search; user override via `Preferences`).
- **Always pass `--json`** so output is machine-parseable.
- **Progress depth:** full — add a streaming subprocess reader plus a live Rich
  progress bar fed by the JSON `progress` events.
- **Sharpen strengths** are recipe `[[parameters]]` with defaults `0.5`.

### Design

#### 1. Streaming execution helper (`src/starbash/tool/base.py`)

The current `tool_run()` uses a blocking `process.communicate()`, so it cannot
report incremental progress. Add a streaming variant (or extend `tool_run` with an
optional `on_line` callback) that:

- Launches the process with `stdout=subprocess.PIPE, text=True`.
- Iterates `process.stdout` line-by-line, invoking `on_line(line)` for each line
  as it arrives.
- Still writes stdout to `log_out`, applies the same timeout handling, and raises
  `ToolError` on a non-zero exit code (preserving existing error semantics).

This keeps existing tools untouched (they keep calling `tool_run`); only
`RCAstroTool` opts into the streaming path.

#### 2. `RCAstroTool` (`src/starbash/tool/rcastro.py`)

- Subclass `ExternalTool("rc-astro", ["rc-astro"], "https://www.rc-astro.com/")`.
- `set_defaults()`: generous timeout (e.g. 2h) — deconvolution on CPU is slow (see
  sample ETA ~180s+ for a small crop).
- `_run()`:
  - Accept `commands` as a **list** (like graxpert), expand with
    `expand_context_list`, and prepend `--json` if not already present.
  - Build `cmd = f"{self.executable_path} --json {expanded}"`.
  - Call the streaming runner with an `on_line` handler that:
    - JSON-decodes each line (ignore non-JSON lines defensively).
    - `event == "progress"` → update a Rich progress task to `done` percent, show
      ETA from the `eta` field.
    - `event == "status"` → update the progress/spinner description (e.g.
      "Initializing", "Saving", "Done").
    - `event == "info"` (e.g. `modelDownload`, `device`, `version`) → log at debug.
  - Integrate with the existing per-tool Rich `Live`/`Spinner` in `Tool.run()`:
    swap or augment the spinner with a `Progress` bar for this tool.

#### 3. Register the tool (`src/starbash/tool/__init__.py`)

Add `RCAstroTool()` to the `tools` list so it registers as `"rc-astro"`, and it will
be preflight-checked (warn-only if the CLI is missing) via `init_tools()`.

#### 4. Recipe: `starbash-recipes/rc-astro/blur-exterminator.toml`

Model on `starbash-recipes/graxpert/background.toml`:

```toml
[repo]
kind = "recipe"

[[parameters]]
name = "bxt_sharpen_stars"
default = 0.5
description = "BlurXTerminator stellar sharpening strength (0..1)"

[[parameters]]
name = "bxt_sharpen_nonstellar"
default = 0.5
description = "BlurXTerminator non-stellar sharpening strength (0..1)"

[[stages]]
name = "blur_exterminator"
description = "Sharpen/deconvolve with BlurXTerminator (rc-astro bxt)"
tool.name = "rc-astro"

script = [
    "bxt",
    "{input[0].full_paths[0]}",
    "--output", "{output.full_paths[0]}",
    "--sharpen-stars", "{parameters.bxt_sharpen_stars}",
    "--sharpen-nonstellar", "{parameters.bxt_sharpen_nonstellar}",
]

[[stages.inputs]]
kind = "job"
after = "background.*"   # run after background elimination
multiplex = true

[[stages.inputs.requires]]
kind = "min_count"
value = 1

[[stages.outputs]]
kind = "processed"
auto.prefix = "bx_"
```

Note: `--json` is injected by the tool, not by the recipe.

### Tests

- **Unit — JSON progress parsing:** feed the sample event lines (below) into the
  `on_line` handler and assert progress percent + status transitions are captured
  (no real subprocess). Assert non-JSON lines are ignored.
- **Unit — arg construction:** assert `RCAstroTool._run` builds the expected
  `rc-astro --json bxt <in> --output <out> --sharpen-stars .. --sharpen-nonstellar ..`
  command from an expanded script list, including auto-injected `--json`.
- **Unit — recipe wiring:** load `blur-exterminator.toml`, confirm parameters resolve
  and the stage sorts **after** a `background` stage (via `after = "background.*"`).
- Keep tests asserting real resulting state (parsed values / built command),
  not merely that a mock was called.

### Docs to update

- `.github/copilot-instructions.md` and `AGENTS.md` — add `rc-astro` to the list of
  supported tools and note the JSON streaming/progress behavior.

### sample invocation and json output
rc-astro --json bxt /mnt/pool/big/kevinh/telescope/processed/ngc6888/bk_stacked_Ha.fits --output foo.fits --sharpen-stars 0.5 --sharpen-nonstellar 0.5 

{"event":"info","topic":"version","cliVersion":"1.1.3","schemaVersion":4}
{"event":"status","phase":"initializing","message":"Initializing"}
{"event":"info","topic":"modelDownload","file":"BlurXTerminator.4.onnx","status":"downloading"}
{"event":"info","topic":"modelDownload","file":"BlurXTerminator.4.onnx","status":"downloaded"}
{"event":"info","topic":"device","device":"cpu","id":"cpu","name":"","provider":"CPU","runtime":"onnxruntime 1.23.2"}
{"event":"progress","done":0.6,"mpPerSec":0.1,"eta":237.1}
{"event":"progress","done":1.1,"mpPerSec":0.1,"eta":185.7}
{"event":"progress","done":1.7,"mpPerSec":0.1,"eta":183.7}
{"event":"progress","done":2.3,"mpPerSec":0.1,"eta":181.8}
{"event":"progress","done":99.4,"mpPerSec":0.2,"eta":0.7}
{"event":"progress","done":100.0,"mpPerSec":0.2,"eta":0.0}
{"event":"status","phase":"saving","message":"Saving","output":"/mnt/pool/big/kevinh/telescope/processed/ngc6888/foo.fits"}
{"event":"status","phase":"complete","message":"Done","output":"/mnt/pool/big/kevinh/telescope/processed/ngc6888/foo.fits"}

## stage m3: noise-exterminator

Building on stage m2 (which added `RCAstroTool` and the streaming JSON progress
plumbing), add `starbash-recipes/rc-astro/noise-exterminator.toml` — a recipe that
runs NoiseXTerminator (`nxt`) on the outputs of blur-exterminator by default.

**No tool code changes required.** `RCAstroTool` already runs any `rc-astro`
subcommand, auto-injects `--json`, and drives the live progress bar. m3 is purely a
new recipe + tests + docs.

### Goals

1. New recipe `starbash-recipes/rc-astro/noise-exterminator.toml` with a single
   `nxt` stage using `tool.name = "rc-astro"`.
2. By default, run **after blur-exterminator** (`after = "blur_exterminator"`),
   consuming its `bx_`-prefixed outputs.
3. Expose the full nxt option surface as recipe `[[parameters]]` (all with the
   CLI's documented defaults), so users can tune any strength.
4. Emit outputs with the `nx_` prefix.

### Decisions (locked in)

- **Subcommand:** `nxt` (positional after the injected `--json`).
- **Output:** explicit `--output {output.full_paths[0]}` (mirrors bxt; do not rely
  on the CLI's default `<input>-<product>.<ext>` naming).
- **Ordering:** `after = "blur_exterminator"` (exact stage name).
- **Output prefix:** `nx_`.
- **Parameters:** expose every nxt flag as a recipe parameter with its documented
  default (see mapping below).

### Parameter mapping

Each recipe parameter maps 1:1 to an nxt long flag; defaults match the CLI docs.

| Parameter name            | Flag                            | Default |
| ------------------------- | ------------------------------- | ------- |
| `nxt_denoise`             | `--denoise`                     | `0.90`  |
| `nxt_denoise_intensity`   | `--denoise-intensity`           | `0.90`  |
| `nxt_denoise_color`       | `--denoise-color`               | `0.90`  |
| `nxt_denoise_hf`          | `--denoise-high-freq`           | `0.90`  |
| `nxt_denoise_lf`          | `--denoise-low-freq`            | `0.90`  |
| `nxt_denoise_intensity_hf`| `--denoise-intensity-high-freq` | `0.90`  |
| `nxt_denoise_intensity_lf`| `--denoise-intensity-low-freq`  | `0.90`  |
| `nxt_denoise_color_hf`    | `--denoise-color-high-freq`     | `0.90`  |
| `nxt_denoise_color_lf`    | `--denoise-color-low-freq`      | `0.90`  |
| `nxt_frequency_scale`     | `--frequency-scale`             | `5.0`   |
| `nxt_iterations`          | `--iterations`                  | `2`     |

### Recipe: `starbash-recipes/rc-astro/noise-exterminator.toml`

Model on `blur-exterminator.toml`. Sketch:

```toml
[repo]
kind = "recipe"

[[parameters]]
name = "nxt_denoise"
default = 0.90
description = "NoiseXTerminator overall denoise strength (0..1)"

# ... one [[parameters]] block per row in the mapping table above ...

[[parameters]]
name = "nxt_iterations"
default = 2
description = "Number of denoising iterations (1..5)"

[[stages]]
name = "noise_exterminator"
description = "Denoise with NoiseXTerminator (rc-astro nxt)"
tool.name = "rc-astro"

# Note: --json is injected automatically by RCAstroTool, do not add it here.
script = [
    "nxt",
    "{input[0].full_paths[0]}",
    "--output", "{output.full_paths[0]}",
    "--denoise", "{parameters.nxt_denoise}",
    "--denoise-intensity", "{parameters.nxt_denoise_intensity}",
    "--denoise-color", "{parameters.nxt_denoise_color}",
    "--denoise-high-freq", "{parameters.nxt_denoise_hf}",
    "--denoise-low-freq", "{parameters.nxt_denoise_lf}",
    "--denoise-intensity-high-freq", "{parameters.nxt_denoise_intensity_hf}",
    "--denoise-intensity-low-freq", "{parameters.nxt_denoise_intensity_lf}",
    "--denoise-color-high-freq", "{parameters.nxt_denoise_color_hf}",
    "--denoise-color-low-freq", "{parameters.nxt_denoise_color_lf}",
    "--frequency-scale", "{parameters.nxt_frequency_scale}",
    "--iterations", "{parameters.nxt_iterations}",
]

[[stages.inputs]]
kind = "job"
after = "blur_exterminator"   # run on blur-exterminator outputs
multiplex = true

[[stages.inputs.requires]]
kind = "min_count"
value = 1

[[stages.outputs]]
kind = "processed"
auto.prefix = "nx_"
```

### Tests

- **Recipe wiring:** load `noise-exterminator.toml`; assert `tool.name == "rc-astro"`,
  the stage name is `noise_exterminator`, `after == "blur_exterminator"`, and the
  output prefix is `nx_`.
- **Parameter defaults:** assert every parameter in the mapping table is present with
  its documented default value.
- **Stage ordering:** run `sort_stages([noise_stage, blur_stage])` and assert
  `blur_exterminator` sorts before `noise_exterminator`. (Optionally chain
  background → blur → noise to confirm the full order.)
- Follow m2's testing style (assert real parsed state, not mock calls).

### Docs to update

- `.github/copilot-instructions.md` / `AGENTS.md` — mention that `rc-astro` now also
  provides NoiseXTerminator (`nxt`), running after blur-exterminator by default.

### example usage

rc-astro --json nxt [OPTIONS] [input_file...]

POSITIONALS:
  input_file (text)           One or more input image files (wildcards allowed). Each output
                              defaults to <input_file>-<product>.<ext>.

OPTIONS:
          --dn, --denoise (float in [0, 1], default 0.90) 
                              Denoise strength
          --di, --denoise-intensity (float in [0, 1], default 0.90) 
                              Intensity denoise strength
          --dc, --denoise-color (float in [0, 1], default 0.90) 
                              Chrominance denoise strength
          --dhf, --denoise-high-freq (float in [0, 1], default 0.90) 
                              High-frequency (small scale) denoise strength
          --dlf, --denoise-low-freq (float in [0, 1], default 0.90) 
                              Low-frequency (large scale) denoise strength
          --dihf, --denoise-intensity-high-freq (float in [0, 1], default 0.90) 
                              High-frequency (small scale) intensity denoise strength
          --dilf, --denoise-intensity-low-freq (float in [0, 1], default 0.90) 
                              Low-frequency (large scale) intensity denoise strength
          --dchf, --denoise-color-high-freq (float in [0, 1], default 0.90) 
                              High-frequency (small scale) color denoise strength
          --dclf, --denoise-color-low-freq (float in [0, 1], default 0.90) 
                              Low-frequency (large scale) color denoise strength
          --fs, --frequency-scale (float in [1, 100], default 5.0) 
                              Pixel scale of the low/high frequency transition band
          --it, --iterations (float in [1, 5], default 2) 
                              Number of denoising iterations to perform


## stage m4: starnet star removal

Replace `starbash-recipes/common/starnet.toml` with a valid siril-based recipe that
runs after `sho` and produces a starless image and a star mask.

### Key behaviour (from actual siril output)

Siril writes its outputs into **the same directory as the input file**, not `process_dir`:

```
Saving FITS: file /home/vscode/starless_bk_stacked.fit
Saving FITS: file /home/vscode/starmask_bk_stacked.fit
```

The naming pattern is `starless_<stem>.fit` and `starmask_<stem>.fit`. Because the
output directory is owned by the output repo (not an arbitrary temp dir), the recipe
script must load each siril-generated file and re-save it to the declared output paths.

### Goals

1. Replace the placeholder `starnet.toml` with a complete, working recipe.
2. Single parameter `starnet_params` (string, default `"-stretch"`) for full flexibility.
3. `multiplex = true`, `after = "sho"` — one task per upstream SHO file.
4. Two declared outputs: starless and starmask (see naming below).

### Recipe design

```toml
[repo]
kind = "recipe"

[[parameters]]
name = "starnet_params"
default = "-stretch"
description = "Options passed to siril starnet command (e.g. -stretch, -upscale)"

[[stages]]
name = "starnet"
description = "Star removal with StarNet via Siril"
tool.name = "siril"

# siril writes starless_<stem>.fit and starmask_<stem>.fit into the working dir
# (process_dir). We load each and re-save to the declared output paths.
script = '''
    load "{input[0].full_paths[0]}"
    starnet {parameters.starnet_params}
    load "starless_{input[0].full_paths[0].stem}.fit"
    save "{output.full_paths[0]}"
    load "starmask_{input[0].full_paths[0].stem}.fit"
    save "{output.full_paths[1]}"
    '''

[[stages.inputs]]
kind = "job"
after = "sho"
multiplex = true

[[stages.inputs.requires]]
kind = "min_count"
value = 1

# Multiple outputs are declared as ONE output block with a name list (see
# stack_single_duo.toml). name entries are context-expanded, so we derive them
# from the input stem: output.full_paths[0]=starless, [1]=starmask.
[[stages.outputs]]
kind = "processed"
name = [
    "starless_{input[0].full_paths[0].stem}.fits",
    "starmask_{input[0].full_paths[0].stem}.fits",
]
```

### Resolved design notes (verified against the code)

1. **Multiple outputs** — use a **single** `[[stages.outputs]]` block with a
   two-element `name` list (as `stack_single_duo.toml` does). `_resolve_output_files`
   in [src/starbash/processing.py](../src/starbash/processing.py) stores exactly one
   `output` FileInfo in context, so the two files must live in one block and are
   referenced as `output.full_paths[0]` / `output.full_paths[1]`. Two separate blocks
   would NOT both be visible to the script.
2. **`name` entries are context-expanded** (`expand_context_unsafe`), so
   `"starless_{input[0].full_paths[0].stem}.fits"` resolves to e.g.
   `starless_SHO.fits` — this keeps names unique per input, so `multiplex = true`
   is safe even if the upstream ever produces more than one file.
3. **`.fit` vs `.fits`** — siril `starnet` writes `.fit` files into the working dir
   (`process_dir`, set via `siril-cli -d <dir>`). We `load` those `.fit` files by
   basename (relative to cwd) and `save` to the declared `.fits` output paths, matching
   the existing `save "{output.full_paths[0]}"` pattern used by `sho.toml`.
4. **`Path.stem`** is usable in `{...}` because `full_paths[0]` is a `Path` and
   RestrictedPython allows attribute access (see `thumbnail.toml`'s
   `output.full_paths[0].with_suffix('')`).

### Tests

- Load the recipe TOML and assert `tool.name == "siril"`, `after == "sho"`,
  `multiplex == true`, and `parameters.starnet_params == "-stretch"`.
- Assert the script contains `starnet {parameters.starnet_params}`.
- Assert a single output block declares two `name` entries (starless + starmask).
- Assert stage ordering: `starnet` sorts after `sho` via `sort_stages`.

### Docs to update

- `.github/copilot-instructions.md` — add `starnet` to the siril recipe list.