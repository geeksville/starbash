import logging
import os

from .database import Database  # re-export for convenience
from rich.console import Console

# Disable Rich formatting in test environments (pytest or NO_COLOR set)
# This prevents ANSI escape codes in test output for more reliable test parsing.
_is_test_env = "PYTEST_VERSION" in os.environ or os.getenv("NO_COLOR")
console = Console(force_terminal=False if _is_test_env else None)

# Global variable for log filter level (can be changed via --debug flag)
log_filter_level = logging.INFO

__all__ = ["Database"]
