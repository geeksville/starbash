import logging
from importlib.metadata import PackageNotFoundError, version

from update_checker import UpdateChecker


def check_version():
    """Check if a newer version of starbash is available on PyPI."""
    try:
        checker = UpdateChecker()
        current_version = version("starbash")
        result = checker.check("starbash", current_version)
        if result:
            logging.warning(result)

    except PackageNotFoundError:
        # Package not installed (e.g., running from source during development)
        pass
