
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

### noise-exterminator

this we will do later after bxt works.  but fyi

Supported formats:

nxt [OPTIONS] [input_file...]

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
