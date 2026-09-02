"""Helpers for reading FITS metadata."""

from pathlib import Path
from typing import Any

from astropy.io import fits

__all__ = ["read_dimensions", "read_fits_header"]


def _json_safe(value: Any) -> Any:
    """Convert an astropy header value into a plain JSON-serializable Python value.

    Commentary cards (COMMENT/HISTORY/blank keyword) come back as
    ``_HeaderCommentaryCards`` (a list-like of strings) and other cards can be
    ``bool``, numpy scalars etc. None of those serialize via ``json.dumps``.
    """
    # Commentary cards: list-like container of strings; join into one string
    if isinstance(value, fits.header._HeaderCommentaryCards):
        return "\n".join(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bool):  # must precede int check (bool is an int subclass)
        return value
    if isinstance(value, (int, float, str)) or value is None:
        return value
    # numpy scalars and anything else: fall back to str()
    return str(value)


def read_fits_header(file_path: str | Path) -> dict[str, Any]:
    """Read and return the primary FITS header from ``file_path``.

    All values are converted to plain JSON-serializable Python types.
    """
    with fits.open(str(file_path), memmap=False) as hdul:
        hdu0: Any = hdul[0]
        return {key: _json_safe(value) for key, value in hdu0.header.items()}


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
