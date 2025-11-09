"""Selection state management for filtering sessions and targets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starbash.database import SearchCondition

from repo import Repo
from starbash.aliases import normalize_target_name


def build_search_conditions(
    conditions: dict[str, Any] | None,
) -> list[SearchCondition]:
    """Build a list of SearchCondition objects from a conditions dictionary.

    Args:
        conditions: Dictionary of session key-value pairs to match, or None for all.
                    Special keys:
                    - 'date_start': Filter sessions starting on or after this date
                    - 'date_end': Filter sessions starting on or before this date

    Returns:
        List of SearchCondition tuples for database queries
    """
    # Import here to avoid circular dependency
    from starbash.database import SearchCondition

    if conditions is None:
        conditions = {}

    search_conditions = []

    # Extract date range conditions
    date_start = conditions.get("date_start")
    date_end = conditions.get("date_end")

    # Add date range filters as SearchConditions
    if date_start:
        search_conditions.append(SearchCondition("start", ">=", date_start))

    if date_end:
        search_conditions.append(SearchCondition("start", "<=", date_end))

    # Add standard conditions as SearchConditions
    for key, value in conditions.items():
        if key not in ("date_start", "date_end") and value is not None:
            search_conditions.append(SearchCondition(key, "=", value))

    return search_conditions


class Selection:
    """Manages the current selection state for filtering sessions and targets.

    This class maintains persistent state about what the user has selected:
    - Target names
    - Date ranges
    - Filters
    - Image types
    - Telescope names

    The selection state is saved to the user config repo TOML file and can be
    used to build database queries.
    """

    def __init__(self, user_repo: Repo):
        """Initialize the Selection with the user config repository.

        Args:
            user_repo: The Repo object for user preferences where selection state is persisted
        """
        self.user_repo = user_repo
        self.targets: list[str] = []
        self.date_start: str | None = None
        self.date_end: str | None = None
        self.filters: list[str] = []
        self.image_types: list[str] = []
        self.telescopes: list[str] = []

        # Load existing state if it exists
        self._load()

    def _load(self) -> None:
        """Load selection state from user config repo."""
        try:
            # Load with type-safe defaults
            targets = self.user_repo.get("selection.targets", [])
            self.targets = targets if isinstance(targets, list) else []

            self.date_start = self.user_repo.get("selection.date_start")
            self.date_end = self.user_repo.get("selection.date_end")

            filters = self.user_repo.get("selection.filters", [])
            self.filters = filters if isinstance(filters, list) else []

            image_types = self.user_repo.get("selection.image_types", [])
            self.image_types = image_types if isinstance(image_types, list) else []

            telescopes = self.user_repo.get("selection.telescopes", [])
            self.telescopes = telescopes if isinstance(telescopes, list) else []

            logging.debug(f"Loaded selection state from {self.user_repo.url}")
        except Exception as e:
            logging.warning(f"Failed to load selection state: {e}")

    def _save(self) -> None:
        """Save selection state to user config repo."""
        try:
            self.user_repo.set("selection.targets", self.targets)

            # Handle date fields - set if not None, delete if None (to clear them)
            if self.date_start is not None:
                self.user_repo.set("selection.date_start", self.date_start)
            else:
                # Delete the key if it exists
                if "selection" in self.user_repo.config:
                    sel_section = self.user_repo.config["selection"]
                    if isinstance(sel_section, dict) and "date_start" in sel_section:
                        del sel_section["date_start"]  # type: ignore

            if self.date_end is not None:
                self.user_repo.set("selection.date_end", self.date_end)
            else:
                # Delete the key if it exists
                if "selection" in self.user_repo.config:
                    sel_section = self.user_repo.config["selection"]
                    if isinstance(sel_section, dict) and "date_end" in sel_section:
                        del sel_section["date_end"]  # type: ignore

            self.user_repo.set("selection.filters", self.filters)
            self.user_repo.set("selection.image_types", self.image_types)
            self.user_repo.set("selection.telescopes", self.telescopes)

            # Write the updated config to disk
            self.user_repo.write_config()
            logging.debug(f"Saved selection state to {self.user_repo.url}")
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

    def set_date_range(self, start: str | None = None, end: str | None = None) -> None:
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

    def get_query_conditions(self) -> list[SearchCondition]:
        """Build query conditions based on the current selection.

        Returns:
            A list of SearchCondition objects for database queries
        """
        conditions = {}

        # Note: This returns a simplified conditions dict.
        # The actual query building will be enhanced later to support
        # complex queries with date ranges, multiple targets, etc.

        if self.targets:
            # For now, just use the first target
            # TODO: Support multiple targets in queries
            conditions["OBJECT"] = (
                normalize_target_name(self.targets[0]) if len(self.targets) == 1 else None
            )

        if self.filters:
            # For now, just use the first filter
            # TODO: Support multiple filters in queries
            conditions["FILTER"] = self.filters[0] if len(self.filters) == 1 else None

        if self.telescopes:
            # For now, just use the first telescope
            # TODO: Support multiple telescopes in queries
            conditions["TELESCOP"] = self.telescopes[0] if len(self.telescopes) == 1 else None

        # Add date range conditions
        if self.date_start:
            conditions["date_start"] = self.date_start
        if self.date_end:
            conditions["date_end"] = self.date_end

        return build_search_conditions(conditions)

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
