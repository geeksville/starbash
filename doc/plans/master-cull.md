# Cull unneeded master runs from the displayed pipeline

## Goal / summary

When the automated pipeline runs (GUI **Run auto pipeline**, CLI
`sb process auto`), it works in two phases:

1. **Phase 1** regenerates master calibration frames (`run_master_stages()`),
   publishing one `EVENT_RUN_FINISHED` per *master run* (`is_master = True`,
   labelled e.g. `Master flat_Ha · 2024-01-01 · canon`).
2. **Phase 2** processes each selected target (`_create_tasks(sessions, [t])` →
   `_run_all_tasks(...)`).

The problem: phase 1 shows **every** master run it generated, but a target only
ever *consumes* a handful of them (the master a target selects is the single
best-scoring candidate per type, see `Processing._resolve_input_master`). The
master list is therefore noisy.

**Wanted:** once phase 2's target task graphs are known, remove the displayed
master nodes whose outputs no target (or no *needed* master) actually depends
on.

## Where the masters are displayed

The core is the source of truth; both front-ends are pure consumers of events.

- `processing.py:_finish_runs()` publishes `EVENT_RUN_FINISHED` with
  `{"target": <label>, "run": <RunTree.to_plain()>}`. A `run` snapshot carries
  `is_master`, `target` (label) and per-stage/task `outputs` (`FileRef` =
  `{label, url}`).
- CLI `commands/process.py:ProcessingView` keeps `self._runs[label]` +
  `self._order`, and `_render()` draws every run.
- GUI `ui/qt/pages/processing.py:ProcessingPage` keeps
  `self._targets[label] -> QTreeWidgetItem` and rebuilds each root in
  `_render_run()`.

So a cull only needs a **new core event** naming the runs to drop, plus a small
handler in each front-end.

## How to know which masters a target needs

There is no static target→master map. The exact dependency is produced when a
target's doit tasks are built:

- `Processing._resolve_input_master()` picks `scored_masters[0]` (one per master
  type) and puts its path in the task's `file_dep` (via
  `_collect_input_files`/`_resolve_all_input_files`).
- A master run's produced files are its task `targets`, reachable from the
  results (`result.task.targets`) that `run_master_stages()` returns.
- `ProcessedTarget.run_label()` gives the display label used by the front-ends.

So: **needed masters = closure of `file_dep` reachable from the phase-2 target
tasks**, matched against each master run's produced outputs.

### The crux: getting the deps without breaking processing-dir cleanup

`_create_tasks()` creates the target's processing dir, and `_run_all_tasks()`
calls `cleanup_old_contexts()`, which prunes to `max_contexts` (default 2).
Naively pre-building *all* targets before phase 2 therefore deletes the
processing dirs of targets that have not run yet (once there are >2 targets).

> **Resolved (build/plan must not prune).** `ProcessedTarget.close()` used to
> call `cleanup_old_contexts()` too; it no longer does. Pruning now happens only
> at the *run* boundary — `Processing._run_all_tasks()` after `_run_jobs()` — so
> a planning/building pass that constructs every target's `ProcessedTarget` has
> no pruning side effect at all, and the >2-targets deletion above can no longer
> happen at build time. `close()` still removes a *temporary* (master)
> processing dir (`is_temp`), which is unrelated to `max_contexts`. This was the
> single change that made pre-building all targets safe, and it is the
> groundwork both approaches below rely on.

Candidate approaches:

- **A. Pre-build all target tasks and run them from the pre-built list**, adding
  a cleanup opt-out for the phase-2 loop and deleting each target's dir right
  after it runs. Most accurate and no double build. With the `close()` fix above,
  the remaining cost is that `_run_all_tasks()` still prunes after *each* target,
  so the phase-2 loop needs either a cleanup opt-out or per-target
  delete-immediately-after-run. This is now the recommended approach: the one
  invasive bit (moving cleanup out of `close()`) is already done, and the phase-2
  loop already owns its own call site, so making it explicit is small.
- **B. Throwaway "discovery" pass.** Build all target tasks (and master tasks)
  into a temporary list to compute the needed-master set, discard them, then run
  phase 2 exactly as today (rebuilding per target). No further cleanup change
  beyond the `close()` fix, at the cost of building tasks twice. Keep as the
  fallback if reusing prebuilt tasks turns out awkward.
- **C. Derive deps from each target's previous `run-log.toml`.** Cheap, but
  stale and can't cull on a first run — rejected as the primary mechanism.
- **D. One big doit run over master + target tasks** (as `build_all_tasks()`
  does) and let doit prune. Changes progress/cleanup/parallelism semantics
  substantially; out of scope for a first pass.

**Note: planning runs no tools, so reusing prebuilt tasks is safe.** The
"ToolAction passes the build-time `cwd`" concern does not apply to the planning
phase: planning only *builds* the doit tree, it never calls
`ToolAction.execute()`, so no tool ever sees a stale `cwd`. The only way the
build-time `cwd` can go stale is if something prunes (deletes) a processing dir
*between* building and running — and with cleanup now confined to
`_run_all_tasks()`, a pure planning pass cannot trigger that. Under approach A
the phase-2 loop must therefore simply not interleave a prune that would delete a
not-yet-run target's dir (handled by the cleanup opt-out / delete-after-run
above).

**Recommendation:** implement **A** (now low-risk given the `close()` fix), and
fall back to **B** only if reuse of prebuilt tasks proves awkward.

**Technology choices:** none — this reuses the existing dependency-free event
bus (`starbash.events`) and the plain-data run snapshots (`run_state`). No new
library or optional dependency is introduced, and the CLI must keep not
importing Qt (see `tests/unit/test_cli_headless.py`).

## Design

### The mechanism: a "preflight" (plan) phase

Rather than an unnamed throwaway "discovery pass", formalise it as an explicit
**preflight** phase at the head of the auto pipeline. This is approach A with a
clear seam:

1. **Preflight** — build the doit tree for every target without running
   anything:
   - `self._create_tasks(sessions, [t])` for each target, accumulating a
     `list[TaskDict]` per target.  (Masters must be *run* first — phase 1 — since
     the targets resolve which masters to consume from the indexed results.)
   - Create each target's output / `processed` directory, exactly as
     `_job_to_tasks` / `ProcessedTarget` already do at build time.  (Writing its
     `.starbash` files early was considered but is *not* a requirement and is not
     a separate step — whatever the build already does is fine.)
   - Because `ProcessedTarget.close()` no longer prunes (see *the crux* above),
     constructing every target here has no destructive side effect.
   - No `ToolAction.execute()` runs, so no build-time `cwd` is ever used.
2. **Publish `EVENT_PREFLIGHT_FINISHED`** with what the UI needs — at minimum the
   master run labels to drop (the cull), and any other planning output the UI
   wants to show before work starts. (This event can subsume/replace the
   narrower `EVENT_RUNS_CULLED` below; carrying cull info in it is fine.)
3. **Run** — execute the prebuilt tasks with `_run_all_tasks(..., prune=False)`
   so no prune deletes a not-yet-run target's directory, and delete each
   target's processing dir immediately after its run
   (`ProcessedTarget.remove_processing_dir()`); then one
   `cleanup_old_contexts()` at the very end.

This keeps the unit of work granular (per target) while giving the UI a clean
"plan is ready" signal, and — because the preflight phase creates the dirs but
does not populate them — it is the natural place to bound the `.cache`
processing tree.

### Core (`src/starbash/processing.py`, `src/starbash/events.py`)

1. New event `EVENT_PREFLIGHT_FINISHED = "preflight.finished"` (+ add to the
   `__all__` list in `events.py`).  Its payload is `{"drop": [<run label>, ...]}`.
   (The narrower `EVENT_RUNS_CULLED` was considered but not added — the preflight
   event carries the cull, and one event is easier for front-ends to handle.)
2. New pure helper (module-level, easy to unit-test), e.g.:

   ```python
   def masters_needed_by(
       target_tasks: list[TaskDict],
       master_tasks: list[TaskDict],
   ) -> set[str]:
       """File paths of master outputs reachable from the target task graphs."""
   ```

   - Seed from every `file_dep` of `target_tasks`.
   - Then repeatedly add `file_dep` of any task whose `targets` intersect the
     needed set (transitive master→master deps, e.g. a needed flat depends on a
     bias/dark master). Normalise paths (`os.path.realpath`).
3. `run_all_stages()`:
   - Phase 1 runs masters as today and keeps their results
     (`master_results`).
   - **Preflight** (before phase 2): build (`_create_tasks(sessions, [t])`)
     every target, accumulating `dict[target, list[TaskDict]]`.  Then call
     `_publish_master_cull(master_results, <all target tasks>)`, which derives
     `label -> produced output paths` from each master result's
     `task.targets` + `meta["processed_target"].run_label()`, computes `needed`
     via `masters_needed_by()`, and publishes `EVENT_PREFLIGHT_FINISHED` with the
     dropped labels.  (It is naturally a no-op with ≤1 master run or no targets,
     so no extra guard is needed.)
   - Phase 2 runs each *prebuilt* target task list with `prune=False`, then
     calls `ProcessedTarget.remove_processing_dir()` immediately after each
     target; one `cleanup_old_contexts()` runs at the very end.
   - `--no-masters` simply skips phase 1 (empty `master_results`), so nothing is
     culled.

Publish shape (keep it plain data, like the other run events):

```python
{"drop": [<master run label>, ...]}
```

Downstream already keys runs by `target` label (`self._runs`, `self._targets`),
so labels are the natural handle. (Open question 2 covers label uniqueness.)

### CLI (`src/starbash/commands/process.py`)

`ProcessingView._on_event()`: on `EVENT_PREFLIGHT_FINISHED`, delete each dropped
label from `self._runs` and `self._order`, then `_refresh()`.

### GUI (`src/starbash/ui/qt/pages/processing.py`)

`_on_event()`: on the new event, for each dropped label, remove its top-level
item from `self._tasks` and pop it from `self._targets` (guarding
`self._running`). This is the path the "Run auto pipeline" button drives via
`ui/qt/jobs.py:process_job`.

## Phased implementation

> **Status: implemented.**  The core, both front-ends and the unit tests are in
> place; the full `tests/unit` suite passes.  What landed:

1. ✅ **Core helper + event.** `EVENT_PREFLIGHT_FINISHED`, `masters_needed_by()`,
   and `Processing._publish_master_cull()` (which derives `label -> outputs` from
   the master results and publishes the drop list).  Guarded so it is a no-op
   with ≤1 master run or no targets.
2. ✅ **Preflight phase** in `run_all_stages()`: build every target first, publish
   the cull, then run the prebuilt tasks with `prune=False` and shed each
   target's processing dir via `ProcessedTarget.remove_processing_dir()` right
   after its run; one `cleanup_old_contexts()` at the very end.  Targets are now
   processed in stable session order (deduped) rather than arbitrary `set` order.
3. ✅ **CLI handler** in `ProcessingView._on_event` (`EVENT_PREFLIGHT_FINISHED`).
4. ✅ **GUI handler** in `ProcessingPage._on_preflight_finished`.
5. ✅ **Memory bank** update (`activeContext.md`) referencing this plan.

Two details worth calling out:

* **The cull is guarded.** `_publish_master_cull()` returns early (publishing
  nothing) when there are no targets or only one master run. Without the first
  guard, a selection with no light frames would compute an empty `needed` set and
  drop *every* master run from the displayed tree — the masters did run, so they
  must stay visible.
* **Each target's processing dir is shed immediately.** Instead of relying on a
  prune between targets (which could delete a dir that has not run yet), the run
  loop calls `ProcessedTarget.remove_processing_dir()` right after that target's
  run, then prunes once at the very end. This is what keeps the `.cache` tree
  from accumulating one per-target copy while still bounding it normally.

### Where the tests live

Rather than the new files sketched below, the tests were added to the existing
`tests/unit/test_processing.py` (`TestMastersNeededBy`, `TestRunAllTasksPrune`,
`TestPublishMasterCull`, `TestRunAllStagesPreflight`) plus
`tests/unit/test_run_tree_rich.py` (CLI) and `tests/unit/test_gui.py` (GUI),
keeping related coverage together.

## Testing strategy

- `tests/unit/test_processing_cull.py` (new): table-driven tests for
  `masters_needed_by()` — direct dep, transitive master→master dep, no deps
  (everything unnecessary), path normalisation/symlinks. Assert on the resulting
  set (not mocks).
- `tests/unit/test_process_view.py` (or extend an existing processing-view
  test): a `ProcessingView` receiving `EVENT_RUN_FINISHED` ×N then
  `EVENT_PREFLIGHT_FINISHED` must drop the named runs from `_order`/`_runs`.
- GUI: extend `tests/unit/test_gui.py` / a processing-page test with the same
  scenario, asserting the dropped top-level item is gone and the kept ones
  remain (query `self._targets` / `topLevelItemCount()`).
- Optional integration: extend `tests/integration/test_workflow.py`
  (`TestProcessAutoWorkflow`) to assert that at most the used masters remain.
- Default suite only; no new optional deps. Run `poetry run pytest -m "not gui"`
  plus the gui-marked tests.

## Risks / open questions

1. **Double task build (approach B).** Only relevant if we fall back to B —
   acceptable then; measure before optimising. Could be gated (skip when only one
   master run / one target).
2. **Master run label uniqueness.** `run_label()` is
   `Master {session_config} · {date} · {camera}`. Sessions are aggregated by
   type/filter/date, so collisions should be rare, but if two master runs share
   a label the front-ends already merge them (a pre-existing issue). Prefer
   deciding keep/drop by output path and, if needed, key runs by output URL
   rather than label.
3. **Transitive master deps.** A needed flat master consumes a bias/dark master;
   that bias/dark must not be culled. `masters_needed_by()` handles this via the
   closure — verify against real repo recipes.
4. **Preflight-phase side effects.** It builds every target (writes target config,
   creates processing dirs). Confirm idempotence in a test, that no tool is
   executed (task building must not run anything), and that no prune happens
   while building (the `close()` fix).
5. **When not to cull.** `sb process masters` (`run_master_stages()` alone) has
   no targets — nothing to cull, leave as-is. The same happens inside
   `run_all_stages()` when the selection yields no light targets; the guard in
   `_publish_master_cull()` prevents that case from dropping every master.

