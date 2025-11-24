import logging
import shutil
from typing import Any

from doit.action import BaseAction
from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.task import Task, dict_to_task

from starbash.paths import get_user_cache_dir
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
        return {"verbosity": 2, "dep_file": dep_file}

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
