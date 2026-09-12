# Plans

Implementation and design plans live in `doc/plans/*.md` and are tracked in git.

## Rules

- When I create or edit a plan, I MUST save it as `doc/plans/<topic>.md`
  (kebab-case, e.g. `gui.md`).
- Always persist plans to that directory so they can eventually be committed —
  never leave a plan only in chat or in a temporary location.
- One plan per file. Update the existing file for the topic instead of creating
  a near-duplicate; use dated filenames only when an explicit supersession is
  intended.
- Plans are implementation-oriented. Each should include: goal/summary,
  approach, library/technology choices with rationale, file & component layout,
  a phased implementation sequence, testing strategy, and risks/open questions.
- When a plan drives active work, reference it from the memory bank
  (`activeContext.md`).
- Do not delete a plan; mark it superseded and link the replacement.

## Existing plans

- `doc/plans/gui.md` — PySide6 desktop GUI launched via `sb gui`.
- `doc/plans/processed-target-model.md` — `ProcessedTarget` as the single model
  for a target's `.starbash` files + the live run tree.
- `doc/plans/master-cull.md` — cull unneeded master runs from the displayed
  pipeline before phase 2.
