"""Tests for starbash.exception module."""

import pytest

from starbash.exception import (
    NonFatalException,
    NoSuitableMastersException,
    NotEnoughFilesError,
    UserHandledError,
    raise_missing_repo,
)


class TestUserHandledError:
    """Tests for UserHandledError exception."""

    def test_user_handled_error_creation(self):
        """Test that UserHandledError can be created with a message."""
        error = UserHandledError("Test error message")
        assert str(error) == "Test error message"

    def test_user_handled_error_is_value_error(self):
        """Test that UserHandledError is a subclass of Exception (via NonSoftwareError)."""
        from starbash.exception import NonSoftwareError

        assert issubclass(UserHandledError, NonSoftwareError)
        assert issubclass(UserHandledError, Exception)
        assert not issubclass(UserHandledError, ValueError)

    def test_user_handled_error_rich_method(self):
        """Test that __rich__ returns the string representation."""
        error = UserHandledError("Test error")
        assert error.__rich__() == "Test error"

    def test_ask_user_handled_returns_false(self, capsys):
        """Test that ask_user_handled prints error and returns False."""
        error = UserHandledError("Test error message")
        result = error.ask_user_handled()

        # Should return False
        assert result is False

        # Should print the error (captured output will have the message)
        # Note: This uses rich console so we can't easily capture exact output


class TestRaiseMissingRepo:
    """Tests for raise_missing_repo function."""

    def test_raise_missing_repo_masters(self):
        """Test that raise_missing_repo raises UserHandledError for masters."""
        with pytest.raises(UserHandledError) as exc_info:
            raise_missing_repo("masters")

        assert "No masters repo configured" in str(exc_info.value)
        assert "sb user setup" in str(exc_info.value)
        assert "sb repo add --masters" in str(exc_info.value)

    def test_raise_missing_repo_processed(self):
        """Test that raise_missing_repo raises UserHandledError for processed."""
        with pytest.raises(UserHandledError) as exc_info:
            raise_missing_repo("processed")

        assert "No processed repo configured" in str(exc_info.value)
        assert "sb user setup" in str(exc_info.value)
        assert "sb repo add --processed" in str(exc_info.value)

    def test_raise_missing_repo_custom_kind(self):
        """Test that raise_missing_repo works with any kind string."""
        with pytest.raises(UserHandledError) as exc_info:
            raise_missing_repo("custom-repo-type")

        assert "No custom-repo-type repo configured" in str(exc_info.value)


class TestNotEnoughFilesError:
    """Tests for NotEnoughFilesError exception."""

    def test_not_enough_files_error_creation(self):
        """Test that NotEnoughFilesError can be created with a message."""
        error = NotEnoughFilesError("Need at least 3 files")
        assert str(error) == "Need at least 3 files"

    def test_not_enough_files_error_is_value_error(self):
        """Test that NotEnoughFilesError is a subclass of ValueError."""
        assert issubclass(NotEnoughFilesError, ValueError)

    def test_not_enough_files_error_is_non_fatal(self):
        """Test that NotEnoughFilesError is a subclass of NonFatalException."""
        assert issubclass(NotEnoughFilesError, NonFatalException)

    def test_not_enough_files_error_with_files_list(self):
        """Test that NotEnoughFilesError can store a list of files."""
        files = ["file1.fits", "file2.fits"]
        error = NotEnoughFilesError("Need at least 3 files", files=files)
        assert error.files == files


class TestNonFatalException:
    """Tests for NonFatalException exception."""

    def test_non_fatal_exception_creation(self):
        """Test that NonFatalException can be created with a message."""
        error = NonFatalException("Test non-fatal error")
        assert str(error) == "Test non-fatal error"

    def test_non_fatal_exception_is_value_error(self):
        """Test that NonFatalException is a subclass of ValueError."""
        assert issubclass(NonFatalException, ValueError)


class TestNoSuitableMastersException:
    """Tests for NoSuitableMastersException exception."""

    def test_no_suitable_masters_exception_creation(self):
        """Test that NoSuitableMastersException can be created with a kind."""
        error = NoSuitableMastersException("bias")
        assert "bias" in str(error)
        assert error.kind == "bias"

    def test_no_suitable_masters_exception_is_non_fatal(self):
        """Test that NoSuitableMastersException is a subclass of NonFatalException."""
        assert issubclass(NoSuitableMastersException, NonFatalException)

    def test_no_suitable_masters_exception_is_value_error(self):
        """Test that NoSuitableMastersException is a subclass of ValueError."""
        assert issubclass(NoSuitableMastersException, ValueError)
