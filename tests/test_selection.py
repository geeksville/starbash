"""Unit tests for the Selection class."""

import json
from pathlib import Path
import pytest

from starbash.selection import Selection


@pytest.fixture
def temp_state_file(tmp_path):
    """Create a temporary state file path."""
    return tmp_path / "selection.json"


@pytest.fixture
def selection(temp_state_file):
    """Create a Selection instance with a temporary state file."""
    return Selection(temp_state_file)


class TestSelectionInit:
    """Tests for Selection initialization."""

    def test_init_creates_empty_selection(self, temp_state_file):
        """Test that initializing Selection creates empty state."""
        sel = Selection(temp_state_file)
        assert sel.targets == []
        assert sel.date_start is None
        assert sel.date_end is None
        assert sel.filters == []
        assert sel.image_types == []
        assert sel.telescopes == []

    def test_init_loads_existing_state(self, temp_state_file):
        """Test that initializing Selection loads existing state from disk."""
        # Create a state file with data
        state_data = {
            "targets": ["M31", "M42"],
            "date_start": "2023-01-01",
            "date_end": "2023-12-31",
            "filters": ["Ha", "OIII"],
            "image_types": ["Light"],
            "telescopes": ["Vespera"],
        }
        temp_state_file.write_text(json.dumps(state_data))

        # Load selection
        sel = Selection(temp_state_file)
        assert sel.targets == ["M31", "M42"]
        assert sel.date_start == "2023-01-01"
        assert sel.date_end == "2023-12-31"
        assert sel.filters == ["Ha", "OIII"]
        assert sel.image_types == ["Light"]
        assert sel.telescopes == ["Vespera"]

    def test_init_handles_missing_file(self, temp_state_file):
        """Test that initializing Selection with non-existent file works."""
        sel = Selection(temp_state_file)
        assert sel.targets == []
        assert not temp_state_file.exists()

    def test_init_handles_corrupt_json(self, temp_state_file, caplog):
        """Test that initializing Selection handles corrupt JSON gracefully."""
        temp_state_file.write_text("not valid json{{{")

        sel = Selection(temp_state_file)
        # Should still create empty selection
        assert sel.targets == []
        assert "Failed to load selection state" in caplog.text

    def test_init_handles_partial_data(self, temp_state_file):
        """Test that initializing Selection handles partial state data."""
        # Only some fields present
        state_data = {"targets": ["M31"]}
        temp_state_file.write_text(json.dumps(state_data))

        sel = Selection(temp_state_file)
        assert sel.targets == ["M31"]
        assert sel.date_start is None
        assert sel.filters == []


class TestSelectionSave:
    """Tests for Selection._save method."""

    def test_save_creates_file(self, selection, temp_state_file):
        """Test that saving creates the state file."""
        selection.targets = ["M31"]
        selection._save()

        assert temp_state_file.exists()

    def test_save_creates_parent_directory(self, tmp_path):
        """Test that saving creates parent directories if needed."""
        nested_path = tmp_path / "subdir" / "another" / "selection.json"
        sel = Selection(nested_path)
        sel.targets = ["M31"]
        sel._save()

        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_save_writes_all_fields(self, selection, temp_state_file):
        """Test that saving writes all selection fields."""
        selection.targets = ["M31"]
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"
        selection.filters = ["Ha"]
        selection.image_types = ["Light"]
        selection.telescopes = ["Vespera"]
        selection._save()

        data = json.loads(temp_state_file.read_text())
        assert data["targets"] == ["M31"]
        assert data["date_start"] == "2023-01-01"
        assert data["date_end"] == "2023-12-31"
        assert data["filters"] == ["Ha"]
        assert data["image_types"] == ["Light"]
        assert data["telescopes"] == ["Vespera"]

    def test_save_handles_write_error(self, selection, caplog):
        """Test that save handles write errors gracefully."""
        # Make the file path invalid (directory instead of file)
        selection.state_file.mkdir(parents=True, exist_ok=True)

        selection.targets = ["M31"]
        selection._save()  # Should not raise

        assert "Failed to save selection state" in caplog.text


class TestSelectionClear:
    """Tests for Selection.clear method."""

    def test_clear_removes_all_criteria(self, selection):
        """Test that clear removes all selection criteria."""
        selection.targets = ["M31"]
        selection.date_start = "2023-01-01"
        selection.filters = ["Ha"]
        selection.telescopes = ["Vespera"]

        selection.clear()

        assert selection.targets == []
        assert selection.date_start is None
        assert selection.date_end is None
        assert selection.filters == []
        assert selection.image_types == []
        assert selection.telescopes == []

    def test_clear_saves_state(self, selection, temp_state_file):
        """Test that clear saves the cleared state to disk."""
        selection.targets = ["M31"]
        selection._save()

        selection.clear()

        # Reload and verify cleared
        new_sel = Selection(temp_state_file)
        assert new_sel.targets == []


class TestSelectionAddTarget:
    """Tests for Selection.add_target method."""

    def test_add_target_adds_new_target(self, selection):
        """Test that add_target adds a new target."""
        selection.add_target("M31")
        assert "M31" in selection.targets

    def test_add_target_avoids_duplicates(self, selection):
        """Test that add_target doesn't add duplicates."""
        selection.add_target("M31")
        selection.add_target("M31")
        assert selection.targets.count("M31") == 1

    def test_add_target_saves_state(self, selection, temp_state_file):
        """Test that add_target saves state to disk."""
        selection.add_target("M31")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "M31" in new_sel.targets

    def test_add_multiple_targets(self, selection):
        """Test adding multiple targets."""
        selection.add_target("M31")
        selection.add_target("M42")
        assert selection.targets == ["M31", "M42"]


class TestSelectionRemoveTarget:
    """Tests for Selection.remove_target method."""

    def test_remove_target_removes_existing(self, selection):
        """Test that remove_target removes an existing target."""
        selection.targets = ["M31", "M42"]
        selection.remove_target("M31")
        assert "M31" not in selection.targets
        assert "M42" in selection.targets

    def test_remove_target_ignores_missing(self, selection):
        """Test that remove_target ignores missing targets."""
        selection.targets = ["M31"]
        selection.remove_target("M42")  # Should not raise
        assert selection.targets == ["M31"]

    def test_remove_target_saves_state(self, selection, temp_state_file):
        """Test that remove_target saves state to disk."""
        selection.targets = ["M31", "M42"]
        selection._save()

        selection.remove_target("M31")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "M31" not in new_sel.targets


class TestSelectionAddTelescope:
    """Tests for Selection.add_telescope method."""

    def test_add_telescope_adds_new_telescope(self, selection):
        """Test that add_telescope adds a new telescope."""
        selection.add_telescope("Vespera")
        assert "Vespera" in selection.telescopes

    def test_add_telescope_avoids_duplicates(self, selection):
        """Test that add_telescope doesn't add duplicates."""
        selection.add_telescope("Vespera")
        selection.add_telescope("Vespera")
        assert selection.telescopes.count("Vespera") == 1

    def test_add_telescope_saves_state(self, selection, temp_state_file):
        """Test that add_telescope saves state to disk."""
        selection.add_telescope("Vespera")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "Vespera" in new_sel.telescopes

    def test_add_multiple_telescopes(self, selection):
        """Test adding multiple telescopes."""
        selection.add_telescope("Vespera")
        selection.add_telescope("EdgeHD 8")
        assert selection.telescopes == ["Vespera", "EdgeHD 8"]


class TestSelectionRemoveTelescope:
    """Tests for Selection.remove_telescope method."""

    def test_remove_telescope_removes_existing(self, selection):
        """Test that remove_telescope removes an existing telescope."""
        selection.telescopes = ["Vespera", "EdgeHD 8"]
        selection.remove_telescope("Vespera")
        assert "Vespera" not in selection.telescopes
        assert "EdgeHD 8" in selection.telescopes

    def test_remove_telescope_ignores_missing(self, selection):
        """Test that remove_telescope ignores missing telescopes."""
        selection.telescopes = ["Vespera"]
        selection.remove_telescope("Other")  # Should not raise
        assert selection.telescopes == ["Vespera"]

    def test_remove_telescope_saves_state(self, selection, temp_state_file):
        """Test that remove_telescope saves state to disk."""
        selection.telescopes = ["Vespera", "EdgeHD 8"]
        selection._save()

        selection.remove_telescope("Vespera")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "Vespera" not in new_sel.telescopes


class TestSelectionSetDateRange:
    """Tests for Selection.set_date_range method."""

    def test_set_date_range_with_both_dates(self, selection):
        """Test setting date range with start and end dates."""
        selection.set_date_range(start="2023-01-01", end="2023-12-31")
        assert selection.date_start == "2023-01-01"
        assert selection.date_end == "2023-12-31"

    def test_set_date_range_with_start_only(self, selection):
        """Test setting date range with only start date."""
        selection.set_date_range(start="2023-01-01")
        assert selection.date_start == "2023-01-01"
        assert selection.date_end is None

    def test_set_date_range_with_end_only(self, selection):
        """Test setting date range with only end date."""
        selection.set_date_range(end="2023-12-31")
        assert selection.date_start is None
        assert selection.date_end == "2023-12-31"

    def test_set_date_range_clears_dates(self, selection):
        """Test that set_date_range can clear dates."""
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"

        selection.set_date_range(start=None, end=None)

        assert selection.date_start is None
        assert selection.date_end is None

    def test_set_date_range_saves_state(self, selection, temp_state_file):
        """Test that set_date_range saves state to disk."""
        selection.set_date_range(start="2023-01-01", end="2023-12-31")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert new_sel.date_start == "2023-01-01"
        assert new_sel.date_end == "2023-12-31"


class TestSelectionAddFilter:
    """Tests for Selection.add_filter method."""

    def test_add_filter_adds_new_filter(self, selection):
        """Test that add_filter adds a new filter."""
        selection.add_filter("Ha")
        assert "Ha" in selection.filters

    def test_add_filter_avoids_duplicates(self, selection):
        """Test that add_filter doesn't add duplicates."""
        selection.add_filter("Ha")
        selection.add_filter("Ha")
        assert selection.filters.count("Ha") == 1

    def test_add_filter_saves_state(self, selection, temp_state_file):
        """Test that add_filter saves state to disk."""
        selection.add_filter("Ha")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "Ha" in new_sel.filters

    def test_add_multiple_filters(self, selection):
        """Test adding multiple filters."""
        selection.add_filter("Ha")
        selection.add_filter("OIII")
        assert selection.filters == ["Ha", "OIII"]


class TestSelectionRemoveFilter:
    """Tests for Selection.remove_filter method."""

    def test_remove_filter_removes_existing(self, selection):
        """Test that remove_filter removes an existing filter."""
        selection.filters = ["Ha", "OIII"]
        selection.remove_filter("Ha")
        assert "Ha" not in selection.filters
        assert "OIII" in selection.filters

    def test_remove_filter_ignores_missing(self, selection):
        """Test that remove_filter ignores missing filters."""
        selection.filters = ["Ha"]
        selection.remove_filter("OIII")  # Should not raise
        assert selection.filters == ["Ha"]

    def test_remove_filter_saves_state(self, selection, temp_state_file):
        """Test that remove_filter saves state to disk."""
        selection.filters = ["Ha", "OIII"]
        selection._save()

        selection.remove_filter("Ha")

        # Reload and verify
        new_sel = Selection(temp_state_file)
        assert "Ha" not in new_sel.filters


class TestSelectionIsEmpty:
    """Tests for Selection.is_empty method."""

    def test_is_empty_returns_true_for_new_selection(self, selection):
        """Test that is_empty returns True for new selection."""
        assert selection.is_empty() is True

    def test_is_empty_returns_false_with_target(self, selection):
        """Test that is_empty returns False when target is set."""
        selection.targets = ["M31"]
        assert selection.is_empty() is False

    def test_is_empty_returns_false_with_date_start(self, selection):
        """Test that is_empty returns False when date_start is set."""
        selection.date_start = "2023-01-01"
        assert selection.is_empty() is False

    def test_is_empty_returns_false_with_date_end(self, selection):
        """Test that is_empty returns False when date_end is set."""
        selection.date_end = "2023-12-31"
        assert selection.is_empty() is False

    def test_is_empty_returns_false_with_filter(self, selection):
        """Test that is_empty returns False when filter is set."""
        selection.filters = ["Ha"]
        assert selection.is_empty() is False

    def test_is_empty_returns_false_with_image_type(self, selection):
        """Test that is_empty returns False when image_type is set."""
        selection.image_types = ["Light"]
        assert selection.is_empty() is False

    def test_is_empty_returns_false_with_telescope(self, selection):
        """Test that is_empty returns False when telescope is set."""
        selection.telescopes = ["Vespera"]
        assert selection.is_empty() is False

    def test_is_empty_after_clear(self, selection):
        """Test that is_empty returns True after clearing."""
        selection.targets = ["M31"]
        selection.clear()
        assert selection.is_empty() is True


class TestSelectionGetQueryConditions:
    """Tests for Selection.get_query_conditions method."""

    def test_get_query_conditions_empty_selection(self, selection):
        """Test that get_query_conditions returns empty dict for empty selection."""
        conditions = selection.get_query_conditions()
        assert conditions == {}

    def test_get_query_conditions_with_single_target(self, selection):
        """Test query conditions with a single target."""
        selection.targets = ["M31"]
        conditions = selection.get_query_conditions()
        assert conditions["OBJECT"] == "M31"

    def test_get_query_conditions_with_multiple_targets(self, selection):
        """Test query conditions with multiple targets (uses first)."""
        selection.targets = ["M31", "M42"]
        conditions = selection.get_query_conditions()
        # Currently returns None for multiple targets
        assert conditions["OBJECT"] is None

    def test_get_query_conditions_with_single_filter(self, selection):
        """Test query conditions with a single filter."""
        selection.filters = ["Ha"]
        conditions = selection.get_query_conditions()
        assert conditions["FILTER"] == "Ha"

    def test_get_query_conditions_with_multiple_filters(self, selection):
        """Test query conditions with multiple filters (uses first)."""
        selection.filters = ["Ha", "OIII"]
        conditions = selection.get_query_conditions()
        # Currently returns None for multiple filters
        assert conditions["FILTER"] is None

    def test_get_query_conditions_with_single_telescope(self, selection):
        """Test query conditions with a single telescope."""
        selection.telescopes = ["Vespera"]
        conditions = selection.get_query_conditions()
        assert conditions["TELESCOP"] == "Vespera"

    def test_get_query_conditions_with_multiple_telescopes(self, selection):
        """Test query conditions with multiple telescopes (uses first)."""
        selection.telescopes = ["Vespera", "EdgeHD 8"]
        conditions = selection.get_query_conditions()
        # Currently returns None for multiple telescopes
        assert conditions["TELESCOP"] is None

    def test_get_query_conditions_with_date_start(self, selection):
        """Test query conditions with date_start."""
        selection.date_start = "2023-01-01"
        conditions = selection.get_query_conditions()
        assert conditions["date_start"] == "2023-01-01"

    def test_get_query_conditions_with_date_end(self, selection):
        """Test query conditions with date_end."""
        selection.date_end = "2023-12-31"
        conditions = selection.get_query_conditions()
        assert conditions["date_end"] == "2023-12-31"

    def test_get_query_conditions_with_date_range(self, selection):
        """Test query conditions with both date_start and date_end."""
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"
        conditions = selection.get_query_conditions()
        assert conditions["date_start"] == "2023-01-01"
        assert conditions["date_end"] == "2023-12-31"

    def test_get_query_conditions_with_all_criteria(self, selection):
        """Test query conditions with all criteria set."""
        selection.targets = ["M31"]
        selection.filters = ["Ha"]
        selection.telescopes = ["Vespera"]
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"

        conditions = selection.get_query_conditions()

        assert conditions["OBJECT"] == "M31"
        assert conditions["FILTER"] == "Ha"
        assert conditions["TELESCOP"] == "Vespera"
        assert conditions["date_start"] == "2023-01-01"
        assert conditions["date_end"] == "2023-12-31"


class TestSelectionSummary:
    """Tests for Selection.summary method."""

    def test_summary_empty_selection(self, selection):
        """Test summary for empty selection."""
        summary = selection.summary()
        assert summary["status"] == "all"
        assert "selecting all sessions" in summary["message"].lower()

    def test_summary_with_target(self, selection):
        """Test summary with target set."""
        selection.targets = ["M31"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        assert any("M31" in criterion for criterion in summary["criteria"])

    def test_summary_with_multiple_targets(self, selection):
        """Test summary with multiple targets."""
        selection.targets = ["M31", "M42"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        # Should list both targets
        target_criterion = [c for c in summary["criteria"] if "Targets:" in c][0]
        assert "M31" in target_criterion
        assert "M42" in target_criterion

    def test_summary_with_telescope(self, selection):
        """Test summary with telescope set."""
        selection.telescopes = ["Vespera"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        assert any("Vespera" in criterion for criterion in summary["criteria"])

    def test_summary_with_multiple_telescopes(self, selection):
        """Test summary with multiple telescopes."""
        selection.telescopes = ["Vespera", "EdgeHD 8"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        telescope_criterion = [c for c in summary["criteria"] if "Telescopes:" in c][0]
        assert "Vespera" in telescope_criterion
        assert "EdgeHD 8" in telescope_criterion

    def test_summary_with_date_start_only(self, selection):
        """Test summary with only date_start."""
        selection.date_start = "2023-01-01"
        summary = selection.summary()
        assert summary["status"] == "filtered"
        date_criterion = [c for c in summary["criteria"] if "Date:" in c][0]
        assert "from 2023-01-01" in date_criterion

    def test_summary_with_date_end_only(self, selection):
        """Test summary with only date_end."""
        selection.date_end = "2023-12-31"
        summary = selection.summary()
        assert summary["status"] == "filtered"
        date_criterion = [c for c in summary["criteria"] if "Date:" in c][0]
        assert "to 2023-12-31" in date_criterion

    def test_summary_with_date_range(self, selection):
        """Test summary with date range."""
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"
        summary = selection.summary()
        assert summary["status"] == "filtered"
        date_criterion = [c for c in summary["criteria"] if "Date:" in c][0]
        assert "from 2023-01-01" in date_criterion
        assert "to 2023-12-31" in date_criterion

    def test_summary_with_filters(self, selection):
        """Test summary with filters."""
        selection.filters = ["Ha", "OIII"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        filter_criterion = [c for c in summary["criteria"] if "Filters:" in c][0]
        assert "Ha" in filter_criterion
        assert "OIII" in filter_criterion

    def test_summary_with_image_types(self, selection):
        """Test summary with image types."""
        selection.image_types = ["Light", "Dark"]
        summary = selection.summary()
        assert summary["status"] == "filtered"
        image_type_criterion = [c for c in summary["criteria"] if "Image types:" in c][
            0
        ]
        assert "Light" in image_type_criterion
        assert "Dark" in image_type_criterion

    def test_summary_with_all_criteria(self, selection):
        """Test summary with all criteria set."""
        selection.targets = ["M31"]
        selection.telescopes = ["Vespera"]
        selection.date_start = "2023-01-01"
        selection.date_end = "2023-12-31"
        selection.filters = ["Ha"]
        selection.image_types = ["Light"]

        summary = selection.summary()

        assert summary["status"] == "filtered"
        assert len(summary["criteria"]) == 5
        # Verify all criteria are present
        criteria_str = " ".join(summary["criteria"])
        assert "M31" in criteria_str
        assert "Vespera" in criteria_str
        assert "2023-01-01" in criteria_str
        assert "2023-12-31" in criteria_str
        assert "Ha" in criteria_str
        assert "Light" in criteria_str


class TestSelectionPersistence:
    """Tests for Selection state persistence."""

    def test_changes_persist_across_instances(self, temp_state_file):
        """Test that changes persist when creating new instances."""
        # Create first instance and modify
        sel1 = Selection(temp_state_file)
        sel1.add_target("M31")
        sel1.set_date_range(start="2023-01-01")

        # Create second instance and verify
        sel2 = Selection(temp_state_file)
        assert "M31" in sel2.targets
        assert sel2.date_start == "2023-01-01"

    def test_clear_persists(self, temp_state_file):
        """Test that clear operation persists."""
        # Add data
        sel1 = Selection(temp_state_file)
        sel1.add_target("M31")

        # Clear
        sel1.clear()

        # Verify cleared in new instance
        sel2 = Selection(temp_state_file)
        assert sel2.targets == []
        assert sel2.is_empty()

    def test_multiple_operations_persist(self, temp_state_file):
        """Test that multiple operations all persist correctly."""
        sel = Selection(temp_state_file)

        sel.add_target("M31")
        sel.add_telescope("Vespera")
        sel.add_filter("Ha")
        sel.set_date_range(start="2023-01-01", end="2023-12-31")

        # Reload and verify all operations persisted
        new_sel = Selection(temp_state_file)
        assert new_sel.targets == ["M31"]
        assert new_sel.telescopes == ["Vespera"]
        assert new_sel.filters == ["Ha"]
        assert new_sel.date_start == "2023-01-01"
        assert new_sel.date_end == "2023-12-31"
