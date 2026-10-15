"""Tests for reusable crop recipe helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from astropy.io import fits

from starbash.fits import read_dimensions
from starbash.recipes import crop
from starbash.tool import tools

#: Real-Siril tests are skipped where Siril is not installed (CI installs it).
SIRIL_AVAILABLE = tools["siril"].is_available


class TestCropRectangle:
    """Tests for centered crop geometry."""

    def test_calculates_centered_eighty_percent_crop(self):
        assert crop.crop_rectangle(1000, 800) == (100, 80, 800, 640)

    def test_full_percent_rounds_both_dimensions_to_a_multiple_of_16(self):
        # 101x99 is not aligned, so each axis drops to 96 and the rectangle stays
        # centered.
        assert crop.crop_rectangle(101, 99, "100%", "100%") == (2, 1, 96, 96)

    def test_rounds_dimensions_down_to_the_nearest_multiple_of_16(self):
        # 600 -> 592; 400 is already aligned.
        assert crop.crop_rectangle(1000, 800, 600, 400) == (204, 200, 592, 400)

    def test_rounds_percentage_dimensions_down_to_a_multiple_of_16(self):
        # 85% of 1000 is 850, which drops to 848; 100% of 800 is already aligned.
        assert crop.crop_rectangle(1000, 800, "85%", "100%") == (76, 0, 848, 800)

    def test_rounds_height_down_to_a_multiple_of_16(self):
        # 1000 -> 992 (x offset 4); 813 -> 800 (y offset 6).
        assert crop.crop_rectangle(1000, 813, "100%", "100%") == (4, 6, 992, 800)

    def test_leaves_already_aligned_dimensions_untouched(self):
        assert crop.crop_rectangle(1000, 800, 800, 400) == (100, 200, 800, 400)

    def test_clamps_explicit_dimensions_to_source(self):
        # 1000 is not aligned, so a full-width request still yields 992.
        assert crop.crop_rectangle(1000, 800, 1200, 900) == (4, 0, 992, 800)

    def test_accepts_numeric_strings_as_pixels(self):
        assert crop.crop_rectangle(1000, 800, "600", "400") == (204, 200, 592, 400)

    def test_supports_mixed_percentage_and_pixel_sizes(self):
        assert crop.crop_rectangle(1000, 800, "80%", 400) == (100, 200, 800, 400)

    @pytest.mark.parametrize("value", [True, 0, -1, 10.5, "", "0", "-1", "80px", "101%"])
    def test_rejects_invalid_crop_sizes(self, value):
        with pytest.raises(ValueError, match="crop_width"):
            crop.crop_rectangle(100, 100, crop_width=value)

    def test_rejects_invalid_dimensions(self):
        with pytest.raises(ValueError, match="positive"):
            crop.crop_rectangle(0, 100)

    def test_rejects_crop_that_rounds_to_zero(self):
        with pytest.raises(ValueError, match="empty crop"):
            crop.crop_rectangle(1, 100, "0.5%")

    def test_rejects_width_that_rounds_down_to_zero(self):
        with pytest.raises(ValueError, match="empty crop"):
            crop.crop_rectangle(1000, 800, 15, 400)

    def test_rejects_height_that_rounds_down_to_zero(self):
        with pytest.raises(ValueError, match="empty crop"):
            crop.crop_rectangle(1000, 800, 400, 15)


class TestRoundDownToMultiple:
    """Tests for the dimension alignment helper."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(101, 96), (96, 96), (95, 80), (16, 16), (15, 0), (0, 0)],
    )
    def test_rounds_down(self, value, expected):
        assert crop.round_down_to_multiple(value, crop.CROP_MULTIPLE) == expected


class TestRotationCommand:
    """Tests for the Siril rotation command builder."""

    @pytest.mark.parametrize(
        ("angle", "expected"),
        [(0, 0.0), (360, 0.0), (-360, 0.0), (720, 0.0), (450, 90.0), (-7, 353.0), (12.5, 12.5)],
    )
    def test_normalizes_away_from_sirils_rejected_ranges(self, angle, expected):
        # Siril rejects negative and >= 360 angles and aborts the whole script.
        assert crop.normalize_rotation(angle) == pytest.approx(expected)

    @pytest.mark.parametrize("angle", [0, 360, -360, 720])
    def test_a_full_turn_emits_no_rotate_command(self, angle):
        assert crop.rotation_command(angle) is None

    @pytest.mark.parametrize("angle", [90, 270, 180, -90, -270, 450, 90.0, 270.0, 180.0])
    def test_quarter_turns_keep_the_whole_rotated_canvas(self, angle):
        command = crop.rotation_command(angle)
        assert command is not None
        # -nocrop is what makes 90/270 swap the output width and height.
        assert command == f"rotate {crop.normalize_rotation(angle):g} -interp=lanczos4 -nocrop"

    @pytest.mark.parametrize("angle", [12.5, 45, 1, 89.5, -7, 359, 100])
    def test_other_angles_keep_sirils_crop_to_fit(self, angle):
        command = crop.rotation_command(angle)
        assert command == f"rotate {crop.normalize_rotation(angle):g} -interp=lanczos4"

    @pytest.mark.parametrize(
        ("angle", "expected"),
        [
            (0.0, True),
            (90.0, True),
            (180.0, True),
            (270.0, True),
            (90.5, False),
            (269.999999, False),
        ],
    )
    def test_is_quarter_turn_only_matches_exact_multiples(self, angle, expected):
        assert crop.is_quarter_turn(angle) is expected


class TestCropFiles:
    """Tests for generated Siril crop commands."""

    def test_builds_crop_then_rotate_commands(self, monkeypatch, tmp_path):
        source = tmp_path / "stacked file.fits"
        destination = tmp_path / "crop_stacked file.fits"
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([source], [destination], rotate_deg=12.5)

        commands = run.call_args.args[0]
        assert commands.index(f'load "{source}"') < commands.index("crop 100 80 800 640")
        assert commands.index("crop 100 80 800 640") < commands.index(
            "rotate 12.5 -interp=lanczos4"
        )
        assert commands.index("rotate 12.5 -interp=lanczos4") < commands.index(
            f'save "{destination}"'
        )
        assert run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_processes_multiple_pairs(self, monkeypatch, tmp_path):
        first = tmp_path / "first.fit"
        second = tmp_path / "second.fits"
        outputs = [tmp_path / "crop_first.fit", tmp_path / "crop_second.fits"]
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([first, second], outputs, crop_width="100%", crop_height="100%")

        commands = run.call_args.args[0]
        assert "rotate" not in commands
        assert f'save "{outputs[0]}"' in commands
        assert f'save "{outputs[1]}"' in commands

    def test_uses_lanczos_for_nonzero_rotation(self, monkeypatch, tmp_path):
        source = tmp_path / "input.fits"
        destination = tmp_path / "output.fits"
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([source], [destination], rotate_deg=12.5)

        commands = run.call_args.args[0]
        assert "rotate 12.5 -interp=lanczos4" in commands

    def test_quarter_turn_keeps_the_whole_rotated_canvas(self, monkeypatch, tmp_path):
        """A 90 degree rotation must not be silently cropped back to the source size."""
        source = tmp_path / "input.fits"
        destination = tmp_path / "output.fits"
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([source], [destination], rotate_deg=90)

        commands = run.call_args.args[0]
        rotate = commands.index("rotate 90 -interp=lanczos4 -nocrop")
        assert commands.index("crop 100 80 800 640") < rotate
        assert rotate < commands.index(f'save "{destination}"')

    @pytest.mark.parametrize("angle", [0, 360, -360])
    def test_full_turns_are_a_no_op(self, monkeypatch, tmp_path, angle):
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([tmp_path / "in.fits"], [tmp_path / "out.fits"], rotate_deg=angle)

        assert "rotate" not in run.call_args.args[0]

    def test_normalizes_negative_rotation_for_siril(self, monkeypatch, tmp_path):
        source = tmp_path / "input.fits"
        destination = tmp_path / "output.fits"
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([source], [destination], rotate_deg=-7)

        commands = run.call_args.args[0]
        # -7 would abort the whole Siril script; 353 crops to fit like any angle.
        assert "rotate 353 -interp=lanczos4" in commands

    def test_negative_quarter_turn_keeps_the_whole_canvas(self, monkeypatch, tmp_path):
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([tmp_path / "in.fits"], [tmp_path / "out.fits"], rotate_deg=-90)

        assert "rotate 270 -interp=lanczos4 -nocrop" in run.call_args.args[0]

    def test_rejects_mismatched_paths_without_running_siril(self, monkeypatch, tmp_path):
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        with pytest.raises(ValueError, match="equal numbers"):
            crop.crop_files([Path("input.fits")], [Path("output-1.fits"), Path("output-2.fits")])

        run.assert_not_called()

    @pytest.mark.parametrize("angle", [float("nan"), float("inf")])
    def test_rejects_non_finite_rotation(self, angle, monkeypatch, tmp_path):
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        with pytest.raises(ValueError, match="finite"):
            crop.crop_files([Path("input.fits")], [Path("output.fits")], rotate_deg=angle)

        run.assert_not_called()


@pytest.mark.skipif(not SIRIL_AVAILABLE, reason="Siril is not installed")
class TestCropFilesWithSiril:
    """Run the real Siril binary: the resulting dimensions are the whole point."""

    @staticmethod
    def _write_input(path: Path, width: int, height: int) -> np.ndarray:
        """A FITS whose pixels stay in [0, 1] so Siril does not rescale them."""
        y, x = np.mgrid[0:height, 0:width]
        pixels = ((y * width + x).astype(np.float32) / 1e6).astype(np.float32)
        fits.PrimaryHDU(pixels).writeto(path)
        return pixels

    def _crop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rotate_deg: int | float
    ) -> tuple[Path, np.ndarray]:
        source = tmp_path / "stacked.fits"
        # 240x128 is already a multiple of CROP_MULTIPLE, so "100%" keeps it all.
        original = self._write_input(source, 240, 128)
        output = tmp_path / "crop_stacked.fits"
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})
        crop.crop_files(
            [source],
            [output],
            rotate_deg=rotate_deg,
            crop_width="100%",
            crop_height="100%",
        )
        return output, original

    def test_90_degree_rotation_swaps_width_and_height(self, monkeypatch, tmp_path):
        """Siril crops back to the source size unless -nocrop is passed."""
        output, original = self._crop(monkeypatch, tmp_path, 90)

        assert read_dimensions(output) == (128, 240)  # swapped, not (240, 128)
        rotated = np.asarray(fits.getdata(output))
        np.testing.assert_allclose(rotated, np.rot90(original, 1), atol=1e-6)

    def test_270_degree_rotation_swaps_width_and_height(self, monkeypatch, tmp_path):
        output, original = self._crop(monkeypatch, tmp_path, 270)

        assert read_dimensions(output) == (128, 240)
        rotated = np.asarray(fits.getdata(output))
        np.testing.assert_allclose(rotated, np.rot90(original, -1), atol=1e-6)

    def test_180_degree_rotation_keeps_the_canvas_and_is_lossless(self, monkeypatch, tmp_path):
        output, original = self._crop(monkeypatch, tmp_path, 180)

        assert read_dimensions(output) == (240, 128)
        rotated = np.asarray(fits.getdata(output))
        np.testing.assert_allclose(rotated, np.rot90(original, 2), atol=1e-6)

    def test_arbitrary_rotation_keeps_the_crop_dimensions(self, monkeypatch, tmp_path):
        """Non-quarter turns still fit the result into the crop rectangle."""
        output, _ = self._crop(monkeypatch, tmp_path, 12)

        assert read_dimensions(output) == (240, 128)
