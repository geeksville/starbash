"""Reusable crop and rotation helpers for processing recipes."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from starbash.fits import read_dimensions
from starbash.tool import tools

siril = tools["siril"]

# These globals are populated by recipe scripts before calling ``crop_files``.
context: dict[str, Any] = {}
logger: logging.Logger = logging.getLogger(__name__)


def crop_rectangle(width: int, height: int, crop_percent: int = 90) -> tuple[int, int, int, int]:
    """Return a centered crop rectangle retaining ``crop_percent`` of an image."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Image dimensions must be positive, got {width}x{height}")
    if isinstance(crop_percent, bool) or not isinstance(crop_percent, int):
        raise ValueError(f"crop_percent must be an integer, got {crop_percent!r}")
    if not 1 <= crop_percent <= 100:
        raise ValueError(f"crop_percent must be between 1 and 100, got {crop_percent}")

    crop_width = width * crop_percent // 100
    crop_height = height * crop_percent // 100
    if crop_width < 1 or crop_height < 1:
        raise ValueError(
            f"crop_percent={crop_percent} produces an empty crop for {width}x{height}"
        )
    crop_x = (width - crop_width) // 2
    crop_y = (height - crop_height) // 2
    return crop_x, crop_y, crop_width, crop_height


def crop_files(
    input_paths: list[Path],
    output_paths: list[Path],
    crop_percent: int = 90,
    rotate_deg: int | float = 0,
) -> None:
    """Crop and rotate each input FITS file into its corresponding output."""
    if not input_paths or not output_paths:
        raise ValueError("crop_files requires at least one input and output path")
    if len(input_paths) != len(output_paths):
        raise ValueError("crop_files requires equal numbers of input and output paths")
    if isinstance(rotate_deg, bool) or not isinstance(rotate_deg, (int, float)):
        raise ValueError(f"rotate_deg must be numeric, got {rotate_deg!r}")
    if not math.isfinite(rotate_deg):
        raise ValueError(f"rotate_deg must be finite, got {rotate_deg!r}")

    commands: list[str] = []
    for input_path, output_path in zip(input_paths, output_paths, strict=True):
        width, height = read_dimensions(input_path)
        crop_x, crop_y, crop_width, crop_height = crop_rectangle(
            width, height, crop_percent
        )
        commands.extend(
            [
                f'load "{input_path}"',
                f"crop {crop_x} {crop_y} {crop_width} {crop_height}",
            ]
        )
        if rotate_deg != 0:
            commands.append(f"rotate {rotate_deg:g} -interp=lanczos4")
        commands.append(f'save "{output_path}"')

    process_dir = context.get("process_dir")
    if not process_dir:
        raise ValueError("crop_files requires context['process_dir']")
    siril.run("\n".join(commands), context=context, cwd=process_dir)
