"""Helpers for reading FITS metadata."""

from pathlib import Path
from typing import Any

from astropy.io import fits

__all__ = ["read_dimensions", "read_fits_header"]


def read_fits_header(file_path: str | Path) -> dict[str, Any]:
    """Read and return the primary FITS header from ``file_path``."""
    with fits.open(str(file_path), memmap=False) as hdul:
        hdu0: Any = hdul[0]
        return dict(hdu0.header)


def read_dimensions(file_path: str | Path) -> tuple[int, int]:
    """Return the primary FITS image dimensions as ``(width, height)``.

    Raises:
        ValueError: If the primary header has missing or invalid dimensions.
    """
    header = read_fits_header(file_path)
    try:
        width = int(header["NAXIS1"])
        height = int(header["NAXIS2"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"FITS image '{file_path}' is missing valid NAXIS1/NAXIS2 dimensions"
        ) from exc

    if width <= 0 or height <= 0:
        raise ValueError(f"FITS image '{file_path}' has invalid dimensions: {width}x{height}")

    return width, height
