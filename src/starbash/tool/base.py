"""Base tool classes for stage execution."""

import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections import deque
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from rich.console import Group, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.spinner import Spinner
from rich.text import Text

from starbash.commands import SPINNER_STYLE
from starbash.exception import UserHandledError

logger = logging.getLogger(__name__)

__all__ = [
    "Tool",
    "ToolError",
    "MissingToolError",
    "ExternalTool",
    "tool_run",
    "tool_run_streaming",
]

# If we want to ensure that child tools don't accidentally try to open GUI windows, we can set this flag.
# This is especially useful to ensure that the tools will work in a headless environment (such as) github CI runners.
force_no_gui = False


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


class ToolLiveDisplay:
    """Live renderable: a running spinner plus the most recent tool output lines.

    Fed incrementally by ``tool_run_streaming`` via :meth:`add_line`.  stderr lines
    render red, stdout lines yellow.  Each line is truncated to a single row so the
    display stays a fixed height while the tool runs.
    """

    MAX_LINES = 3

    def __init__(self, name: str) -> None:
        self.name = name
        self.spinner = Spinner(
            "arc",
            text=f"Tool running: [bold]{name}[/bold]...",
            speed=2.0,
            style=SPINNER_STYLE,
        )
        self._lines: deque[Text] = deque(maxlen=self.MAX_LINES)
        self._done = False

    def add_line(self, line: str, is_stderr: bool) -> None:
        """Append a tool output line, keeping only the most recent MAX_LINES."""
        text = line.rstrip("\n")
        if not text.strip():
            return
        self._lines.append(
            Text(
                text,
                style="red" if is_stderr else "yellow",
                no_wrap=True,
                overflow="ellipsis",
            )
        )

    def finish(self) -> None:
        """Swap the spinner for a static header so the final frame persists."""
        self._done = True

    def __rich__(self) -> RenderableType:
        header: RenderableType = (
            Text(f"Tool completed: {self.name}", style="dim")
            if self._done
            else self.spinner
        )
        # Indent each output line by 4 spaces beneath the header.
        lines = [Padding(line, (0, 0, 0, 4)) for line in self._lines]
        return Group(header, *lines)


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

    def _stderr_fixup(stdout_captured: list[str], stderr_lines: list[str]) -> list[str]:
        # Siril writes errors to stdout with "Aborting"; surface those alongside real stderr.
        abort_lines = [
            line for line in "".join(stdout_captured).splitlines() if "Aborting" in line
        ]
        combined = stderr_lines + abort_lines
        # Drop a bogus harmless Siril noise line that confuses users.
        return [line for line in combined if "Reading sequence failed, file cannot be opened" not in line]

    tool_run_streaming(
        cmd,
        cwd,
        timeout=timeout,
        log_out=log_out,
        commands=commands,
        arguments=commands,
        stderr_fixup=_stderr_fixup,
    )


def tool_run_streaming(
    cmd: str,
    cwd: str,
    on_line: Callable[[str], None] | None = None,
    timeout: float | None = None,
    log_out: io.TextIOWrapper | None = None,
    commands: str | None = None,
    arguments: str | None = None,
    stderr_fixup: Callable[[list[str], list[str]], list[str]] | None = None,
) -> None:
    """Execute an external tool, invoking on_line for each stdout line as it arrives.

    Unlike a blocking communicate()-based runner, this streams stdout line-by-line so
    callers can react to incremental output (e.g. JSON progress events).  Separate
    reader threads for stdout and stderr feed a shared queue so the timeout fires
    correctly even for silent processes and both streams are written to log_out in
    approximate arrival order.  A non-zero exit code raises ToolError.
    """
    import queue
    import threading
    import time

    logger.debug(f"Streaming {cmd} in {cwd}")

    env = os.environ.copy()

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if commands else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    if commands:
        assert process.stdin is not None

        def _write_stdin() -> None:
            try:
                process.stdin.write(commands)  # type: ignore[union-attr]
                process.stdin.close()  # type: ignore[union-attr]
            except BrokenPipeError:
                pass

        threading.Thread(target=_write_stdin, daemon=True).start()

    # Both reader threads push (stream_name, line) tuples so we can interleave the
    # two streams into log_out in approximate arrival order.  A None line marks EOF
    # for that reader; the main loop stops once both readers have finished.
    line_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def _reader(name: str, stream: io.TextIOBase) -> None:
        try:
            for line in stream:
                line_queue.put((name, line))
        except Exception:
            pass
        finally:
            line_queue.put((name, None))  # EOF sentinel

    threading.Thread(
        target=_reader, args=("stdout", process.stdout), daemon=True
    ).start()
    threading.Thread(
        target=_reader, args=("stderr", process.stderr), daemon=True
    ).start()

    deadline = (time.monotonic() + timeout) if timeout else None
    stdout_captured: list[str] = []
    stderr_captured: list[str] = []
    readers_done = 0

    try:
        while readers_done < 2:
            remaining = max(0.0, deadline - time.monotonic()) if deadline else None
            try:
                stream_name, line = line_queue.get(timeout=remaining)
            except queue.Empty:
                process.kill()
                process.wait()
                raise RuntimeError(f"Tool timed out after {timeout} seconds")
            if line is None:  # EOF for one of the streams
                readers_done += 1
                continue
            if log_out:
                log_out.write(line)
                log_out.flush()  # Just in case the user is 'tailing' the file
            active_display = Tool._active_display
            if active_display is not None:
                active_display.add_line(line, is_stderr=stream_name == "stderr")
            if stream_name == "stdout":
                stdout_captured.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        logger.exception("Error in tool output line handler")
            else:
                stderr_captured.append(line)
    finally:
        process.stdout.close()
        process.stderr.close()

    returncode = process.wait()

    stdout_str = "".join(stdout_captured)
    if returncode != 0:
        tool_emit_logs(stdout_str, log_level=logging.ERROR)

    stderr_list = [line.rstrip("\n") for line in stderr_captured]
    if stderr_fixup:
        stderr_list = stderr_fixup(stdout_captured, stderr_list)
    if stderr_list:
        stderr_level = logging.ERROR if returncode != 0 else logging.WARNING
        logger.log(stderr_level, f"[tool-warnings] {'\n'.join(stderr_list)}")

    if returncode != 0:
        raise ToolError(
            f"{cmd} failed with exit code {returncode}", command=cmd, arguments=arguments
        )
    else:
        logger.debug("Tool command successful.")


class Tool:
    """A tool for stage execution"""

    # A hierarchical dictionary of user preferences for this tool.  Typical node path would be: "siril.path"
    # Normally set by the app constructor based on user configuration toml.
    Preferences: dict[str, Any] = {}

    # Tools and recursively invoke other tools.  So it is important that if we've set a log file destination at the top
    # of our call tree, that variables get passed down to all sub-tools.
    _default_log_out: io.TextIOWrapper | None = None

    # The live output display owned by the outermost tool in a call chain.  Nested
    # tools (and tool_run_streaming) feed their output lines into this same display.
    _active_display: "ToolLiveDisplay | None" = None

    # If True, this tool renders its own progress display in _run() (e.g. a Rich
    # Progress bar), so Tool.run() suppresses the default spinner to avoid nested
    # Live displays.
    manages_own_progress: bool = False

    def __init__(self, name: str) -> None:
        self.name: str = name

        # default script file name
        self.default_script_file: None | str = None
        self.set_defaults()

    def set_defaults(self) -> None:
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
        # Only the outermost tool in a call chain owns the live display; nested tools
        # (and tool_run_streaming) feed their output into the already-active display.
        owns_display = not self.manages_own_progress and Tool._active_display is None
        display_obj = ToolLiveDisplay(self.name) if owns_display else None
        display = (
            Live(display_obj, console=console, refresh_per_second=8, transient=False)
            if display_obj is not None
            else nullcontext()
        )
        with display:
            if display_obj is not None:
                Tool._active_display = display_obj

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
                if display_obj is not None:
                    display_obj.finish()
                    Tool._active_display = None
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

        # Did the user manually specify a path
        pref_path = Tool.Preferences.get(self.name.lower(), {}).get("path")
        if pref_path:
            return pref_path

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
