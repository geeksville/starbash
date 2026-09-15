"""Tests for hover previews: link classification, the popup and its placement.

The popup decodes files off the GUI thread (a FITS frame is far too slow to read
inline), so these tests exercise both the pure classification helpers and the
asynchronous rendering paths.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    if _QApplication.instance() is None:
        _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from starbash.ui.qt.models import LINK_ROLE  # noqa: E402
from starbash.ui.qt.widgets import hover_preview as hp  # noqa: E402
from starbash.ui.qt.widgets.file_links import set_link  # noqa: E402
from starbash.url import make_file_url  # noqa: E402

pytestmark = pytest.mark.gui

#: An arbitrary item-data role, as a page would use.
URL_ROLE = Qt.ItemDataRole.UserRole + 9


@pytest.fixture(autouse=True)
def _forget_the_remembered_preview_size():
    """Keep a *process-wide* user preview size (see ``_PreviewPopup._user_size``)
    from leaking between tests: one test dragging the popup bigger would otherwise
    resize every later test's popup."""
    hp._PreviewPopup._user_size = None
    yield
    hp._PreviewPopup._user_size = None


def _top(tree: QTreeWidget, index: int = 0) -> QTreeWidgetItem:
    """Return a tree's top-level item (Qt types it Optional)."""
    item = tree.topLevelItem(index)
    assert item is not None
    return item


def _text_file(tmp_path: Path, name: str = "notes.txt", lines: int = 2) -> Path:
    """Write a small UTF-8 text file."""
    path = tmp_path / name
    path.write_text("\n".join(f"line {i}" for i in range(lines)), encoding="utf-8")
    return path


def _png(tmp_path: Path, name: str = "frame.png", width: int = 80, height: int = 60) -> Path:
    """Write a real PNG so the raster path is exercised end to end."""
    path = tmp_path / name
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(path))
    return path


def _fits(tmp_path: Path, name: str = "frame.fits", width: int = 48, height: int = 32) -> Path:
    """Write a real FITS frame with some signal in it."""
    import numpy as np
    from astropy.io import fits

    data = np.zeros((height, width), dtype=np.float32)
    data[4:12, 4:20] = 500.0
    path = tmp_path / name
    fits.PrimaryHDU(data).writeto(path)
    return path


def _parent(qtbot, width: int = 1200, height: int = 900) -> QWidget:
    """A shown, laid-out window to size/position the popup against."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(width, height)
    parent.show()
    qtbot.waitExposed(parent)
    return parent


# --- classification --------------------------------------------------------


def test_preview_kind_classifies_supported_types(tmp_path):
    """Only existing local text/image files are previewable; http is not."""
    assert hp.preview_kind(None) is hp.PreviewKind.NONE
    assert hp.preview_kind("https://example.com/recipe.toml") is hp.PreviewKind.NONE
    assert hp.preview_kind((tmp_path / "missing.txt").as_uri()) is hp.PreviewKind.NONE

    assert hp.preview_kind(_text_file(tmp_path).as_uri()) is hp.PreviewKind.TEXT

    for name in ("frame.fits", "thumb.jpg"):
        path = tmp_path / name
        path.write_bytes(b"x")
        assert hp.preview_kind(path.as_uri()) is hp.PreviewKind.IMAGE

    blob = tmp_path / "thing.bin"
    blob.write_bytes(b"x")
    assert hp.preview_kind(blob.as_uri()) is hp.PreviewKind.NONE


def test_local_path_decodes_a_percent_escaped_file_url(tmp_path):
    """A URL with quoted characters resolves back to the real path."""
    path = tmp_path / "my notes.txt"
    path.write_text("hi", encoding="utf-8")
    assert hp.local_path(path.as_uri()) == path


#: The characters a fragment/query split would truncate -- the reason
#: :func:`starbash.url.make_file_url` percent-encodes rather than pasting a raw path
#: after ``file://``, so ``#`` must not turn into a fragment.  ``?`` is deliberately
#: absent: Windows forbids it in a file name, so this fixture file cannot exist
#: there.  Its encoding is asserted without a file, on the URL itself, in
#: ``test_url.py::test_make_file_url_percent_encodes_a_question_mark``.
@pytest.mark.parametrize("name", ["a b.txt", "hash#tag.txt", "amp&and.txt"])
def test_local_path_reads_every_kind_of_canonical_file_url(tmp_path, name):
    """A URL Starbash produced opens the file it was built for.

    The characters here are the ones a fragment/query split would truncate, which
    is why the URL quotes them instead of pasting the path (see above for ``?``).
    """
    path = tmp_path / name
    path.write_text("hi", encoding="utf-8")

    assert hp.local_path(make_file_url(path)) == path


def test_local_path_rejects_a_legacy_hand_built_url(tmp_path):
    """A ``file://C:\\...`` URL is refused rather than resolved to a wrong path."""
    path = tmp_path / "frame.fits"
    path.write_bytes(b"x")

    assert hp.local_path(f"file://{path}".replace("/", "\\")) is None


# --- popup -----------------------------------------------------------------


def test_target_size_is_about_a_quarter_of_the_window(qtbot):
    """The popup budget is ~25% of the owning window, clamped to sane pixels."""
    parent = _parent(qtbot, 1200, 900)
    size = hp._PreviewPopup._target_size(parent)
    assert size.width() == 300  # 1200 * 0.25
    assert size.height() == 225  # 900 * 0.25


def test_popup_renders_text_and_caps_the_tail(qtbot, tmp_path):
    """A text link shows its content, bounded to the tail cap."""
    path = _text_file(tmp_path, "long.txt", lines=hp.MAX_TEXT_LINES + 40)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QPlainTextEdit), timeout=5000)

    view = popup._content
    assert isinstance(view, QPlainTextEdit)
    assert view.isReadOnly()
    text = view.toPlainText()
    assert "line 0" in text
    assert text.endswith("…")
    assert text.count("\n") == hp.MAX_TEXT_LINES  # capped + the ellipsis row


def test_popup_renders_a_raster_image_and_hugs_it(qtbot, tmp_path):
    """An image link shows a scaled pixmap, never past the size budget."""
    path = _png(tmp_path)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QLabel), timeout=5000)

    content = popup._content
    assert isinstance(content, QLabel)
    pixmap = content.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    target = hp._PreviewPopup._target_size(parent)
    assert popup.width() <= target.width()
    assert popup.height() <= target.height()


def test_popup_renders_a_fits_frame(qtbot, tmp_path):
    """FITS links go through the astropy stretch renderer, off the GUI thread."""
    path = _fits(tmp_path)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QLabel), timeout=5000)

    content = popup._content
    assert isinstance(content, QLabel)
    pixmap = content.pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_popup_is_placed_beside_not_over_the_hovered_cell(qtbot):
    """The popup flips side as needed but never covers the hovered cell."""
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)
    popup.resize(300, 225)

    screen = QGuiApplication.primaryScreen()
    available = screen.availableGeometry()
    anchor = QRect(
        available.left() + available.width() // 2,
        available.top() + available.height() // 2,
        160,
        20,
    )
    popup._place(anchor)

    assert not popup.geometry().intersects(anchor)
    assert available.contains(popup.geometry())


def test_popup_reports_an_unreadable_file(qtbot, tmp_path, monkeypatch):
    """A broken file shows a message in the popup, never raises."""
    path = _png(tmp_path)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)

    def broken(_source: object) -> QImage:
        raise ValueError("boom")

    monkeypatch.setattr(hp, "load_image_file", broken)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(
        lambda: isinstance(popup._content, QLabel) and "Preview failed" in popup._content.text(),
        timeout=5000,
    )


# --- popup resize (the user's own size) ------------------------------------


def _drag(widget: QWidget, delta: QPoint) -> None:
    """Drag ``widget`` by ``delta`` using synthetic events.

    ``QTest.mouseMove`` needs a real cursor position, which the offscreen platform
    the suite runs on has none of, so press/move/release are posted directly.  The
    press point is inside either a grip or a title row, and the events go straight
    to ``widget``, so no hit-testing is involved.
    """
    left = Qt.MouseButton.LeftButton
    modifiers = Qt.KeyboardModifier.NoModifier
    start = QPointF(hp.GRIP_SIZE / 2, hp.GRIP_SIZE / 2)
    end = QPointF(start.x() + delta.x(), start.y() + delta.y())
    for event in (
        QMouseEvent(QEvent.Type.MouseButtonPress, start, start, left, left, modifiers),
        QMouseEvent(QEvent.Type.MouseMove, end, end, Qt.MouseButton.NoButton, left, modifiers),
        QMouseEvent(
            QEvent.Type.MouseButtonRelease, end, end, left, Qt.MouseButton.NoButton, modifiers
        ),
    ):
        QApplication.sendEvent(widget, event)


def _text_popup(qtbot, tmp_path: Path) -> tuple[hp._PreviewPopup, QWidget]:
    """A shown popup rendering a text preview, with its owning window."""
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)
    popup.preview(_text_file(tmp_path).as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QPlainTextEdit), timeout=5000)
    return popup, parent


def test_dragging_the_grip_resizes_the_popup_and_is_remembered(qtbot, tmp_path):
    """A preview is user-resizable, and the size the user chose sticks for the next."""
    popup, parent = _text_popup(qtbot, tmp_path)

    # The handle sits inside the card's bottom-right corner.
    assert popup._grip.parent() is popup._card
    assert popup._card.rect().contains(popup._grip.geometry())

    before = popup.size()
    _drag(popup._grip, QPoint(120, 90))

    assert popup.width() > before.width()
    assert popup.height() > before.height()
    assert hp._PreviewPopup._user_size == popup.size()

    # The choice is remembered process-wide, so the *next* preview opens at it
    # rather than back at the automatic quarter-of-the-window size.
    popup.preview(_text_file(tmp_path, "b.txt").as_uri(), QRect(100, 100, 200, 20), parent)
    assert popup.size() == hp._PreviewPopup._user_size
    assert popup.width() > hp._PreviewPopup._target_size(parent).width()


def test_dragging_the_grip_inwards_stops_at_the_minimums(qtbot, tmp_path):
    """A preview cannot be dragged away to nothing."""
    popup, _parent_window = _text_popup(qtbot, tmp_path)

    _drag(popup._grip, QPoint(-4000, -4000))

    # The drag stops dead at the popup's floor.  The width floor is our own clamp,
    # but the height floor is whatever the popup's layout asks for: a top-level
    # ``QLayout`` pins the window's minimum size to its contents, and the text view
    # wants more room on macOS (~194px) than on Linux (~88px) - Qt would enforce that
    # over ``MIN_HEIGHT`` whatever we clamped to, so the floor is read back from the
    # popup rather than assumed to be the constants.
    floor = popup._minimum_size()
    assert floor.width() == hp.MIN_WIDTH
    assert floor.height() >= hp.MIN_HEIGHT
    assert popup.size() == floor
    # ...and the size remembered for the next hover is the size the window really has.
    assert hp._PreviewPopup._user_size == popup.size()


def test_dragging_the_grip_inwards_stops_at_the_layouts_own_floor(qtbot, tmp_path):
    """When the window's own floor is above ``MIN_HEIGHT``, that floor wins - and the
    size remembered is the one the window really got.

    A top-level ``QLayout`` pins the window's minimum size to its contents, and the
    text view's share of that is font-dependent: on Linux it lands below
    ``MIN_HEIGHT``, on macOS above it (~194px), where Qt then refuses to shrink the
    popup to ``MIN_HEIGHT``.  That used to leave ``_user_size`` recording a size the
    window could not take, and every later hover reopened at that phantom size.
    """
    popup, _parent_window = _text_popup(qtbot, tmp_path)

    # The window minimum a top-level layout pins here: Linux's ends up below
    # ``MIN_HEIGHT``, macOS's ends up above it (its text metrics are fatter), and Qt
    # refuses to shrink the window past it either way.
    pinned = QSize(hp.MIN_WIDTH, hp.MIN_HEIGHT + 14)
    popup.setMinimumSize(pinned)
    assert popup._minimum_size() == pinned

    _drag(popup._grip, QPoint(-4000, -4000))

    # The drag stops at that floor too, and remembers the size it really got - the
    # bug was recording ``MIN_HEIGHT`` while the window sat at 194px.
    assert popup.size() == pinned
    assert hp._PreviewPopup._user_size == popup.size()


# --- popup move (the title row is the drag bar) -----------------------------


def test_dragging_the_title_row_moves_the_popup(qtbot, tmp_path):
    """The popup has no window-manager titlebar, so its title row moves it."""
    popup, _parent_window = _text_popup(qtbot, tmp_path)
    origin = popup.pos()
    size = popup.size()

    _drag(popup._titlebar, QPoint(40, 25))

    assert popup.pos() == origin + QPoint(40, 25)
    assert popup.size() == size, "moving must not resize"
    # The *name* is what a user aims at, so the label must let the press through to
    # the title row - otherwise only the blank space beside it would drag.
    assert popup._title.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert popup._titlebar.cursor().shape() == Qt.CursorShape.SizeAllCursor


def test_a_moved_popup_keeps_its_place_when_the_grip_resizes_it(qtbot, tmp_path):
    """Resizing must not teleport a popup the user moved back beside its cell."""
    popup, _parent_window = _text_popup(qtbot, tmp_path)
    _drag(popup._titlebar, QPoint(-40, -30))
    moved = popup.pos()
    before = popup.size()

    _drag(popup._grip, QPoint(60, 40))

    assert popup.width() > before.width(), "the grip still resizes"
    assert popup.pos() == moved, "and the window stayed where the user put it"


def test_a_user_sized_preview_is_not_shrunk_to_hug_a_small_image(qtbot, tmp_path):
    """Hugging is skipped once the user owns the size, so their choice is not undone.

    Without that, the next hover of a small thumbnail would shrink the window back
    down and silently discard the size the user had dragged out.
    """
    path = _png(tmp_path, width=80, height=60)  # far smaller than the chosen size
    parent = _parent(qtbot)
    hp._PreviewPopup._user_size = QSize(420, 340)
    popup = hp._PreviewPopup()
    qtbot.addWidget(popup)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QLabel), timeout=5000)

    assert popup.size() == QSize(420, 340)


def test_resizing_re_scales_the_previewed_image(qtbot, tmp_path):
    """Making the window bigger re-renders the image larger, from the source frame."""
    path = _png(tmp_path, width=800, height=600)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()
    qtbot.addWidget(popup)

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QLabel), timeout=5000)

    content = popup._content
    assert isinstance(content, QLabel)
    before = content.pixmap().width()
    assert popup._source is not None

    popup.resize(600, 520)  # what a grip drag ends up doing

    # Re-scaling is debounced, so wait for it rather than racing the timer.
    qtbot.waitUntil(lambda: content.pixmap().width() > before, timeout=2000)


# --- popup close / single window -------------------------------------------


def test_popup_close_adornment_hides_and_signals(qtbot, tmp_path):
    """The close button hides the popup and reports a user close."""
    path = _text_file(tmp_path)
    parent = _parent(qtbot)
    popup = hp._PreviewPopup()  # unparented so qtbot can own its teardown
    qtbot.addWidget(popup)
    closed: list[int] = []
    popup.closed.connect(lambda: closed.append(1))

    popup.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    qtbot.waitUntil(lambda: isinstance(popup._content, QPlainTextEdit), timeout=5000)
    assert popup.isVisible()

    popup._close.click()

    assert not popup.isVisible()
    assert closed == [1]


def test_opening_a_preview_closes_any_other(qtbot, tmp_path):
    """At most one preview window is ever visible."""
    path = _text_file(tmp_path)
    parent = _parent(qtbot)
    first = hp._PreviewPopup()
    qtbot.addWidget(first)
    second = hp._PreviewPopup()
    qtbot.addWidget(second)

    first.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)
    assert first.isVisible()

    second.preview(path.as_uri(), QRect(100, 100, 200, 20), parent)

    assert second.isVisible()
    assert not first.isVisible()


# --- engine ----------------------------------------------------------------


def _link_tree(qtbot, urls: list[str]) -> QTreeWidget:
    """A shown two-column tree with one link (column 0) per row."""
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(2)
    for index, url in enumerate(urls):
        item = QTreeWidgetItem([f"item {index}", "detail"])
        item.setData(0, URL_ROLE, url)
        tree.addTopLevelItem(item)
    tree.resize(400, 200)
    tree.show()
    qtbot.waitExposed(tree)
    return tree


def test_engine_waits_on_a_link_but_keeps_an_open_popup(qtbot, tmp_path):
    """Moving off a link cancels a *pending* preview but never closes an open one."""
    first = _text_file(tmp_path, "a.txt")
    second = _text_file(tmp_path, "b.txt")
    tree = _link_tree(qtbot, [first.as_uri(), second.as_uri()])
    engine = hp.HoverPreview(tree, url_role=URL_ROLE, parent=tree)

    item = _top(tree, 0)
    on_link = tree.visualRect(tree.indexFromItem(item, 0)).center()
    engine._on_mouse_move(on_link)
    assert engine._pending_url == first.as_uri()
    assert engine._timer.isActive()

    # Leaning off the link (before the delay) cancels the pending preview.
    off_link = tree.visualRect(tree.indexFromItem(item, 1)).center()
    engine._on_mouse_move(off_link)
    assert engine._pending_url is None
    assert not engine._timer.isActive()

    # Now open it for real, then move off: it must stay open for the scrollbars.
    engine._on_mouse_move(on_link)
    engine._show_preview()
    assert engine._popup.isVisible()
    engine._on_mouse_move(off_link)
    assert engine._popup.isVisible()
    assert engine._shown_url == first.as_uri()


def test_engine_replaces_the_preview_for_a_new_link(qtbot, tmp_path):
    """Hovering a different link closes the old preview and opens the new one."""
    first = _text_file(tmp_path, "a.txt")
    second = _text_file(tmp_path, "b.txt")
    tree = _link_tree(qtbot, [first.as_uri(), second.as_uri()])
    engine = hp.HoverPreview(tree, url_role=URL_ROLE, parent=tree)

    engine._on_mouse_move(tree.visualRect(tree.indexFromItem(_top(tree, 0), 0)).center())
    engine._show_preview()
    assert engine._shown_url == first.as_uri()

    engine._on_mouse_move(tree.visualRect(tree.indexFromItem(_top(tree, 1), 0)).center())
    assert engine._pending_url == second.as_uri()
    engine._show_preview()

    assert engine._shown_url == second.as_uri()
    assert engine._popup.isVisible()


def test_engine_previews_a_link_set_on_a_table_item(qtbot, tmp_path):
    """``set_link`` also works on a QTableWidgetItem, which the master picker uses.

    The engine itself is view-agnostic, but the picker's cells are widget-backed
    items rather than model indices, so the link role has to survive that path.
    """
    path = _text_file(tmp_path)
    table = QTableWidget(1, 1)
    qtbot.addWidget(table)
    table.verticalHeader().setVisible(False)
    item = QTableWidgetItem("master_bias_gain100.fit")
    set_link(item, 0, path.as_uri())
    table.setItem(0, 0, item)
    table.resize(400, 200)
    table.show()
    qtbot.waitExposed(table)

    engine = hp.HoverPreview(table, url_role=LINK_ROLE, parent=table)

    assert item.data(LINK_ROLE) == path.as_uri()
    assert item.font().underline() is True

    engine._on_mouse_move(table.visualItemRect(item).center())
    assert engine._pending_url == path.as_uri()
    engine._show_preview()
    assert engine._popup.isVisible()


def test_engine_does_not_reopen_a_closed_link_until_the_cursor_leaves(qtbot, tmp_path):
    """After the user closes a preview, jitter on the same link won't reopen it."""
    path = _text_file(tmp_path)
    tree = _link_tree(qtbot, [path.as_uri()])
    engine = hp.HoverPreview(tree, url_role=URL_ROLE, parent=tree)
    item = _top(tree, 0)
    on_link = tree.visualRect(tree.indexFromItem(item, 0)).center()
    off_link = tree.visualRect(tree.indexFromItem(item, 1)).center()

    engine._on_mouse_move(on_link)
    engine._show_preview()
    engine._popup.close_for_user()

    engine._on_mouse_move(on_link)  # still on the same link
    assert not engine._timer.isActive()

    engine._on_mouse_move(off_link)  # leave the link...
    engine._on_mouse_move(on_link)  # ...and come back
    assert engine._pending_url == path.as_uri()


def test_engine_shows_a_hand_cursor_over_links(qtbot, tmp_path):
    """The cursor becomes a pointing hand only over link cells."""
    path = _text_file(tmp_path)
    tree = _link_tree(qtbot, [path.as_uri()])
    engine = hp.HoverPreview(tree, url_role=URL_ROLE, parent=tree)
    item = _top(tree, 0)

    engine._on_mouse_move(tree.visualRect(tree.indexFromItem(item, 0)).center())
    assert tree.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor

    engine._on_mouse_move(tree.visualRect(tree.indexFromItem(item, 1)).center())
    assert tree.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
