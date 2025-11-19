"""Classic processing implementation for starbash."""

import glob
import itertools
import logging
import os
import shutil
import textwrap
from pathlib import Path
from typing import Any

from rich.progress import track

import starbash
from repo import Repo
from starbash.aliases import get_aliases
from starbash.app import Starbash
from starbash.database import (
    Database,
    SessionRow,
    get_column_name,
)
from starbash.processed_target import ProcessedTarget
from starbash.processing import (
    Processing,
    ProcessingContext,
    ProcessingResult,
    update_processing_result,
)
from starbash.score import score_candidates
from starbash.tool import expand_context_unsafe, tools


class ProcessingClassic(Processing):
    """Does all heavyweight processing operations for starbash"""

    def __init__(self, sb: Starbash) -> None:
        super().__init__(sb)

        self.sessions: list[SessionRow] = []  # The list of sessions we are currently processing
        self.recipe: Repo | None = None  # the recipe we are using for processing

    def __enter__(self) -> "ProcessingClassic":
        return self

    def _get_stages(self, name: str) -> list[dict[str, Any]]:
        """Get all pipeline stages defined in the merged configuration.

        Returns:
            List of stage definitions (dictionaries with 'name' and 'priority')
        """
        # 1. Get all pipeline definitions (the `[[stages]]` tables with name and priority).
        pipeline_definitions = self.sb.repo_manager.merged.getall(name)
        flat_pipeline_steps = list(itertools.chain.from_iterable(pipeline_definitions))

        # 2. Sort the pipeline steps by their 'priority' field.
        try:
            sorted_pipeline = sorted(flat_pipeline_steps, key=lambda s: s["priority"])
        except KeyError as e:
            # Re-raise as a ValueError with a more descriptive message.
            raise ValueError(
                "invalid stage definition: a stage is missing the required 'priority' key"
            ) from e

        logging.debug(f"Found {len(sorted_pipeline)} pipeline steps to run in order of priority.")
        return sorted_pipeline

    def run_pipeline_step(self, step_name: str):
        logging.info(f"--- Running pipeline step: '{step_name}' ---")

        # 3. Get all available task definitions (the `[[stage]]` tables with tool, script, when).
        task_definitions = self.sb.repo_manager.merged.getall("stage")
        all_tasks = list(itertools.chain.from_iterable(task_definitions))

        # Find all tasks that should run during this pipeline step.
        tasks_to_run = [task for task in all_tasks if task.get("when") == step_name]
        for task in tasks_to_run:
            self.run_stage(task)

    def _process_target(self, target: str) -> ProcessingResult:
        """Do processing for a particular target (i.e. all sessions for a particular object)."""

        pipeline = self._get_stages("stages")

        lights_step = pipeline[
            0
        ]  # FIXME super nasty - we assume the array is exactly these two elements
        stack_step = pipeline[1]
        task_exception: Exception | None = None

        result = ProcessingResult(target=target, sessions=self.sessions)
        try:
            # target specific processing here

            # we find our recipe while processing our first light frame session
            recipe = None

            # process all light frames
            step = lights_step
            lights_task = self.progress.add_task("Processing session...", total=len(self.sessions))
            try:
                lights_processed = False  # for better reporting
                stack_processed = False

                for session in self.sessions:
                    step_name = step["name"]
                    if not recipe:
                        # for the time being: The first step in the pipeline MUST be "light"
                        recipe = self.get_recipe_for_session(session, step)
                        if not recipe:
                            continue  # No recipe found for this target/session

                        self.recipe = recipe
                        self.recipes_considered = [
                            recipe
                        ]  # FIXME: we should let the user pick if needed

                    # find the task for this step
                    task = None
                    if recipe:
                        task = recipe.get("recipe.stage." + step_name)

                    if task:
                        # put all relevant session info into context
                        self._set_session_in_context(session)

                        # The following operation might take a long time, so give the user some more info...
                        self.progress.update(
                            lights_task,
                            description=f"Processing {step_name} {self.context['date']}...",
                        )
                        try:
                            self.run_stage(task)
                            lights_processed = True
                        except NotEnoughFilesError:
                            logging.warning(
                                "Skipping session, siril requires at least two frames per session..."
                            )

                    # We made progress - call once per iteration ;-)
                    self.progress.advance(lights_task)
            finally:
                self.progress.remove_task(lights_task)

            # after all light frames are processed, do the stacking
            step = stack_step
            if recipe:
                task = recipe.get("recipe.stage." + step["name"])

                if task:
                    #
                    # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                    # dirs for particular targets?
                    try:
                        self.run_stage(task)

                        # FIXME create this earlier - but for now I want to assume the output
                        # path is correct.
                        processed_target = ProcessedTarget(self)
                        processed_target.close()
                        stack_processed = True
                    except NotEnoughFilesError:
                        logging.warning(
                            "Skipping stacking, siril requires at least two frames per session..."
                        )

            # Success!  we processed all lights and did a stack (probably)
            if not lights_processed:
                result.notes = "Skipped, no suitable recipe found for light frames..."
            elif not stack_processed:
                result.notes = "Skipped, no suitable recipe found for stacking..."
            else:
                update_processing_result(result)
        except Exception as e:
            task_exception = e
            update_processing_result(result, task_exception)

        return result

    def run_master_stages(self) -> list[ProcessingResult]:
        """Generate any missing master frames

        Steps:
        * loop across all pipeline stages, first bias, then dark, then flat, etc...  Very important that bias is before flat.
        * set all_tasks to be all tasks for when == "setup.master.bias"
        * loop over all currently unfiltered sessions
        * if task input.type == the imagetyp for this current session
        *    add_input_to_context() add the input files to the context (from the session)
        *    run_stage(task) to generate the new master frame
        """
        sorted_pipeline = self._get_stages("master-stages")
        sessions = self.sb.search_session([])  # for masters we always search everything
        results: list[ProcessingResult] = []

        # we loop over pipeline steps in the
        for step in sorted_pipeline:
            step_name = step.get("name")
            if not step_name:
                raise ValueError("Invalid pipeline step found: missing 'name' key.")
            for session in track(sessions, description=f"Processing {step_name} for sessions..."):
                task = None
                recipe = self.get_recipe_for_session(session, step)
                if recipe:
                    task = recipe.get("recipe.stage." + step_name)

                processing_exception: Exception | None = None
                if task:
                    try:
                        # Create a default process dir in /tmp.
                        # FIXME - eventually we should allow hashing or somesuch to keep reusing processing
                        # dirs for particular targets?
                        with ProcessingContext(self):
                            self._set_session_in_context(session)

                            # we want to allow already processed masters from other apps to be imported
                            self.run_stage(task, processed_ok=True)
                    except Exception as e:
                        processing_exception = e

                    # for user feedback we try to tell the name of the master we made
                    target = step_name
                    if self.context.get("output"):
                        output_path = self.context.get("output", {}).get("relative_base_path")
                        if output_path:
                            target = str(output_path)
                    result = ProcessingResult(target=target, sessions=[session])

                    # We did one processing run. add the results
                    update_processing_result(result, processing_exception)

                    # if we skipped leave the result as skipped
                    results.append(result)

        return results

    def get_recipe_for_session(self, session: SessionRow, step: dict[str, Any]) -> Repo | None:
        """Try to find a recipe that can be used to process the given session for the given step name
        (master-dark, master-bias, light, stack, etc...)

        * if a recipe doesn't have a matching recipe.stage.<step_name> it is not considered
        * As part of this checking we will look at recipe.auto.require.* conditions to see if the recipe
        is suitable for this session.
        * the imagetyp of this session matches step.input

        Currently we return just one Repo but eventually we should support multiple matching recipes
        and make the user pick (by throwing an exception?).
        """
        # Get all recipe repos - FIXME add a getall(kind) to RepoManager
        recipe_repos = self.sb.get_recipes()

        step_name = step.get("name")
        if not step_name:
            raise ValueError("Invalid pipeline step found: missing 'name' key.")

        input_name = step.get("input")
        if not input_name:
            raise ValueError("Invalid pipeline step found: missing 'input' key.")

        # if input type is recipe we don't check for filetype match - because we'll just use files already in
        # the tempdir
        if input_name != "recipe":
            imagetyp = session.get(get_column_name(Database.IMAGETYP_KEY))

            if not imagetyp or input_name != get_aliases().normalize(imagetyp):
                logging.debug(
                    f"Session imagetyp '{imagetyp}' does not match step input '{input_name}', skipping"
                )
                return None

        # Get session metadata for checking requirements
        session_metadata = session.get("metadata", {})

        for repo in recipe_repos:
            # Check if this recipe has the requested stage
            stage_config = repo.get(f"recipe.stage.{step_name}")
            if not stage_config:
                logging.debug(f"Recipe {repo.url} does not have stage '{step_name}', skipping")
                continue

            # Check auto.require conditions if they exist

            # If requirements are specified, check if session matches
            required_filters = repo.get("recipe.auto.require.filter", [])
            if required_filters:
                session_filter = get_aliases().normalize(
                    session_metadata.get(Database.FILTER_KEY), lenient=True
                )

                # Session must have AT LEAST one filter that matches one of the required filters
                if not session_filter or session_filter not in required_filters:
                    logging.debug(
                        f"Recipe {repo.url} requires filters {required_filters}, "
                        f"session has '{session_filter}', skipping"
                    )
                    continue

            required_color = repo.get("recipe.auto.require.color", False)
            if required_color:
                session_bayer = session_metadata.get("BAYERPAT")

                # Session must be color (i.e. have a BAYERPAT header)
                if not session_bayer:
                    logging.debug(
                        f"Recipe {repo.url} requires a color camera, "
                        f"but session has no BAYERPAT header, skipping"
                    )
                    continue

            required_cameras = repo.get("recipe.auto.require.camera", [])
            if required_cameras:
                session_camera = get_aliases().normalize(
                    session_metadata.get(Database.INSTRUME_KEY), lenient=True
                )  # Camera identifier

                # Session must have a camera that matches one of the required cameras
                if not session_camera or session_camera not in required_cameras:
                    logging.debug(
                        f"Recipe {repo.url} requires cameras {required_cameras}, "
                        f"session has '{session_camera}', skipping"
                    )
                    continue

            # This recipe matches!
            logging.info(f"Selected recipe {repo.url} for stage '{step_name}' ")
            return repo

        # No matching recipe found
        return None

    def add_input_masters(self, stage: dict) -> None:
        """based on input.masters add the correct master frames as context.master.<type> filepaths"""
        session = self.context.get("session")
        assert session is not None, "context.session should have been already set"

        input_config = stage.get("input", {})
        master_types: list[str] = input_config.get("masters", [])
        for master_type in master_types:
            masters = self.sb.get_master_images(imagetyp=master_type, reference_session=session)
            if not masters:
                raise RuntimeError(
                    f"No master frames of type '{master_type}' found for stage '{stage.get('name')}'"
                )

            context_master = self.context.setdefault("master", {})

            # Try to rank the images by desirability
            scored_masters = score_candidates(masters, session)
            session_masters = session.setdefault("masters", {})
            session_masters[master_type] = scored_masters  # for reporting purposes

            if len(scored_masters) == 0:
                raise RuntimeError(f"No suitable master frames of type '{master_type}' found.")

            self.sb._add_image_abspath(
                scored_masters[0].candidate
            )  # make sure abspath is populated, we need it

            selected_master = scored_masters[0].candidate["abspath"]
            logging.info(
                f"For master '{master_type}', using: {selected_master} (score={scored_masters[0].score:.1f}, {scored_masters[0].reason})"
            )

            context_master[master_type] = selected_master

    def add_input_files(self, stage: dict, processed_ok: bool = False) -> None:
        """adds to context.input_files based on the stage input config"""
        input_config = stage.get("input")
        input_required = 0
        if input_config:
            # if there is an "input" dict, we assume input.required is true if unset
            input_required = input_config.get("required", 0)
            source = input_config.get("source")
            if source is None:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' configuration: missing 'source'"
                )
            if source == "path":
                # The path might contain context variables that need to be expanded.
                # path_pattern = expand_context(input_config["path"], context)
                path_pattern = input_config["path"]
                input_files = glob.glob(path_pattern, recursive=True)

                self.context["input_files"] = (
                    input_files  # Pass in the file list via the context dict
                )
            elif source == "repo":
                # Get images for this session (by pulling from repo)
                session = self.context.get("session")
                assert session is not None, "context.session should have been already set"

                # if session["id"] == 10:
                #    logging.warning("debugging session 10")

                images = self.sb.get_session_images(session, processed_ok=processed_ok)
                logging.debug(f"Using {len(images)} files as input_files")
                self.context["input_files"] = [
                    img["abspath"] for img in images
                ]  # Pass in the file list via the context dict
            elif source == "recipe":
                # The input files are already in the tempdir from the recipe processing
                # therefore we don't need to do anything here
                pass
            else:
                raise ValueError(
                    f"Stage '{stage.get('name')}' has invalid 'input' source: {source}"
                )

            # FIXME compare context.output to see if it already exists and is newer than the input files, if so skip processing
        else:
            # The script doesn't mention input, therefore assume it doesn't want input_files
            if "input_files" in self.context:
                del self.context["input_files"]

        input_files: list[str] = self.context.get("input_files", [])
        if input_required:
            if len(input_files) < input_required:
                raise NotEnoughFilesError(
                    f"Stage requires >{input_required} input files ({len(input_files)} found)",
                    input_files,
                )

    def add_output_path(self, stage: dict) -> None:
        """Adds output path information to context based on the stage output config.

        If the output dest is 'repo', it finds the appropriate repository and constructs
        the full output path based on the repository's base path and relative path expression.

        Sets the following context variables:
        - context.output.root_path - base path of the destination repo
        - context.output.base_path - full path without file extension
        - context.output.suffix - file extension (e.g., .fits or .fit.gz)
        - context.output.full_path - complete output file path
        - context.output.repo - the destination Repo (if applicable)
        """
        output_config = stage.get("output")
        if not output_config:
            # No output configuration, remove any existing output from context
            if "output" in self.context:
                del self.context["output"]
            return

        dest = output_config.get("dest")
        if not dest:
            raise ValueError(
                f"Stage '{stage.get('description', 'unknown')}' has 'output' config but missing 'dest'"
            )

        if dest == "repo":
            # Find the destination repo by type/kind
            output_type = output_config.get("type")
            if not output_type:
                raise ValueError(
                    f"Stage '{stage.get('description', 'unknown')}' has output.dest='repo' but missing 'type'"
                )

            # Find the repo with matching kind
            dest_repo = self.sb.repo_manager.get_repo_by_kind(output_type)
            if not dest_repo:
                raise ValueError(
                    f"No repository found with kind '{output_type}' for output destination"
                )

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
            self.context["output"] = {
                # "root_path": repo_relative, not needed I think
                "base_path": base_path,
                # "suffix": full_path.suffix, not needed I think
                "full_path": full_path,
                "relative_base_path": repo_relative,
                "repo": dest_repo,
            }
        else:
            raise ValueError(
                f"Unsupported output destination type: {dest}. Only 'repo' is currently supported."
            )

    def expand_to_context(self, to_add: dict[str, Any]):
        """Expands any string values in to_add using the current context and updates the context.

        This allows scripts to add new context variables - with general python expressions inside
        """
        for key, value in to_add.items():
            if isinstance(value, str):
                expanded_value = expand_context_unsafe(value, self.context)
                self.context[key] = expanded_value
            else:
                self.context[key] = value

    def run_stage(self, stage: dict, processed_ok: bool = False) -> None:
        """
        Executes a single processing stage.

        Args:
            stage: A dictionary representing the stage configuration, containing
                   at least 'tool' and 'script' keys.
        """
        stage_desc = stage.get("description", "(missing description)")
        stage_disabled = stage.get("disabled", False)
        if stage_disabled:
            logging.info(f"Skipping disabled stage: {stage_desc}")
            return

        logging.info(f"Running stage: {stage_desc}")

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
        script = stage.get("script")
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

        # This allows recipe TOML to define their own default variables.
        # (apply all of the changes to context that the task demands)
        stage_context = stage.get("context", {})
        self.expand_to_context(stage_context)
        self.add_output_path(stage)

        output_info: dict | None = self.context.get("output")
        try:
            self.add_input_files(stage, processed_ok=processed_ok)
            self.add_input_masters(stage)

            # if the output path already exists and is newer than all input files, skip processing
            if output_info and not starbash.force_regen:
                output_path = output_info.get("full_path")
                if output_path:
                    # output_path might contain * wildcards, make output_files be a list
                    output_files = glob.glob(str(output_path))
                    if len(output_files) > 0:
                        logging.info(
                            f"Output file already exists, skipping processing: {output_path}"
                        )
                        return

            # We normally run tools in a temp dir, but if input.source is recipe we assume we want to
            # run in the shared processing directory.  Because prior stages output files are waiting for us there.
            cwd = None
            if stage.get("input", {}).get("source") == "recipe":
                cwd = self.context.get("process_dir")

            tool.run(script, context=self.context, cwd=cwd)
        except NotEnoughFilesError as e:
            # Not enough input files provided
            input_files = e.files
            if len(input_files) != 1:
                raise  # We only handle the single file case here

            # Copy the single input file to the output path
            output_path = self.context.get("output", {}).get("full_path")
            if output_path:
                shutil.copy(input_files[0], output_path)
                logging.warning(f"Copied single master from {input_files[0]} to {output_path}")
            else:
                # no output path specified, re-raise
                raise

        # verify context.output was created if it was specified
        if output_info:
            output_path = output_info[
                "full_path"
            ]  # This must be present, because we created it when we made the output node

            # output_path might contain * wildcards, make output_files be a list
            output_files = glob.glob(str(output_path))

            if len(output_files) < 1:
                raise RuntimeError(f"Expected output file not found: {output_path}")
            else:
                if output_info["repo"].kind() == "master":
                    # we add new masters to our image DB
                    # add to image DB (ONLY! we don't also create a session)

                    # The generated files might not have propagated all of the metadata (because we added it after FITS import)
                    extra_metadata = self.context.get("session", {}).get("metadata", {})
                    self.sb.add_image(
                        output_info["repo"],
                        Path(output_path),
                        force=True,
                        extra_metadata=extra_metadata,
                    )
