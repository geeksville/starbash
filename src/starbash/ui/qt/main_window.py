"""The main window: a navigation rail beside a stack of pages."""

from __future__ import annotations

import logging
from typing import TypeVar

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from starbash.app import Starbash
from starbash.tool import set_tool_ignored
from starbash.ui.qt.bridge import EventBusBridge
from starbash.ui.qt.pages import (
    ACTION_PROCESS,
    ACTION_TARGETS,
    DashboardPage,
    MastersPage,
    ProcessingPage,
    PublishPage,
    RepositoriesPage,
    SessionsPage,
    SettingsPage,
    TargetsPage,
    run_setup_dialog,
)
from starbash.ui.qt.widgets import ToolWarningPanel

__all__ = ["MainWindow"]

logger = logging.getLogger(__name__)

#: Type variable for :meth:`MainWindow.show_page_of_type`.
_PageT = TypeVar("_PageT")

#: Pages in navigation order.
PAGE_CLASSES = [
    DashboardPage,
    TargetsPage,
    SessionsPage,
    ProcessingPage,
    PublishPage,
    RepositoriesPage,
    MastersPage,
    SettingsPage,
]


class MainWindow(QMainWindow):
    """Hosts every page and owns the event-bus bridge and app context."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Starbash")
        self.resize(1280, 820)

        self._bus = EventBusBridge(self)
        self._sb = sb
        #: Set while we programmatically change the nav selection, so the
        #: currentRowChanged handler doesn't treat it as a user navigation.
        self._switching = False

        self._nav = QListWidget()
        self._nav.setObjectName("NavRail")
        self._nav.setFixedWidth(190)

        self._stack = QStackedWidget()
        self._stack.setObjectName("CentralArea")

        for page_class in PAGE_CLASSES:
            page = page_class(self._sb, self._bus)
            page.status.connect(self.statusBar().showMessage)
            context_changed = getattr(page, "contextChanged", None)
            if context_changed is not None:
                context_changed.connect(self.reload_context)
            self._stack.addWidget(page)
            self._nav.addItem(QListWidgetItem(page.nav_title))

        self._nav.currentRowChanged.connect(self._on_page_changed)

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # Missing-tool warnings sit above the pages, so they are visible whatever
        # page the user is on; the panel hides itself when every tool is present.
        self._warnings = ToolWarningPanel(self._on_ignore_tool, central)
        self._warnings.status.connect(self.statusBar().showMessage)
        column.addWidget(self._warnings)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._nav)
        row.addWidget(self._stack, 1)
        column.addLayout(row, 1)
        self.setCentralWidget(central)

        self._build_menu()
        self.statusBar().showMessage("Ready.")
        self._nav.setCurrentRow(0)

    # --- public API -------------------------------------------------------
    @property
    def sb(self) -> Starbash:
        """The current application context."""
        return self._sb

    def current_page(self) -> object:
        """Return the page currently shown."""
        return self._stack.currentWidget()

    def pages(self) -> list[object]:
        """Return every page widget, in navigation order."""
        return [self._stack.widget(index) for index in range(self._stack.count())]

    @property
    def warnings(self) -> ToolWarningPanel:
        """The missing-tool warning bars shown above the pages."""
        return self._warnings

    def show_page(self, index: int) -> None:
        """Switch to the page at ``index`` (which refreshes it)."""
        self._nav.setCurrentRow(index)

    def show_page_of_type(self, page_type: type[_PageT]) -> _PageT | None:
        """Switch to the first page of ``page_type``, returning it (or ``None``).

        Switching through the nav rail is what refreshes the page, so a caller
        gets a fully-loaded page back and can drive it immediately.
        """
        for index in range(self._stack.count()):
            page = self._stack.widget(index)
            if isinstance(page, page_type):
                self._nav.setCurrentRow(index)
                return page
        return None

    def reload_context(self) -> None:
        """Rebuild the app context (e.g. after a repository was added).

        The repository manager is loaded once at startup, so a repo added from a
        worker thread is only visible after we rebuild.  Pages are simply
        re-pointed at the fresh context, which keeps this cheap.
        """
        try:
            self._sb.close()
        except Exception:  # noqa: BLE001 - closing a half-built context must not block reload
            pass

        self._sb = Starbash("gui")
        for index in range(self._stack.count()):
            self._stack.widget(index).sb = self._sb  # type: ignore[attr-defined]

        # A fresh context re-reads the tool preferences, so a newly ignored (or
        # newly configured) tool changes which warnings apply.
        self._warnings.refresh()

        page = self.current_page()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    # --- internals --------------------------------------------------------
    def _on_ignore_tool(self, key: str) -> None:
        """Stop warning about a missing tool, for good.

        The choice is persisted as ``tool.<key>.ignored`` in the user config, which
        the core reads back through
        :func:`starbash.tool.missing_tool_statuses` - so it survives a restart and
        also silences the CLI's startup warning.  If it cannot be written we keep
        the bar and say so, rather than pretending the warning is gone.
        """
        try:
            self._sb.user_repo.set(f"tool.{key}.ignored", True)
            self._sb.user_repo.write_config()
        except Exception as exc:  # noqa: BLE001 - a failed preference write must not crash the GUI
            logger.warning(f"Could not save the ignored-tool preference: {exc}")
            self.statusBar().showMessage(f"Could not save the preference: {exc}")
            return

        set_tool_ignored(key)  # in memory too, so the bar goes away now
        self.statusBar().showMessage(f"Starbash will stop warning about {key}.")

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")

        setup = QAction("Run setup wizard…", self)
        setup.triggered.connect(self._on_setup)
        menu.addAction(setup)

        reindex = QAction("Re-index all repositories", self)
        reindex.triggered.connect(self._on_reindex_requested)
        menu.addAction(reindex)

        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

    def _on_page_changed(self, row: int) -> None:
        if row < 0 or self._switching:
            return

        previous = self._stack.currentIndex()
        if previous != row and not self._page_can_leave(previous):
            # The page being left refused (unsaved edits): undo the navigation.
            self._switching = True
            try:
                self._nav.setCurrentRow(previous)
            finally:
                self._switching = False
            return

        # Switch the visible page *and* reload it - forgetting the first half is
        # the classic "nav clicks do nothing" bug.
        self._stack.setCurrentIndex(row)
        page = self._stack.widget(row)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()
        subtitle = getattr(page, "subtitle", "")
        if subtitle:
            self.statusBar().showMessage(subtitle)

    def _page_can_leave(self, index: int) -> bool:
        """Ask the page at ``index`` whether it is safe to navigate away."""
        if index < 0:
            return True
        page = self._stack.widget(index)
        can_leave = getattr(page, "can_leave", None)
        return bool(can_leave()) if callable(can_leave) else True

    def _on_setup(self) -> None:
        """*File ▸ Run setup wizard…* — re-runnable at any time."""
        self.run_setup_wizard()

    def run_setup_wizard(self) -> None:
        """Show the setup wizard, then act on how the user left it.

        Public because :mod:`starbash.ui.qt.app` schedules it on the first run,
        once the event loop is running.
        """
        self._apply_setup_action(run_setup_dialog(self._sb, self))

    def _apply_setup_action(self, action: str | None) -> None:
        """Reload what the wizard changed, then honour its closing action.

        The reload comes first: the wizard may have created output folders or
        added an image folder, and the pages must see those before a run starts.
        """
        self.reload_context()

        if action == ACTION_PROCESS:
            # An empty selection means "every session" - the CLI's `sb select any`.
            self._sb.selection.clear()
            page = self.show_page_of_type(ProcessingPage)
            if page is not None:
                page.start_run()
        elif action == ACTION_TARGETS:
            self.show_page_of_type(TargetsPage)

    def _on_reindex_requested(self) -> None:
        """Jump to the Repositories page, where re-indexing lives."""
        self.show_page_of_type(RepositoriesPage)

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Ask about unsaved work, then release the bridge and app context."""
        if not self._page_can_leave(self._stack.currentIndex()):
            ignore = getattr(event, "ignore", None)
            if callable(ignore):
                ignore()
            return

        self._bus.close()
        try:
            self._sb.close()
        except Exception:  # noqa: BLE001 - never block shutdown
            pass
        super().closeEvent(event)  # type: ignore[arg-type]
