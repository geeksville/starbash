from typing import Any

from starbash import InputDef, RequireDef
from starbash.database import (
    ImageRow,
)
from starbash.exception import NotEnoughFilesError
from starbash.safety import get_safe


def _apply_filter(requires: RequireDef, candidates: list[ImageRow]) -> list[ImageRow]:
    """Filter candidate images based on the 'requires' conditions in the input definition.

    Args:
        requires: a requires clause from the stage TOML
        candidates: List of candidate ImageRow objects to filter
    Returns:
        The filtered list of candidate ImageRow objects"""

    kind: str | None = get_safe(requires, "kind")
    value: Any | None = get_safe(requires, "value")

    # Stage 1: Filter candidates using kind-specific filter functions
    def _filter_metadata(img: ImageRow) -> bool:
        """Return True if image should be kept based on metadata filter."""
        name: str | None = requires.get("name")
        if not name:
            raise ValueError("Metadata filter requires 'name' field")

        # Value can be a single item or a list (OR condition)
        if isinstance(value, list):
            return img.get(name) in value
        else:
            return img.get(name) == value

    def _filter_camera(img: ImageRow) -> bool:
        """Return True if image should be kept based on camera filter."""
        return img.get("camera") == value

    def _filter_min_count(img: ImageRow) -> bool:
        """Min_count is handled in stage 2, so always return True here."""
        return True

    # Map of filter kinds to their filter functions
    filters = {
        "metadata": _filter_metadata,
        "camera": _filter_camera,
        "min_count": _filter_min_count,
    }

    if not kind:
        raise ValueError("Filter requires 'kind' field")

    filter_func = filters.get(kind)
    if not filter_func:
        raise ValueError(f"Unknown requires kind: {kind}")

    # Apply the filter function to all candidates
    filtered_candidates = [img for img in candidates if filter_func(img)]

    # Stage 2: Handle min_count check after filtering
    if kind == "min_count":
        if value is not None and len(filtered_candidates) < value:
            raise NotEnoughFilesError(
                f"Stage requires >{value} input files ({len(filtered_candidates)} found)",
                ["FIXMEneedfile"],
            )

    return filtered_candidates


def filter_by_requires(input: InputDef, candidates: list[ImageRow]) -> list[ImageRow]:
    """Filter candidate images based on the 'requires' conditions in the input definition.

    Args:
        input: The input definition from the stage TOML
        candidates: List of candidate ImageRow objects to filter
    Returns:
        The filtered list of candidate ImageRow objects"""
    requires_list: list[RequireDef] = input.get("requires", [])
    for requires in requires_list:
        candidates = _apply_filter(requires, candidates)
    return candidates
