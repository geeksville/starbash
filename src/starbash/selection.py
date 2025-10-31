"""Selection state management for filtering sessions and targets."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


def where_tuple(conditions: dict[str, Any] | None) -> tuple[str, list[Any]]:
    """Search for sessions matching the given conditions.

    Args:
        conditions: Dictionary of session key-value pairs to match, or None for all.
                    Special keys:
                    - 'date_start': Filter sessions starting on or after this date
                    - 'date_end': Filter sessions starting on or before this date

    Returns:
        Tuple of (WHERE clause string, list of parameters)
    """
    if conditions is None:
        conditions = {}

    # Build WHERE clause dynamically based on conditions
    where_clauses = []
    params = []

    # Extract date range conditions
    date_start = conditions.get("date_start")
    date_end = conditions.get("date_end")

    # Add date range filters to WHERE clause
    if date_start:
        where_clauses.append("start >= ?")
        params.append(date_start)

    if date_end:
        where_clauses.append("start <= ?")
        params.append(date_end)

    # Add standard conditions to WHERE clause
    for key, value in conditions.items():
        if key not in ("date_start", "date_end") and value is not None:
            column_name = key
            where_clauses.append(f"{column_name} = ?")
            params.append(value)

    # Build the query
    query = ""

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    return (query, params)


class Selection:
    """Manages the current selection state for filtering sessions and targets.

    This class maintains persistent state about what the user has selected:
    - Target names
    - Date ranges
    - Filters
    - Image types
    - Telescope names

    The selection state is saved to disk and can be used to build database queries.
    """

    def __init__(self, state_file: Path):
        """Initialize the Selection with a state file path.

        Args:
            state_file: Path to the JSON file where selection state is persisted
        """
        self.state_file = state_file
        self.targets: list[str] = []
        self.date_start: Optional[str] = None
        self.date_end: Optional[str] = None
        self.filters: list[str] = []
        self.image_types: list[str] = []
        self.telescopes: list[str] = []

        # Load existing state if it exists
        self._load()

    def _load(self) -> None:
        """Load selection state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.targets = data.get("targets", [])
                    self.date_start = data.get("date_start")
                    self.date_end = data.get("date_end")
                    self.filters = data.get("filters", [])
                    self.image_types = data.get("image_types", [])
                    self.telescopes = data.get("telescopes", [])
                logging.debug(f"Loaded selection state from {self.state_file}")
            except Exception as e:
                logging.warning(f"Failed to load selection state: {e}")

    def _save(self) -> None:
        """Save selection state to disk."""
        try:
            # Ensure parent directory exists
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "targets": self.targets,
                "date_start": self.date_start,
                "date_end": self.date_end,
                "filters": self.filters,
                "image_types": self.image_types,
                "telescopes": self.telescopes,
            }

            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
            logging.debug(f"Saved selection state to {self.state_file}")
        except Exception as e:
            logging.error(f"Failed to save selection state: {e}")

    def clear(self) -> None:
        """Clear all selection criteria (select everything)."""
        self.targets = []
        self.date_start = None
        self.date_end = None
        self.filters = []
        self.image_types = []
        self.telescopes = []
        self._save()

    def add_target(self, target: str) -> None:
        """Add a target to the selection.

        Args:
            target: Target name to add to the selection
        """
        if target not in self.targets:
            self.targets.append(target)
            self._save()

    def remove_target(self, target: str) -> None:
        """Remove a target from the selection.

        Args:
            target: Target name to remove from the selection
        """
        if target in self.targets:
            self.targets.remove(target)
            self._save()

    def add_telescope(self, telescope: str) -> None:
        """Add a telescope to the selection.

        Args:
            telescope: Telescope name to add to the selection
        """
        if telescope not in self.telescopes:
            self.telescopes.append(telescope)
            self._save()

    def remove_telescope(self, telescope: str) -> None:
        """Remove a telescope from the selection.

        Args:
            telescope: Telescope name to remove from the selection
        """
        if telescope in self.telescopes:
            self.telescopes.remove(telescope)
            self._save()

    def set_date_range(
        self, start: Optional[str] = None, end: Optional[str] = None
    ) -> None:
        """Set the date range for the selection.

        Args:
            start: ISO format date string for start of range (inclusive)
            end: ISO format date string for end of range (inclusive)
        """
        self.date_start = start
        self.date_end = end
        self._save()

    def add_filter(self, filter_name: str) -> None:
        """Add a filter to the selection.

        Args:
            filter_name: Filter name to add to the selection
        """
        if filter_name not in self.filters:
            self.filters.append(filter_name)
            self._save()

    def remove_filter(self, filter_name: str) -> None:
        """Remove a filter from the selection.

        Args:
            filter_name: Filter name to remove from the selection
        """
        if filter_name in self.filters:
            self.filters.remove(filter_name)
            self._save()

    def is_empty(self) -> bool:
        """Check if the selection has any criteria set.

        Returns:
            True if no selection criteria are active (selecting everything)
        """
        return (
            not self.targets
            and self.date_start is None
            and self.date_end is None
            and not self.filters
            and not self.image_types
            and not self.telescopes
        )

    def get_query_conditions(self) -> tuple[str, list[Any]]:
        """Build query conditions based on the current selection.

        Returns:
            A tuple of SQL (WHERE clause string, list of parameters)
        """
        conditions = {}

        # Note: This returns a simplified conditions dict.
        # The actual query building will be enhanced later to support
        # complex queries with date ranges, multiple targets, etc.

        if self.targets:
            # For now, just use the first target
            # TODO: Support multiple targets in queries
            conditions["OBJECT"] = self.targets[0] if len(self.targets) == 1 else None

        if self.filters:
            # For now, just use the first filter
            # TODO: Support multiple filters in queries
            conditions["FILTER"] = self.filters[0] if len(self.filters) == 1 else None

        if self.telescopes:
            # For now, just use the first telescope
            # TODO: Support multiple telescopes in queries
            conditions["TELESCOP"] = (
                self.telescopes[0] if len(self.telescopes) == 1 else None
            )

        # Add date range conditions
        if self.date_start:
            conditions["date_start"] = self.date_start
        if self.date_end:
            conditions["date_end"] = self.date_end

        return where_tuple(conditions)

    def summary(self) -> dict[str, Any]:
        """Get a summary of the current selection state.

        Returns:
            Dictionary with human-readable summary of selection criteria
        """
        if self.is_empty():
            return {
                "status": "all",
                "message": "No filters active - selecting all sessions",
            }

        summary = {"status": "filtered", "criteria": []}

        if self.targets:
            summary["criteria"].append(f"Targets: {', '.join(self.targets)}")

        if self.telescopes:
            summary["criteria"].append(f"Telescopes: {', '.join(self.telescopes)}")

        if self.date_start or self.date_end:
            date_range = []
            if self.date_start:
                date_range.append(f"from {self.date_start}")
            if self.date_end:
                date_range.append(f"to {self.date_end}")
            summary["criteria"].append(f"Date: {' '.join(date_range)}")

        if self.filters:
            summary["criteria"].append(f"Filters: {', '.join(self.filters)}")

        if self.image_types:
            summary["criteria"].append(f"Image types: {', '.join(self.image_types)}")

        return summary
