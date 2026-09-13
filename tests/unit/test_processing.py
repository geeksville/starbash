"""Tests for starbash.processing module utility functions."""

from pathlib import Path
from typing import Any

import pytest

from starbash.stages import (
    create_default_task,
    inputs_by_kind,
    make_imagerow,
    stage_to_doc,
    tasks_to_stages,
)


class TestRunLogAttribution:
    """Tests that streamed lines reach (or are kept from) the active target's log tail."""

    def _processing_with_target(self) -> tuple[Any, list[str]]:
        """A Processing with only the bits ``_on_log_event`` needs, plus its log."""
        from starbash.processing import Processing

        recorded: list[str] = []

        class _Target:
            def record_log(self, line: str) -> None:
                recorded.append(line)

        processing = Processing.__new__(Processing)
        processing._active_target = _Target()  # type: ignore  # duck-typed stub
        return processing, recorded

    def test_records_tool_output_and_log_messages(self):
        from starbash import events

        processing, recorded = self._processing_with_target()

        processing._on_log_event(
            events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "working"})
        )
        processing._on_log_event(events.Event(events.EVENT_LOG_MESSAGE, {"message": "hello"}))

        assert recorded == ["working", "hello"]

    def test_skips_structured_stream_frames(self):
        """Protocol frames (e.g. rc-astro's --json) must not pollute the log tail."""
        from starbash import events

        processing, recorded = self._processing_with_target()

        processing._on_log_event(
            events.Event(
                events.EVENT_TOOL_OUTPUT,
                {"stream": "stdout.json", "line": '{"event":"progress","done":1}'},
            )
        )
        processing._on_log_event(
            events.Event(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "human"})
        )

        assert recorded == ["human"]


class TestImportFromPriorStages:
    """Tests for filtering outputs imported from multiplexed stages."""

    def _run_import(
        self,
        requires: list[dict],
        prior_tasks: list[dict],
        optional: bool = False,
    ):
        from starbash.processing import Processing

        processing = Processing.__new__(Processing)
        processing.stage = {"inputs": [{"after": "upstream"}]}
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._get_prior_tasks = lambda stage: prior_tasks
        return processing._import_from_prior_stages(
            {"kind": "job", "requires": requires, "optional": optional}
        )

    @staticmethod
    def _task(index: int) -> dict:
        from starbash.doit import FileInfo

        path = f"source_{index}.fits"
        output_path = f"output_{index}.fits"
        return {
            "name": f"upstream_i{index}",
            "meta": {
                "stage": {"name": "upstream"},
                "context": {
                    "input": {
                        0: FileInfo(
                            image_rows=[
                                {
                                    "abspath": f"/tmp/{path}",
                                    "path": path,
                                }
                            ]
                        )
                    },
                    "output": FileInfo(
                        base="/tmp",
                        image_rows=[
                            {
                                "abspath": f"/tmp/{output_path}",
                                "path": output_path,
                            }
                        ],
                    ),
                },
            },
        }

    def test_min_count_is_checked_across_prior_tasks(self):
        """A count applies to the complete input group, not each multiplexed task."""
        result = self._run_import(
            [{"kind": "min_count", "value": 2}],
            [self._task(0), self._task(1)],
        )

        assert result.image_rows is not None
        assert [row["path"] for row in result.image_rows] == [
            "output_0.fits",
            "output_1.fits",
        ]

    def test_min_count_still_rejects_an_input_group_when_insufficient(self):
        """A named input group still fails when its own aggregate is too small."""
        from starbash.exception import NotEnoughFilesError

        with pytest.raises(NotEnoughFilesError):
            self._run_import(
                [{"kind": "min_count", "value": 2}],
                [self._task(0)],
            )

    def test_optional_input_group_can_be_empty(self):
        """An optional group returns an empty FileInfo when nothing matches."""
        result = self._run_import(
            [{"kind": "metadata", "name": "filter", "value": ["SiiOiii"]}],
            [self._task(0)],
            optional=True,
        )

        assert result.image_rows == []


class TestPaletteRecipes:
    """Tests that palette recipes declare independent channel inputs."""

    @staticmethod
    def _load(name: str) -> Any:
        import tomlkit

        path = Path(__file__).parents[2] / "starbash-recipes" / "palette" / name
        return tomlkit.parse(path.read_text())

    def test_sho_requires_ha_oiii_and_has_optional_sii(self):
        stage = self._load("sho.toml")["stages"][0]
        inputs = {item["name"]: item for item in stage["inputs"]}

        assert inputs["ha"]["requires"][-1]["value"] == 1
        assert inputs["oiii"]["requires"][-1]["value"] == 1
        assert inputs["sii"]["optional"] is True
        assert inputs["sii"]["requires"][0]["value"] == ["SiiOiii"]

    def test_hoo_requires_separate_ha_and_oiii_inputs(self):
        stage = self._load("hoo.toml")["stages"][0]
        inputs = {item["name"]: item for item in stage["inputs"]}

        assert set(inputs) == {"ha", "oiii"}
        assert [r["value"] for r in inputs["ha"]["requires"] if r["kind"] == "min_count"] == [1]
        assert [r["value"] for r in inputs["oiii"]["requires"] if r["kind"] == "min_count"] == [1]


def remove_tasks_by_stage_name(tasks: list[dict], excluded: list[str]) -> list[dict]:
    """Helper function to remove tasks by stage name (for testing)."""
    return [t for t in tasks if t["meta"]["stage"]["name"] not in excluded]


class TestMakeImagerow:
    """Tests for _make_imagerow function."""

    def test_make_imagerow_basic(self):
        """Test creating a basic imagerow."""
        dir_path = Path("/test/directory")
        filename = "image.fits"

        result = make_imagerow(dir_path, filename)

        assert "abspath" in result
        assert "path" in result
        assert result["abspath"] == str(dir_path / filename)
        assert result["path"] == filename

    def test_make_imagerow_with_subdirectory(self):
        """Test creating imagerow with nested path."""
        dir_path = Path("/test/directory")
        filename = "subdir/nested/image.fits"

        result = make_imagerow(dir_path, filename)

        assert result["abspath"] == str(dir_path / filename)
        assert result["path"] == filename


class TestStageToDoc:
    """Tests for _stage_to_doc function."""

    def test_stage_to_doc_with_description(self):
        """Test setting doc from stage description."""
        task = {}
        stage = {"description": "Process bias frames"}

        stage_to_doc(task, stage)

        assert task["doc"] == "Process bias frames"

    def test_stage_to_doc_without_description(self):
        """Test default doc when stage has no description."""
        task = {}
        stage = {}

        stage_to_doc(task, stage)

        assert task["doc"] == "No description provided"

    def test_stage_to_doc_overwrites_existing(self):
        """Test that stage_to_doc overwrites existing doc."""
        task = {"doc": "Old doc"}
        stage = {"description": "New description"}

        stage_to_doc(task, stage)

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

        session_inputs = inputs_by_kind(stage, "session")

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

        results = inputs_by_kind(stage, "master")

        assert len(results) == 0
        assert results == []

    def test_inputs_by_kind_no_inputs(self):
        """Test when stage has no inputs."""
        stage = {}

        results = inputs_by_kind(stage, "session")

        assert len(results) == 0

    def test_inputs_by_kind_empty_inputs(self):
        """Test empty result when stage has empty inputs list."""
        stage = {"inputs": []}

        results = inputs_by_kind(stage, "session")

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
            "Dependency must be satisfied before dependent stage, regardless of priority"
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
            "This is the key bug: veralux depends on background.*, so background must come first"
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

        sessions = inputs_by_kind(stage, "session")
        masters = inputs_by_kind(stage, "master")
        files = inputs_by_kind(stage, "file")

        assert len(sessions) == 3
        assert len(masters) == 1
        assert len(files) == 1


class TestRemoveMissingToolTasks:
    """Tests for Processing._remove_missing_tool_tasks."""

    @staticmethod
    def _make_task(name: str, tool_name: str) -> dict:
        return {"name": name, "meta": {"stage": {"name": name, "tool": {"name": tool_name}}}}

    def _run_filter(self, tasks: list[dict]) -> list[dict]:
        from starbash.processing import Processing

        # Bypass __init__; the method only relies on module-level `tools`.
        proc = Processing.__new__(Processing)
        return proc._remove_missing_tool_tasks(tasks)

    def test_keeps_available_tool_tasks(self, monkeypatch):
        """Tasks whose tool is available are retained."""

        class FakeTool:
            is_available = True

        monkeypatch.setattr("starbash.processing.tools", {"siril": FakeTool()})

        tasks = [self._make_task("stack", "siril")]
        result = self._run_filter(tasks)

        assert len(result) == 1

    def test_drops_missing_tool_tasks(self, monkeypatch, caplog):
        """Tasks whose tool is unavailable are removed and warned about."""

        class AvailTool:
            is_available = True

        class MissingTool:
            is_available = False

        monkeypatch.setattr(
            "starbash.processing.tools",
            {"siril": AvailTool(), "rc-astro": MissingTool()},
        )

        tasks = [
            self._make_task("stack", "siril"),
            self._make_task("blur_exterminator", "rc-astro"),
        ]

        import logging

        with caplog.at_level(logging.WARNING):
            result = self._run_filter(tasks)

        assert [t["name"] for t in result] == ["stack"]
        assert "blur_exterminator" in caplog.text
        assert "rc-astro" in caplog.text

    def test_unknown_tool_is_dropped(self, monkeypatch):
        """A stage referencing a tool not in the registry is removed."""
        monkeypatch.setattr("starbash.processing.tools", {})

        tasks = [self._make_task("mystery", "nonexistent")]
        result = self._run_filter(tasks)

        assert result == []

    def test_warns_once_per_stage(self, monkeypatch, caplog):
        """Multiplexed tasks sharing a stage only emit a single warning."""

        class MissingTool:
            is_available = False

        monkeypatch.setattr("starbash.processing.tools", {"rc-astro": MissingTool()})

        tasks = [
            self._make_task("blur_exterminator", "rc-astro"),
            self._make_task("blur_exterminator", "rc-astro"),
        ]

        import logging

        with caplog.at_level(logging.WARNING):
            result = self._run_filter(tasks)

        assert result == []
        warnings = [r for r in caplog.records if "blur_exterminator" in r.message]
        assert len(warnings) == 1


class TestMastersNeededBy:
    """Tests for the masters_needed_by() dependency closure."""

    def test_direct_dependency_is_needed(self, tmp_path):
        """A master consumed directly by a target lands in the needed set."""
        from starbash.processing import masters_needed_by

        flat = tmp_path / "flat_master.fit"
        needed = masters_needed_by(
            [{"file_dep": [str(flat)], "targets": [str(tmp_path / "light.fit")]}],
            [{"targets": [str(flat)], "file_dep": [str(tmp_path / "raw_flat.fit")]}],
        )
        assert str(flat) in needed

    def test_transitive_dependency_is_needed(self, tmp_path):
        """A master that a *needed* master consumes is also needed."""
        from starbash.processing import masters_needed_by

        flat = tmp_path / "flat_master.fit"
        bias = tmp_path / "bias_master.fit"
        dark = tmp_path / "dark_master.fit"
        needed = masters_needed_by(
            [{"file_dep": [str(flat)], "targets": [str(tmp_path / "light.fit")]}],
            [
                {"targets": [str(flat)], "file_dep": [str(bias)]},
                {"targets": [str(bias)], "file_dep": [str(tmp_path / "raw_bias.fit")]},
                {"targets": [str(dark)], "file_dep": [str(tmp_path / "raw_dark.fit")]},
            ],
        )
        assert str(bias) in needed
        assert str(flat) in needed
        assert str(dark) not in needed

    def test_unrelated_master_is_not_needed(self, tmp_path):
        """A master nothing depends on is absent from the needed set."""
        from starbash.processing import masters_needed_by

        needed = masters_needed_by(
            [{"file_dep": [str(tmp_path / "used.fit")], "targets": []}],
            [{"targets": [str(tmp_path / "unused.fit")], "file_dep": []}],
        )
        assert str(tmp_path / "unused.fit") not in needed


class TestRunAllTasksPrune:
    """Tests for the optional cleanup in _run_all_tasks()."""

    @staticmethod
    def _make_processing() -> Any:
        from starbash.processing import Processing

        proc: Any = Processing.__new__(Processing)

        class FakeDoit:
            def __init__(self) -> None:
                self.tasks: list[dict] = []

            def set_tasks(self, tasks: list[dict]) -> None:
                self.tasks = tasks

        proc.doit = FakeDoit()
        proc.results = []
        proc._run_jobs = lambda: None
        return proc

    def test_prune_defaults_to_true(self, monkeypatch):
        """Without an argument, finishing a batch still prunes old contexts."""
        calls: list[int] = []
        monkeypatch.setattr("starbash.processing.cleanup_old_contexts", lambda: calls.append(1))

        proc = self._make_processing()
        proc._run_all_tasks([])

        assert calls == [1]

    def test_prune_false_skips_cleanup(self, monkeypatch):
        """prune=False lets a caller that created all dirs up front defer pruning."""
        calls: list[int] = []
        monkeypatch.setattr("starbash.processing.cleanup_old_contexts", lambda: calls.append(1))

        proc = self._make_processing()
        proc._run_all_tasks([], prune=False)

        assert calls == []


class TestPublishMasterCull:
    """Tests for Processing._publish_master_cull()."""

    @staticmethod
    def _master_result(label: str, targets: list[str], file_dep: list[str]) -> Any:
        from types import SimpleNamespace

        class FakePt:
            def run_label(self, context: dict | None = None) -> str:
                return label

        task = SimpleNamespace(
            file_dep=file_dep,
            targets=targets,
            meta={"processed_target": FakePt(), "context": {}},
        )
        return SimpleNamespace(task=task)

    def test_unneeded_master_is_dropped(self, tmp_path, monkeypatch):
        """A master no target depends on appears in the published drop list."""
        from starbash import events
        from starbash.processing import Processing

        published: list[tuple[str, dict | None]] = []
        monkeypatch.setattr(
            events, "publish", lambda kind, data=None: published.append((kind, data))
        )

        used = tmp_path / "used_master.fit"
        unused = tmp_path / "unused_master.fit"
        results = [
            self._master_result("Master used", [str(used)], [str(tmp_path / "r1.fit")]),
            self._master_result("Master unused", [str(unused)], [str(tmp_path / "r2.fit")]),
        ]
        target_tasks = [{"file_dep": [str(used)], "targets": []}]

        proc = Processing.__new__(Processing)
        drop = proc._publish_master_cull(results, target_tasks)

        assert drop == ["Master unused"]
        assert published[-1][0] == events.EVENT_PREFLIGHT_FINISHED
        assert published[-1][1] == {"drop": ["Master unused"]}

    def test_all_needed_publishes_nothing(self, tmp_path, monkeypatch):
        """When every master is needed, no event is published."""
        from starbash import events
        from starbash.processing import Processing

        published: list[tuple[str, dict | None]] = []
        monkeypatch.setattr(
            events, "publish", lambda kind, data=None: published.append((kind, data))
        )

        used = tmp_path / "used_master.fit"
        results = [self._master_result("Master used", [str(used)], [str(tmp_path / "r1.fit")])]

        proc = Processing.__new__(Processing)
        drop = proc._publish_master_cull(results, [{"file_dep": [str(used)], "targets": []}])

        assert drop == []
        assert published == []

    def test_no_targets_drops_nothing(self, tmp_path, monkeypatch):
        """With no targets selected, every master survives (nothing pulls them in)."""
        from starbash import events
        from starbash.processing import Processing

        published: list[tuple[str, dict | None]] = []
        monkeypatch.setattr(
            events, "publish", lambda kind, data=None: published.append((kind, data))
        )

        results = [
            self._master_result("Master a", [str(tmp_path / "a.fit")], []),
            self._master_result("Master b", [str(tmp_path / "b.fit")], []),
        ]

        proc = Processing.__new__(Processing)
        drop = proc._publish_master_cull(results, [])

        assert drop == []
        assert published == []

    def test_single_master_run_drops_nothing(self, tmp_path, monkeypatch):
        """A single master run is never culled (there is no choice to make)."""
        from starbash import events
        from starbash.processing import Processing

        published: list[tuple[str, dict | None]] = []
        monkeypatch.setattr(
            events, "publish", lambda kind, data=None: published.append((kind, data))
        )

        results = [self._master_result("Master only", [str(tmp_path / "only.fit")], [])]

        proc = Processing.__new__(Processing)
        drop = proc._publish_master_cull(results, [{"file_dep": [], "targets": []}])

        assert drop == []
        assert published == []


class TestRunAllStagesPreflight:
    """The auto pipeline builds every target before running any of them."""

    @staticmethod
    def _fake_processing(targets: list[str]):
        from starbash.processing import Processing

        proc: Any = Processing.__new__(Processing)

        class FakeSb:
            def search_session(self, *args, **kwargs):
                return [{"object": t} for t in targets]

        class FakeProgress:
            def __init__(self) -> None:
                self.events: list[str] = []

            def add_task(self, *args, **kwargs) -> int:
                return 0

            def update(self, *args, **kwargs) -> None:
                pass

            def track(self, iterable, *args, **kwargs):
                return iterable

            def remove_task(self, *args, **kwargs) -> None:
                pass

        class FakePt:
            def __init__(self, name: str) -> None:
                self.name = name

        proc.sb = FakeSb()
        proc.progress = FakeProgress()
        proc.processed_target = None
        return proc, FakePt

    def test_all_targets_built_before_any_run(self, monkeypatch):
        """Planning for every target completes before the first target runs."""
        import starbash
        from starbash import processing as processing_mod

        monkeypatch.setattr(starbash, "process_masters", False, raising=False)
        proc, FakePt = self._fake_processing(["M42", "M31"])

        sequence: list[tuple[str, str]] = []
        prune_flags: list[bool] = []
        prune_calls: list[int] = []

        def fake_create(sessions, targets):
            target = targets[0]
            sequence.append(("create", target))
            return [{"meta": {"processed_target": FakePt(target)}}]

        def fake_run(tasks, prune: bool = True):
            target = tasks[0]["meta"]["processed_target"].name
            sequence.append(("run", target))
            prune_flags.append(prune)
            return []

        proc._create_tasks = fake_create
        proc._run_all_tasks = fake_run
        proc._finish_runs = lambda results: None
        proc._publish_master_cull = lambda results, tasks: []
        monkeypatch.setattr(processing_mod, "cleanup_old_contexts", lambda: prune_calls.append(1))

        proc.run_all_stages()

        # Every "create" happens before every "run": planning is its own phase.
        last_create = max(i for i, (kind, _) in enumerate(sequence) if kind == "create")
        first_run = min(i for i, (kind, _) in enumerate(sequence) if kind == "run")
        assert last_create < first_run
        # Targets are processed in stable selection order (deduped)...
        assert [t for kind, t in sequence if kind == "create"] == ["m42", "m31"]
        assert [t for kind, t in sequence if kind == "run"] == ["m42", "m31"]
        # Mid-run pruning is disabled: preflight created every target's processing
        # dir up front, so pruning here could delete a not-yet-run target's cache.
        assert prune_flags == [False, False]
        # The cache bound is applied exactly once, after the whole run.
        assert prune_calls == [1]
        assert proc.processed_target is None

    def test_target_processing_dir_is_kept_after_run(self, monkeypatch):
        """A target's processing dir is a reuse cache and must survive its run.

        Regression: the run loop used to call
        ``ProcessedTarget.remove_processing_dir()`` after each target, deleting the
        ``~/.cache/starbash/processing/<target>`` tree and making the next run redo
        every stage from scratch.
        """
        import starbash
        from starbash import processing as processing_mod

        monkeypatch.setattr(starbash, "process_masters", False, raising=False)
        proc, FakePt = self._fake_processing(["M42"])

        removed: list[str] = []

        def fake_create(sessions, targets):
            pt = FakePt(targets[0])
            pt.remove_processing_dir = lambda: removed.append(pt.name)
            return [{"meta": {"processed_target": pt}}]

        proc._create_tasks = fake_create
        proc._run_all_tasks = lambda tasks, prune=True: []
        proc._finish_runs = lambda results: None
        proc._publish_master_cull = lambda results, tasks: []
        monkeypatch.setattr(processing_mod, "cleanup_old_contexts", lambda: None)

        proc.run_all_stages()

        assert removed == []

    def test_master_cull_sees_every_targets_tasks(self, monkeypatch):
        """The cull is computed from all targets' tasks, not just the first."""
        import starbash
        from starbash import processing as processing_mod

        monkeypatch.setattr(starbash, "process_masters", False, raising=False)
        proc, FakePt = self._fake_processing(["M42", "M31"])

        def fake_create(sessions, targets):
            return [{"meta": {"processed_target": FakePt(targets[0]), "tag": targets[0]}}]

        seen: list[list[str]] = []
        proc._create_tasks = fake_create
        proc._run_all_tasks = lambda tasks, prune=True: []
        proc._finish_runs = lambda results: None
        proc._publish_master_cull = lambda results, tasks: seen.append(
            [t["meta"]["tag"] for t in tasks]
        )
        monkeypatch.setattr(processing_mod, "cleanup_old_contexts", lambda: None)

        proc.run_all_stages()

        assert len(seen) == 1
        assert set(seen[0]) == {"m42", "m31"}
