"""FITS range re-mapping shared by tools whose loaders rescale out-of-range data.

GraXpert and rc-astro (BXT/NXT) both min/max-rescale an image as soon as any
pixel leaves ``[0, 1]`` and write the result in that normalized scale without
restoring it.  A duo-stack OIII channel (MAD-matched max ~3) therefore arrives
back at ~1/3 of its original intensity, while Ha (max <= 1) is untouched —
the whole SHO/HOO blue/green cast of ``duo-palette-orange.md``.

To keep the working intensity scale across such a stage, map the input into
``[0, 1]`` ourselves with exactly the loader's transform, run the stage, and
remap the output back with the inverse.  Both tools opt in per recipe stage;
nothing changes for inputs already inside ``[0, 1]``.
"""

from pathlib import Path
from typing import cast

import numpy as np
from astropy.io import fits


def _input_range(path: Path) -> tuple[float, float]:
    """Return the range of a finite, floating-point FITS image."""
    with fits.open(path, memmap=True) as hdus:
        primary = cast(fits.PrimaryHDU, hdus[0])
        data = primary.data
        if data is None or data.dtype.kind != "f":
            raise ValueError(f"Range-preserving stages need a floating-point FITS image: {path}")
        if not np.isfinite(data).all():
            raise ValueError(f"Input contains non-finite pixels: {path}")
        return float(np.min(data)), float(np.max(data))


def _write_scaled_input(source: Path, destination: Path, offset: float, scale: float) -> None:
    """Prepare a float FITS within [0, 1] without losing the source header."""
    with fits.open(source, memmap=True) as hdus:
        primary = cast(fits.PrimaryHDU, hdus[0])
        data = primary.data
        assert data is not None
        scaled = ((data.astype(np.float64) - offset) / scale).astype(np.float32)
        fits.PrimaryHDU(scaled, header=primary.header).writeto(destination)


def _restore_scaled_output(source: Path, destination: Path, offset: float, scale: float) -> None:
    """Undo the input transform, retaining the metadata the tool generated."""
    with fits.open(source, memmap=True) as hdus:
        primary = cast(fits.PrimaryHDU, hdus[0])
        data = primary.data
        if data is None:
            raise ValueError(f"Tool produced an empty FITS image: {source}")
        restored = (data.astype(np.float64) * scale + offset).astype(np.float32)
        fits.PrimaryHDU(restored, header=primary.header).writeto(destination, overwrite=True)
