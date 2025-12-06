"""Tests for starbash.filtering module."""

from unittest.mock import MagicMock

import pytest

from starbash.exception import NotEnoughFilesError
from starbash.filtering import FallbackToImageException, filter_by_requires


class TestFallbackToImageException:
    """Tests for FallbackToImageException."""

    def test_exception_creation(self):
        """Test that FallbackToImageException can be created."""
        image = {"path": "/test/image.fits"}
        exc = FallbackToImageException(image)

        assert exc.image == image
        assert "Falling back" in str(exc)

    def test_exception_with_missing_path(self):
        """Test that exception handles missing path gracefully."""
        image = {"other": "data"}
        exc = FallbackToImageException(image)

        assert exc.image == image
        assert "unknown" in str(exc)


class TestFilterByRequires:
    """Tests for filter_by_requires and _apply_filter functions."""

    def test_filter_by_requires_no_requirements(self):
        """Test that filter returns all candidates when no requirements."""
        input_def = {}
        candidates = [{"path": "img1.fits"}, {"path": "img2.fits"}]

        result = filter_by_requires(input_def, candidates)
        assert len(result) == 2

    def test_filter_by_requires_empty_requires_list(self):
        """Test that empty requires list returns all candidates."""
        input_def = {"requires": []}
        candidates = [{"path": "img1.fits"}, {"path": "img2.fits"}]

        result = filter_by_requires(input_def, candidates)
        assert len(result) == 2

    def test_filter_metadata_matching(self):
        """Test filtering by metadata field."""
        input_def = {"requires": [{"kind": "metadata", "name": "FILTER", "value": ["HA", "OIII"]}]}

        # Mock aliases to return normalized values
        import starbash.filtering

        mock_aliases = MagicMock()
        mock_aliases.normalize = lambda x: x.upper()

        original_get_aliases = starbash.filtering.get_aliases
        starbash.filtering.get_aliases = lambda: mock_aliases

        try:
            candidates = [
                {"FILTER": "Ha", "path": "img1.fits"},
                {"FILTER": "OIII", "path": "img2.fits"},
                {"FILTER": "Lum", "path": "img3.fits"},
            ]

            result = filter_by_requires(input_def, candidates)
            assert len(result) == 2
            assert result[0]["FILTER"] == "Ha"
            assert result[1]["FILTER"] == "OIII"
        finally:
            starbash.filtering.get_aliases = original_get_aliases

    def test_filter_metadata_no_match(self):
        """Test filtering by metadata when no candidates match."""
        input_def = {"requires": [{"kind": "metadata", "name": "FILTER", "value": ["Red"]}]}

        # Mock aliases
        import starbash.filtering

        mock_aliases = MagicMock()
        mock_aliases.normalize = lambda x: x.upper()

        original_get_aliases = starbash.filtering.get_aliases
        starbash.filtering.get_aliases = lambda: mock_aliases

        try:
            candidates = [
                {"FILTER": "Ha", "path": "img1.fits"},
                {"FILTER": "OIII", "path": "img2.fits"},
            ]

            result = filter_by_requires(input_def, candidates)
            assert len(result) == 0
        finally:
            starbash.filtering.get_aliases = original_get_aliases

    def test_filter_camera_color(self):
        """Test filtering by color camera (has BAYERPAT)."""
        input_def = {"requires": [{"kind": "camera", "value": "color"}]}

        candidates = [
            {"BAYERPAT": "RGGB", "path": "img1.fits"},
            {"path": "img2.fits"},  # No BAYERPAT
            {"BAYERPAT": "GBRG", "path": "img3.fits"},
        ]

        result = filter_by_requires(input_def, candidates)
        assert len(result) == 2
        assert all("BAYERPAT" in img for img in result)

    def test_filter_camera_invalid_value(self):
        """Test that invalid camera value raises ValueError."""
        input_def = {"requires": [{"kind": "camera", "value": "invalid"}]}
        candidates = [{"path": "img1.fits"}]

        with pytest.raises(ValueError, match="Unknown camera value"):
            filter_by_requires(input_def, candidates)

    def test_filter_unprocessed(self):
        """Test filtering for unprocessed images."""
        input_def = {"requires": [{"kind": "unprocessed"}]}

        mock_repo_processed = MagicMock()
        mock_repo_processed.kind.return_value = "processed"

        mock_repo_master = MagicMock()
        mock_repo_master.kind.return_value = "master"

        mock_repo_light = MagicMock()
        mock_repo_light.kind.return_value = "light"

        candidates = [
            {"repo": mock_repo_light, "path": "img1.fits"},
            {"repo": mock_repo_processed, "path": "img2.fits"},
            {"repo": mock_repo_master, "path": "img3.fits"},
        ]

        result = filter_by_requires(input_def, candidates)
        assert len(result) == 1
        assert result[0]["path"] == "img1.fits"

    def test_filter_min_count_sufficient(self):
        """Test min_count filter when sufficient images."""
        input_def = {"requires": [{"kind": "min_count", "value": 2}]}
        candidates = [{"path": "img1.fits"}, {"path": "img2.fits"}, {"path": "img3.fits"}]

        result = filter_by_requires(input_def, candidates)
        assert len(result) == 3

    def test_filter_min_count_insufficient(self):
        """Test min_count filter when insufficient images."""
        input_def = {"requires": [{"kind": "min_count", "value": 5}]}
        candidates = [{"path": "img1.fits"}, {"path": "img2.fits"}]

        with pytest.raises(NotEnoughFilesError, match="requires >=5 input files"):
            filter_by_requires(input_def, candidates)

    def test_filter_min_count_accept_single(self):
        """Test min_count with accept_single option when exactly 1 image."""
        input_def = {"requires": [{"kind": "min_count", "value": 5, "accept_single": True}]}
        candidates = [{"path": "img1.fits"}]

        with pytest.raises(FallbackToImageException) as exc_info:
            filter_by_requires(input_def, candidates)

        assert exc_info.value.image == candidates[0]

    def test_filter_min_count_accept_single_but_zero(self):
        """Test min_count with accept_single but 0 images."""
        input_def = {"requires": [{"kind": "min_count", "value": 5, "accept_single": True}]}
        candidates = []

        with pytest.raises(NotEnoughFilesError):
            filter_by_requires(input_def, candidates)

    def test_filter_min_count_missing_value(self):
        """Test that min_count without value raises ValueError."""
        input_def = {"requires": [{"kind": "min_count"}]}
        candidates = [{"path": "img1.fits"}]

        with pytest.raises(ValueError, match="min_count requires a 'value' field"):
            filter_by_requires(input_def, candidates)

    def test_filter_unknown_kind(self):
        """Test that unknown filter kind raises ValueError."""
        input_def = {"requires": [{"kind": "unknown_filter"}]}
        candidates = [{"path": "img1.fits"}]

        with pytest.raises(ValueError, match="Unknown requires kind"):
            filter_by_requires(input_def, candidates)

    def test_filter_missing_kind(self):
        """Test that missing kind field raises ValueError."""
        input_def = {"requires": [{"value": "something"}]}
        candidates = [{"path": "img1.fits"}]

        with pytest.raises(ValueError, match="Config is missing 'kind' field"):
            filter_by_requires(input_def, candidates)

    def test_filter_multiple_requirements(self):
        """Test applying multiple filter requirements in sequence."""
        # Mock aliases
        import starbash.filtering

        mock_aliases = MagicMock()
        mock_aliases.normalize = lambda x: x.upper()

        original_get_aliases = starbash.filtering.get_aliases
        starbash.filtering.get_aliases = lambda: mock_aliases

        try:
            input_def = {
                "requires": [
                    {"kind": "metadata", "name": "FILTER", "value": ["HA", "OIII"]},
                    {"kind": "camera", "value": "color"},
                ]
            }

            candidates = [
                {"FILTER": "Ha", "BAYERPAT": "RGGB", "path": "img1.fits"},
                {"FILTER": "OIII", "path": "img2.fits"},  # No BAYERPAT
                {"FILTER": "Lum", "BAYERPAT": "RGGB", "path": "img3.fits"},
            ]

            result = filter_by_requires(input_def, candidates)
            # Should only match img1 (Ha + color camera)
            assert len(result) == 1
            assert result[0]["path"] == "img1.fits"
        finally:
            starbash.filtering.get_aliases = original_get_aliases
