"""RC-Astro tool integration (BlurXTerminator, NoiseXTerminator, ...)."""

import io
import json
import logging
import os
import re
from typing import Any

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from starbash.tool.base import ExternalTool, tool_run_streaming
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

    manages_own_progress = True

    def __init__(self) -> None:
        super().__init__("rc-astro", ["rc-astro"], "https://www.rc-astro.com/stand-alone-rc-astro-tools/")

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
        **kwargs: dict[str, Any],
    ) -> None:
        """Execute rc-astro with the specified command line arguments."""
        from starbash import console  # Lazy import to avoid circular dependency

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

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"[bold]{self.name}[/bold]", total=100.0)

            def on_line(line: str) -> None:
                obj = parse_json_line(line)
                if obj is None:
                    return
                event = obj.get("event")
                if event == "progress":
                    done = float(obj.get("done", 0.0))
                    message = "Processing"
                    progress.update(task, completed=done, description=f"[bold]{self.name}[/bold]: {message}")
                elif event == "status":
                    message = obj.get("message") or obj.get("phase") or ""
                    progress.update(task, description=f"[bold]{self.name}[/bold]: {message}")
                elif event == "info":
                    logger.debug(f"[rc-astro] {obj}")

            tool_run_streaming(
                cmd, cwd, on_line=on_line, timeout=self.timeout, log_out=log_out
            )
