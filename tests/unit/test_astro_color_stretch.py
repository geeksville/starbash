"""Tests for the astro-color-stretch port (``src/starbash/recipes/astro_color_stretch.py``).

The engine is pure (``stretch_array``) with a thin FITS boundary (``load_image``/
``save_image``/``run``), so most behaviour is tested on synthetic arrays and the file I/O is
tested against real FITS files through the ``sim_siril`` interface.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import tomlkit
from astropy.io import fits

from starbash.recipes import astro_color_stretch as acs
from starbash.sim_siril import SirilInterface

RECIPE_PATH = Path(__file__).parents[2] / "starbash-recipes" / "post" / "astro-color-stretch.toml"
MANIFEST_PATH = Path(__file__).parents[2] / "starbash-recipes" / "starbash.toml"


def load_recipe() -> Any:
    """Parse the recipe TOML (tomlkit, so ``default`` types stay as written)."""
    return tomlkit.parse(RECIPE_PATH.read_text())


def recipe_stage() -> Any:
    """Return the single ``[[stages]]`` entry of the recipe."""
    return load_recipe()["stages"][0]


def synthetic_image(height: int = 96, width: int = 128, seed: int = 20240914) -> np.ndarray:
    """Return a deterministic linear RGB test image: coloured sky, noise and three stars.

    The sky is deliberately tinted (R/G/B gains 1.0/1.1/1.4) so the sky-neutralisation and
    colour-correction steps have something real to work on, and the stars give the star
    reduction and deconvolution steps something to find.
    """
    rng = np.random.default_rng(seed)
    im = np.empty((height, width, 3), dtype=np.float64)
    for index, tint in enumerate((1.0, 1.1, 1.4)):
        im[..., index] = 800.0 * tint + rng.normal(0.0, 20.0, (height, width))

    yy, xx = np.mgrid[0:height, 0:width]
    for cy, cx, amp in ((20, 30, 40000.0), (60, 90, 60000.0), (80, 15, 20000.0)):
        im += amp * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / 6.0)[..., None]

    return np.clip(im, 0, 65535)


def base_params(**kwargs: Any) -> acs.StretchParams:
    """Return default settings.

    CA channel alignment is off by default (detectable in the test below), which also keeps
    these tests fast; a test that wants it passes ``ca_correct=True``.
    """
    return acs.StretchParams(**kwargs)


def spread(image: np.ndarray) -> float:
    """Return the 1st-to-99th percentile span, used as a contrast measure."""
    return float(np.percentile(image, 99) - np.percentile(image, 1))


def misalignment(image: np.ndarray) -> float:
    """Mean absolute difference between the red and green channels.

    A channel-to-channel misfit measure: it drops when channel alignment pulls the red
    channel back onto green.
    """
    red, green, _blue = acs.split_channels(image)
    return float(np.mean(np.abs(red - green)))


class TestParameterParity:
    """The TOML parameters and the dataclass fields must stay in lock-step."""

    def test_recipe_declares_every_dataclass_field(self) -> None:
        declared = {p["name"] for p in recipe_stage()["parameters"]}
        fields = {f.name for f in acs.StretchParams.__dataclass_fields__.values()}

        assert fields == declared

    def test_recipe_defaults_match_the_dataclass(self) -> None:
        declared = {p["name"]: p["default"] for p in recipe_stage()["parameters"]}
        mismatches = {
            name: (value, getattr(acs.StretchParams(), name))
            for name, value in declared.items()
            if value != getattr(acs.StretchParams(), name)
        }

        assert mismatches == {}

    def test_every_parameter_documents_itself(self) -> None:
        for param in recipe_stage()["parameters"]:
            assert param.get("description", "").strip(), f"{param['name']} has no description"

    def test_from_parameter_object_ignores_unknown_settings(self) -> None:
        params = acs.StretchParams.from_parameter_object(
            SimpleNamespace(stretch_type=acs.STRETCH_ASINH, something_new=True)
        )

        assert params.stretch_type == acs.STRETCH_ASINH
        assert params.k1 == 100.0  # untouched settings keep their upstream default

    def test_from_context_reads_the_stage_parameters(self) -> None:
        context = {"parameters": SimpleNamespace(zeroskyblue=8000, scurve=2)}

        params = acs.StretchParams.from_context(context)

        assert (params.zeroskyblue, params.scurve) == (8000, 2)

    def test_string_values_are_coerced(self) -> None:
        params = acs.StretchParams.from_parameter_object(
            SimpleNamespace(skylevelfactor="0.08", win_width="640")
        )

        assert params.skylevelfactor == pytest.approx(0.08)
        assert params.win_width == pytest.approx(640)

    def test_ca_correction_is_off_by_default(self) -> None:
        # Deviation 7: upstream defaults ca_correct to true, but this stage's input is the
        # starless frame, where there are no stars to align (the recipe TOML must agree -
        # that parity is asserted in TestParameterParity).
        assert acs.StretchParams().ca_correct is False

    def test_ca_correction_can_still_be_enabled(self) -> None:
        # Deviation 7 only changes the *default*: enabling it must still realign a channel.
        # This also pins the RGB channel order of align_channels (R and B are aligned to G;
        # a BGR mix-up would shift the wrong channels and not reduce the misfit).
        shifted = synthetic_image().copy()
        shifted[..., 0] = np.roll(shifted[..., 0], 3, axis=1)  # push red 3 px sideways

        aligned = acs.ca_correction(shifted, acs.StretchParams(ca_correct=True))

        assert misalignment(aligned) < 0.5 * misalignment(shifted)

    def test_ca_correction_leaves_an_already_aligned_image_alone(self) -> None:
        plain = synthetic_image()

        aligned = acs.ca_correction(plain.copy(), acs.StretchParams(ca_correct=True))

        assert np.allclose(aligned, plain, atol=0.01)


class TestRecipeWiring:
    """Tests that the recipe is wired into the pipeline like the other stretch recipes."""

    def test_stage_is_multiplexed_in_the_veralux_slot(self) -> None:
        stage = recipe_stage()
        input_def = stage["inputs"][0]

        assert stage["name"] == "astro_color_stretch"
        assert stage["tool"]["name"] == "python"
        assert input_def["after"] == "(starnet|palette_broadband).*"
        assert input_def["multiplex"] is True

    def test_stage_requires_a_non_starmask_input(self) -> None:
        requires = recipe_stage()["inputs"][0]["requires"]

        assert requires[0]["kind"] == "min_count"
        assert requires[0]["value"] == 1
        assert requires[1]["kind"] == "filename"
        assert requires[1]["value"] == "starmask"
        assert requires[1]["mode"] == "exclude"

    def test_stage_writes_an_acs_prefixed_processed_output(self) -> None:
        stage = recipe_stage()

        assert stage["outputs"][0]["kind"] == "processed"
        assert stage["outputs"][0]["auto"]["prefix"] == "acs_"

    def test_script_calls_the_recipe_engine(self) -> None:
        script = recipe_stage()["script"]

        assert "from starbash.recipes import astro_color_stretch" in script
        assert "astro_color_stretch.logger = logger" in script
        assert "astro_color_stretch.run(context)" in script

    def test_default_manifest_includes_the_recipe(self) -> None:
        manifest: Any = tomlkit.parse(MANIFEST_PATH.read_text())
        refs = [ref.get("dir") for ref in manifest["repo-ref"]]

        assert "post/astro-color-stretch.toml" in refs


class TestImageBoundary:
    """Tests for the FITS <-> 0..65535 working-array conversion."""

    def test_uint16_planar_data_becomes_interleaved_float64(self) -> None:
        data = np.zeros((3, 4, 5), dtype=np.uint16)
        data[0] = 100
        data[1] = 200
        data[2] = 300

        im = acs.normalize_input(data)

        assert im.shape == (4, 5, 3)
        assert im.dtype == np.float64
        assert list(im[0, 0]) == [100.0, 200.0, 300.0]

    def test_uint8_data_is_expanded_to_the_full_range(self) -> None:
        data = np.full((3, 2, 2), 255, dtype=np.uint8)

        assert acs.normalize_input(data).min() == 65535.0

    def test_normalised_float_data_is_scaled_up(self) -> None:
        data = np.zeros((3, 2, 2), dtype=np.float32)
        data[0] = 0.5

        im = acs.normalize_input(data)

        assert im[0, 0, 0] == pytest.approx(0.5 * 65535.0, abs=1.0)

    def test_integer_dn_float_data_is_used_as_is(self) -> None:
        data = np.full((3, 2, 2), 4000.0, dtype=np.float32)

        assert acs.normalize_input(data).min() == pytest.approx(4000.0)

    def test_mono_input_is_rejected_with_a_clear_message(self) -> None:
        with pytest.raises(ValueError, match="3-channel colour image"):
            acs.normalize_input(np.zeros((8, 8), dtype=np.uint16))

    def test_stacked_round_trip_preserves_pixel_values(self) -> None:
        im = synthetic_image(height=8, width=6)

        assert np.array_equal(acs.to_interleaved(acs.to_stacked(im)), im)


class TestStretchParamsValidation:
    """Tests for parameter checking (upstream printed and called ``sys.exit()``)."""

    def test_defaults_are_valid(self) -> None:
        acs.StretchParams().validate()

    def test_reports_every_offender_at_once(self) -> None:
        params = acs.StretchParams(stretch_type=1, rootpower=9999, skylevelfactor=5.0, scurve=9)

        with pytest.raises(ValueError) as failure:
            params.validate()

        message = str(failure.value)
        assert "rootpower" in message
        assert "skylevelfactor" in message
        assert "scurve" in message

    def test_parameters_for_unused_stretches_are_not_checked(self) -> None:
        # ``k1`` only applies to the asinh stretch, so an out-of-range value is legal while
        # the root-power stretch is selected.
        acs.StretchParams(stretch_type=acs.STRETCH_RTP, k1=-5).validate()

        with pytest.raises(ValueError, match="k1"):
            acs.StretchParams(stretch_type=acs.STRETCH_ASINH, k1=-5).validate()

    def test_describe_echoes_the_effective_settings(self) -> None:
        lines = acs.StretchParams(scurve=3).describe()

        assert len(lines) == len(acs.StretchParams.__dataclass_fields__) + 4
        assert any("scurve = 3" in line for line in lines)
        assert any("root-power" in line for line in lines)
        assert any("4096.0/4096.0/4096.0" in line for line in lines)


class TestDarkSkyRegion:
    """Tests for the dark-sky window selection used by the black point."""

    def test_full_image_method_uses_the_whole_frame(self) -> None:
        im = synthetic_image(height=20, width=30)

        assert acs.select_dark_region(im, base_params()) == ((0, 0), (30, 20))

    def test_auto_method_finds_a_window_inside_the_frame(self) -> None:
        im = synthetic_image(height=60, width=80)
        params = base_params(
            rgbskyzero_method=acs.SKYZERO_AUTO, win_width=20, win_height=20, win_frac=2
        )

        (x1, y1), (x2, y2) = acs.select_dark_region(im, params)

        assert 0 <= x1 < x2 <= 80
        assert 0 <= y1 < y2 <= 60

    def test_window_larger_than_the_image_is_rejected(self) -> None:
        im = synthetic_image(height=20, width=30)
        params = base_params(rgbskyzero_method=acs.SKYZERO_AUTO)

        with pytest.raises(ValueError, match="exceeds"):
            acs.select_dark_region(im, params)

    def test_manual_window_running_off_the_frame_is_rejected(self) -> None:
        im = synthetic_image(height=60, width=80)
        params = base_params(
            rgbskyzero_method=acs.SKYZERO_MANUAL, ulx=70, uly=50, win_width=20, win_height=20
        )

        with pytest.raises(ValueError, match="runs off"):
            acs.select_dark_region(im, params)


class TestStretchArray:
    """Tests for the pure pipeline: ``stretch_array``."""

    def test_stretch_brightens_the_background(self) -> None:
        im = synthetic_image()

        out = acs.stretch_array(im, base_params())

        assert float(np.median(out)) > 2.0 * float(np.median(im))

    def test_output_stays_inside_the_16_bit_range(self) -> None:
        out = acs.stretch_array(synthetic_image(), base_params())

        assert float(out.min()) >= 0.0
        assert float(out.max()) <= acs.DN_MAX

    def test_sky_is_neutralised_across_the_channels(self) -> None:
        # The synthetic sky is deliberately blue-tinted (gain 1.4); after the black-point
        # step the three sky medians must sit within a few DN of each other.
        im = synthetic_image()
        assert float(np.median(im[..., 2])) > 1.2 * float(np.median(im[..., 0]))

        out = acs.stretch_array(im, base_params())

        skies = [float(np.median(out[..., index])) for index in range(3)]
        assert max(skies) - min(skies) < 40.0

    def test_regression_pins(self) -> None:
        # Pins the seeded output statistics for the default settings, so an accidental
        # algorithm change (channel order, scaling, an extra pass) cannot slip through.
        out = acs.stretch_array(synthetic_image(), base_params())

        means = [float(out[..., index].mean()) for index in range(3)]
        medians = [float(np.median(out[..., index])) for index in range(3)]
        assert means == pytest.approx([3436.35, 3439.07, 3453.48], abs=0.5)
        assert medians == pytest.approx([3039.83, 3041.95, 3058.62], abs=0.5)
        assert float(out.max()) == pytest.approx(65041.87, abs=0.5)

    def test_is_deterministic(self) -> None:
        params = base_params()

        assert np.array_equal(
            acs.stretch_array(synthetic_image(), params),
            acs.stretch_array(synthetic_image(), params),
        )

    @pytest.mark.parametrize("stretch_type", [acs.STRETCH_RTP, acs.STRETCH_ASINH, acs.STRETCH_LOG])
    def test_each_stretch_family_works(self, stretch_type: int) -> None:
        out = acs.stretch_array(synthetic_image(), base_params(stretch_type=stretch_type))

        assert float(np.median(out)) > 2000.0

    def test_stretch_type_none_leaves_the_sky_at_the_black_point(self) -> None:
        # With the stretch switched off the black-point step still runs (that is its job),
        # but the image must stay down at the ``zerosky*`` level instead of being lifted
        # into the visible range - so no S-curve either, which would move the sky too.
        out = acs.stretch_array(
            synthetic_image(), base_params(stretch_type=acs.STRETCH_NONE, scurve=0)
        )

        sky = float(np.median(out))
        assert 3500.0 < sky < 5000.0
        assert sky == pytest.approx(acs.StretchParams().zeroskygreen, abs=1000.0)

    def test_s_curve_adds_contrast(self) -> None:
        im = synthetic_image()

        without = acs.stretch_array(im, base_params(scurve=0))
        with_curve = acs.stretch_array(im, base_params(scurve=2))

        assert not np.allclose(without, with_curve)
        # The curve is a contrast curve: it darkens the region below its crossover point
        # (the sky) while widening the overall tonal spread.
        assert float(np.median(with_curve)) < float(np.median(without))
        assert spread(with_curve) > spread(without)

    def test_neutral_hsv_adjust_is_a_near_no_op(self) -> None:
        # Deviation 3: upstream fed 0..65535 data into OpenCV's float HSV space (S/V are
        # 0..1), which blew the image out to white. With every adjustment neutral the round
        # trip must therefore barely change the image - a bug detector, not a tolerance test.
        plain = acs.stretch_array(synthetic_image(), base_params())

        neutral = acs.stretch_array(synthetic_image(), base_params(hsv_adjust=True))

        assert float(np.mean(neutral)) == pytest.approx(float(np.mean(plain)), rel=1e-4)
        assert float(np.percentile(neutral, 99)) == pytest.approx(
            float(np.percentile(plain, 99)), rel=1e-3
        )

    def test_hsv_adjust_changes_the_image_when_asked_to(self) -> None:
        plain = acs.stretch_array(synthetic_image(), base_params())

        boosted = acs.stretch_array(
            synthetic_image(), base_params(hsv_adjust=True, sat_adjust=1.6, val_adjust=0.9)
        )

        assert not np.allclose(plain, boosted)
        assert float(boosted.max()) <= acs.DN_MAX

    def test_set_minimum_lifts_the_darkest_pixels(self) -> None:
        out = acs.stretch_array(synthetic_image(), base_params(setmin=True))

        assert float(out.min()) > 0.8 * acs.StretchParams().setminr

    def test_both_colour_correction_methods_produce_different_results(self) -> None:
        im = synthetic_image()

        ratio = acs.stretch_array(im, base_params(color_correction_type=acs.COLORCOR_RATIO))
        hsv = acs.stretch_array(im, base_params(color_correction_type=acs.COLORCOR_HSV))

        assert not np.allclose(ratio, hsv)
        assert float(hsv.max()) <= acs.DN_MAX

    def test_white_balance_gray_world_matches_the_channel_means(self) -> None:
        balanced = acs.stretch_array(synthetic_image(), base_params(wb_mode=acs.WB_GRAY))

        means = [float(balanced[..., index].mean()) for index in range(3)]
        assert max(means) - min(means) < 1.0

    def test_star_reduction_shrinks_halos_but_keeps_bright_cores(self) -> None:
        im = synthetic_image()

        plain = acs.stretch_array(im, base_params())
        reduced = acs.stretch_array(im, base_params(star_reduction=True))

        assert float(reduced.mean()) < float(plain.mean())
        assert float(reduced.max()) > 0.85 * float(plain.max())

    def test_deconvolution_sharpens_without_leaving_the_range(self) -> None:
        plain = acs.stretch_array(synthetic_image(), base_params())
        sharpened = acs.stretch_array(synthetic_image(), base_params(rl_deconvolve=True))

        assert not np.allclose(plain, sharpened)
        assert float(sharpened.min()) >= 0.0
        assert float(sharpened.max()) <= acs.DN_MAX

    def test_vignette_and_gradient_correction_run_on_each_channel(self) -> None:
        im = synthetic_image()
        plain = acs.stretch_array(im, base_params())

        flat = acs.stretch_array(
            im, base_params(vn_correct=True, lg_correct=True, vn_strength=50.0, lg_strength=50.0)
        )

        assert not np.allclose(plain, flat)
        assert float(flat.min()) >= 0.0


class TestRunStage:
    """End-to-end tests of the stage entry point against real FITS files."""

    @staticmethod
    def _install_stage_context(
        monkeypatch: pytest.MonkeyPatch, input_path: Path, output_path: Path
    ) -> None:
        """Point the ``sim_siril`` interface at a real input and output file."""

        class _Def:
            def __init__(self, path: Path) -> None:
                self.full_paths = [str(path)]

        monkeypatch.setattr(
            SirilInterface,
            "Context",
            {"stage_input": [_Def(input_path)], "output": _Def(output_path)},
            raising=False,
        )

    @staticmethod
    def _write_input(path: Path) -> np.ndarray:
        """Write a stretched-style (0..1 float32, planar) FITS input and return its data."""
        data = acs.to_stacked((synthetic_image() / acs.DN_MAX).astype(np.float32))
        header = fits.Header()
        header["INSTRUME"] = "TESTCAM"
        fits.PrimaryHDU(data=data, header=header).writeto(path)
        return data

    def test_run_reads_stretches_and_writes_the_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        input_path = tmp_path / "starless_broadband.fits"
        output_path = tmp_path / "acs_starless_broadband.fits"
        source = self._write_input(input_path)
        self._install_stage_context(monkeypatch, input_path, output_path)

        acs.run({"parameters": SimpleNamespace(ca_correct=False)})

        result = fits.getdata(output_path, header=True)
        assert result is not None
        data, header = result
        assert data.shape == source.shape
        # FITS is written big-endian, so compare the element size rather than the byte order.
        assert data.dtype.kind == "f"
        assert data.dtype.itemsize == 4
        assert float(data.min()) >= 0.0
        assert float(data.max()) <= 1.0
        assert header["INSTRUME"] == "TESTCAM"  # the input header is carried over

    def test_run_honours_parameter_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        input_path = tmp_path / "input.fits"
        output_path = tmp_path / "output.fits"
        self._write_input(input_path)

        self._install_stage_context(monkeypatch, input_path, output_path)
        acs.run({"parameters": SimpleNamespace(ca_correct=False, stretch_type=acs.STRETCH_ASINH)})
        asinh = fits.getdata(output_path)

        self._install_stage_context(monkeypatch, input_path, output_path)
        acs.run({"parameters": SimpleNamespace(ca_correct=False)})
        root_power = fits.getdata(output_path)

        assert asinh is not None
        assert root_power is not None
        assert not np.allclose(asinh, root_power)

    def test_run_rejects_an_out_of_range_parameter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        input_path = tmp_path / "input.fits"
        output_path = tmp_path / "output.fits"
        self._write_input(input_path)
        self._install_stage_context(monkeypatch, input_path, output_path)

        with pytest.raises(ValueError, match="rootpower"):
            acs.run({"parameters": SimpleNamespace(ca_correct=False, rootpower=0)})

        assert not output_path.exists()  # nothing was written

    def test_run_rejects_a_mono_input(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        input_path = tmp_path / "mono.fits"
        output_path = tmp_path / "output.fits"
        fits.PrimaryHDU(data=np.zeros((16, 16), dtype=np.uint16)).writeto(input_path)
        self._install_stage_context(monkeypatch, input_path, output_path)

        with pytest.raises(ValueError, match="3-channel colour image"):
            acs.run({"parameters": SimpleNamespace(ca_correct=False)})

    def test_recipe_script_runs_in_the_restricted_python_sandbox(self, tmp_path: Path) -> None:
        """The recipe's own inline script must work through the real python tool.

        This is the path a real run takes: the machinery dedents the TOML ``script``
        (``processing.py``), the tool compiles it with RestrictedPython, sets
        ``SirilInterface.Context`` from the stage context and provides ``logger``/``context``.
        Calling ``run()`` directly (the other tests here) would not catch a script the sandbox
        rejects.
        """
        from starbash.tool.python import PythonTool

        input_path = tmp_path / "starless_broadband.fits"
        output_path = tmp_path / "acs_starless_broadband.fits"
        source = self._write_input(input_path)

        script = textwrap.dedent(str(recipe_stage()["script"]))
        context: dict[str, Any] = {
            "stage_input": [SimpleNamespace(full_paths=[str(input_path)])],
            "output": SimpleNamespace(full_paths=[str(output_path)]),
            "parameters": SimpleNamespace(ca_correct=False),
        }

        PythonTool().run(script, context, str(tmp_path))

        result = fits.getdata(output_path, header=True)
        assert result is not None
        data, _header = result
        assert data.shape == source.shape
        assert float(data.min()) >= 0.0
        assert float(data.max()) <= 1.0
        assert not np.allclose(data, source)
