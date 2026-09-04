"""Reusable crop and rotation helpers for processing recipes."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starbash.fits import read_dimensions
from starbash.tool import tools

siril = tools["siril"]

# These globals are populated by recipe scripts before calling ``crop_files``.
context: dict[str, Any] = {}
logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CropSize:
    """A parsed crop size expressed as pixels or a percentage."""

    unit: str
    value: int | float


_PIXELS_RE = re.compile(r"[+]?[0-9]+")
_PERCENT_RE = re.compile(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)%")


def parse_crop_size(name: str, value: int | str) -> CropSize:
    """Parse a crop size parameter into pixels or a percentage.

    Integer values and numeric strings are maximum pixel dimensions. Strings
    ending in ``%`` retain that percentage of the source dimension.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive pixel value, got {value!r}")

    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{name} must be a positive pixel value, got {value!r}")
        return CropSize("pixels", value)

    if not isinstance(value, str):
        raise ValueError(f"{name} must be an integer or string, got {value!r}")

    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be empty")

    if text.endswith("%"):
        if not _PERCENT_RE.fullmatch(text):
            raise ValueError(f"{name} has an invalid percentage: {value!r}")
        percentage = float(text[:-1])
        if not math.isfinite(percentage) or not 0 < percentage <= 100:
            raise ValueError(f"{name} percentage must be between 0 and 100, got {value!r}")
        return CropSize("percent", percentage)

    if not _PIXELS_RE.fullmatch(text):
        raise ValueError(f"{name} must be a positive pixel value, got {value!r}")
    pixels = int(text)
    if pixels <= 0:
        raise ValueError(f"{name} must be a positive pixel value, got {value!r}")
    return CropSize("pixels", pixels)


def crop_rectangle(
    width: int,
    height: int,
    crop_width: int | str = "80%",
    crop_height: int | str = "80%",
) -> tuple[int, int, int, int]:
    """Return a centered crop rectangle using the configured axis sizes."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Image dimensions must be positive, got {width}x{height}")

    parsed_width = parse_crop_size("crop_width", crop_width)
    parsed_height = parse_crop_size("crop_height", crop_height)
    if parsed_width.unit == "percent":
        actual_width = int(width * parsed_width.value / 100)
    else:
        actual_width = min(width, int(parsed_width.value))
    if parsed_height.unit == "percent":
        actual_height = int(height * parsed_height.value / 100)
    else:
        actual_height = min(height, int(parsed_height.value))

    if actual_width < 1 or actual_height < 1:
        raise ValueError(
            f"Crop dimensions produce an empty crop for {width}x{height}"
        )
    crop_x = (width - actual_width) // 2
    crop_y = (height - actual_height) // 2
    return crop_x, crop_y, actual_width, actual_height


def crop_files(
    input_paths: list[Path],
    output_paths: list[Path],
    rotate_deg: int | float = 0,
    crop_width: int | str = "80%",
    crop_height: int | str = "80%",
) -> None:
    """Crop and rotate each input FITS file into its corresponding output."""
    if not input_paths or not output_paths:
        raise ValueError("crop_files requires at least one input and output path")
    if len(input_paths) != len(output_paths):
        raise ValueError("crop_files requires equal numbers of input and output paths")
    parse_crop_size("crop_width", crop_width)
    parse_crop_size("crop_height", crop_height)
    if isinstance(rotate_deg, bool) or not isinstance(rotate_deg, (int, float)):
        raise ValueError(f"rotate_deg must be numeric, got {rotate_deg!r}")
    if not math.isfinite(rotate_deg):
        raise ValueError(f"rotate_deg must be finite, got {rotate_deg!r}")

    commands: list[str] = []
    for input_path, output_path in zip(input_paths, output_paths, strict=True):
        width, height = read_dimensions(input_path)
        crop_x, crop_y, actual_width, actual_height = crop_rectangle(
            width, height, crop_width, crop_height
        )
        commands.extend(
            [
                f'load "{input_path}"',
                f"crop {crop_x} {crop_y} {actual_width} {actual_height}",
            ]
        )
        if rotate_deg != 0:
            commands.append(f"rotate {rotate_deg:g} -interp=lanczos4")
        commands.append(f'save "{output_path}"')

    process_dir = context.get("process_dir")
    if not process_dir:
        raise ValueError("crop_files requires context['process_dir']")
    siril.run("\n".join(commands), context=context, cwd=process_dir)
