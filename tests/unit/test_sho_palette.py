"""End-to-end checks for Siril's optional background-anchored SHO colour controls."""

import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from starbash.doit import FileInfo
from starbash.fits import resolve_fits_variant
from starbash.tool import tools

RECIPE = Path(__file__).resolve().parents[2] / "starbash-recipes" / "palette" / "sho.toml"


def _channel(base: float, *, channel: str) -> np.ndarray:
    """Sky, shared/isolated emission regions and a white star."""
    pixels = np.full((32, 32), base, dtype=np.float32)
    pixels[4:12, 4:12] = base + 0.04
    pixels[15:23, 15:23] = base + 0.12
    if channel == "Ha":
        pixels[24:29, 4:9] = base + 0.10  # Ha-only
        pixels[24:29, 12:17] = base + 0.10  # Ha + real Sii
        pixels[24:29, 20:25] = base + 0.10  # Ha + OIII
    elif channel == "Sii":
        pixels[24:29, 12:17] = base + 0.10
    elif channel == "OIII":
        pixels[24:29, 20:25] = base + 0.10
    pixels[0, 0] = 0.0
    pixels[-1, -1] = 10.0  # a white star: bright enough to clamp at 1 in the palette
    # (keep max <= ~10: Siril's median() collapses to 0 above a ~20 outlier)
    # A star halo above every nebula patch: the palette's P99 reference must
    # land above the features under test, or they would clip at 1.
    pixels[2:5, 27:31] = base + 0.5
    return pixels


def _run_sho(
    tmp_path: Path,
    green_strength: float,
    blue_strength: float,
    *,
    has_sii: bool,
    red_suppression: float = 0.0,
) -> np.ndarray:
    tmp_path.mkdir(parents=True)
    with RECIPE.open("rb") as recipe:
        stage = tomllib.load(recipe)["stages"][0]
    defaults = {p["name"]: p["default"] for p in stage["parameters"]}
    # Defaults are recipe/user choices; each test explicitly sets its controls.
    assert {
        "green_strength",
        "blue_strength",
        "red_suppression",
        "signal_reference",
    } <= defaults.keys()
    inputs: dict[str, FileInfo] = {}
    for name, base in (("ha", 0.3), ("oiii", 0.08), ("sii", 0.12)):
        if name == "sii" and not has_sii:
            inputs[name] = FileInfo(image_rows=[])
            continue
        channel = {"ha": "Ha", "oiii": "OIII", "sii": "Sii"}[name]
        path = tmp_path / f"nx_bx_bk_crop_stacked_{channel}.fits"
        fits.PrimaryHDU(_channel(base, channel=channel)).writeto(path)
        inputs[name] = FileInfo(image_rows=[{"abspath": str(path), "path": path.name}])

    output = tmp_path / "SHO.fits"
    context = {
        "input": inputs,
        "output": FileInfo(image_rows=[{"abspath": str(output), "path": output.name}]),
        "parameters": SimpleNamespace(
            ha_weight=0.4,
            oiii_weight=0.6,
            green_strength=green_strength,
            blue_strength=blue_strength,
            red_suppression=red_suppression,
            signal_reference=0.1,
        ),
    }
    tools["siril"].run(stage["script"], context=context, cwd=str(tmp_path))
    return np.asarray(fits.getdata(output)).copy()


@pytest.mark.parametrize("has_sii", [True, False], ids=["real-sii", "synthetic-green"])
def test_sho_boost_is_sky_anchored_and_white_preserving(tmp_path: Path, has_sii: bool) -> None:
    """Exercise the real recipe with Siril, not a duplicate numpy-only formula."""
    baseline = _run_sho(tmp_path / "neutral", 1.0, 1.0, has_sii=has_sii)
    raised = _run_sho(tmp_path / "boosted", 1.5, 2.0, has_sii=has_sii)

    np.testing.assert_allclose(raised[0], baseline[0], atol=1e-6)
    for index in (1, 2):
        old = baseline[index]
        new = raised[index]
        sky = float(np.median(old))
        # Pixels at or below the channel median, including the darkest pixel,
        # should not be brightened just to fix colour in the nebulosity.
        np.testing.assert_allclose(new[old <= sky], old[old <= sky], atol=1e-6)
        assert new[6, 6] > old[6, 6]
        assert new[19, 19] > old[19, 19]
        assert new.max() <= 1.0
        np.testing.assert_allclose(new[-1, -1], old[-1, -1], atol=1e-6)
    green_sky = float(np.median(baseline[1]))
    blue_sky = float(np.median(baseline[2]))
    green_relative_boost = (raised[1, 6, 6] - green_sky) / (baseline[1, 6, 6] - green_sky)
    blue_relative_boost = (raised[2, 6, 6] - blue_sky) / (baseline[2, 6, 6] - blue_sky)
    assert blue_relative_boost > green_relative_boost > 1


@pytest.mark.parametrize("has_sii", [True, False], ids=["real-sii", "synthetic-green"])
def test_sho_blue_strength_does_not_change_green(tmp_path: Path, has_sii: bool) -> None:
    """A synthetic green blend must use OIII before its blue-only boost."""
    neutral = _run_sho(tmp_path / "neutral", 1.0, 1.0, has_sii=has_sii)
    blue_only = _run_sho(tmp_path / "blue-only", 1.0, 2.0, has_sii=has_sii)
    np.testing.assert_allclose(blue_only[:2], neutral[:2], atol=1e-6)
    assert blue_only[2, 6, 6] > neutral[2, 6, 6]


@pytest.mark.parametrize("has_sii", [True, False], ids=["real-sii", "synthetic-green"])
def test_red_suppression_reduces_violet_without_dimming_ha_only_nebula(
    tmp_path: Path, has_sii: bool
) -> None:
    """Exercise the actual Siril recipe with the user's strong blue setting."""
    neutral = _run_sho(tmp_path / "neutral", 2.0, 8.0, has_sii=has_sii)
    softened = _run_sho(tmp_path / "softened", 2.0, 8.0, has_sii=has_sii, red_suppression=0.5)
    strongest = _run_sho(tmp_path / "strongest", 2.0, 8.0, has_sii=has_sii, red_suppression=1.0)

    # Do not touch Sii or OIII (including their own boosts).
    np.testing.assert_array_equal(softened[1:], neutral[1:])
    np.testing.assert_array_equal(strongest[1:], neutral[1:])
    # Blue-rich nebulosity shifts toward blue, progressively with strength.
    assert neutral[0, 6, 6] > softened[0, 6, 6] > strongest[0, 6, 6] >= 0
    assert neutral[0, 19, 19] > softened[0, 19, 19] > strongest[0, 19, 19]
    # Inspect Siril's saved mask: use the stronger independent signal rather
    # than adding green + blue and over-suppressing Ha where both overlap.
    # Siril's median(Image) differs slightly from numpy's median(FITS), hence
    # compare the mask with a tolerance rather than the complete red equation.
    # Siril appends its saved extension (.fit/.fits) to extension-less save
    # names, so resolve whichever spelling it actually wrote.
    companion_path = resolve_fits_variant(tmp_path / "softened" / "SHO_Companion.fit")
    companion_data = fits.getdata(companion_path)
    assert companion_data is not None
    companion = np.asarray(companion_data)
    blue_signal = max(float(neutral[2, 6, 6]) - float(np.median(neutral[2])), 0.0)
    green_signal = (
        max(float(neutral[1, 6, 6]) - float(np.median(neutral[1])), 0.0) if has_sii else 0.0
    )
    assert float(companion[6, 6]) == pytest.approx(max(green_signal, blue_signal), abs=0.002)
    if has_sii:
        # The stronger signal wins (not their sum); the 0.002 slack tracks the
        # fixture's value scale, which the palette's P99 normalization shrinks.
        assert float(companion[6, 6]) < green_signal + blue_signal - 0.002
    # The sky pedestal and a red-only nebula retain their original red values.
    np.testing.assert_allclose(softened[0, 2, 2], neutral[0, 2, 2], atol=1e-6)
    np.testing.assert_allclose(softened[0, 26, 6], neutral[0, 26, 6], atol=1e-6)
    np.testing.assert_allclose(strongest[0, 26, 6], neutral[0, 26, 6], atol=1e-6)
    if has_sii:
        # Green-only Sii emission now gates red, without any OIII signal.
        assert neutral[0, 26, 14] > softened[0, 26, 14] > strongest[0, 26, 14]
        assert neutral[0, 26, 22] > softened[0, 26, 22] > strongest[0, 26, 22]
    else:
        # Synthetic green contains Ha; it must not suppress Ha in a green-only
        # region when OIII contributes nothing above its median.
        np.testing.assert_allclose(softened[0, 26, 14], neutral[0, 26, 14], atol=1e-6)
        assert neutral[0, 26, 22] > softened[0, 26, 22] > strongest[0, 26, 22]
    # White cores must not turn blue or dark, even at maximum suppression.
    np.testing.assert_allclose(strongest[:, -1, -1], neutral[:, -1, -1], atol=1e-6)
    assert np.isfinite(strongest).all()
    assert 0 <= strongest.min() <= strongest.max() <= 1


def test_real_sii_green_strength_controls_red_suppression(tmp_path: Path) -> None:
    """Only the genuinely independent Sii channel can extend the OIII red mask."""
    weak_green = _run_sho(tmp_path / "weak-green", 1.0, 8.0, has_sii=True, red_suppression=0.5)
    strong_green = _run_sho(tmp_path / "strong-green", 2.0, 8.0, has_sii=True, red_suppression=0.5)
    # Boosting green increases red suppression in the Sii-only area.
    assert strong_green[1, 26, 14] > weak_green[1, 26, 14]
    assert strong_green[0, 26, 14] < weak_green[0, 26, 14]
    # It cannot change suppression in the OIII-only or Ha-only areas.
    np.testing.assert_allclose(strong_green[0, 26, 22], weak_green[0, 26, 22], atol=1e-6)
    np.testing.assert_allclose(strong_green[0, 26, 6], weak_green[0, 26, 6], atol=1e-6)


def _run_sho_with_low_sky(
    tmp_path: Path,
    *,
    has_sii: bool,
    red_suppression: float,
    ha_patch: float = 0.70,
    oiii_patch: float = 0.30,
    base: float = 0.01,
) -> np.ndarray:
    """Like _run_sho, but on sky-like bases so Ha's excess over its median is
    the dominant term (the regime the actual palette operates in after rescale)."""
    tmp_path.mkdir(parents=True)
    with RECIPE.open("rb") as recipe:
        stage = tomllib.load(recipe)["stages"][0]
    inputs: dict[str, FileInfo] = {}
    for name, above in (("ha", ha_patch), ("oiii", oiii_patch), ("sii", oiii_patch)):
        if name == "sii" and not has_sii:
            inputs[name] = FileInfo(image_rows=[])
            continue
        pixels = np.full((32, 32), base, dtype=np.float32)
        pixels[4:12, 4:12] = base + above  # shared bright Ha + OIII patch
        if name == "ha":
            pixels[24:29, 4:9] = base + ha_patch  # Ha-only patch, companion is zero
        pixels[0, 0] = 0.0
        pixels[-1, -1] = 10.0  # white star: clamps to 1 under the normalization
        # Star halo above the test patch, so the P99 reference does not clip it.
        pixels[25:29, 25:29] = base + 0.8
        suffix = {"ha": "Ha", "oiii": "OIII", "sii": "Sii"}[name]
        path = tmp_path / f"nx_bx_bk_crop_stacked_{suffix}.fits"
        fits.PrimaryHDU(pixels).writeto(path)
        inputs[name] = FileInfo(image_rows=[{"abspath": str(path), "path": path.name}])

    output = tmp_path / "SHO.fits"
    context = {
        "input": inputs,
        "output": FileInfo(image_rows=[{"abspath": str(output), "path": output.name}]),
        "parameters": SimpleNamespace(
            ha_weight=0.4,
            oiii_weight=0.6,
            green_strength=2.0,
            blue_strength=8.0,
            red_suppression=red_suppression,
            signal_reference=0.1,
        ),
    }
    tools["siril"].run(stage["script"], context=context, cwd=str(tmp_path))
    return np.asarray(fits.getdata(output)).copy()


@pytest.mark.parametrize("has_sii", [True, False], ids=["real-sii", "synthetic-green"])
def test_red_suppression_turns_bright_ha_patches_blue(tmp_path: Path, has_sii: bool) -> None:
    """A bright Ha patch with strong boosted blue loses its red at full strength.

    The old ``(1 - Ha)`` star mask throttled exactly this regime: the brighter
    Ha was, the less the companion could suppress it.  The all-channel
    ``(1 - min(R, G, B))`` mask only shields pixels bright in *every* channel,
    so Ha-bright/blue-bright cloudy regions can finally go blue.
    """
    neutral = _run_sho_with_low_sky(tmp_path / "neutral", has_sii=has_sii, red_suppression=0.0)
    half = _run_sho_with_low_sky(tmp_path / "half", has_sii=has_sii, red_suppression=0.5)
    strong = _run_sho_with_low_sky(tmp_path / "strong", has_sii=has_sii, red_suppression=1.0)

    pixel = (4 + (12 - 4) // 2, 4 + (12 - 4) // 2)
    # Red drops monotonically with strength and falls below the boosted blue.
    assert neutral[0, *pixel] > half[0, *pixel] > strong[0, *pixel] >= 0
    assert strong[0, *pixel] < strong[2, *pixel]
    assert np.isfinite(strong).all()
    assert 0 <= strong.min() <= strong.max() <= 1
    # The sky, the Ha-only patch (no companion) and the white corner stay put.
    np.testing.assert_allclose(strong[0, 2, 2], neutral[0, 2, 2], atol=1e-6)
    np.testing.assert_allclose(strong[0, 0, 0], neutral[0, 0, 0], atol=1e-6)
    np.testing.assert_allclose(strong[0, 26, 6], neutral[0, 26, 6], atol=1e-6)
    np.testing.assert_allclose(strong[:, -1, -1], neutral[:, -1, -1], atol=1e-6)
