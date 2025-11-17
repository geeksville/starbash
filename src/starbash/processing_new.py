"""New processing implementation for starbash (under development)."""

import logging
import textwrap
from pathlib import Path
from typing import Any

from starbash.app import Starbash
from starbash.database import SessionRow
from starbash.doit import StarbashDoit
from starbash.processing import Processing, ProcessingResult
from starbash.tool import tools

# some type aliases for clarity

type TaskDict = dict[str, Any]  # a doit task dictionary
type StageDict = dict[str, Any]  # a processing stage definition from our toml
type InputDef = dict[str, Any]  # an input definition within a stage


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
        """Find actual filepaths that we can provide as inputs.

        This resolution will also check things like input.requires.camera/metadata
        etc... and filter responses based on that.

        Args:
            input_def: Input definition from the stage TOML

        Returns:
            List of Path objects for the matched input files
        """
        # FIXME: Implement session-to-filepath resolution
        # - Query database for session images based on input_def
        # - Apply filters from input_def.requires (metadata, min_count, camera)
        # - Return list of Path objects
        return []

    def _stage_to_action(self, task: TaskDict, stage: StageDict) -> None:
        """Given a stage definition, populate the "actions" list of the task dictionary.

        Creates instances of ToolAction for the specified tool and commands.

        Args:
            task: The doit task dictionary to populate
            stage: The stage definition from TOML containing tool and script info
        """
        from starbash.doit import ToolAction

        tool_dict = stage.get("tool")
        if not tool_dict:
            raise ValueError(f"Stage '{stage.get('name')}' is missing a 'tool' definition.")
        tool_name = tool_dict.get("name")
        if not tool_name:
            raise ValueError(f"Stage '{stage.get('name')}' is missing a 'tool.name' definition.")
        tool = tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' for stage '{stage.get('name')}' not found.")
        logging.debug(f"Using tool: {tool_name}")
        tool.set_defaults()

        # Allow stage to override tool timeout if specified
        tool_timeout = tool_dict.get("timeout")
        if tool_timeout is not None:
            tool.timeout = float(tool_timeout)
            logging.debug(f"Using tool timeout: {tool.timeout} seconds")

        # is the script included inline?
        script: str | None = stage.get("script")
        if script:
            script = textwrap.dedent(script)  # it might be indented in the toml
        else:
            # try to load it from a file
            script_filename = stage.get("script-file", tool.default_script_file)
            if script_filename:
                source = stage.source  # type: ignore (was monkeypatched by repo)
                try:
                    script = source.read(script_filename)
                except OSError as e:
                    raise ValueError(f"Error reading script file '{script_filename}'") from e

        if script is None:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'script' or 'script-file' definition."
            )

        # FIXME: Need to determine the working directory (cwd)
        # - For session stages: typically process_dir
        # - For final stages: typically results_dir or process_dir
        cwd = None

        # Create the ToolAction and add to task
        action = ToolAction(tool, commands=script, context=self.context, cwd=cwd)
        task["actions"] = [action]

    def _stage_to_tasks(self, stage: StageDict) -> None:
        """Convert the given stage to doit task(s) and add them to our doit task list.

        This method handles both single and multiplexed (per-session) stages.
        For multiplexed stages, creates one task per session with unique names.
        """

        # Find what kinds of inputs the stage is REQUESTING
        # masters_in = _inputs_by_kind(stage, "master")  # TODO: Use for input resolution
        session_in = _inputs_by_kind(stage, "session")
        # job_in = _inputs_by_kind(stage, "job")  # TODO: Use for input resolution

        assert len(session_in) <= 1, "A maximum of one 'session' input is supported per stage"

        # If we have any session inputs, this stage is multiplexed (one task per session)
        need_multiplex = len(session_in) > 0

        if need_multiplex:
            # Create one task per session
            for session in self.sessions:
                task_dict = self._create_task_dict(stage, session)
                self.doit.add_task(task_dict)
        else:
            # Single task (no multiplexing) - e.g., final stacking or post-processing
            task_dict = self._create_task_dict(stage)
            self.doit.add_task(task_dict)

    def _create_task_dict(self, stage: StageDict, session: SessionRow | None = None) -> TaskDict:
        """Create a doit task dictionary for a single session in a multiplexed stage.

        Args:
            stage: The stage definition from TOML
            session: The session row from the database

        Returns:
            Task dictionary suitable for doit
        """
        task_name = stage.get("name", "unnamed_stage")

        # FIXME - might need to further uniquify the task name
        if session:
            session_id = session["id"]

            # Make unique task name by combining stage name and session ID
            task_name += f"_s{session_id}"

        file_deps = self._resolve_input_files(stage, session)
        targets = self._resolve_output_files(stage, session)

        task_dict: TaskDict = {
            "name": task_name,
            "file_dep": file_deps,
            "targets": targets,
        }

        self._stage_to_action(task_dict, stage)  # add the actions
        _stage_to_doc(task_dict, stage)  # add the doc string

        return task_dict

    def _resolve_input_files(self, stage: StageDict, session: SessionRow | None) -> list[Path]:
        """Resolve input file paths for a stage.

        Args:
            stage: The stage definition from TOML
            session: Session row if this is a multiplexed stage, None otherwise

        Returns:
            List of absolute file paths that are inputs to this stage
        """
        # FIXME: Implement input file resolution
        # - Extract inputs from stage["inputs"]
        # - For each input, based on its "kind":
        #   - "session": get session light frames from database
        #   - "master": look up master frame path (bias/dark/flat)
        #   - "job": construct path from previous stage outputs
        # - Apply input.requires filters (metadata, min_count, camera)
        # - Return list of actual file paths
        return []

    def _resolve_output_files(self, stage: StageDict, session: SessionRow | None) -> list[Path]:
        """Resolve output file paths for a stage.

        Args:
            stage: The stage definition from TOML
            session: Session row if this is a multiplexed stage, None otherwise

        Returns:
            List of absolute file paths that are outputs/targets of this stage
        """
        # FIXME: Implement output file resolution
        # - Extract outputs from stage["outputs"]
        # - For each output, based on its "kind":
        #   - "job": construct path in shared processing temp dir
        #   - "processed": construct path in target-specific results dir
        # - Expand context variables in output names (e.g., {light_base})
        # - Handle both single names and lists of names
        # - Return list of actual file paths
        return []

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
