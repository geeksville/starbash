import logging
import shutil
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doit.action import BaseAction, TaskFailed
from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.exceptions import BaseFail
from doit.reporter import ConsoleReporter
from doit.task import Task, dict_to_task
from rich.progress import TaskID

from repo import Repo
from starbash.database import ImageRow
from starbash.exception import UserHandledError
from starbash.paths import get_user_cache_dir
from starbash.processing_like import ProcessingLike
from starbash.tool.base import Tool

# for early testing
my_builtin_task = {
    "name": "sample_task",
    "actions": ["echo hello from built in"],
    "doc": "sample doc",
}

__all__ = [
    "StarbashDoit",
    "ToolAction",
    "my_builtin_task",
]

type TaskDict = dict[str, Any]  # a doit task dictionary


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
    image_rows: list[ImageRow] | None = None  # List of individual files (if applicable)

    @property
    def short_paths(self) -> list[str]:
        """Get the list of individual file paths from this FileInfo.

        Returns:
            List of Path objects for individual files. (relative to the base directory)
        """
        if self.image_rows is not None:
            return [img["path"] for img in self.image_rows]
        elif self.base is not None:
            return [self.base]
        else:
            return []

    @property
    def full_paths(self) -> list[Path]:
        """Get the list of individual file paths from this FileInfo.

        Returns:
            List of Path objects for individual files. (full abs paths)
        """
        if self.image_rows is not None:
            return [img["abspath"] for img in self.image_rows]
        elif self.full is not None:
            return [self.full]
        else:
            return []


max_contexts = 3  # FIXME, eventually make customizable via user preferences


def get_processing_dir() -> Path:
    """Get the base directory for processing contexts."""
    cache_dir = get_user_cache_dir()
    processing_dir = cache_dir / "processing"
    processing_dir.mkdir(parents=True, exist_ok=True)
    return processing_dir


def cleanup_old_contexts() -> None:
    """Remove oldest context directories if we exceed max_contexts."""
    processing_dir = get_processing_dir()
    if not processing_dir.exists():
        return

    # Get all subdirectories in processing_dir
    contexts = [d for d in processing_dir.iterdir() if d.is_dir()]

    # If we have more than max_contexts, delete the oldest ones
    if len(contexts) > max_contexts:
        # Sort by modification time (oldest first)
        contexts.sort(key=lambda d: d.stat().st_mtime)

        # Calculate how many to delete
        num_to_delete = len(contexts) - max_contexts

        # Delete the oldest directories
        for context_dir in contexts[:num_to_delete]:
            logging.info(f"Removing old processing context: {context_dir}")
            shutil.rmtree(context_dir, ignore_errors=True)


def doit_do_copy(task_dict: TaskDict):
    """Just add an action that copies files from file_dep to targets"""
    src = task_dict["file_dep"]
    dest = task_dict["targets"]

    assert len(src) >= 1, "doit_do_copy requires at least one source file"

    copy_actions = []
    for s, d in zip(src, dest, strict=True):
        tuple = (shutil.copy, [s, d])
        copy_actions.append(tuple)

    task_dict["actions"] = copy_actions


def add_action(task_dict: TaskDict, action: Callable):
    """Add an action to the task dictionary's actions list."""
    actions: list = task_dict.setdefault("actions", [])
    actions.append(action)


def doit_post_process(task_dict: TaskDict):
    """Do after execution processing

    * Populate master output files in the DB (FIXME I think we can remove this once doit dependencies fully linked)
    * Set result for this task (for later reporting)
    * Advance the progress bar
    """

    def closure(targets) -> None:
        logging.debug(f"Post processing task {task_dict['name']}")

        meta = task_dict.get("meta", {})
        context = meta.get("context", {})
        output = context.get("output")

        if output and output.repo and output.repo.kind() == "master":
            processing: ProcessingLike = meta["processing"]  # guaranteed to be present
            sb = processing.sb

            # we add new masters to our image DB
            # add to image DB (ONLY! we don't also create a session)

            # The generated files might not have propagated all of the metadata (because we added it after FITS import)
            extra_metadata = context.get("metadata", {})
            sb.add_image(
                output.repo,
                output.full,
                force=True,
                extra_metadata=extra_metadata,
            )

    add_action(task_dict, closure)


class ToolAction(BaseAction):
    """An action that runs a starbash tool with given commands and context."""

    def __init__(
        self,
        tool: Tool,
        commands: str | list[str],
        cwd: str | None = None,
        parameters: dict[str, Any] = {},
    ):
        self.tool: Tool = tool
        self.commands: str | list[str] = commands
        self.task: Task | None = None  # Magically filled in by doit
        self.cwd: str | None = cwd
        self.parameters: dict[str, Any] = parameters

    def execute(self, out=None, err=None):
        # Doit requires that we set result to **something**. None is fine, though returning TaskFailed or a dictionary or a string.
        assert self.task and self.task.meta  # We always set this to context
        context: dict[str, Any] = self.task.meta["context"]

        # Optional description of input files - to give user an idea on how long it will take
        input_files: list[FileInfo] = context.get("input_files", [])
        desc = ""
        if input_files:
            desc = f"({len(input_files)} input files)"

        logging.info(f"Running {self.tool.name} for {self.task.name} {desc}")
        try:
            self.result = self.tool.run(
                self.commands, context=context, cwd=self.cwd, **self.parameters
            )
        except ValueError as e:
            # We pass back any exceptions in task.meta - so that our ConsoleReporter can pick them up (doit normally strips exceptions)
            self.task.meta["exception"] = e
            return TaskFailed("tool failed")
            # raise e  # Let doit do its normal exception handling though

        self.values = {}  # doit requires this attribute to be set

    def __str__(self) -> str:
        return f"ToolAction(tool={self.tool.name}, commands={self.commands})"


@dataclass
class ProcessingResult:
    task: Task
    success: bool | None = None  # false if we had an error, None if skipped
    reason: str | None = (
        None  # reason for failure/skipping (either "processed", "skipped", "ignored", "failed")
    )
    notes: str | None = None  # notes about what happened
    # FIXME, someday we will add information about masters/flats that were used?

    @property
    def context(self) -> dict[str, Any]:
        assert self.task.meta, "ProcessingResult requires task.meta to be set"
        return self.task.meta.get("context", {})

    @property
    def is_master(self) -> bool:
        assert self.task.meta, "ProcessingResult requires task.meta to be set"
        return self.task.meta.get("is_master", False)

    @property
    def session_desc(self) -> str:
        return f"{self.context.get('date', '')}:{self.context.get('session_config', '')}"

    @property
    def target(self) -> str:
        """normalized target name, or in the case of masters the camera or instrument id"""

        output: FileInfo | None = self.context.get("output")
        t = self.context.get("target")
        if not t and output and output.relative:
            t = output.relative
        return t or "unknown"

    def update(self, e: Exception | BaseFail | None = None) -> None:
        """Handle exceptions during processing and update the ProcessingResult accordingly."""
        if e:
            self.success = False

            if isinstance(e, BaseFail):
                self.notes = "Task failed: " + str(e)
            elif isinstance(e, UserHandledError):
                e.ask_user_handled()
                # FIXME we currently ignore the result of ask_user_handled?
                self.notes = f"{self.task.name}: {e.__rich__()}"  # No matter what we want to show the fault in our results
            elif isinstance(e, RuntimeError):
                # Print errors for runtimeerrors but keep processing other runs...
                logging.error(f"Skipping run due to: {e}")
                self.notes = f"Aborted due to possible error in (alpha) code, please file bug on our github: {str(e)}"
            elif isinstance(e, ValueError):
                # General error from user misconfiguration or tools - not a bug in our code
                logging.error(f"Skipping run due to: {e}")
                self.notes = str(e)
            else:
                # Unexpected exception - log it and re-raise
                logging.exception("Unexpected error during processing:")
                raise e


class MyReporter(ConsoleReporter):
    """A custom reporter that uses rich progress bars to show task progress."""

    def __init__(self, outstream, options):
        super().__init__(outstream, options)
        self.job_task = TaskID(0)
        self.processing: ProcessingLike | None = None

    def execute_task(self, task):
        """Called just before running a task"""
        # self.outstream.write("MyReporter --> %s\n" % task.title())

        if self.processing:
            self.processing.progress.update(
                self.job_task, description=f"Subtask: {task.title()}", refresh=True
            )

    def _handle_completion(
        self,
        task: Task,
        fail: BaseFail | None = None,
        reason: str | None = None,
        success: bool | None = True,
    ) -> None:
        # We made progress - call once per iteration ;-)

        if self.processing:
            self.processing.progress.advance(self.job_task)

            if task.meta:
                result = ProcessingResult(task=task, reason=reason, success=success)
                e = task.meta.get("exception")  # try to pass our raw exception if possible

                result.notes = task.name  # default nodes just show the task name
                result.update(e or fail)
                self.processing.add_result(result)

    def skip_uptodate(self, task):
        """skipped up-to-date task"""
        self._handle_completion(task, reason="Current", success=None)

    def skip_ignore(self, task):
        """skipped ignored task"""
        self._handle_completion(task, reason="Ignored", success=None)

    def add_success(self, task):
        """called when execution finishes successfully (either this or add_failure is guaranteed to be called)"""
        super().add_success(task)
        self._handle_completion(task)

    def add_failure(self, task, fail: BaseFail):
        """called when execution finishes with a failure"""
        super().add_failure(task, fail)
        self._handle_completion(task, fail)

    def initialize(self, tasks: OrderedDict[str, Task], selected_tasks):
        """called just after tasks have been loaded before execution starts

        tasks will be the full list of tasks we might run
        """
        super().initialize(tasks, selected_tasks)

        if len(tasks) > 0:
            first = next(
                iter(tasks.values())
            )  # All tasks we add are required to have meta.processing

            self.processing = first.meta and first.meta["processing"]
            if self.processing:
                self.job_task = self.processing.progress.add_task(
                    "Processing tasks...", total=len(tasks)
                )

    def complete_run(self):
        """called when finished running all tasks"""
        super().complete_run()

        if self.processing:
            self.processing.progress.remove_task(self.job_task)


class StarbashDoit(TaskLoader2):
    """The starbash wrapper for doit invocation."""

    def __init__(self):
        super().__init__()
        self.dicts: dict[str, TaskDict] = {}

        # For early testing
        # self.add_task(my_builtin_task)

    def set_tasks(self, tasks: list[TaskDict]) -> None:
        """Replace the current list of tasks with the given list."""
        self.dicts = {}
        for task in tasks:
            self.add_task(task)

    def add_task(self, task_dict: TaskDict) -> None:
        """Add a task defined as a dictionary to the list of tasks.

        Args:
            task_dict: The task definition as a dictionary.
        """
        if task_dict["name"] in self.dicts:
            raise ValueError(f"Task with name {task_dict['name']} already exists.")

        task_dict["io"] = {
            "capture": False
        }  # Important to turn off doit iocapture - it breaks rich logging

        self.dicts[task_dict["name"]] = task_dict

    def run(self, args: list[str] = []) -> int:
        """Run the doit command using our currently loaded tasks

        Returns:
            Exit code from doit command (0 for success)
        """
        main = DoitMain(self)
        return main.run(args)

    def setup(self, opt_values) -> None:
        """Required by baseclass"""
        pass

    def load_doit_config(self) -> dict[str, Any]:
        """Required by baseclass"""
        # Store the doit database in the user's cache directory instead of the workspace
        cache_dir = get_user_cache_dir()
        dep_file = str(cache_dir / "doit.json")
        return {
            "verbosity": 2,
            "dep_file": dep_file,
            "reporter": MyReporter,
            "backend": "json",
        }

    def load_tasks(self, cmd, pos_args):
        """Load tasks for Starbash. (required by baseclass)

        Args:
            cmd: The command object.
            pos_args: The positional arguments.

        Returns:
            A list of tasks.
        """
        task_list = [dict_to_task(t) for t in self.dicts.values()]
        return task_list
