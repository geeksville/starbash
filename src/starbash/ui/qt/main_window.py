"""The main window: a navigation rail beside a stack of pages."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from starbash.app import Starbash
from starbash.ui.qt.bridge import EventBusBridge
from starbash.ui.qt.pages import (
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

__all__ = ["MainWindow"]

#: Pages in navigation order.
PAGE_CLASSES = [
    DashboardPage,
    SessionsPage,
    MastersPage,
    TargetsPage,
    ProcessingPage,
    RepositoriesPage,
    PublishPage,
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
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
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

    def show_page(self, index: int) -> None:
        """Switch to the page at ``index`` (which refreshes it)."""
        self._nav.setCurrentRow(index)

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

        page = self.current_page()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    # --- internals --------------------------------------------------------
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
        if run_setup_dialog(self._sb, self):
            self.reload_context()

    def _on_reindex_requested(self) -> None:
        """Jump to the Repositories page, where re-indexing lives."""
        for index in range(self._stack.count()):
            if isinstance(self._stack.widget(index), RepositoriesPage):
                self._nav.setCurrentRow(index)
                return

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
