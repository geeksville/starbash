"""Tests for the PySide6 desktop GUI.

PySide6 is a normal dependency, so these tests run as part of the default suite.
They build real widgets, which needs a Qt platform plugin: ``tests/conftest.py``
sets ``QT_QPA_PLATFORM=offscreen`` so they work headless.  If Qt cannot start at
all on this machine the whole module skips instead of failing.
"""

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    _QApplication.instance() or _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

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


def test_gui_unavailable_error_explains_reinstall():
    """The hint names PySide6 and tells the user to reinstall."""
    assert "PySide6" in QTSIDE6_IMPORT_HINT
    assert "reinstall" in QTSIDE6_IMPORT_HINT.lower()
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


def test_integration_column_renders_approximately_whole_minutes(qapp):
    """The sessions table shows integration as compact whole minutes, not seconds."""
    from starbash.ui.qt.models import SESSION_COLUMNS

    column = next(c for c in SESSION_COLUMNS if c.key == "exptime_total")

    assert column.render({"exptime_total": 25440.0}) == "424"
    assert column.render({"exptime_total": 60}) == "1"
    assert column.render({"exptime_total": 4.333699999999999}) == "0"
    assert column.render({"exptime_total": None}) == ""
    assert column.render({}) == ""


def _seed_session(
    sb,
    *,
    target: str,
    start: str,
    end: str,
    num_images: int,
    exptime_total: float,
) -> None:
    """Insert one image plus its session, so stats have real numbers to report.

    Keys go through ``get_column_name`` exactly like the real indexing path, so the
    session row is keyed by SQL column name (``num_images``/``exptime_total``).
    """
    from starbash.database import Database, get_column_name

    repo_url = "file:///tmp/gui_test_repo"
    sb.db.upsert_repo(repo_url)
    image_id = sb.db.upsert_image(
        {
            "path": f"{target}-{start}.fits",
            "DATE-OBS": start,
            "DATE": start[:10],
            "IMAGETYP": "LIGHT",
            "FILTER": "Ha",
            "OBJECT": target,
            "TELESCOP": "Test Scope",
            "EXPTIME": 120.0,
        },
        repo_url,
    )
    sb.db.upsert_session(
        {
            get_column_name(Database.START_KEY): start,
            get_column_name(Database.END_KEY): end,
            get_column_name(Database.FILTER_KEY): "Ha",
            get_column_name(Database.IMAGETYP_KEY): "LIGHT",
            get_column_name(Database.OBJECT_KEY): target,
            get_column_name(Database.TELESCOP_KEY): "Test Scope",
            get_column_name(Database.NUM_IMAGES_KEY): num_images,
            get_column_name(Database.EXPTIME_TOTAL_KEY): exptime_total,
            get_column_name(Database.EXPTIME_KEY): 120.0,
            get_column_name(Database.IMAGE_DOC_KEY): image_id,
        }
    )


def test_dashboard_stats_counts_frames_and_integration(app_context):
    """Dashboard totals come from real session rows.

    Regression guard: session rows are keyed by SQL column name, so reading the
    metadata-style ``Database.*_KEY`` constants directly silently yields 0.
    """
    from starbash.ui.qt.services import dashboard_stats, load_sessions

    _seed_session(
        app_context,
        target="sh2126",
        start="2026-09-01T22:00:00",
        end="2026-09-01T23:00:00",
        num_images=10,
        exptime_total=3600.0,
    )
    _seed_session(
        app_context,
        target="sh2126",
        start="2026-09-02T22:00:00",
        end="2026-09-02T23:00:00",
        num_images=5,
        exptime_total=1800.0,
    )

    stats = dashboard_stats(app_context)

    assert stats["sessions"] == 2
    assert stats["frames"] == 15  # 10 + 5
    assert stats["integration_hours"] == 1.5  # (3600 + 1800) / 3600

    # And the rows the table receives carry the raw SQL-keyed values.
    rows = load_sessions(app_context)
    totals = sorted(row["exptime_total"] for row in rows)
    assert totals == [1800.0, 3600.0]


def test_dashboard_table_does_not_stretch_last_column(qtbot, app_context):
    """The last column keeps its declared width, so integration stays compact."""
    from starbash.ui.qt.models import SESSION_COLUMNS
    from starbash.ui.qt.pages import DashboardPage

    page = DashboardPage(app_context, None)
    qtbot.addWidget(page)

    header = page._table.horizontalHeader()
    assert header.stretchLastSection() is False

    last = len(SESSION_COLUMNS) - 1
    assert page._table.columnWidth(last) == SESSION_COLUMNS[last].width


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


def test_load_masters_resolves_absolute_paths_for_preview(app_context, tmp_path, qapp):
    """Master rows must resolve to a real file, so their preview can open it.

    Regression guard: ``get_master_images()`` returned repo-relative paths only, so
    every master/flat preview failed with "No such file or directory".
    """
    from astropy.io import fits

    from starbash.ui.qt.services import load_masters
    from starbash.ui.qt.widgets.image_viewer import load_image_file

    repo_dir = tmp_path / "master_repo"
    repo_dir.mkdir()
    hdu = fits.PrimaryHDU(np.zeros((8, 8), dtype=np.float32))
    hdu.header["DATE-OBS"] = "2026-07-11T05:10:08"
    hdu.header["IMAGETYP"] = "FLAT"
    hdu.header["FILTER"] = "Ha"
    master_file = repo_dir / "master_flat_Ha.fits"
    hdu.writeto(master_file)

    # Index it through the real path, so the row is keyed like production data.
    app_context.add_local_repo(str(repo_dir), repo_type="master")

    rows = load_masters(app_context)
    assert len(rows) == 1, f"expected the indexed master, got {rows}"

    row = rows[0]
    assert row["abspath"] == str(master_file)
    assert Path(row["abspath"]).is_file()
    assert row["basename"] == "master_flat_Ha.fits"

    # And the row really is previewable (the thing the user sees).
    assert not load_image_file(row["abspath"]).isNull()


# --- application icon ------------------------------------------------------


def test_app_icon_is_packaged_and_decodes(qapp):
    """The window icon asset ships inside the package and decodes to a pixmap."""
    from importlib import resources

    from starbash.ui.qt.theme import APP_ICON_NAME, load_app_icon

    asset = resources.files("starbash.assets").joinpath(APP_ICON_NAME)
    assert asset.is_file(), f"icon not packaged: starbash/assets/{APP_ICON_NAME}"

    icon = load_app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(64, 64).isNull()


def test_create_application_sets_the_window_icon(qapp):
    """The QApplication carries an icon, which is what the title bar shows."""
    from starbash.ui.qt.app import create_application

    app = create_application([])
    assert not app.windowIcon().isNull()


def test_load_app_icon_tolerates_a_missing_asset(monkeypatch, qapp):
    """A packaging mistake yields no icon rather than crashing start-up."""
    from starbash.ui.qt import theme

    monkeypatch.setattr(theme, "APP_ICON_NAME", "definitely-not-a-real-icon.png")
    assert theme.load_app_icon().isNull()


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


# --- checkboxes ------------------------------------------------------------


def _indicator_pixels(box: QWidget) -> list[QColor]:
    """Colours of the checkbox's indicator area (its leftmost ~18 columns).

    The stylesheet pins the indicator to the left edge and the label starts after
    ``spacing``, so this window contains the box and none of the text.
    """
    image = box.grab().toImage()
    return [
        image.pixelColor(x, y) for x in range(min(18, image.width())) for y in range(image.height())
    ]


def _luminance(colour: QColor) -> float:
    """Rough perceived brightness (0-255), enough to answer "can I see it?"."""
    return (colour.red() + colour.green() + colour.blue()) / 3


def _is_near(colour: QColor, other: QColor, tolerance: int = 40) -> bool:
    return (
        abs(colour.red() - other.red()) < tolerance
        and abs(colour.green() - other.green()) < tolerance
        and abs(colour.blue() - other.blue()) < tolerance
    )


def test_an_unchecked_box_draws_a_visible_outline(qtbot, qapp):
    """Regression: the indicator was a dark box on a dark panel - invisible.

    The dark palette makes Fusion's native indicator use ``Base`` (#171d22) plus a
    black border, so it vanished into the page.  It is now drawn explicitly, and
    this renders a real checkbox to prove the outline is actually there.
    """
    from PySide6.QtWidgets import QCheckBox

    from starbash.ui.qt import theme

    theme.apply_theme(qapp)
    box = QCheckBox("Send anonymous crash reports and usage data")
    qtbot.addWidget(box)
    box.resize(320, 28)
    box.show()
    qtbot.waitExposed(box)

    assert box.isChecked() is False
    # An outline must be noticeably lighter than the #10161b fill behind it.
    assert max(_luminance(colour) for colour in _indicator_pixels(box)) > 70


def test_a_checked_box_is_filled_with_the_accent_and_a_tick(qtbot, qapp):
    """A checked box shows the accent colour and a light tick, not an empty hole."""
    from PySide6.QtWidgets import QCheckBox

    from starbash.ui.qt import theme

    theme.apply_theme(qapp)
    box = QCheckBox("Send anonymous crash reports and usage data")
    qtbot.addWidget(box)
    box.resize(320, 28)
    box.show()
    qtbot.waitExposed(box)

    box.setChecked(True)
    pixels = _indicator_pixels(box)

    accent = QColor(theme.ACCENT)
    assert sum(1 for colour in pixels if _is_near(colour, accent)) > 50
    # ...plus the tick glyph itself, which is white.
    assert sum(1 for colour in pixels if min(colour.red(), colour.green(), colour.blue()) > 200) >= 5


def test_the_checkmark_is_packaged_and_referenced_by_the_stylesheet(qapp):
    """The tick is a real, packaged asset and the QSS points at it by path."""
    from starbash.ui.qt import theme

    path = theme.checkmark_path()
    assert path is not None, "checkmark asset not found next to the app icon"
    assert Path(path).is_file()
    assert not QPixmap(path).isNull()
    assert f'image: url("{path}")' in theme.STYLESHEET


def test_a_missing_checkmark_only_drops_the_tick(monkeypatch, qapp):
    """Best effort: no glyph means a solid accent box, not a broken stylesheet."""
    from starbash.ui.qt import theme

    monkeypatch.setattr(theme, "CHECKMARK_NAME", "definitely-not-a-real-check.png")
    assert theme.checkmark_path() is None



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


def _child_of_kind(parent, kind):
    """First child of ``parent`` whose ``UserRole`` kind matches (or None)."""
    for index in range(parent.childCount()):
        child = parent.child(index)
        if child.data(0, Qt.ItemDataRole.UserRole) == kind:
            return child
    return None


def _child_named(parent, kind, name):
    """Child of ``parent`` matching both its kind and its stored name (or None)."""
    for index in range(parent.childCount()):
        child = parent.child(index)
        if (
            child.data(0, Qt.ItemDataRole.UserRole) == kind
            and child.data(0, Qt.ItemDataRole.UserRole + 1) == name
        ):
            return child
    return None



def test_processing_page_renders_core_events(qtbot, app_context, bus):
    """Core events drive the nested run tree, progress bar and per-task log."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    run = {
        "target": "M31",
        "output_url": "file:///out",
        "is_master": False,
        "stages": [
            {
                "name": "stack",
                "status": "running",
                "excluded": False,
                "dependencies": [],
                "outputs": [{"label": "stack.fits", "url": "file:///out/stack.fits"}],
                "logs": [],
                "tasks": [],
            }
        ],
    }
    events.publish(events.EVENT_RUN_STARTED, {"target": "M31"})
    events.publish(events.EVENT_STAGE_RESULT, {"result": None, "run": run})
    events.publish(
        events.EVENT_TASK_STARTED,
        {"task": "stack", "title": "Stack lights", "target": "M31", "stage": "stack"},
    )
    events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "working 42%"})
    events.publish(events.EVENT_TOOL_PROGRESS, {"percent": 42})

    assert page._tasks.topLevelItemCount() == 1
    target_item = page._tasks.topLevelItem(0)
    assert target_item.text(0) == "M31"
    assert target_item.isExpanded()
    assert target_item.childCount() == 1
    stage_item = target_item.child(0)
    assert "stack" in stage_item.text(0)

    # The task row (created by TASK_STARTED) has a collapsible Log node, and the
    # streamed tool line lands *inside it* - not loose under the stage.
    task_item = _child_of_kind(stage_item, "task")
    assert task_item is not None
    assert "Stack lights" in task_item.text(0)
    log_node = _child_of_kind(task_item, "log")
    assert log_node is not None
    assert log_node.isExpanded()  # open while the task runs
    lines = [log_node.child(i).text(0) for i in range(log_node.childCount())]
    assert any("working 42%" in line for line in lines)

    assert page._progress.value() == 42


def test_processing_page_labels_unused_stages(qtbot, app_context, bus):
    """A stage that never ran reads as 'unused' rather than 'pending'."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    run = {
        "target": "M31",
        "is_master": False,
        "stages": [{"name": "noise_exterminator", "status": "pending", "excluded": False}],
    }
    events.publish(events.EVENT_STAGE_RESULT, {"result": None, "run": run})

    stage_item = page._tasks.topLevelItem(0).child(0)
    assert stage_item.text(1) == "unused"


def test_processing_page_collapses_master_nodes(qtbot, app_context, bus):
    """Master (calibration) runs are collapsed so they don't crowd the tree."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    run = {
        "target": "Master flat_Ha · 2024-01-01 · canon",
        "is_master": True,
        "stages": [{"name": "stack_bias", "status": "ok", "excluded": False}],
    }
    events.publish(events.EVENT_STAGE_RESULT, {"result": None, "run": run})

    root = page._tasks.topLevelItem(0)
    assert root.text(0) == "Master flat_Ha · 2024-01-01 · canon"
    assert not root.isExpanded()




def test_processing_page_groups_logs_under_each_task(qtbot, app_context, bus):
    """Each task gets its own Log/Out nodes; finished logs start closed."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    run = {
        "target": "M31",
        "is_master": False,
        "stages": [
            {
                "name": "lightvbias",
                "status": "ok",
                "excluded": False,
                "dependencies": [],
                "outputs": [],
                "logs": ["stage-level noise"],
                "tasks": [
                    {
                        "name": "lightvbias_s123",
                        "title": "lightvbias_s123",
                        "status": "ok",
                        "outputs": [{"label": "bkg_pp_light_s123.fits", "url": "file:///o"}],
                        "logs": ["line a", "line b"],
                    },
                    {
                        "name": "lightvbias_s555",
                        "title": "lightvbias_s555",
                        "status": "ok",
                        "outputs": [],
                        "logs": [],
                    },
                ],
            }
        ],
    }
    events.publish(events.EVENT_STAGE_RESULT, {"result": None, "run": run})

    stage_item = page._tasks.topLevelItem(0).child(0)
    assert "lightvbias" in stage_item.text(0)

    first = _child_named(stage_item, "task", "lightvbias_s123")
    assert first is not None
    log_node = _child_of_kind(first, "log")
    assert log_node is not None
    assert not log_node.isExpanded()  # finished ok -> closed
    assert [log_node.child(i).text(0).strip() for i in range(log_node.childCount())] == [
        "line a",
        "line b",
    ]
    out_node = _child_of_kind(first, "out")
    assert out_node is not None
    assert out_node.childCount() == 1
    assert "bkg_pp_light_s123.fits" in out_node.child(0).text(0)

    # With tasks present the stage's flat log tail is *not* rendered: the lines
    # live under the tasks instead.
    assert not any(
        "stage-level noise" in stage_item.child(i).text(0)
        for i in range(stage_item.childCount())
    )
    assert _child_named(stage_item, "task", "lightvbias_s555") is not None


def test_processing_page_caps_running_log_at_the_tail(qtbot, app_context, bus):
    """A running task's Log keeps only the last LOG_TAIL_LINES lines."""
    from starbash.run_state import LOG_TAIL_LINES
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    events.publish(events.EVENT_RUN_STARTED, {"target": "M31"})
    events.publish(
        events.EVENT_TASK_STARTED,
        {"task": "stack", "title": "Stack", "target": "M31", "stage": "stack"},
    )
    for i in range(LOG_TAIL_LINES + 4):
        events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": f"line {i}"})

    stage_item = page._tasks.topLevelItem(0).child(0)
    log_node = _child_of_kind(_child_of_kind(stage_item, "task"), "log")
    assert log_node is not None
    assert log_node.childCount() == LOG_TAIL_LINES
    assert log_node.isExpanded()
    assert "line 0" not in log_node.child(0).text(0)
    assert f"line {LOG_TAIL_LINES + 3}" in log_node.child(log_node.childCount() - 1).text(0)


def test_processing_page_closes_log_on_finish_keeps_failure_open(qtbot, app_context, bus):
    """A Log closes when its task finishes ok, but stays open on failure."""
    from starbash.ui.qt.pages.processing import ProcessingPage

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    def running_log(task_name):
        stage_item = page._tasks.topLevelItem(0).child(0)
        task_item = _child_named(stage_item, "task", task_name)
        return _child_of_kind(task_item, "log")

    events.publish(events.EVENT_RUN_STARTED, {"target": "M31"})
    events.publish(
        events.EVENT_TASK_STARTED,
        {"task": "ok_task", "title": "Ok task", "target": "M31", "stage": "stack"},
    )
    events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stdout", "line": "fine"})
    log_node = running_log("ok_task")
    assert log_node is not None and log_node.isExpanded()

    events.publish(
        events.EVENT_TASK_FINISHED,
        {
            "task": "ok_task",
            "title": "Ok task",
            "target": "M31",
            "stage": "stack",
            "success": True,
        },
    )
    assert not log_node.isExpanded()

    events.publish(
        events.EVENT_TASK_STARTED,
        {"task": "bad_task", "title": "Bad task", "target": "M31", "stage": "stack"},
    )
    events.publish(events.EVENT_TOOL_OUTPUT, {"stream": "stderr", "line": "kaboom"})
    failed_log = running_log("bad_task")
    assert failed_log is not None
    events.publish(
        events.EVENT_TASK_FINISHED,
        {
            "task": "bad_task",
            "title": "Bad task",
            "target": "M31",
            "stage": "stack",
            "success": False,
        },
    )
    assert failed_log.isExpanded()



def test_run_tree_starts_with_an_even_column_split(qtbot):
    """The run tree gives its first column half the viewport on first show."""
    from starbash.ui.qt.pages.processing import _RunTree

    tree = _RunTree()
    qtbot.addWidget(tree)
    tree.setHeaderLabels(["Target / stage / task", "Status / details"])
    tree.resize(1000, 400)
    tree.show()
    qtbot.waitExposed(tree)

    tree._split_applied = False  # as if shown for the first time
    tree._apply_initial_split()

    assert tree.columnWidth(0) == tree.viewport().width() // 2


def test_processing_page_marks_links_and_opens_them(qtbot, app_context, bus, monkeypatch):
    """Stage/output cells are underlined links that open with the OS handler."""
    from starbash.ui.qt.models import LINK_ROLE
    from starbash.ui.qt.pages.processing import ProcessingPage
    from starbash.ui.qt.widgets import file_links

    opened: list[str] = []
    monkeypatch.setattr(file_links, "open_link", lambda url: opened.append(url) or True)

    page = ProcessingPage(app_context, bus)
    qtbot.addWidget(page)

    run = {
        "target": "M31",
        "output_url": "file:///out",
        "is_master": False,
        "stages": [
            {
                "name": "stack",
                "status": "ok",
                "excluded": False,
                "recipe_url": "https://example.com/stack.toml",
                "dependencies": [],
                "outputs": [],
                "tasks": [
                    {
                        "name": "stack_s1",
                        "title": "stack_s1",
                        "status": "ok",
                        "outputs": [
                            {"label": "stack.fits", "url": "file:///out/stack.fits"}
                        ],
                        "logs": [],
                    }
                ],
            }
        ],
    }
    events.publish(events.EVENT_STAGE_RESULT, {"result": None, "run": run})

    root = page._tasks.topLevelItem(0)
    assert root.data(1, LINK_ROLE) == "file:///out"

    stage_item = root.child(0)
    assert stage_item.data(0, LINK_ROLE) == "https://example.com/stack.toml"
    assert stage_item.font(0).underline() is True
    # A remote recipe cannot be previewed, so its URL stays discoverable.
    assert stage_item.toolTip(0) == "https://example.com/stack.toml"

    task_item = stage_item.child(0)
    out_node = next(
        task_item.child(i)
        for i in range(task_item.childCount())
        if task_item.child(i).text(0).strip() == "Out"
    )
    file_row = out_node.child(0)
    assert file_row.data(0, LINK_ROLE) == "file:///out/stack.fits"
    assert file_row.data(1, LINK_ROLE) == "file:///out/stack.fits"
    assert file_row.font(0).underline() is True
    assert file_row.font(1).underline() is True

    # Clicking the link cell opens it (the decorator listens on view.clicked).
    page._tasks.clicked.emit(page._tasks.indexFromItem(file_row, 1))
    assert opened == ["file:///out/stack.fits"]



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


# --- background workers -----------------------------------------------------


def test_run_async_callbacks_fire_even_when_the_worker_is_dropped(qtbot):
    """Regression: run_async must retain its Worker until it finishes.

    A Worker is a QRunnable with ``autoDelete`` set, so a dropped Python reference
    let C++ delete it - and its signal object - before the queued ``finished``
    signal was delivered.  Measured here: only 7 of 60 callbacks arrived.  Since
    ignoring the return value of ``run_async`` is the natural thing to do, the
    worker is now kept alive internally, which makes it 60 of 60.
    """
    from starbash.ui.qt.workers import run_async

    results: list[int] = []
    for index in range(40):
        run_async(lambda _report, _token, i=index: i, on_finished=results.append)

    qtbot.waitUntil(lambda: len(results) == 40, timeout=10000)
    assert sorted(results) == list(range(40))


def test_run_async_releases_finished_workers(qtbot):
    """The internal keep-alive set must not grow without bound."""
    from starbash.ui.qt import workers
    from starbash.ui.qt.workers import run_async

    before = len(workers._live_workers)
    finished: list[object] = []
    run_async(lambda _report, _token: "done", on_finished=finished.append)

    qtbot.waitUntil(lambda: bool(finished), timeout=5000)
    qtbot.waitUntil(lambda: len(workers._live_workers) <= before, timeout=5000)
    assert len(workers._live_workers) <= before


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


def test_setup_wizard_shows_analytics_defaults(qtbot, app_context):
    """An unset preference shows the documented defaults, not an unchecked box."""
    from starbash.ui.qt.pages.wizard import SetupWizard

    wizard = SetupWizard(app_context)
    qtbot.addWidget(wizard)

    # Analytics defaults to enabled; including the email defaults to off.
    assert wizard._analytics.isChecked() is True
    assert wizard._include_email.isChecked() is False


def test_settings_page_shows_analytics_defaults(qtbot, app_context):
    """The Settings page agrees with the core about the analytics defaults."""
    from starbash.ui.qt.pages.settings import SettingsPage

    page = SettingsPage(app_context)
    qtbot.addWidget(page)
    page.refresh()

    assert page._analytics.isChecked() is True
    assert page._include_email.isChecked() is False
