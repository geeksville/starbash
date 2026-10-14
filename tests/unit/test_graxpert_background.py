"""Range-preserving GraXpert background recipe and palette contracts."""

import sys
import tomllib
import types
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from astropy.io import fits

from starbash.tool.graxpert import GraxpertBuiltinTool

RECIPES = Path(__file__).resolve().parents[2] / "starbash-recipes"


def _run_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: np.ndarray
) -> tuple[np.ndarray, list[tuple[list[str], dict[str, object]]], fits.Header]:
    """Run the actual tool and inspect the FITS seen by a stand-in AI backend."""
    source = tmp_path / "source.fits"
    target = tmp_path / "target.fits"
    header = fits.Header({"OBJECT": "ngc7822"})
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(source)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def api_run(args: list[str], prefs: dict[str, object]) -> None:
        calls.append((args, prefs))
        assert args[:3] == ["-cmd", "background-extraction", "-output"]
        with fits.open(args[4]) as hdus:
            primary = cast(fits.PrimaryHDU, hdus[0])
            image = primary.data
            assert image is not None
            assert image.min() >= 0 and image.max() <= 1
            assert primary.header["OBJECT"] == "ngc7822"
            # A nonzero spatial correction with mean zero (like GraXpert's BGE).
            correction = np.linspace(-0.01, 0.01, image.shape[-1], dtype=np.float32)
            corrected = image - correction
            output_header = primary.header.copy()
            output_header["BG-EXTR"] = "GraXpert"
            fits.PrimaryHDU(corrected, header=output_header).writeto(args[3])

    graxpert = types.ModuleType("graxpert")
    graxpert.__file__ = str(tmp_path / "graxpert" / "__init__.py")
    graxpert.api_run = api_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "graxpert", graxpert)

    GraxpertBuiltinTool().run(
        ["-cmd", "background-extraction", "-output", str(target), str(source)],
        cwd=str(tmp_path),
        preserve_input_range="true",
        ai_version="1.0.1",
        smoothing_option=0.5,
    )
    with fits.open(target) as hdus:
        primary = cast(fits.PrimaryHDU, hdus[0])
        result = np.asarray(primary.data).copy()
        output_header = primary.header.copy()
    return result, calls, output_header


@pytest.mark.parametrize(
    "data",
    [
        np.array([[0.1, 0.5, 1.0]], dtype=np.float32),
        np.array([[0.1, 0.5, 2.0]], dtype=np.float32),
        np.array([[-0.2, 0.3, 1.8]], dtype=np.float32),
        np.zeros((3, 4), dtype=np.float32),
        np.stack([np.full((2, 4), 0.2), np.full((2, 4), 1.8), np.full((2, 4), 0.5)]),
    ],
    ids=["in-range", "bright-star", "negative-minimum", "constant", "rgb"],
)
def test_background_keeps_scale_and_gradient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: np.ndarray
) -> None:
    result, calls, header = _run_background(tmp_path, monkeypatch, data)
    assert len(calls) == 1
    assert calls[0][1] == {"ai_version": "1.0.1", "smoothing_option": 0.5}
    # The spatial correction is reversed with exactly the input transform.
    offset = min(0.0, float(data.min()))
    scale = max(1.0, float(data.max()) - offset)
    correction = np.linspace(-0.01, 0.01, data.shape[-1]) * scale
    np.testing.assert_allclose(result, data - correction, atol=2e-7)
    assert header["OBJECT"] == "ngc7822"
    assert header["BG-EXTR"] == "GraXpert"
    assert not list(tmp_path.glob("starbash-bge-*"))
    if offset or scale != 1:
        assert calls[0][0][3] != str(tmp_path / "target.fits")
    else:
        assert calls[0][0][3] == str(tmp_path / "target.fits")


def test_background_rejects_nonfinite_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graxpert = types.ModuleType("graxpert")
    graxpert.__file__ = str(tmp_path / "graxpert" / "__init__.py")
    graxpert.api_run = lambda *args: pytest.fail("GraXpert must not run")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "graxpert", graxpert)
    source = tmp_path / "source.fits"
    fits.PrimaryHDU(np.array([[np.nan, 1]], dtype=np.float32)).writeto(source)
    with pytest.raises(ValueError, match="non-finite"):
        GraxpertBuiltinTool().run(
            ["-cmd", "background-extraction", "-output", str(tmp_path / "out.fits"), str(source)],
            cwd=str(tmp_path),
            preserve_input_range="true",
        )


def test_failed_background_keeps_prior_output_and_cleans_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never replace a previously good bk_* when the AI step fails."""
    graxpert = types.ModuleType("graxpert")
    graxpert.__file__ = str(tmp_path / "graxpert" / "__init__.py")

    def failed_run(args: list[str], prefs: dict[str, object]) -> None:
        assert Path(args[4]).is_file()
        raise RuntimeError("model failed")

    graxpert.api_run = failed_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "graxpert", graxpert)
    source = tmp_path / "source.fits"
    target = tmp_path / "target.fits"
    fits.PrimaryHDU(np.array([[0.1, 2]], dtype=np.float32)).writeto(source)
    fits.PrimaryHDU(np.array([[0.5, 0.5]], dtype=np.float32)).writeto(target)
    with pytest.raises(RuntimeError, match="model failed"):
        GraxpertBuiltinTool().run(
            ["-cmd", "background-extraction", "-output", str(target), str(source)],
            cwd=str(tmp_path),
            preserve_input_range="true",
        )
    np.testing.assert_array_equal(fits.getdata(target), [[0.5, 0.5]])
    assert not list(tmp_path.glob("starbash-bge-*"))


def test_recipe_opts_in_and_sho_does_not_apply_scnr() -> None:
    with (RECIPES / "graxpert" / "background.toml").open("rb") as file:
        stage = tomllib.load(file)["stages"][0]
    assert stage["tool"]["name"] == "graxpert"
    assert stage["tool"]["parameters"]["preserve_input_range"] == "true"
    assert stage["outputs"][0]["auto"]["prefix"] == "bk_"
    with (RECIPES / "palette" / "sho.toml").open("rb") as file:
        sho = tomllib.load(file)["stages"][0]["script"]
    with (RECIPES / "palette" / "hoo.toml").open("rb") as file:
        hoo = tomllib.load(file)["stages"][0]["script"]
    assert "rmgreen" not in "\n".join(
        line for line in sho.splitlines() if not line.strip().startswith("#")
    )
    assert "rgbcomp SHO_Ha SHO_SynGreen SHO_OIII -out=SHO_results" in sho
    assert "rgbcomp HOO_Ha HOO_Green HOO_OIII -out=HOO_results" in hoo
    assert "load SHO_results" in sho and "load HOO_results" in hoo
