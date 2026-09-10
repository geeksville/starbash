"""Top-level pages of the Starbash desktop GUI.

Each page is a :class:`~starbash.ui.qt.pages.base.Page` subclass that reads from
the shared application context and, for long operations, delegates to
:mod:`starbash.ui.qt.jobs` on a worker thread.
"""

from __future__ import annotations

from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.pages.dashboard import DashboardPage
from starbash.ui.qt.pages.masters import MastersPage
from starbash.ui.qt.pages.processing import ProcessingPage
from starbash.ui.qt.pages.publish import PublishPage
from starbash.ui.qt.pages.repositories import RepositoriesPage
from starbash.ui.qt.pages.sessions import SessionsPage
from starbash.ui.qt.pages.settings import SettingsPage
from starbash.ui.qt.pages.targets import TargetsPage
from starbash.ui.qt.pages.wizard import SetupWizard, run_setup_dialog

__all__ = [
    "Page",
    "DashboardPage",
    "SessionsPage",
    "MastersPage",
    "TargetsPage",
    "ProcessingPage",
    "RepositoriesPage",
    "PublishPage",
    "SettingsPage",
    "SetupWizard",
    "run_setup_dialog",
]
