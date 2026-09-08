"""Tests for the check_version module."""

import logging
from importlib.metadata import PackageNotFoundError
from unittest.mock import MagicMock, patch

import pytest

import starbash.check_version as check_version_module
from starbash.check_version import check_version


@pytest.fixture(autouse=True)
def reset_is_connected():
    """Reset the module-level connectivity cache after each test."""
    original = check_version_module._is_connected
    yield
    check_version_module._is_connected = original


class TestCheckVersion:
    """Tests for check_version()."""

    @patch("starbash.check_version.UpdateChecker")
    @patch("starbash.check_version.version", return_value="0.3.2")
    @patch("starbash.check_version.is_connected", return_value=True)
    def test_check_uses_keyword_arguments(self, mock_connected, mock_version, mock_checker_cls):
        """update_checker 1.0.0 requires keyword-only args to UpdateChecker.check()."""
        mock_result = MagicMock()
        mock_checker = mock_checker_cls.return_value
        mock_checker.check.return_value = mock_result

        check_version()

        mock_checker.check.assert_called_once_with(
            package_name="starbash", package_version="0.3.2"
        )

    @patch("starbash.check_version.UpdateChecker")
    @patch("starbash.check_version.version", return_value="0.3.2")
    @patch("starbash.check_version.is_connected", return_value=True)
    def test_update_available_logs_warning(
        self, mock_connected, mock_version, mock_checker_cls, caplog
    ):
        """A returned UpdateResult should be reported via a warning log."""
        mock_result = MagicMock()
        mock_checker_cls.return_value.check.return_value = mock_result

        with caplog.at_level(logging.WARNING):
            check_version()

        assert any(
            record.name == "root" and record.msg is mock_result for record in caplog.records
        )

    @patch("starbash.check_version.UpdateChecker")
    @patch("starbash.check_version.version", return_value="0.3.2")
    @patch("starbash.check_version.is_connected", return_value=True)
    def test_no_update_logs_nothing(
        self, mock_connected, mock_version, mock_checker_cls, caplog
    ):
        """A None result (no update available) should not log an update warning."""
        mock_checker_cls.return_value.check.return_value = None

        with caplog.at_level(logging.WARNING, logger="starbash.check_version"):
            check_version()

        assert not [
            r
            for r in caplog.records
            if r.name == "starbash.check_version" and "skipping" not in r.message
        ]

    @patch("starbash.check_version.UpdateChecker")
    @patch("starbash.check_version.version", return_value="0.3.2")
    @patch("starbash.check_version.is_connected", return_value=False)
    def test_offline_skips_check(self, mock_connected, mock_version, mock_checker_cls, caplog):
        """When offline, the checker must not be invoked."""
        with caplog.at_level(logging.WARNING, logger="starbash.check_version"):
            check_version()

        mock_checker_cls.return_value.check.assert_not_called()
        assert "skipping app version check" in caplog.text

    @patch("starbash.check_version.UpdateChecker")
    @patch(
        "starbash.check_version.version",
        side_effect=PackageNotFoundError("starbash"),
    )
    @patch("starbash.check_version.is_connected", return_value=True)
    def test_package_not_found_is_ignored(
        self, mock_connected, mock_version, mock_checker_cls
    ):
        """Running from source without the package installed must not raise."""
        check_version()  # Must not raise

