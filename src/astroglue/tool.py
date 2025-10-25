import os
import shutil
import textwrap
import tempfile
import subprocess
import re

import logging

from RestrictedPython import compile_restricted
from RestrictedPython.Guards import safe_builtins

logger = logging.getLogger(__name__)


class _SafeFormatter(dict):
    """A dictionary for safe string formatting that ignores missing keys during expansion."""

    def __missing__(self, key):
        return "{" + key + "}"


def expand_context(s: str, context: dict) -> str:
    """Expand any named variables in the provided string

    Will expand strings of the form MyStr{somevar}a{someothervar} using vars listed in context.
    Guaranteed safe, doesn't run any python scripts.
    """
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
            f"Template expansion reached max iterations ({max_iterations}). Possible recursive definition in '{s}'."
        )

    logger.info(f"Expanded '{s}' into '{expanded}'")

    # throw an error if any remaining unexpanded variables remain unexpanded
    unexpanded_vars = re.findall(r"\{([^{}]+)\}", expanded)
    if unexpanded_vars:
        raise KeyError("Missing context variable(s): " + ", ".join(unexpanded_vars))

    return expanded


def make_safe_globals(context: dict = {}) -> dict:
    """Generate a set of RestrictedPython globals for AstoGlue exec/eval usage"""
    # Define the global and local namespaces for the restricted execution.
    # FIXME - this is still unsafe, policies need to be added to limit import/getattr etc...
    # see https://restrictedpython.readthedocs.io/en/latest/usage/policy.html#implementing-a-policy
    execution_globals = {
        "__builtins__": safe_builtins,
        "context": context,
        "logger": logging.getLogger("script"),  # Allow logging within the script
    }
    return execution_globals


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
        logger.debug(f"Tool output:\n")
        for line in result.stdout.splitlines():
            logger.debug(line)

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


class Tool:
    """A tool for stage execution"""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, commands: str, context: dict = {}) -> None:
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
            self._run(temp_dir, expanded, context=context)
        finally:
            shutil.rmtree(temp_dir)

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        raise NotImplementedError()


class SirilTool(Tool):
    """Expose Siril as a tool"""

    def __init__(self) -> None:
        super().__init__("siril")

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        input_files = context.get("input_files", [])
        siril_run(cwd, commands, input_files)


class GraxpertTool(Tool):
    """Expose Graxpert as a tool"""

    def __init__(self) -> None:
        super().__init__("graxpert")

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        graxpert_run(cwd, commands)


class PythonTool(Tool):
    """Expose Python as a tool"""

    def __init__(self) -> None:
        super().__init__("python")

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(cwd)  # cd to where this script expects to run

            logger.info(f"Executing python script in {cwd} using RestrictedPython")
            try:
                byte_code = compile_restricted(
                    commands, filename="<inline code>", mode="exec"
                )
                # No locals yet
                execution_locals = None
                exec(byte_code, make_safe_globals(context), execution_locals)
            except SyntaxError as e:
                logger.error(f"Syntax error in python script: {e}")
                raise
            except Exception as e:
                logger.error(f"Error during python script execution: {e}")
                raise
        finally:
            os.chdir(original_cwd)


# A dictionary mapping tool names to their respective tool instances.
tools = {tool.name: tool for tool in [SirilTool(), GraxpertTool(), PythonTool()]}
