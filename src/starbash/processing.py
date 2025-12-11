"""Base class for processing operations in starbash."""

import copy
import logging
import os
import textwrap
from pathlib import Path
from typing import Any

from multidict import MultiDict
from rich.progress import Progress
from tomlkit.items import AoT

import starbash
from repo import Repo
from starbash import InputDef, OutputDef, StageDict
from starbash.aliases import get_aliases, normalize_target_name
from starbash.app import Starbash
from starbash.database import (
    Database,
    ImageRow,
    SessionRow,
    get_column_name,
    metadata_to_camera_id,
    metadata_to_instrument_id,
)
from starbash.doit import (
    FileInfo,
    ProcessingResult,
    StarbashDoit,
    doit_do_copy,
    doit_post_process,
)
from starbash.doit_types import TaskDict, cleanup_old_contexts
from starbash.exception import (
    NonFatalException,
    NoSuitableMastersException,
    NotEnoughFilesError,
    UserHandledError,
    raise_missing_repo,
)
from starbash.filtering import FallbackToImageException, filter_by_requires
from starbash.processed_target import (
    ProcessedTarget,
    get_from_toml,
    set_excluded,
    set_used_stages_from_tasks,
    task_to_session,
    task_to_stage,
    tasks_to_stages,
)
from starbash.processing_like import ProcessingLike
from starbash.rich import to_rich_string, to_tree
from starbash.safety import get_list_of_strings, get_safe
from starbash.score import score_candidates
from starbash.toml import toml_from_list
from starbash.tool import tools
from starbash.tool.context import expand_context_dict, expand_context_list, expand_context_unsafe

__all__ = [
    "Processing",
]


class NoPriorTaskException(NonFatalException):
    """Exception raised when a prior task specified in 'after' cannot be found."""


def _make_imagerow(dir: Path, path: str) -> ImageRow:
    """Make a stub imagerow definition with just an abspath (no metadata or other standard columns)"""
    return {"abspath": str(dir / path), "path": path}


def _stage_to_doc(task: TaskDict, stage: StageDict) -> None:
    """Given a stage definition, populate the "doc" string of the task dictionary."""
    task["doc"] = stage.get("description", "No description provided")


def _inputs_with_key(stage: StageDict, key: str) -> list[InputDef]:
    """Returns all imputs which contain a particular key."""
    inputs: list[InputDef] = stage.get("inputs", [])
    return [inp for inp in inputs if key in inp]


def _inputs_by_kind(stage: StageDict, kind: str) -> list[InputDef]:
    """Returns all imputs of a particular kind from the given stage definition."""
    inputs: list[InputDef] = stage.get("inputs", [])
    return [inp for inp in inputs if inp.get("kind") == kind]


def remove_excluded_tasks(tasks: list[TaskDict]) -> list[TaskDict]:
    """Look in our session['stages'] dict to see if this task is allowed to be processed"""

    def task_allowed(task: TaskDict) -> bool:
        stage = task_to_stage(task)
        session = task_to_session(task)
        if not session:
            pt: ProcessedTarget = task["meta"]["processed_target"]
            assert pt, "ProcessedTarget must be set in Processing for sessionless tasks"
            session = pt.default_stages

        excluded_stages = get_from_toml(session, "excluded")
        return stage.get("name") not in excluded_stages

    return [t for t in tasks if task_allowed(t)]


def create_default_task(tasks: list[TaskDict]) -> TaskDict:
    """Create a default task that depends on all given tasks.

    This task can be used to represent the overall processing of a target.

    Args:
        tasks: List of TaskDict objects to depend on.

    Returns:
        A TaskDict representing the default task.
    """
    default_task_name = "process_all"
    task_deps = []
    for task in tasks:
        # We consider tasks that are writing to the final output repos
        # 'high value' and what we should run by default
        stage = task["meta"]["stage"]
        outputs = stage.get("outputs", [])
        for output in outputs:
            output_kind = get_safe(output, "kind")
            if output_kind == "master" or output_kind == "processed":
                high_value_task = task
                task_deps.append(high_value_task["name"])
                break  # no need to check other outputs for this task

    task_dict: TaskDict = {
        "name": default_task_name,
        "task_dep": task_deps,
        "actions": None,  # No actions, just depends on other tasks
        "doc": "Top level task to process all stages for all targets",
    }
    return task_dict


def _clone_context(context: dict[str, Any]) -> dict[str, Any]:
    """Create a deep copy of the current processing context.

    Returns:
        A deep copy of the current context dictionary.
    """
    r = copy.deepcopy(context)

    # A few fields (if populated) we want SHARED between all contexts, so that if two contexts were initially pointing
    # at the same session row (for insance), changes in one context are reflected in the other.
    for key in ["session"]:
        if key in context:
            r[key] = context[key]

    return r


class Processing(ProcessingLike):
    """Abstract base class for processing operations.

    Implementations must provide:
    - run_all_stages(): Process all stages for selected sessions
    - run_master_stages(): Generate master calibration frames
    """

    def __init__(self, sb: Starbash) -> None:
        self.sb: Starbash = sb
        self.context: dict[str, Any] = {}

        self.sessions: list[SessionRow] = []  # The list of sessions we are currently processing

        self.doit: StarbashDoit = StarbashDoit()

        # Normally we will use the "process_dir", but if we are importing new images from a session we place those images
        self.use_temp_cwd = False

        self.processed_target: ProcessedTarget | None = (
            None  # The target we are currently processing (with extra runtime metadata)
        )
        self.stage: StageDict | None = None  # the stage we are currently processing

        self.results: list[ProcessingResult] = []

        self.progress = Progress(console=starbash.console, refresh_per_second=2)
        self.progress.start()

    # --- Lifecycle ---
    def close(self) -> None:
        self.progress.stop()

    # Context manager support
    def __enter__(self) -> "Processing":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def init_context(self) -> None:
        """Do common session init"""

        # Context is preserved through all stages, so each stage can add new symbols to it for use by later stages
        self.context = {}

        # Update the context with runtime values.
        runtime_context = {}
        self.context.update(runtime_context)

    def add_result(self, result: ProcessingResult) -> None:
        """Add a processing result to the list of results."""
        self.results.append(result)

    def _run_all_tasks(self, tasks: list[TaskDict]) -> list[ProcessingResult]:
        self.doit.set_tasks(tasks)
        self.results.clear()
        self._run_jobs()
        cleanup_old_contexts()
        return self.results

    def _create_tasks(
        self, sessions: list[SessionRow], targets: list[str | None]
    ) -> list[TaskDict]:
        """Create all processing tasks for the indicated targets.

        Args:
            targets: List of target names (normalized) to process, or None to process
            all the master frames."""

        all_tasks: list[
            TaskDict
        ] = []  # We merge all the tasks into this list - because we regenerate sb.doit.dicts each iteration
        for target in targets:
            if target:
                # we only want sessions with light frames, because other session types (bias, dark, flat) are already
                # included in our list of masters auto dependencies
                sessions_this_target = self.sb.filter_by_imagetyp(sessions, "light")

                # select sessions for this target
                sessions_this_target = self.sb.filter_sessions_by_target(
                    sessions_this_target, target
                )

                # We are processing a single target, so build the context around that, and process
                # all sessions for that target as a group
                self.init_context()
                self.sessions = sessions_this_target
                self._job_to_tasks(target, target)
                all_tasks.extend(self.tasks)
                self.doit.set_tasks([])
            else:
                for s in sessions:
                    # For masters we process each session individually
                    self.init_context()
                    self._set_session_in_context(s)
                    # Note: We need to do this early because we need to get camera_id etc... from session

                    self.sessions = [s]
                    job_desc = f"master_{s.get('id', 'unknown')}"
                    self._job_to_tasks(job_desc, None)
                    all_tasks.extend(self.tasks)
                    self.doit.set_tasks([])

        return all_tasks

    def _get_sessions_by_imagetyp(self, imagetyp: str) -> list[SessionRow]:
        """Get all sessions that are relevant for master frame generation.

        Returns:
            List of SessionRow objects for master frame sessions.
        """
        sessions = self.sb.search_session([])  # for masters we always search everything

        # Don't return any light frame sessions

        sessions = [
            s for s in sessions if get_aliases().normalize(s.get("imagetyp", "light")) == imagetyp
        ]

        return sessions

    def _remove_duplicates(self, sessions: list[SessionRow], to_check: list[SessionRow]) -> None:
        """Remove sessions from 'sessions' that are already in 'to_check' based on session ID."""
        existing_ids = {s.get("id") for s in to_check if s.get("id") is not None}
        sessions[:] = [s for s in sessions if s.get("id") not in existing_ids]

    def run_all_stages(self) -> list[ProcessingResult]:
        """On the currently active session, run all processing stages

        * for each target in the current selection:
        *   select ONE recipe for processing that target (check recipe.auto.require.* conditions)
        *   init session context (it will be shared for all following steps) - via ProcessingContext
        *   create a temporary processing directory (for intermediate files - shared by all stages)
        *   create a processed output directory (for high value final files) - via run_stage()
        *   iterate over all light frame sessions in the current selection
        *     for each session:
        *       update context input and output files
        *       run session.light stages
        *   after all sessions are processed, run final.stack stages (using the shared context and temp dir)

        """
        sessions = self.sb.search_session()
        targets: set[str] = set()

        for s in sessions:
            target = s.get(get_column_name(Database.OBJECT_KEY))
            if target:
                target = normalize_target_name(target)
                targets.add(target)

        targets_list: list[str | None] = list(targets)

        import starbash

        results: list[ProcessingResult] = []
        auto_process_masters = starbash.process_masters
        if auto_process_masters:
            results.extend(self.run_master_stages())

        # Note: we don't process all tasks in one big doit run, because we want to be able to cleanup processing dirs
        # between targets.

        # Show two progress bars, one for each target and a second (from inside doit.py) showing the tasks
        progress_task = self.progress.add_task("Processing targets...", total=len(targets_list))
        try:
            for t in self.progress.track(targets_list, task_id=progress_task):
                self.progress.update(
                    progress_task, description=f"Processing: {t}" if t else "masters", refresh=True
                )
                tasks = self._create_tasks(sessions, [t])
                results.extend(self._run_all_tasks(tasks))
        finally:
            # we manually created this task, so we manually need to remove it
            self.progress.remove_task(progress_task)

        return results

    def _set_session_in_context(self, session: SessionRow) -> None:
        """adds to context from the indicated session:

        Sets the following context variables based on the provided session:
        * target - the normalized target name of the session
        * instrument - the telescope ID for this session
        * camera_id - the camera ID for this session (cameras might be moved between telescopes by users)
        * date - the localtimezone date of the session
        * imagetyp - the imagetyp of the session
        * session - the current session row (joined with a typical image) (can be used to
        find things like telescope, temperature ...)
        * session_config - a short human readable description of the session - suitable for logs or filenames
        """
        # it is okay to give them the actual session row, because we're never using it again
        self.context["session"] = session

        target = session.get(get_column_name(Database.OBJECT_KEY))
        if target:
            self.context["target"] = normalize_target_name(target)

        metadata = session.get("metadata", {})
        # the telescope name is our instrument id
        instrument = metadata_to_instrument_id(metadata)
        if instrument:
            self.context["instrument"] = instrument

        # the FITS INSTRUMEN keyword is the closest thing we have to a default camera ID.  FIXME, let user override
        # if needed?
        # It isn't in the main session columns, so we look in metadata blob

        camera_id = metadata_to_camera_id(metadata)
        if camera_id:
            self.context["camera_id"] = camera_id

        logging.debug(f"Using camera_id={camera_id}")

        # The type of images in this session
        imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))
        if imagetyp:
            imagetyp = get_aliases().normalize(imagetyp)
            self.context["imagetyp"] = imagetyp

            # add a short human readable description of the session - suitable for logs or in filenames
            session_config = f"{imagetyp}"

            metadata = session.get("metadata", {})
            filter = metadata.get(Database.FILTER_KEY)
            if (imagetyp == "flat" or imagetyp == "light") and filter:
                # we only care about filters in these cases
                session_config += f"_{filter}"
            if imagetyp == "dark":
                exptime = session.get(get_column_name(Database.EXPTIME_KEY))
                if exptime:
                    session_config += f"_{int(float(exptime))}s"
            gain = metadata.get(Database.GAIN_KEY)
            if gain is not None:  # gain values can be zero
                session_config += f"_gain{gain}"

            self.context["session_config"] = session_config

        # a short user friendly date for this session
        date = session.get(get_column_name(Database.START_KEY))
        if date:
            # Convert ISO date to yyyy-mm-dd_hh-mm-ss format for guaranteed filename uniqueness
            from datetime import datetime

            from starbash import (
                to_shortdate,
            )  # Lazy import to avoid circular dependency

            dt = datetime.fromisoformat(date)
            self.context["datetime"] = dt.strftime("%Y-%m-%d_%H-%M-%S")

            self.context["date"] = to_shortdate(date)

    @property
    def target(self) -> dict[str, Any] | None:
        """Get the current target from the context."""
        return self.context.get("target")

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
    def output_file_info(self) -> FileInfo:
        """Get the current output directory (for working/temp files) from the context."""
        d = self.context["final_output"]
        return d

    def _create_master_tasks(self) -> list[TaskDict]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.
        """
        # it is important that we make bias/dark **before** flats because we don't yet do all the task execution in one go
        results: list[TaskDict] = []
        results.extend(self._create_masters_by_type("bias"))
        results.extend(self._create_masters_by_type("dark"))
        results.extend(self._create_masters_by_type("flat"))

        return results

    def _create_masters_by_type(self, imagetyp: str) -> list[TaskDict]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.
        """
        sessions = self._get_sessions_by_imagetyp(imagetyp)
        results = self._create_tasks(sessions, [None])

        for t in results:
            t["meta"]["is_master"] = True  # mark these as possibly uninteresting

        return results

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate master calibration frames (bias, dark, flat).

        Returns:
            List of ProcessingResult objects, one per master frame generated.
        """
        # it is important that we make bias/dark **before** flats because we don't yet do all the task execution in one go

        types = ["bias", "dark", "flat"]
        results: list[ProcessingResult] = []
        for t in types:
            # run each of the master gens sepearately - because flats might need bias/dark to be present
            results.extend(self._run_all_tasks(self._create_masters_by_type(t)))
        return results

    @property
    def tasks(self) -> list[TaskDict]:
        """Get the list of tasks generated for the current processing run."""
        return list[TaskDict](self.doit.dicts.values())

    def _add_task(self, task: TaskDict) -> None:
        """Add a task to the doit task list."""
        self.doit.add_task(task)

    def _run_jobs(self) -> None:
        # add a default task to run all the other tasks
        self._add_task(create_default_task(self.tasks))

        tree = to_rich_string(to_tree(self.tasks))

        logging.debug(f"Tasks:\n{tree}")

        # fire up doit to run the tasks
        # FIXME, perhaps we could run doit one level higher, so that all targets are processed by doit
        # for parallism etc...?
        # self.doit.run(["list", "--all", "--status"])

        logging.debug("Running doit tasks...")
        doit_args: list[str] = []
        if starbash.force_regen:
            doit_args.append("-a")  # force rebuild
        doit_args.append("process_all")
        result_code = self.doit.run(doit_args)  # light_{self.target}_s35

        # Start with a blank task list next time
        self.doit.dicts.clear()

        # FIXME - it would be better to call a doit entrypoint that lets us catch the actual Doit exception directly
        if (
            result_code != 0 and result_code != 1
        ):  # 1 means a task failed, we just include that failure in our list of results
            raise RuntimeError(f"doit processing failed with exit code {result_code}")

    def _job_to_tasks(self, job_name: str, target: str | None) -> None:
        """Do processing for a particular target/master
        (i.e. all selected sessions for a particular complete processing run)."""

        with ProcessedTarget(self, target) as pt:
            pt.config_valid = False  # assume our config is not worth writing

            stages = self.stages
            self._stages_to_tasks(stages)

            self.doit.set_tasks(self.preflight_tasks(pt, self.tasks))
            # self.doit.run(
            #     [
            #         "info",
            #         "process_all",  # "stack_m20",  # seqextract_haoiii_m20_s35
            #     ]
            # )
            # self.doit.run(["dumpdb"])
            pt.config_valid = True  # our config is probably worth keeping

    @property
    def stages(
        self,
    ) -> list[StageDict]:
        """Get all pipeline stages defined in the merged configuration."""
        name = "stages"

        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).

        # FIXME this is kinda yucky.  The 'merged' repo_manage doesn't know how to merge AoT types, so we get back a list of AoT
        # we need to flatten that out into one list of dict like objects
        stages: list[AoT] = self.sb.repo_manager.merged.getall(name)
        s_unwrapped: list[StageDict] = []
        for stage in stages:
            # .unwrap() - I'm trying an experiment of not unwrapping stage - which would be nice because
            # stage has a useful 'source' backpointer.
            s_unwrapped.extend(stage)
        return s_unwrapped

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
        tool_parameters_in: dict[str, str] = tool_dict.get("parameters", {})
        tool_parameters = expand_context_dict(tool_parameters_in, self.context)
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
        script: str | list[str] | None = stage.get("script")
        if script:
            if isinstance(script, str):
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

        # Need to determine the working directory (cwd)
        # If we are 'importing' session files, use None so that the script is initially in a disposable temp dir
        # otherwise use process_dir
        cwd = self.context.get("process_dir") if not self.use_temp_cwd else None

        # Create the ToolAction and add to task
        action = ToolAction(tool, commands=script, cwd=cwd, parameters=tool_parameters)
        task["actions"] = [action]

    def _add_stage_context_defs(self, stage: StageDict) -> None:
        """Add any context definitions specified in the stage to our processing context.

        Args:
            stage: The stage definition from TOML
        """
        context_defs: dict[str, Any] = stage.get("context", {})
        for key, value in context_defs.items():
            self.context[key] = value

    def _clear_context(self) -> None:
        """Clear out any session-specific context variables."""
        # since 'inputs' are session specific we erase them here, so that _create_task_dict can reinit with
        # the correct session specific files
        self.context.pop("input", None)

    def _get_prior_tasks(self, stage: StageDict) -> TaskDict | list[TaskDict] | None:
        """Get the prior tasks for the given stage based on the 'after' input definition.

        Args:
            stage: The stage definition from TOML
        Returns:
            Note: this function will return a single TaskDict if the prior stage was not
            multiplexed, otherwise a list of TaskDicts for each multiplexed task.
            Or None if no "after" keyword was found."""
        inputs: list[InputDef] = stage.get("inputs", [])
        input_with_after = next((inp for inp in inputs if "after" in inp), None)

        if not input_with_after:
            return None

        after = get_safe(input_with_after, "after")
        prior_task_name = self._get_unique_task_name(
            after
        )  # find the right task for our stage and multiplex

        # Compile the prior_task_name into a regex pattern for prefix matching.
        # The pattern from TOML may contain wildcards like "light.*" which should match
        # task names like "light_m20_s35". We anchor the pattern to match the start of the task name.
        import re

        prior_starting_pattern = re.compile(f"^{prior_task_name}")
        prior_exact_pattern = re.compile(f"^{prior_task_name}$")

        # Handle the easier 'non-multiplexed' case - the name will exactly match
        keys = self.doit.dicts.keys()
        matching_keys = [k for k in keys if prior_exact_pattern.match(k)]
        if len(matching_keys) == 1:
            return self.doit.dicts[matching_keys[0]]

        # collect all the tasks that match prior_task_pattern, in case of multiplexing
        prior_tasks = []
        cur_session_id = self.context.get("session", {}).get("id")
        matching_keys = [k for k in keys if prior_starting_pattern.match(k)]
        for key in matching_keys:
            # Checking task names is a good filter, but to prevent being confused by things like:
            # prior_task_name is 'light_m20_s3' but the key is 'light_m20_s35' we also need to
            # confirm that the session IDs match
            if (
                not cur_session_id
                or self.doit.dicts[key]["meta"]["context"].get("session", {}).get("id")
                == cur_session_id
            ):
                prior_tasks.append(self.doit.dicts[key])

        if not prior_tasks:
            raise NoPriorTaskException(
                f"Could not find prior task '{prior_task_name}' for 'after' input."
            )
        return prior_tasks

    def _set_context_from_prior_stage(self, stage: StageDict) -> None:
        """If we have an input section marked to be "after" some other session, try to respect that."""
        prior_tasks = self._get_prior_tasks(stage)
        if not prior_tasks:
            # We aren't after anything - just plug in some correct defaults
            self._clear_context()
        else:
            # old_session = self.context.get("session")
            # FIXME this is kinda nasty, but if the prior stage was multiplexed we just need a context from any of
            # tasks in that stage (as if we were in in stage_to_tasks just after them).  So look for one by name
            # Use the last task in the list
            multiplexed = isinstance(prior_tasks, list)
            if multiplexed:
                prior_task = prior_tasks[-1]
            else:
                prior_task = prior_tasks

            context = prior_task["meta"]["context"]
            old_session = self.context.get("session")
            self.context = _clone_context(context)

            # Don't accidentially try to copy in the prior stages input files
            self.context.pop("input_files", None)

            # We don't want downstream tasks to be confused by our transient multiplex and current stage inputs
            self.context.pop("multiplex_index", None)
            self.context.pop("stage_input", None)

            if multiplexed:
                # since we just did a nasty thing, we don't want to inadvertently think our current
                # (possibly non multiplexed) stage is tied to the prior stage's session
                self.context.pop("session", None)  # remove the just added session
                if old_session:
                    self.context["session"] = old_session  # restore our old session

    def _stage_to_tasks(self, stage: StageDict) -> None:
        """Convert the given stage to doit task(s) and add them to our doit task list.

        This method handles both single and multiplexed (per-session) stages.
        For multiplexed stages, creates one task per session with unique names.
        """
        self.stage = stage

        # Find what kinds of inputs the stage is REQUESTING
        # masters_in = _inputs_by_kind(stage, "master")  # TODO: Use for input resolution
        has_session_in = len(_inputs_by_kind(stage, "session")) > 0
        has_session_extra_in = len(_inputs_by_kind(stage, "session-extra")) > 0

        assert (not has_session_in) or (not has_session_extra_in), (
            "Stage cannot have both 'session' and 'session-extra' inputs simultaneously."
        )

        self._add_stage_context_defs(stage)

        # If we have any session inputs, this stage is multiplexed (one task per session)
        multiplex_by_session = has_session_in or has_session_extra_in
        if multiplex_by_session:
            # Create one task per session
            for s in self.sessions:
                # Note we have a single context instance and we set session inside it
                # later when we go to actually RUN the tasks we need to make sure each task is using a clone
                # from _clone_context().  So that task will be seeing the correct context data we are building here.
                # Note: we do this even in the "session_extra" case because that code needs to know the current
                # session to find the 'previous' stage.
                self._set_session_in_context(s)

                self._create_task_dicts(stage)
        else:
            # no session for non-session-multiplex stages
            self.context.pop("session", None)

            # Single task (no multiplexing) - e.g., final stacking or post-processing
            self._create_task_dicts(stage)

    def _get_unique_task_name(self, task_name: str) -> str:
        """Generate a unique task name for the given stage and current session."""

        # include target name in the task (if we have one)
        if self.target:
            task_name += f"_{self.target}"

        # NOTE: we intentially don't use self.session because session might be None here and thats okay
        session = self.context.get("session")
        if session:
            session_id = session["id"]

            # Make unique task name by combining stage name and session ID
            task_name += f"_s{session_id}"

        # handle input by single file multiplexing
        multiplex = self.context.get("multiplex_index")
        if multiplex is not None:
            task_name += f"_i{multiplex}"

        return task_name

    def _create_task_dict(self, stage: StageDict) -> None:
        """Create a doit task dictionary for a single session in a stage.

        Args:
            stage: The stage definition from TOML
            session: The session row from the database

        Returns:
            Task dictionary suitable for doit (or None if stage cannot be processed).
        """

        task_name = self._get_unique_task_name(stage.get("name", "unnamed_stage"))

        # Add our parameters to the context (stage.repo was monkey patched by the repo manager)
        # FIXME, perhaps it makes more sense to put parameters at the 'stage' level so we don't need to do this?
        assert self.processed_target, "ProcessedTarget is guaraneed to be set here"
        self.processed_target.parameter_store.add_from_repo(stage.source)  # pyright: ignore[reportAttributeAccessIssue]
        self.context["parameters"] = self.processed_target.parameter_store.as_obj

        self.use_temp_cwd = False

        fallback_output: None | ImageRow = None
        try:
            # in the multiplexed case we will have already resolved the input files _once_ for
            # the various subtasks.  Otherwise do that here
            if "multiplex_index" not in self.context:
                self._resolve_all_input_files(stage)  # resolve all inputs to current stage

            file_deps = self._collect_input_files(
                stage
            )  # convert current inputs into a list of doit dependencies
        except FallbackToImageException as e:
            logging.debug(
                f"Skipping '{stage.get('name')}' using fallback file {e.image.get('path', 'unknown')}"
            )
            fallback_output = e.image
            metadata = e.image.copy()
            metadata.pop(
                "repo", None
            )  # Repo is not serializable and for some reason doit serializes this
            self.context["metadata"] = (
                metadata  # Store the image metadata so it can be used in doit_post_process
            )
            file_deps = [e.image["abspath"]]  # abspath is guaranteed to be present

        targets = self._stage_output_files(stage)

        task_dict: TaskDict = {
            "name": task_name,
            "file_dep": expand_context_list(file_deps, self.context),
            # FIXME, we should probably be using something more structured than bare filenames - so we can pass base source and confidence scores
            "targets": expand_context_list(targets, self.context),
            "meta": {
                "context": _clone_context(self.context),
                "stage": stage,  # The stage we came from - used later in culling/handling conflicts
                "processing": self,  # so doit_post_process can update progress/write-to-db etc...
                "processed_target": self.processed_target,  # so the tasks can access saved toml metadata
            },
            "clean": True,  # Let the doit "clean" command auto-delete any targets we listed
        }

        if fallback_output:
            doit_do_copy(task_dict)
            task_dict["doc"] = "Simple copy of singleton input file"
        else:
            # add the actions THIS will store a SNAPSHOT of the context AT THIS TIME for use if the task/action is later executed
            self._stage_to_action(task_dict, stage)
            _stage_to_doc(task_dict, stage)  # add the doc string

        doit_post_process(task_dict)

        self._add_task(task_dict)

    def _create_task_dicts(self, stage: StageDict) -> None:
        """Create a doit task dictionaries for a possibly multiplexed input stage.

        Args:
            stage: The stage definition from TOML"""
        has_job_multiplex_in = len(_inputs_with_key(stage, "multiplex")) > 0

        try:
            # We need to init our context from whatever the prior stage was using.
            self._set_context_from_prior_stage(stage)

            if not has_job_multiplex_in:
                self.context.pop("stage_input", None)  # Force new stage inputs to be resolved
                self._create_task_dict(stage)
            else:
                self._resolve_all_input_files(
                    stage
                )  # resolve all inputs to current stage (to find out inputs to multiplex)

                # This should be already defined by this point
                job_inputs: dict[Any, FileInfo] = self.context["stage_input"]
                # FIXME, we currently assume this feature is only used with the default '0' input
                multiplexed_inputs = get_safe(job_inputs, 0)
                rows = multiplexed_inputs.image_rows
                assert rows, "I think always guaranteed have image rows here?"
                for index, image_row in enumerate(rows):
                    fi = FileInfo(
                        base=multiplexed_inputs.base, image_rows=[image_row]
                    )  # one image row at a time
                    job_inputs[0] = fi  # For this task we are telling it just this one file
                    self.context["multiplex_index"] = (
                        index  # let the task know we are multiplexing inputs
                    )
                    self._create_task_dict(stage)

        except NotEnoughFilesError as e:
            # if the session was empty that probably just means it was completely filtered as a bad match
            level = logging.DEBUG if len(e.files) == 0 else logging.WARNING
            logging.log(
                level,
                f"Skipping stage '{stage.get('name')}' - insufficient input files: {e}",
            )
        except NonFatalException as e:
            logging.debug(f"Skipping stage '{stage.get('name')}' - {e}")
        except UserHandledError as e:
            logging.warning(f"Skipping stage '{stage.get('name')}' - {e}")

        finally:
            # clean things up for any future runs
            self.context.pop("stage_input", None)
            self.context.pop("multiplex_index", None)

    def _with_defaults(self, img: ImageRow) -> ImageRow:
        """Try to provide missing metadata for image rows.  Some imagerows are 'sparse'
        with just a filename and minor other info.  In that case try to assume the metadata matches
        the input metadata for this single pipeline of images."""
        r = self.context.get("default_metadata", {}).copy()

        # values from the passed in img override our defaults
        for key, value in img.items():
            r[key] = value

        return r

    def _import_from_prior_stages(self, input: InputDef) -> FileInfo:
        """Import and filter image data from prior stage outputs.

        This function collects image rows from the outputs of previous stages in the pipeline,
        applies any filtering requirements specified in the input definition.  If that prior stage
        had matching unfiltered inputs, we assume that stage generated **outputs** that we want.

        Args:
            input: The input definition from the stage TOML, which may contain 'requires'
                   filters to apply to the collected image rows.

        Returns:
            The FileInfo object we found a matching stage.  (from task["meta"]["context"]["output"])

        Raises:
            ValueError: If no prior tasks have image_rows in their context, or if the
                       input definition is missing required fields.
        """
        image_rows: dict[
            str, ImageRow
        ] = {}  # We use a dict[abspath -> imagerow] because there might be duplicate outputs from prior stages

        assert self.stage
        prior_tasks = self._get_prior_tasks(self.stage)
        if not prior_tasks:
            raise ValueError("Input definition with 'after' must refer to a valid prior stage.")

        if not isinstance(prior_tasks, list):
            prior_tasks = [prior_tasks]

        # Collect all image rows from prior stage outputs
        child_exception: Exception | None = None

        base: str | None = None  # We will set base from the first matching prior task output
        for task in prior_tasks:
            task_context: dict[str, Any] = task["meta"]["context"]  # type: ignore
            task_inputs = task_context.get("input", {})

            # Look through all input types in the task context for image_rows
            for _input_type, file_info in task_inputs.items():
                if isinstance(file_info, FileInfo) and file_info.image_rows:
                    images = file_info.image_rows
                    images = [self._with_defaults(img) for img in images]
                    try:
                        task_filtered_input = filter_by_requires(input, images)
                        if (
                            task_filtered_input
                        ):  # This task had matching inputs for us, so therefore we want its outputs
                            task_output = task_context.get("output")
                            if (
                                task_output
                                and isinstance(task_output, FileInfo)
                                and task_output.image_rows
                            ):
                                base = task_output.base
                                for img in task_output.image_rows:
                                    image_rows[img["abspath"]] = img
                    except NotEnoughFilesError as e:
                        child_exception = e  # In case we need to raise later
                        # just because one prior task doesn't have what we need, we shouldn't stop looking
                        logging.debug(f"Prior task '{task['name']}' skipped, still looking... {e}")

        if child_exception and len(image_rows) == 0:
            # we failed on every child, give up
            raise child_exception

        return FileInfo(base=base, image_rows=list(image_rows.values()), definition=input)

    def preflight_tasks(self, pt: ProcessedTarget, tasks: list[TaskDict]) -> list[TaskDict]:
        # if user has excluded any stages, we need to respect that (remove matching stages)

        tasks = remove_excluded_tasks(tasks)

        # multimap from target file to tasks that produce it
        target_to_tasks = MultiDict[TaskDict]()
        for task in tasks:
            for target in task.get("targets", []):
                target_to_tasks.add(target, task)

        # check for tasks that are writing to the same target (which is not allowed).  If we
        # find such tasks we'll have to pick ONE based on priority and let the user know in the future
        # they could pick something else.
        for target in target_to_tasks.keys():
            producing_tasks = target_to_tasks.getall(target)
            if len(producing_tasks) > 1:
                conflicting_stages = tasks_to_stages(producing_tasks)
                assert len(conflicting_stages) > 1, (
                    "Multiple conflicting tasks must imply multiple conflicting stages?"
                )

                names = [t["name"] for t in conflicting_stages]
                logging.debug(
                    f"Multiple stages could produce the same target '{target}': {names}, picking a default for now..."
                )
                # exclude all but the first one (highest priority)
                stages_to_exclude = conflicting_stages[1:]

                # If the producing_tasks are generating conflicting outputs, all of those tasks must be associated with the
                # same session.  Therefore we only need to update one session row (which is shared by all of them)
                session = task_to_session(producing_tasks[0])
                if not session:
                    session = pt.default_stages
                set_excluded(session, stages_to_exclude)

                tasks = remove_excluded_tasks(tasks)

        set_used_stages_from_tasks(tasks)

        return tasks

    def _resolve_input_files(self, input: InputDef, index: int) -> None:
        """Resolve input file paths for a stage.

        Args:
            stage: The stage definition from TOML

        """
        # FIXME: Implement input file resolution
        # - Extract inputs from stage["inputs"]
        # - For each input, based on its "kind":
        #   - "session": get session light frames from database
        #   - "master": look up master frame path (bias/dark/flat)
        #   - "job": construct path from previous stage outputs
        # - Apply input.requires filters (metadata, min_count, camera)
        # - Return list of actual file paths

        # Note: at the time of staging, we store the inputs from _this stage_ in new_input
        # later (after staging) we merge this into the prior stages inputs in commit_inputs().
        # This allows us do staging at an earlier point in the pipeline.
        ci: dict = self.context["stage_input"]

        def _resolve_input_job() -> None:
            """Resolve job-type inputs by importing data from prior stage outputs.

            For each input name specified in the input definition, this function:
            1. Imports and filters image rows from prior stages using _import_from_prior_stages
            2. Stores the resulting FileInfo in the context under context["input"][name]
            3. Collects all file paths from all imported FileInfos

            Returns:
                List of Path objects for all files imported from prior stages.
            """

            # name is optional - if missing we use the integer index as the name
            input_names: list[str] | list[int] = (
                get_list_of_strings(input, "name") if "name" in input else [index]
            )

            # Import and filter data from prior stages
            file_info = self._import_from_prior_stages(input)
            for name in input_names:
                # Store in context for script access
                ci[name] = file_info

        def _resolve_session_extra() -> None:
            # In this case our context was preinited by cloning from the stage that preceeded us in processing
            # To clean things up (before importing our real imports) we could clobber the old input section
            # ci.clear()
            # HOWEVER, I think it is useful to let later stages optionally refer to prior stage inputs (because inputs have names we can
            # use to prevent colisions).
            # In particular the "lights" input is useful to find our raw source files.

            # currently our 'output' is really just the FileInfo from the prior stage output.  Repurpose that as
            # our new input.
            file_info: FileInfo = get_safe(self.context, "output")
            file_info.definition = input  # update definition to current input

            # We don't actually use this return value, but we want an exception raised if we are missing suitable
            # prior inputs (i.e. if the current requires filters don't match anything).
            self._import_from_prior_stages(input)

            ci["extra"] = (
                file_info  # FIXME, change inputs to optionally use incrementing numeric keys instead of "default""
            )
            self.context.pop("output", None)  # remove the bogus output

        def _resolve_input_session() -> None:
            images = self.sb.get_session_images(self.session)

            # FIXME Move elsewhere. It really just just be another "requires" clause
            imagetyp = get_safe(input, "type")
            images = self.sb.filter_by_imagetyp(images, imagetyp)

            filter_by_requires(input, images)

            logging.debug(f"Using {len(images)} files as input_files")
            self.use_temp_cwd = True

            repo: Repo | None = None
            if len(images) > 0:
                ref_image = images[0]
                repo = ref_image.get("repo")  # all images will be from the same repo
                self.context["default_metadata"] = (
                    ref_image  # To allow later stage scripts info about the current script pipeline
                )

            fi = FileInfo(
                image_rows=images,
                repo=repo,
                base=f"{imagetyp}_s{self.session['id']}",  # it is VERY important that the base name include the session ID, because it is used to construct unique filenames
                definition=input,
            )
            ci[imagetyp] = fi

            # The tool invocation will automatically copy any files listed in input_files
            # into the local working directory - which is what we want for 'session' inputs
            self.context["input_files"] = fi.full_paths

        def _resolve_input_master() -> None:
            imagetyp = get_safe(input, "type")
            masters = self.sb.get_master_images(imagetyp=imagetyp, reference_session=self.session)
            if not masters:
                raise UserHandledError(
                    f"No master frames of type '{imagetyp}' found for stage.  Have you already run 'sb process masters'?"
                )

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
                raise NoSuitableMastersException(imagetyp)

            used_candidates = [scored_masters[0]]  # FIXME, for now we just pick the top one
            excluded_candidates = scored_masters[1:]

            self.sb._add_image_abspath(
                used_candidates[0].candidate
            )  # make sure abspath is populated, we need it

            selected = used_candidates[0].candidate
            selected_master = selected["abspath"]
            path = Path(selected["path"])  # to get just the filename portion
            logging.info(
                f"For master '{imagetyp}', using: {path.name} (score={used_candidates[0].score:.1f}, {used_candidates[0].reason})"
            )

            # so scripts can find input["bias"].base etc...
            info = FileInfo(full=selected_master, definition=input)
            # Store the canidates we considered so they eventually end up in the toml fole
            session_masters = self.session.setdefault("masters", {})
            session_masters[imagetyp] = {
                "used": toml_from_list(used_candidates),  # To have nice comments in the toml
                "excluded": toml_from_list(excluded_candidates),
            }
            ci[imagetyp] = info

        resolvers = {
            "job": _resolve_input_job,
            "session": _resolve_input_session,
            "master": _resolve_input_master,
            "session-extra": _resolve_session_extra,
        }
        kind: str = get_safe(input, "kind")
        resolver = get_safe(resolvers, kind)
        resolver()

    def _resolve_all_input_files(self, stage: StageDict) -> None:
        """Resolve input file paths for the given stage.
        This populates context["stage_input"] with all the inputs for the current stage.

        Args:
            stage: The stage definition from TOML"""
        inputs: list[InputDef] = stage.get("inputs", [])

        # Prepare for a new staging run by initing the generated inputs
        new_inputs: dict[str, FileInfo] = {}
        self.context["stage_input"] = new_inputs  # inputs for just the current stage

        for index, inp in enumerate(inputs):
            self._resolve_input_files(inp, index)

    def _collect_input_files(self, stage: StageDict) -> list[Path]:
        """Get all input file paths for the given stage.

        Args:
            stage: The stage definition from TOML"""

        # Collect all the generate inputs into a single list of files for doit
        all_input_files: list[Path] = []
        new_inputs: dict[str, FileInfo] = self.context["stage_input"]
        for inp in new_inputs.values():
            all_input_files.extend(inp.full_paths)

        # Merge the new inputs into the existing inputs in context
        existing_inputs: dict[str, FileInfo] = self.context.setdefault("input", {})
        existing_inputs.update(new_inputs)

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

        def _resolve_files(dir: Path, output_file_info: FileInfo | None = None) -> FileInfo:
            """combine the directory with the input/output name(s) to get paths."""
            filenames: list[str] = []

            auto_prefix = output.get("auto", {}).get("prefix", "")
            auto_suffix = output.get("auto", {}).get("suffix")
            repo: Repo | None = None  # the repo for our output (assume none)
            if output_file_info:
                repo = (
                    output_file_info.repo
                )  # preserve the same repo we were using for output (if possible)

            # Note: we allow auto.suffix to be an empty string to remove suffixes
            if auto_prefix or auto_suffix is not None:
                # automatically generate filenames based on input files
                my_input = self.context["input"]  # Guaranteed to be present by now
                input_file_info: FileInfo = get_safe(
                    my_input, 0
                )  # FIXME, currently we only work with the 'default' input for this feature

                for filename in input_file_info.short_paths:
                    # change suffix: if filename already has a suffix, replace it otherwise add it
                    if auto_suffix is not None:
                        stem = Path(filename).stem
                        filename = f"{stem}{auto_suffix}"

                    generated_name = f"{auto_prefix}{filename}"
                    filenames.append(generated_name)
            else:
                # normal case - get the list of filenames from the output definition
                filenames = get_list_of_strings(output, "name")

            # filenames might have had {} variables, we must expand them before going to the actual file
            filenames = [expand_context_unsafe(f, self.context) for f in filenames]

            if not filenames:
                raise ValueError("Output definition must specify at least one file.")

            return FileInfo(
                repo=repo, base=str(dir), image_rows=[_make_imagerow(dir, f) for f in filenames]
            )

        def _resolve_output_job() -> FileInfo:
            return _resolve_files(self.job_dir)

        def _resolve_processed() -> FileInfo:
            fi = self.output_file_info
            assert fi.base, "Output FileInfo must have a base for processed output"
            return _resolve_files(Path(fi.base), fi)

        def _resolve_master() -> FileInfo:
            """Master frames and such - just a single output file in the output dir."""
            fi = self._get_output_by_repo("master")
            assert fi.base, "Output FileInfo must have a base for master output"
            assert fi.full, "Should be inited by now"
            assert fi.relative
            imagerow = {"abspath": str(fi.full), "path": fi.relative}
            fi.image_rows = [imagerow]
            return fi

        resolvers = {
            "job": _resolve_output_job,
            "processed": _resolve_processed,
            "master": _resolve_master,
        }
        kind: str = get_safe(output, "kind")
        resolver = get_safe(resolvers, kind)
        r: FileInfo = resolver()

        r.definition = output
        self.context["output"] = r
        return r.full_paths

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

    def _get_output_by_repo(self, kind: str) -> FileInfo:
        """Get output paths in the context based on their kind.

        Args:
            kind: The kind of output ("job", "processed", etc.)
            paths: List of Path objects for the outputs
        """
        # Find the repo with matching kind
        dest_repo = self.sb.repo_manager.get_repo_by_kind(kind)
        if not dest_repo:
            raise_missing_repo(kind)

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
        return FileInfo(base=str(base_path), full=full_path, relative=repo_relative, repo=dest_repo)

    def _set_output_to_repo(self, kind: str) -> None:
        """Set output paths in the context based on their kind.

        Args:
            kind: The kind of output ("job", "processed", etc.)
            paths: List of Path objects for the outputs
        """
        # Set context variables as documented in the TOML
        # FIXME, change this type from a dict to a dataclass?!? so foo.base works in the context expanson strings
        self.context["output"] = self._get_output_by_repo(kind)

    def _set_output_by_kind(self, kind: str) -> None:
        """Set output paths in the context based on their kind.

        Args:
            kind: The kind of output ("job", "processed", "master" etc...)
            paths: List of Path objects for the outputs
        """
        if kind == "job":
            raise NotImplementedError("Setting 'job' output kind is not yet implemented")
        else:
            # look up the repo by kind
            self._set_output_to_repo(kind)

            # Store that FileInfo so that any task that needs to know our final output dir can find it.  This is useful
            # so we can read/write our per target starbash.toml file for instance...
            self.context["final_output"] = self.context["output"]
