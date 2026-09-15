# Plan: one canonical `file://` URL spelling

> **Status:** Implemented (2026-09-15) — pending the `toml-repo` release decision in §7
> **Owner:** Kevin Hester
> **Last updated:** 2026-09-15
> **Scope:** Make every `file://` URL Starbash builds use one canonical spelling,
> across both the starbash repo and the `toml-repo` submodule.
> **Related:** `gui-github-publish.md` (site upload ordering).

## 1. Goal / summary

A repository — and every file Starbash indexes from it — is identified by its
`file://` URL. That string is written into the user config (`[[repo-ref]]`), the
SQLite `repos`/`images` tables and `sessions.toml`, and it is compared for
equality (e.g. "is this repo removable?"). So every producer and consumer must
agree on **exactly one** spelling.

There were two, and the wrong one was everywhere:

```python
f"file://{path}"            # hand-built -- wrong
path.as_uri()               # canonical   -- right
```

On POSIX the two coincide by luck (an absolute path starts with `/`). On Windows
they do not, and the hand-built form is not merely ugly — it is
*unparseable-as-intended*:

| path | hand-built | canonical (`as_uri()`) |
|---|---|---|
| `C:\Users\me\lights` | `file://C:\Users\me\lights` | `file:///C:/Users/me/lights` |
| `C:\Users\me\lights` (quoted) | `file://C%3A%5CUsers%5Cme%5Clights` | `file:///C:/Users/me/lights` |
| `\\server\share` | `file://\\server\share` | `file:////server/share` |

In the hand-built form the filesystem path lands in the URL **authority** (the
`host` position), so anything that reads `url[7:]`, or `QUrl`, or
`urllib.parse.urlsplit` silently gets a different — usually relative — path. The
user-visible symptoms were master/output links in the GUI Targets page that would
not open, and (after the repo-URL half of this change) a Windows repo recorded by
an older version showing as not removable.

## 2. Approach

1. **`toml_repo` owns the spelling** (new `toml_repo/urls.py`:
   `make_file_url()` / `path_from_file_url()`), because `toml_repo` is the library
   that must *parse* these URLs back into paths and build them internally. If the
   two sides disagreed, a repository Starbash recorded would be unreadable when
   reloaded.
2. **`starbash.url` re-exports them** (`make_file_url`, `path_from_file_url`) so
   Starbash code has one obvious import and the two can never drift.
3. **Every hand-built URL and every `url[len("file://"):]` slice is replaced** in
   both repos.
4. **No legacy tolerance.** The old spelling is *refused* (`ValueError`), not
   translated: `file://C:\dir` is indistinguishable from a URL host, and reading
   it as a UNC share would resolve a real path to something that does not exist.
   A repository recorded by an older Starbash therefore has to be re-added and
   re-indexed (the owner will recreate the databases).

### Where the parsing rules live, and why

| URL | parsed as | note |
|---|---|---|
| `file:///home/me/x` | `/home/me/x` | POSIX |
| `file:///C:/x` | `C:/x` | the drive is a **path segment** on Windows |
| `file:////server/share` | `//server/share` | what `as_uri()` writes for a UNC path |
| `file://server/share` | `//server/share` | hand-written UNC; both spellings must agree |
| `file://localhost/x` | `/x` | a host naming this machine is not a host |
| `file:///C%3A/x` | `/C:/x` | a POSIX directory genuinely named `/C:` |
| `file://C:\x`, `file://C:/x` | **`ValueError`** | the legacy form |

The drive-letter test is applied to the **still-encoded** path precisely so that
a POSIX `/C:` directory (whose colon `as_uri()` percent-encodes to `%3A`) is not
mistaken for a Windows drive.

## 3. Files changed

### `toml-repo` (submodule)

| File | Change |
|---|---|
| `src/toml_repo/urls.py` | **new** — canonical helpers, rule documented in the module docstring |
| `src/toml_repo/__init__.py` | exports `make_file_url`, `path_from_file_url` |
| `src/toml_repo/repo.py` | the two hand-built URLs (`Repo(path)` in `__init__`, and `add_from_ref`'s provider URL) plus the three `url[len("file://"):]` slices in `write_config()` / `get_path()` / `_read_file()` |
| `tests/test_urls.py` | **new** — Windows drive/UNC/localhost/legacy-refusal, parsed from strings so it runs on Linux |
| `tests/test_repo_manager.py`, `tests/test_repo_imports.py` | build URLs with the helper; the cross-repo import test no longer embeds the legacy form |

### `starbash`

| File | Change |
|---|---|
| `src/starbash/url.py` | re-exports both helpers; module docstring states the rule |
| `src/starbash/app.py` | three repo-URL producers (`_install_local_recipes`, the preferences repo, `_find_user_repo_ref`) |
| `src/starbash/doit.py` | `FileInfo.rich_links` clickable outputs |
| `src/starbash/publish/github_publish.py` | `collect_site_files()` sorts by the site-relative **posix** path |
| `src/starbash/ui/qt/widgets/{hover_preview,file_links}.py` | hand-sliced `file://` replaced by the strict parser |
| `pyproject.toml` | `toml-repo` dependency source — see §7 |
| tests | `test_url.py`, `test_doit.py`, `test_app.py`, `test_cli.py`, `test_selection.py`, `test_repo_manager.py`, `test_repositories_page.py`, `test_github_publish.py` |

## 4. Implementation sequence

1. Canonical helpers + tests in `toml-repo` (§3), so both repos share one rule.
2. `toml_repo` consumers switched to them (5 sites).
3. `starbash.url` re-export; `doit.py` + `github_publish.py`.
4. `app.py` repo-URL producers and the `_find_user_repo_ref` comparison (which
   now accepts *either* the recorded directory path *or* the canonical URL, since
   the CLI passes user input while the GUI passes `repo.url`).
5. GUI hover/link parsers switched to the strict parser.
6. Tests updated from `f"file://{p}"` to `make_file_url(p)` everywhere.

## 5. Testing strategy

* `toml_repo/tests/test_urls.py` parses Windows URLs as **strings**, so the
  Windows rules are verified on Linux CI — the only way they get exercised here.
  It includes the round-trip property and the refusal of the legacy form.
* `tests/unit/test_app.py::test_user_repo_url_is_a_canonical_file_url` pins the
  preferences-repo URL (guards `app.py`);
  `..._legacy_hand_built_repo_url_is_not_removable` pins the no-legacy-tolerance
  decision.
* `tests/unit/test_doit.py::TestFileInfoRichLinks` pins the run tree's links;
  `tests/unit/test_url.py` pins the helper; `test_github_publish.py` pins the
  platform-independent site order.
* Gates: `just lint` (ruff **and** basedpyright) then `poetry run pytest -q`, in
  both repos. Windows CI (`windows-latest`) remains the real Windows gate.

## 6. Risks

* **Cross-repo consistency is now load-bearing.** Starbash's canonical URLs and
  `toml_repo`'s parser must ship together — the Windows failure mode is a repo
  whose URL changes spelling between write and read (not removable / not found).
  This is why the dependency source in §7 matters.
* Any *other* producer of `file://` URLs (a hand-written
  `[[repo-ref]] url = "..."`, an old config) that still uses the legacy form is
  now refused loudly rather than silently misread. That is intended — use
  `sb repo add` rather than hand-editing URLs.

## 7. Open question (needs the maintainer's decision)

`starbash` must consume the *updated* `toml_repo`, which is not on PyPI yet
(0.1.6 == the submodule HEAD before this change). Options:

| # | Option | Consequence |
|---|---|---|
| A | `toml-repo = {path = "toml-repo", develop = true}` (**current state**) | dev/CI green now. `poetry build` emits `Requires-Dist: toml-repo @ file:///…`, so **this must be reverted before any PyPI publish** — the workflows do check out submodules, but a path dep cannot be published. |
| B | Release `toml-repo` 0.1.7, then `toml-repo = ">=0.1.7"` | cleanest; needs a release in the other repo before starbash CI can pass. |
| C | Keep `>=0.1.6` and make `starbash.url` self-contained | no dependency change, but leaves `toml_repo` building legacy provider URLs on Windows → the repo-removal mismatch returns. Not recommended. |

`pyproject.toml` carries a `NOTE:` describing the revert-to-version-constraint
step for whichever option is chosen.