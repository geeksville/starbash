from typing import Any

from doit.action import BaseAction
from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.task import dict_to_task

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


class ToolAction(BaseAction):
    """An action that runs a starbash tool with given commands and context."""

    def __init__(self, tool: Tool, commands: str, context: dict = {}, cwd: str | None = None):
        self.tool: Tool = tool
        self.commands: str = commands
        self.context: dict[Any, Any] = context
        self.cwd: str | None = cwd

    def execute(self, out=None, err=None):
        # Doit requires that we set result to **something**. None is fine, though returning TaskFailed or a dictionary or a string.
        self.result = self.tool.run(self.commands, context=self.context, cwd=self.cwd)
        self.values = {}  # doit requires this attribute to be set

    def __str__(self) -> str:
        return f"ToolAction(tool={self.tool.name}, commands={self.commands})"


class StarbashDoit(TaskLoader2):
    """The starbash wrapper for doit invocation."""

    def __init__(self):
        super().__init__()
        self.dicts: list[dict[str, Any]] = []

        # For early testing
        # self.add_task(my_builtin_task)

    def add_task(self, task_dict: dict[str, Any]) -> None:
        """Add a task defined as a dictionary to the list of tasks.

        Args:
            task_dict: The task definition as a dictionary.
        """
        self.dicts.append(task_dict)

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
        task_list = [dict_to_task(t) for t in self.dicts]
        return task_list
