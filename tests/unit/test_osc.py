"""Tests for the OSC recipe helpers."""

from unittest.mock import MagicMock

import pytest

from starbash.recipes import osc


class TestCropRectangle:
    """Tests for the centered final-image crop."""

    def test_calculates_centered_ninety_percent_crop(self):
        """The crop keeps 90% of each image dimension."""
        assert osc._crop_rectangle(6248, 4176) == (312, 209, 5623, 3758)

    def test_rejects_invalid_dimensions(self):
        """Invalid image dimensions cannot produce a crop command."""
        with pytest.raises(ValueError, match="positive"):
            osc._crop_rectangle(0, 100)


class TestCropFinalFiles:
    """Tests for the Siril commands that crop final outputs in place."""

    def test_loads_crops_and_saves_each_file(self, monkeypatch, tmp_path):
        """Each final file is cropped using dimensions read from that file."""
        first = tmp_path / "stacked_Ha.fits"
        second = tmp_path / "stacked_OIII.fits"
        run = MagicMock()
        monkeypatch.setattr(osc.siril, "run", run)
        monkeypatch.setattr(osc, "context", {"process_dir": str(tmp_path)})
        monkeypatch.setattr(
            osc,
            "read_dimensions",
            lambda path: (1000, 800) if path == first else (2000, 1200),
        )

        osc._crop_final_files([first, second])

        commands = run.call_args.args[0]
        assert f'load "{first}"' in commands
        assert "crop 50 40 900 720" in commands
        assert f'save "{first}"' in commands
        assert f'load "{second}"' in commands
        assert "crop 100 60 1800 1080" in commands
        assert f'save "{second}"' in commands
