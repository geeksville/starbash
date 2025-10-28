import logging

from starbash import console

# Default to no analytics/auto crash reports
analytics_allowed = False

project_url = "https://github.com/geeksville/starbash"
analytics_docs_url = f"{project_url}/blob/main/doc/analytics.md"


def new_issue_url(report_id: str) -> str:
    return f"{project_url}/issues/new?body=Please%20describe%20the%20problem%2C%20but%20include%20this%3A%0ACrash%20ID%20{report_id}"


def analytics_setup(allowed: bool = False) -> None:
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

        # if user blesses
        # sentry_sdk.set_user({"email": "jane.doe@example.com"})
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


def analytics_exception(exc: Exception) -> None:
    """Report an exception to the analytics service, if enabled."""

    if analytics_allowed:
        import sentry_sdk

        report_id = sentry_sdk.capture_exception(exc)

        console.print(
            f"""An error has occurred and been reported.  Thank you for your help.
                If you'd like to chat with the devs about it, please click
                [link={new_issue_url(str(report_id))}]here[/link] to open an issue.""",
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
