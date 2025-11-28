import logging
import os
from datetime import datetime
from typing import Any

from rich.console import Console

# Common type aliases for clarity
type StageDict = dict[str, Any]  # a processing stage definition from our toml
type InputDef = dict[str, Any]  # an input definition within a stage
type OutputDef = dict[str, Any]  # an output definition within a stage
type RequireDef = dict[str, Any]  # a requires definition within an input
type Metadata = dict[str, Any]  # image metadata dictionary

# Disable Rich formatting in test environments (pytest or NO_COLOR set)
# This prevents ANSI escape codes and line wrapping in test output for more reliable test parsing.
_is_test_env = "PYTEST_VERSION" in os.environ

# Note: this console instance is probably never used - because the Starbash constructor slams in a new version into
# this global.
console = Console(
    force_terminal=False if _is_test_env else None,
    width=999999 if _is_test_env else None,  # Disable line wrapping in tests
)

# Global variable for log filter level (can be changed via --debug flag)
log_filter_level = logging.INFO

# Global variable for forcing some file generation
force_regen = False

# Show extra command output
verbose_output = False

# Should we automatically process masters?
process_masters = True


def to_shortdate(date_iso: str) -> str:
    """Convert ISO UTC datetime string to local short date string (YYYY-MM-DD).

    Args:
        date_iso: ISO format datetime string (e.g., "2023-10-15T14:30:00Z")

    Returns:
        Short date string in YYYY-MM-DD format
    """
    try:
        dt_utc = datetime.fromisoformat(date_iso)
        dt_local = dt_utc.astimezone()
        return dt_local.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_iso


__all__ = ["console", "to_shortdate", "log_filter_level", "force_regen", "verbose_output"]
