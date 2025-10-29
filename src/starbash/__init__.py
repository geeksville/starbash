import logging

from .database import Database  # re-export for convenience
from rich.console import Console

console = Console()

# Global variable for log filter level (can be changed via --debug flag)
log_filter_level = logging.INFO

__all__ = ["Database"]
