"""Tests for candidate ranking logic in Starbash.score_candidates."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from starbash import paths
from starbash.app import Starbash
from starbash.database import Database


@pytest.fixture
def setup_test_environment(tmp_path):
    """Isolated config/data directories for ranking tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    paths.set_test_directories(config_dir, data_dir)
    # Disable analytics to avoid external touches
    (config_dir / "starbash.toml").write_text("[analytics]\nenabled = false\n")
    yield {"config_dir": config_dir, "data_dir": data_dir}
    paths.set_test_directories(None, None)


def make_ref_session(**meta: Any):
    """Helper to create a reference session structure with metadata dict."""
    return {"metadata": meta}


def test_gain_scoring_prefers_exact_match(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 2000,
            }
        )
        candidates = [
            {  # exact gain match
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-02T00:00:00",
                "CCD-TEMP": -10.5,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 2000,
            },
            {  # gain diff
                Database.GAIN_KEY: 95,
                Database.DATE_OBS_KEY: "2025-01-02T00:00:00",
                "CCD-TEMP": -10.5,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 2000,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        # First should be the exact match (higher score)
        assert scored[0].candidate[Database.GAIN_KEY] == 100
        assert any("gain match" in s.reason for s in scored)


def test_temperature_scoring_prefers_closer(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                "CCD-TEMP": -10.0,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        candidates = [
            {
                "CCD-TEMP": -10.2,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                "CCD-TEMP": -15.0,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        # Smaller temp diff should rank higher
        assert scored[0].candidate["CCD-TEMP"] == -10.2
        assert any("temp" in s.reason for s in scored)


def test_time_scoring_prefers_close_dates(setup_test_environment):
    with Starbash() as app:
        ref_date = datetime(2025, 1, 1, 0, 0, 0)
        ref = make_ref_session(
            **{
                Database.DATE_OBS_KEY: ref_date.isoformat(),
                "CCD-TEMP": -10.0,
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        close_date = (ref_date + timedelta(hours=2)).isoformat()
        far_date = (ref_date + timedelta(days=30)).isoformat()
        candidates = [
            {
                Database.DATE_OBS_KEY: close_date,
                "CCD-TEMP": -10.0,
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                Database.DATE_OBS_KEY: far_date,
                "CCD-TEMP": -10.0,
                Database.GAIN_KEY: 100,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        assert scored[0].candidate[Database.DATE_OBS_KEY] == close_date
        assert any("time" in s.reason for s in scored)


def test_instrument_mismatch_penalty(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        candidates = [
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T02:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T02:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "DifferentScope",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        # Mismatching instrument should have lower score and reason
        assert scored[0].candidate["INSTRUME"] == "ScopeA"
        assert any("instrument mismatch" in s.reason for s in scored)


def test_camera_mismatch_penalty(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "CameraA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        candidates = [
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "CameraA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "DifferentCam",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        assert scored[0].candidate["INSTRUME"] == "CameraA"
        assert any("camera mismatch" in s.reason for s in scored)


def test_camera_dimensions_excludes_mismatch(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 2000,
            }
        )
        candidates = [
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T02:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 2000,
            },
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T02:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 3000,
                "NAXIS2": 1999,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        # Second candidate should be excluded due to NAXIS2 mismatch
        assert len(scored) == 1
        assert scored[0].candidate["NAXIS2"] == 2000


def test_flat_filter_penalty_only_for_flat(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "FLAT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        candidates = [
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "FLAT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "OIII",
                Database.IMAGETYP_KEY: "FLAT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        assert len(scored) == 2
        # Ha filter match should rank higher than OIII mismatch
        assert scored[0].candidate[Database.FILTER_KEY] == "Ha"
    assert any("filter mismatch" in s.reason for s in scored)


def test_flat_filter_not_applied_to_non_flat(setup_test_environment):
    with Starbash() as app:
        ref = make_ref_session(
            **{
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T00:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            }
        )
        candidates = [
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
            {
                Database.GAIN_KEY: 100,
                Database.DATE_OBS_KEY: "2025-01-01T01:00:00",
                "CCD-TEMP": -10.0,
                Database.FILTER_KEY: "OIII",
                Database.IMAGETYP_KEY: "LIGHT",
                "INSTRUME": "ScopeA",
                "NAXIS": 2,
                "NAXIS1": 100,
                "NAXIS2": 100,
            },
        ]
        scored = app.score_candidates(candidates, ref)
        # Both candidates included; no flat filter mismatch reason since imagetyp != FLAT
        assert len(scored) == 2
        assert not any("flat filter mismatch" in s.reason for s in scored)
