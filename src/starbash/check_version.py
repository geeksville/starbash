from importlib.metadata import PackageNotFoundError, version


def check_version():
    """Check if a newer version of starbash is available on PyPI."""
    try:
        current_version = version("starbash")
        # warn_if_outdated("starbash", current_version)
    except PackageNotFoundError:
        # Package not installed (e.g., running from source during development)
        pass
