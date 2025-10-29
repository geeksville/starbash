import logging
import os

from starbash import console
import starbash.url as url

# Default to no analytics/auto crash reports
analytics_allowed = False


def analytics_setup(allowed: bool = False, user_email: str | None = None) -> None:
    import sentry_sdk

    global analytics_allowed
    analytics_allowed = allowed
    if analytics_allowed:
        logging.info(
            f"Analytics/crash-reports enabled.  To change [link={url.analytics_docs}]click here[/link]",
            extra={"markup": True},
        )
        sentry_sdk.init(
            dsn="https://e9496a4ea8b37a053203a2cbc10d64e6@o209837.ingest.us.sentry.io/4510264204132352",
            send_default_pii=True,
            enable_logs=True,
            traces_sample_rate=1.0,
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


def is_running_in_pytest() -> bool:
    """Detect if code is being run inside pytest."""
    return "PYTEST_CURRENT_TEST" in os.environ


def is_development_environment() -> bool:
    """Detect if running in a development environment."""

    # Check for explicit environment variable
    if os.getenv("STARBASH_ENV") == "development":
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

        if is_running_in_pytest():
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

        return sentry_sdk.start_transaction(**kwargs)
    else:
        return NopAnalytics()
