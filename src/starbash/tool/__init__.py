"""Tool management and execution for starbash processing stages."""

from starbash.tool.base import ExternalTool, MissingToolError, Tool, ToolError, tool_run
from starbash.tool.context import (
    _SafeFormatter,
    expand_context,
    expand_context_list,
    expand_context_unsafe,
    make_safe_globals,
    strip_comments,
)
from starbash.tool.graxpert import GraxpertBuiltinTool, GraxpertExternalTool
from starbash.tool.python import PythonScriptError, PythonTool
from starbash.tool.siril import SirilTool

__all__ = [
    "Tool",
    "ToolError",
    "MissingToolError",
    "ExternalTool",
    "tool_run",
    "_SafeFormatter",
    "expand_context",
    "expand_context_unsafe",
    "expand_context_list",
    "make_safe_globals",
    "strip_comments",
    "SirilTool",
    "GraxpertBuiltinTool",
    "GraxpertExternalTool",
    "PythonTool",
    "PythonScriptError",
    "tools",
    "preflight_tools",
]


def preflight_tools() -> None:
    """Preflight check all known tools to see if they are available"""
    for tool in tools.values():
        if isinstance(tool, ExternalTool):
            tool.preflight()


# A dictionary mapping tool names to their respective tool instances.
tools: dict[str, Tool] = {
    tool.name.lower(): tool
    for tool in list[Tool]([SirilTool(), GraxpertBuiltinTool(), PythonTool()])
}
