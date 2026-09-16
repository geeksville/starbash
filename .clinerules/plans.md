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
- `doc/plans/session-masters.md` — structured, machine-parseable per-session
  master selection in `sessions.toml` (replaces the comment-carried reasons),
  consumed by the GUI Targets screen.
- `doc/plans/targets-redesign.md` — the sequenced execution plan for the Targets
  screen redesign (narrow target picker + grouped explorer tree + session/master
  detail pane); implemented, kept as the build record. Design: `gui.md` §5.5.
- `doc/plans/stage-roles.md` — optional `role` on `[[stages]]` so interchangeable
  implementations (GraXpert vs RC-Astro deconvolution/denoise) auto-select by
  `priority`, plus generalizing the `after` clause to accept role names.
  **Phase 1 implemented 2026-09-14**; the test/code map is the table at the top of
  the file. Both blocking questions were **decided** the same day — §7.1: a *higher*
  `priority` wins (the code's existing rule), §7.2: `exclude_by_default` is dropped,
  not honoured. Phase 2 (GUI grouping, per-session role resolution) remains open.
- `doc/plans/qt-object-lifetimes.md` — the two Qt-lifetime crashes (the
  `test_every_page_refreshes_without_error` SIGSEGV and the CI `RecursionError`) and
  their fix: a pool drain in `tests/conftest.py`, `Worker.run` dropping a report whose
  signals are gone, `setAutoDelete(False)`, a self-detaching `EventBusBridge`, and a
  recursion-proof `events.publish` failure path. **Implemented 2026-09-15**; its
  *Open question* (should closing the GUI cancel-and-wait for in-flight jobs?) is
  **undecided** and deliberately left out of the fix.
- `doc/plans/gui-setup-wizard.md` — the GUI's first run end to end: the setup
  dialog becomes a six-page **`QWizard`** (welcome → you → output folders →
  raw-image folder picker → tools → checklist), page 2 requires a **username**
  (which is also the first-run test, replacing the config-file check), page 5
  **blocks on a missing required tool** (Siril) and needs a new
  `Tool.invalidate_availability()` for its *Re-check* button, and the last page's
  two closing actions (*Process all my targets* / *Pick a target*) stay disabled
  until the folders, the images and the required tools are in place. Also makes
  bare `sb` open the GUI when a desktop session exists. **Proposed and revised
  2026-09-15, awaiting review**; no code written. Design record: `gui.md` §5.9.
- `doc/plans/gui-widget-teardown.md` — the *third* crash in that area (the xdist-only
  SIGSEGV that the Masters-tree tests made likely): a test's widgets were never
  destroyed, so a later cyclic collection destroyed them off the GUI thread. Fix: the
  teardown hook flushes the pending `DeferredDelete` events and collects widget garbage
  on the GUI thread, plus `workers.guard_callback` for job callbacks PySide cannot tie
  to a receiver (`partial`/lambda). **Implemented 2026-09-15.**
