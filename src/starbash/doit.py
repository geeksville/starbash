from __future__ import annotations

import glob
import logging
import re
import shutil
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from doit.action import BaseAction, TaskFailed
from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.exceptions import BaseFail
from doit.reporter import ConsoleReporter
from doit.task import Task, dict_to_task
from toml_repo import Repo

from starbash import InputDef, events
from starbash.database import ImageRow
from starbash.doit_types import TaskDict
from starbash.exception import FilesystemUnavailableError, UserHandledError
from starbash.os import symlink_or_copy
from starbash.paths import get_user_cache_dir
from starbash.tool.base import Tool
from starbash.tool.context import expand_context_list
from starbash.url import make_file_url

if TYPE_CHECKING:
    from starbash.processing_like import ProcessingLike

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
    provenance: dict[str, int] | None = None  # Generated basename -> source image ID
    sequence_provenance: dict[str, list[int]] | None = None  # Sequence -> source IDs in order
    definition: InputDef | None = (
        None  # The input (or output) definition that produced this FileInfo
    )

    @property
    def rich_links(self) -> list[str]:
        """Get rich links for individual file paths from this FileInfo.

        Returns:
            List of rich link strings for individual files.
        """
        links = []
        if self.image_rows is not None:
            for img in self.image_rows:
                path = Path(img["abspath"])
                links.append(f"[link={make_file_url(path)}]{img['path']}[/link]")
        elif self.base is not None and self.full is not None:
            label = self.relative or self.full.name
            links.append(f"[link={make_file_url(self.full)}]{label}[/link]")
        return links

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
            return [Path(img["abspath"]) for img in self.image_rows]
        elif self.full is not None:
            return [self.full]
        else:
            return []


def doit_do_copy(task_dict: TaskDict) -> None:
    """Just add an action that copies files from file_dep to targets"""
    src = task_dict["file_dep"]
    dest = task_dict["targets"]

    assert len(src) >= 1, "doit_do_copy requires at least one source file"

    copy_actions = []
    for s, d in zip(src, dest, strict=True):
        tuple = (shutil.copy, [s, d])
        copy_actions.append(tuple)

    task_dict["actions"] = copy_actions


def add_action(task_dict: TaskDict, action: Callable) -> None:
    """Add an action to the task dictionary's actions list."""
    actions: list = task_dict.setdefault("actions", [])
    actions.append(action)


def cleanup_temporaries(stage: Any, context: dict[str, Any]) -> None:
    """Delete intermediate files/dirs declared by a stage's ``temporaries`` key.

    Each entry in ``temporaries`` is a glob pattern (e.g. ``"in*"``, ``"r_in*"``,
    ``"pp_{light_base}*"``). Patterns are expanded against the runtime ``context`` and
    matched against the top level of the stage's ``process_dir``. Both matching files
    and directories are removed. Runs regardless of whether the stage succeeded.

    Args:
        stage: The stage definition (dict-like) that ran, or None.
        context: The task's snapshot context (must contain ``process_dir``).
    """
    patterns: list[str] = stage.get("temporaries", []) if stage else []
    if not patterns:
        return

    process_dir = context.get("process_dir")
    if not process_dir:
        logging.warning("Cannot clean temporaries: no 'process_dir' in context")
        return

    base = Path(process_dir)
    for pattern in expand_context_list(patterns, context):
        p = pattern.strip()
        # Guard against patterns that would escape process_dir or match nothing sane.
        if not p or "/" in p or ".." in p or Path(p).is_absolute():
            logging.warning(f"Skipping unsafe 'temporaries' pattern: {pattern!r}")
            continue

        for match in glob.glob(str(base / p)):
            match_path = Path(match)
            try:
                if match_path.is_dir() and not match_path.is_symlink():
                    shutil.rmtree(match_path)
                else:
                    match_path.unlink()
                logging.debug(f"Removed temporary: {match_path}")
            except OSError as e:
                logging.warning(f"Failed to remove temporary {match_path}: {e}")


def doit_post_process(task_dict: TaskDict) -> None:
    """Do after execution processing

    * Populate master output files in the DB (FIXME I think we can remove this once doit dependencies fully linked)
    * Set result for this task (for later reporting)

    Note it publishes nothing and draws nothing: ``MyReporter`` reports the
    task's completion on the event bus (see doc/plans/cli-live-display.md).
    """

    def closure(targets: list) -> None:
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


def merge_to(base_name: str, fi: FileInfo) -> None:
    """Merge all input files in fi into a single sequence named base_name.

    This function collects all FITS files from the input FileInfo (including files from .seq sequences)
    and creates symlinks/copies with sequential names in a subdirectory like base_name/base_name_0001.fits,
    base_name/base_name_0002.fits, etc.

    Note: this function guarantees that the generated frames are sorted:
        * first by the sequence number
        * second by the order of frames in that sequence

    Args:
        base_name: The base name for the merged sequence (without extension)
        fi: FileInfo containing the input files to merge
    """
    assert fi.base, "FileInfo must have a base directory for merging"
    base_dir = Path(fi.base)
    collected_files: list[Path] = []
    provenance: dict[str, int] = {}

    # Iterate over short_paths to find all FITS files
    logging.debug(f"Merging files to {base_name} from {fi.short_paths}")
    for short_path in fi.short_paths:
        path = Path(short_path)

        # If it's a .seq file, find all FITS files with that prefix
        if path.suffix == ".seq":
            seq_prefix = path.stem
            pattern1 = str(base_dir / f"{seq_prefix}*.fit")
            pattern2 = str(base_dir / f"{seq_prefix}*.fits")
            matching_files = sorted(glob.glob(pattern1) + glob.glob(pattern2))
            source_ids = (fi.sequence_provenance or {}).get(path.name)
            if source_ids is None and path.name.endswith("_.seq"):
                source_ids = (fi.sequence_provenance or {}).get(f"{path.stem}.seq")
            resolved_source_ids: list[int] | None = None
            if source_ids is not None:
                if len(source_ids) == len(matching_files):
                    resolved_source_ids = source_ids
                else:
                    # A prior Siril stage can omit a frame while preserving
                    # the original numeric suffix. Recover the mapping by
                    # suffix rather than pairing the remaining files by order.
                    indexed_ids: list[int] = []
                    for matching_file in matching_files:
                        match = re.search(r"_(\d+)\.(?:fit|fits)$", matching_file)
                        if match is None:
                            indexed_ids = []
                            break
                        source_index = int(match.group(1))
                        if not 1 <= source_index <= len(source_ids):
                            indexed_ids = []
                            break
                        indexed_ids.append(source_ids[source_index - 1])
                    if len(indexed_ids) == len(matching_files) and len(set(indexed_ids)) == len(
                        indexed_ids
                    ):
                        resolved_source_ids = indexed_ids
                    else:
                        logging.warning(
                            "Skipping provenance for sequence %s: found %d files but "
                            "%d provenance records and suffix mapping failed",
                            path.name,
                            len(matching_files),
                            len(source_ids),
                        )

            if resolved_source_ids is not None:
                for matching_file, source_id in zip(
                    matching_files, resolved_source_ids, strict=True
                ):
                    source_path = Path(matching_file)
                    collected_files.append(source_path)
                    provenance[source_path.name] = source_id
            if resolved_source_ids is None:
                collected_files.extend([Path(f) for f in matching_files])

    # Create output directory and remove if it already exists
    output_dir = base_dir / base_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create symlinks/copies with sequential names in the subdirectory.  Every
    # input frame of the target is touched here, so it reports its own counts:
    # the core owns no display (see doc/plans/cli-live-display.md) -- the CLI's
    # run view points its bar at this phase from these events, the GUI ignores
    # them -- where the old `track()` bar drew on Rich's *global* console, i.e.
    # a second Live over the run view and an unrequested display in a GUI worker.
    total = len(collected_files)
    events.publish(events.EVENT_MERGE_PROGRESS, {"name": base_name, "done": 0, "total": total})
    for index, source_file in enumerate(collected_files, start=1):
        dest_name = f"{base_name}_{index:05d}.fits"
        dest_path = output_dir / dest_name
        # logging.debug(f"Linking {source_file} to {dest_path}")
        symlink_or_copy(str(source_file), str(dest_path))
        # One event per file would flood the bus on a large target (the reindex
        # scan reports every 25 for the same reason); always report the last one
        # so the phase is never left short of its total.
        if index % 25 == 0 or index == total:
            events.publish(
                events.EVENT_MERGE_PROGRESS,
                {"name": base_name, "done": index, "total": total},
            )
    events.publish(events.EVENT_MERGE_FINISHED, {"name": base_name, "files": total})

    merged_provenance = {
        f"{base_name}_{index:05d}.fits": provenance[source_file.name]
        for index, source_file in enumerate(collected_files, start=1)
        if source_file.name in provenance
    }
    fi.provenance = {**(fi.provenance or {}), **merged_provenance}
    fi.sequence_provenance = {
        **(fi.sequence_provenance or {}),
        f"{base_name}_.seq": list(merged_provenance.values()),
    }


def perhaps_merge_to(fi: FileInfo) -> None:
    input = fi.definition
    if input:
        merge: str | None = input.get("merge_to")
        if merge:
            merge_to(merge, fi)


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

    def execute(self, out: Any = None, err: Any = None) -> Any:
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
            # Some tools might want us to pre merge all the input frames (siril merge command doesn't nicely work with images
            # of different sizes etc).
            stage_input: dict[Any, FileInfo] = context["stage_input"]
            for fi in stage_input.values():
                perhaps_merge_to(fi)

            from starbash.processed_target import ProcessedTarget

            pt: ProcessedTarget = self.task.meta["processed_target"]
            logfile_path = pt.log_path

            with open(logfile_path, "a", encoding="utf-8") as logfile:
                self.result = self.tool.run(
                    self.commands, context=context, cwd=self.cwd, log_out=logfile, **self.parameters
                )
        except OSError as e:
            error = FilesystemUnavailableError(
                f"running {self.tool.name} for task '{self.task.name}'", e
            )
            logging.error("%s (%s)", error, e)
            self.task.meta["exception"] = error
            return TaskFailed(str(error))
        except FilesystemUnavailableError as e:
            logging.error("%s", e)
            self.task.meta["exception"] = e
            return TaskFailed(str(e))
        except Exception as e:
            # We pass back any exceptions in task.meta - so that our ConsoleReporter can pick them up (doit normally strips exceptions)
            self.task.meta["exception"] = e
            return TaskFailed("tool failed")
        finally:
            # Remove any intermediate files this stage declared as temporaries (success or failure).
            cleanup_temporaries(self.task.meta.get("stage"), context)

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
            elif isinstance(e, OSError):
                self.notes = (
                    "The filesystem became unavailable during processing. "
                    "Check that the drive or network mount is connected, then retry."
                )
                logging.error("Filesystem unavailable during processing: %s", e)
            else:
                # Unexpected exception - log it and re-raise
                logging.exception("Unexpected error during processing:")
                raise e


class MyReporter(ConsoleReporter):
    """A custom reporter that narrates a run on the event bus.

    It *publishes* -- per-task start/finish and the size of the run -- and owns
    no display at all: the CLI's ``ProcessingView`` and the GUI's task tree
    render from those events (see doc/plans/cli-live-display.md).
    """

    def __init__(self, outstream: Any, options: Any) -> None:
        super().__init__(outstream, options)
        self.processing: ProcessingLike | None = None

    @staticmethod
    def _task_labels(task: Task) -> dict[str, Any]:
        """Plain-data labels (target/stage/is_master) for a task's events."""
        meta = task.meta or {}
        stage = meta.get("stage") or {}
        pt = meta.get("processed_target")
        context = meta.get("context", {}) or {}

        # Prefer the model's run label so master (temp-dir) runs get the same
        # descriptive name the tree uses, and real targets keep their name.
        target = None
        run_label = getattr(pt, "run_label", None)
        if run_label is not None:
            try:
                target = run_label(context)
            except Exception:  # noqa: BLE001 - labels must never break a run
                target = None
        target = target or context.get("target")

        return {
            "target": target,
            "stage": stage.get("name") if hasattr(stage, "get") else None,
            "is_master": bool(meta.get("is_master", False)),
        }

    def execute_task(self, task: Task) -> None:
        """Called just before running a task"""
        # self.outstream.write("MyReporter --> %s\n" % task.title())

        # Update the target's live run state (best-effort; never break a run).
        pt = (task.meta or {}).get("processed_target")
        run_plain: dict[str, Any] | None = None
        if pt is not None:
            setter = getattr(self.processing, "set_active_target", None)
            if setter is not None:
                setter(pt)
            try:
                pt.task_started(task)
                # Publish the run *now*, with this task marked as running.  This is
                # the only snapshot that can contain a running node: the one sent
                # with a stage result is taken when the task has just finished, so
                # nothing is running at that instant -- which left the CLI's live
                # tree unable to show (or scroll to) the task being worked on.
                tree = pt.run_tree()
                run_plain = tree.to_plain() if tree is not None else None
            except Exception as e:  # noqa: BLE001
                logging.debug(f"run-state task_started failed: {e}")

        # Note: the progress *bar* is no longer labelled here.  It only ever
        # relabelled a caller-owned bar that the core no longer has, and every
        # front end already names the running task from this very event -- the
        # CLI's live status line ("stack: Stack lights", built by
        # ProcessingView._task_caption) and the GUI's caption/tree row.
        events.publish(
            events.EVENT_TASK_STARTED,
            {
                "task": task.name,
                "title": task.title(),
                "run": run_plain,
                **self._task_labels(task),
            },
        )

    def _handle_completion(
        self,
        task: Task,
        fail: BaseFail | None = None,
        reason: str | None = None,
        success: bool | None = True,
    ) -> None:
        # We made progress - call once per iteration ;-)

        if self.processing and task.meta:
            result = ProcessingResult(task=task, reason=reason, success=success)
            e = task.meta.get("exception")  # try to pass our raw exception if possible

            result.notes = task.name  # default nodes just show the task name
            result.update(e or fail)
            self.processing.add_result(result)

        # Report completion to any observers (e.g. the GUI task tree).  This is
        # outside the `if self.processing` guard so standalone doit runs report too.
        events.publish(
            events.EVENT_TASK_FINISHED,
            {
                "task": task.name,
                "title": task.title(),
                "success": success,
                "reason": reason,
                **self._task_labels(task),
            },
        )

    def skip_uptodate(self, task: Task) -> None:
        """skipped up-to-date task"""
        self._handle_completion(task, reason="Current", success=None)

    def skip_ignore(self, task: Task) -> None:
        """skipped ignored task"""
        self._handle_completion(task, reason="Ignored", success=None)

    def add_success(self, task: Task) -> None:
        """called when execution finishes successfully (either this or add_failure is guaranteed to be called)"""
        super().add_success(task)
        self._handle_completion(task)

    def add_failure(self, task: Task, fail: BaseFail) -> None:
        """called when execution finishes with a failure"""
        super().add_failure(task, fail)
        self._handle_completion(task, fail)

    def initialize(self, tasks: OrderedDict[str, Task], selected_tasks: list[str]) -> None:
        """called just after tasks have been loaded before execution starts

        tasks will be the full list of tasks we might run
        """
        super().initialize(tasks, selected_tasks)

        if len(tasks) > 0:
            # Tell observers how big this run is.  Every task in this list ends
            # with exactly one EVENT_TASK_FINISHED -- a task that was already up
            # to date, or ignored, reports through skip_uptodate/skip_ignore --
            # so this is the denominator a live progress bar needs.  Nothing
            # draws here: the core owns no display (see doc/plans/cli-live-display.md).
            events.publish(events.EVENT_TASKS_PLANNED, {"tasks": len(tasks)})

            first = next(
                iter(tasks.values())
            )  # All tasks we add are required to have meta.processing

            self.processing = first.meta and first.meta["processing"]


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

    def setup(self, opt_values: Any) -> None:
        """Required by baseclass"""
        pass

    def load_doit_config(self) -> dict[str, Any]:
        """Required by baseclass"""
        # Store the doit database in the user's cache directory instead of the workspace
        cache_dir = get_user_cache_dir()
        dep_file = str(cache_dir / "doit.db")
        return {
            "verbosity": 2,
            "dep_file": dep_file,
            "reporter": MyReporter,
            "backend": "dbm",  # the json backend is slow and buggy, use dbm instead
        }

    def load_tasks(self, cmd: Any, pos_args: Any) -> list[Task]:
        """Load tasks for Starbash. (required by baseclass)

        Args:
            cmd: The command object.
            pos_args: The positional arguments.

        Returns:
            A list of tasks.
        """
        task_list = [dict_to_task(t) for t in self.dicts.values()]
        return task_list
