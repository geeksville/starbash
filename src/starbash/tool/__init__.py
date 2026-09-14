"""Tool management and execution for starbash processing stages."""

from typing import Any

from starbash.tool.base import (
    ExternalTool,
    MissingToolError,
    Tool,
    ToolError,
    ToolSeverity,
    ToolStatus,
    plain_message,
    tool_run,
    tool_run_in_process,
)
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
from starbash.tool.rcastro import RCAstroTool
from starbash.tool.siril import SirilTool
from starbash.tool.starnet import StarnetTool

__all__ = [
    "Tool",
    "ToolError",
    "MissingToolError",
    "ExternalTool",
    "ToolSeverity",
    "ToolStatus",
    "plain_message",
    "tool_run",
    "tool_run_in_process",
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
    "RCAstroTool",
    "tools",
    "init_tools",
    "tool_statuses",
    "tool_status",
    "missing_tool_statuses",
    "set_tool_ignored",
]


def init_tools(tool_prefs: dict[str, Any]) -> None:
    """Preflight check all known tools to see if they are available

    Args:
        tool_prefs: The user config's ``[tool]`` section.  It is stored on
            :class:`Tool` so probes honour per-tool overrides (an explicit path)
            and the ``ignored`` flag, rather than looking at the PATH alone.
    """
    Tool.Preferences = tool_prefs

    for tool in tools.values():
        # Each tool is reported at a log level matching its severity - a missing
        # optional tool only logs at debug level (see Tool.preflight).
        tool.preflight()


# A dictionary mapping tool names to their respective tool instances.
tools: dict[str, Tool] = {
    tool.name.lower(): tool
    for tool in list[Tool](
        [SirilTool(), GraxpertBuiltinTool(), PythonTool(), RCAstroTool(), StarnetTool()]
    )
}


def tool_statuses() -> list[ToolStatus]:
    """Availability of every known tool, in registry order.

    The CLI and the GUI both render these, so neither front end has to know how a
    tool is probed - see :meth:`Tool.status`.
    """
    return [tool.status() for tool in tools.values()]


def tool_status(key: str) -> ToolStatus | None:
    """Availability of the tool registered as ``key``, or ``None`` if unknown."""
    tool = tools.get(key)
    return tool.status() if tool is not None else None


def missing_tool_statuses(*, include_ignored: bool = False) -> list[ToolStatus]:
    """The tools that are missing, most important first.

    Ignored tools are left out unless ``include_ignored`` is set, which is what
    makes the GUI's *Ignore* button stick; a *required* tool is never ignorable, so
    it always appears.
    """
    statuses = tool_statuses()
    if include_ignored:
        return [status for status in statuses if not status.available]
    missing = [status for status in statuses if status.needs_attention]
    # Most important first (stable sort, so ties keep registry order).
    return sorted(missing, key=lambda status: status.severity, reverse=True)


def set_tool_ignored(key: str, ignored: bool = True) -> None:
    """Remember that the user does not want to be warned about the tool ``key``.

    Only the in-memory preferences are updated here - persisting the choice (the
    GUI writes ``tool.<key>.ignored`` into the user config) is the caller's job,
    which is what keeps this module free of repo knowledge.  The change is visible
    to any later :meth:`Tool.status` call.
    """
    prefs = Tool.Preferences.get(key)
    if not isinstance(prefs, dict):
        prefs = {}
        Tool.Preferences[key] = prefs
    prefs["ignored"] = ignored
