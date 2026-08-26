"""Utility functions for stage management to avoid circular imports.

Per-target settings are stored as a single ``[[stages]]`` array-of-tables. Each
item has a ``name``, an optional ``excluded = true`` flag, and an optional nested
``[[stages.overrides]]`` array. A "container" here is any mapping that holds such
an AoT under the key ``stages`` (a target's ``default_stages``, a session row, or
a repo's ``config`` document).
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import tomlkit
from tomlkit.items import AoT, Table

from starbash import StageDict

__all__ = [
    "get_stages_aot",
    "find_stage_entry",
    "is_excluded",
    "upsert_stage",
    "mark_used",
    "mark_excluded",
    "prune_empty_stages",
]


def get_stages_aot(container: MutableMapping[str, Any], create: bool = False) -> AoT:
    """Return the ``[[stages]]`` array-of-tables held by ``container``.

    Args:
        container: mapping that stores the stages AoT under key ``stages``.
        create: if True, create and store an empty AoT when missing (so mutations
            persist back into ``container``). If False, return a detached empty AoT.
    """
    node = container.get("stages")
    if not isinstance(node, AoT):
        node = tomlkit.aot()
        if create:
            container["stages"] = node
    return node


def find_stage_entry(container: MutableMapping[str, Any], name: str) -> Table | None:
    """Return the ``[[stages]]`` entry with the given ``name``, or None."""
    for item in get_stages_aot(container):
        if item.get("name") == name:
            return item  # type: ignore[return-value]
    return None


def is_excluded(container: MutableMapping[str, Any], name: str) -> bool:
    """Return True if the stage ``name`` is marked ``excluded = true``."""
    entry = find_stage_entry(container, name)
    return bool(entry.get("excluded", False)) if entry is not None else False


def upsert_stage(
    container: MutableMapping[str, Any],
    stage: StageDict,
    excluded: bool | None = None,
) -> Table:
    """Ensure a ``[[stages]]`` entry exists for ``stage``; optionally set excluded.

    Existing entries (and any user-added overrides) are preserved. ``excluded=None``
    leaves the flag untouched; ``True`` sets it; ``False`` removes it.
    """
    aot = get_stages_aot(container, create=True)
    name = stage.get("name", "unnamed_stage")

    entry: Table | None = None
    for item in aot:
        if item.get("name") == name:
            entry = item  # type: ignore[assignment]
            break

    if entry is None:
        entry = tomlkit.table()
        name_item = tomlkit.string(str(name))
        description = stage.get("description")
        if description:
            name_item.comment(description)
        entry["name"] = name_item
        aot.append(entry)

    if excluded is True:
        entry["excluded"] = True
    elif excluded is False and "excluded" in entry:
        del entry["excluded"]

    return entry


def mark_used(container: MutableMapping[str, Any], stages: list[StageDict]) -> None:
    """Record each stage as a (non-excluded) ``[[stages]]`` entry."""
    for stage in stages:
        upsert_stage(container, stage, excluded=False)


def mark_excluded(container: MutableMapping[str, Any], stages: list[StageDict]) -> None:
    """Mark each stage as ``excluded = true`` in the ``[[stages]]`` AoT."""
    for stage in stages:
        upsert_stage(container, stage, excluded=True)


def prune_empty_stages(container: MutableMapping[str, Any]) -> None:
    """Remove ``[[stages]]`` entries that have no ``name``.

    The processed-target template ships a placeholder empty ``[[stages]]`` (to fix
    where the array lands in the file); once real entries are added it becomes a
    bogus nameless entry, so drop any nameless entries before writing.
    """
    aot = get_stages_aot(container)
    empty_indices = [i for i, item in enumerate(aot) if not item.get("name")]
    for i in reversed(empty_indices):  # reverse so indices stay valid during removal
        del aot[i]
