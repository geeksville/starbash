"""GraXpert tool integration."""

import io
import logging
from typing import Any

from starbash.tool.base import ExternalTool, Tool, tool_run
from starbash.tool.context import expand_context_list, expand_context_unsafe

logger = logging.getLogger(__name__)

__all__ = ["GraxpertBuiltinTool", "GraxpertExternalTool"]


class GraxpertBuiltinTool(Tool):
    """Expose Graxpert as a tool"""

    def __init__(self) -> None:
        super().__init__("GraXpert")

    def _run(
        self, cwd: str, commands: str | list[str], context: dict = {}, **kwargs: dict[str, Any]
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

        super().__init__("GraXpert", commands, "https://graxpert.com/")

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
