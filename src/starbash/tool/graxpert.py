"""GraXpert tool integration."""

import io
import logging
from typing import Any

from starbash.tool.base import ExternalTool, Tool, ToolSeverity, tool_run
from starbash.tool.context import expand_context_list, expand_context_unsafe

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
        **kwargs: dict[str, Any],
    ) -> None:
        """Executes Graxpert with the specified command line arguments"""

        expanded_args = None
        if isinstance(commands, list):
            # expand each argument separately and join into a single command line
            expanded_args = expand_context_list(commands, context)
        else:
            raise ValueError("GraxpertTool requires commands specified as a list")

        # it is very important that we import graxpert.api_run here and not at the top level, we don't want to pull in graxpert unless user
        # is using it.
        from graxpert import api_run

        api_run(expanded_args, kwargs)


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
        **kwargs: dict[str, Any],
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
        cmd = f"{self.executable_path} {expanded}"

        tool_run(cmd, cwd, timeout=self.timeout, log_out=log_out)
