"""Siril tool integration."""

import io
import logging
import os
import textwrap
from pathlib import Path

from rich.progress import track

from starbash.os import symlink_or_copy
from starbash.tool.base import ExternalTool, tool_run
from starbash.tool.context import expand_context_unsafe, strip_comments

logger = logging.getLogger(__name__)

__all__ = ["SirilTool"]


def link_or_copy_to_dir(input_files: list[Path], dest_dir: str):
    """Create symbolic links or copies of input files in the given directory."""

    from starbash.os import symlinks_supported

    description = (
        "Linking input files..."
        if symlinks_supported
        else "Copying input files (fix your OS settings!)..."
    )

    for f in track(input_files, description=description, transient=True):
        dest_file = os.path.join(dest_dir, os.path.basename(str(f)))

        # if a script is re-run we might already have the input file symlinks
        if not os.path.exists(dest_file):
            symlink_or_copy(str(f), dest_file)


class SirilTool(ExternalTool):
    """Expose Siril as a tool"""

    def __init__(self) -> None:
        # siril_path = "/home/kevinh/packages/Siril-1.4.0~beta3-x86_64.AppImage"
        # Possible siril commands, with preferred option first
        commands: list[str] = [
            "siril-cli",
            "siril",
            "org.siril.Siril",
            "Siril",
        ]

        super().__init__("Siril", commands, "https://siril.org/")

    def _run(
        self, cwd: str, commands: str, context: dict = {}, log_out: io.TextIOWrapper | None = None
    ) -> None:
        """Executes Siril with a script of commands in a given working directory."""

        # Iteratively expand the command string to handle nested placeholders.
        # The loop continues until the string no longer changes.
        expanded = expand_context_unsafe(commands, context)

        input_files: list[Path] = context.get("input_files", [])

        temp_dir = cwd

        siril_path = self.executable_path
        if siril_path == "org.siril.Siril":
            siril_path = "flatpak run org.siril.Siril"

        link_or_copy_to_dir(input_files, temp_dir)

        # We dedent here because the commands are often indented multiline strings
        script_content = textwrap.dedent(
            f"""
            requires 1.4.0-beta3
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
