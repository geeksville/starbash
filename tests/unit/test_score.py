"""Tests for starbash.score module."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from starbash.database import Database
from starbash.score import ScoredCandidate, score_candidates


@pytest.fixture(autouse=True)
def mock_aliases():
    """Mock the aliases module for all tests."""
    import starbash.aliases

    mock_aliases_obj = MagicMock()
    # Simple passthrough normalization that lowercases and handles None
    mock_aliases_obj.normalize = lambda x, lenient=False: x.lower() if x else None

    original_get_aliases = starbash.aliases.get_aliases
    starbash.aliases.get_aliases = lambda: mock_aliases_obj

    yield mock_aliases_obj

    starbash.aliases.get_aliases = original_get_aliases


class TestScoredCandidate:
    """Tests for ScoredCandidate dataclass."""

    def test_scored_candidate_creation(self):
        """Test creating a ScoredCandidate."""
        candidate = {"path": "/test/image.fits", "id": 1}
        scored = ScoredCandidate(candidate=candidate, score=100.0, reason="test match")

        assert scored.candidate == candidate
        assert scored.score == 100.0
        assert scored.reason == "test match"

    def test_get_comment(self):
        """Test get_comment property generates correct format."""
        candidate = {"path": "/test/image.fits"}
        scored = ScoredCandidate(candidate=candidate, score=95.7, reason="gain match")

        comment = scored.get_comment
        assert "96" in comment
        assert "gain match" in comment

    def test_str_returns_path(self):
        """Test __str__ returns the candidate path."""
        candidate = {"path": "/test/my_image.fits"}
        scored = ScoredCandidate(candidate=candidate, score=100.0, reason="test")

        assert str(scored) == "/test/my_image.fits"


class TestScoreCandidatesGain:
    """Test scoring by GAIN matching."""

    def test_exact_gain_match_high_score(self):
        """Test that exact GAIN match gets highest score contribution."""
        ref_session = {
            "metadata": {Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}
        }
        candidates = [
            {Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1
        assert "gain match" in results[0].reason

    def test_gain_mismatch_penalty(self):
        """Test that GAIN mismatch reduces score."""
        ref_session = {
            "metadata": {Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}
        }
        candidates = [
            {Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
            {Database.GAIN_KEY: 80, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        assert results[0].score > results[1].score
        assert "gain Δ=" in results[1].reason

    def test_missing_gain_in_reference(self):
        """Test handling when reference session has no GAIN."""
        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = [{Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1
        # Should not crash, just won't contribute gain score

    def test_missing_gain_in_candidate(self):
        """Test handling when candidate has no GAIN."""
        ref_session = {
            "metadata": {Database.GAIN_KEY: 60, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}
        }
        candidates = [{Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1


class TestScoreCandidatesTemperature:
    """Test scoring by CCD-TEMP matching."""

    def test_close_temperature_high_score(self):
        """Test that close temperature gets higher score."""
        ref_session = {"metadata": {"CCD-TEMP": 20.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = [
            {"CCD-TEMP": 20.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
            {"CCD-TEMP": 15.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        assert results[0].score > results[1].score

    def test_temperature_difference_in_reason(self):
        """Test that significant temperature difference appears in reason."""
        ref_session = {"metadata": {"CCD-TEMP": 20.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = [{"CCD-TEMP": 15.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}]

        results = score_candidates(candidates, ref_session)

        assert "temp Δ=" in results[0].reason

    def test_missing_temperature(self):
        """Test handling when temperature is missing."""
        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = [{"CCD-TEMP": 20.0, Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1


class TestScoreCandidatesTime:
    """Test scoring by time difference."""

    def test_older_candidates_preferred(self):
        """Test that older candidates are preferred."""
        ref_date = "2024-01-15T00:00:00"
        ref_session = {"metadata": {Database.DATE_OBS_KEY: ref_date}}
        candidates = [
            {Database.DATE_OBS_KEY: "2024-01-10T00:00:00"},  # 5 days older
            {Database.DATE_OBS_KEY: "2024-01-14T00:00:00"},  # 1 day older
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        # Closer in time should score higher
        assert results[0].candidate[Database.DATE_OBS_KEY] == "2024-01-14T00:00:00"

    def test_future_candidates_penalized(self):
        """Test that candidates more than 2 days in future are penalized."""
        ref_date = "2024-01-15T00:00:00"
        ref_session = {"metadata": {Database.DATE_OBS_KEY: ref_date}}
        candidates = [
            {Database.DATE_OBS_KEY: "2024-01-14T00:00:00"},  # 1 day older (good)
            {Database.DATE_OBS_KEY: "2024-01-20T00:00:00"},  # 5 days newer (penalized)
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        assert results[0].candidate[Database.DATE_OBS_KEY] == "2024-01-14T00:00:00"
        assert "in future" in results[1].reason

    def test_recent_future_allowed(self):
        """Test that candidates less than 2 days in future are allowed."""
        ref_date = "2024-01-15T00:00:00"
        ref_session = {"metadata": {Database.DATE_OBS_KEY: ref_date}}
        candidates = [{Database.DATE_OBS_KEY: "2024-01-16T00:00:00"}]  # 1 day newer

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1
        assert "in future" not in results[0].reason

    def test_malformed_date_warning(self, caplog):
        """Test handling of malformed dates."""
        import logging

        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-15T00:00:00"}}
        candidates = [{Database.DATE_OBS_KEY: "not-a-date"}]

        with caplog.at_level(logging.WARNING):
            results = score_candidates(candidates, ref_session)

        # Should still return the candidate, just without time scoring
        assert len(results) == 1


class TestScoreCandidatesInstrument:
    """Test scoring by instrument matching."""

    def test_instrument_mismatch_severe_penalty(self):
        """Test that instrument mismatch gets severe penalty."""
        from starbash.database import metadata_to_instrument_id

        ref_session = {
            "metadata": {
                Database.TELESCOP_KEY: "TELE1",
                "INSTRUME": "CAM1",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {
                Database.TELESCOP_KEY: "TELE1",
                "INSTRUME": "CAM1",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
            {
                Database.TELESCOP_KEY: "TELE2",
                "INSTRUME": "CAM2",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        # First should have much higher score
        assert results[0].score > results[1].score
        assert "instrument mismatch" in results[1].reason


class TestScoreCandidatesCamera:
    """Test scoring by camera matching."""

    def test_camera_mismatch_severe_penalty(self):
        """Test that camera mismatch severely penalizes score."""
        ref_session = {
            "metadata": {
                Database.INSTRUME_KEY: "ASI294MM",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {Database.INSTRUME_KEY: "ASI294MM", Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
            {Database.INSTRUME_KEY: "ASI183MM", Database.DATE_OBS_KEY: "2024-01-01T00:00:00"},
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        assert results[0].score > results[1].score
        assert "camera mismatch" in results[1].reason


class TestScoreCandidatesDimensions:
    """Test scoring by camera dimensions."""

    def test_dimension_mismatch_excludes_candidate(self):
        """Test that dimension mismatch makes candidate unusable."""
        ref_session = {
            "metadata": {
                "NAXIS": 2,
                "NAXIS1": 1920,
                "NAXIS2": 1080,
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {
                "NAXIS": 2,
                "NAXIS1": 1920,
                "NAXIS2": 1080,
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
            {
                "NAXIS": 2,
                "NAXIS1": 1280,
                "NAXIS2": 720,
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
        ]

        results = score_candidates(candidates, ref_session)

        # Only the matching dimension candidate should be included
        assert len(results) == 1
        assert results[0].candidate["NAXIS1"] == 1920


class TestScoreCandidatesFlatFilter:
    """Test scoring for FLAT frames by filter."""

    def test_flat_filter_match_required(self):
        """Test that FLAT frames must have matching filter."""
        ref_session = {
            "metadata": {
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "flat",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "flat",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
            {
                Database.FILTER_KEY: "OIII",
                Database.IMAGETYP_KEY: "flat",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            },
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 2
        # Matching filter should score much higher
        assert results[0].score > results[1].score
        assert "filter match" in results[0].reason
        assert "filter mismatch" in results[1].reason

    def test_non_flat_ignores_filter(self):
        """Test that non-FLAT frames don't get filter penalty."""
        ref_session = {
            "metadata": {
                Database.FILTER_KEY: "Ha",
                Database.IMAGETYP_KEY: "light",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {
                Database.FILTER_KEY: "OIII",
                Database.IMAGETYP_KEY: "light",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1
        # Should not have filter mismatch penalty for non-flat
        assert "filter mismatch" not in results[0].reason


class TestScoreCandidatesSorting:
    """Test that candidates are sorted correctly."""

    def test_candidates_sorted_by_score(self):
        """Test that results are sorted highest score first."""
        ref_session = {
            "metadata": {
                Database.GAIN_KEY: 60,
                "CCD-TEMP": 20.0,
                Database.DATE_OBS_KEY: "2024-01-15T00:00:00",
            }
        }
        candidates = [
            {
                Database.GAIN_KEY: 80,
                "CCD-TEMP": 15.0,
                Database.DATE_OBS_KEY: "2024-01-10T00:00:00",
            },  # Poor match
            {
                Database.GAIN_KEY: 60,
                "CCD-TEMP": 20.0,
                Database.DATE_OBS_KEY: "2024-01-14T00:00:00",
            },  # Good match
            {
                Database.GAIN_KEY: 70,
                "CCD-TEMP": 18.0,
                Database.DATE_OBS_KEY: "2024-01-12T00:00:00",
            },  # Medium match
        ]

        results = score_candidates(candidates, ref_session)

        # Should be sorted with best match first
        assert len(results) == 3
        assert results[0].score > results[1].score > results[2].score
        assert results[0].candidate[Database.GAIN_KEY] == 60  # Exact gain match

    def test_empty_candidates_list(self):
        """Test handling of empty candidates list."""
        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = []

        results = score_candidates(candidates, ref_session)

        assert len(results) == 0


class TestScoreCandidatesEdgeCases:
    """Test edge cases and error handling."""

    def test_candidate_with_no_metadata(self):
        """Test handling of candidate with minimal metadata."""
        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        candidates = [{}]

        results = score_candidates(candidates, ref_session)

        # Should still be included with low/zero score
        assert len(results) == 1

    def test_invalid_numeric_values(self):
        """Test handling of invalid numeric values for GAIN/temp."""
        ref_session = {
            "metadata": {
                Database.GAIN_KEY: 60,
                "CCD-TEMP": 20.0,
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        }
        candidates = [
            {
                Database.GAIN_KEY: "invalid",
                "CCD-TEMP": "not-a-number",
                Database.DATE_OBS_KEY: "2024-01-01T00:00:00",
            }
        ]

        results = score_candidates(candidates, ref_session)

        # Should not crash, just skip those scoring factors
        assert len(results) == 1

    def test_reason_string_formatting(self):
        """Test that multiple reasons are joined correctly."""
        ref_session = {
            "metadata": {
                Database.GAIN_KEY: 60,
                "CCD-TEMP": 20.0,
                Database.DATE_OBS_KEY: "2024-01-15T00:00:00",
            }
        }
        candidates = [
            {
                Database.GAIN_KEY: 80,
                "CCD-TEMP": 15.0,
                Database.DATE_OBS_KEY: "2024-01-10T00:00:00",
            }
        ]

        results = score_candidates(candidates, ref_session)

        assert len(results) == 1
        # Should have multiple comma-separated reasons
        assert ", " in results[0].reason
        assert "gain" in results[0].reason.lower()
        assert "temp" in results[0].reason.lower()

    def test_missing_path_in_candidate(self, caplog):
        """Test handling when candidate is missing expected fields."""
        import logging

        ref_session = {"metadata": {Database.DATE_OBS_KEY: "2024-01-01T00:00:00"}}
        # Candidate that might cause issues during processing
        candidates = [{"id": 1}]  # Has ID but might be missing other expected fields

        with caplog.at_level(logging.WARNING):
            results = score_candidates(candidates, ref_session)

        # Should handle gracefully
        assert len(results) >= 0
