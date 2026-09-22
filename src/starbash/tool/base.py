"""Base tool classes for stage execution."""

import contextlib
import enum
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from starbash import events
from starbash.exception import FilesystemUnavailableError, UserHandledError

logger = logging.getLogger(__name__)

__all__ = [
    "Tool",
    "ToolError",
    "MissingToolError",
    "ExternalTool",
    "ToolSeverity",
    "ToolStatus",
    "plain_message",
    "tool_run",
    "tool_run_streaming",
    "tool_run_in_process",
    "publish_tool_progress",
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


# Matches a "42%" or "42.5 %" progress token anywhere in a tool output line.
_PERCENT_RE = re.compile(r"(\d{1,3})(?:\.\d+)?\s*%")


def publish_tool_progress(
    cmd: str,
    *,
    percent: float | int | None = None,
    message: str | None = None,
    line: str | None = None,
) -> None:
    """Publish an ``EVENT_TOOL_PROGRESS`` event for ``cmd``.

    This is the single place that shapes a tool-progress payload, so a tool that
    parses its own structured output (rc-astro's ``--json`` stream) reports
    progress identically to the generic ``NN%`` scan in
    :func:`_publish_tool_line`.

    Args:
        cmd: The command line the progress came from.
        percent: Completion in the 0-100 range, or ``None`` for a message-only
            status update (the GUI then leaves the bar untouched).
        message: Optional human-readable phase/status caption.
        line: Optional raw output line the progress was derived from.
    """
    data: dict[str, Any] = {"cmd": cmd}
    if percent is not None:
        data["percent"] = max(0, min(100, int(percent)))
    if message:
        data["message"] = message
    if line is not None:
        data["line"] = line
    events.publish(events.EVENT_TOOL_PROGRESS, data)


def _publish_tool_line(cmd: str, stream_name: str, line: str) -> None:
    """Publish a tool output line (plus any percentage found in it) to the bus.

    Observers render it themselves: the desktop GUI streams it into a log pane and
    progress bar, and the CLI's ``ProcessingView`` keeps the last few lines on
    screen under its status line.  Publishing is infallible and cheap, so callers
    never need to know whether anything is listening.
    """
    text = line.rstrip("\n")
    events.publish(events.EVENT_TOOL_OUTPUT, {"cmd": cmd, "stream": stream_name, "line": text})
    match = _PERCENT_RE.search(text)
    if match:
        publish_tool_progress(cmd, percent=int(match.group(1)), line=text)


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
        abort_lines = [line for line in "".join(stdout_captured).splitlines() if "Aborting" in line]
        combined = stderr_lines + abort_lines
        # Drop a bogus harmless Siril noise line that confuses users.
        return [
            line
            for line in combined
            if "Reading sequence failed, file cannot be opened" not in line
        ]

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
    stdout_mime: str | None = None,
) -> None:
    """Execute an external tool, invoking on_line for each stdout line as it arrives.

    Unlike a blocking communicate()-based runner, this streams stdout line-by-line so
    callers can react to incremental output (e.g. JSON progress events).  Separate
    reader threads for stdout and stderr feed a shared queue so the timeout fires
    correctly even for silent processes and both streams are written to log_out in
    approximate arrival order.  A non-zero exit code raises ToolError.

    Args:
        cmd: Shell command line to run.
        cwd: Working directory for the child process.
        on_line: Called with each stdout line as it arrives (already newline-stripped
            for the caller's convenience by convention).
        timeout: Seconds to wait before killing the child, or None for no limit.
        log_out: Raw log file; receives *every* line from both streams, verbatim.
        commands: Text written to the child's stdin, which is then closed.
        arguments: Extra arguments appended to the command line (see above).
        stderr_fixup: Rewrites (stdout, stderr) line lists into the raised ToolError.
        stdout_mime: When the tool's stdout is a machine-readable protocol (e.g.
            ``"json"`` for rc-astro's ``--json`` events), names it ``"stdout.<mime>"``
            in the published :data:`~starbash.events.EVENT_TOOL_OUTPUT` payload so log
            renderers can skip those frames (see
            :func:`starbash.events.is_structured_stream`).  ``log_out`` still receives
            the raw lines, and ``on_line`` is unaffected.
    """
    import queue
    import threading
    import time

    logger.debug(f"Streaming {cmd} in {cwd}")

    events.publish(events.EVENT_TOOL_STARTED, {"cmd": cmd, "cwd": cwd})

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

    threading.Thread(target=_reader, args=("stdout", process.stdout), daemon=True).start()
    threading.Thread(target=_reader, args=("stderr", process.stderr), daemon=True).start()

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
            # Tag a structured stdout so log renderers can drop its protocol frames.
            published_stream = (
                f"stdout.{stdout_mime}" if stdout_mime and stream_name == "stdout" else stream_name
            )
            _publish_tool_line(cmd, published_stream, line)
            if stream_name == "stdout":
                stdout_captured.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        logger.exception("Error in tool output line handler")
            else:
                stderr_captured.append(line)
    except OSError as exc:
        # A log file may live on a removable or network filesystem. If that
        # filesystem disappears, terminate the child rather than leaving the
        # external tool running after the logging failure.
        try:
            process.kill()
        finally:
            process.wait()
        raise FilesystemUnavailableError("writing tool output", exc) from exc
    finally:
        process.stdout.close()
        process.stderr.close()

    returncode = process.wait()

    events.publish(
        events.EVENT_TOOL_FINISHED,
        {"cmd": cmd, "returncode": returncode, "success": returncode == 0},
    )

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


class _ToolSourceFilter(logging.Filter):
    """Accept - or reject - records emitted by a built-in tool's own modules.

    An in-process tool logs through Python's ``logging`` from inside its own
    package, so ``record.pathname`` names the file that made the call.  That is
    what tells the tool's messages apart from Starbash's own, which matters
    because a tool that logs with the module-level helpers (``logging.info``, as
    GraXpert does) creates its records *on the root logger* - so a logger name
    cannot be matched on, and the emitting file is the only reliable signal.

    ``source=None`` means "every record is the tool's own" (and, inverted, accepts
    nothing).  That is the right reading for a tool whose output comes from
    Starbash's *own* modules - the python sandbox logs a script's ``print`` from
    ``starbash.tool.context`` and its ``sim_siril`` calls from
    ``starbash.sim_siril`` - where no directory can be named as the origin.
    """

    def __init__(self, source: str | None, *, invert: bool = False) -> None:
        super().__init__()
        self.prefix: str | None = _source_prefix(source)
        self.invert = invert

    def filter(self, record: logging.LogRecord) -> bool:
        from_tool = self.prefix is None or os.path.abspath(record.pathname).startswith(self.prefix)
        return not from_tool if self.invert else from_tool


def _source_prefix(source: str | None) -> str | None:
    """Directory prefix marking a record as a built-in tool's, or ``None`` for all."""
    if source is None:
        return None
    prefix = os.path.abspath(source)
    # A trailing separator keeps ".../graxpertish" from matching ".../graxpert".
    return prefix if prefix.endswith(os.sep) else prefix + os.sep


#: Installed forwarders, outermost first (see :meth:`_ToolLogForwarder.emit`).
_active_forwarders: list["_ToolLogForwarder"] = []


class _ToolLogForwarder(logging.Handler):
    """Republish a built-in tool's log records as tool output events.

    The in-process counterpart of the reader threads in
    :func:`tool_run_streaming`: one log record becomes one
    :data:`~starbash.events.EVENT_TOOL_OUTPUT` line (plus a progress event if the
    line carries a percentage), and the raw line is appended to ``log_out``.
    """

    def __init__(self, cmd: str, log_out: io.TextIOWrapper | None, source: str | None) -> None:
        super().__init__()
        self.cmd = cmd
        self.log_out = log_out
        # Kept by name (rather than read back from ``self.filters``) so ``accepts``
        # can ask it directly whether a record is this tool's.
        self.source = _ToolSourceFilter(source)
        self.addFilter(self.source)

    def accepts(self, record: logging.LogRecord) -> bool:
        """Whether this forwarder would republish ``record``."""
        return self.source.filter(record)

    def _owned_by_an_inner_run(self, record: logging.LogRecord) -> bool:
        """True when a tool started *inside* this one already republishes ``record``.

        A nested in-process tool installs its forwarder later, so without this the
        outer run would publish the inner tool's lines a second time.
        """
        try:
            index = _active_forwarders.index(self)
        except ValueError:  # not registered (any more): nothing to defer to
            return False
        return any(inner.accepts(record) for inner in _active_forwarders[index + 1 :])

    def emit(self, record: logging.LogRecord) -> None:
        if self._owned_by_an_inner_run(record):
            return
        try:
            line = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record must not kill the tool
            self.handleError(record)
            return
        # Warnings and errors are the tool's stderr, so the log panes colour them red.
        stream = "stderr" if record.levelno >= logging.WARNING else "stdout"
        if self.log_out:
            self.log_out.write(line + "\n")
            self.log_out.flush()  # Just in case the user is 'tailing' the file
        _publish_tool_line(self.cmd, stream, line)


@contextlib.contextmanager
def tool_run_in_process(
    cmd: str,
    *,
    source: str | None,
    cwd: str | None = None,
    log_out: io.TextIOWrapper | None = None,
) -> Iterator[None]:
    """Run a built-in tool's work while its own log output is published as events.

    An external tool has its stdout/stderr captured and streamed by
    :func:`tool_run_streaming`; a tool implemented as Python code inside Starbash
    (GraXpert's ``api_run``) instead logs through Python's ``logging``, and that
    output used to reach the root logger's handler and be drawn *straight onto the
    console* - over the live run display the observer owns, so the user saw the
    lines dumped around the live tree instead of in it, and the GUI saw none at
    all (see ``doc/plans/cli-live-display.md``).

    This makes the in-process path look identical to the external one from an
    observer's point of view: ``tool.started`` / ``tool.output`` /
    ``tool.progress`` / ``tool.finished`` events plus the raw lines in
    ``log_out``.  The CLI's run tree and the GUI therefore show the tool's output
    as it happens, exactly as they do for Siril or rc-astro.

    Args:
        cmd: Command-line-style label for the events - what the UIs show as "the
            tool" (mirrors the ``cmd`` an external tool would report).
        source: Directory the tool's own modules live in, i.e.
            ``os.path.dirname(<package>.__file__)``.  Only records emitted from
            files under it are republished, so Starbash's own log messages keep
            their usual handling.  Pass ``None`` when the output is emitted by
            Starbash's own modules instead - the python sandbox logs a script's
            ``print`` from ``starbash.tool.context`` - which makes *every* record
            emitted during the call part of the tool's output.
        cwd: Working directory, reported in the ``tool.started`` payload.
        log_out: Raw log file; receives every republished line, verbatim.

    Nested calls are safe: each forwarder defers to one started inside it, so a
    line is republished exactly once, and an inner call's silencer also keeps it
    away from the outer call's handlers.
    """
    events.publish(events.EVENT_TOOL_STARTED, {"cmd": cmd, "cwd": cwd})

    root = logging.getLogger()
    forwarder = _ToolLogForwarder(cmd, log_out, source)
    # Keep the tool's own lines away from the console's usual handlers: observers
    # render them from the bus, and a second, direct draw would fight the CLI's
    # live display (the tear described in doc/plans/cli-live-display.md).
    silencers = [(handler, _ToolSourceFilter(source, invert=True)) for handler in root.handlers]
    for handler, silencer in silencers:
        handler.addFilter(silencer)
    root.addHandler(forwarder)
    _active_forwarders.append(forwarder)

    success = True
    try:
        yield
    except BaseException:
        success = False
        raise
    finally:
        _active_forwarders.remove(forwarder)
        root.removeHandler(forwarder)
        for handler, silencer in silencers:
            handler.removeFilter(silencer)
        events.publish(
            events.EVENT_TOOL_FINISHED,
            {"cmd": cmd, "returncode": 0 if success else 1, "success": success},
        )


#: Matches the one piece of Rich markup our tool messages use for a link.
_LINK_MARKUP = re.compile(r"\[link=([^\]]*)\](.*?)\[/link\]")


def plain_message(message: str) -> str:
    """Rewrite a tool message written for Rich's console as plain text.

    Tool messages are rendered by Rich in the CLI (``Click [link=URL]here[/link]``).
    Anything that is *not* a console - a Qt label, a tooltip, a log file - must not
    show that markup, so links become ``here (URL)`` and any leftover link tags are
    dropped.
    """
    text = _LINK_MARKUP.sub(lambda match: f"{match.group(2)} ({match.group(1)})", message)
    return re.sub(r"\[/?link(?:=[^\]]*)?\]", "", text)


class ToolSeverity(enum.IntEnum):
    """How badly the user needs a tool that Starbash could not find.

    The ordering is significant (``OPTIONAL < RECOMMENDED < REQUIRED``), which is
    why this is an :class:`enum.IntEnum`: a caller can write
    ``severity < ToolSeverity.REQUIRED`` to decide whether a missing tool may be
    dismissed with an *Ignore* button.  A ``REQUIRED`` tool keeps warning, because
    most workflows cannot run without it.
    """

    OPTIONAL = 0
    RECOMMENDED = 1
    REQUIRED = 2

    @property
    def label(self) -> str:
        """A short, lowercase name for messages and stylesheet hooks."""
        return self.name.lower()


@dataclass(frozen=True)
class ToolStatus:
    """The availability of one tool, shaped for the CLI and the GUI to render.

    Both front ends need the same facts - which tool, how important it is, where
    to get it - so probing a tool and describing the result lives here instead of
    being re-implemented per UI.
    """

    name: str
    key: str
    severity: ToolSeverity
    available: bool
    install_url: str | None = None
    ignored: bool = False
    detail: str | None = None

    @property
    def needs_attention(self) -> bool:
        """True when the user should be told about this tool.

        A missing tool is worth a warning unless the user already asked us to
        stop mentioning it.
        """
        return not self.available and not self.ignored

    @property
    def can_be_ignored(self) -> bool:
        """Whether this warning may be dismissed permanently (see ``severity``)."""
        return self.severity < ToolSeverity.REQUIRED

    @property
    def summary(self) -> str:
        """A one-line, plain-text form of :attr:`detail`, for compact UIs.

        The GUI's warning bar shows this beside an *Install* button - the console's
        multi-paragraph explanation (with its Rich link markup) would be unreadable
        there, and word-wrapping all of it would make the bar enormous.
        """
        if not self.detail:
            return ""
        first_line = self.detail.strip().splitlines()[0].strip()
        return plain_message(first_line)


class Tool:
    """A tool for stage execution"""

    #: How important it is that this tool is installed (see :class:`ToolSeverity`).
    severity: ToolSeverity = ToolSeverity.OPTIONAL

    #: Where the user can install this tool; ``None`` for tools that ship with Starbash.
    install_url: str | None = None

    # A hierarchical dictionary of user preferences for this tool.  Typical node path would be: "siril.path"
    # Normally set by the app constructor based on user configuration toml.
    Preferences: dict[str, Any] = {}

    # Tools and recursively invoke other tools.  So it is important that if we've set a log file destination at the top
    # of our call tree, that variables get passed down to all sub-tools.
    _default_log_out: io.TextIOWrapper | None = None

    # NOTE: tools no longer own a live terminal display.  The CLI renders run
    # progress from the event bus (see ProcessingView), so nothing here draws over
    # it -- two Rich Live displays on one console tear each other apart
    # (doc/plans/cli-live-display.md).

    def __init__(self, name: str) -> None:
        self.name: str = name

        # default script file name
        self.default_script_file: None | str = None
        self.set_defaults()

    @property
    def is_available(self) -> bool:
        """Whether this tool can be run. Built-in tools are always available."""
        return True

    @property
    def key(self) -> str:
        """The registry and preference key for this tool (its lowercased name)."""
        return self.name.lower()

    @property
    def is_ignored(self) -> bool:
        """Whether the user asked to stop being warned that this tool is missing.

        Set from the ``ignored`` flag of the tool's user-config section, i.e.
        ``tool.<key>.ignored = true``, which the GUI's *Ignore* button writes.
        """
        prefs = Tool.Preferences.get(self.key)
        return bool(prefs.get("ignored")) if isinstance(prefs, dict) else False

    def missing_message(self) -> str:
        """Explain why this tool is unavailable, and how the user can fix it."""
        return f"The {self.name} executable was not found."

    def status(self) -> ToolStatus:
        """Report this tool's availability (probing it if necessary)."""
        available = self.is_available
        return ToolStatus(
            name=self.name,
            key=self.key,
            severity=self.severity,
            available=available,
            install_url=self.install_url,
            ignored=self.is_ignored,
            detail=None if available else self.missing_message(),
        )

    def invalidate_availability(self) -> None:
        """Forget the cached availability probe, so the next check re-probes.

        Built-in tools are always available, so the base implementation is a
        no-op; :class:`ExternalTool` overrides it to drop its cached probe result.
        This exists for the GUI setup wizard's *Re-check* button: a user who
        installs a missing tool while the wizard is open must be able to make
        Starbash look again, and ``is_available`` caches its first answer.
        """
        return None

    def preflight(self) -> None:
        """Report a missing tool at a log level matching its severity.

        ``REQUIRED`` (Siril) logs an error, ``RECOMMENDED`` (StarNet) a warning,
        and ``OPTIONAL`` tools only a debug line - so the default CLI run is not
        cluttered with tools most users never need.  A tool the user chose to
        ignore stays silent here, exactly as its GUI warning bar disappears.
        """
        if self.is_available or self.is_ignored:
            return

        message = self.missing_message()
        if self.severity is ToolSeverity.REQUIRED:
            logger.error("%s This tool is required for most workflows.", message)
        elif self.severity is ToolSeverity.RECOMMENDED:
            logger.warning("%s Some features will be unavailable until it is installed.", message)
        else:
            logger.debug("Optional tool %s is not installed: %s", self.name, message)

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
        **kwargs: Any,
    ) -> None:
        """Run commands inside this tool

        If cwd is provided, use that as the working directory otherwise a temp directory is used as cwd.
        """
        temp_dir = None
        did_set_default_log = False  # Assume we are not the top entry into the chain of tool calls
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

                context["temp_dir"] = temp_dir  # pass our directory path in for the tool's usage

            self._run(cwd, commands, context=context, log_out=my_log, **kwargs)
        finally:
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
        **kwargs: Any,
    ) -> None:
        """Run commands inside this tool (with cwd pointing to the specified directory)"""
        raise NotImplementedError()


class ExternalTool(Tool):
    """A tool provided by an external executable

    Args:
        name: Name of the tool (e.g. "Siril" or "GraXpert") it is important that this matches the GUI name exactly
        commands: List of command names or absolute executable paths to try
            when locating the tool
        install_url: URL to installation instructions for the tool
        severity: How important it is that this tool is installed (defaults to
            :attr:`ToolSeverity.OPTIONAL`, so a new tool is quiet until proven
            necessary - see :meth:`Tool.preflight`).
    """

    def __init__(
        self,
        name: str,
        commands: list[str],
        install_url: str,
        severity: ToolSeverity = ToolSeverity.OPTIONAL,
    ) -> None:
        super().__init__(name)
        self.commands = commands
        self.install_url = install_url
        self.severity = severity
        self._is_available: bool | None = None  # cached result of is_available probe
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

    def missing_message(self) -> str:
        """Explain that the executable was not found, with install and PATH hints."""
        return textwrap.dedent(f"""\
            The {self.name} executable was not found.  Related features will be unavailable until you install it.
            Click [link={self.install_url}]here[/link] for installation instructions.

            If you have already installed {self.name}, make sure it is in your system PATH.
            Instructions for Windows are [link=https://www.architectryan.com/2018/03/17/add-to-the-path-on-windows-10/]here[/link], for Linux or OS-X try [link=https://stackoverflow.com/questions/14637979/how-to-permanently-set-path-on-linux-mac]this[/link].""")

    @property
    def is_available(self) -> bool:
        """Whether the external executable was found on PATH (probed once and cached)."""
        if self._is_available is None:
            try:
                _ = self.executable_path  # raises if not found
                self._is_available = True
            except MissingToolError:
                self._is_available = False
        return self._is_available

    def invalidate_availability(self) -> None:
        """Drop the cached probe so the next :attr:`is_available` re-runs it.

        ``is_available`` caches its answer in ``_is_available`` on first read, so
        without this a *Re-check* after the user installed the tool would keep
        reporting the old (missing) answer forever.
        """
        self._is_available = None

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

        for cmd in self.commands:
            if os.path.isabs(cmd) and os.path.isfile(cmd) and os.access(cmd, os.X_OK):
                return cmd

        for path in paths:
            for cmd in self.commands:
                if os.path.isabs(cmd):
                    continue
                if shutil.which(cmd, path=path):
                    return cmd

        # didn't find anywhere
        raise MissingToolError(
            f"{self.name} not found. Installation instructions [link={self.install_url}]here[/link]",
            command=self.name,
        )
