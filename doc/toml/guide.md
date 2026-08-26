# Writing Starbash Recipes

A **recipe** is a TOML file that tells Starbash how to process astrophotography
images: how to calibrate, stack, stretch, remove stars, denoise, and so on.
Recipes are grouped into **repos** and executed as an ordered **pipeline** of
**stages**, each of which runs an external **tool** (Siril, GraXpert, RC‑Astro,
or sandboxed Python).

This is a full authoring reference. It documents every section, its syntax, and
what it does. Working examples live in
[starbash-recipes/](../../starbash-recipes) and [doc/toml/example/](example).

---

## 1. Mental model

Processing runs as a chain of stages. Each stage:

1. **Selects inputs** — either raw frames for a session, master frames, or the
   **outputs of an earlier stage**.
2. **Runs a tool** with a script.
3. **Declares outputs** that later stages can consume.

Stages find each other by name: a later stage says `after = "<earlier-stage>"`
to consume that stage's outputs. This forms the dependency graph.

A typical narrowband chain looks like:

```
master_bias / master_flat  →  light_vs_dark  →  seqextract_haoiii
  →  stack_dual_duo  →  blur_exterminator  →  noise_exterminator
  →  palette_sho  →  starnet  →  veralux  →  merge_stars  →  thumbnail
```

---

## 2. Repo files (`starbash.toml`)

A **repo** is a directory (or a single TOML file) that Starbash loads. Every
repo begins with a `[repo]` table declaring its `kind`:

```toml
[repo]
kind = "recipe"
```

### Repo kinds

| `kind` | Meaning |
|--------|---------|
| `recipe` | A normal recipe repo containing `[[stages]]`. |
| `std-recipe` | The built‑in default recipe set. You rarely create these; if no `std-recipe` is present, Starbash fetches the official one from GitHub automatically. |
| `raw` | A directory of raw light/flat/dark/bias frames (see §9). |
| `master` | A directory of generated master frames. |
| `processed-target` | A per‑target output directory; holds a `[[stages]]` array (with `excluded` flags and nested `[[stages.overrides]]`) (see §8). |
| `preferences` | The user's config file (`~/.config/starbash/starbash.toml`). |

### Referencing other repos

A repo can pull in other recipe files with `[[repo-ref]]`. Use `dir` for a path
relative to this repo, or `url` for a remote/absolute location:

```toml
[[repo-ref]]
dir = "osc/stack_dual_duo.toml"          # relative to this repo

[[repo-ref]]
url = "https://raw.githubusercontent.com/.../VeraLux_HyperMetric_Stretch.toml"

[[repo-ref]]
url = "file:///abs/path/to/recipe.toml"  # absolute local path
```

Repos are merged with **precedence: later repos win** when resolving a single
key. Supported URL schemes are `file://`, `pkg://`, and `https://`.

### Recipe metadata (optional)

```toml
[recipe]
description = "Generate an SHO palette from HaOiii/SiiOiii data."
author.name = "Riccardo Paterniti"
author.email = "info@veralux.space"
```

---

## 3. Parameters

Parameters are named, documented knobs with defaults. They are **declared inside
the stage that uses them** as `[[stages.parameters]]`, exposed to that stage's
script as `{parameters.<name>}`, and can be overridden per target (see §8).

```toml
[[stages]]
name = "palette_sho"
tool.name = "siril"
script = '''...'''

[[stages.parameters]]
name = "ha_weight"
default = 0.4
description = "Ha contribution when synthesizing the green channel (0..1)"
```

- `name` — the identifier used in scripts (`{parameters.ha_weight}`).
- `default` — value used when not overridden. May be a number or string.
- `description` — shown to users; also emitted as commented‑out override
  scaffolding in a target's `starbash.toml`.

Parameters are **scoped to their owning stage**: an override only affects the
stage that declared the parameter, and two stages may declare the same parameter
name independently.

Any parameter your script references as `{parameters.<name>}` **must declare a
real `default`**. A commented‑out `# default = …` is invisible to the parser, so
the placeholder would expand to nothing at runtime. (If you truly want a value
only sometimes passed to a tool, gate it inside the script rather than relying on
a missing default.)

---

## 4. Stages

A stage is one unit of work, declared with the `[[stages]]` array‑of‑tables.

```toml
[[stages]]
name = "palette_sho"
description = "SHO palette: R=Ha, G=Sii-or-synthetic, B=OIII"
tool.name = "siril"
priority = 330            # optional; lower runs earlier
# disabled = true         # optional; skip this stage entirely
script = '''
    ... tool script ...
    '''
```

### Stage fields

| Field | Purpose |
|-------|---------|
| `name` | **Unique** stage name. Used by `after` (§5) and by target exclusion lists (§8). |
| `description` | Human‑readable summary. |
| `tool.name` | Which tool runs the script: `siril`, `python`, `graxpert`, or `rc-astro`. |
| `priority` | Optional integer to bias ordering; lower runs earlier. Ordering is otherwise driven by the `after` dependency graph. |
| `disabled` | Optional `true` to remove the stage from consideration. |
| `script` | Inline script (see §6). |
| `script-file` | Path to a script file, resolved relative to the repo. Use instead of `script`. |
| `temporaries` | Glob patterns of intermediate files to delete after the stage (§7). |
| `[stages.context]` | Extra variables merged into the runtime context (§6). |
| `[[stages.inputs]]` | Input selection (§5). |
| `[[stages.outputs]]` | Output declaration (§5). |

---

## 5. Inputs and outputs

### 5.1 Inputs (`[[stages.inputs]]`)

Each input block has a `kind` that decides where candidate files come from. A
stage may have **multiple** input blocks; each becomes a named entry in
`context["input"]`.

| `kind` | Where it gets files |
|--------|---------------------|
| `session` | Raw frames for the current session. Add `type = "light" \| "bias" \| "flat" \| "dark"`. |
| `master` | A generated master frame. Add `type = "bias" \| "dark" \| "flat"`. |
| `job` | The **outputs of a prior stage**. Add `after = "<stage>"`. |
| `session-extra` | Continue in the same working dir as a prior session stage (shares its context/tempdir). Add `after = "<stage>"`. |

Common keys:

- `after` — name (regex‑matched) of the upstream stage to follow, e.g.
  `after = "seqextract_haoiii"` or `after = "palette.*"`.
- `name` — optional label; the input becomes `context["input"]["<name>"]`. If
  omitted, inputs are numbered (`input[0]`, `input[1]`, …).
- `multiplex = true` — create **one task per upstream file** instead of a single
  task consuming all of them (used for per‑file stretch, denoise, thumbnails).

```toml
[[stages.inputs]]
kind = "job"
after = "noise_exterminator"

[[stages.inputs.requires]]
kind = "min_count"
value = 2
```

Two input blocks with different `requires` filters populate two named inputs.
For example the dual‑duo stacker builds `input["ha"]` and `input["sii"]`:

```toml
[[stages.inputs]]
kind = "job"
name = "ha"
after = "seqextract_haoiii"
[[stages.inputs.requires]]
kind = "metadata"
name = "filter"
value = ["HaOiii"]

[[stages.inputs]]
kind = "job"
name = "sii"
after = "seqextract_haoiii"
[[stages.inputs.requires]]
kind = "metadata"
name = "filter"
value = ["SiiOiii"]
```

### 5.2 Requires filters (`[[stages.inputs.requires]]`)

Filters narrow the candidate files for an input. They are evaluated **in order**;
put `min_count` last so it tests what remains. Implementation:
[src/starbash/filtering.py](../../src/starbash/filtering.py).

| `kind` | Effect |
|--------|--------|
| `metadata` | Keep files whose FITS header `name` matches `value`. `value` may be a **list** (matches if *any* value matches — logical OR). Use multiple `requires` blocks for AND. Values are normalized via the alias table. |
| `camera` | `value = "color"` keeps only sessions with a `BAYERPAT` header (OSC/color cameras). |
| `unprocessed` | Keep only files from non‑`processed`/non‑`master` repos (used by master generation so it never re‑consumes its own output). |
| `filename` | Keep files whose **basename** matches the regex `value`. `mode = "include"` (default) keeps matches; `mode = "exclude"` keeps non‑matches. |
| `min_count` | Require at least `value` files, else the stage is rejected/skipped. `accept_single = true` reuses a lone file instead of stacking. |

Examples:

```toml
# Only stretch starless files (skip the star mask)
[[stages.inputs.requires]]
kind = "filename"
value = "starmask"
mode = "exclude"

# Need at least both an Ha and an OIII channel
[[stages.inputs.requires]]
kind = "min_count"
value = 2
```

### 5.3 Outputs (`[[stages.outputs]]`)

Outputs declare what the stage produces and where it lands.

| `kind` | Destination |
|--------|-------------|
| `master` | The master repo (master darks/flats/biases). |
| `processed` | The per‑target processed directory (final products). |
| `job` | A shared job directory keyed by target, for intermediate results consumed by later stages. |

Naming an output — choose one approach:

- **Explicit `name`** — a string or list of strings, each context‑expanded:

  ```toml
  [[stages.outputs]]
  kind = "processed"
  name = ["SHO.fits"]

  [[stages.outputs]]
  kind = "processed"
  name = [
      "starless_{input[0].full_paths[0].stem}.fits",
      "starmask_{input[0].full_paths[0].stem}.fits",
  ]
  ```

- **Auto‑derived** from the input filename via `auto.prefix` / `auto.suffix`:

  ```toml
  [[stages.outputs]]
  kind = "processed"
  auto.prefix = "hms_"      # bx_input.fits -> hms_bx_input.fits

  [[stages.outputs]]
  kind = "processed"
  auto.suffix = ".jpg"      # change extension for a thumbnail
  ```

A single output block may declare **multiple** files by giving `name` a list
(e.g. StarNet emits `starless_*` and `starmask_*`). The script then references
them as `output.full_paths[0]` and `output.full_paths[1]`.

---

## 6. Scripts and context expansion

The `script` (or `script-file`) is the body the tool runs. Before running,
Starbash expands `{...}` placeholders against the runtime **context** using
Python's `str.format_map`.

### Script forms by tool

- **Siril** — a multi‑line string of Siril commands, sent via stdin:

  ```toml
  tool.name = "siril"
  script = '''
      load "{input[0].full_paths[0]}"
      starnet {parameters.params}
      save "{output.full_paths[0]}"
      '''
  ```

- **Python** — inline string (RestrictedPython sandbox) or a `.py`
  `script-file`. Globals available: `context`, `logger`, `parameters`.

  ```toml
  tool.name = "python"
  script = '''
      from starbash.recipes import osc
      osc.logger = logger
      osc.context = context
      osc.osc_process(has_ha_oiii=True, has_sii_oiii=True)
      '''
  ```

- **GraXpert / RC‑Astro** — a **list** of CLI arguments (each element is
  context‑expanded). For GraXpert, tool params can be passed via
  `tool.parameters`; for RC‑Astro, `--json` is injected automatically — do not
  add it yourself.

  ```toml
  tool.name = "rc-astro"
  script = [
      "bxt",
      "{input[0].full_paths[0]}",
      "--output", "{output.full_paths[0]}",
      "--sharpen-stars", "{parameters.sharpen_stars}",
  ]
  ```

  ```toml
  tool.name = "graxpert"
  tool.parameters = { ai_version = "{parameters.ai_version}", smoothing_option = "{parameters.smoothing_option}" }
  script = ["-cmd", "background-extraction", "-output", "{output.full_paths[0]}", "{input[0].full_paths[0]}"]
  ```

### Context variables

Placeholders resolve against these (non‑exhaustive) context values:

| Placeholder | Meaning |
|-------------|---------|
| `{parameters.<name>}` | A declared parameter's effective value. |
| `{input[<n>]...}` or `{input["<name>"]...}` | An input's `FileInfo` (see below). |
| `{output...}` | The output `FileInfo` for this stage. |
| `{process_dir}` | The stage's working directory (provided automatically). |
| `{target}` | Normalized target name. |
| `{instrument}`, `{camera_id}` | Session hardware identifiers. |
| `{imagetyp}` | Frame type (light/flat/dark/bias). |
| `{session_config}` | Session configuration key. |
| `{date}`, `{datetime}` | Session date / timestamp. |
| `{session["id"]}` | Numeric session id (usable in names, e.g. `light_s23`). |
| Anything in `[stages.context]` | Your own shorthand variables. |

**`FileInfo` attributes** (from
[src/starbash/doit.py](../../src/starbash/doit.py)):

- `full_paths` — list of absolute `Path`s to the individual files.
- `base` — the directory/base name component.
- `full` — the single full path (when there is exactly one).
- `relative`, `repo`, `image_rows` — provenance details.

Because expansion runs real Python inside `{...}`, you can use expressions:

```toml
# pick the file whose name contains "_Ha"
load {[str(p) for p in input[0].full_paths if "_Ha" in str(p)][0]}

# derive a sibling filename
load "{str(input[0].full_paths[0].parent / (input[0].full_paths[0].stem.replace('hms_starless_', 'starmask_') + '.fits'))}"

# strip the extension
savejpg "{output.full_paths[0].with_suffix('')}" {parameters.quality}
```

### Custom context shorthand

Define readable variables with `[stages.context]`:

```toml
[stages.context]
light_base = """{input["light"].base}"""
```

Expansion is **iterative** (nested placeholders resolve over multiple passes).
Any placeholder still unresolved at the end raises `KeyError` — always define
every variable you reference, or provide a default.

---

## 7. Temporaries (cleanup)

List glob patterns of intermediate files/dirs to delete from `process_dir`
after the stage runs (on both success and failure):

```toml
temporaries = ["pp_{light_base}*"]
```

- Patterns are context‑expanded.
- Matched at the **top level** of `process_dir` only (non‑recursive).
- Patterns containing `/`, `..`, or absolute paths are skipped for safety.

Implemented by `cleanup_temporaries()` in
[src/starbash/doit.py](../../src/starbash/doit.py).

---

## 8. Per‑target control (`processed-target` repos)

Each processed target has its own `starbash.toml` (kind `processed-target`),
auto‑generated on first run and preserved thereafter. It records which stages
ran and lets the user opt in/out and override parameters.

```toml
[repo]
kind = "processed-target"

[[stages]]
name = "stack_osc"
[[stages.overrides]]
name = "options"           # always written; description as a comment
# value = "-cfa -equalize_cfa"   # stays commented until you opt in

[[stages]]
name = "background"

[[stages]]
name = "denoise"
excluded = true                  # omit the flag (or the whole entry) to run it
```

- Each `[[stages]]` entry names a stage. Its presence means the stage runs; add
  `excluded = true` to skip it. This replaces the old `used`/`excluded` string
  lists. Exclusions are applied by `remove_excluded_tasks()` in
  [src/starbash/stages.py](../../src/starbash/stages.py), which checks each
  task's `stage["name"]` against these entries.
- `[[stages.overrides]]` overrides a parameter **for that stage only**. Starbash
  scaffolds one entry per declared parameter with `name` set and `value`
  commented; uncomment `value` to activate the override.
- Per‑session settings use the same shape nested under each `[[sessions]]` entry.

---

## 9. Raw and master repos

Raw and master repos describe *where image files live*, not how to process them.

Raw repo — declare one or more search patterns with placeholders:

```toml
[repo]
kind = "raw"

[[raw]]
name = "NINA layout"
relative.default = "{target}/{sessionid}/{frametype}/*_{session_config}_*.fit*"

[[raw]]
type = "master-raw"
relative.default = "masters-raw/{frametype}/*_{session_config}_*.fit*"
```

Master repo — a single `relative` pattern for generated masters:

```toml
[repo]
kind = "master"
relative = "{instrument}/{date}/{imagetyp}/{session_config}.fits"
```

---

## 10. TOML imports (reuse and inheritance)

To avoid duplicating stage templates, a table can import another node with an
`[<node>.import]` block, resolved when the repo loads.

```toml
[my_stage.import]
node = "source.node.path"    # required: dotted path to the node to import
file = "path/to/file.toml"   # optional: source file (default: current file)
repo = "url_or_path"         # optional: source repo (default: current repo)
```

Behavior:

- The `import` table is replaced by a **deep copy** of the referenced node.
- Inside an array‑of‑tables, the import **merges** into the existing item,
  preserving that item's other keys.
- Imports may be nested (an imported node may itself import).
- You cannot import at the root level, and files that use imports cannot be
  reliably rewritten afterward.

See [doc/toml/example/imports/](example/imports) for patterns; tests live in
`tests/unit/test_repo_imports.py`.

---

## 11. A complete annotated example

A minimal Siril stacking recipe that consumes a session's light frames plus
master dark and flat, and writes a stacked result to the shared job directory:

```toml
[repo]
kind = "recipe"

[[stages]]
name = "light_vs_dark"
description = "Calibrate OSC lights against master dark + flat"
tool.name = "siril"
temporaries = ["pp_{light_base}*"]

script = '''
    link {light_base} -out={process_dir}
    cd {process_dir}
    calibrate {light_base} -dark={input["dark"].full} -flat={input["flat"].full} {parameters.options}
    seqsubsky pp_{light_base} 1
    '''

[stages.context]
light_base = """{input["light"].base}"""

[[stages.parameters]]
name = "options"
default = "-cfa -equalize_cfa"
description = "Light frame calibration options for OSC cameras"

[[stages.inputs]]
kind = "session"
type = "light"
[[stages.inputs.requires]]
kind = "min_count"
value = 2

[[stages.inputs]]
kind = "master"
type = "dark"

[[stages.inputs]]
kind = "master"
type = "flat"

[[stages.outputs]]
kind = "job"
name = ["bkg_pp_{light_base}_.seq"]
```

---

## 12. Quick reference

- **Repo**: `[repo]` `kind = ...`; pull in others with `[[repo-ref]]` (`dir`/`url`).
- **Params**: `[[stages.parameters]]` `name`/`default`/`description` → `{parameters.name}`.
- **Stage**: `[[stages]]` `name`, `tool.name`, `script`/`script-file`, optional
  `priority`, `disabled`, `temporaries`, `[stages.context]`.
- **Inputs**: `[[stages.inputs]]` `kind` = `session`/`master`/`job`/`session-extra`;
  `after`, `name`, `multiplex`; filter with `[[stages.inputs.requires]]`.
- **Outputs**: `[[stages.outputs]]` `kind` = `master`/`processed`/`job`; explicit
  `name` (string or list) or `auto.prefix`/`auto.suffix`.
- **Scripts**: Siril/Python use multi‑line strings; GraXpert/RC‑Astro use arg
  lists. `{...}` runs Python against the context; unresolved placeholders raise
  `KeyError`.

### Common gotchas

- Match `after` to a real stage `name` (regex allowed) or the stage never runs.
- Put `min_count` **last** in a `requires` chain.
- `metadata` `value` list means OR; use multiple `requires` blocks for AND.
- Every `{placeholder}` must resolve — define it or give it a default.
- `temporaries` are non‑recursive and reject unsafe paths (`/`, `..`, absolute).
- Don't add `--json` to RC‑Astro scripts; it is injected automatically.