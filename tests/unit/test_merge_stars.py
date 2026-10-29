"""End-to-end checks for merge_stars removing residual star light from the starless."""

import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from starbash.doit import FileInfo
from starbash.tool import tools

RECIPE = Path(__file__).resolve().parents[2] / "starbash-recipes" / "post" / "merge_stars.toml"


def _run_merge(
    tmp_path: Path,
    *,
    has_broadband: bool,
    star_residual_removal: float,
    residual: tuple[float, float, float] = (0.60, 0.60, 1.00),
    mask_star: tuple[float, float, float] = (0.0001, 0.0001, 0.0001),
) -> np.ndarray:
    """Run the real recipe through Siril with a (blue) residual star in the starless."""
    tmp_path.mkdir(parents=True)
    with RECIPE.open("rb") as recipe:
        stage = tomllib.load(recipe)["stages"][0]

    # A bright residual star in the stretched starless (starnet leftovers carry
    # the palette tint; default B/R ~ 1.7).  The mask star is faint.
    starless = np.zeros((3, 32, 32), dtype=np.float32)
    starless[:, 16, 16] = residual
    starless_path = tmp_path / "hms_starless_SHO.fits"
    fits.PrimaryHDU(starless).writeto(starless_path)

    # The starnet mask's star; the recipe flattens it to neutral luminance.
    mask = np.zeros((3, 32, 32), dtype=np.float32)
    mask[:, 16, 16] = mask_star
    starmask = tmp_path / "starmask_SHO.fits"
    fits.PrimaryHDU(mask).writeto(starmask)

    broadband_rows = []
    if has_broadband:
        plate = tmp_path / "stacked_bb.fits"
        fits.PrimaryHDU(np.full((32, 32), 0.10, dtype=np.float32)).writeto(plate)
        broadband_rows = [{"abspath": str(plate), "path": plate.name}]

    output = tmp_path / "merged_SHO.fits"
    context = {
        "input": {
            0: FileInfo(image_rows=[{"abspath": str(starless_path), "path": starless_path.name}]),
            "broadband": FileInfo(image_rows=broadband_rows),
        },
        "output": FileInfo(image_rows=[{"abspath": str(output), "path": output.name}]),
        "parameters": SimpleNamespace(stretch=1000.0, star_residual_removal=star_residual_removal),
    }
    tools["siril"].run(stage["script"], context=context, cwd=str(tmp_path))
    return np.asarray(fits.getdata(output)).copy()


def _star_ratio(d: np.ndarray, y: int = 16, x: int = 16) -> float:
    return float(d[2, y, x] / max(d[0, y, x], 1e-9))


def test_residual_tint_is_removed_and_stars_stay_neutral(tmp_path: Path) -> None:
    """Blue starless residuals are knocked out; the neutral star layer shows."""
    full = _run_merge(tmp_path / "full", has_broadband=False, star_residual_removal=1.0)
    half = _run_merge(tmp_path / "half", has_broadband=False, star_residual_removal=0.85)
    none = _run_merge(tmp_path / "none", has_broadband=False, star_residual_removal=0.0)
    # The residual's blue tint shows through when kept, and is removed at 1.0.
    assert _star_ratio(none) > 1.4
    assert _star_ratio(full) == pytest.approx(1.0, abs=0.1)
    assert _star_ratio(half) < _star_ratio(none)
    # The intermediate starless is dimmed under the star mask when removing.
    half_starless = np.asarray(fits.getdata(tmp_path / "half" / "starless.fits"), dtype=float)
    assert float(half_starless[0, 16, 16]) < 0.2  # was 0.60 before the dim
    # The sky is untouched (mask ~ 0 there) and the result stays in range.
    assert full[0, 2, 2] == pytest.approx(none[0, 2, 2], abs=1e-6)
    assert 0 <= full.min() <= full.max() <= 1


def test_broadband_plate_path_uses_neutral_stencil(tmp_path: Path) -> None:
    """With a plate, a blue mask must not leak its tint into the neutral stars."""
    merged = _run_merge(
        tmp_path / "bb",
        has_broadband=True,
        star_residual_removal=0.85,
        residual=(0.60, 0.60, 0.60),  # neutral residual: any tint must come from the mask
        mask_star=(0.10, 0.15, 0.35),  # strongly blue starnet mask star
    )
    # Old behaviour (multiply the plate by the coloured mask) would tint B > R.
    assert _star_ratio(merged) == pytest.approx(1.0, abs=0.1)
    r = float(merged[0, 16, 16])
    assert 0 < r  # some star signal survived the stretch
