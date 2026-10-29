"""Unit tests for FITS palette-channel statistics."""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from starbash.fits import signal_scale


def _write(path: Path, data: np.ndarray) -> None:
    fits.PrimaryHDU(data.astype(np.float32)).writeto(path)


def test_signal_scale_is_inverse_of_p99_minus_median(tmp_path: Path) -> None:
    source = tmp_path / "oiii.fits"
    data = np.full((64, 64), 1e-3, dtype=np.float32)
    data[10:20, 10:20] = 1.4e-3
    data[5, 5] = 4.0  # a hot star: must not pin the reference
    _write(source, data)
    expected = 1.0 / (np.percentile(data, 99) - np.median(data))
    assert signal_scale(source) == pytest.approx(expected)


def test_sky_anchored_normalization_ignores_star_max(tmp_path: Path) -> None:
    """The reference comes from the P99, not the star-pinned global max."""
    source = tmp_path / "star.fits"
    base = np.full((128, 128), 0.002, dtype=np.float32)
    base[4:36, 4:36] = 0.004  # a large star halo: this is where P99 lands
    base[3, 3] = 5.0  # one huge saturated star core
    _write(source, base)
    scale = signal_scale(source)
    # (x - median) * scale maps the P99 onto 1; the star core shoots far beyond
    # 1 and is clamped by the palette's min(..., 1).
    assert (np.percentile(base, 99) - np.median(base)) * scale == pytest.approx(1.0)
    assert base[3, 3] * scale > 1.0


def test_signal_scale_rejects_integer_images(tmp_path: Path) -> None:
    source = tmp_path / "int.fits"
    fits.PrimaryHDU(np.zeros((8, 8), dtype=np.int32)).writeto(source)
    with pytest.raises(ValueError, match="floating-point"):
        signal_scale(source)


def test_signal_scale_rejects_non_finite_images(tmp_path: Path) -> None:
    source = tmp_path / "nan.fits"
    _write(source, np.array([[0.0, 1.0, np.nan, 2.0]], dtype=np.float32))
    with pytest.raises(ValueError, match="non-finite"):
        signal_scale(source)


def test_signal_scale_rejects_constant_images(tmp_path: Path) -> None:
    source = tmp_path / "flat.fits"
    _write(source, np.full((8, 8), 0.5, dtype=np.float32))
    with pytest.raises(ValueError, match="no above-median signal"):
        signal_scale(source)
