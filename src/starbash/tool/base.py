"""Base tool classes for stage execution."""

import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any

from rich.live import Live
from rich.spinner import Spinner

from starbash.commands import SPINNER_STYLE
from starbash.exception import UserHandledError

logger = logging.getLogger(__name__)

__all__ = [
    "Tool",
    "ToolError",
    "MissingToolError",
    "ExternalTool",
    "tool_run",
]


class ToolError(UserHandledError):
    """Exception raised when a tool fails to execute properly."""

    def __init__(self, *args: object, command: str, arguments: str | None) -> None:
        super().__init__(*args)
        self.command = command
        self.arguments = arguments

    def ask_user_handled(self) -> bool:
        from starbash import console  # Lazy import to avoid circular dependency

        args = self.arguments
        # remove any blank lines from args (to make log output shorter)
        if args:
            args = "\n".join(line for line in args.splitlines() if line.strip())

        console.print(f"'{self.command}' failed while running [bold red]{args}[/bold red]")
        return True

    def __rich__(self) -> Any:
        return f"Tool: [red]'{self.command}'[/red] failed"


class MissingToolError(UserHandledError):
    """Exception raised when a required tool is not found."""

    def __init__(self, *args: object, command: str) -> None:
        super().__init__(*args)
        self.command = command

    def __rich__(self) -> Any:
        return str(self)  # FIXME do something better here?


BAD_WORDS = [
    "error",
    "failed",
    "abort",
    "warning",
    "cannot",
    "unable",
    "fatal",
    "No image",
    "Not enough",
]


def color_line(line: str) -> str:
    """Siril/other tools are bad at marking error lines, so we look for 'bad' words and color those lines red."""
    lower_line = line.lower()
    for bad_word in BAD_WORDS:
        if bad_word in lower_line:
            return f"[red]{line}[/red]"
    return line


def color_lines(lines: list[str]) -> str:
    """Color lines based on presence of 'bad' words."""
    return "\n".join(color_line(line) for line in lines)


def tool_emit_logs(lines: str, log_level: int = logging.INFO) -> None:
    """Emit log lines from a tool to the logger at the specified log level.

    Some tools (especially Siril) are poor at marking which lines have actual error message, and they might generate LOTS
    of less interesting log lines.  So in the case we got an error result from the tool, print only the first few lines (to show basic
    context) and the last few lines (to show actual error messages).
    """
    NUM_PRELUDE_LINES = 5
    NUM_WARNING_LINES = 10

    if log_level == logging.DEBUG:
        logger.log(log_level, f"[tool] {lines}")  # Show all the lines if we are debugging
    else:
        # Remove blank lines (not interesting)
        split_lines = [line for line in lines.splitlines() if line.strip()]
        total_preview_lines = NUM_PRELUDE_LINES + NUM_WARNING_LINES

        if len(split_lines) <= total_preview_lines:
            # If there are few enough lines, just show them all at the specified log level
            logger.log(log_level, f"[tool] {color_lines(split_lines)}")
        else:
            # Show first few lines as INFO
            first_lines = color_lines(split_lines[:NUM_PRELUDE_LINES])
            logger.info(f"[tool] {first_lines}")

            # Show ellipsis to indicate omitted lines
            omitted_count = len(split_lines) - total_preview_lines
            logger.info(f"[dim][tool] … ({omitted_count} lines omitted) …[/dim]")

            # Show last few lines at the specified log level
            last_lines = color_lines(split_lines[-NUM_WARNING_LINES:])
            logger.log(log_level, f"[tool] {last_lines}")


def tool_run(
    cmd: str,
    cwd: str,
    commands: str | None = None,
    timeout: float | None = None,
    log_out: io.TextIOWrapper | None = None,
) -> None:
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

    # print stdout BEFORE stderr so the user can more easily see error message near the exception
    if returncode != 0:
        # log stdout with error priority because the tool failed
        log_level = logging.ERROR
    else:
        log_level = logging.DEBUG
    tool_emit_logs(stdout_lines, log_level=log_level)

    # If log_out is provided, also write stdout to that file
    if log_out and stdout_lines:
        log_out.write(stdout_lines)
        log_out.flush()  # Just in case the user is 'tailing' the file

    # Check stdout for "Aborting" messages and append them to stderr (because the only useful Siril error messages appear on such a line)
    abort_lines = [line for line in stdout_lines.splitlines() if "Aborting" in line]
    stderr_level = logging.ERROR if returncode != 0 else logging.WARNING
    if abort_lines:
        stderr_lines = (
            stderr_lines + "\n" + "\n".join(abort_lines) if stderr_lines else "\n".join(abort_lines)
        )

    if stderr_lines:
        # drop any line that contains "Reading sequence failed, file cannot be opened"
        # because it is a bogus harmless message from siril and confuses users.
        filtered_lines = [
            line
            for line in stderr_lines.splitlines()
            if "Reading sequence failed, file cannot be opened" not in line
        ]
        if filtered_lines:
            logger.log(stderr_level, f"[tool-warnings] {'\n'.join(filtered_lines)}")

    if returncode != 0:
        # log stdout with warn priority because the tool failed
        raise ToolError(
            f"{cmd} failed with exit code {returncode}", command=cmd, arguments=commands
        )
    else:
        logger.debug("Tool command successful.")


class Tool:
    """A tool for stage execution"""

    # Tools and recursively invoke other tools.  So it is important that if we've set a log file destination at the top
    # of our call tree, that variables get passed down to all sub-tools.
    _default_log_out: io.TextIOWrapper | None = None

    def __init__(self, name: str) -> None:
        self.name: str = name

        # default script file name
        self.default_script_file: None | str = None
        self.set_defaults()

    def set_defaults(self):
        # default timeout in seconds, if you need to run a tool longer than this, you should change
        # it before calling run()
        # FIXME, remove this concept and instead just use the new parameters API
        self.timeout = (
            60 * 60.0  # 60 minutes - just to make sure we eventually stop all tools
        )

    def run(
        self,
        commands: str | list[str],
        context: dict = {},
        cwd: str | None = None,
        log_out: io.TextIOWrapper | None = None,
        **kwargs: dict[str, Any],
    ) -> None:
        """Run commands inside this tool

        If cwd is provided, use that as the working directory otherwise a temp directory is used as cwd.
        """
        from starbash import console  # Lazy import to avoid circular dependency

        temp_dir = None
        spinner = Spinner(
            "arc", text=f"Tool running: [bold]{self.name}[/bold]...", speed=2.0, style=SPINNER_STYLE
        )
        with Live(spinner, console=console, refresh_per_second=5, transient=True):
            did_set_default_log = (
                False  # Assume we are not the top entry into the chain of tool calls
            )
            if log_out:
                if not Tool._default_log_out:
                    # set the class default log output if we don't have one yet
                    Tool._default_log_out = log_out
                    did_set_default_log = True

            # Use the default if someone higher up provided it
            my_log = log_out if log_out else Tool._default_log_out

            try:
                if not cwd:
                    # Create a temporary directory for processing
                    cwd = temp_dir = tempfile.mkdtemp(prefix=self.name)

                    context["temp_dir"] = (
                        temp_dir  # pass our directory path in for the tool's usage
                    )

                self._run(cwd, commands, context=context, log_out=my_log, **kwargs)
            finally:
                spinner.update(text=f"Tool completed: [bold]{self.name}[/bold].")
                if temp_dir:
                    shutil.rmtree(temp_dir)
                    context.pop("temp_dir", None)

                if did_set_default_log:
                    # clear the class default log output if we set it
                    Tool._default_log_out = None

    def _run(
        self,
        cwd: str,
        commands: str | list[str],
        context: dict = {},
        log_out: io.TextIOWrapper | None = None,
        **kwargs: dict[str, Any],
    ) -> None:
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
                    The {self.name} executable was not found.  Most features will be unavailable until you install it.
                    Click [link={self.install_url}]here[/link] for installation instructions.

                    If you have already installed {self.name}, make sure it is in your system PATH.
                    Instructions for Windows are [link=https://www.architectryan.com/2018/03/17/add-to-the-path-on-windows-10/]here[/link], for Linux or OS-X try [link=https://stackoverflow.com/questions/14637979/how-to-permanently-set-path-on-linux-mac]this[/link].""")
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
