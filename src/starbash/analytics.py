import logging

from starbash import console

# Default to no analytics/auto crash reports
analytics_allowed = False

project_url = "https://github.com/geeksville/starbash"
analytics_docs_url = f"{project_url}/blob/main/doc/analytics.md"


def new_issue_url(report_id: str | None = None) -> str:
    if report_id:
        return f"{project_url}/issues/new?body=Please%20describe%20the%20problem%2C%20but%20include%20this%3A%0ACrash%20ID%20{report_id}"
    else:
        return f"{project_url}/issues/new?body=Please%20describe%20the%20problem"


def analytics_setup(allowed: bool = False, user_email: str | None = None) -> None:
    import sentry_sdk

    global analytics_allowed
    analytics_allowed = allowed
    if analytics_allowed:
        logging.info(
            "Analytics/crash-reports enabled.  To learn more see: %s",
            analytics_docs_url,
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
            "Analytics/crash-reports disabled.  To learn more see: %s",
            analytics_docs_url,
        )


def analytics_shutdown() -> None:
    """Shut down the analytics service, if enabled."""
    if analytics_allowed:
        import sentry_sdk

        sentry_sdk.flush()


def is_development_environment() -> bool:
    """Detect if running in a development environment."""
    import os
    import sys
    from pathlib import Path

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

        report_id = sentry_sdk.capture_exception(exc)

        logging.info(
            f"""An unexpected error has occurred and been reported.  Thank you for your help.
                If you'd like to chat with the devs about it, please click
                [link={new_issue_url(str(report_id))}]here[/link] to open an issue.""",
        )
    else:
        logging.error(
            f"""An unexpected error has occurred. Automated crash reporting is disabled,
                      but we encourage you to contact the developers
                      at [link={new_issue_url()}]here[/link] and we will try to help.
                      The full exception is: {exc}"""
        )


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
        return NopContextManager()
