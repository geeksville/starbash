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

# Crop dimensions are rounded down to a multiple of this so downstream tools that
# require aligned widths/heights (StarNet, deconvolution and similar) work on the
# cropped output. See ``crop_rectangle``.
CROP_MULTIPLE = 16

# Siril only accepts ``rotate`` angles in [0, 360) and aborts the whole script
# ("Angle ... not allowed. Should be between 0.0 and 360.0.") on anything else,
# so angles are normalized before being emitted. See ``normalize_rotation``.
FULL_TURN_DEGREES = 360.0

# An exact multiple of this is a quarter turn. Such a rotation is a pixel-exact
# permutation of the source pixels and fills its bounding rectangle completely,
# so Siril can keep the whole rotated canvas. See ``rotation_command``.
QUARTER_TURN_DEGREES = 90.0


def round_down_to_multiple(value: int, multiple: int) -> int:
    """Round ``value`` down to the nearest multiple of ``multiple``."""
    return (value // multiple) * multiple


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


def normalize_rotation(rotate_deg: int | float) -> float:
    """Return ``rotate_deg`` mapped into the ``[0, 360)`` range Siril accepts.

    Siril rejects negative and 360-and-above angles, aborting the whole script,
    so ``-90`` becomes ``270`` and ``360`` becomes ``0`` (i.e. no rotation).
    """
    return float(rotate_deg) % FULL_TURN_DEGREES


def is_quarter_turn(angle: float) -> bool:
    """Return True when ``angle`` is an exact multiple of 90 degrees."""
    return angle % QUARTER_TURN_DEGREES == 0.0


def rotation_command(rotate_deg: int | float) -> str | None:
    """Return the Siril ``rotate`` command for ``rotate_deg``, or None to skip it.

    Siril's default is to fit the rotated image back into the *source* rectangle, so
    ``rotate 90`` on a 640x360 image saves 640x360 again -- the corners of the
    rotation are silently dropped, which is not what "rotate 90 degrees" means.

    For an exact quarter turn the rotated image fills its bounding rectangle with
    no black corners and the transform is a pixel-exact permutation, so ``-nocrop``
    is added and the output keeps the whole rotated canvas: 90 and 270 degrees swap
    the output width and height, while 180 degrees does not (all three are
    lossless). Any other angle keeps Siril's crop-to-fit behavior, because a
    rotated rectangle cannot fill a larger one without black corners, and the
    designer's rule is that a crop stage must not grow the canvas.
    """
    angle = normalize_rotation(rotate_deg)
    if angle == 0.0:
        return None  # Siril treats a 0/360 degree rotation as an error, not a no-op
    options = "-interp=lanczos4"
    if is_quarter_turn(angle):
        options += " -nocrop"
    return f"rotate {angle:g} {options}"


def crop_rectangle(
    width: int,
    height: int,
    crop_width: int | str = "80%",
    crop_height: int | str = "80%",
) -> tuple[int, int, int, int]:
    """Return a centered crop rectangle using the configured axis sizes.

    Each generated dimension is rounded down to the nearest multiple of
    :data:`CROP_MULTIPLE` (never up), so the requested size is preserved as
    closely as possible while remaining aligned for downstream tools.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Image dimensions must be positive, got {width}x{height}")

    parsed_width = parse_crop_size("crop_width", crop_width)
    parsed_height = parse_crop_size("crop_height", crop_height)
    if parsed_width.unit == "percent":
        actual_width = int(width * parsed_width.value / 100)
    else:
        actual_width = min(width, int(parsed_width.value))
    # Round each generated dimension down to an aligned multiple, so the request
    # is honoured as closely as possible without exceeding it.
    actual_width = round_down_to_multiple(actual_width, CROP_MULTIPLE)
    if parsed_height.unit == "percent":
        actual_height = int(height * parsed_height.value / 100)
    else:
        actual_height = min(height, int(parsed_height.value))
    actual_height = round_down_to_multiple(actual_height, CROP_MULTIPLE)

    if actual_width < 1 or actual_height < 1:
        raise ValueError(f"Crop dimensions produce an empty crop for {width}x{height}")
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
    """Crop and rotate each input FITS file into its corresponding output.

    The crop rectangle (see :func:`crop_rectangle`) is applied first, then the
    rotation, and the angle is normalized into ``[0, 360)``. An exact quarter turn
    keeps the whole rotated canvas, so ``rotate_deg = 90`` (or ``270``) swaps the
    output width and height; any other angle is rotated inside the crop
    rectangle's dimensions, discarding the rotated corners. See
    :func:`rotation_command`.
    """
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

    rotate_command = rotation_command(rotate_deg)
    if rotate_command:
        normalized = normalize_rotation(rotate_deg)
        if normalized != rotate_deg:
            logger.info(
                "Normalizing rotation %g degrees to %g (Siril only accepts 0-360)",
                rotate_deg,
                normalized,
            )
        logger.debug("Rotating by %g degrees using '%s'", normalized, rotate_command)

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
        if rotate_command:
            commands.append(rotate_command)
        commands.append(f'save "{output_path}"')

    process_dir = context.get("process_dir")
    if not process_dir:
        raise ValueError("crop_files requires context['process_dir']")
    siril.run("\n".join(commands), context=context, cwd=process_dir)
