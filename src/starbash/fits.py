"""Helpers for reading FITS metadata."""

from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

__all__ = [
    "canonical_fits_path",
    "read_dimensions",
    "read_fits_header",
    "resolve_fits_variant",
    "signal_scale",
]

#: Siril appends its *saved* extension (``.fit`` or ``.fits``, per the user's
#: ``config.1.4.ini``) to an extension-less ``-out`` path. A recipe that names
#: ``master_bias_gain100.fit`` therefore gets ``...gain100.fits`` on a machine
#: whose preference is ``.fits`` -- and recording the declared path would point
#: doit and the DB at a file that was never created. We deliberately do *not*
#: pin this with ``setext``: it calls ``writeinitfile()``, persisting the
#: preference into Siril's shared user config, so parallel runs race on that
#: file (Windows CI: ``save`` failing with "already exists?"). Instead every
#: lookup treats the two spellings as the same file.
FITS_VARIANT_SUFFIXES = (".fit", ".fits")


def resolve_fits_variant(path: str | Path) -> Path:
    """Return the on-disk spelling of a FITS path, trying ``.fit``/``.fits``.

    Returns ``path`` itself when it exists (or has no FITS suffix); otherwise
    returns the existing sibling with the other spelling, or ``path`` unchanged
    when neither exists.
    """
    candidate = Path(path)
    if candidate.exists() or candidate.suffix.lower() not in FITS_VARIANT_SUFFIXES:
        return candidate
    sibling = candidate.with_suffix(".fits" if candidate.suffix.lower() == ".fit" else ".fit")
    return sibling if sibling.exists() else candidate


def canonical_fits_path(path: str | Path) -> str:
    """Canonical key for comparing FITS paths: collapses ``.fit``/``.fits``.

    Dict lookups keyed on ``abspath`` (producers, image_rows, doit
    file_dep/target matching) must agree whether Siril wrote ``.fit`` or
    ``.fits``. Non-FITS paths pass through unchanged.
    """
    text = str(path)
    lower = text.lower()
    for suffix in FITS_VARIANT_SUFFIXES:
        if lower.endswith(suffix):
            return text[: -len(suffix)] + ".fit"
    return text


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


def signal_scale(file_path: str | Path, q: float = 99) -> float:
    """Return ``1 / (Pq - median)`` for a palette channel, its bright reference.

    The SHO/HOO palettes rescale each channel by this inverse span so that a
    duo-stack OIII/Sii channel's nebulosity is not crushed by a star-pinned
    global max: ``(x - median) * scale`` maps the channel's own Pq onto 1 while
    leaving the sky (at/below the median) at zero.  ``q`` is the percentile of
    the reference (default 99), which lands above the nebula but below the few
    saturated star cores (see doc/plans/duo-palette-orange.md).

    Raises:
        ValueError: If the image is not a finite float FITS, or has no signal
            above its median (everything within [median, median]).
    """
    with fits.open(str(file_path), memmap=True) as hdul:
        primary: Any = hdul[0]
        data = primary.data
        if data is None or data.dtype.kind != "f":
            raise ValueError(f"Palette channel must be a floating-point FITS image: {file_path}")
        if not np.isfinite(data).all():
            raise ValueError(f"Palette channel contains non-finite pixels: {file_path}")
        median = float(np.median(data))
        reference = float(np.percentile(data, q))
    span = reference - median
    if span <= 0:
        raise ValueError(f"Palette channel has no above-median signal: {file_path}")
    return 1.0 / span
