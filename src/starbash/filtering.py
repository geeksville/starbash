import logging

from starbash import InputDef, Metadata, RequireDef
from starbash.aliases import get_aliases
from starbash.database import (
    ImageRow,
)
from starbash.exception import NotEnoughFilesError
from starbash.safety import get_list_of_strings, get_safe


def _apply_filter(requires: RequireDef, candidates: list[ImageRow]) -> list[ImageRow]:
    """Filter candidate images based on the 'requires' conditions in the input definition.

    Args:
        requires: a requires clause from the stage TOML
        candidates: List of candidate ImageRow objects to filter
    Returns:
        The filtered list of candidate ImageRow objects"""

    kind = get_safe(requires, "kind")
    value = get_safe(requires, "value")

    # Stage 1: Filter candidates using kind-specific filter functions
    def _filter_metadata(metadata: Metadata) -> bool:
        """Return True if image should be kept based on metadata filter."""
        name = get_safe(requires, "name")
        value_list = get_list_of_strings(requires, "value")

        # kinda yucky - we assume that the keys in metadata are uppercase
        metadata_value = get_aliases().normalize(metadata.get(name.upper(), ""))

        # we want to do an 'or' match - if any of the names in the list match we claim success
        return metadata_value in value_list

    def _filter_camera(metadata: Metadata) -> bool:
        """Return True if image should be kept based on camera filter."""

        if value == "color":
            session_bayer = metadata.get("BAYERPAT")

            # Session must be color (i.e. have a BAYERPAT header)
            if not session_bayer:
                logging.debug(
                    "Recipe requires a color camera, but session has no BAYERPAT header, skipping"
                )
            return bool(session_bayer)
        else:
            raise ValueError(f"Unknown camera value: {value}")

    def _filter_min_count(metadata: Metadata) -> bool:
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
        if len(filtered_candidates) < value:
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
