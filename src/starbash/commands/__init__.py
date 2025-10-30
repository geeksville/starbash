"""Shared utilities for starbash commands."""

from datetime import datetime
from rich.style import Style

# Define reusable table styles
TABLE_COLUMN_STYLE = Style(color="cyan")
TABLE_VALUE_STYLE = Style(color="green")


def format_duration(seconds: int | float) -> str:
    """Format seconds as a human-readable duration string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 120:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def to_shortdate(date_iso: str) -> str:
    """Convert ISO UTC datetime string to local short date string (YYYY-MM-DD).

    Args:
        date_iso: ISO format datetime string (e.g., "2023-10-15T14:30:00Z")

    Returns:
        Short date string in YYYY-MM-DD format, or the original string if conversion fails
    """
    try:
        dt_utc = datetime.fromisoformat(date_iso)
        dt_local = dt_utc.astimezone()
        return dt_local.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_iso
