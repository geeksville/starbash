
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

## stage m2