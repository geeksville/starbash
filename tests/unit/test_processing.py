"""Tests for starbash.processing module utility functions."""

from pathlib import Path

import pytest

from starbash.processed_target import tasks_to_stages
from starbash.processing import (
    _inputs_by_kind,
    _make_imagerow,
    _stage_to_doc,
    create_default_task,
)


def remove_tasks_by_stage_name(tasks: list[dict], excluded: list[str]) -> list[dict]:
    """Helper function to remove tasks by stage name (for testing)."""
    return [t for t in tasks if t["meta"]["stage"]["name"] not in excluded]


class TestMakeImagerow:
    """Tests for _make_imagerow function."""

    def test_make_imagerow_basic(self):
        """Test creating a basic imagerow."""
        dir_path = Path("/test/directory")
        filename = "image.fits"

        result = _make_imagerow(dir_path, filename)

        assert "abspath" in result
        assert "path" in result
        assert result["abspath"] == str(dir_path / filename)
        assert result["path"] == filename

    def test_make_imagerow_with_subdirectory(self):
        """Test creating imagerow with nested path."""
        dir_path = Path("/test/directory")
        filename = "subdir/nested/image.fits"

        result = _make_imagerow(dir_path, filename)

        assert result["abspath"] == str(dir_path / filename)
        assert result["path"] == filename


class TestStageToDoc:
    """Tests for _stage_to_doc function."""

    def test_stage_to_doc_with_description(self):
        """Test setting doc from stage description."""
        task = {}
        stage = {"description": "Process bias frames"}

        _stage_to_doc(task, stage)

        assert task["doc"] == "Process bias frames"

    def test_stage_to_doc_without_description(self):
        """Test default doc when stage has no description."""
        task = {}
        stage = {}

        _stage_to_doc(task, stage)

        assert task["doc"] == "No description provided"

    def test_stage_to_doc_overwrites_existing(self):
        """Test that _stage_to_doc overwrites existing doc."""
        task = {"doc": "Old description"}
        stage = {"description": "New description"}

        _stage_to_doc(task, stage)

        assert task["doc"] == "New description"


class TestInputsByKind:
    """Tests for _inputs_by_kind function."""

    def test_inputs_by_kind_filters_correctly(self):
        """Test filtering inputs by kind."""
        stage = {
            "inputs": [
                {"kind": "session", "name": "lights"},
                {"kind": "file", "name": "config"},
                {"kind": "session", "name": "darks"},
                {"kind": "master", "name": "bias"},
            ]
        }

        session_inputs = _inputs_by_kind(stage, "session")

        assert len(session_inputs) == 2
        assert all(inp["kind"] == "session" for inp in session_inputs)
        assert session_inputs[0]["name"] == "lights"
        assert session_inputs[1]["name"] == "darks"

    def test_inputs_by_kind_no_matches(self):
        """Test when no inputs match the kind."""
        stage = {
            "inputs": [
                {"kind": "session", "name": "lights"},
                {"kind": "file", "name": "config"},
            ]
        }

        results = _inputs_by_kind(stage, "master")

        assert len(results) == 0
        assert results == []

    def test_inputs_by_kind_no_inputs(self):
        """Test when stage has no inputs."""
        stage = {}

        results = _inputs_by_kind(stage, "session")

        assert len(results) == 0

    def test_inputs_by_kind_empty_inputs(self):
        """Test when stage has empty inputs list."""
        stage = {"inputs": []}

        results = _inputs_by_kind(stage, "session")

        assert len(results) == 0


class TestTasksToStages:
    """Tests for tasks_to_stages function."""

    def test_tasks_to_stages_unique_stages(self):
        """Test extracting unique stages from tasks."""
        tasks = [
            {"meta": {"stage": {"name": "preprocessing", "priority": 10}}},
            {"meta": {"stage": {"name": "stacking", "priority": 20}}},
            {"meta": {"stage": {"name": "preprocessing", "priority": 10}}},
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 2
        stage_names = [s["name"] for s in stages]
        assert "preprocessing" in stage_names
        assert "stacking" in stage_names

    def test_tasks_to_stages_sorted_by_priority(self):
        """Test that stages are sorted by priority (highest first)."""
        tasks = [
            {"meta": {"stage": {"name": "c", "priority": 30}}},
            {"meta": {"stage": {"name": "a", "priority": 10}}},
            {"meta": {"stage": {"name": "b", "priority": 20}}},
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 3
        assert stages[0]["name"] == "c"
        assert stages[0]["priority"] == 30
        assert stages[1]["name"] == "b"
        assert stages[2]["name"] == "a"

    def test_tasks_to_stages_empty_list(self):
        """Test with empty task list."""
        tasks = []

        stages = tasks_to_stages(tasks)

        assert len(stages) == 0

    def test_tasks_to_stages_preserves_stage_data(self):
        """Test that stage data is preserved."""
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "test",
                        "priority": 10,
                        "description": "Test stage",
                        "custom_field": "value",
                    }
                }
            }
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 1
        assert stages[0]["name"] == "test"
        assert stages[0]["description"] == "Test stage"
        assert stages[0]["custom_field"] == "value"

    def test_tasks_to_stages_respects_after_dependencies(self):
        """Test that stages with 'after' dependencies are ordered correctly."""
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "stack",
                        "priority": 100,
                        "inputs": [{"kind": "job", "after": "light"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "light",
                        "priority": 200,
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 2
        # Despite stack having lower priority, light should come first because stack depends on it
        assert stages[0]["name"] == "light"
        assert stages[1]["name"] == "stack"

    def test_tasks_to_stages_regex_after_dependencies(self):
        """Test that stages with regex 'after' patterns match correctly."""
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "seqextract_haoiii",
                        "priority": 500,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "light_calibration",
                        "priority": 600,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "stack_dual_duo",
                        "priority": 330,
                        "inputs": [{"kind": "job", "after": "seqextract_haoiii"}],
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 3
        # seqextract should come before stack_dual_duo due to dependency
        seqextract_idx = next(i for i, s in enumerate(stages) if s["name"] == "seqextract_haoiii")
        stack_idx = next(i for i, s in enumerate(stages) if s["name"] == "stack_dual_duo")
        assert seqextract_idx < stack_idx

    def test_tasks_to_stages_wildcard_after_dependencies(self):
        """Test that stages with wildcard 'after' patterns work correctly."""
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "light_session1",
                        "priority": 600,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "light_session2",
                        "priority": 600,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "background",
                        "priority": 400,
                        "inputs": [{"kind": "job", "after": "stack.*"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "stack_final",
                        "priority": 500,
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 4
        # stack_final should come before background due to dependency
        stack_idx = next(i for i, s in enumerate(stages) if s["name"] == "stack_final")
        bg_idx = next(i for i, s in enumerate(stages) if s["name"] == "background")
        assert stack_idx < bg_idx

    def test_tasks_to_stages_chain_dependencies(self):
        """Test that chained dependencies (A->B->C) are resolved correctly."""
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "final",
                        "priority": 100,
                        "inputs": [{"kind": "job", "after": "middle"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "middle",
                        "priority": 200,
                        "inputs": [{"kind": "job", "after": "start"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "start",
                        "priority": 300,
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 3
        assert stages[0]["name"] == "start"
        assert stages[1]["name"] == "middle"
        assert stages[2]["name"] == "final"

    def test_tasks_to_stages_priority_overrides_when_no_deps(self):
        """Test that higher priority stages come first when there are no dependencies.
        
        This catches bugs where dependency logic interferes with priority ordering
        for independent stages.
        """
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "low_priority",
                        "priority": 100,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "high_priority",
                        "priority": 500,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "medium_priority",
                        "priority": 300,
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 3
        # Without dependencies, should be sorted by priority (highest first)
        assert stages[0]["name"] == "high_priority"
        assert stages[1]["name"] == "medium_priority"
        assert stages[2]["name"] == "low_priority"

    def test_tasks_to_stages_dependency_overrides_priority(self):
        """Test that dependencies override priority - even when dependent stage has higher priority.
        
        This is the key test that would have caught the original bug where veralux
        (depending on background) was placed before background despite the dependency.
        """
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "veralux",
                        "priority": 900,  # Very high priority
                        "inputs": [{"kind": "job", "after": "background.*"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "background",
                        "priority": 100,  # Low priority
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 2
        # Despite veralux having much higher priority, background must come first
        assert stages[0]["name"] == "background", (
            "Dependency must be satisfied before dependent stage, "
            "regardless of priority"
        )
        assert stages[1]["name"] == "veralux"

    def test_tasks_to_stages_complex_dependency_chain(self):
        """Test a complex realistic scenario with multiple stages and dependencies.
        
        This simulates the real-world case from the bug report with multiple
        stages having different priorities and dependencies.
        """
        tasks = [
            {
                "meta": {
                    "stage": {
                        "name": "stack_dual_duo",
                        "priority": 330,
                        "inputs": [{"kind": "job", "after": "seqextract_haoiii"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "seqextract_haoiii",
                        "priority": 500,
                        "inputs": [{"kind": "job", "after": "light.*"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "light_vs_bias",
                        "priority": 600,
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "background",
                        "priority": 400,
                        "inputs": [{"kind": "job", "after": "stack.*"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "veralux",
                        "priority": 350,
                        "inputs": [{"kind": "job", "after": "background.*"}],
                    }
                }
            },
            {
                "meta": {
                    "stage": {
                        "name": "thumbnail",
                        "priority": 100,
                        "inputs": [{"kind": "job", "after": "stack.*"}],
                    }
                }
            },
        ]

        stages = tasks_to_stages(tasks)

        assert len(stages) == 6

        # Get indices for dependency verification
        light_idx = next(i for i, s in enumerate(stages) if s["name"] == "light_vs_bias")
        seqextract_idx = next(i for i, s in enumerate(stages) if s["name"] == "seqextract_haoiii")
        stack_idx = next(i for i, s in enumerate(stages) if s["name"] == "stack_dual_duo")
        background_idx = next(i for i, s in enumerate(stages) if s["name"] == "background")
        veralux_idx = next(i for i, s in enumerate(stages) if s["name"] == "veralux")
        thumbnail_idx = next(i for i, s in enumerate(stages) if s["name"] == "thumbnail")

        # Verify dependency chain: light -> seqextract -> stack
        assert light_idx < seqextract_idx, "light must come before seqextract (dependency)"
        assert seqextract_idx < stack_idx, "seqextract must come before stack (dependency)"

        # Verify stack -> background -> veralux chain
        assert stack_idx < background_idx, "stack must come before background (dependency)"
        assert background_idx < veralux_idx, "background must come before veralux (dependency)"

        # Verify stack -> thumbnail
        assert stack_idx < thumbnail_idx, "stack must come before thumbnail (dependency)"

        # Additional check: veralux should come after background despite potentially higher priority
        assert background_idx < veralux_idx, (
            "This is the key bug: veralux depends on background.*, "
            "so background must come first"
        )


class TestRemoveTasksByStageName:
    """Tests for remove_tasks_by_stage_name function."""

    def test_remove_tasks_by_stage_name_removes_matches(self):
        """Test removing tasks with excluded stage names."""
        tasks = [
            {"meta": {"stage": {"name": "keep1"}}},
            {"meta": {"stage": {"name": "remove"}}},
            {"meta": {"stage": {"name": "keep2"}}},
            {"meta": {"stage": {"name": "remove"}}},
        ]
        excluded = ["remove"]

        result = remove_tasks_by_stage_name(tasks, excluded)

        assert len(result) == 2
        assert all(t["meta"]["stage"]["name"] != "remove" for t in result)

    def test_remove_tasks_multiple_exclusions(self):
        """Test removing tasks with multiple excluded names."""
        tasks = [
            {"meta": {"stage": {"name": "keep"}}},
            {"meta": {"stage": {"name": "remove1"}}},
            {"meta": {"stage": {"name": "remove2"}}},
        ]
        excluded = ["remove1", "remove2"]

        result = remove_tasks_by_stage_name(tasks, excluded)

        assert len(result) == 1
        assert result[0]["meta"]["stage"]["name"] == "keep"

    def test_remove_tasks_empty_exclusion_list(self):
        """Test with empty exclusion list returns all tasks."""
        tasks = [
            {"meta": {"stage": {"name": "task1"}}},
            {"meta": {"stage": {"name": "task2"}}},
        ]
        excluded = []

        result = remove_tasks_by_stage_name(tasks, excluded)

        assert len(result) == 2
        assert result == tasks

    def test_remove_tasks_no_matches(self):
        """Test when no tasks match exclusion list."""
        tasks = [
            {"meta": {"stage": {"name": "task1"}}},
            {"meta": {"stage": {"name": "task2"}}},
        ]
        excluded = ["task3", "task4"]

        result = remove_tasks_by_stage_name(tasks, excluded)

        assert len(result) == 2
        assert result == tasks


class TestCreateDefaultTask:
    """Tests for create_default_task function."""

    def test_create_default_task_structure(self):
        """Test that default task has required structure."""
        tasks = [
            {
                "name": "test1",
                "meta": {
                    "stage": {"name": "test1", "priority": 10, "outputs": [{"kind": "master"}]}
                },
            },
            {
                "name": "test2",
                "meta": {
                    "stage": {"name": "test2", "priority": 20, "outputs": [{"kind": "processed"}]}
                },
            },
        ]

        default_task = create_default_task(tasks)

        assert "name" in default_task
        assert "actions" in default_task
        assert "task_dep" in default_task
        assert "doc" in default_task

    def test_create_default_task_name(self):
        """Test that default task has correct name."""
        tasks = []

        default_task = create_default_task(tasks)

        assert default_task["name"] == "process_all"

    def test_create_default_task_with_tasks(self):
        """Test default task with actual tasks."""
        tasks = [
            {
                "name": "preprocessing",
                "meta": {
                    "stage": {
                        "name": "preprocessing",
                        "priority": 10,
                        "outputs": [{"kind": "master"}],
                    }
                },
            },
            {
                "name": "stacking",
                "meta": {
                    "stage": {
                        "name": "stacking",
                        "priority": 20,
                        "outputs": [{"kind": "processed"}],
                    }
                },
            },
        ]

        default_task = create_default_task(tasks)

        # Should create a task that depends on high-value tasks
        assert "task_dep" in default_task
        assert len(default_task["task_dep"]) == 2
        assert "preprocessing" in default_task["task_dep"]
        assert "stacking" in default_task["task_dep"]

    def test_create_default_task_empty_tasks(self):
        """Test default task with empty task list."""
        tasks = []

        default_task = create_default_task(tasks)

        # Should still create valid structure
        assert default_task["name"] == "process_all"
        assert "actions" in default_task
        assert default_task["task_dep"] == []

    def test_create_default_task_meta_structure(self):
        """Test that only high-value outputs are included."""
        tasks = [
            {
                "name": "low_value",
                "meta": {"stage": {"name": "test", "priority": 10, "outputs": [{"kind": "temp"}]}},
            },
            {
                "name": "high_value",
                "meta": {
                    "stage": {"name": "test2", "priority": 20, "outputs": [{"kind": "master"}]}
                },
            },
        ]

        default_task = create_default_task(tasks)

        # Should only include high-value task
        assert len(default_task["task_dep"]) == 1
        assert "high_value" in default_task["task_dep"]
        assert "low_value" not in default_task["task_dep"]


class TestProcessingUtilityIntegration:
    """Integration tests for processing utilities working together."""

    def test_stage_extraction_and_filtering_workflow(self):
        """Test typical workflow of extracting stages and filtering tasks."""
        tasks = [
            {
                "name": "prep1",
                "meta": {
                    "stage": {
                        "name": "preprocessing",
                        "priority": 10,
                        "outputs": [{"kind": "master"}],
                    }
                },
            },
            {
                "name": "calib",
                "meta": {
                    "stage": {"name": "calibration", "priority": 5, "outputs": [{"kind": "temp"}]}
                },
            },
            {
                "name": "stack",
                "meta": {
                    "stage": {
                        "name": "stacking",
                        "priority": 20,
                        "outputs": [{"kind": "processed"}],
                    }
                },
            },
            {
                "name": "prep2",
                "meta": {
                    "stage": {
                        "name": "preprocessing",
                        "priority": 10,
                        "outputs": [{"kind": "master"}],
                    }
                },
            },
        ]

        # Extract unique stages
        stages = tasks_to_stages(tasks)
        assert len(stages) == 3

        # Remove certain stages
        filtered = remove_tasks_by_stage_name(tasks, ["calibration"])
        assert len(filtered) == 3

        # Create default task from filtered
        default = create_default_task(filtered)
        assert default["name"] == "process_all"
        # Should include only high-value tasks
        assert len(default["task_dep"]) == 3
        assert "prep1" in default["task_dep"]
        assert "prep2" in default["task_dep"]
        assert "stack" in default["task_dep"]

    def test_multiple_inputs_filtering(self):
        """Test filtering multiple input types from a stage."""
        stage = {
            "inputs": [
                {"kind": "session", "name": "lights", "imagetyp": "light"},
                {"kind": "session", "name": "darks", "imagetyp": "dark"},
                {"kind": "master", "name": "bias", "path": "bias.fits"},
                {"kind": "file", "name": "config", "path": "config.toml"},
                {"kind": "session", "name": "flats", "imagetyp": "flat"},
            ]
        }

        sessions = _inputs_by_kind(stage, "session")
        masters = _inputs_by_kind(stage, "master")
        files = _inputs_by_kind(stage, "file")

        assert len(sessions) == 3
        assert len(masters) == 1
        assert len(files) == 1
