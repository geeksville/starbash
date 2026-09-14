"""User preferences that are not tied to one feature area.

The canonical defaults live here rather than at the read sites (mirroring
:mod:`starbash.analytics`), so every front end - the core, the CLI and the GUI
settings page - treats an unset preference identically.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DEFAULT_AUTO_REINDEX", "auto_reindex_enabled"]

#: Re-index the user's image folders at the start of every processing run, so
#: frames added since the last run are picked up.  Mirrors the commented default
#: in ``templates/userconfig.toml``.
DEFAULT_AUTO_REINDEX = True


def auto_reindex_enabled(repo: Any) -> bool:
    """Return whether a processing run should re-index the repos before it starts.

    Args:
        repo: the user preferences repo (or any object with a ``get(key, default)``).
    """
    return bool(repo.get("reindex.auto", DEFAULT_AUTO_REINDEX))
