"""New processing implementation for starbash (under development)."""

import logging
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tomlkit.items import AoT

from repo import Repo
from starbash import InputDef, OutputDef, StageDict, TaskDict
from starbash.app import Starbash
from starbash.doit import StarbashDoit
from starbash.filtering import filter_by_requires
from starbash.processing import (
    Processing,
    ProcessingResult,
    update_processing_result,
)
from starbash.safety import get_list_of_strings, get_safe
from starbash.score import score_candidates
from starbash.tool import expand_context_list, expand_context_unsafe, tools


@dataclass
class FileInfo:
    """Dataclass to hold output context information.
    To make for easier syntactic sugar when expanding context variables."""

    base: str | None = None  # The directory name component of the path
    full: Path | None = (
        None  # The full filepath without spaces - because Siril doesn't like that, might contain wildcards
    )
    relative: str | None = None  # the relative path within the repository
    repo: Repo | None = None  # The repo this file is within
    files: list[Path] | None = None  # List of individual files (if applicable)


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

    @property
    def session(self) -> dict[str, Any]:
        """Get the current session from the context."""
        return self.context["session"]

    @property
    def job_dir(self) -> Path:
        """Get the current job directory (for working/temp files) from the context."""
        d = self.context["process_dir"]  # FIXME change this to be named "job".base
        return Path(d)

    @property
    def output_dir(self) -> Path:
        """Get the current output directory (for working/temp files) from the context."""
        d = self.context["output"].base
        return Path(d)

    def __init__(self, sb: Starbash) -> None:
        super().__init__(sb)
        self.doit: StarbashDoit = StarbashDoit()

    def __enter__(self) -> "ProcessingNew":
        return self

    def _process_target(self, target: str) -> ProcessingResult:
        """Do processing for a particular target (i.e. all selected sessions for a particular object)."""

        result = ProcessingResult(target=target, sessions=self.sessions)

        try:
            stages = self._get_stages()
            self._stages_to_tasks(stages)
            # fire up doit to run the tasks
            # FIXME, perhaps we could run doit one level higher, so that all targets are processed by doit
            # for parallism etc...?
            self.doit.run(["list"])
            # self.doit.run(["dumpdb"])
            logging.info("Running doit tasks...")
            self.doit.run(["strace", "stack_s36"])  # light_s35

            # have doit tasks store into a ProcessingResults object somehow

        except Exception as e:
            task_exception = e
            update_processing_result(result, task_exception)

        return result

    def _get_stages(self, name: str = "stages2") -> list[StageDict]:
        """Get all pipeline stages defined in the merged configuration."""
        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).

        # FIXME this is kinda yucky.  The 'merged' repo_manage doesn't know how to merge AoT types, so we get back a list of AoT
        # we need to flatten that out into one list of normal dicts
        stages: list[AoT] = self.sb.repo_manager.merged.getall(name)
        s_unwrapped: list[StageDict] = []
        for stage in stages:
            s_unwrapped.extend(stage.unwrap())
        return s_unwrapped

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

    def _clone_context(self) -> dict[str, Any]:
        """Create a shallow copy of the current processing context.

        Returns:
            A shallow copy of the current context dictionary.
        """
        return self.context.copy()

    def _stage_to_action(self, task: TaskDict, stage: StageDict) -> None:
        """Given a stage definition, populate the "actions" list of the task dictionary.

        Creates instances of ToolAction for the specified tool and commands.

        Args:
            task: The doit task dictionary to populate
            stage: The stage definition from TOML containing tool and script info
        """
        from starbash.doit import ToolAction

        tool_dict = get_safe(stage, "tool")
        tool_name = get_safe(tool_dict, "name")
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
        action = ToolAction(tool, commands=script, context=self._clone_context(), cwd=cwd)
        task["actions"] = [action]

    def _add_stage_context_defs(self, stage: StageDict) -> None:
        """Add any context definitions specified in the stage to our processing context.

        Args:
            stage: The stage definition from TOML
        """
        context_defs: dict[str, Any] = stage.get("context", {})
        for key, value in context_defs.items():
            self.context[key] = value

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

        self._add_stage_context_defs(stage)

        # If we have any session inputs, this stage is multiplexed (one task per session)
        need_multiplex = len(session_in) > 0
        if need_multiplex:
            has_set_output = False

            # Create one task per session
            for s in self.sessions:
                # Note we have a single context instance and we set session inside it
                # later when we go to actually RUN the tasks we need to make sure each task is using a clone
                # from _clone_context().  So that task will be seeing the correct context data we are building here.

                self._set_session_in_context(s)

                # Note: we can't set the output directory until we know at least one session (so we can find 'target' name)
                # so we do it here.
                if not has_set_output:
                    self._set_output_by_kind("processed")
                    # FIXME this is the earliest place we can create/read the output toml file
                    has_set_output = True

                task_dict = self._create_task_dict(stage)
                self.doit.add_task(task_dict)
        else:
            # no session for non-multiplexed stages, FIXME, not sure if there is a better place to clean this up?
            self.context.pop("session", None)

            # Single task (no multiplexing) - e.g., final stacking or post-processing
            task_dict = self._create_task_dict(stage)
            self.doit.add_task(task_dict)

    def _create_task_dict(self, stage: StageDict) -> TaskDict:
        """Create a doit task dictionary for a single session in a multiplexed stage.

        Args:
            stage: The stage definition from TOML
            session: The session row from the database

        Returns:
            Task dictionary suitable for doit
        """
        task_name = stage.get("name", "unnamed_stage")

        # FIXME - might need to further uniquify the task name
        # NOTE: we intentially don't use self.session because session might be None here and thats okay
        session = self.context.get("session")
        if session:
            session_id = session["id"]

            # Make unique task name by combining stage name and session ID
            task_name += f"_s{session_id}"

        # since 'inputs' are session specific we erase them here, so that _create_task_dict can reinit with
        # the correct session specific files
        self.context.pop("input", None)
        self.context.pop(
            "input_files", None
        )  # also nuke our temporary old-school way of finding input files

        file_deps = self._stage_input_files(stage)
        targets = self._stage_output_files(stage)

        task_dict: TaskDict = {
            "name": task_name,
            "file_dep": expand_context_list(file_deps, self.context),
            # FIXME, we should probably be using something more structured than bare filenames - so we can pass base source and confidence scores
            "targets": expand_context_list(targets, self.context),
        }

        # add the actions THIS will store a SNAPSHOT of the context AT THIS TIME for use if the task/action is later executed
        self._stage_to_action(task_dict, stage)
        _stage_to_doc(task_dict, stage)  # add the doc string

        return task_dict

    def _resolve_files(self, input: InputDef, dir: Path) -> list[Path]:
        """combine the directory with the input/output name(s) to get paths.

        We can share this function because input/output sections have the same rules for jobs"""
        filenames = get_list_of_strings(input, "name")
        return [dir / filename for filename in filenames]

    def _resolve_input_files(self, input: InputDef) -> list[Path]:
        """Resolve input file paths for a stage.

        Args:
            stage: The stage definition from TOML

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

        ci = self.context.setdefault("input", {})

        def _resolve_input_job() -> list[Path]:
            return self._resolve_files(input, self.job_dir)

        def _resolve_input_session() -> list[Path]:
            images = self.sb.get_session_images(self.session)

            filter_by_requires(input, images)

            logging.debug(f"Using {len(images)} files as input_files")

            filepaths = [img["abspath"] for img in images]
            # FIMXEMove elsewhere.
            # we also need to add ["input"][type] to the context so that scripts can find .base etc... o
            imagetyp = get_safe(input, "type")
            ci[imagetyp] = FileInfo(files=filepaths, base=f"{imagetyp}_s{self.session['id']}")

            # FIXME, we temporarily (until the processing_classic is removed) use the old style input_files
            # context variable - so that existing scripts can keep working.
            self.context["input_files"] = filepaths

            return filepaths

        def _resolve_input_master() -> list[Path]:
            imagetyp = get_safe(input, "type")
            masters = self.sb.get_master_images(imagetyp=imagetyp, reference_session=self.session)
            if not masters:
                logging.warning(f"No master frames of type '{imagetyp}' found for stage")
                return []

            # Try to rank the images by desirability
            scored_masters = score_candidates(masters, self.session)

            # FIXME - do reporting and use the user selected master if specified
            # FIXME make a special doit task that just provides a very large set of possible masters - so that doit can do the resolution
            # /selection of inputs?  The INPUT for a master kind would just make its choice based on the toml user preferences (or pick the first
            # if no other specified).  Perhaps no need for a special master task, just use the regular depdency mechanism and port over the
            # master scripts as well!!!
            # Use the ScoredCandidate data during the cullling!  In fact, delay DOING the scoring until that step.
            #
            # session_masters = session.setdefault("masters", {})
            # session_masters[master_type] = scored_masters  # for reporting purposes

            if len(scored_masters) == 0:
                logging.warning(f"No suitable master frames of type '{imagetyp}' found.")
                return []

            self.sb._add_image_abspath(
                scored_masters[0].candidate
            )  # make sure abspath is populated, we need it

            selected_master = scored_masters[0].candidate["abspath"]
            logging.info(
                f"For master '{imagetyp}', using: {selected_master} (score={scored_masters[0].score:.1f}, {scored_masters[0].reason})"
            )

            # so scripts can find input["bias"].base etc...
            ci[imagetyp] = FileInfo(full=selected_master)

            return [selected_master]

        resolvers = {
            "job": _resolve_input_job,
            "session": _resolve_input_session,
            "master": _resolve_input_master,
        }
        kind: str = get_safe(input, "kind")
        resolver = get_safe(resolvers, kind)
        r = resolver()

        return r

    def _stage_input_files(self, stage: StageDict) -> list[Path]:
        """Get all input file paths for the given stage.

        Args:
            stage: The stage definition from TOML"""
        inputs: list[InputDef] = stage.get("inputs", [])
        all_input_files: list[Path] = []
        for inp in inputs:
            input_files = self._resolve_input_files(inp)
            all_input_files.extend(input_files)
        return all_input_files

    def _resolve_output_files(self, output: OutputDef) -> list[Path]:
        """Resolve output file paths for a stage.

        Args:
            stage: The stage definition from TOML

        Returns:
            List of absolute file paths that are outputs/targets of this stage
        """
        # FIXME: Implement output file resolution
        # - Extract outputs from stage["outputs"]
        # - For each output, based on its "kind":
        #   - "job": construct path in shared processing temp dir
        #   - "processed": construct path in target-specific results dir
        # - Return list of actual file paths

        def _resolve_output_job() -> list[Path]:
            return self._resolve_files(output, self.job_dir)

        def _resolve_processed() -> list[Path]:
            return self._resolve_files(output, self.output_dir)

        resolvers = {
            "job": _resolve_output_job,
            "processed": _resolve_processed,
        }
        kind: str = get_safe(output, "kind")
        resolver = get_safe(resolvers, kind)
        r = resolver()
        return r

    def _stage_output_files(self, stage: StageDict) -> list[Path]:
        """Get all output file paths for the given stage.

        Args:
            stage: The stage definition from TOML"""
        outputs: list[OutputDef] = stage.get("outputs", [])
        all_output_files: list[Path] = []
        for outp in outputs:
            output_files = self._resolve_output_files(outp)
            all_output_files.extend(output_files)
        return all_output_files

    def _stages_to_tasks(self, stages: list[StageDict]) -> None:
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

    def _set_output_by_kind(self, kind: str) -> None:
        """Set output paths in the context based on their kind.

        Args:
            kind: The kind of output ("job", "processed", etc.)
            paths: List of Path objects for the outputs
        """
        # Find the repo with matching kind
        dest_repo = self.sb.repo_manager.get_repo_by_kind(kind)
        if not dest_repo:
            raise ValueError(f"No repository found with kind '{kind}' for output destination")

        repo_base = dest_repo.get_path()
        if not repo_base:
            raise ValueError(f"Repository '{dest_repo.url}' has no filesystem path")

        # try to find repo.relative.<imagetyp> first, fallback to repo.relative.default
        # Note: we are guaranteed imagetyp is already normalized
        imagetyp = self.context.get("imagetyp", "unspecified")
        repo_relative: str | None = dest_repo.get(
            f"repo.relative.{imagetyp}", dest_repo.get("repo.relative.default")
        )
        if not repo_relative:
            raise ValueError(
                f"Repository '{dest_repo.url}' is missing 'repo.relative.default' configuration"
            )

        # we support context variables in the relative path
        repo_relative = expand_context_unsafe(repo_relative, self.context)
        full_path = repo_base / repo_relative

        # base_path but without spaces - because Siril doesn't like that
        full_path = Path(str(full_path).replace(" ", r"_"))

        base_path = full_path.parent / full_path.stem
        if str(base_path).endswith("*"):
            # The relative path must be of the form foo/blah/*.fits or somesuch.  In that case we want the base
            # path to just point to that directory prefix.
            base_path = Path(str(base_path)[:-1])

        # create output directory if needed
        os.makedirs(base_path.parent, exist_ok=True)

        # Set context variables as documented in the TOML
        # FIXME, change this type from a dict to a dataclass?!? so foo.base works in the context expanson strings
        self.context["output"] = FileInfo(
            base=str(base_path), full=full_path, relative=repo_relative, repo=dest_repo
        )
