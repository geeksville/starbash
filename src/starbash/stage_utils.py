"""Utility functions for stage management to avoid circular imports."""

from __future__ import annotations

from starbash import StageDict
from starbash.toml import CommentedString, toml_from_list

__all__ = [
    "stage_with_comment",
    "set_used",
    "set_excluded",
    "get_from_toml",
]


def stage_with_comment(stage: StageDict) -> CommentedString:
    """Create a CommentedString for the given stage."""
    name = stage.get("name", "unnamed_stage")
    description = stage.get("description", None)
    return CommentedString(value=name, comment=description)


def set_used(self: dict, used_stages: list[StageDict]) -> None:
    """Set the used lists for the given section."""
    name = "stages"
    used = [stage_with_comment(s) for s in used_stages]
    node = self.setdefault(name, {})
    node["used"] = toml_from_list(used)


def set_excluded(self: dict, stages_to_exclude: list[StageDict]) -> None:
    """Set the excluded lists for the given section."""
    name = "stages"
    excluded = [stage_with_comment(s) for s in stages_to_exclude]

    node = self.setdefault(name, {})
    node["excluded"] = toml_from_list(excluded)


def get_from_toml(self: dict, key_name: str) -> list[str]:
    """Any consumers of this function probably just want the raw string (key_name is usually excluded or used)"""
    dict_name = "stages"
    node = self.setdefault(dict_name, {})
    excluded: list[CommentedString] = node.get(key_name, [])
    return [a.value for a in excluded]
