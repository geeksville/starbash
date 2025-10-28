# Default to no analytics/auto crash reports
analytics_allowed = False


def analytics_setup(allowed: bool = False) -> None:
    import sentry_sdk

    global analytics_allowed
    analytics_allowed = allowed
    if analytics_allowed:
        sentry_sdk.init(
            dsn="https://e9496a4ea8b37a053203a2cbc10d64e6@o209837.ingest.us.sentry.io/4510264204132352",
            # Add data like request headers and IP for users,
            # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
            send_default_pii=True,
        )


def analytics_exception(exc: Exception) -> None:
    """Report an exception to the analytics service, if enabled."""

    if analytics_allowed:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
