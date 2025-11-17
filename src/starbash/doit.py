from typing import Any

from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.task import dict_to_task

# for early testing
my_builtin_task = {
    "name": "sample_task",
    "actions": ["echo hello from built in"],
    "doc": "sample doc",
}


class StarbashDoit(TaskLoader2):
    """The starbash wrapper for doit invocation."""

    def __init__(self):
        super().__init__()
        self.dicts: list[dict[str, Any]] = []

        # For early testing
        self.add_task(my_builtin_task)

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
        return {"verbosity": 2}

    def load_tasks(self, cmd, pos_args):
        """Load tasks for Starbash. (required by baseclass)

        Args:
            cmd: The command object.
            pos_args: The positional arguments.

        Returns:
            A list of tasks.
        """
        task_list = [dict_to_task(my_builtin_task)]
        return task_list
