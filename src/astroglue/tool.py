import os
import shutil
import textwrap
import tempfile
import subprocess
import re

import logging

logger = logging.getLogger(__name__)


def strip_comments(text: str) -> str:
    """Removes comments from a string.

    This function removes both full-line comments (lines starting with '#')
    and inline comments (text after '#' on a line).
    """
    lines = []
    for line in text.splitlines():
        lines.append(line.split("#", 1)[0].rstrip())
    return "\n".join(lines)


def tool_run(cmd: str, cwd: str, commands: str | None = None) -> None:
    """Executes an external tool with an optional script of commands in a given working directory."""

    logger.debug(f"Running {cmd} in {cwd}: stdin={commands}")
    result = subprocess.run(
        cmd, input=commands, shell=True, capture_output=True, text=True, cwd=cwd
    )

    if result.stdout:
        logger.info(f"Tool output:\n")
        for line in result.stdout.splitlines():
            logger.info(line)

    if result.stderr:
        logger.warning(f"Tool error message:")
        for line in result.stderr.splitlines():
            logger.warning(line)

    if result.returncode != 0:
        logger.error(f"Tool failed with exit code {result.returncode}!")
        result.check_returncode()  # Child process returned an error code
    else:
        logger.info("Tool command successful.")


# siril_path = "/home/kevinh/packages/Siril-1.4.0~beta3-x86_64.AppImage"
siril_path = "org.siril.Siril"  # flatpak


def siril_run(temp_dir: str, commands: str, input_files: list[str] = []) -> None:
    """Executes Siril with a script of commands in a given working directory."""

    # Create symbolic links for all input files in the temp directory
    for f in input_files:
        os.symlink(
            os.path.abspath(str(f)), os.path.join(temp_dir, os.path.basename(str(f)))
        )

    # Run Siril commands in the temporary directory
    logger.info(f"Running Siril in temporary directory: {temp_dir}, cmds {commands}")

    # We dedent here because the commands are often indented multiline strings
    script_content = textwrap.dedent(
        f"""
        requires 1.4.0-beta3
        {textwrap.dedent(strip_comments(commands))}
        """
    )

    # The `-s -` arguments tell Siril to run in script mode and read commands from stdin.
    # It seems like the -d command may also be required when siril is in a flatpak
    cmd = f"{siril_path} -d {temp_dir} -s -"

    tool_run(cmd, temp_dir, script_content)


def graxpert_run(cwd: str, arguments: str) -> None:
    """Executes Graxpert with the specified command line arguments"""

    # Arguments look similar to: graxpert -cmd background-extraction -output /tmp/testout tests/test_images/real_crummy.fits
    cmd = f"graxpert {arguments}"

    tool_run(cmd, cwd)


class _SafeFormatter(dict):
    """A dictionary for safe string formatting that ignores missing keys during expansion."""

    def __missing__(self, key):
        return "{" + key + "}"


def expand_context(s: str, context: dict) -> str:
    """Expand any named variables in the provided string"""
    # Iteratively expand the command string to handle nested placeholders.
    # The loop continues until the string no longer changes.
    expanded = s
    previous = None
    max_iterations = 10  # Safety break for infinite recursion
    for i in range(max_iterations):
        if expanded == previous:
            break  # Expansion is complete
        previous = expanded
        expanded = expanded.format_map(_SafeFormatter(context))
    else:
        logger.warning(
            f"Template expansion reached max iterations ({max_iterations}). Possible recursive definition in '{commands}'."
        )

    logger.info(f"Expanded '{s}' into '{expanded}'")

    # throw an error if any remaining unexpanded variables remain unexpanded
    unexpanded_vars = re.findall(r"\{([^{}]+)\}", expanded)
    if unexpanded_vars:
        raise KeyError("Missing context variable(s): " + ", ".join(unexpanded_vars))

    return expanded


class Tool:
    """A tool for stage execution"""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(
        self, commands: str, context: dict = {}, input_files: list[str] = []
    ) -> None:
        """Run commands inside this tool (with cwd pointing to a temp directory)"""
        # Create a temporary directory for processing
        temp_dir = tempfile.mkdtemp(prefix=self.name)

        context["temp_dir"] = (
            temp_dir  # pass our directory path in for the tool's usage
        )

        # Iteratively expand the command string to handle nested placeholders.
        # The loop continues until the string no longer changes.
        expanded = expand_context(commands, context)

        try:
            self._run(temp_dir, expanded, input_files)
        finally:
            shutil.rmtree(temp_dir)

    def _run(self, cwd: str, commands: str, input_files: list[str] = []) -> None:
        raise NotImplementedError()


class SirilTool(Tool):
    """Expose Siril as a tool"""

    def __init__(self) -> None:
        super().__init__("siril")

    def _run(self, cwd: str, commands: str, input_files: list[str] = []) -> None:
        siril_run(cwd, commands, input_files)


class GraxpertTool(Tool):
    """Expose Graxpert as a tool"""

    def __init__(self) -> None:
        super().__init__("graxpert")

    def _run(self, cwd: str, commands: str, input_files: list[str] = []) -> None:
        graxpert_run(cwd, commands)


class PythonTool(Tool):
    """Expose Python as a tool

    FIXME Caution currently this runs unvalidated python code - the script can do anything
    """

    def __init__(self) -> None:
        super().__init__("python")


# A dictionary mapping tool names to their respective tool instances.
tools = {tool.name: tool for tool in [SirilTool(), GraxpertTool(), PythonTool()]}
