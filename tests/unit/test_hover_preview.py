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

    _QApplication.instance() or _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QLabel,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from starbash.ui.qt.widgets import hover_preview as hp  # noqa: E402

pytestmark = pytest.mark.gui

#: An arbitrary item-data role, as a page would use.
URL_ROLE = Qt.ItemDataRole.UserRole + 9


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

    pixmap = popup._content.pixmap()
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

    pixmap = popup._content.pixmap()
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


# --- engine ----------------------------------------------------------------


def test_engine_waits_on_a_link_and_dismisses_elsewhere(qtbot):
    """Hovering a link starts the delay; leaving it dismisses immediately."""
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(2)
    item = QTreeWidgetItem(["a", "b"])
    item.setData(0, URL_ROLE, "file:///tmp/whatever.txt")
    tree.addTopLevelItem(item)
    tree.resize(400, 200)
    tree.show()
    qtbot.waitExposed(tree)

    engine = hp.HoverPreview(tree, url_role=URL_ROLE, parent=tree)

    on_link = tree.visualRect(tree.indexFromItem(item, 0)).center()
    engine._on_mouse_move(on_link)
    assert engine._url == "file:///tmp/whatever.txt"
    assert engine._timer.isActive()

    # Column 1 carries no URL, so hovering it dismisses the pending preview.
    off_link = tree.visualRect(tree.indexFromItem(item, 1)).center()
    engine._on_mouse_move(off_link)
    assert engine._url is None
    assert not engine._timer.isActive()

