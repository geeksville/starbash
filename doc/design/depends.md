# Plan: Rebuild stages when parameters / overrides change

## 1. Problem

`sb process auto` is driven by `doit` file-dependency tracking (`file_dep` → `targets`). If the user edits a per-target override in `private/processed/<target>/starbash.toml`:

```toml
[[stages]]
name = "light_no_darks"
  [[stages.overrides]]
  name = "options"
  value = "-somenew-opt"
```

nothing on disk changes from `doit`'s point of view (inputs and outputs have the same mtimes), so the stage is reported `up-to-date` and skipped. The same applies to recipe default changes and `tool.parameters` edits.

We need a **value-based** invalidation that survives across runs. `doit` already has a standard mechanism for this — no custom snapshot file needed.

## 2. Desired behavior (decided)

* **Scope:** changing a stage's effective config rebuilds that stage **and transitively all downstream consumers** (via the existing `file_dep` → `targets` chain — when the changed stage rewrites its outputs, downstream mtimes change and `doit` naturally rebuilds them).
* **What counts as config:** effective parameter values for the stage (`defaults` from the recipe + active `overrides` from the target's `starbash.toml`) **plus** `tool.parameters` (expanded). Optionally also hash the stage's `script`/`script-file` content so recipe script updates invalidate (recommended — cheap, catches `starbash-recipes` bumps).
* **Stage-list edits:** changes to `[[stages]]` `used`/`excluded` lists also invalidate. In practice this is already handled by task-graph culling (tasks appear/disappear), but any surviving task whose stage was toggled should also be considered config-changed.

## 3. Background: `doit` concepts

* Each task can declare `uptodate` — a list of callables/objects. If any returns `False`, the task is out-of-date regardless of file mtimes. Docs: https://pydoit.org/dependencies.html
* Standard helper: `from doit.tools import config_changed` — stores a JSON-serializable dict in `doit.db` (`~/.cache/starbash/doit.db`, `backend="dbm"` in `src/starbash/doit.py:load_doit_config`). On the next run it compares the current dict to the stored one; mismatch ⇒ rebuild. This is exactly the "snapshot in the doit db" asked about.
* Other helpers (`check_timestamp`, `result_dep`, `calc_dep`) are not needed here. `config_changed` is the idiomatic choice for parameter changes.
* File deps already give us transitive invalidation for free — no need for explicit `task_dep` edges if we ensure the changed stage actually rewrites its `targets`.

## 4. Proposed design

### 4.1 Fingerprint per task

In `src/starbash/processing.py:_create_task_dict` (where `task_dict` is built, ~line 790), compute a stable fingerprint dict for the stage:

```python
from doit.tools import config_changed
import hashlib, json

def stage_fingerprint(stage, context) -> dict:
    params_obj = context["parameters"]  # already effective values
    params = {k: v for k, v in vars(params_obj).items() if not k.startswith("_")}
    tool_params = context.get("_tool_params_expanded", {})  # expanded tool.parameters
    script = stage.get("script") or stage.source.read(stage.get("script-file", ""))  # if present
    return {
        "stage": stage.get("name"),
        "params": params,                       # effective defaults+overrides
        "tool": stage.get("tool", {}).get("name"),
        "tool_params": tool_params,
        "script_sha": hashlib.sha256(script.encode()).hexdigest()[:12] if script else None,
        # optional: include stage priority/exclude_by_default if you want list edits to count
    }
```

Then attach to the task:

```python
task_dict["uptodate"] = [config_changed(fingerprint)]
# keep existing file_dep/targets/clean/meta/actions
```

`config_changed` handles serialization and comparison; no manual DB code.

### 4.2 Where values come from

* `params` — reuse `ProcessedTarget.parameter_store.as_obj_for_stage(stage_name)` already placed in `context["parameters"]`. Convert to plain dict for JSON stability (sort keys).
* `tool_params` — capture the already-expanded `tool_parameters` from `_stage_to_action` (or compute before `task_dict` creation). Must be the expanded form so `{var}` resolution is included.
* `script_sha` — hash of inline `script` or resolved `script-file` content via `stage.source`. Cheap, makes recipe updates invalidate.
* Stage-list changes — if `used`/`excluded` toggles a stage, the task set changes via `preflight_tasks`/`remove_excluded_tasks`. Surviving tasks still get a new fingerprint if their stage's effective params changed; newly-enabled tasks are new tasks and run unconditionally.

### 4.3 Multiplexed stages

Stages with `inputs[].multiplex` create N tasks (`_create_task_dicts` loop). All N share the same stage fingerprint, so a param change rebuilds all N — correct. If per-file params ever exist, include `multiplex_index` in the fingerprint.

### 4.4 Transitive rebuild

No extra work: `calibrate_lights` → `pp_lights` → `seqextract` etc. are linked by `file_dep`/`targets` (output of one is input of next, see `src/starbash/processing.py:_resolve_all_input_files` / `_collect_input_files`). When the upstream task's `config_changed` forces a rebuild, its `targets` get new mtimes, downstream tasks become out-of-date via timestamp check.

### 4.5 What NOT to include

Exclude volatile context: `process_dir`, `session.id`, `date`, `input_files` absolute paths, `output` FileInfo. Those would cause spurious rebuilds every run.

## 5. Alternatives considered

| Alternative | Why not |
|---|---|
| Custom snapshot file next to `starbash.toml` | Duplicates `doit.db`; manual GC; `config_changed` already does this. |
| `calc_dep` that hashes files | Overkill; we want value-based, not file-content-based, for params. |
| `task_dep` edges for transitive | Unnecessary — file deps already propagate. Would add coupling. |
| Store hash in `meta` only | `meta` is not checked by `doit` for up-to-date; need `uptodate`. |

## 6. Implementation plan

**Phase 1 — minimal fix (1–2 files, ~30 lines):**
1. `src/starbash/processing.py`: add `stage_fingerprint()` helper and set `task_dict["uptodate"] = [config_changed(...)]` in `_create_task_dict`. Thread expanded `tool_parameters` into context so fingerprint can read it.
2. `src/starbash/doit.py`: no change needed (already uses `dbm` backend; `config_changed` works with it). Optionally add `from doit.tools import config_changed` import if fingerprint helper lives there.
3. Manual test: `sb process auto` → edit `private/processed/<target>/starbash.toml` override → `sb process auto` should show the stage as `run` not `up-to-date`; downstream stages also run.

**Phase 2 — hardening:**
4. Include `script_sha` and ensure `tool.parameters` expansion is stable (sort keys, `json.dumps(sort_keys=True)` inside `config_changed` already does).
5. Add unit test: build two task dicts with same/different fingerprints, assert `config_changed` returns correct `uptodate` boolean via `doit` API (or simple integration test that runs `doit` twice with changed fingerprint).
6. Verify `sb process doit --help` / `graph` still works (fingerprint doesn't affect task graph).

**Phase 3 — optional:**
7. If stage-list edits need explicit invalidation beyond task appearance/disappearance, include `used`/`excluded` state for the stage in the fingerprint (read from `ProcessedTarget.default_stages`).
8. Document in `doc/doit.md` and add a `just` recipe for `sb process doit dumpdb` inspection.

## 7. Testing

* **Unit:** `tests/test_processing.py` (new or existing) — mock `ProcessedTarget` + stage, call `_create_task_dict`, assert `uptodate` contains a `config_changed` entry and that changing `params` changes the stored config.
* **Integration:** temp `processing` dir + `doit.db` in isolated cache (`paths.set_test_directories`), run `Processing._run_all_tasks` twice with same fingerprint (second run skips), then with changed override (second run rebuilds). Assert `ProcessingResult` counts.
* **Manual:** `just select-small && sb process auto` → edit override → `sb process auto -v` should log `config_changed` reason.

## 8. Risks & open questions

* **Doit DB location:** `~/.cache/starbash/doit.db` is per-user, not per-target. Fingerprints are per-task (task name includes target + session id via `_get_unique_task_name`), so no collision. If user wipes cache (`just clean-cache`), next run rebuilds everything — acceptable.
* **JSON stability:** ensure fingerprint dict is JSON-serializable and key-order stable. `config_changed` uses `json.dumps(sort_keys=True)` internally, but we should still avoid non-serializable values (e.g., `Path` → `str`).
* **Performance:** negligible — one hash per task at graph-build time.
* **No remaining decisions** — scope and config definition were confirmed in Q&A. If we later want to exclude `script_sha`, it's a one-line removal.

## 9. References

* `src/starbash/processing.py:760` — `_create_task_dict` (where to add `uptodate`)
* `src/starbash/doit.py:load_doit_config` — `dep_file` + `backend="dbm"`
* `src/starbash/parameters.py:ParameterStore` — effective params logic
* `src/starbash/processed_target.py` — per-target `starbash.toml` + `parameter_store`
* https://pydoit.org/dependencies.html — `uptodate` / `config_changed`
* Original note preserved below for context.

---

### Original note

* currently when the user changes an override for a parameter "sb process auto" doesnt trigger a rebuild of the corresponding stage.
* change this (by creating a doit dependecy?) so that we notice the change and properly rebuild

ie if a user changes private/processed/ngc6888/starbash.toml
```
[[stages]]
name = "light_no_darks" # Calibrate OSC lights that have no dark frames available
[[stages.overrides]]
name = "options" # Light frame calibration options for OSC cameras
value = "-somenew-opt"
```

to be able to detect this we must keep a snapshot of the values used in the previous run.  can you keep it in the doit db somehow?  is this a standard concept in doit?
