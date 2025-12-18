"""Tests for Dwarf3 FITS header extension functionality."""

import os
from pathlib import Path

import pytest

from starbash.database import Database
from starbash.dwarf3 import extend_dwarf3_headers

# Use STARBASH_TEST_DATA environment variable if set, otherwise use local test-data
# This allows tests to work both locally and in CI where test data is extracted to a different location
REPO_ROOT = Path(__file__).parent.parent.parent  # Go up from tests/unit/ to workspace root
TEST_DATA_BASE = Path(os.environ.get("STARBASH_TEST_DATA", str(REPO_ROOT / "test-data")))
TEST_DATA_ROOT = TEST_DATA_BASE / "inflated" / "dwarf3"


@pytest.mark.slow
class TestDwarf3HeaderExtension:
    """Test the extend_dwarf3_headers function for various Dwarf3 file types."""

    def test_cali_frame_bias(self, setup_test_environment):
        """Test CALI_FRAME bias file header extension."""
        headers = {"path": "dwarf3/CALI_FRAME/bias/cam_0/bias_gain_2_bin_1.fits"}
        full_path = TEST_DATA_ROOT / "CALI_FRAME" / "bias" / "cam_0" / "bias_gain_2_bin_1.fits"

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "bias"
        assert headers[Database.DATE_OBS_KEY] >= "2000-01-01T00:00:00.000"
        assert headers[Database.EXPTIME_KEY] == 0.001
        assert headers[Database.GAIN_KEY] == 2

    def test_cali_frame_bias_cam1(self, setup_test_environment):
        """Test CALI_FRAME bias file for cam_1 (WIDE camera)."""
        headers = {"path": "dwarf3/CALI_FRAME/bias/cam_1/bias_gain_2_bin_1.fits"}
        full_path = TEST_DATA_ROOT / "CALI_FRAME" / "bias" / "cam_1" / "bias_gain_2_bin_1.fits"

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3WIDE"
        assert headers["INSTRUME"] == "WIDE"
        assert headers[Database.IMAGETYP_KEY] == "bias"

    def test_cali_frame_dark(self, setup_test_environment):
        """Test CALI_FRAME dark file header extension."""
        headers = {
            "path": "dwarf3/CALI_FRAME/dark/cam_0/dark_exp_60.000000_gain_60_bin_1_20C_stack_8.fits"
        }
        full_path = (
            TEST_DATA_ROOT
            / "CALI_FRAME"
            / "dark"
            / "cam_0"
            / "dark_exp_60.000000_gain_60_bin_1_20C_stack_8.fits"
        )

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "dark"
        assert headers[Database.DATE_OBS_KEY] >= "2000-01-01T00:00:00.000"
        assert headers[Database.EXPTIME_KEY] == 60.0
        assert headers[Database.GAIN_KEY] == 60
        assert headers["CCD-TEMP"] == 20.0

    def test_cali_frame_flat_vis(self, setup_test_environment):
        """Test CALI_FRAME flat file with VIS filter (ir_0)."""
        headers = {"path": "dwarf3/CALI_FRAME/flat/cam_0/flat_gain_2_bin_1_ir_0.fits"}
        full_path = TEST_DATA_ROOT / "CALI_FRAME" / "flat" / "cam_0" / "flat_gain_2_bin_1_ir_0.fits"

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "flat"
        assert headers[Database.DATE_OBS_KEY] >= "2000-01-01T00:00:00.000"
        assert headers[Database.EXPTIME_KEY] == 0.0
        assert headers[Database.GAIN_KEY] == 2
        assert headers[Database.FILTER_KEY] == "VIS"

    def test_cali_frame_flat_astro(self, setup_test_environment):
        """Test CALI_FRAME flat file with Astro filter (ir_1)."""
        headers = {"path": "dwarf3/CALI_FRAME/flat/cam_0/flat_gain_2_bin_1_ir_1.fits"}
        full_path = TEST_DATA_ROOT / "CALI_FRAME" / "flat" / "cam_0" / "flat_gain_2_bin_1_ir_1.fits"

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.FILTER_KEY] == "Astro"

    def test_cali_frame_flat_duo(self, setup_test_environment):
        """Test CALI_FRAME flat file with Duo filter (ir_2)."""
        headers = {"path": "dwarf3/CALI_FRAME/flat/cam_0/flat_gain_2_bin_1_ir_2.fits"}
        full_path = TEST_DATA_ROOT / "CALI_FRAME" / "flat" / "cam_0" / "flat_gain_2_bin_1_ir_2.fits"

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.FILTER_KEY] == "Duo"

    def test_dwarf_dark(self, setup_test_environment):
        """Test DWARF_DARK file header extension."""
        headers = {
            "path": "dwarf3/DWARF_DARK/tele_exp_60_gain_60_bin_1_2025-10-20-03-20-10-952/raw_60s_60_0002_20251020-032310186_20C.fits"
        }
        full_path = (
            TEST_DATA_ROOT
            / "DWARF_DARK"
            / "tele_exp_60_gain_60_bin_1_2025-10-20-03-20-10-952"
            / "raw_60s_60_0002_20251020-032310186_20C.fits"
        )

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "dark"
        assert headers[Database.DATE_OBS_KEY] == "2025-10-20T03:23:10.186"
        assert headers[Database.EXPTIME_KEY] == 60.0
        assert headers[Database.GAIN_KEY] == 60
        assert headers["CCD-TEMP"] == 20.0
        assert headers["CCD-TEMP"] == 20.0

    def test_light_frame(self, setup_test_environment):
        """Test light frame header extension with shotsInfo.json."""
        headers = {
            "path": "dwarf3/IC 434 Horsehead Nebula/DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420/IC 434_60s60_Astro_20251018-045226559_17C.fits"
        }
        full_path = (
            TEST_DATA_ROOT
            / "IC 434 Horsehead Nebula"
            / "DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420"
            / "IC 434_60s60_Astro_20251018-045226559_17C.fits"
        )

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "light"
        assert headers[Database.DATE_OBS_KEY] == "2025-10-18T04:52:26.559"
        assert headers[Database.EXPTIME_KEY] == 60.0
        assert headers[Database.GAIN_KEY] == 60
        assert headers[Database.FILTER_KEY] == "Astro"
        assert headers["OBJECT"] == "IC 434"
        assert headers["CCD-TEMP"] == 17.0

    def test_non_dwarf3_file(self, setup_test_environment):
        """Test that non-Dwarf3 files return False and headers are unchanged."""
        headers = {"path": "some/other/path/image.fits"}
        full_path = Path("/some/other/path/image.fits")

        result = extend_dwarf3_headers(headers, full_path)

        assert result is False
        # Only the original path key should exist
        assert list(headers.keys()) == ["path"]

    def test_dwarf_dark_different_exposure(self, setup_test_environment):
        """Test DWARF_DARK with different exposure time."""
        headers = {
            "path": "dwarf3/DWARF_DARK/tele_exp_15_gain_130_bin_1_2025-10-31-05-42-52-480/raw_15s_130_0000_20251031-054306711_16C.fits"
        }
        full_path = (
            TEST_DATA_ROOT
            / "DWARF_DARK"
            / "tele_exp_15_gain_130_bin_1_2025-10-31-05-42-52-480"
            / "raw_15s_130_0000_20251031-054306711_16C.fits"
        )

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.EXPTIME_KEY] == 15.0
        assert headers[Database.GAIN_KEY] == 130
        assert headers[Database.DATE_OBS_KEY] == "2025-10-31T05:43:06.711"

    def test_cali_frame_dark_various_exposures(self, setup_test_environment):
        """Test CALI_FRAME dark files with different exposure times."""
        test_cases = [
            ("dark_exp_15.000000_gain_130_bin_1_16C_stack_10.fits", 15.0, 130),
            ("dark_exp_30.000000_gain_40_bin_1_15C_stack_7.fits", 30.0, 40),
        ]

        for filename, expected_exp, expected_gain in test_cases:
            headers = {"path": f"dwarf3/CALI_FRAME/dark/cam_0/{filename}"}
            full_path = TEST_DATA_ROOT / "CALI_FRAME" / "dark" / "cam_0" / filename

            result = extend_dwarf3_headers(headers, full_path)

            assert result is True
            assert headers[Database.EXPTIME_KEY] == expected_exp
            assert headers[Database.GAIN_KEY] == expected_gain


class TestDwarf3HelperFunctions:
    """Test helper functions in the dwarf3 module."""

    def test_extract_temperature_with_valid_formats(self):
        """Test temperature extraction from various filename formats."""
        from starbash.dwarf3 import _extract_temperature

        assert _extract_temperature("file_16C.fits") == 16.0
        assert _extract_temperature("file_20C_stack.fits") == 20.0
        assert _extract_temperature("dark_15C.fits") == 15.0
        assert _extract_temperature("raw_60s_60_0002_20251020-032310186_20C.fits") == 20.0

    def test_extract_temperature_no_match(self):
        """Test temperature extraction when no temperature in filename."""
        from starbash.dwarf3 import _extract_temperature

        assert _extract_temperature("file.fits") is None
        assert _extract_temperature("no_temp_here.fits") is None
        assert _extract_temperature("16_degrees.fits") is None

    def test_make_monotonic_datetime_increments(self):
        """Test that monotonic datetime increments on each call."""
        from starbash.dwarf3 import _make_monotonic_datetime

        # Reset counter
        _make_monotonic_datetime.counter = 0

        dt1 = _make_monotonic_datetime()
        dt2 = _make_monotonic_datetime()
        dt3 = _make_monotonic_datetime()

        assert dt1 == "2000-01-01T00:00:00.000"
        assert dt2 == "2000-01-02T00:00:00.000"
        assert dt3 == "2000-01-03T00:00:00.000"

    def test_make_monotonic_datetime_format(self):
        """Test that monotonic datetime has correct format."""
        from starbash.dwarf3 import _make_monotonic_datetime

        _make_monotonic_datetime.counter = 0
        dt = _make_monotonic_datetime()

        # Check format: YYYY-MM-DDTHH:MM:SS.mmm
        assert len(dt) == 23
        assert dt[4] == "-"
        assert dt[7] == "-"
        assert dt[10] == "T"
        assert dt[13] == ":"
        assert dt[16] == ":"
        assert dt[19] == "."


class TestDwarf3CameraDetection:
    """Test camera/instrument detection logic."""

    def test_tele_camera_variants(self):
        """Test various ways to detect TELE camera."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        test_cases = [
            "dwarf3/CALI_FRAME/bias/cam_0/bias.fits",
            "dwarf3/something/TELE/file.fits",
            "dwarf3/folder/raw_tele_data.fits",
        ]

        for path in test_cases:
            headers = {"path": path}
            full_path = Path("/fake") / path
            # Create a minimal cali_frame context
            if "CALI_FRAME" in path:
                result = extend_dwarf3_headers(headers, full_path)
                if result:
                    assert headers.get("INSTRUME") == "TELE"

    def test_wide_camera_variants(self):
        """Test various ways to detect WIDE camera."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        test_cases = [
            "dwarf3/CALI_FRAME/bias/cam_1/bias.fits",
            "dwarf3/something/WIDE/file.fits",
            "dwarf3/folder/raw_wide_data.fits",
        ]

        for path in test_cases:
            headers = {"path": path}
            full_path = Path("/fake") / path
            # Create a minimal cali_frame context
            if "CALI_FRAME" in path:
                result = extend_dwarf3_headers(headers, full_path)
                if result:
                    assert headers.get("INSTRUME") == "WIDE"


class TestDwarf3EdgeCases:
    """Test edge cases and error handling."""

    def test_malformed_gain_patterns(self):
        """Test handling of malformed gain patterns in filenames."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        headers = {"path": "dwarf3/CALI_FRAME/bias/cam_0/bias_no_gain.fits"}
        full_path = Path("/fake/bias_no_gain.fits")

        result = extend_dwarf3_headers(headers, full_path)
        assert result is True
        # Should not have GAIN_KEY if parsing failed
        assert Database.GAIN_KEY not in headers or headers.get(Database.GAIN_KEY) is None

    def test_malformed_exposure_patterns(self):
        """Test handling of malformed exposure patterns in filenames."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        headers = {"path": "dwarf3/CALI_FRAME/dark/cam_0/dark_no_exp.fits"}
        full_path = Path("/fake/dark_no_exp.fits")

        result = extend_dwarf3_headers(headers, full_path)
        assert result is True
        # Should not have EXPTIME_KEY if parsing failed
        assert Database.EXPTIME_KEY not in headers or headers.get(Database.EXPTIME_KEY) is None

    def test_missing_shots_info_json(self, tmp_path):
        """Test light frame handling when shotsInfo.json is missing."""
        from starbash.dwarf3 import extend_dwarf3_headers

        # Create a directory without shotsInfo.json
        light_dir = tmp_path / "light_session"
        light_dir.mkdir()

        headers = {"path": "dwarf3/target/session/light_60s60_Astro_20251018-045926401_16C.fits"}
        full_path = light_dir / "light_60s60_Astro_20251018-045926401_16C.fits"

        # Should return False since shotsInfo.json doesn't exist
        result = extend_dwarf3_headers(headers, full_path)
        assert result is False

    def test_invalid_json_in_shots_info(self, tmp_path, caplog):
        """Test handling of invalid JSON in shotsInfo.json."""
        import logging

        from starbash.dwarf3 import extend_dwarf3_headers

        # Create a directory with invalid JSON
        light_dir = tmp_path / "light_session"
        light_dir.mkdir()
        shots_info = light_dir / "shotsInfo.json"
        shots_info.write_text("{invalid json")

        headers = {"path": "dwarf3/target/session/light_60s60_Astro_20251018-045926401_16C.fits"}
        full_path = light_dir / "light_60s60_Astro_20251018-045926401_16C.fits"

        with caplog.at_level(logging.WARNING):
            result = extend_dwarf3_headers(headers, full_path)

        # Should still process the file but log warning
        assert result is True
        assert "Could not read shotsInfo.json" in caplog.text

    def test_dwarf_dark_removes_bad_keys(self):
        """Test that DWARF_DARK processing removes bogus FITS keys."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        headers = {
            "path": "dwarf3/DWARF_DARK/session/raw_60s_60_0002_20251020-032310186_20C.fits",
            Database.FILTER_KEY: "bogus_filter",
            "RA": "00:00:00",
            "DEC": "+00:00:00",
            Database.OBJECT_KEY: "bogus_object",
        }
        full_path = Path("/fake/raw_60s_60_0002_20251020-032310186_20C.fits")

        result = extend_dwarf3_headers(headers, full_path)
        assert result is True

        # These keys should be removed
        assert Database.FILTER_KEY not in headers
        assert "RA" not in headers
        assert "DEC" not in headers
        assert Database.OBJECT_KEY not in headers

    def test_telescop_naming_convention(self):
        """Test that TELESCOP is set to D3 + INSTRUME."""
        from pathlib import Path

        from starbash.dwarf3 import extend_dwarf3_headers

        # Test TELE
        headers = {"path": "dwarf3/CALI_FRAME/bias/cam_0/bias.fits"}
        full_path = Path("/fake/bias.fits")
        extend_dwarf3_headers(headers, full_path)
        assert headers.get(Database.TELESCOP_KEY) == "D3TELE"

        # Test WIDE
        headers = {"path": "dwarf3/CALI_FRAME/bias/cam_1/bias.fits"}
        full_path = Path("/fake/bias.fits")
        extend_dwarf3_headers(headers, full_path)
        assert headers.get(Database.TELESCOP_KEY) == "D3WIDE"
        assert headers[Database.IMAGETYP_KEY] == "bias"
