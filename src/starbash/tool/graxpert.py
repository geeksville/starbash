"""GraXpert tool integration."""

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from starbash.tool.base import (
    ExternalTool,
    Tool,
    ToolSeverity,
    quote_executable,
    tool_run,
    tool_run_in_process,
)
from starbash.tool.context import expand_context_list, expand_context_unsafe
from starbash.tool.ranges import _input_range, _restore_scaled_output, _write_scaled_input

logger = logging.getLogger(__name__)

__all__ = ["GraxpertBuiltinTool", "GraxpertExternalTool"]


class GraxpertBuiltinTool(Tool):
    """Expose Graxpert as a tool"""

    #: GraXpert ships inside Starbash (the ``graxpert`` Python package), so it is
    #: always available; the severity is only a hint for the warning UI.
    severity = ToolSeverity.OPTIONAL

    def __init__(self) -> None:
        super().__init__("GraXpert")

    def _run(
        self,
        cwd: str,
        commands: str | list[str],
        context: dict = {},
        log_out: io.TextIOWrapper | None = None,
        **kwargs: Any,
    ) -> None:
        """Executes Graxpert with the specified command line arguments

        GraXpert runs *in process* (we call its ``api_run`` rather than a
        subprocess), so its log output would otherwise go straight to the root
        logger's handler and be drawn over the CLI's live run display.  Wrap the
        call so those lines are published as tool output events - the same way an
        external tool's stdout/stderr is streamed - and land in ``log_out``.
        """

        expanded_args = None
        if isinstance(commands, list):
            # expand each argument separately and join into a single command line
            expanded_args = expand_context_list(commands, context)
        else:
            raise ValueError("GraxpertTool requires commands specified as a list")

        # it is very important that we import graxpert.api_run here and not at the top level, we don't want to pull in graxpert unless user
        # is using it.
        import graxpert
        from graxpert import api_run

        package_file = graxpert.__file__
        assert package_file is not None, "graxpert is a real package, so __file__ is set"

        # Only the background recipe opts into range preservation. GraXpert's FITS
        # loader otherwise rescales *all* pixels when even one is outside [0, 1].
        preserve_range = kwargs.pop("preserve_input_range", None) == "true"
        if not preserve_range:
            self._run_api(api_run, expanded_args, kwargs, package_file, cwd, log_out)
            return

        if len(expanded_args) != 5 or expanded_args[:3] != [
            "-cmd",
            "background-extraction",
            "-output",
        ]:
            raise ValueError("preserve_input_range requires a background-extraction input/output")
        source = Path(expanded_args[4])
        destination = Path(expanded_args[3])
        minimum, maximum = _input_range(source)
        offset = min(0.0, minimum)
        scale = max(1.0, maximum - offset)
        if scale == 1.0 and offset == 0.0:
            self._run_api(api_run, expanded_args, kwargs, package_file, cwd, log_out)
            return

        # GraXpert writes the final result itself; its temporary files must be
        # distinct per task and removed even if it fails.
        with tempfile.TemporaryDirectory(prefix="starbash-bge-", dir=cwd) as tmp:
            scaled_input = Path(tmp) / "input.fits"
            scaled_output = Path(tmp) / "output.fits"
            _write_scaled_input(source, scaled_input, offset, scale)
            args = [*expanded_args[:3], str(scaled_output), str(scaled_input)]
            self._run_api(api_run, args, kwargs, package_file, cwd, log_out)
            _restore_scaled_output(scaled_output, destination, offset, scale)

    @staticmethod
    def _run_api(
        api_run: Any,
        args: list[str],
        prefs: dict[str, Any],
        package_file: str,
        cwd: str,
        log_out: io.TextIOWrapper | None,
    ) -> None:
        """Keep GraXpert log/progress events identical with or without scaling."""
        with tool_run_in_process(
            f"graxpert {' '.join(args)}",
            source=os.path.dirname(package_file),
            cwd=cwd,
            log_out=log_out,
        ):
            api_run(args, prefs)


class GraxpertExternalTool(ExternalTool):
    """Expose Graxpert as a tool"""

    def __init__(self) -> None:
        commands: list[str] = ["graxpert", "GraXpert"]

        # Optional: the built-in GraXpert tool covers the same work, so this
        # only matters for users who prefer their own installed copy.
        super().__init__("GraXpert", commands, "https://graxpert.com/", ToolSeverity.OPTIONAL)

    def _run(
        self,
        cwd: str,
        commands: str | list[str],
        context: dict = {},
        log_out: io.TextIOWrapper | None = None,
        **kwargs: Any,
    ) -> None:
        """Executes Graxpert with the specified command line arguments"""

        expanded_args = None
        if isinstance(commands, list):
            # expand each argument separately and join into a single command line
            expanded_args = expand_context_list(commands, context)
            expanded = " ".join(expanded_args)
        else:
            expanded = expand_context_unsafe(commands, context)

        # Arguments look similar to: graxpert -cmd background-extraction -output /tmp/testout tests/test_images/real_crummy.fits
        cmd = f"{quote_executable(self.executable_path)} {expanded}"

        tool_run(cmd, cwd, timeout=self.timeout, log_out=log_out)
