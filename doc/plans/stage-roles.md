# Stage roles — interchangeable implementations with automatic fallback

Status: **Phase 1 implemented** (2026-09-14). Both blocking questions were
**decided** (2026-09-14): **§7.1 — the code's existing rule stands, a higher
`priority` wins**, and **§7.2 — `exclude_by_default` is dropped** rather than
honoured, because roles subsume it (§3.4). §7 keeps the rejected alternatives on
record.

What landed, and where to look for the proof:

| Piece | Code | Tests |
|---|---|---|
| `select_stages()` + `_stage_drop_reason()` | `src/starbash/stages.py:142-247` | `tests/unit/test_stage_roles.py::TestSelectStages` |
| `StageSelection.resolve()` — `after` names a role | `src/starbash/stages.py:55-140` | `::TestResolveAfterPattern` |
| `sort_stages(resolve=…)` | `src/starbash/stages.py:250-355` | `::TestSortStagesWithResolve` |
| call site (select → sort → tasks) | `src/starbash/processing.py:885-900` | `tests/unit/test_processing.py` |
| `_get_prior_tasks()` role resolution + hint | `src/starbash/processing.py:1029-1106` (resolution 1044-1066, hint 1095-1105) | `tests/unit/test_processing.py::TestGetPriorTasksWithRoles` |
| `exclude_by_default` removed | `src/starbash/processed_target.py:601-618` | `tests/unit/test_processed_target.py::test_set_default_stages_gives_every_stage_an_entry` |
| recipes (`role`/`priority`, palette `after`) | `starbash-recipes/{graxpert,rc-astro,palette}/*.toml` | `::TestRecipeRoles`, `::TestRoleFallbackPipeline` |

Phase 2 (GUI grouping, per-session role resolution) and Phase 3 remain open —
see §10.

## 1. Goal

Let a recipe declare that a stage is one *implementation* of a pipeline step:

```toml
[[stages]]
name = "blur_exterminator"
role = "deblur"
priority = 350
```

When several **non-disabled, tool-available** stages share a `role`, only one of
them is used for a run — the best `priority`. Nothing else in the graph changes
for the author.

The first use is automatic fallback between the two deconvolution/denoise
implementations:

| role | stages | tool |
|---|---|---|
| `deblur` | `deconv-obj` | graxpert |
| | `blur_exterminator` | rc-astro |
| `denoise` | `denoise` | graxpert |
| | `noise_exterminator` | rc-astro |

with `background`, `palette` and `auto-stretch` as the obvious next roles (and
`deblur`/`denoise` also carrying a side effect: they become a natural grouping
key for the GUI Targets screen).

The same change **generalizes the `after` clause** so that its regex may name a
*role* as well as a stage (`after = "denoise"`), which is what keeps downstream
recipes from having to know which implementation won (§6). That is the piece that
makes the feature usable for authors rather than a one-off fallback.

## 2. Why the current graph cannot do this

The narrowband/duo pipeline is:

```
crop ─ background ─┬─ deconv-obj ─────── denoise ────────────┐
                   └─ blur_exterminator ─ noise_exterminator ─┴─ palette.{broadband,hoo,sho}
                                                                     │
                                                        starnet ─ merge_stars ─ thumbnail
```

(`graxpert/deconv-obj.toml:28` `after = "background.*"`, `graxpert/denoise.toml:27`
`after = "deconv-obj.*"`, `rc-astro/blur-exterminator.toml:25` `after = "background.*"`,
`rc-astro/noise-exterminator.toml:43` `after = "blur_exterminator"`,
`palette/{broadband,hoo,sho}.toml` `after = "noise_exterminator"`.)

So **the palette branch is hard-wired to the rc-astro stages.** A user without
rc-astro installed currently gets *no* palette, starnet, merge_stars or thumbnail
output at all — `_remove_missing_tool_tasks()` runs in `preflight_tasks()`
(`src/starbash/processing.py:1490-1520`), i.e. **after** the whole task graph has
been built, so the palette tasks survive with inputs that can never be produced.
The GraXpert branch is a dead end for the palette.

That ordering is the central constraint on this design: **role selection must
happen before any task is created**, so the losing branch never materialises and
downstream stages follow the winner. A filter applied in `preflight_tasks()`
(next to `remove_excluded_tasks()`) is too late.

The second problem is the *reference* itself. `after` is today a regex matched
against **stage names only**, in two consumers with two different behaviours:

| consumer | matches | rule |
|---|---|---|
| `sort_stages()` (`stages.py:77-87`) | `^pattern$` over the stage names in the list | one dependency edge per match |
| `_get_prior_tasks()` (`processing.py:1025-1056`) | `^pattern` + target/session suffix, over doit **task** names | collects the prior tasks, else raises `NoPriorTaskException` (a `NonFatalException` → `_create_task_dict` logs at debug and the *whole stage* is skipped, `:1304-1305`) |

Neither knows about roles, so `after = "noise_exterminator"` names an
*implementation*, not a capability. §6 generalizes the clause: a role name or a
stage name both resolve to the stages that will actually run.

## 3. Proposed semantics

* `role` — optional string on `[[stages]]`. Names a capability slot; stages with
  the same role are interchangeable.
* **Candidate** = a stage with that role that is
  * not `disabled = true`,
  * not excluded (`excluded = true` in the target's `[[stages]]`, per §3.3),
  * whose tool is available (`Tool.is_available`).
* **Winner** = the candidate with the best `priority` (direction: §7.1 = higher
  wins). Ties fall back to catalog order — **earlier wins**, verified: the sorts at
  `stages.py:96`/`:117` are Python's *stable* sort over a default of `0`
  (`[aaa,bbb]` stays `[aaa,bbb]`, `[bbb,aaa]` stays `[bbb,aaa]`). (Later-wins is the
  *different* rule for two stages sharing one `name`, which `stage_by_name`
  collapses; it is not what breaks role ties.) Recipes must therefore still set
  distinct priorities — catalog order is an accident of repo precedence, not a
  statement of intent.
* **Losers are dropped from the run** (no task, not in the run tree). They are
  **not** written to the user's config: selection is recomputed every run, so
  installing rc-astro later switches the branch back automatically. This is
  deliberately different from the conflicting-output path
  (`processing.py:1534-1551`), which persists `mark_excluded()` and would make
  the choice sticky.
* Every decision is logged once (`INFO`, or `DEBUG` for a redundant
  duplicate-of-same-tool case) as
  `Stage 'denoise' shares role 'denoise' with 'noise_exterminator'; using the latter (priority 350)`.
* A role with **no** candidate yields nothing (existing behaviour: the dependent
  stages are skipped).

### 3.1 `disabled`

The guide already documents it (`doc/toml/guide.md:158`, quick reference `:606`)
and `starbash-recipes/master/{bias,dark,flat}.toml:8` carry a commented-out
example, but **it is not implemented anywhere in `src/`**. Implement it in the
same selection filter — it is the same "not considered" concept and the role rule
refers to it.

### 3.2 Interaction with `_remove_missing_tool_tasks()`

Keep it as a safety net for non-role stages. Role candidates are pre-filtered on
availability, so the winner's tool is available by construction and preflight
never has to drop it.

### 3.3 Known limitation (Phase 1): per-session exclusions

Exclusions live in two places: the target's `default_stages` (visible here) and
each session's own `[[stages]]` (applied later, per task, by
`remove_excluded_tasks()`, `stages.py:215-228`). Role selection runs before
sessions are expanded, so it only sees the target-level list. Consequence: if a
user excludes the role winner for *one session only*, that session's branch is
skipped (preflight removes the task) and the loser is not resurrected.

Documented in the guide; the fix (resolve roles per session) is Phase 2 (§10).

### 3.4 `exclude_by_default` is removed (decided)

`exclude_by_default = true` exists so the slow GraXpert stages are not run unless
opted into (`graxpert/deconv-obj.toml:9`, `denoise.toml:9`;
`ProcessedTarget._set_default_stages()` persists them as `excluded`,
`processed_target.py:601-621`, flag read at `:617`). **Roles subsume the feature,
so it is dropped** — decided at review:

* the GraXpert stages become ordinary role candidates, and their priority (§5)
  loses to rc-astro's, so with rc-astro installed they still never run;
* they run only when rc-astro is absent — precisely the case the old flag got
  *wrong* (a user with no rc-astro also lost the whole palette);
* "it is very slow, do not run it by default" is now expressed honestly, as a
  *choice between implementations*, instead of by hiding one stage from the graph.

Removal touches: the two recipe lines (delete them, do not comment them out), the
`exclude_by_default` read in `_set_default_stages()`, the tests that pin the
behaviour (`tests/unit/test_processed_target.py:256-269` and `:350-373`), the
`doc/design/new-params.md:159` mention, and the guide text. **`excluded` itself
stays** — that is the user's own toggle, and the GUI Targets checkbox keeps writing
it.

Migration: an existing target's `.starbash/main.toml` may already carry
`excluded = true` for these two stages, persisted the first time it was processed.
§3.3's "existing entries are left alone" rule means removing the feature does not
retroactively un-exclude them — and deliberately so, since it cannot distinguish
that from a human turning the stage off. Those users get no GraXpert fallback until
they clear the flag, so Phase 1 should surface a one-line hint in the run log when a
role has *no* candidate but a stage for that role exists while excluded ("stage
'denoise' would implement role 'denoise' but is excluded for this target").

The submodule's two uncommitted local edits (the flags commented out) are this same
decision, incompletely applied: they become deletions.

## 4. Code layout

### 4.1 `src/starbash/stages.py` — new selection step

```python
@dataclass
class StageSelection:
    """The stages that may run, plus what role selection decided."""

    stages: list[StageDict]          # selected, in catalog order
    roles: dict[str, str]            # role -> winning stage name
    dropped: dict[str, str]          # dropped stage name -> reason (for logs/GUI)

    def resolve(self, pattern: str) -> list[str]:  # §4.3
        """Stage names that will actually run for an `after` pattern (§6)."""

def select_stages(
    stages: list[StageDict],
    *,
    is_available: Callable[[str], bool] | None = None,   # tool name -> installed
    is_excluded: Callable[[StageDict], bool] | None = None,
) -> StageSelection: ...
```

Pure function, no `Processing`/`ProcessedTarget` coupling — easy to unit test.
Order of filtering: `disabled` → excluded → tool availability → role dedup.
A stage with no `role` is only subject to the first three rules, so existing
recipes behave exactly as today. `StageDict` is `dict[str, Any]`
(`src/starbash/__init__.py:15`), so no type change is needed for `role`.

### 4.2 `src/starbash/processing.py` — call site

`_job_to_tasks()` (`:873-898`) already opens the `ProcessedTarget` and holds the
sorted catalog; insert the selection between the two:

```python
stages = self.stages                       # raw catalog (unchanged, still sorted)
selection = select_stages(
    stages,
    is_available=lambda tool: (tools.get(tool) is not None and tools[tool].is_available),
    is_excluded=lambda s: is_excluded(pt.default_stages, s.get("name", "")),
)
self._stage_selection = selection          # §4.3/§6 resolution + GUI (§8)
ordered = sort_stages(selection.stages, resolve=selection.resolve)  # §4.3
candidate_tasks = self._stages_to_tasks(ordered)
```

Leave the `stages` property (`:900-926`) alone: `processed_target.py:612`
(`_ensure_default_stages`) iterates it to seed the target's `[[stages]]` list, and
must keep seeing *all* stages — including role losers — so the GUI can still list
and toggle them.

`sort_stages()` itself needs no new ordering logic: selecting drops only stages
that are role *siblings*, and a role winner is a sibling of the loser, so no edge
between two surviving stages is invalidated by the drop. The re-sort in §4.3 is
only so that a consumer's `after` resolves against what survived.

Two behaviours a dropped-stage reference can now have:

* **role member, redirected (§6)** — `after` naming the loser (or the role) lands
  on the winner, which *is* in the graph, so the consumer runs normally. This is
  what makes `after = "noise_exterminator"` keep working when the winner is
  `denoise`.
* **resolves to nothing** — the winner is gone because the role has no candidate
  (both tools missing). Then `sort_stages()` sees no edge and `_get_prior_tasks()`
  raises `NoPriorTaskException`, and the existing non-fatal path skips the stage
  (`:1304-1305`). That is still the correct outcome, just now limited to the
  genuinely-empty case.

### 4.3 `after` resolution — `StageSelection.resolve()`

`StageSelection` also carries what `after` needs (§6 is the normative spec):

```python
@dataclass
class StageSelection:
    stages: list[StageDict]          # selected, in catalog order
    roles: dict[str, str]            # role -> winning stage name
    dropped: dict[str, str]          # dropped stage name -> reason (for logs/GUI)

    def resolve(self, pattern: str) -> list[str]:
        """Stage names that will actually run for an `after` pattern (§6)."""
```

`resolve()` matches `pattern` against **stage names ∪ role names** and maps each
match to its canonical provider: a selected stage name → itself; a dropped stage
name → the winner of its role; a role name → its winner; nothing → `[]`. It is
built from the catalog plus the selection result, so it is pure and directly
unit-testable (`selection.resolve("noise_exterminator") == ["denoise"]` in the
no-rc-astro case).

Two consumers, both fed the resolved names:

* `sort_stages(stages, resolve=...)` (`stages.py:50-137`) — replaces the
  name-only loop at `:77-87`; `resolve=None` keeps the old behaviour
  byte-for-byte, so the existing `sort_stages` tests in `tests/unit/test_tool.py`
  stay valid as the regression guard.
* `_get_prior_tasks()` (`processing.py:1010-1072`) — builds its task-name pattern
  from the resolved names rather than the raw `after`
  (`f"(?:{'|'.join(map(re.escape, providers))}){self._get_unique_task_name('')}"`).
  That deletes the alternation-slicing hack at `:1035-1037`: the providers are
  literals and the suffix comes from `_get_unique_task_name("")`, which yields
  *just* the target/session/multiplex suffix. Both compiled patterns (exact and
  prefix) stay exactly as they are — only their source string changes. With no
  selection (`self._stage_selection is None`, e.g. a hand-built `Processing` in a
  unit test) the existing code path runs unchanged.

## 5. Recipe changes

Phase 1 — roles, priorities and role-named references:

| file | change |
|---|---|
| `starbash-recipes/graxpert/deconv-obj.toml:7` | `role = "deblur"`, `priority = 300`; **delete** the commented-out `exclude_by_default` line (`:9`, §3.4) |
| `starbash-recipes/graxpert/denoise.toml:7` | `role = "denoise"`, `priority = 300`; **delete** the commented-out `exclude_by_default` line (`:9`) |
| `starbash-recipes/rc-astro/blur-exterminator.toml:6` | `role = "deblur"`, `priority = 350` |
| `starbash-recipes/rc-astro/noise-exterminator.toml:6` | `role = "denoise"`, `priority = 350` |
| `palette/broadband.toml:24`, `palette/hoo.toml:48,67`, `palette/sho.toml:63,82,102` | `after = "denoise"` (role name, §6) |

Six palette lines, one per existing `after = "noise_exterminator"`. Role dedup
leaves exactly one live `denoise` producer and `sort_stages()` orders role
providers before their consumers either way, so this is a rename, not a graph
change. `after = "deblur"` is *not* needed: nothing downstream reads the
deconvolution output except the denoiser, and both role members already point at
`background.*`.

**The numbers.** None of the four stages carries a `priority` today, so all four
currently tie at the default `0` (§3: the winner would fall out of catalog order,
which is exactly what a role must not depend on). `350`/`300` are both unused in the
catalog, sit above the `0` default, and stay clear of the stackers/report
(310/320/330/340) and `master/dark.toml`'s 2000, so the values are purely
role-internal and reorder nothing else: dependencies already serialise
`background → deblur → denoise → palette`. **rc-astro above GraXpert is the point** —
with both tools installed the fast native stages win and GraXpert is never scheduled;
with rc-astro absent GraXpert wins by default rather than by a user's checkbox
(§7.2). If the numbers ever drift back to equal, §7.1's direction is the only thing
deciding the branch, and catalog order takes over — hence the `priority` assertion in
§9's recipe test.

(If the generalized `after` is deferred — §10 — the interim form is
`after = "(noise_exterminator|denoise)"`, correct because role dedup guarantees at
most one of the two exists. It is deleted again when §6 lands.)

`common/starnet.toml:26` (`after = "palette.*"`), `post/merge_stars.toml:33`,
`common/thumbnail.toml:23`, `common/crop.toml:29` and `graxpert/background.toml:26`
reference no role member and stay untouched.

Resulting behaviour:

| rc-astro installed? | deblur | denoise | palette |
|---|---|---|---|
| yes | `blur_exterminator` | `noise_exterminator` | runs after them |
| no | `deconv-obj` | `denoise` | runs after them (**new**) |
| (neither tool) | — | — | skipped (as today) |

The middle row is the behaviour §3.4's decision buys: the GraXpert stages are no
longer excluded by default, so a user without rc-astro gets the whole palette
immediately instead of having to enable two stages first.

## 6. Generalized `after`: role names or stage names

What authors actually want to say is *"run me after whatever produced this"*, not
*"run me after this named stage"*. So `after` becomes a **name pattern matched
against both stage names and role names**, with every match resolved to the stage
that will really run:

```python
def resolve(pattern: str) -> list[str]:
    """Stage names that will run, for an `after` pattern."""
    result = set()
    for name in (*selected_names, *dropped_names, *role_names):   # both namespaces
        if re.fullmatch(pattern, name):
            result.add(canonical(name))    # via the map described below (§4.3)
    return sorted(result)

# canonical(): the stage that will actually produce the output
#   selected stage name  -> itself
#   dropped stage name   -> the winner of *its* role (loser -> winner redirect)
#   role name            -> the winner of that role
#   a name that is both a stage and a role is matched in both namespaces;
#     its canonical forms dedup to a single provider
```

| `after` | situation | resolves to |
|---|---|---|
| `"denoise"` | rc-astro installed | `["noise_exterminator"]` (role) |
| `"denoise"` | rc-astro absent | `["denoise"]` (stage is the winner) |
| `"noise_exterminator"` | rc-astro absent | `["denoise"]` (loser → winner redirect) |
| `"(deblur\|denoise)"` | rc-astro installed | `["blur_exterminator", "noise_exterminator"]` — one regex, two roles, no implementation names |
| `"deconv-obj.*"` | rc-astro installed | `[]` → consumer skipped, as today |
| `"background.*"` | either | `["background"]` (no role involved) |
| a typo, e.g. `"denois"` | either | `[]` → consumer skipped, as today |

Rules:

* **Union, not precedence.** A pattern matching a role name *and* stage names
  yields every canonical provider (deduped) rather than one winning namespace, so
  behaviour stays explainable. This is not hypothetical: the role `denoise` has the
  **same name as the GraXpert stage `denoise`** (`graxpert/denoise.toml:7`), so
  `after = "denoise"` really does match both namespaces and canonicalisation is what
  makes it safe — rc-astro present: the stage is dropped → its role's winner →
  `noise_exterminator`; rc-astro absent: the stage *is* the role winner → itself. One
  provider either way. `deblur` collides with nothing. Prefer a distinct role name
  when there is a choice, but note the shared name reads naturally here and the
  dedup means it needs no special case.
* **Empty resolution changes nothing.** No edge in `sort_stages()`, and
  `NoPriorTaskException` skips the consumer — so a role with no candidate removes
  its consumers exactly as `_remove_missing_tool_tasks()` removes a missing tool's
  stages today, and a typo keeps behaving as it always has.
* **Resolution never invents a stage.** Names come from the catalog, so this is not
  a way to reference a stage no repo provided.
* **Existing recipes are unaffected.** Adding the role namespace can only change a
  resolution where a pattern matches a role name, and no `after` in the catalog does.
  The distinct values today are `noise_exterminator` (6), `background.*` (2),
  `light.*` (2), `deconv-obj.*`, `blur_exterminator`, `crop`, `palette.*`,
  `stack_osc`, `stack_.*`, `stack_(single|dual)_duo`, `seqextract_haoiii`,
  `veralux.*` and `(veralux|merge_stars).*` — none matches `deblur` or `denoise`
  under `fullmatch`, and none is even a *prefix* of either name (the looser rule
  `_get_prior_tasks()` uses). The only affected references are the six palette lines
  of §5, which are changed deliberately.
* Authors should prefer the **role name** (`after = "denoise"`): it names the
  capability, survives a tool swap, and reads as intent. Stage names keep working
  (they are canonicalized to the winner), which is what lets a stage-specific or
  legacy reference stay valid.

Implementation is §4.3 (one `resolve()`, two consumers), and it is Phase 1 work:
generalizing the clause *before* touching the recipes avoids editing the six
palette lines twice. The interim regex of §5 is the fallback if it is felt too
risky to land at once (§10 step 2).

### 6.1 Alternatives considered

* **Broadened regexes only** — `after = "(noise_exterminator|denoise)"`. Works, and
  is the documented fallback, but leaks implementation names into consumers: every
  new implementation and every new role means editing them again.
* **Redirect only, without role-name matching** — the same plumbing minus the role
  namespace. A reference silently retargets to a stage the author never named, and
  roles stay invisible in the recipes: strictly less useful for the same code.
* **Select roles after task creation**, dropping loser *tasks* (§2). Rejected: the
  downstream stages that already consumed the loser keep its dead branch, and the
  palette attaches to the wrong producer.

## 7. Decisions taken

Both questions that gated Phase 1 were settled on 2026-09-14 (details and the
rejected alternatives below): the `priority` direction, and what happens to a stage
that is only excluded *by default*.

### 7.1 `priority` direction (decided — Option A, higher wins)

**Decided 2026-09-14: Option A.** The code's existing rule stands (`reverse=True` at
`stages.py:96`/`:117`, i.e. a *higher* number is scheduled earlier **and** wins a
role), and `doc/toml/guide.md:157` is corrected instead — it is the only place that
says "lower runs earlier". Rationale: zero behaviour change, no recipe renumbering,
and no risk to the conflicting-output resolver (§11). Option B stays below as the
record, and as the path back if "lower = earlier" is ever wanted everywhere.

Three sources disagreed about the direction (which is why role selection needed it
settled — it must agree with `sort_stages()`):

| source | rule |
|---|---|
| `sort_stages()` (`stages.py:96`, `:117`, `:127-131`, `reverse=True`) + `tests/unit/test_processing.py:313` ("highest first") + `doc/design/report.md:712` ("`priority` above 330 so ordering is guaranteed") + recipe numbers (osc 310 < single 320 < dual 330, report 340) | **higher = scheduled earlier / wins — the decision** |
| `doc/toml/guide.md:157` ("lower runs earlier") | lower = earlier — the doc that is wrong and gets fixed |
| the original request ("lower numbers mean higher pri") | lower = higher — considered, then rejected |

The direction is settled (above), so role selection simply follows `sort_stages()`.
Worth knowing for Option B's record: the stackers **do** conflict:
`stack_single_duo` and `stack_dual_duo` both write `stacked_Ha.fits`/`stacked_OIII.fits`,
and `preflight_tasks()` keeps `conflicting_stages[0]` — i.e. today `dual_duo` (330)
beats `single_duo` (320).

* **(A) Keep the code's rule; use higher-wins for roles too. — CHOSEN.** Zero
  behaviour change, no recipe renumbering; `guide.md:157` fixed instead. (The
  wording of the original request was "lower = higher priority"; the decision went
  the other way because the code, the tests, `doc/design/report.md:712` and four
  recipes' numbers all already agree on higher-wins, and flipping them is the larger
  and riskier diff.)
* **(B) Adopt "lower = higher priority" everywhere. — rejected (record).** Would flip `sort_stages()`
  to ascending, update its docstring and `test_tasks_to_stages_sorted_by_priority`,
  and renumber the four recipes that rely on descending order:
  `osc/stack_dual_duo.toml:16` 330 → **310**, `osc/stack_osc.toml:11` 310 → **330**
  (the swap keeps the conflict winner *and* the creation order
  `dual, single, osc` identical to today), `osc/report_registration.toml:13,43`
  340 stays but now means "runs late" rather than "immediately after stacking"
  (benign: the `.seq` it reads is a tracked job output,
  `osc/stack_osc.toml:59-65`), and `master/dark.toml:12` 2000 becomes the
  lowest-priority master stage (verify nothing asserts master ordering, else
  renumber). Larger diff, but it makes the documented rule true and matches the
  near-universal convention.

### 7.2 Roles do not fall back to a default-excluded stage (decided — drop the flag)

**Decided 2026-09-14: option (c) — `exclude_by_default` is removed.** With roles in
place the flag has no job left: it hid the slow GraXpert stages from *everyone* to
spare the users who have rc-astro, at the price of also hiding them from the users
who don't (who then lost the whole palette). Role selection expresses the same
preference without that side effect. The three options were:

* **(a) Leave the flag as a candidate exclusion — rejected.** Makes the plan's
  headline behaviour opt-in: a user without rc-astro gets no palette until they find
  the checkbox. An exclusion is also the wrong shape for "use this only if the
  better one is missing".
* **(b) Let a default-excluded stage win a role *if it is the only candidate* —
  rejected.** Needs provenance on the persisted entry (`excluded_by = "default" |
  "user"`), because `upsert_stage()` writes only `name` + `excluded`, so a recipe
  default is indistinguishable from a user's own choice — and it inverts the
  intended meaning: a stage the recipe marked "not by default" is exactly the one
  that *should* be the automatic fallback.
* **(c) Drop `exclude_by_default` from the recipes. — CHOSEN.** The GraXpert stages
  become ordinary role candidates: their `priority` loses to rc-astro's, so nothing
  changes when rc-astro is installed, and they run when it is not — precisely the
  fallback this plan exists for (§5's behaviour table). Every cost lands in §3.4,
  including the one caveat that an already-persisted `excluded = true` is *not*
  retroactively cleared.

The submodule's two uncommitted hunks (the flags commented out) are option (c) half
applied; Phase 1 turns them into deletions and removes the rest of the feature (§3.4).
`excluded` itself stays — that is the user's own toggle, and the GUI Targets checkbox
keeps writing it.

## 8. Observability

* One `INFO` log line per dropped stage (§3) — the run's log tail already shows it.
* **Role-driven skips should say why.** Today a missing `after` is only
  `DEBUG`-logged ("Skipping stage 'palette_sho' - Could not find prior task …",
  `:1304-1305`). When the pattern names a *role* that resolved to nothing, raise
  that to `INFO` with the role named ("no available stage implements role
  'denoise'; skipping 'palette_sho'") — rare, actionable, and the only way a user
  learns that the palette is missing, and why.
* `DEBUG`-log each resolution (`after 'denoise' -> ['noise_exterminator']`) so a
  recipe author can see what a pattern did without reaching for a debugger.
* Phase 1: losers simply do not appear in the run tree (`set_run_stages()` is fed
  the tasks of selected stages only), which matches "only one of them should be
  used" but leaves the GUI Targets page showing a toggle for a stage that will not
  run. Acceptable short term; see Phase 2.
* Phase 2: `StageNode` (`run_state.py:185-198`) gains `role` (+ the winner name),
  the run tree shades a role group, and `pages/targets.py` groups its stage list
  by role, marking losers as *unused — role 'denoise' handled by
  'noise_exterminator'*.

## 9. Testing strategy

New `tests/unit/test_stage_roles.py` (pure, no Qt/DB) for `select_stages()`:

* one role member → unchanged; two members → best priority wins, loser in
  `dropped` with a useful reason, and a `caplog` assertion on the message;
* a member whose tool is unavailable loses even if it has the better priority
  (the whole point of the feature);
* `disabled = true` removes a stage (with and without a role);
* an excluded stage is not a candidate;
* equal priorities → deterministic (earlier catalog order wins, the stable-sort
  rule of §3), asserted twice;
* stages with no role are never dropped;
* direction: a test that pins the chosen §7.1 rule (so a future flip is deliberate).

Pipeline-level (`tests/unit/test_processing.py`, alongside
`TestRemoveMissingToolTasks:920`, using the same `Processing.__new__` +
`monkeypatch.setattr("starbash.processing.tools", …)` style):

* with rc-astro marked unavailable, the isolated selection step chooses
  `deconv-obj`/`denoise`; with it available, `blur_exterminator`/
  `noise_exterminator`;
* a kept downstream stage whose `after` names a role (or names the dropped
  member) attaches to the **winner's** tasks — assert on the resulting task graph
  (`file_dep`/upstream task names), not on a mock call.

`StageSelection.resolve()` and the generalized `after` (pure, same module):

* role name → the winner; a dropped stage name → the winner's name; a pattern
  matching live *and* role names → the deduped union (assert the real instance,
  `denoise`, from §11: exactly one provider, not two); a pattern matching nothing →
  `[]`; an empty selection → `[]` rather than a crash;
* `sort_stages(resolve=…)`: a consumer `after` a role lands on the winner, and
  `resolve=None` reproduces today's edges exactly (the existing
  `tests/unit/test_tool.py` sort tests are the guard);
* `_get_prior_tasks()` with a role-named `after`: the prior task is the winner's
  task for the current session, the multiplex prefix still collects every index,
  and with `_stage_selection = None` the produced pattern is byte-identical to
  today's — including the alternation case the slicing hack at `:1035-1037`
  exists for.

Recipe wiring (`tests/unit/test_report_registration.py` is the closest existing
precedent for asserting recipe content; `conftest.py:78-97` forces the local
`starbash-recipes` submodule, so the files are readable in tests):

* the four stages declare the expected `role`/`priority` (`300` for both GraXpert,
  `350` for both rc-astro — so rc-astro wins, §5), and the two `exclude_by_default`
  lines are gone (§3.4);
* every `after` referencing a role member resolves for **both** branches
  (parameterise over "rc-astro present/absent").

Then the usual gate: `just lint` (it rewrites files — re-run the tests after) and
`poetry run pytest -q`, plus a manual `sb process auto` on a duo target with
rc-astro hidden to confirm the GraXpert branch really produces `SHO.fits`.

## 10. Phased sequence

1. ~~**Decide §7.1 and §7.2**~~ — **done 2026-09-14**: higher `priority` wins
   (§7.1 Option A) and `exclude_by_default` is removed (§7.2 option c). Recipe work
   is unblocked.
2. ~~**Phase 1**~~ — **landed 2026-09-14** (see the table at the top of this file
   for the exact code/test locations). The mechanism: `select_stages()` + `disabled`
   (§3.1) + `StageSelection.resolve()` and the generalized `after` (§4.3, §6) in
   `sort_stages()`/`_get_prior_tasks()`, the `_job_to_tasks()` call site, the four
   recipes (`role` + `priority` + the `exclude_by_default` deletions, §5), the six
   palette references, **the `exclude_by_default` removal itself** (§3.4: the
   `_set_default_stages()` read at `processed_target.py:617`, the tests at
   `tests/unit/test_processed_target.py:256-269`/`:350-373`, the
   `doc/design/new-params.md:159` mention), the guide (`role` row in §4's table,
   quick reference, a §4.x note on role selection, the note that `after` matches
   roles, and `doc/toml/guide.md:157` corrected to "higher runs earlier" per §7.1)
   and the tests of §9.
   *Optional de-risking split:* land `select_stages()` with the palette regexes
   broadened, verify a GraXpert-only run, then switch the palette to
   `after = "denoise"` once the `after` work is in. Costs one throwaway edit, buys
   a working intermediate state — useful if the `after` change needs its own review
   round. **Not taken** — the `after` work landed with the rest, so the palette went
   straight to `after = "denoise"`.
3. Phase 2 — `role` in `StageNode`, run-tree/GUI grouping, per-session role
   resolution (§3.3), and the first *non-fallback* roles (`background`, `palette`,
   `auto-stretch`) once the mechanism has run in anger.
4. Phase 3 (optional) — *was* §7.2 option (b)'s `excluded_by` provenance; it died
   with that decision, so it stays only as a marker: if a "run me only when nothing
   better exists" notion is ever wanted again, that is the shape to revive.

## 11. Risks

* `_get_prior_tasks()` is delicate (regex + suffix + multiplexing). The
  no-selection path must stay byte-identical and be covered before *and* after the
  change; the alternation case at `:1035-1037` is the one to write first.
* **Role names colliding with stage names.** Phase 1 has one deliberate collision:
  `denoise` is both the role and the GraXpert stage name
  (`graxpert/denoise.toml:7`). §6's union + canonicalisation makes it resolve to
  exactly one provider per branch, but it is the subtle path, so §9 asserts it
  directly (`after = "denoise"` with rc-astro present must resolve to
  `["noise_exterminator"]` alone, *not* both names). `deblur` collides with nothing,
  and no other existing `after` pattern matches either role name, so Phase 1 changes
  no other ordering — if that stops being true, the union rule is the thing to
  re-examine.
* A role whose winner cannot resolve inputs for a target yields nothing: there is
  **no second-chance fallback** to the runner-up (selection is availability +
  priority only). If that bites, a bounded retry in `_job_to_tasks` (rebuild tasks
  with the winner removed when a role winner produced zero tasks) is the escape
  hatch; deliberately out of scope here.
* Flipping `priority` (the rejected §7.1 Option B) would touch the conflicting-output
  resolver, whose winner is `conflicting_stages[0]`; the stacker renumbering would
  have to land in the same change or `stack_single_duo` quietly starts beating
  `stack_dual_duo`. Not in scope now that Option A is chosen — recorded so the
  decision is not re-litigated by accident. The inverse risk of Option A: the new
  `priority = 350` / `300` values are the only thing that makes rc-astro beat
  GraXpert, so §9 asserts them.
* `starbash-recipes` is a submodule with **two uncommitted local hunks** today
  (`exclude_by_default` commented out in `graxpert/deconv-obj.toml:9` and
  `graxpert/denoise.toml:9`; HEAD has them enabled). §7.2's decision makes those
  hunks the right intent in the wrong form: Phase 1 **deletes** both lines, so the
  recipe edits build on that rather than on HEAD. The submodule is committed
  separately — **by the human** (`.clinerules/collaboration.md`).
