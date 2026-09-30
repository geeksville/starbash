# Stage conflict exclusion — resolve it before the graph is built

## Status

**Implemented 2026-09-30.** Fixes the `crop_m20_i3` / `stacked_Sii.fits` failure
that `tests/integration/test_workflow.py` only exposed in its log (the run exited
0 and the summary table was never checked).

## The bug

A target file may only be written by one stage.  When two stages claim the same
output (`stack_single_duo` and `stack_dual_duo` both write `stacked_Ha.fits` /
`stacked_OIII.fits`), `Processing.preflight_tasks()` kept the first (highest
priority) and recorded the rest as `excluded = true` — the same persisted flag a
user toggle writes.

But preflight ran **after** `_stages_to_tasks()` had built the whole graph, and
that first pass had already given consumers the losing stage's outputs:
`common/crop.toml` declares `[[stages.inputs]] kind = "job" after = "stack_.*"`,
`multiplex = true`, so crop got **one task per upstream stack output** — including
`stacked_Sii.fits`, which only `stack_dual_duo` produces.

Nothing re-checked those consumers after the exclusion.  On a *fresh* target
(target m20 in the test data: HaOiii + SiiOiii sessions) the graph therefore
contained `crop_m20_i3`, whose `file_dep` was a file no surviving task would
create:

```
crop_m20_i3  dep: .../processed/m20/stacked_Sii.fits  (does not exist)
             tgt: .../processed/m20/crop_stacked_Sii.fits
```

doit treats a missing `file_dep` as "needs running", so the task ran, the crop
script died on `FileNotFoundError`, the task failed, and doit abandoned the rest
of the target — m20 was left entirely unprocessed (every other m20 stage stayed
`Pending` in the summary table).  A *second* run was fine, because by then the
exclusion was persisted and `select_stages()` dropped the loser before any task
existed.  The bug was therefore **first-run-only**, which is exactly the case the
integration test covers.

## Fix

Split the conflict resolution out of `preflight_tasks()` and run it as a step
that the graph builder can react to:

* `Processing._exclude_conflicting_stages(pt, tasks) -> bool` — the moved code
  (per-target-file producer multimap, keep the first, `mark_excluded` the rest).
  It now also reports whether it newly excluded anything.
* `Processing._build_target_tasks(pt)` — the select → sort → build loop.  After
  each pass it calls `_exclude_conflicting_stages()`; if that excluded a stage it
  clears `doit.dicts` and builds again.  The second pass re-runs `select_stages()`
  with the just-recorded exclusion, so the loser's branch never materialises and
  its consumers are never created — the same graph a later run produces.  Each
  pass excludes at least one more stage, so the loop terminates.
* `preflight_tasks(tasks)` — now only the user-exclusion filter, the missing-tool
  filter and `set_used_stages_from_tasks()`.  (It no longer needs `pt`.)

Excluding a stage before the rebuild is preferable to pruning orphaned tasks
afterwards: pruning by `file_dep` cannot tell "this file is gone" from "this file
is now produced by the surviving stage" (the loser's `stacked_Ha.fits` *is* still
produced, by the winner), and a consumer that needs only *some* of the loser's
files (e.g. `report_duo`, which reads the shared `r_all_ha_.seq`) should keep
running rather than be dropped.

## Tests

* `tests/unit/test_processing.py::TestExcludeConflictingStages` — the loser is
  excluded and reported as newly excluded; no conflict reports `False`; a second
  pass over the winner reports `False` (the loop converges).
* `tests/unit/test_processing.py::TestBuildTargetTasksConflictRebuild` — a fake
  catalog + builder that reproduces the shape (two stack stages, a multiplexed
  consumer): the graph is built exactly twice, `stack_dual_duo` ends up excluded,
  `crop_m20_i2` (the consumer of its unique output) is gone, the winner's crops
  survive, and no remaining task depends on `stacked_Sii.fits`.
* `tests/integration/test_workflow.py::TestProcessAutoWorkflow` — the summary
  table is now asserted to contain **no** `Failed` row.  The failure it caught
  was invisible otherwise: `sb process auto` exited 0 and the successful-row
  count was still >= 10.

## Verified

Reproduced outside pytest (temp dirs + `repo add /test-data/nina`, `--master`,
`--processed`, `sb --force process masters`, then `_create_tasks(..., ["m20"])`):

* **before** — first-run graph 36 tasks including the doomed `crop_m20_i3`, and
  running it executed *only* that task (`RESULT crop_m20_i3: success=False`), so
  the target produced nothing;
* **after** — first-run graph 32 tasks, no task references `stacked_Sii.fits`, and
  the target runs to the end: 31 results, **all** `success=True`, with
  `SHO.fits` / `HOO.fits` / `merged_*` / `hms_*` thumbnails written.  The only
  task that does not run is `seqextract_haoiii_m20_s4`, whose sole consumer was
  the excluded `stack_dual_duo`.  Re-building the same target again yields the
  same 32-task graph (the exclusion is persisted, so it is idempotent).

Consequence for the suite: `tests/integration/test_workflow.py` now does the
work it used to skip — m20 accumulates 6 rc-astro runs plus 2 StarNet runs, so
`just test-integration` takes correspondingly longer on this data.

`just lint` clean (basedpyright 0 errors); full unit suite **1381 passed, 1
skipped**.
