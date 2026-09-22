"""Siril tool integration."""

import io
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from starbash import events
from starbash.os import symlink_or_copy
from starbash.tool.base import ExternalTool, ToolSeverity, tool_run
from starbash.tool.context import expand_context_unsafe, strip_comments

logger = logging.getLogger(__name__)

__all__ = ["SirilTool", "SIRIL_INSTALL_URL"]

#: Where the user can download Siril.
SIRIL_INSTALL_URL = "https://siril.org/"


def link_or_copy_to_dir(input_files: list[Path], dest_dir: str) -> None:
    """Create symbolic links or copies of input files in the given directory.

    This runs *inside* a processing run, so it reports through the event bus
    rather than drawing: a ``rich.progress.track()`` here builds its own
    ``Console`` on stdout, which paints a second bar over the CLI's one live
    display and writes to stdout from a GUI worker.  The CLI's bar has a
    "Collecting inputs" phase for these counts (the same phase
    ``doit.merge_to()`` feeds, as both collect a stage's inputs) -- see
    doc/plans/cli-live-display.md.
    """

    from starbash.os import symlinks_supported

    if not symlinks_supported:
        # This used to be the bar's description; a log line is where a user can
        # still read it, and it is the only hint why the run is slower than it
        # needs to be.
        logger.info(
            "Copying input files (symbolic links are unavailable here, fix your OS settings)"
        )

    # Name the phase after the directory being filled, so a new stage's collection
    # restarts the bar instead of extending the previous one.
    name = Path(dest_dir).name or str(dest_dir)
    total = len(input_files)
    events.publish(events.EVENT_MERGE_PROGRESS, {"name": name, "done": 0, "total": total})
    for index, f in enumerate(input_files, start=1):
        dest_file = os.path.join(dest_dir, os.path.basename(str(f)))

        # if a script is re-run we might already have the input file symlinks
        if not os.path.exists(dest_file):
            symlink_or_copy(str(f), dest_file)

        # A target is thousands of frames, so report every 25th -- plus the last,
        # so the phase always reaches its total (the reindex scan does the same).
        if index % 25 == 0 or index == total:
            events.publish(
                events.EVENT_MERGE_PROGRESS, {"name": name, "done": index, "total": total}
            )
    events.publish(events.EVENT_MERGE_FINISHED, {"name": name, "files": total})


class SirilTool(ExternalTool):
    """Expose Siril as a tool"""

    def __init__(self) -> None:
        # siril_path = "/home/kevinh/packages/Siril-1.4.0~beta3-x86_64.AppImage"
        # Possible siril commands, with preferred option first
        commands: list[str] = [
            "siril-cli",  # We prefer the top two options because they work even without a Gtk accessible GUI
            "org.siril.Siril",
            "siril",
            "Siril",
        ]
        if sys.platform == "win32":
            commands.append(r"C:\Program Files\Siril\bin\siril.exe")

        super().__init__(
            "Siril",
            commands,
            SIRIL_INSTALL_URL,
            # Siril is required: virtually every calibration/stacking recipe
            # runs through it, so a missing Siril must be loud.
            severity=ToolSeverity.REQUIRED,
        )

    """Siril can run for a long time on big jobs."""

    def set_defaults(self) -> None:
        super().set_defaults()
        self.timeout = (
            8 * 60 * 60.0  # 8 hours - Big Siril jobs can take a LONG time
        )

    def _run(
        self,
        cwd: str,
        commands: str | list[str],
        context: dict = {},
        log_out: io.TextIOWrapper | None = None,
        **kwargs: Any,
    ) -> None:
        """Executes Siril with a script of commands in a given working directory."""

        assert isinstance(commands, str), "Siril tool requires commands as a string, not a list"
        # Iteratively expand the command string to handle nested placeholders.
        # The loop continues until the string no longer changes.
        expanded = expand_context_unsafe(commands, context)

        input_files: list[Path] = context.get("input_files", [])

        temp_dir = cwd

        siril_path = self.executable_path
        if siril_path == "org.siril.Siril":
            siril_path = "flatpak run --command=siril-cli org.siril.Siril"

        link_or_copy_to_dir(input_files, temp_dir)

        # We dedent here because the commands are often indented multiline strings
        script_content = textwrap.dedent(
            f"""
            requires 1.4.0 1.5.0
            {textwrap.dedent(strip_comments(expanded))}
            """
        )

        logger.debug(
            f"Running Siril in {temp_dir}, ({len(input_files)} input files) cmds:\n{script_content}"
        )
        logger.debug(f"Running Siril ({len(input_files)} input files)")

        # The `-s -` arguments tell Siril to run in script mode and read commands from stdin.
        # It seems like the -d command may also be required when siril is in a flatpak
        cmd = f"{siril_path} -d {temp_dir} -s -"

        tool_run(cmd, temp_dir, script_content, timeout=self.timeout, log_out=log_out)
