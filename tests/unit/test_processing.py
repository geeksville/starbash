"""Tests for starbash.processing module utility functions."""

from pathlib import Path

import pytest

from starbash.processing import (
    _inputs_by_kind,
    _make_imagerow,
    _stage_to_doc,
    create_default_task,
    remove_tasks_by_stage_name,
    tasks_to_stages,
)


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
