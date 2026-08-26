# Plan: Per‑stage parameters & overrides refactor

## Goal

Move parameters and per‑target overrides so they are **nested under the stage
they belong to**, and collapse the `used`/`excluded` split into a single
`[[stages]]` list with an `excluded` boolean.

This touches three surfaces:

1. **Recipe TOML** (`starbash-recipes/`, `siril-scripts/`): `[[parameters]]` →
   `[[stages.parameters]]` (nested under each `[[stages]]`).
2. **Per‑target TOML** (`private/processed/<target>/starbash.toml`): flat
   `[stages].used/excluded` + top‑level `[[overrides]]` → a single `[[stages]]`
   array where each item has `name`, optional `excluded = true`, and nested
   `[[stages.overrides]]`.
3. **Docs**: `doc/toml/guide.md` updated to describe the new shape.

### Decisions (confirmed)

- **Override scope**: per‑stage. An override applies **only** when its owning
  stage runs. `context["parameters"]` is built per‑stage, not globally.
- **Param → stage mapping**: structural — a parameter belongs to the stage it is
  nested under in the recipe TOML (no separate `stage` field needed).
- **Sessions**: unify `[[sessions.stages]]` to the same new `[[stages]]` shape.
- **Migration**: no back‑compat. Old per‑target files are regenerated; any
  hand‑edited `excluded`/`overrides` in existing files are lost. (These dirs are
  disposable.)
- **Sequencing**: this is the plan; implement only after approval.

---

## 1. New TOML shapes

### 1a. Recipe file (authoring side)

Before:

```toml
[[parameters]]
name = "starnet_params"
default = "-stretch"
description = "Options passed to the Siril 'starnet' command"

[[stages]]
name = "starnet"
tool.name = "starnet"
script = '''...'''
```

After:

```toml
[[stages]]
name = "starnet"
tool.name = "starnet"
script = '''...'''

[[stages.parameters]]
name = "starnet_params"
default = "-stretch"
description = "Options passed to the Siril 'starnet' command"
```

Rules:

- Every `[[parameters]]` moves under the single stage in its file. Files that
  declare **one** stage (almost all) are mechanical. Files with **multiple**
  stages need each parameter placed under the stage that references it in its
  `script`.
- `tool.parameters` (the GraXpert/RC‑Astro CLI arg dict at
  `stage.tool.parameters`) is **unrelated** and unchanged — do not confuse it
  with the new `stage.parameters` array.

### 1b. Per‑target file (generated + user‑editable)

Before:

```toml
[stages]
used = ["stack_single_duo", "background", ...]
excluded = ["stack_osc", ...]

[[overrides]]
# name = "light_options"
# value = "-cfa -equalize_cfa"
```

After:

```toml
[[stages]]
name = "stack_single_duo"          # comment = recipe description
[[stages.overrides]]
name = "light_options"             # always written, uncommented
# value = "-cfa -equalize_cfa"     # value stays commented until user opts in

[[stages]]
name = "background"

[[stages]]
name = "stack_osc"
excluded = true                    # omitted ⇒ false
```

Rules:

- One `[[stages]]` entry per **known** stage (both run and excluded). Presence of
  the entry replaces the old `used` list; `excluded = true` replaces the old
  `excluded` list.
- `[[stages.overrides]]` scaffolds every parameter the stage declares, with
  `name` set and `value` commented. Uncommenting `value` activates the override
  for that stage only.
- Per‑session settings use the same shape nested under each `[[sessions]]`
  entry (`[[sessions.stages]]` array‑of‑tables).

---

## 2. Code changes

### 2.1 `src/starbash/parameters.py` — `ParameterStore`

- `add_from_repo()` currently reads top‑level `config.get("parameters")` /
  `config.get("overrides")`. Change the model so parameters/overrides are keyed
  by **(stage_name, param_name)** instead of a flat list.
- Add `add_from_stage(repo, stage)` that reads `stage["parameters"]` and (for
  per‑target repos) `stage["overrides"]`, tagging each `Parameter` with its
  `stage_name`.
- `as_obj` becomes **per‑stage**: `as_obj_for_stage(stage_name)` returns a
  `ParameterObject` resolving overrides→defaults for just that stage. (Keep a
  thin global `as_obj` only if still needed elsewhere; otherwise remove.)
- `write_overrides()` → rewrite to emit `[[stages.overrides]]` scaffolding under
  each `[[stages]]` entry (name uncommented, value commented), instead of a
  single top‑level `[[overrides]]` block.
- Add a `stage_name` field to the `Parameter` dataclass.

### 2.2 `src/starbash/stage_utils.py` + `stages.py`

- Replace `set_used` / `set_excluded` / `get_from_toml` (which operate on a
  `[stages]` table with `used`/`excluded` string lists) with helpers over the
  new `[[stages]]` AoT:
  - `find_stage_entry(container, name)` → the AoT item or None.
  - `is_excluded(container, name)` → bool (reads `excluded`).
  - `set_stage_entry(container, stage, excluded=False)` → upsert an item,
    preserving user edits/overrides.
  - `set_used_entries(container, stages)` / `set_excluded_entries(...)` rewritten
    to upsert into the AoT.
- `remove_excluded_tasks()` — swap `get_from_toml(session,"excluded")` for
  `is_excluded(...)` against the new AoT (both session‑level and
  `pt.default_stages`).
- `set_used_stages_from_tasks()` — record used stages as `[[stages]]` entries
  (not a `used` string list).

### 2.3 `src/starbash/processed_target.py`

- `_init_from_toml()` — read the new `[[stages]]` AoT into `self.default_stages`
  (shape: `{"stages": <AoT>}`), and copy the same AoT for matching sessions.
- `_set_default_stages()` — iterate `self.p.stages`; for each, ensure a
  `[[stages]]` entry exists; mark `excluded = true` for `exclude_by_default`
  stages not already present. Preserve existing entries/overrides.
- `_update_from_context()` — write back the `[[stages]]` AoT (per‑target and
  per‑session) instead of `stages.used` / `stages.excluded`.
- Parameter loading — call `add_from_stage()` for each stage of the target repo
  rather than a single `add_from_repo(self.repo)`.

### 2.4 `src/starbash/processing.py`

- `stages` property already flattens `[[stages]]`; parameters now live on each
  stage dict as `stage["parameters"]` — ensure they survive the AoT flatten
  (they will, since we keep `.unwrap()` off).
- `_create_task_dict()` (~line 775): replace the global
  `parameter_store.add_from_repo(stage.source)` +
  `context["parameters"] = ...as_obj` with **per‑stage** resolution:
  - `parameter_store.add_from_stage(stage.source, stage)`
  - `context["parameters"] = parameter_store.as_obj_for_stage(stage["name"])`
- Confirm `tool_dict.get("parameters")` (GraXpert/RC‑Astro CLI args) still reads
  from `stage.tool.parameters` and is untouched.

### 2.5 Templates

- `src/starbash/templates/target/processed.toml` and `.../master.toml`:
  remove `[stages]` (used/excluded) and top‑level `[[overrides]]`; the
  `[[stages]]` AoT + nested overrides are generated programmatically, so the
  template just needs the surrounding `[about]`, `[processing.citation]`,
  `[[sessions]]` scaffolding.

---

## 3. Recipe TOML migrations (authoring)

Move `[[parameters]]` → `[[stages.parameters]]` in each file below. Single‑stage
files are mechanical; **multi‑stage** files (verify none exist — current audit
shows one stage per file) need per‑stage placement.

Files with parameters (from audit):

- `starbash-recipes/common/starnet.toml` (1)
- `starbash-recipes/common/thumbnail.toml` (2)
- `starbash-recipes/graxpert/background.toml` (2)
- `starbash-recipes/osc/light_no_darks.toml` (1)
- `starbash-recipes/osc/light_vs_bias.toml` (1)
- `starbash-recipes/osc/light_vs_dark.toml` (1)
- `starbash-recipes/osc/stack_osc.toml` (4)
- `starbash-recipes/palette/hoo.toml` (1)
- `starbash-recipes/palette/sho.toml` (2)
- `starbash-recipes/post/merge_stars.toml` (1)
- `starbash-recipes/rc-astro/blur-exterminator.toml` (2)
- `starbash-recipes/rc-astro/noise-exterminator.toml` (11)
- `siril-scripts/processing/VeraLux_HyperMetric_Stretch.toml` (1)

> Note: `starbash-recipes` and `siril-scripts` are separate git repos in this
> workspace — each migration is a commit in its own repo.

---

## 4. Docs

Update `doc/toml/guide.md`:

- §3 Parameters — show `[[stages.parameters]]` nesting; drop top‑level
  `[[parameters]]`.
- §8 Per‑target control — replace `[stages].used/excluded` + `[[overrides]]`
  with the new `[[stages]]` + `excluded` + `[[stages.overrides]]` shape.
- §11/§12 examples & quick‑reference — reflect the nesting.

---

## 5. Tests

- `tests/unit/test_parameters.py` — rewrite for per‑stage add/resolve and
  `[[stages.overrides]]` output. Replace top‑level `[[overrides]]` fixtures.
- `tests/unit/test_processed_target.py` — update `set_used`/`set_excluded`/
  `get_from_toml` tests to the new AoT helpers; update `_set_default_stages`
  exclusion tests.
- `tests/unit/test_toml.py` — update the `_update_from_context` shape assertion
  (`doc["stages"] = {...}` → `[[stages]]` AoT).
- `tests/unit/test_processing.py` — task exclusion tests use bare stage dicts;
  verify still valid.
- Add tests: override applies to owning stage only; scaffolding writes `name`
  uncommented + `value` commented; regenerated file round‑trips.

---

## 6. Risks / watch‑outs

- **Name overloading**: `stage.tool.parameters` (CLI args) vs new
  `stage.parameters` (declarations). Keep them distinct in code and docs.
- **Multi‑stage recipe files**: if any file defines >1 stage, a parameter could
  be ambiguous — assign by which stage's `script` references it.
- **tomlkit comment handling**: existing override scaffolding already fights
  tomlkit quirks (comments on AoT don't render; see `write_overrides`). The new
  nested scaffolding must attach comments to concrete tables, not the AoT.
- **Regenerate‑only migration**: users lose prior manual `excluded`/`overrides`
  in `private/processed/*`. Acceptable per decision; call it out in the PR.
- **`starnet` recipe**: now uses `tool.name = "starnet"`; its single
  `starnet_params` parameter moves under that one stage.

---

## 7. Suggested implementation order

1. Land TOML‑shape helpers + `ParameterStore` per‑stage model (with tests).
2. Wire `processed_target` + `processing` to per‑stage resolution.
3. Update templates; regenerate a sample target to eyeball output.
4. Migrate recipe TOMLs (`starbash-recipes`, `siril-scripts`).
5. Update `doc/toml/guide.md`.
6. Full `poetry run pytest`; fix fallout.