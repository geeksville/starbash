# Plan: missing-tool warnings (severity, ignore, GUI bars)

## Goal & summary

When Starbash cannot find an external tool it should say so **once, in the user's
own terms**: how important the tool is, what to do about it, and a way to stop
being told (for tools the user simply does not use). Today there are three
different ways to say "this tool is missing" (Rich markup in the CLI, an ad-hoc
warning in the GUI, nothing at all for most tools), and no way to dismiss any of
them.

This plan introduces a single core model - `ToolSeverity` + `ToolStatus` - and
renders it in both front ends from the same source of truth:

- **Core** (`tool/base.py`, `tool/__init__.py`): each tool declares a severity;
  `Tool.status()` reports availability; `missing_tool_statuses()` gives the front
  ends a ready-sorted list; `Tool.preflight()` logs at a level matching severity.
- **GUI** (`ui/qt/widgets/tool_warning.py`): a stack of dismissible warning bars at
  the top of the main window, one per missing tool, with an *Install* link and - for
  anything that is not required - an *Ignore* button that persists
  `tool.<key>.ignored` to the user config.
- **CLI**: unchanged in shape (a startup log line), but now severity-driven, so an
  optional tool is only a debug line instead of a warning.

Rationale: the front ends should never re-implement a tool probe or re-word a tool
message. Everything the user needs is a field on `ToolStatus`.

## Approach

### Severity model (core)

```python
class ToolSeverity(enum.IntEnum):   # ordered, so `<` is meaningful
    OPTIONAL = 0
    RECOMMENDED = 1
    REQUIRED = 2
```

`IntEnum` (not `StrEnum`) because the ordering *is* the semantics: "may this
warning be dismissed?" is `severity < ToolSeverity.REQUIRED`, and "most important
first" is a plain reverse sort.

Assignment across the registry:

| Tool | Severity | Why |
|---|---|---|
| Siril | `REQUIRED` | nearly every recipe stacks with it |
| StarNet | `RECOMMENDED` | stellar processing is a common but optional step |
| GraXpert | `OPTIONAL` | (built-in variant ships with Starbash) |
| Python | `OPTIONAL` | built-in sandbox |
| rc-astro | `OPTIONAL` | paid add-on |

### Honest probes (why StarNet needed one)

A probe must not call a tool available because the *configuration* looks right -
it has to check that the thing the configuration names actually exists.  StarNet
is the case that bit us: availability was "`starnet_exe` is non-empty in Siril's
own config", and Starbash **writes that value itself** when it finds `starnet2` on
the PATH.  So installing StarNet and later removing the binary left a setting
naming a deleted file, `is_available` stayed `True`, and *neither* front end
warned: an invisible failure, which is exactly what this feature exists to
prevent.

`starnet._starnet_exe_usable()` therefore resolves the setting the way Siril
would - a bare name is looked up on the PATH, an explicit path must still exist -
and a stale path counts as missing.  `missing_message()` names the dead path
instead of telling the user to configure something Siril already has configured:

> StarNet is configured in Siril as `/usr/bin/starnet2`, but that file no longer
> exists.  Point Siril at your StarNet install (Preferences > Miscellaneous) ...

Starbash never rewrites a non-blank `starnet_exe`: auto-configuration fills in a
blank one only, so repairing a stale value stays the user's decision - the
warning just tells them how.

**Which config file is read (or written).**  Siril has two possible config homes,
because a flatpak app cannot see `~/.config`: a native (distro/AppImage) install
uses `~/.config/siril`, the flatpak app uses the config home inside its sandbox,
`~/.var/app/org.siril.Siril/config/siril`.  `StarnetTool._siril_config_dirs()`
returns both, putting the one belonging to the Siril Starbash would run first
(`_siril_is_flatpak()`: the app id in the resolved executable, or in a
`siril.path` override).  `_starnet_configured()` **scans every directory** - a
dead path in one install must not hide a working setting in the other - while
auto-configuration writes only into the live directory's newest
`config.<version>.ini`, since a setting written into the other install's file may
never be read.  Before this, only `~/.config/siril` was consulted, which is why
StarNet went undetected on Linux, where Siril is usually the flatpak.

### `ToolStatus` (core)

A frozen dataclass carrying everything a UI needs: `name`, `key`, `severity`,
`available`, `install_url`, `ignored`, `detail`. Derived properties:

- `needs_attention` - missing *and* not ignored (the single predicate both front
  ends filter on);
- `can_be_ignored` - `severity < REQUIRED`;
- `summary` - first line of `detail`, run through `plain_message()`, for compact
  widgets (the full text is long and written for a console).

`plain_message()` converts the one piece of Rich markup our tool messages use
(`[link=URL]here[/link]` → `here (URL)`, dropping stray link tags) so non-console
targets - Qt labels, tooltips, log files - never show markup.

### Registry helpers (core)

`tool_statuses()` (all, registry order), `tool_status(key)`, and
`missing_tool_statuses(*, include_ignored=False)` (missing, most important first;
`include_ignored=True` is the diagnostics view). `set_tool_ignored(key)` updates
the in-memory preferences only - persisting is the caller's job, which keeps the
tool module free of repo knowledge.

### GUI surface

`ToolWarningPanel` (a `QVBoxLayout` of `ToolWarningBar`) sits above the nav rail
and page stack, so warnings are visible from any page, and hides itself when there
is nothing to report (`refresh()` rebuilds from `missing_tool_statuses()`, so a bar
disappears as soon as its tool is installed or ignored).

Each `ToolWarningBar` shows: a severity badge (`REQUIRED`/`RECOMMENDED`/`OPTIONAL`),
`<Name> was not found`, the one-line `summary`, a *How to install* button (only when
the tool has an `install_url`), and an *Ignore* button (only when
`can_be_ignored`). The full explanation stays reachable as the label's tooltip.
Severity picks the colours through a `severity` **dynamic property** set on both
the frame and the badge - Qt selectors cannot read a parent's property.

Persisting the ignore is `MainWindow._on_ignore_tool`: `user_repo.set(
"tool.<key>.ignored", True)` + `write_config()`, then `set_tool_ignored(key)` in
memory. A write failure keeps the bar and reports the error to the status bar
rather than pretending the choice stuck. Because it lands in the same user config
the CLI reads, ignoring a tool also silences the CLI's startup warning.

The bar reports clicks as signals (`ignored`, `status`); it owns no persistence,
matching the codebase's "core publishes, observers render" split.

## File & component layout

| File | Change |
|---|---|
| `src/starbash/tool/base.py` | `ToolSeverity`, `ToolStatus`, `plain_message`, `Tool.severity`/`key`/`is_ignored`/`missing_message`/`status`/`preflight` |
| `src/starbash/tool/__init__.py` | `tool_statuses`, `tool_status`, `missing_tool_statuses`, `set_tool_ignored`; `init_tools` calls `preflight()` |
| `src/starbash/tool/{siril,starnet,graxpert,rcastro,python}.py` | declare `severity` (+ `install_url`), move wording into `missing_message()` |
| `src/starbash/ui/qt/widgets/tool_warning.py` | **new** - `ToolWarningBar`, `ToolWarningPanel` |
| `src/starbash/ui/qt/main_window.py` | central widget becomes a column: warnings above nav+stack; `warnings` property; refresh on context load; `_on_ignore_tool` |
| `src/starbash/ui/qt/theme.py` | QSS for the bar frame, stripe, badge and title |
| `src/starbash/templates/userconfig.toml` | document `tool.<key>.ignored` |
| `tests/unit/test_tool.py` | `TestToolSeverity` - ordering, registry tagging, status, ignore, sorting, preflight levels |
| `tests/unit/test_tool_warning.py` | **new** - bar/panel rendering, install click, ignore, refresh, empty panel, `plain_message` |
| `tests/unit/test_gui.py` | end-to-end - bars appear; *Ignore* writes the config and drops the bar |

## Phases

0. **Core model** - `ToolSeverity`/`ToolStatus`/`plain_message`; tag every tool;
   `status()`/`preflight()`; registry helpers. Tests in `test_tool.py`.
1. **CLI** - `init_tools` logs through `preflight()`, so severity decides the log
   level (error / warning / debug).
2. **GUI widget** - `ToolWarningBar`/`ToolWarningPanel` + theme QSS; tests.
3. **Wiring** - panel in `MainWindow`, refresh on context load, `_on_ignore_tool`
   persistence + status-bar feedback; tests.
4. **Docs** - `userconfig.toml` comment; this plan.

## Testing strategy

- Unit (core): enum ordering and labels; each registry tool's severity; a
  fabricated `Tool` subclass (availability under test control) for
  `status()`/`preflight()`; `missing_tool_statuses` sort + ignore filtering with a
  stubbed registry.
- Unit (GUI, `gui` marker, offscreen Qt): panel ordering and visibility; badge,
  title, one-line detail and tooltip; *Ignore* absent for required and present for
  recommended/optional; install click opens the URL (with `QDesktopServices`
  stubbed) and reports status; ignore callback + bar removal; refresh after
  "installing"; `plain_message` link rewriting.
- End-to-end (GUI): a real `MainWindow` with the tools stubbed missing - bars are
  shown, clicking *Ignore* writes `tool.rc-astro.ignored` to the user config (read
  back with `tomllib`) and removes the bar from both the panel and the core report.
- No test opens a real window or runs a real tool; the whole suite stays green with
  `QT_QPA_PLATFORM=offscreen`.

## Risks & open questions

- **Widget lifetime under pytest-qt**: `addWidget` tracks widgets by *weak*
  reference, so a parentless host is garbage-collected mid-test, taking its child
  panel with it. The tests keep an explicit strong reference (see `_KEEPALIVE` in
  `test_tool_warning.py`).
- **Ignore is per tool key, not per severity** - a user who ignores `starnet` still
  sees the Siril error, by design. Should the GUI offer a "don't warn again" for
  *all* optional tools? Not implemented; revisit if it becomes noise.
- **Tool availability is probed per call** (`status()` calls `is_available`), and
  `ToolWarningPanel.refresh()` runs on every context reload. StarNet's probe caches
  its result, so this is cheap; if a future tool's probe shells out, it will need
  the same caching.
- **The Settings page still has no Tools tab** (see `gui.md` §10): re-detecting
  tools and editing `path` overrides is CLI-only. The warning bars deliberately do
  not grow into that.
- **The StarNet probe has a side effect**: when `starnet_exe` is blank *and*
  `starnet2` is on the PATH it writes that path into Siril's config file, so a
  mere availability check mutates the user's Siril settings. It is deliberate -
  a fresh install then just works, and the write is logged - but it arguably
  belongs behind an explicit "configure Siril for me" action rather than inside
  `is_available`. Left as-is when the stale-path check was added: the fix only
  stops Starbash from *trusting* such a value, it does not change when one is
  written.
