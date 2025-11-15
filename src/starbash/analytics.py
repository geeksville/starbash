import logging
import os
import platform

from sentry_sdk.integrations.excepthook import ExcepthookIntegration

import starbash
import starbash.url as url
from starbash import _is_test_env

# Default to no analytics/auto crash reports
analytics_allowed = False


def analytics_setup(allowed: bool = False, user_email: str | None = None) -> None:
    global analytics_allowed
    analytics_allowed = allowed
    if analytics_allowed:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        logging.info(
            f"Analytics/crash-reports enabled.  To change [link={url.analytics_docs}]click here[/link]",
            extra={"markup": True},
        )
        sentry_sdk.init(
            dsn="https://e9496a4ea8b37a053203a2cbc10d64e6@o209837.ingest.us.sentry.io/4510264204132352",
            send_default_pii=True,
            enable_logs=True,
            traces_sample_rate=1.0,
            disabled_integrations=[
                ExcepthookIntegration()
            ],  # This line removes the aggressive unhandled exception catcher
            integrations=[
                LoggingIntegration(
                    level=starbash.log_filter_level,  # Capture INFO and above as breadcrumbs
                    event_level=None,  # Don't automatically convert error messages to sentry events
                    sentry_logs_level=starbash.log_filter_level,  # Capture INFO and above as logs
                ),
            ],
        )

        if user_email:
            sentry_sdk.set_user({"email": user_email})
    else:
        logging.info(
            f"Analytics/crash-reports disabled.  To learn more [link={url.analytics_docs}]click here[/link]",
            extra={"markup": True},
        )


def analytics_shutdown() -> None:
    """Shut down the analytics service, if enabled."""
    if analytics_allowed:
        import sentry_sdk

        sentry_sdk.flush()


def is_development_environment() -> bool:
    """Detect if running in a development environment."""

    # Check for explicit environment variable
    if os.getenv("SENTRY_ENVIRONMENT") == "development":
        return True

    # Check if running under VS Code
    if any(k.startswith("VSCODE_") for k in os.environ):
        return True

    return False


def analytics_exception(exc: Exception) -> bool:
    """Report an exception to the analytics service, if enabled.
    return True to suppress exception propagation/log messages"""

    if is_development_environment():
        return False  # We want to let devs see full exception traces

    if analytics_allowed:
        import sentry_sdk

        if _is_test_env:
            report_id = "TESTING-ENVIRONMENT"
        else:
            report_id = sentry_sdk.capture_exception(exc)

        logging.info(
            f"""An unexpected error has occurred and been reported.  Thank you for your help.
                If you'd like to chat with the devs about it, please click
                [link={url.new_issue(str(report_id))}]here[/link] to open an issue.""",
            extra={"markup": True},
        )
    else:
        logging.error(
            f"""An unexpected error has occurred. Automated crash reporting is disabled,
                      but we encourage you to contact the developers
                      at [link={url.new_issue()}]here[/link] and we will try to help.

                      The full exception is: {exc}""",
            extra={"markup": True},
        )
    return True


class NopAnalytics:
    """Used when users have disabled analytics/crash reporting."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def set_data(self, key, value):
        pass


def analytics_start_span(**kwargs):
    """Start an analytics/tracing span if analytics is enabled, otherwise return a no-op context manager."""
    if analytics_allowed:
        import sentry_sdk

        return sentry_sdk.start_span(**kwargs)
    else:
        return NopAnalytics()


def analytics_start_transaction(**kwargs):
    """Start an analytics/tracing transaction if analytics is enabled, otherwise return a no-op context manager."""
    if analytics_allowed:
        import sentry_sdk

        r = sentry_sdk.start_transaction(**kwargs)

        # include key OS info
        r.set_data("os.name", platform.system())
        r.set_data("os.release", platform.release())
        r.set_data("os.architecture", platform.machine())

        return r
    else:
        return NopAnalytics()
