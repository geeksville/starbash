"""Parse registration measurements written by Siril sequence files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class SirilSequenceError(ValueError):
    """Raised when a Siril sequence cannot be parsed safely."""


@dataclass(frozen=True)
class RegistrationResult:
    """Registration measurements for one Siril sequence member."""

    sequence_index: int
    selected: bool
    fwhm: float
    amplitude: float
    roundness: float
    background: float
    stars: int

    def as_metadata(self) -> dict[str, float | int]:
        """Return measurements using the database metadata names."""
        return {
            "FWHM": self.fwhm,
            "Amplitude": self.amplitude,
            "Roundness": self.roundness,
            "Background": self.background,
            "Stars": self.stars,
        }


@dataclass(frozen=True)
class SequenceConversion:
    """Mapping from a source frame name to its merged sequence index."""

    source_name: str
    merged_name: str
    merged_index: int


def _parse_int(value: str, description: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise SirilSequenceError(f"Invalid {description}: {value!r}") from exc


def _parse_float(value: str, description: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise SirilSequenceError(f"Invalid {description}: {value!r}") from exc


def parse_siril_seq(file_path: str | Path) -> list[RegistrationResult]:
    """Parse ``R0`` rows and associate them positionally with ``I`` records.

    Siril writes one ``I`` record and one ``R0`` record for each sequence
    member. Unselected members are retained so callers can apply their update
    policy without losing sequence alignment.
    """
    path = Path(file_path)
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise SirilSequenceError(f"Could not read Siril sequence {path}: {exc}") from exc

    header: list[str] | None = None
    sequence_members: list[tuple[int, bool]] = []
    registration_rows: list[tuple[float, float, float, float, int]] = []

    for line_number, line in enumerate(lines, start=1):
        parts = line.split()
        if not parts:
            continue
        record_type = parts[0]
        if record_type == "S":
            if header is not None:
                raise SirilSequenceError(f"Duplicate S header at line {line_number}")
            header = parts
        elif record_type == "I":
            if len(parts) < 3:
                raise SirilSequenceError(f"Malformed I record at line {line_number}: {line!r}")
            index = _parse_int(parts[1], f"sequence index at line {line_number}")
            selected = _parse_int(parts[2], f"selection flag at line {line_number}")
            if selected not in (0, 1):
                raise SirilSequenceError(f"Selection flag must be 0 or 1 at line {line_number}")
            if any(existing == index for existing, _ in sequence_members):
                raise SirilSequenceError(f"Duplicate sequence index {index}")
            sequence_members.append((index, bool(selected)))
        elif record_type == "R0":
            if len(parts) < 7:
                raise SirilSequenceError(f"Malformed R0 record at line {line_number}: {line!r}")
            registration_rows.append(
                (
                    _parse_float(parts[1], f"FWHM at line {line_number}"),
                    _parse_float(parts[2], f"amplitude at line {line_number}"),
                    _parse_float(parts[3], f"roundness at line {line_number}"),
                    _parse_float(parts[5], f"background at line {line_number}"),
                    _parse_int(parts[6], f"stars at line {line_number}"),
                )
            )

    if header is None or len(header) < 5:
        raise SirilSequenceError(f"Malformed or missing S header in {path}")
    declared_images = _parse_int(header[3], "declared image count")
    declared_selected = _parse_int(header[4], "declared selected count")
    if len(sequence_members) != declared_images:
        raise SirilSequenceError(
            f"Siril sequence declares {declared_images} images but contains {len(sequence_members)} I records"
        )
    selected_count = sum(selected for _, selected in sequence_members)
    if selected_count != declared_selected:
        raise SirilSequenceError(
            f"Siril sequence declares {declared_selected} selected images but contains {selected_count} selected I records"
        )
    if len(registration_rows) != len(sequence_members):
        raise SirilSequenceError(
            f"Siril sequence has {len(sequence_members)} I records but {len(registration_rows)} R0 registration rows"
        )

    return [
        RegistrationResult(index, selected, fwhm, amplitude, roundness, background, stars)
        for (index, selected), (fwhm, amplitude, roundness, background, stars) in zip(
            sequence_members, registration_rows, strict=True
        )
    ]


def parse_siril_conversion(file_path: str | Path) -> list[SequenceConversion]:
    """Parse source-to-merged filename mappings written by Siril."""
    path = Path(file_path)
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise SirilSequenceError(f"Could not read Siril conversion {path}: {exc}") from exc

    pattern = re.compile(r"^'(?P<source>[^']+)'\s+->\s+'(?P<merged>[^']+)'$")
    conversions: list[SequenceConversion] = []
    seen_sources: set[str] = set()
    seen_indexes: set[int] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        match = pattern.match(line.strip())
        if match is None:
            raise SirilSequenceError(f"Malformed conversion record at line {line_number}: {line!r}")
        source_name = Path(match.group("source")).name
        merged_name = Path(match.group("merged")).name
        index_match = re.search(r"_(\d+)\.fits?$", merged_name)
        if index_match is None:
            raise SirilSequenceError(f"Missing merged index at line {line_number}: {line!r}")
        merged_index = int(index_match.group(1))
        if source_name in seen_sources or merged_index in seen_indexes:
            raise SirilSequenceError(f"Duplicate conversion mapping at line {line_number}")
        seen_sources.add(source_name)
        seen_indexes.add(merged_index)
        conversions.append(SequenceConversion(source_name, merged_name, merged_index))
    return conversions


__all__ = [
    "RegistrationResult",
    "SequenceConversion",
    "SirilSequenceError",
    "parse_siril_conversion",
    "parse_siril_seq",
]
