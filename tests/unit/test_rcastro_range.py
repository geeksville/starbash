"""Range-preserving rc-astro (BXT/NXT) recipe and wrapper contracts."""

import shlex
import tomllib
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from astropy.io import fits

from starbash.tool.base import Tool
from starbash.tool.rcastro import RCAstroTool, _parse_single_input_output

RECIPES = Path(__file__).resolve().parents[2] / "starbash-recipes"


def _run_bxt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: np.ndarray,
    *,
    preserve: bool = True,
) -> tuple[np.ndarray, fits.Header, dict[str, str], list[str]]:
    """Run the tool with a stand-in for the rc-astro CLI binary."""
    source = tmp_path / "source.fits"
    target = tmp_path / "target.fits"
    header = fits.Header({"OBJECT": "ngc7635"})
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(source)
    seen: dict[str, str] = {}
    calls: list[str] = []

    def fake_stream(
        cmd: str,
        cwd: str,
        on_line: Any = None,
        timeout: float | None = None,
        log_out: Any = None,
        stdout_mime: str | None = None,
    ) -> None:
        calls.append(cmd)
        argv = shlex.split(cmd)
        sub_idx = next(i for i, t in enumerate(argv) if t in ("bxt", "nxt"))
        input_path = Path(argv[sub_idx + 1])
        out_path = Path(argv[argv.index("--output") + 1])
        seen["input"] = str(input_path)
        seen["output"] = str(out_path)
        image = np.asarray(fits.getdata(input_path), dtype=float)
        seen["input_min"] = str(float(image.min()))
        seen["input_max"] = str(float(image.max()))
        with fits.open(input_path) as hdus:
            primary = cast(fits.PrimaryHDU, hdus[0])
            out_header = primary.header.copy()
        out_header["BX-TEST"] = "rc-astro"
        # A stand-in processed output: a small constant shift in the tool's own
        # [0, 1] domain, like rc-astro's loader would produce.
        fits.PrimaryHDU(((image + 0.02).astype(np.float32)), header=out_header).writeto(out_path)
        assert on_line is not None
        on_line('{"event":"progress","done":100.0}')

    monkeypatch.setattr("starbash.tool.rcastro.tool_run_streaming", fake_stream)
    monkeypatch.setattr(Tool, "Preferences", {"rc-astro": {"path": "/usr/bin/rc-astro"}})
    kwargs: dict[str, Any] = {"preserve_input_range": "true"} if preserve else {}
    RCAstroTool().run(
        ["bxt", str(source), "--output", str(target), "--sharpen-stars", "0.5"],
        context={},
        cwd=str(tmp_path),
        **kwargs,
    )
    with fits.open(target) as hdus:
        primary = cast(fits.PrimaryHDU, hdus[0])
        result = np.asarray(primary.data).copy()
        out_header = primary.header.copy()
    return result, out_header, seen, calls


@pytest.mark.parametrize(
    "data,scaled",
    [
        (np.array([[0.1, 0.5, 1.0]], dtype=np.float32), False),
        (np.array([[0.0, 0.5, 0.999]], dtype=np.float32), False),
        (np.array([[0.1, 0.5, 3.4]], dtype=np.float32), True),
        (np.array([[-0.1, 0.4, 2.2]], dtype=np.float32), True),
        (np.zeros((3, 4), dtype=np.float32), False),
    ],
    ids=["in-range", "in-range-two", "out-of-range", "negative-minimum", "constant"],
)
def test_bxt_keeps_intensity_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: np.ndarray, scaled: bool
) -> None:
    result, out_header, seen, calls = _run_bxt(tmp_path, monkeypatch, data)
    assert len(calls) == 1
    offset = min(0.0, float(data.min()))
    scale = max(1.0, float(data.max()) - offset)
    np.testing.assert_allclose(result, data + 0.02 * scale, atol=2e-7)
    assert out_header["OBJECT"] == "ngc7635"
    assert out_header["BX-TEST"] == "rc-astro"
    assert not list(tmp_path.glob("starbash-rca-*"))
    if scaled:
        # rc-astro is pointed at a temporary copy in the loader's own [0, 1] domain.
        assert Path(seen["input"]) != tmp_path / "source.fits"
        assert Path(seen["output"]) != tmp_path / "target.fits"
        assert float(seen["input_min"]) >= 0 and float(seen["input_max"]) <= 1
    else:
        # Fully in-range inputs run untouched, exactly as before.
        assert seen["input"] == str(tmp_path / "source.fits")
        assert seen["output"] == str(tmp_path / "target.fits")


def test_bxt_rejects_nonfinite_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.fits"
    fits.PrimaryHDU(np.array([[np.nan, 1]], dtype=np.float32)).writeto(source)

    def fake_stream(*args: Any, **kwargs: Any) -> None:
        pytest.fail("rc-astro must not run on a non-finite image")

    monkeypatch.setattr("starbash.tool.rcastro.tool_run_streaming", fake_stream)
    monkeypatch.setattr(Tool, "Preferences", {"rc-astro": {"path": "/usr/bin/rc-astro"}})
    with pytest.raises(ValueError, match="non-finite"):
        RCAstroTool().run(
            ["bxt", str(source), "--output", str(tmp_path / "out.fits")],
            context={},
            cwd=str(tmp_path),
            preserve_input_range="true",
        )


def test_rc_astro_recipes_opt_into_range_preservation() -> None:
    for name in ("blur-exterminator", "noise-exterminator"):
        with (RECIPES / "rc-astro" / f"{name}.toml").open("rb") as file:
            stage = tomllib.load(file)["stages"][0]
        assert stage["tool"]["name"] == "rc-astro"
        assert stage["tool"]["parameters"]["preserve_input_range"] == "true"


def test_parse_single_input_output() -> None:
    assert _parse_single_input_output(
        ["--json", "bxt", "in.fits", "--output", "out.fits", "--sharpen-stars", "0.5"]
    ) == ("in.fits", "out.fits")
    assert _parse_single_input_output(["--json", "nxt", "in.fits", "--output", "out.fits"]) == (
        "in.fits",
        "out.fits",
    )
    # Not a one-input/one-output shape: run unwrapped.
    assert _parse_single_input_output(["--json", "sxt", "in.fits"]) == (None, None)
    assert _parse_single_input_output(["--json", "bxt", "in.fits"]) == (None, None)
