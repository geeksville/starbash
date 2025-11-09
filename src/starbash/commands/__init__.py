"""Shared utilities for starbash commands."""

from rich.style import Style

# Define reusable table styles
TABLE_COLUMN_STYLE = Style(color="cyan")
TABLE_VALUE_STYLE = Style(color="green")
TABLE_HEADER_STYLE = Style(color="magenta", bold=True)
SPINNER_STYLE = Style(color="magenta", bold=True)


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
