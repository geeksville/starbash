"""Tests for reusable crop recipe helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from starbash.recipes import crop


class TestCropRectangle:
    """Tests for centered crop geometry."""

    def test_calculates_centered_eighty_percent_crop(self):
        assert crop.crop_rectangle(1000, 800) == (100, 80, 800, 640)

    def test_full_percent_keeps_the_complete_image(self):
        assert crop.crop_rectangle(101, 99, "100%", "100%") == (0, 0, 101, 99)

    def test_uses_explicit_maximum_dimensions(self):
        assert crop.crop_rectangle(1000, 800, 600, 400) == (200, 200, 600, 400)

    def test_clamps_explicit_dimensions_to_source(self):
        assert crop.crop_rectangle(1000, 800, 1200, 900) == (0, 0, 1000, 800)

    def test_accepts_numeric_strings_as_pixels(self):
        assert crop.crop_rectangle(1000, 800, "600", "400") == (200, 200, 600, 400)

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

        crop.crop_files([source], [destination], rotate_deg=-7)

        commands = run.call_args.args[0]
        assert "rotate -7 -interp=lanczos4" in commands

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
