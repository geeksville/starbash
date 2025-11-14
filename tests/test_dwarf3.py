"""Tests for Dwarf3 FITS header extension functionality."""

from pathlib import Path

import pytest

from starbash.database import Database
from starbash.dwarf3 import extend_dwarf3_headers

# Calculate repository root relative to this test file
REPO_ROOT = Path(__file__).parent.parent
TEST_DATA_ROOT = REPO_ROOT / "test-data" / "inflated" / "dwarf3"


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
            "path": "dwarf3/IC 434 Horsehead Nebula/DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420/IC 434_60s60_Astro_20251018-045926401_16C.fits"
        }
        full_path = (
            TEST_DATA_ROOT
            / "IC 434 Horsehead Nebula"
            / "DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420"
            / "IC 434_60s60_Astro_20251018-045926401_16C.fits"
        )

        result = extend_dwarf3_headers(headers, full_path)

        assert result is True
        assert headers[Database.TELESCOP_KEY] == "D3TELE"
        assert headers["INSTRUME"] == "TELE"
        assert headers[Database.IMAGETYP_KEY] == "light"
        assert headers[Database.DATE_OBS_KEY] == "2025-10-18T04:59:26.401"
        assert headers[Database.EXPTIME_KEY] == 60.0
        assert headers[Database.GAIN_KEY] == 60
        assert headers[Database.FILTER_KEY] == "Astro"
        assert headers["OBJECT"] == "IC 434"
        assert headers["CCD-TEMP"] == 16.0

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
            assert headers[Database.IMAGETYP_KEY] == "dark"
