"""Tests for reusable crop recipe helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from starbash.recipes import crop


class TestCropRectangle:
    """Tests for centered crop geometry."""

    def test_calculates_centered_ninety_percent_crop(self):
        assert crop.crop_rectangle(6248, 4176) == (312, 209, 5623, 3758)

    def test_full_percent_keeps_the_complete_image(self):
        assert crop.crop_rectangle(101, 99, 100) == (0, 0, 101, 99)

    def test_uses_explicit_maximum_dimensions(self):
        assert crop.crop_rectangle(1000, 800, 90, 600, 400) == (200, 200, 600, 400)

    def test_clamps_explicit_dimensions_to_source(self):
        assert crop.crop_rectangle(1000, 800, 10, 1200, 900) == (0, 0, 1000, 800)

    def test_uses_width_for_both_axes_when_height_is_missing(self):
        assert crop.crop_rectangle(1000, 800, 90, 600) == (200, 100, 600, 600)

    def test_uses_height_for_both_axes_when_width_is_missing(self):
        assert crop.crop_rectangle(1000, 800, 90, None, 400) == (300, 200, 400, 400)

    @pytest.mark.parametrize("percent", [0, -1, 101])
    def test_rejects_invalid_percent(self, percent):
        with pytest.raises(ValueError, match="between 1 and 100"):
            crop.crop_rectangle(100, 100, percent)

    def test_rejects_non_integer_percent(self):
        with pytest.raises(ValueError, match="integer"):
            crop.crop_rectangle(100, 100, 90.5)

    @pytest.mark.parametrize("name", ["crop_width", "crop_height"])
    @pytest.mark.parametrize("value", [True, 0, -1, 10.5, "600"])
    def test_rejects_invalid_explicit_dimensions(self, name, value):
        dimensions = {name: value}
        with pytest.raises(ValueError, match=f"{name} must be a positive integer"):
            crop.crop_rectangle(100, 100, crop_width=dimensions.get("crop_width"), crop_height=dimensions.get("crop_height"))

    def test_rejects_invalid_dimensions(self):
        with pytest.raises(ValueError, match="positive"):
            crop.crop_rectangle(0, 100)

    def test_rejects_crop_that_rounds_to_zero(self):
        with pytest.raises(ValueError, match="empty crop"):
            crop.crop_rectangle(1, 100, 1)


class TestCropFiles:
    """Tests for generated Siril crop commands."""

    def test_builds_crop_then_rotate_commands(self, monkeypatch, tmp_path):
        source = tmp_path / "stacked file.fits"
        destination = tmp_path / "crop_stacked file.fits"
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files([source], [destination], crop_percent=90, rotate_deg=12.5)

        commands = run.call_args.args[0]
        assert commands.index(f'load "{source}"') < commands.index("crop 50 40 900 720")
        assert commands.index("crop 50 40 900 720") < commands.index(
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

        crop.crop_files([first, second], outputs, crop_percent=100)

        commands = run.call_args.args[0]
        assert "rotate" not in commands
        assert f'save "{outputs[0]}"' in commands
        assert f'save "{outputs[1]}"' in commands

    def test_uses_explicit_dimensions_and_warns_once_per_invocation(
        self, monkeypatch, tmp_path, caplog
    ):
        sources = [tmp_path / "first.fits", tmp_path / "second.fits"]
        outputs = [tmp_path / "crop_first.fits", tmp_path / "crop_second.fits"]
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        with caplog.at_level("WARNING"):
            crop.crop_files(sources, outputs, crop_percent=90, crop_width=600)

        commands = run.call_args.args[0]
        assert commands.count("crop 200 100 600 600") == 2
        assert sum("crop_height was not specified" in message for message in caplog.messages) == 1
        assert sum("crop_percent is ignored" in message for message in caplog.messages) == 1

    def test_uses_height_only_dimension_mode(self, monkeypatch, tmp_path):
        run = MagicMock()
        monkeypatch.setattr(crop.siril, "run", run)
        monkeypatch.setattr(crop, "read_dimensions", lambda path: (1000, 800))
        monkeypatch.setattr(crop, "context", {"process_dir": str(tmp_path)})

        crop.crop_files(
            [tmp_path / "input.fits"],
            [tmp_path / "output.fits"],
            crop_height=400,
        )

        assert "crop 300 200 400 400" in run.call_args.args[0]

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
