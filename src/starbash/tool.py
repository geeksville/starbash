import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any

import RestrictedPython
from rich.live import Live
from rich.spinner import Spinner
from rich.traceback import Traceback

from starbash.commands import SPINNER_STYLE
from starbash.exception import UserHandledError

logger = logging.getLogger(__name__)


class ToolError(UserHandledError):
    """Exception raised when a tool fails to execute properly."""

    def __init__(self, *args: object, command: str, arguments: str | None) -> None:
        super().__init__(*args)
        self.command = command
        self.arguments = arguments

    def ask_user_handled(self) -> bool:
        from starbash import console  # Lazy import to avoid circular dependency

        console.print(
            f"'{self.command}' failed while running [bold red]{self.arguments}[/bold red]"
        )
        return True

    def __rich__(self) -> Any:
        return f"Tool: [red]'{self.command}'[/red] failed"


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
    for _i in range(max_iterations):
        if expanded == previous:
            break  # Expansion is complete
        previous = expanded
        expanded = expanded.format_map(_SafeFormatter(context))
    else:
        logger.warning(
            f"Template expansion reached max iterations ({max_iterations}). Possible recursive definition in '{s}'."
        )

    logger.debug(f"Expanded '{s}' into '{expanded}'")

    # throw an error if any remaining unexpanded variables remain unexpanded
    unexpanded_vars = re.findall(r"\{([^{}]+)\}", expanded)

    # Remove duplicates
    unexpanded_vars = list(dict.fromkeys(unexpanded_vars))
    if unexpanded_vars:
        raise KeyError("Missing context variable(s): " + ", ".join(unexpanded_vars))

    return expanded


def expand_context_unsafe(s: str, context: dict) -> str:
    """Expand a string with Python expressions in curly braces using RestrictedPython.

    Context variables are directly available in expressions without a prefix.

    Supports expressions like:
    - "foo {1 + 2}" -> "foo 3"
    - "bar {name}" -> "bar <value of context['name']>"
    - "path {instrument}/{date}/file.fits" -> "path MyScope/2025-01-01/file.fits"
    - "sum {x + y}" -> "sum <value of context['x'] + context['y']>"

    Args:
        s: String with Python expressions in curly braces
        context: Dictionary of variables available directly in expressions

    Returns:
        String with all expressions evaluated and substituted

    Raises:
        ValueError: If any expression cannot be evaluated (syntax errors, missing variables, etc.)

    Note: Uses RestrictedPython for safety, but still has security implications.
    This is a more powerful but less safe alternative to expand_context().
    """
    # Find all expressions in curly braces
    pattern = r"\{([^{}]+)\}"

    def eval_expression(match):
        """Evaluate a single expression and return its string representation."""
        expr = match.group(1).strip()

        try:
            # Compile the expression with RestrictedPython
            byte_code = RestrictedPython.compile_restricted(
                expr, filename="<template expression>", mode="eval"
            )

            # Evaluate with safe globals and the context
            result = eval(byte_code, make_safe_globals(context), None)
            return str(result)

        except Exception as e:
            raise ValueError(f"Failed to evaluate '{expr}' in context") from e

    # Replace all expressions
    expanded = re.sub(pattern, eval_expression, s)

    logger.debug(f"Unsafe expanded '{s}' into '{expanded}'")

    return expanded


def make_safe_globals(extra_globals: dict = {}) -> dict:
    """Generate a set of RestrictedPython globals for AstoGlue exec/eval usage"""
    # Define the global and local namespaces for the restricted execution.
    # FIXME - this is still unsafe, policies need to be added to limit import/getattr etc...
    # see https://restrictedpython.readthedocs.io/en/latest/usage/policy.html#implementing-a-policy

    builtins = RestrictedPython.safe_builtins.copy()

    def write_test(obj):
        """``_write_`` is a guard function taking a single argument.  If the
        object passed to it may be written to, it should be returned,
        otherwise the guard function should raise an exception.  ``_write_``
        is typically called on an object before a ``setattr`` operation."""
        return obj

    def getitem_glue(baseobj, index):
        return baseobj[index]

    extras = {
        "__import__": __import__,  # FIXME very unsafe
        "_getitem_": getitem_glue,  # why isn't the default guarded getitem found?
        "_getiter_": iter,  # Allows for loops and other iterations.
        "_write_": write_test,
        # Add common built-in types
        "list": list,
        "dict": dict,
        "str": str,
        "int": int,
        "all": all,
    }
    builtins.update(extras)

    execution_globals = {
        # Required for RestrictedPython
        "__builtins__": builtins,
        "__name__": "__starbash_script__",
        "__metaclass__": type,
        # Extra globals auto imported into the scripts context
        "logger": logging.getLogger("script"),  # Allow logging within the script
    }
    execution_globals.update(extra_globals)
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


def tool_run(cmd: str, cwd: str, commands: str | None = None, timeout: float | None = None) -> None:
    """Executes an external tool with an optional script of commands in a given working directory."""

    logger.debug(f"Running {cmd} in {cwd}: stdin={commands}")

    # Start the process with pipes for streaming
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if commands else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        text=True,
        cwd=cwd,
    )

    # Wait for process to complete with timeout
    try:
        stdout_lines, stderr_lines = process.communicate(input=commands, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout_lines, stderr_lines = process.communicate()
        raise RuntimeError(f"Tool timed out after {timeout} seconds")

    returncode = process.returncode

    if stderr_lines:
        # drop any line that contains "Reading sequence failed, file cannot be opened"
        # because it is a bogus harmless message from siril and confuses users.
        filtered_lines = [
            line
            for line in stderr_lines.splitlines()
            if "Reading sequence failed, file cannot be opened" not in line
        ]
        if filtered_lines:
            logger.warning(f"[tool-warnings] {'\n'.join(filtered_lines)}")

    if returncode != 0:
        # log stdout with warn priority because the tool failed
        logger.warning(f"[tool] {stdout_lines}")
        raise ToolError(
            f"{cmd} failed with exit code {returncode}", command=cmd, arguments=commands
        )
    else:
        logger.debug(f"[tool] {stdout_lines}")
        logger.debug("Tool command successful.")


class MissingToolError(UserHandledError):
    """Exception raised when a required tool is not found."""

    def __init__(self, *args: object, command: str) -> None:
        super().__init__(*args)
        self.command = command

    def __rich__(self) -> Any:
        return str(self)  # FIXME do something better here?


class Tool:
    """A tool for stage execution"""

    def __init__(self, name: str) -> None:
        self.name: str = name

        # default script file name
        self.default_script_file: None | str = None
        self.set_defaults()

    def set_defaults(self):
        # default timeout in seconds, if you need to run a tool longer than this, you should change
        # it before calling run()
        self.timeout = (
            5 * 60.0  # 5 minutes - just to make sure we eventually stop all tools
        )

    def run(self, commands: str, context: dict = {}, cwd: str | None = None) -> None:
        """Run commands inside this tool

        If cwd is provided, use that as the working directory otherwise a temp directory is used as cwd.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        temp_dir = None
        spinner = Spinner(
            "arc", text=f"Tool running: [bold]{self.name}[/bold]...", speed=2.0, style=SPINNER_STYLE
        )
        with Live(spinner, console=console, refresh_per_second=5):
            try:
                if not cwd:
                    # Create a temporary directory for processing
                    cwd = temp_dir = tempfile.mkdtemp(prefix=self.name)

                    context["temp_dir"] = (
                        temp_dir  # pass our directory path in for the tool's usage
                    )

                self._run(cwd, commands, context=context)
            finally:
                spinner.update(text=f"Tool completed: [bold]{self.name}[/bold].")
                if temp_dir:
                    shutil.rmtree(temp_dir)
                    context.pop("temp_dir", None)

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        """Run commands inside this tool (with cwd pointing to the specified directory)"""
        raise NotImplementedError()


class ExternalTool(Tool):
    """A tool provided by an external executable

    Args:
        name: Name of the tool (e.g. "Siril" or "GraXpert") it is important that this matches the GUI name exactly
        commands: List of possible command names to try to find the tool executable
        install_url: URL to installation instructions for the tool
    """

    def __init__(self, name: str, commands: list[str], install_url: str) -> None:
        super().__init__(name)
        self.commands = commands
        self.install_url = install_url
        self.extra_dirs: list[
            str
        ] = []  # extra directories we look for the tool in addition to system PATH

        # Look for the tool in the system PATH first, but if that doesn't work look in common install locations
        if sys.platform == "linux" or sys.platform == "darwin":
            self.extra_dirs.extend(
                [
                    "/opt/homebrew/bin",
                    "/usr/local/bin",
                    "/opt/local/bin",
                    os.path.expanduser("~/.local/share/flatpak/exports/bin"),
                ]
            )

        # On macOS, also search common .app bundles
        if sys.platform == "darwin":
            self.extra_dirs.append(
                f"/Applications/{name}.app/Contents/MacOS",
            )

    def preflight(self) -> None:
        """Check that the tool is available"""
        try:
            _ = self.executable_path  # raise if not found
        except MissingToolError:
            logger.warning(
                textwrap.dedent(f"""\
                    The {self.name} executable was not found.  Some features will be unavailable until you install it.
                    Click [link={self.install_url}]here[/link] for installation instructions.""")
            )

    @property
    def executable_path(self) -> str:
        """Find the correct executable path to run for the given tool"""

        paths: list[None | str] = [None]  # None means use system PATH

        if self.extra_dirs:
            as_path = os.pathsep.join(self.extra_dirs)
            paths.append(as_path)

        for path in paths:
            for cmd in self.commands:
                if shutil.which(cmd, path=path):
                    return cmd

        # didn't find anywhere
        raise MissingToolError(
            f"{self.name} not found. Installation instructions [link={self.install_url}]here[/link]",
            command=self.name,
        )


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

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        """Executes Siril with a script of commands in a given working directory."""

        # Iteratively expand the command string to handle nested placeholders.
        # The loop continues until the string no longer changes.
        expanded = expand_context_unsafe(commands, context)

        input_files = context.get("input_files", [])

        temp_dir = cwd

        siril_path = self.executable_path
        if siril_path == "org.siril.Siril":
            # The executable is inside a flatpak, so run the lighter/faster/no-gui required exe
            # from inside the flatpak
            siril_path = "flatpak run --command=siril-cli org.siril.Siril"

        # Create symbolic links for all input files in the temp directory
        for f in input_files:
            dest_file = os.path.join(temp_dir, os.path.basename(str(f)))

            # if a script is re-run we might already have the input file symlinks
            if not os.path.exists(dest_file):
                os.symlink(
                    os.path.abspath(str(f)),
                    dest_file,
                )

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
        logger.info(f"Running Siril ({len(input_files)} input files)")

        # The `-s -` arguments tell Siril to run in script mode and read commands from stdin.
        # It seems like the -d command may also be required when siril is in a flatpak
        cmd = f"{siril_path} -d {temp_dir} -s -"

        tool_run(cmd, temp_dir, script_content, timeout=self.timeout)


class GraxpertTool(ExternalTool):
    """Expose Graxpert as a tool"""

    def __init__(self) -> None:
        commands: list[str] = ["graxpert", "GraXpert"]

        super().__init__("GraXpert", commands, "https://graxpert.com/")

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        """Executes Graxpert with the specified command line arguments"""

        # Arguments look similar to: graxpert -cmd background-extraction -output /tmp/testout tests/test_images/real_crummy.fits
        cmd = f"{self.executable_path} {commands}"

        tool_run(cmd, cwd, timeout=self.timeout)


class PythonScriptError(UserHandledError):
    """Exception raised when an error occurs during Python script execution."""

    def ask_user_handled(self) -> bool:
        """Prompt the user with a friendly message about the error.
        Returns:
            True if the error was handled, False otherwise.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        console.print(
            """[bold red]Python Script Error[/bold red] please contact the script author and
            give them this information.

            Processing for the current file will be skipped..."""
        )

        # Show the traceback with Rich formatting
        if self.__cause__:
            traceback = Traceback.from_exception(
                type(self.__cause__),
                self.__cause__,
                self.__cause__.__traceback__,
                show_locals=True,
            )
            console.print(traceback)
        else:
            console.print(f"[yellow]{str(self)}[/yellow]")

        return True


class PythonTool(Tool):
    """Expose Python as a tool"""

    def __init__(self) -> None:
        super().__init__("python")

        # default script file override
        self.default_script_file = "starbash.py"

    def _run(self, cwd: str, commands: str, context: dict = {}) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(cwd)  # cd to where this script expects to run

            logger.info(f"Executing python script in {cwd} using RestrictedPython")
            try:
                byte_code = RestrictedPython.compile_restricted(
                    commands, filename="<python script>", mode="exec"
                )
                # No locals yet
                execution_locals = None
                globals = {"context": context}
                exec(byte_code, make_safe_globals(globals), execution_locals)
            except SyntaxError as e:
                raise PythonScriptError("Syntax error in python script") from e
            except UserHandledError:
                raise  # No need to wrap this - just pass it through for user handling
            except Exception as e:
                raise PythonScriptError("Error during python script execution") from e
        finally:
            os.chdir(original_cwd)


def preflight_tools() -> None:
    """Preflight check all known tools to see if they are available"""
    for tool in tools.values():
        if isinstance(tool, ExternalTool):
            tool.preflight()


# A dictionary mapping tool names to their respective tool instances.
tools: dict[str, Tool] = {
    tool.name.lower(): tool for tool in list[Tool]([SirilTool(), GraxpertTool(), PythonTool()])
}
