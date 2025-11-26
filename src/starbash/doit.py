import logging
import shutil
from typing import Any

from doit.action import BaseAction
from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.reporter import ConsoleReporter
from doit.task import Task, dict_to_task

from starbash.paths import get_user_cache_dir
from starbash.processed_target import ProcessingLike
from starbash.tool import Tool

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

    task_dict["actions"].append(closure)


class ToolAction(BaseAction):
    """An action that runs a starbash tool with given commands and context."""

    def __init__(self, tool: Tool, commands: str, cwd: str | None = None):
        self.tool: Tool = tool
        self.commands: str = commands
        self.task: Task | None = None  # Magically filled in by doit
        self.cwd: str | None = cwd

    def execute(self, out=None, err=None):
        # Doit requires that we set result to **something**. None is fine, though returning TaskFailed or a dictionary or a string.
        assert self.task and self.task.meta  # We always set this to context
        context: dict[str, Any] = self.task.meta["context"]

        logging.debug(f"Running ToolAction for {self.task}")
        self.result = self.tool.run(self.commands, context=context, cwd=self.cwd)
        self.values = {}  # doit requires this attribute to be set

    def __str__(self) -> str:
        return f"ToolAction(tool={self.tool.name}, commands={self.commands})"


class MyReporter(ConsoleReporter):
    # def __init__(self, outstream, options):
    #     from starbash import console

    #     # instead of stdout, have it go to our rich console
    #     outstream = console
    #     super().__init__(outstream, options)

    def execute_task(self, task):
        self.outstream.write("MyReporter --> %s\n" % task.title())


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
        dep_file = str(cache_dir / ".doit.db")
        return {"verbosity": 2, "dep_file": dep_file, "reporter": MyReporter}

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
