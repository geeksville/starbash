"""RC-Astro tool integration (BlurXTerminator, NoiseXTerminator, ...)."""

import io
import json
import logging
import os
import re
from typing import Any

from starbash.tool.base import ExternalTool, ToolSeverity, publish_tool_progress, tool_run_streaming
from starbash.tool.context import expand_context_unsafe

logger = logging.getLogger(__name__)

__all__ = ["RCAstroTool", "parse_json_line"]

_PLACEHOLDER_RE = re.compile(r"^\s*\{[^{}]+\}\s*$")


def _is_placeholder(s: str) -> bool:
    """True if s is a single ``{...}`` template placeholder (no surrounding literal text)."""
    return bool(_PLACEHOLDER_RE.match(s))


def _is_unset(expanded: str) -> bool:
    """True if an expanded value represents an unset parameter (empty or ``None``)."""
    return expanded == "" or expanded == "None"


def parse_json_line(line: str) -> dict | None:
    """Parse a single line of rc-astro ``--json`` output.

    Returns the decoded JSON object, or ``None`` for blank lines or lines that are
    not valid JSON objects (rc-astro may interleave non-JSON diagnostic text).
    """
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


class RCAstroTool(ExternalTool):
    """Expose the rc-astro CLI (BlurXTerminator etc.) as a tool.

    Always passes ``--json`` so the streaming output can drive a live progress bar.
    """

    def __init__(self) -> None:
        super().__init__(
            "rc-astro",
            ["rc-astro"],
            "https://www.rc-astro.com/stand-alone-rc-astro-tools/",
            # Optional: BlurXTerminator/NoiseXTerminator are a paid add-on, and
            # plenty of workflows never use them.
            ToolSeverity.OPTIONAL,
        )

    def set_defaults(self) -> None:
        super().set_defaults()
        self.timeout = 2 * 60 * 60.0  # 2 hours - CPU deconvolution can be slow

    def build_args(self, commands: str | list[str], context: dict) -> list[str]:
        """Expand recipe arguments and ensure ``--json`` is pnresent.

        A ``--flag {parameters.x}`` pair whose value comes from an *unset* parameter
        (no default and no user override, so it expands to ``None``) is dropped
        entirely, so rc-astro falls back to its own built-in default for that option.
        """
        if not isinstance(commands, list):
            args = expand_context_unsafe(commands, context).split()
            if "--json" not in args:
                args = ["--json", *args]
            return args

        raw = [str(s) for s in commands]
        args: list[str] = []
        i = 0
        while i < len(raw):
            token = raw[i]
            expanded = expand_context_unsafe(token, context)
            # Treat "--flag <value>" as a pair (rc-astro flags always take a value).
            if token.startswith("--") and i + 1 < len(raw) and not raw[i + 1].startswith("--"):
                value_raw = raw[i + 1]
                value = expand_context_unsafe(value_raw, context)
                if _is_placeholder(value_raw) and _is_unset(value):
                    i += 2  # unset parameter -> omit the flag and its value
                    continue
                args.append(expanded)
                args.append(value)
                i += 2
                continue
            args.append(expanded)
            i += 1

        if "--json" not in args:
            args = ["--json", *args]
        return args

    def _run(
        self,
        cwd: str,
        commands: str | list[str],
        context: dict = {},
        log_out: io.TextIOWrapper | None = None,
        **kwargs: Any,
    ) -> None:
        """Execute rc-astro with the specified command line arguments.

        Progress is published on the event bus rather than drawn here: the CLI's
        ``ProcessingView`` and the GUI both render it, and a tool-owned Rich
        ``Live``/``Progress`` would fight the observer's display for the console.
        """
        args = self.build_args(commands, context)
        cmd = f"{self.executable_path} " + " ".join(args)

        # rc-astro refuses to run if the output already exists; remove it first.
        try:
            out_idx = args.index("--output")
            out_path = args[out_idx + 1]
            if os.path.exists(out_path):
                logger.debug(f"Removing existing output file: {out_path}")
                os.remove(out_path)
        except (ValueError, IndexError):
            pass

        def on_line(line: str) -> None:
            obj = parse_json_line(line)
            if obj is None:
                return
            event = obj.get("event")
            if event == "progress":
                done = float(obj.get("done", 0.0))
                publish_tool_progress(cmd, percent=done, message="Processing")
            elif event == "status":
                message = obj.get("message") or obj.get("phase") or ""
                if message:
                    # No percentage in a status line, so this is a phase-only
                    # update; consumers must not reset their bar to zero.
                    publish_tool_progress(cmd, message=message)
            elif event == "info":
                logger.debug(f"[rc-astro] {obj}")

        # ``--json`` makes stdout a structured event stream, so declare it:
        # log renderers then skip these protocol frames (the useful parts are
        # already published as tool.progress) while log_out keeps them raw.
        tool_run_streaming(
            cmd,
            cwd,
            on_line=on_line,
            timeout=self.timeout,
            log_out=log_out,
            stdout_mime="json",
        )
