"""Tests for the analytics module."""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock, call

from starbash.analytics import (
    analytics_setup,
    analytics_shutdown,
    is_development_environment,
    analytics_exception,
    NopAnalytics,
    analytics_start_span,
    analytics_start_transaction,
    analytics_allowed,
)


@pytest.fixture
def reset_analytics():
    """Reset analytics_allowed global state after each test."""
    import starbash.analytics

    original_state = starbash.analytics.analytics_allowed
    yield
    starbash.analytics.analytics_allowed = original_state


class TestAnalyticsSetup:
    """Tests for analytics_setup function."""

    @patch("sentry_sdk.init")
    @patch("sentry_sdk.set_user")
    def test_setup_disabled_by_default(self, mock_set_user, mock_init, reset_analytics):
        """Test that analytics is disabled by default."""
        analytics_setup(allowed=False)

        mock_init.assert_not_called()
        mock_set_user.assert_not_called()

    @patch("sentry_sdk.init")
    @patch("sentry_sdk.set_user")
    def test_setup_enabled_initializes_sentry(
        self, mock_set_user, mock_init, reset_analytics
    ):
        """Test that enabling analytics initializes Sentry."""
        analytics_setup(allowed=True)

        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert "dsn" in call_kwargs
        assert call_kwargs["send_default_pii"] is True
        assert call_kwargs["enable_logs"] is True
        assert call_kwargs["traces_sample_rate"] == 1.0

    @patch("sentry_sdk.init")
    @patch("sentry_sdk.set_user")
    def test_setup_with_user_email(self, mock_set_user, mock_init, reset_analytics):
        """Test that user email is set when provided."""
        analytics_setup(allowed=True, user_email="test@example.com")

        mock_set_user.assert_called_once_with({"email": "test@example.com"})

    @patch("sentry_sdk.init")
    @patch("sentry_sdk.set_user")
    def test_setup_without_user_email(self, mock_set_user, mock_init, reset_analytics):
        """Test that set_user is not called without email."""
        analytics_setup(allowed=True, user_email=None)

        mock_set_user.assert_not_called()

    @patch("sentry_sdk.init")
    def test_setup_sets_global_analytics_allowed(self, mock_init, reset_analytics):
        """Test that setup sets the global analytics_allowed flag."""
        import starbash.analytics

        analytics_setup(allowed=True)
        assert starbash.analytics.analytics_allowed is True

        analytics_setup(allowed=False)
        assert starbash.analytics.analytics_allowed is False


class TestAnalyticsShutdown:
    """Tests for analytics_shutdown function."""

    @patch("sentry_sdk.flush")
    def test_shutdown_when_disabled(self, mock_flush, reset_analytics):
        """Test that shutdown does nothing when analytics is disabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = False

        analytics_shutdown()

        mock_flush.assert_not_called()

    @patch("sentry_sdk.flush")
    def test_shutdown_when_enabled(self, mock_flush, reset_analytics):
        """Test that shutdown flushes when analytics is enabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        analytics_shutdown()

        mock_flush.assert_called_once()


class TestIsDevelopmentEnvironment:
    """Tests for is_development_environment function."""

    def test_explicit_development_env_var(self, monkeypatch):
        """Test STARBASH_ENV=development is detected."""
        # Clear all VS Code vars first
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("STARBASH_ENV", "development")
        assert is_development_environment() is True

    def test_vscode_environment_detected(self, monkeypatch):
        """Test VS Code environment variables are detected."""
        monkeypatch.delenv("STARBASH_ENV", raising=False)
        monkeypatch.setenv("VSCODE_PID", "12345")
        assert is_development_environment() is True

        monkeypatch.delenv("VSCODE_PID")
        monkeypatch.setenv("VSCODE_CLI", "1")
        assert is_development_environment() is True

    def test_production_environment(self, monkeypatch):
        """Test production environment is not flagged as development."""
        # Clear any VS Code vars
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("STARBASH_ENV", raising=False)

        assert is_development_environment() is False

    def test_other_environment_values_not_development(self, monkeypatch):
        """Test that other STARBASH_ENV values are not development."""
        # Clear VS Code env vars first
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("STARBASH_ENV", "production")
        assert is_development_environment() is False

        monkeypatch.setenv("STARBASH_ENV", "ci")
        assert is_development_environment() is False


class TestAnalyticsException:
    """Tests for analytics_exception function."""

    @patch("sentry_sdk.capture_exception")
    def test_exception_in_development_returns_false(
        self, mock_capture, reset_analytics, monkeypatch
    ):
        """Test that exceptions in development are not suppressed."""
        monkeypatch.setenv("STARBASH_ENV", "development")
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        exc = ValueError("test error")
        result = analytics_exception(exc)

        assert result is False
        mock_capture.assert_not_called()

    @patch("sentry_sdk.capture_exception", return_value="test-report-id-123")
    def test_exception_with_analytics_enabled(
        self, mock_capture, reset_analytics, monkeypatch
    ):
        """Test that exceptions are reported when analytics is enabled."""
        monkeypatch.delenv("STARBASH_ENV", raising=False)
        # Clear VS Code env vars
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)

        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        exc = RuntimeError("test error")
        result = analytics_exception(exc)

        assert result is True
        mock_capture.assert_called_once_with(exc)

    def test_exception_with_analytics_disabled(self, reset_analytics, monkeypatch):
        """Test that exceptions are logged when analytics is disabled."""
        monkeypatch.delenv("STARBASH_ENV", raising=False)
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)

        import starbash.analytics

        starbash.analytics.analytics_allowed = False

        exc = RuntimeError("test error")
        result = analytics_exception(exc)

        assert result is True


class TestNopAnalytics:
    """Tests for NopAnalytics class."""

    def test_nop_analytics_context_manager(self):
        """Test NopAnalytics works as a context manager."""
        nop = NopAnalytics()

        with nop as ctx:
            assert ctx is nop

    def test_nop_analytics_exit_returns_false(self):
        """Test that __exit__ returns False (doesn't suppress exceptions)."""
        nop = NopAnalytics()
        result = nop.__exit__(None, None, None)
        assert result is False

    def test_nop_analytics_set_data_does_nothing(self):
        """Test that set_data is a no-op."""
        nop = NopAnalytics()
        # Should not raise any errors
        nop.set_data("key", "value")
        nop.set_data("another", 123)

    def test_nop_analytics_used_in_with_statement(self):
        """Test NopAnalytics in actual with statement."""
        nop = NopAnalytics()
        executed = False

        with nop:
            executed = True

        assert executed is True


class TestAnalyticsStartSpan:
    """Tests for analytics_start_span function."""

    @patch("sentry_sdk.start_span")
    def test_start_span_when_analytics_enabled(self, mock_start_span, reset_analytics):
        """Test that start_span returns Sentry span when enabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        mock_span = MagicMock()
        mock_start_span.return_value = mock_span

        result = analytics_start_span(op="test.operation", description="Test")

        mock_start_span.assert_called_once_with(op="test.operation", description="Test")
        assert result == mock_span

    def test_start_span_when_analytics_disabled(self, reset_analytics):
        """Test that start_span returns NopAnalytics when disabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = False

        result = analytics_start_span(op="test.operation")

        assert isinstance(result, NopAnalytics)

    @patch("sentry_sdk.start_span")
    def test_start_span_with_various_kwargs(self, mock_start_span, reset_analytics):
        """Test that kwargs are passed through to Sentry."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        analytics_start_span(
            op="db.query", description="SELECT * FROM users", parent_span_id="abc123"
        )

        mock_start_span.assert_called_once_with(
            op="db.query", description="SELECT * FROM users", parent_span_id="abc123"
        )


class TestAnalyticsStartTransaction:
    """Tests for analytics_start_transaction function."""

    @patch("sentry_sdk.start_transaction")
    def test_start_transaction_when_analytics_enabled(
        self, mock_start_transaction, reset_analytics
    ):
        """Test that start_transaction returns Sentry transaction when enabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        mock_txn = MagicMock()
        mock_start_transaction.return_value = mock_txn

        result = analytics_start_transaction(name="test.transaction", op="test")

        mock_start_transaction.assert_called_once_with(
            name="test.transaction", op="test"
        )
        assert result == mock_txn

    def test_start_transaction_when_analytics_disabled(self, reset_analytics):
        """Test that start_transaction returns NopAnalytics when disabled."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = False

        result = analytics_start_transaction(name="test.transaction")

        assert isinstance(result, NopAnalytics)

    @patch("sentry_sdk.start_transaction")
    def test_start_transaction_with_various_kwargs(
        self, mock_start_transaction, reset_analytics
    ):
        """Test that kwargs are passed through to Sentry."""
        import starbash.analytics

        starbash.analytics.analytics_allowed = True

        analytics_start_transaction(name="http.request", op="http", sampled=True)

        mock_start_transaction.assert_called_once_with(
            name="http.request", op="http", sampled=True
        )


class TestAnalyticsIntegration:
    """Integration tests for analytics workflow."""

    @patch("sentry_sdk.init")
    @patch("sentry_sdk.set_user")
    @patch("sentry_sdk.start_transaction")
    @patch("sentry_sdk.start_span")
    @patch("sentry_sdk.capture_exception", return_value="test-id")
    @patch("sentry_sdk.flush")
    def test_complete_analytics_workflow(
        self,
        mock_flush,
        mock_capture,
        mock_start_span,
        mock_start_transaction,
        mock_set_user,
        mock_init,
        reset_analytics,
        monkeypatch,
    ):
        """Test a complete analytics workflow from setup to shutdown."""
        monkeypatch.delenv("STARBASH_ENV", raising=False)
        for key in list(os.environ.keys()):
            if key.startswith("VSCODE_"):
                monkeypatch.delenv(key, raising=False)

        mock_txn = MagicMock()
        mock_start_transaction.return_value = mock_txn
        mock_span = MagicMock()
        mock_start_span.return_value = mock_span

        # Setup analytics
        analytics_setup(allowed=True, user_email="user@example.com")
        mock_init.assert_called_once()
        mock_set_user.assert_called_once()

        # Start a transaction
        with analytics_start_transaction(name="test"):
            # Verify transaction was started
            mock_start_transaction.assert_called_once_with(name="test")

            # Start a span within the transaction
            with analytics_start_span(op="test.op"):
                # Verify span was started
                mock_start_span.assert_called_once_with(op="test.op")

        # Report an exception
        exc = ValueError("test")
        result = analytics_exception(exc)
        assert result is True
        mock_capture.assert_called_once_with(exc)

        # Shutdown
        analytics_shutdown()
        mock_flush.assert_called_once()

    def test_disabled_analytics_workflow(self, reset_analytics):
        """Test that disabled analytics uses NopAnalytics everywhere."""
        analytics_setup(allowed=False)

        # All operations should return NopAnalytics or not call Sentry
        txn = analytics_start_transaction(name="test")
        assert isinstance(txn, NopAnalytics)

        span = analytics_start_span(op="test")
        assert isinstance(span, NopAnalytics)

        # Shutdown shouldn't raise
        analytics_shutdown()
