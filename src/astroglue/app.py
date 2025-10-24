import logging
from importlib import resources

import itertools
from astroglue.tool import Tool
from astroglue.repo import RepoManager
from astroglue.tool import tools


class AstroGlue:
    """The main AstroGlue application class."""

    def __init__(self):
        """
        Initializes the AstroGlue application by loading configurations
        and setting up the repository manager.
        """
        logging.info("AstroGlue application initializing...")

        # Load app defaults and initialize the repository manager
        app_defaults_text = (
            resources.files("astroglue").joinpath("appdefaults.ag.toml").read_text()
        )
        self.repo_manager = RepoManager(app_defaults_text)
        logging.info(
            f"Repo manager initialized with {len(self.repo_manager.repos)} default repo references."
        )
        self.repo_manager.dump()
        self.run_all_stages()

    def run_all_stages(self):
        """On the currently active session, run all processing stages"""
        logging.info("--- Running all stages ---")

        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).
        pipeline_definitions = self.repo_manager.union().getall("stages")
        flat_pipeline_steps = list(itertools.chain.from_iterable(pipeline_definitions))

        # 2. Sort the pipeline steps by their 'priority' field.
        try:
            sorted_pipeline = sorted(flat_pipeline_steps, key=lambda s: s["priority"])
        except KeyError as e:
            # Re-raise as a ValueError with a more descriptive message.
            raise ValueError(
                f"invalid stage definition: a stage is missing the required '{e.key}' key"
            ) from e

        # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
        task_definitions = self.repo_manager.union().getall("stage")
        all_tasks = list(itertools.chain.from_iterable(task_definitions))

        logging.info(
            f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority."
        )

        # 4. Iterate through the sorted pipeline and execute the associated tasks.
        for step in sorted_pipeline:
            step_name = step.get("name")
            if not step_name:
                raise ValueError("Invalid pipeline step found: missing 'name' key.")

            logging.info(
                f"--- Running pipeline step: '{step_name}' (Priority: {step['priority']}) ---"
            )
            # Find all tasks that should run during this pipeline step.
            tasks_to_run = [task for task in all_tasks if task.get("when") == step_name]
            for task in tasks_to_run:
                self.run_stage(task)

        logging.info("--- End of stages ---")

    def run_stage(self, stage: dict) -> None:
        """
        Executes a single processing stage.

        Args:
            stage: A dictionary representing the stage configuration, containing
                   at least 'tool' and 'script' keys.
        """
        tool_name = stage.get("tool")
        if not tool_name:
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'tool' definition."
            )

        script = stage.get("script")
        if script is None:  # Allow empty scripts
            raise ValueError(
                f"Stage '{stage.get('name')}' is missing a 'script' definition."
            )

        tool = tools.get(tool_name)
        if not tool:
            raise ValueError(
                f"Tool '{tool_name}' for stage '{stage.get('name')}' not found."
            )

        logging.info(f"  Using tool: {tool_name}")
        tool_instance: Tool = tool

        # This allows recipe TOML to define their own default variables.
        context = stage.get("context", {})

        # Update the context with runtime values.
        runtime_context = {
            "process_dir": "/workspaces/astroglue/images/process",  # FIXME - create/find this more correctly per session
            "masters": "/workspaces/astroglue/images/masters" # FIXME find this the correct way
        }
        context.update(runtime_context)

        tool_instance.run(script, context=context)
