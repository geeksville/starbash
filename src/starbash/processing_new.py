"""New processing implementation for starbash (under development)."""

from pathlib import Path
from typing import Any

from starbash.app import Starbash
from starbash.doit import StarbashDoit
from starbash.processing import Processing, ProcessingResult

# some type aliases for clarity

type TaskDict = dict[str, Any]  # a doit task dictionary
type StageDict = dict[str, Any]  # a processing stage definition from our toml
type InputDef = dict[str, Any]  # an input definition within a stage


def _stage_to_action(task: TaskDict, stage: StageDict) -> None:
    """Given a stage definition, populate the "actions" list of the task dictionary.

    Creates instances of ToolAction for the specified tool and commands.
    """
    pass  # not yet implemented


def _stage_to_doc(task: TaskDict, stage: StageDict) -> None:
    """Given a stage definition, populate the "doc" string of the task dictionary."""
    task["doc"] = stage.get("description", "No description provided")


def _inputs_by_kind(stage: StageDict, kind: str) -> list[InputDef]:
    """Returns all imputs of a particular kind from the given stage definition."""
    inputs: list[InputDef] = stage.get("inputs", [])
    return [inp for inp in inputs if inp.get("kind") == kind]


class ProcessingNew(Processing):
    """New processing implementation (work in progress).

    This is a placeholder for the refactored processing architecture.
    """

    def __init__(self, sb: Starbash) -> None:
        super().__init__(sb)
        self.doit: StarbashDoit = StarbashDoit()

    def __enter__(self) -> "ProcessingNew":
        return self

    def process_target(self, target: str) -> ProcessingResult:
        """Do processing for a particular target (i.e. all sessions for a particular object)."""
        raise NotImplementedError("ProcessingNew.process_target() is not yet implemented")

    def _get_stages(self, name: str = "stages2") -> list[StageDict]:
        """Get all pipeline stages defined in the merged configuration."""
        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).
        s = self.sb.repo_manager.merged.getall(name)
        return s

    def _session_to_filepaths(self, input_def: InputDef) -> list[Path]:
        """find actual filepaths that we can provide as inputs.  This resolution
        # will also check things like input.requires.camera/metadata etc... and filter responses based on that"""
        pass

    def _stage_to_tasks(self, stage: StageDict) -> None:
        """Convert the given stage to doit task(s) and add them to our doit task list."""

        # Find what kinds of inputs the stage is REQUESTING
        masters_in = _inputs_by_kind(stage, "master")

        session_in = _inputs_by_kind(stage, "session")
        assert len(session_in) <= 1, "A maximum of one 'session' input is supported per stage"

        # Based on those requests, find actual filepaths that we can provide as inputs.  This resolution
        # will also check things like input.requires.camera/metadata etc... and filter responses based on that

        # if we have any session inputs assume that this stage is multiplexed.  We will output one task per session
        need_multplex = len(session_in) > 0

        # Convert each stage to a doit task dictionary
        task_dict = {
            "name": stage.get(
                "name", "unnamed_stage"
            ),  # FIXME, needs to be unique, even when multiplexed
            "file_dep": stage.get(
                "inputs", []
            ),  # FIXME, build from inputs per example starbash-recipes/osc_dual_duo2/starbash.toml
            "targets": stage.get(
                "outputs", []
            ),  # FIXME, build from outputs per example starbash-recipes/osc_dual_duo2/starbash.toml
        }
        _stage_to_action(task_dict, stage)  # add the actions
        _stage_to_doc(task_dict, stage)  # add the doc string
        self.doit.add_task(task_dict)

    def _stages_to_tasks(self, stages: list[dict[str, Any]]) -> None:
        """Convert the given stages to doit tasks and add them to our doit task list."""
        for stage in stages:
            self._stage_to_tasks(stage)

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.

        Raises:
            NotImplementedError: This method is not yet implemented.
        """
        raise NotImplementedError("ProcessingNew.run_master_stages() is not yet implemented")
