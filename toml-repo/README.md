# toml-repo

A TOML-based repository manager for Python applications. Provides precedence-based
configuration merging, cross-file imports, and multi-scheme URL support (`file://`, `pkg://`, `http://`).  You can have trees
of toml (and other data files) with auto resolved links between them.

## Features

- **Multi-scheme repositories** – load TOML configs from local directories (`file://`), Python
  package resources (`pkg://`), or HTTP(S) URLs.
- **Precedence-based merging** – later-added repos override earlier ones; query across all repos
  with a single `get()` call.
- **TOML imports** – `[section.import]` tables let you pull nodes from other files or repos,
  eliminating duplication.
- **Configurable config filename** – defaults to `repo.toml`; call `set_config_suffix()` to use
  any name (e.g. `"myapp.toml"`).
- **Source tracking** – every TOML node is monkey-patched with a `.source` back-pointer to the
  `Repo` that loaded it.
- **HTTP caching** – HTTP repos use `requests-cache` so previously fetched configs work offline.

## Installation

```bash
pip install toml-repo
```

Or with Poetry:

```bash
poetry add toml-repo
```

## Quick start

```python
from toml_repo import RepoManager, set_config_suffix

# Optional: change the filename looked up inside repo directories
set_config_suffix("myapp.toml")

manager = RepoManager()
manager.add_repo("file:///path/to/base-config")
manager.add_repo("file:///path/to/user-overrides")

# Last repo wins
value = manager.get("section.key", default="fallback")
```

### Using `pkg://` URLs

If your application ships default configs as package data you can load them
via importlib resources:

```python
from toml_repo import set_pkg_resource_root

# Tell toml-repo which installed package contains the resources
set_pkg_resource_root("myapp")

manager.add_repo("pkg://defaults")  # reads myapp/defaults/myapp.toml
```

### TOML imports

Inside any TOML file managed by toml-repo you can import nodes from other
files to reduce duplication:

```toml
[repo]
kind = "recipe"

# Import the "base_stage" table from a library file
[my_stage.import]
file = "library.toml"
node = "base_stage"
```

Imports support:
- Same-file references (`node = "some.path"`)
- Cross-file references (`file = "relative/path.toml"`)
- Cross-repo references (`repo = "file:///other/repo"`)
- Recursive resolution (imported files can themselves contain imports)

## API reference

### Module-level configuration

| Function | Description |
|---|---|
| `set_config_suffix(name)` | Set the TOML filename for directory repos (default: `"repo.toml"`) |
| `get_config_suffix()` | Get the current config suffix |
| `set_pkg_resource_root(pkg)` | Set the Python package for `pkg://` URL resolution |

### `RepoManager`

| Method | Description |
|---|---|
| `add_repo(url)` | Add a repo by URL; returns the `Repo` instance |
| `get(key, default=None)` | Get a value with last-repo-wins precedence |
| `get_repo_by_url(url)` | Find a repo by its URL |
| `get_repo_by_kind(kind)` | Find the first repo matching a `repo.kind` value |
| `dump()` | Log all merged key-value pairs (debug) |

### `Repo`

| Method | Description |
|---|---|
| `get(key, default=None)` | Get a dot-separated key from this repo's config |
| `set(key, value)` | Set a dot-separated key in this repo's config |
| `kind()` | Return the `repo.kind` value |
| `read(filepath)` | Read a file relative to the repo root |
| `resolve_path(filepath)` | Resolve a relative path to an absolute `Path` |
| `write_config()` | Write modified config back to disk (file repos only) |
| `add_repo_ref(manager, dir)` | Add a `[[repo-ref]]` entry and load it |

## Development

```bash
cd toml-repo
poetry install --with dev
poetry run pytest
```

## License

GPL-3.0 — see [LICENSE](LICENSE) for details.
