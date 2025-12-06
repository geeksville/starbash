"""Tests for starbash.safety module."""

import pytest

from starbash.safety import get_list_of_strings, get_safe


class TestGetSafe:
    """Tests for get_safe function."""

    def test_get_safe_returns_value(self):
        """Test that get_safe returns the value when key exists."""
        d = {"key": "value"}
        assert get_safe(d, "key") == "value"

    def test_get_safe_raises_on_missing_key(self):
        """Test that get_safe raises ValueError when key is missing."""
        d = {"other": "value"}
        with pytest.raises(ValueError, match="Config is missing 'key' field"):
            get_safe(d, "key")

    def test_get_safe_raises_on_none_value(self):
        """Test that get_safe raises ValueError when value is None."""
        d = {"key": None}
        with pytest.raises(ValueError, match="Config is missing 'key' field"):
            get_safe(d, "key")

    def test_get_safe_with_different_types(self):
        """Test that get_safe works with various value types."""
        d = {"int": 42, "list": [1, 2, 3], "dict": {"nested": "value"}}
        assert get_safe(d, "int") == 42
        assert get_safe(d, "list") == [1, 2, 3]
        assert get_safe(d, "dict") == {"nested": "value"}


class TestGetListOfStrings:
    """Tests for get_list_of_strings function."""

    def test_get_list_of_strings_with_list(self):
        """Test that get_list_of_strings returns list as-is."""
        d = {"key": ["a", "b", "c"]}
        assert get_list_of_strings(d, "key") == ["a", "b", "c"]

    def test_get_list_of_strings_with_single_string(self):
        """Test that get_list_of_strings wraps single string in list."""
        d = {"key": "single"}
        assert get_list_of_strings(d, "key") == ["single"]

    def test_get_list_of_strings_raises_on_invalid_type(self):
        """Test that get_list_of_strings raises ValueError on invalid type."""
        d = {"key": 42}
        with pytest.raises(ValueError, match="Expected string or list of strings"):
            get_list_of_strings(d, "key")

    def test_get_list_of_strings_raises_on_dict(self):
        """Test that get_list_of_strings raises ValueError on dict."""
        d = {"key": {"nested": "value"}}
        with pytest.raises(ValueError, match="Expected string or list of strings"):
            get_list_of_strings(d, "key")

    def test_get_list_of_strings_raises_on_missing_key(self):
        """Test that get_list_of_strings raises ValueError on missing key."""
        d = {"other": "value"}
        with pytest.raises(ValueError, match="Config is missing 'key' field"):
            get_list_of_strings(d, "key")

    def test_get_list_of_strings_with_empty_list(self):
        """Test that get_list_of_strings handles empty list."""
        d = {"key": []}
        # Empty list is falsy, so get_safe will raise
        with pytest.raises(ValueError, match="Config is missing 'key' field"):
            get_list_of_strings(d, "key")
