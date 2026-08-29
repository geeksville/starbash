"""Domain objects and helpers for generated target reports."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SESSION_METADATA_KEYS = ("FOCALLEN", "FOCRATIO", "GAIN", "XPIXSZ", "YPIXSZ")
FRAME_METADATA_KEYS = (
    "DATE-OBS",
    "DEWPOINT",
    "HUMIDITY",
    "AMBTEMP",
    "WINDGUST",
    "WINDSPD",
    "CCD-TEMP",
    "EXPTIME",
    "FWHM",
    "Amplitude",
    "Roundness",
    "Background",
    "Stars",
)
EQUIPMENT_FITS_KEYS = {
    "camera": ("INSTRUME", "instrumen"),
    "telescope": ("TELESCOP", "telescop"),
    "filter": ("FILTER", "filter"),
    "filterwheel": ("FWHEEL", "fwheel"),
}


@dataclass
class FrameInfo:
    """Reportable information about one source frame."""

    metadata: dict[str, Any]


@dataclass
class SessionInfo:
    """Reportable information about one imaging session."""

    id: int | None
    date: str | None
    start: str | None
    end: str | None
    equipment: dict[str, dict[str, Any]]
    metadata: dict[str, Any]
    frames: list[FrameInfo]


def selected_metadata(metadata: dict[str, Any], keys: Iterable[str], blacklist: Iterable[str] = ()) -> dict[str, Any]:
    """Copy selected metadata fields, excluding blacklisted keys and ``None`` values."""
    excluded = set(blacklist)
    return {
        key: copy.deepcopy(metadata[key])
        for key in keys
        if key in metadata and key not in excluded and metadata[key] is not None
    }


def frame_info(metadata: dict[str, Any], blacklist: Iterable[str] = ()) -> FrameInfo:
    """Build frame report metadata, omitting unavailable registration values."""
    values = selected_metadata(metadata, FRAME_METADATA_KEYS, blacklist)
    return FrameInfo(metadata=values)


def _as_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _matches(pattern: str, observed: str) -> tuple[bool, bool]:
    """Return ``(matched, exact)`` for a catalog value and observed FITS value."""
    if pattern == observed:
        return True, True
    try:
        return re.fullmatch(pattern, observed) is not None, False
    except re.error:
        return False, False


def match_equipment(metadata: dict[str, Any], catalog: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Match supported equipment types, returning complete or partial records.

    Exact matches outrank regular-expression matches; ties retain catalog order.
    Unmatched observed values are represented by a partial ``type``/``fits`` record.
    """
    result: dict[str, dict[str, Any]] = {}
    catalog_entries = [dict(entry) for entry in catalog]
    for equipment_type, (metadata_key, catalog_key) in EQUIPMENT_FITS_KEYS.items():
        observed = _as_string(metadata.get(metadata_key))
        if observed is None:
            continue
        best: tuple[int, dict[str, Any]] | None = None
        for entry in catalog_entries:
            if entry.get("type") != equipment_type:
                continue
            fits = entry.get("fits", {})
            pattern = _as_string(fits.get(catalog_key))
            if pattern is None:
                continue
            matched, exact = _matches(pattern, observed)
            if matched and (best is None or (exact and best[0] != 0)):
                candidate = copy.deepcopy(dict(entry))
                best = (0 if exact else 1, candidate)
        if best is not None:
            result[equipment_type] = best[1]
        else:
            result[equipment_type] = {"type": equipment_type, "fits": {catalog_key: observed}}
    return result


def sort_datetime(value: Any) -> tuple[int, str]:
    """Produce a deterministic chronological sort key for FITS date strings."""
    text = _as_string(value) or ""
    try:
        return (0, datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat())
    except ValueError:
        return (1, text)
