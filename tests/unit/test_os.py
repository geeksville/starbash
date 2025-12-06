"""Tests for starbash.os module."""

import os
import tempfile
from pathlib import Path

import pytest

from starbash.os import symlink_or_copy


class TestSymlinkOrCopy:
    """Tests for symlink_or_copy function."""

    def test_symlink_or_copy_creates_symlink(self, tmp_path: Path):
        """Test that symlink_or_copy creates a symlink when possible."""
        src = tmp_path / "source.txt"
        dest = tmp_path / "link.txt"

        # Create source file
        src.write_text("test content")

        # Create symlink
        symlink_or_copy(str(src), str(dest))

        # Verify dest exists
        assert dest.exists()
        assert dest.read_text() == "test content"

        # On systems that support symlinks, verify it's actually a symlink
        # (we can't guarantee this everywhere, especially on Windows)
        if os.name != "nt":
            assert dest.is_symlink()

    def test_symlink_or_copy_falls_back_to_copy(self, tmp_path: Path, monkeypatch):
        """Test that symlink_or_copy falls back to copy when symlink fails."""
        src = tmp_path / "source.txt"
        dest = tmp_path / "copy.txt"

        # Create source file
        src.write_text("test content")

        # Mock os.symlink to raise OSError
        original_symlink = os.symlink

        def mock_symlink(src, dst):
            raise OSError("Symlink not supported")

        monkeypatch.setattr(os, "symlink", mock_symlink)

        # Create copy
        symlink_or_copy(str(src), str(dest))

        # Verify dest exists and is a regular file (not a symlink)
        assert dest.exists()
        assert dest.read_text() == "test content"
        assert not dest.is_symlink()

    def test_symlink_or_copy_preserves_metadata(self, tmp_path: Path, monkeypatch):
        """Test that copy preserves file metadata."""
        src = tmp_path / "source.txt"
        dest = tmp_path / "copy.txt"

        # Create source file with specific content
        src.write_text("test content")
        original_mtime = src.stat().st_mtime

        # Force copy mode by mocking symlink failure
        def mock_symlink(src, dst):
            raise OSError("Symlink not supported")

        monkeypatch.setattr(os, "symlink", mock_symlink)

        # Create copy
        symlink_or_copy(str(src), str(dest))

        # Verify metadata is preserved (mtime should be close)
        dest_mtime = dest.stat().st_mtime
        assert abs(dest_mtime - original_mtime) < 1.0  # Within 1 second

    def test_symlink_or_copy_warning_logged_once(self, tmp_path: Path, monkeypatch, caplog):
        """Test that warning is only logged once when falling back to copy."""
        import starbash.os

        # Reset the global flag
        starbash.os._symlink_warning_logged = False

        src1 = tmp_path / "source1.txt"
        src2 = tmp_path / "source2.txt"
        dest1 = tmp_path / "copy1.txt"
        dest2 = tmp_path / "copy2.txt"

        src1.write_text("content1")
        src2.write_text("content2")

        # Mock os.symlink to raise OSError
        def mock_symlink(src, dst):
            raise OSError("Symlink not supported")

        monkeypatch.setattr(os, "symlink", mock_symlink)

        # First call should log warning
        with caplog.at_level("WARNING"):
            symlink_or_copy(str(src1), str(dest1))
            assert "Symlinks are not enabled" in caplog.text

        # Clear log
        caplog.clear()

        # Second call should not log warning again
        with caplog.at_level("WARNING"):
            symlink_or_copy(str(src2), str(dest2))
            assert "Symlinks are not enabled" not in caplog.text
