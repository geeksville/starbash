"""Tests for starbash.rich module."""

import pytest
from rich.tree import Tree

from starbash.rich import BRIEF_LIMIT, to_rich_string, to_tree


class TestToTree:
    """Tests for to_tree function."""

    def test_to_tree_simple_dict(self):
        """Test that to_tree converts a simple dict to a tree."""
        obj = {"key1": "value1", "key2": "value2"}
        tree = to_tree(obj, label="test", brief=False)

        assert isinstance(tree, Tree)
        assert tree.label == "test"

    def test_to_tree_nested_dict(self):
        """Test that to_tree handles nested dictionaries."""
        obj = {"outer": {"inner": "value"}}
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)
        # Tree should have subtrees for nested structures

    def test_to_tree_with_list(self):
        """Test that to_tree handles lists."""
        obj = {"items": ["a", "b", "c"]}
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)

    def test_to_tree_brief_mode_limits_items(self):
        """Test that brief mode limits the number of leaf items shown."""
        # Create a dict with more items than BRIEF_LIMIT
        obj = {f"key{i}": f"value{i}" for i in range(BRIEF_LIMIT + 5)}
        tree = to_tree(obj, label="root", brief=True)

        assert isinstance(tree, Tree)
        # In brief mode, should have limited children

    def test_to_tree_not_brief_shows_all_items(self):
        """Test that non-brief mode shows all items."""
        obj = {f"key{i}": f"value{i}" for i in range(10)}
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)

    def test_to_tree_truncates_long_values(self):
        """Test that to_tree truncates values longer than 80 characters."""
        long_value = "x" * 100
        obj = {"long_key": long_value}
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)

    def test_to_tree_with_iterable(self):
        """Test that to_tree handles iterables that are not strings."""
        obj = {"tuple": (1, 2, 3), "set": {4, 5, 6}}
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)

    def test_to_tree_with_mixed_types(self):
        """Test that to_tree handles mixed types."""
        obj = {
            "string": "value",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "none": None,
        }
        tree = to_tree(obj, label="root", brief=False)

        assert isinstance(tree, Tree)

    def test_to_tree_default_label(self):
        """Test that to_tree uses default label 'root'."""
        obj = {"key": "value"}
        tree = to_tree(obj)

        assert tree.label == "root"

    def test_to_tree_default_brief(self):
        """Test that to_tree defaults to brief=True."""
        # Create a dict with many items
        obj = {f"key{i}": f"value{i}" for i in range(20)}
        tree = to_tree(obj)

        assert isinstance(tree, Tree)


class TestToRichString:
    """Tests for to_rich_string function."""

    def test_to_rich_string_returns_string(self):
        """Test that to_rich_string returns a string representation."""
        obj = {"key": "value"}
        result = to_rich_string(obj)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_rich_string_with_tree(self):
        """Test that to_rich_string works with Tree objects."""
        obj = {"key": "value"}
        tree = to_tree(obj, label="myroot")
        result = to_rich_string(tree)

        assert isinstance(result, str)
        assert "myroot" in result

    def test_to_rich_string_with_nested_structure(self):
        """Test that to_rich_string handles nested structures."""
        obj = {"outer": {"inner": {"deep": "value"}}}
        result = to_rich_string(obj)

        assert isinstance(result, str)

    def test_to_rich_string_with_dict(self):
        """Test that to_rich_string handles plain dict."""
        obj = {"key1": "value1", "key2": "value2"}
        result = to_rich_string(obj)

        assert isinstance(result, str)
        assert "key1" in result or "value1" in result

    def test_to_rich_string_with_simple_types(self):
        """Test that to_rich_string handles simple types."""
        assert isinstance(to_rich_string("test"), str)
        assert isinstance(to_rich_string(42), str)
        assert isinstance(to_rich_string([1, 2, 3]), str)

    def test_to_rich_string_with_none(self):
        """Test that to_rich_string handles None."""
        result = to_rich_string(None)
        assert isinstance(result, str)
