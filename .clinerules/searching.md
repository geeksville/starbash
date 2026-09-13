
## Code Search

**Default tool: `semble`, accessed through its MCP server.** Use the MCP tools
`semble__search` and `semble__find_related` — they are auto-approved (no
confirmation prompt) and share the exact index the CLI uses. Only fall back to
the `poetry run semble ...` CLI when the MCP tools are not available to you
(some clients/agents do not expose MCP) — see *CLI fallback* below. Never use
`uvx` or a bare `pip install` (see *Build / test / run* above).

The server is configured as `poetry -C /workspaces/starbash run semble` with
`search`/`find_related` auto-approved, so the MCP call is the cheap path.

Use it to find code by describing what it does, or by naming a symbol/identifier,
instead of grep. `semble__search` parameters:

| Parameter | Meaning |
|---|---|
| `query` | What the code does, or a symbol/identifier name |
| `repo` | A path or git URL to index. Pass `.` for this repo's root, or `src` / `tests` to scope |
| `top_k` | Number of results; default 5, widen with 10+ |
| `content` | `code` (default), `docs` (prose), `config` (TOML/YAML), `all` |
| `max_snippet_lines` | Lines of source per hit; default 10 (signature + first body lines), `0` for path/line only, `null` for the full chunk |

```text
semble__search(query="where sessions are aggregated", repo=".")         # describe behaviour
semble__search(query="get_column_name", repo="src")                     # name a symbol
semble__search(query="stage exclusion", repo="src", top_k=10)           # widen results
semble__search(query="safe formatter", repo="src", max_snippet_lines=5) # shorter output
semble__search(query="how releases are cut", repo=".", content="docs")  # prose
semble__search(query="repo precedence", repo=".", content="config")     # TOML/YAML
semble__search(query="processing pipeline", repo=".", content="all")    # everything
```

The index is built on first run (and cached for subsequent runs) and invalidated
automatically when files change.

Use `semble__find_related` to discover code similar to a known location — pass
the `file_path` and `line` from a prior `semble__search` result (its other
parameters mirror `semble__search`):

```text
semble__find_related(file_path="src/starbash/app.py", line=270, repo="src")
```

**Prefer scoping to `src` / `tests`.** The first run indexes whatever tree you
point at; scoping keeps it fast and keeps large non-source trees (`reference/`,
`test-data/`, `starbash-recipes/`) out of the index. `file_path` in the JSON
results is relative to the `repo` path you passed.

### CLI fallback

When the MCP server is not reachable, the CLI is the same dev dependency and the
same index — only the invocation differs (shell flags instead of structured
arguments):

```bash
poetry run semble search "where sessions are aggregated"          # describe behaviour
poetry run semble search "get_column_name"                        # name a symbol
poetry run semble search "stage exclusion" src                    # scope to the package
poetry run semble search "fixture setup" tests                    # scope to the tests
poetry run semble search "stage exclusion" --top-k 10             # widen results
poetry run semble search "safe formatter" --max-snippet-lines 10  # shorter output
poetry run semble search "how releases are cut" --content docs    # prose
poetry run semble search "repo precedence" --content config       # TOML/YAML
poetry run semble search "processing pipeline" --content all      # everything
poetry run semble find-related src/starbash/app.py 270
```

`path` defaults to the current directory (the repo root), so you can omit it. The
`./my-project` argument in semble's upstream docs is a placeholder — never copy it
into a command here. `--top-k N` widens results; `--max-snippet-lines N` shortens
output.

If `semble` is missing it is a dev dependency: run `poetry install --with dev`
(or `poetry run semble ...`). Do not reach for `uvx` or a bare `pip install`.

### Choosing a tool (read this before reaching for `grep`)

| You need… | Use |
|---|---|
| "where is X handled / what does this do" | `semble__search(query="<description>", repo=".")` |
| a symbol by name (`get_column_name`, `class Tool`) | `semble__search(query="<symbol>", repo="src")` |
| **every** occurrence of a literal string repo-wide (rename/migration sweep) | `grep -rn` (bounded — see *Workspace search safety*) |
| a structural outline of one already-known file (list its `def`s) | read the file, or `grep -n '^\s*def ' <file>` |
| a literal/regex sweep semble keeps missing | `grep -rn` or the `search_codebase` tool |

Rules of thumb:

1. Start with `semble__search` for anything semantic or symbol-shaped.
2. Navigate straight to the returned `file:line` — don't re-search or re-grep for the same content.
3. `grep` is for the two carve-outs above *only*: an exhaustive literal sweep, or outlining a single file you already know.
4. When in doubt, `semble` first — it's ranked, quieter, and won't dump huge generated output.
5. Keep sweeps out of `.venv/`, `reference/`, `test-data/`, and image trees.
6. If the MCP tools are unavailable, use the CLI fallback above — not grep.

### Workflow

1. `semble__search` first — for anything semantic or symbol-shaped.
2. Use `content="docs"` for prose, `content="config"` for TOML/YAML, `content="all"` for everything.
3. Navigate directly to the returned `file:line` — do not re-search or `grep` for the same content.
4. `semble__find_related(file_path=..., line=...)` to find sibling implementations.
5. `grep` only for an exhaustive literal sweep (e.g. every caller of a renamed
   function) or to outline a single already-known file — never for semantic/symbol lookups.

## Workspace search safety

- Do not run unrestricted recursive `grep` or similar searches in data-heavy
  directories such as `private/`, processed-image trees, caches, or build
  outputs. These directories can contain very large FITS, image, database, and
  log files and searches may take an excessive amount of time.
- When searching those directories, restrict the search to the relevant text
  file types (for example `*.toml`, `*.py`, `*.md`, or explicitly selected log
  extensions) and scope the search to the smallest useful subtree.
- Prefer targeted file listing and inspection over searching binary or large
  generated files.

