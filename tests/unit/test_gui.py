"""Tests for the optional PySide6 desktop GUI.

Every test here is marked ``gui`` so the default test run (which excludes
``gui``) still passes on a machine without the optional ``gui`` extra.  Run them
with ``poetry run pytest -m gui`` after ``poetry install -E gui``.
"""

import numpy as np
import pytest

pytest.importorskip("PySide6")

from starbash import events  # noqa: E402
from starbash.ui.qt import QTSIDE6_IMPORT_HINT, GuiUnavailableError, qt_available  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context for GUI tests."""
    from starbash.app import Starbash

    with Starbash("test.gui") as sb:
        yield sb


@pytest.fixture(autouse=True)
def _clean_bus():
    """Give each test a pristine event bus."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


# --- availability ----------------------------------------------------------


def test_qt_available_matches_import():
    """qt_available() reflects whether PySide6 can actually be imported."""
    assert qt_available() is True


def test_gui_unavailable_error_mentions_the_extra():
    """The install hint tells the user exactly how to enable the GUI."""
    assert "gui" in QTSIDE6_IMPORT_HINT
    assert issubclass(GuiUnavailableError, RuntimeError)


# --- event bridge ----------------------------------------------------------


def test_bridge_forwards_core_events_to_qt_signals(qtbot):
    """Publishing on the core bus re-emits the event as a Qt signal."""
    from starbash.ui.qt.bridge import EventBusBridge

    bridge = EventBusBridge()
    with qtbot.waitSignal(bridge.received, timeout=1000) as blocker:
        events.publish(events.EVENT_TASK_STARTED, {"task": "stack", "title": "Stack"})

    assert blocker.args == [events.EVENT_TASK_STARTED, {"task": "stack", "title": "Stack"}]
    bridge.close()


def test_bridge_close_stops_delivery(qtbot):
    """After close(), the bridge no longer forwards events."""
    from starbash.ui.qt.bridge import EventBusBridge

    bridge = EventBusBridge()
    received = []
    bridge.received.connect(lambda kind, data: received.append(kind))

    bridge.close()
    events.publish("whatever")

    assert received == []


# --- table models ----------------------------------------------------------


def test_dict_table_model_renders_and_sorts(qtbot):
    """The model formats column values and orders rows on sort()."""
    from PySide6.QtCore import Qt

    from starbash.ui.qt.models import SESSION_COLUMNS, DictTableModel

    model = DictTableModel(SESSION_COLUMNS)
    model.set_rows(
        [
            {"object": "m31", "filter": "Ha", "num_images": 3},
            {"object": "m42", "filter": "OIII", "num_images": 9},
        ]
    )

    assert model.rowCount() == 2
    assert model.columnCount() == len(SESSION_COLUMNS)
    first = model.index(0, 0)
    assert model.data(first, Qt.ItemDataRole.DisplayRole) == "m31"

    model.sort(0, Qt.SortOrder.DescendingOrder)
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "m42"


def test_plain_row_accepts_sqlite_row(tmp_path):
    """plain_row() converts a sqlite3.Row into an ordinary dict."""
    import sqlite3

    from starbash.ui.qt.models import plain_row

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    row = connection.execute("SELECT 1 AS a, 'x' AS b").fetchone()

    assert plain_row(row) == {"a": 1, "b": "x"}


# --- services --------------------------------------------------------------


def test_load_sessions_and_selection_shape(app_context):
    """load_sessions/load_selection return plain, model-ready data."""
    from starbash.ui.qt.services import load_selection, load_sessions

    rows = load_sessions(app_context)
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)

    selection = load_selection(app_context)
    assert selection["summary"]["status"] == "all"
    assert selection["targets"] == []


def test_dashboard_stats_on_empty_db(app_context):
    """Headline counts are zero (not an error) for a freshly created database."""
    from starbash.ui.qt.services import dashboard_stats

    stats = dashboard_stats(app_context)
    assert stats["sessions"] == 0
    assert stats["frames"] == 0
    assert stats["integration_hours"] == 0.0


def test_load_masters_without_master_repo_is_empty(app_context):
    """A missing master repo yields an empty list rather than raising."""
    from starbash.ui.qt.services import load_masters

    assert load_masters(app_context) == []


def test_load_targets_without_processed_repo_is_empty(app_context):
    """A missing processed repo yields an empty target list."""
    from starbash.ui.qt.services import load_targets

    assert load_targets(app_context) == []


def test_target_stage_roundtrip(tmp_path):
    """save_target_stages writes the [[stages]] schema load_target_config reads."""
    from starbash.ui.qt.services import (
        TARGET_CONFIG_NAME,
        load_target_config,
        save_target_stages,
    )

    target_dir = tmp_path / "m31"
    (target_dir / TARGET_CONFIG_NAME).parent.mkdir(parents=True)

    assert load_target_config(str(target_dir)) == []

    save_target_stages(str(target_dir), used=["stack", "stretch"], excluded=["denoise"])

    stages = {entry["name"]: entry["excluded"] for entry in load_target_config(str(target_dir))}
    assert stages == {"stack": False, "stretch": False, "denoise": True}

    # Re-saving must flip a stage without losing the others.
    save_target_stages(str(target_dir), used=["denoise"], excluded=["stretch"])
    stages = {entry["name"]: entry["excluded"] for entry in load_target_config(str(target_dir))}
    assert stages["denoise"] is False
    assert stages["stretch"] is True
    assert stages["stack"] is False


# --- FITS rendering --------------------------------------------------------


def test_fits_to_qimage_renders_grayscale(qapp, tmp_path):
    """A FITS frame is stretched into a non-null QImage of the right size."""
    from astropy.io import fits

    from starbash.ui.qt.widgets.image_viewer import fits_to_qimage

    data = np.zeros((32, 48), dtype=np.float32)
    data[8:24, 8:40] = 1000.0
    path = tmp_path / "frame.fits"
    fits.PrimaryHDU(data).writeto(path)

    image = fits_to_qimage(path)

    assert not image.isNull()
    assert (image.width(), image.height()) == (48, 32)


def test_fits_to_qimage_rejects_empty_file(qapp, tmp_path):
    """A FITS file with no data raises a clear error rather than crashing."""
    from astropy.io import fits

    from starbash.ui.qt.widgets.image_viewer import fits_to_qimage

    path = tmp_path / "empty.fits"
    fits.PrimaryHDU().writeto(path)

    with pytest.raises(ValueError, match="no image data"):
        fits_to_qimage(path)


# --- theme -----------------------------------------------------------------


def test_create_application_applies_theme(qapp):
    """create_application() installs the dark stylesheet."""
    from starbash.ui.qt.app import create_application

    app = create_application([])
    assert "NavRail" in app.styleSheet()


# --- main window and pages -------------------------------------------------


@pytest.fixture
def bus():
    """A live event bridge, closed after the test."""
    from starbash.ui.qt.bridge import EventBusBridge

    bridge = EventBusBridge()
    yield bridge
    bridge.close()


def test_main_window_builds_every_page(qtbot, app_context):
    """The window shows one nav entry and one page per configured page."""
    from starbash.ui.qt.main_window import PAGE_CLASSES, MainWindow
    from starbash.ui.qt.pages import DashboardPage

    window = MainWindow(app_context)
    qtbot.addWidget(window)

    assert [page.nav_title for page in window.pages()] == [c.nav_title for c in PAGE_CLASSES]
    assert isinstance(window.current_page(), DashboardPage)


def test_every_page_refreshes_without_error(qtbot, app_context):
    """Switching to each page reloads it against the real database cleanly."""
    from starbash.ui.qt.main_window import MainWindow

    window = MainWindow(app_context)
    qtbot.addWidget(window)

    for index in range(len(window.pages())):
        window.show_page(index)
        assert window.current_page() is window.pages()[index]


def test_selection_panel_writes_selection(qtbot, app_context):
    """Applying the panel persists the same Selection the CLI writes."""
    from PySide6.QtCore import Qt

    from starbash.ui.qt.widgets import SelectionPanel

    panel = SelectionPanel()
    qtbot.addWidget(panel)
    panel.load(app_context)

    # The panel exposes no setter API, so drive its widgets directly and assert
    # the *persisted selection* - the behaviour that actually matters.
    panel._targets.setText("m31, m42")
    panel._filters.setText("Ha")

    with qtbot.waitSignal(panel.selectionChanged, timeout=1000):
        qtbot.mouseClick(panel._apply, Qt.MouseButton.LeftButton)

    assert app_context.selection.targets == ["m31", "m42"]
    assert app_context.selection.filters == ["Ha"]


def test_selection_panel_clear_resets_everything(qtbot, app_context):
    """Clear empties the criteria, matching `sb select any`."""
    from PySide6.QtCore import Qt

    from starbash.ui.qt.widgets import SelectionPanel

    panel = SelectionPanel()
    qtbot.addWidget(panel)
    panel.load(app_context)
    panel._targets.setText("m31")
    qtbot.mouseClick(panel._apply, Qt.MouseButton.LeftButton)
    assert app_context.selection.targets == ["m31"]

    with qtbot.waitSignal(panel.selectionChanged, timeout=1000):
        qtbot.mouseClick(panel._clear, Qt.MouseButton.LeftButton)

    assert app_context.selection.is_empty()


def test_processing_page_renders_core_events(qtbot, app_context, bus):
    """Core events drive the task tree, progress bar and log pane."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    events.publish(events.EVENT_TASK_STARTED, {"task": "stack", "title": "Stack lights"})
    events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "working 42%"})
    events.publish(events.EVENT_TOOL_PROGRESS, {"percent": 42})
    events.publish(
        events.EVENT_TASK_FINISHED,
        {"task": "stack", "title": "Stack lights", "success": True},
    )

    assert page._tasks.topLevelItemCount() == 1
    assert page._tasks.topLevelItem(0).text(1) == "ok"
    assert page._progress.value() == 42
    log_text = page._log.toPlainText()
    assert "42%" in log_text
    assert "Stack lights" in log_text


def test_repositories_page_reports_indexing_progress(qtbot, app_context, bus):
    """Re-index progress events update the page's progress bar."""
    from starbash.ui.qt.pages.repositories import RepositoriesPage

    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)

    events.publish(
        events.EVENT_REINDEX_PROGRESS,
        {"repo": "file:///tmp/img", "done": 3, "total": 10},
    )

    assert page._progress.maximum() == 10
    assert page._progress.value() == 3


# --- setup wizard ----------------------------------------------------------


def test_setup_wizard_persists_preferences(qtbot, app_context):
    """The wizard writes the same user config keys as `sb user setup`."""
    from starbash.ui.qt.pages.wizard import SetupWizard

    wizard = SetupWizard(app_context)
    qtbot.addWidget(wizard)
    wizard._name.setText("Ada Lovelace")
    wizard._email.setText("ada@example.com")
    wizard._analytics.setChecked(True)
    # Leave this off so the test doesn't create repositories / start an index run.
    wizard._create_dirs.setChecked(False)

    wizard.apply()

    repo = app_context.user_repo
    assert repo.get("user.name") == "Ada Lovelace"
    assert repo.get("user.email") == "ada@example.com"
    assert repo.get("analytics.enabled") is True
