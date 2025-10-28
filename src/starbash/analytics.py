import logging

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
        )
    else:
        logging.info(
            "Analytics/crash-reports disabled.  To learn more see: %s",
            analytics_docs_url,
        )


def analytics_exception(exc: Exception) -> None:
    """Report an exception to the analytics service, if enabled."""

    if analytics_allowed:
        import sentry_sdk

        report_id = sentry_sdk.capture_exception(exc)
        logging.error(
            """An error has occurred and been reported.  Thank you for your help.
                      If you'd like to chat with the devs about it, please open an issue here:
                      %s""",
            new_issue_url(str(report_id)),
        )
