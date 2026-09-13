"""Reusable widgets for the Starbash GUI."""

from __future__ import annotations

from starbash.ui.qt.widgets.busy_indicator import BusyIndicator, Spinner
from starbash.ui.qt.widgets.file_links import LINK_ROLE, LinkDecorator, open_link, set_link
from starbash.ui.qt.widgets.github_login import GitHubSetupDialog, run_github_setup
from starbash.ui.qt.widgets.hover_preview import HoverPreview
from starbash.ui.qt.widgets.image_viewer import ImageViewer
from starbash.ui.qt.widgets.log_view import LogView
from starbash.ui.qt.widgets.selection_panel import SelectionPanel
from starbash.ui.qt.widgets.stat_card import StatCard
from starbash.ui.qt.widgets.tool_warning import ToolWarningBar, ToolWarningPanel

__all__ = [
    "BusyIndicator",
    "Spinner",
    "GitHubSetupDialog",
    "run_github_setup",
    "HoverPreview",
    "ImageViewer",
    "LINK_ROLE",
    "LinkDecorator",
    "LogView",
    "SelectionPanel",
    "StatCard",
    "ToolWarningBar",
    "ToolWarningPanel",
    "open_link",
    "set_link",
]
