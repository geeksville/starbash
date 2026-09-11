# Plan: `ProcessedTarget` as the single per-target model + live run tree

**Status:** In progress (approved 2026-09-11)
**Scope:** Consolidate per-target file I/O behind `ProcessedTarget`; add a run-state
model derived from doit metadata; drive a live Rich tree (CLI) and a tree view
(GUI) from the event bus.

## 1. Goal / summary

1. **Per-target persistence is scattered.** `.starbash/{main,about,sessions}.toml`
   and `starbash.log` are read/written from several modules with hand-rolled
   `tomlkit` parsing (`ui/qt/services.py`, `publish/github.py`, `doit.py`,
   `commands/process.py`). Make `ProcessedTarget` the one model every other
   module uses, with a **read-only open path** so GUI/publish don't need a
   `Processing` instance.
2. **Run results come from doit metadata** that the CLI currently re-interprets
   in `commands/process.py:print_results()`. Move that extraction into the model
   and expose a clean, **plain-data** tree (stages run / not run, inputs, outputs,
   dependencies, links). The CLI renders it live as a Rich tree; the GUI renders a
   tree view; both are fed by the event bus.

**Non-goal:** changing the processing pipeline or the on-disk format of
`main/about/sessions.toml`.

## 2. Decisions (from review)

- **Dependencies come from doit data only** — an edge A→B when
  `A.file_dep ∩ B.targets ≠ ∅`, plus explicit `task_dep`. The stage `after`
  regex is already reflected in the generated `file_dep`/`targets`, so it is not
  consulted directly.
- **Persist the run** as `.starbash/run-log.toml`, owned by `ProcessedTarget`,
  so the most recent run can be re-loaded (the GUI can show the last run before a
  new one starts). Structured as a list so a bounded history can be added later.
- **Per-stage log tail** via a "current stage" pointer plus a bounded ring buffer
  (default last 8 lines). Fed by `EVENT_TOOL_OUTPUT` (tool lines) *and* a small
  `logging.Handler` → `EVENT_LOG_MESSAGE` (Starbash's own log lines), because tool
  output alone is sparse. Frozen into `StageNode.logs` and written (trimmed) to
  `run-log.toml`.
- **Single `ProcessedTarget` class** with a `read_only` mode + `open()` classmethod
  + `discover()` — no separate config class.
- **One shared Rich `Live`/console** threaded through `Processing` so the existing
  `Progress` bar and the new tree don't fight over the terminal.

## 3. Model API

### 3.1 Construction

```python
# processing path (unchanged signature)
ProcessedTarget(p: ProcessingLike, target: str | None)

# NEW: open an existing target dir read-only (no temp dir, no log wipe,
# never writes).  self.p is None, self.read_only is True.
ProcessedTarget.open(target_dir: Path | str) -> ProcessedTarget
ProcessedTarget.discover(root: Path | str) -> list[ProcessedTarget]
```

### 3.2 New accessors

| New API | Replaces |
|---|---|
| `ProcessedTarget.discover(root)` | `services.load_targets`, `publish._targets` |
| `pt.config_url`, `pt.log_path`, `pt.output_dir` | raw `pt.repo.config_url`, `pt.log_path` |
| `pt.stage_entries()` | `_stage_counts`, raw `get_stages_aot` walks |
| `pt.stage_counts()` | `services._stage_counts` |
| `pt.stage_options(declarations)` | `services.load_stage_options` |
| `pt.save_stage_options(options)` | `services.save_stage_options` |
| `pt.about`, `pt.sessions` | `publish._targets` merging three files |
| `pt.record_result(result)` / `pt.run_tree()` | `commands/process.py:print_results` metadata walk |
| `pt.save_run_log()` / `pt.latest_run()` | (new persistence) |

`StageOption` / `ParameterOption` dataclasses move into the core model
(re-exported from `ui/qt/services.py` for compatibility).


## 4. Run-state model — `src/starbash/run_state.py`

Dependency-free dataclasses (no import of `doit.py`, to avoid cycles):

```python
class RunStatus(StrEnum): PENDING, RUNNING, OK, SKIPPED, FAILED, EXCLUDED

@dataclass FileRef:  label: str; url: str | None
@dataclass TaskNode: name, title, status, reason, session, inputs, outputs
@dataclass StageNode: name, description, status, excluded, recipe_url,
                      config_url, inputs, outputs, dependencies, tasks, logs
@dataclass RunTree:  target, output_url, stages
```

`RunState` accumulates results into the tree, derives dependencies from the doit
task graph, keeps the current-task pointer + log ring buffer, and can
serialise/deserialise (`to_plain()`, `to_toml()`, `from_toml()`).

`ProcessedTarget` owns `self.run: RunState`.

## 5. Events

- Enrich `EVENT_TASK_STARTED/FINISHED` with `target`, `stage`, `is_master`
  (read from `task.meta` in `doit.py:MyReporter`).
- `Processing.add_result` calls `pt.record_result(result)` then publishes a
  plain-data `EVENT_STAGE_RESULT` payload.
- New `EVENT_RUN_STARTED` / `EVENT_RUN_FINISHED`.
- A `logging.Handler` → `EVENT_LOG_MESSAGE` bridge feeds the per-stage log tail.

## 6. CLI — live Rich tree

`commands/process.py` replaces the end-of-run `Table` with a live view: root =
target, children = stages, grandchildren = tasks, each with status glyph, links
(`to_rich_link`) and a dim log tail. Rendered via a single `rich.live.Live`
shared with the `Progress` bar; the final tree is printed on completion.

## 7. GUI — processing page tree

`ui/qt/pages/processing.py` builds a nested target → stage → task tree from the
enriched events, with status colours, clickable recipe/config links and a log
tail. Live updates stay event-driven (no polling).

## 8. Migration of remaining consumers

- `ui/qt/services.py`: delegate to the model; re-export option dataclasses.
- `publish/github.py`: use `ProcessedTarget.discover` + `about`/`sessions`.
- `commands/process.py`, `doit.py`: use `pt.config_url` / `pt.log_path`.

## 9. `run-log.toml` schema

```toml
[[run]]                       # newest first
timestamp = 2026-09-11T14:03:22Z
success = true
stages_run = 7
stages_failed = 0
output = "file:///.../stacked/....fits"

  [[run.stage]]
  name = "stack_osc"
  status = "ok"               # pending|running|ok|skipped|failed|excluded
  description = "..."
  recipe_url = "file:///..."
  config_url = "file:///..."
  dependencies = ["pp_lights"]
  inputs = ["file:///..."]
  outputs = ["file:///..."]
  logs = ["...", "..."]

    [[run.stage.task]]
    name = "stack_osc"; title = "..."; status = "ok"; session = "..."
    inputs = ["..."]; outputs = ["..."]; logs = ["..."]
```

## 10. Phases

0. **Model foundation** — `run_state.py`; `ProcessedTarget.open()` read-only mode
   + accessors; unit tests.
1. **Events + recording** — `record_result`, enriched payloads, run-log persist.
2. **CLI live tree** — `ProcessingView`; shared `Live`/`Progress`.
3. **GUI tree** — nested tree from events.
4. **Migrate consumers** — services + publish onto the model.
5. **Polish** — docs / memory bank, optional log-handler event.

## 11. Risks / open questions

- Shared `Live` + `Progress` wiring (resolve in Phase 2).
- Run-log history depth (currently latest run only).
- GUI/CLI must consume *plain-data* events only — the producing
  `Starbash`/SQLite connection belongs to the worker thread.
## 12. Refinements after review

- **Master (calibration) runs stay in the tree** but are no longer shown as
  opaque `temp_*` names.  `ProcessedTarget.run_label()` names a master run from
  its context (e.g. `Master flat_Ha · 2024-01-01 · canon`), and the plain
  `RunTree` carries `is_master` so the GUI can leave those roots **collapsed**
  (there are usually many and they are rarely being watched).  Real targets keep
  their directory name and open by default.  `MyReporter._task_labels` uses the
  same label so `task.*` events line up with the tree nodes.
- **The GUI log pane is gone.**  The tree *is* the log: `tool.output` /
  `log.message` lines are appended live under the currently-running stage node
  (`_append_log_line`, bounded to `_LIVE_LOG_LIMIT`), and the model's per-stage
  `logs` tail is rendered on each stage-result rebuild.
- `RunState`/`RunTree` gained `is_master`; `processing._finish_runs` publishes the
  run's descriptive `target` label instead of the temp dir name.
- **Only relevant stages are listed.**  The tree was previously seeded from the
  target's `main.toml` `[[stages]]` AoT, which is the union of *every* recipe's
  stages (so a master listed `noise_exterminator`, and a light target listed
  `master_dark`).  Now `Processing._job_to_tasks` records the stages that actually
  produced a doit task (`tasks_to_stages(candidate_tasks)`) via
  `ProcessedTarget.set_run_stages()`, and `_ensure_run()` seeds from that list
  (marking user-excluded stages as `excluded`); the config-based seeding remains
  only as a fallback when no task list was supplied.
- **`RunStatus.PENDING` displays as `unused`** in the tree (`RunStatus.label`); the
  serialized value stays `"pending"` for `run-log.toml` compatibility.

