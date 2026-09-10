"""Tests for image previews: background decoding and the busy arc.

Decoding a FITS frame is slow enough to freeze the GUI, so the viewer decodes on a
worker thread and shows a :class:`BusyIndicator` over the spot the image will occupy.
These tests pin that down - including the guarantee that widgets are only ever
touched from the GUI thread.
"""

from __future__ import annotations

import os
import threading
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

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

from starbash.ui.qt.widgets import image_viewer as viewer_module  # noqa: E402
from starbash.ui.qt.widgets.busy_indicator import BusyIndicator  # noqa: E402
from starbash.ui.qt.widgets.image_viewer import ImageViewer  # noqa: E402

pytestmark = pytest.mark.gui


def _filled(width: int, height: int) -> QImage:
    """A solid-colour image of the given size (decoding is stubbed in most tests)."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    return image


def _png(path: Path, width: int = 40, height: int = 30) -> Path:
    """Write a real PNG so the viewer's own loader is exercised."""
    assert _filled(width, height).save(str(path))
    return path


def _fits(path: Path, width: int = 48, height: int = 32) -> Path:
    """Write a real FITS frame with some signal in it."""
    from astropy.io import fits

    data = np.zeros((height, width), dtype=np.float32)
    data[4:12, 4:20] = 500.0
    fits.PrimaryHDU(data).writeto(path)
    return path


def _make_viewer(qtbot, width: int = 400, height: int = 300) -> ImageViewer:
    """A shown, laid-out viewer - geometry assertions need a real window."""
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(width, height)
    viewer.show()
    qtbot.waitExposed(viewer)
    return viewer


def _centred_offset(widget: QWidget, parent: QWidget) -> tuple[int, int]:
    """How far ``widget``'s centre is from ``parent``'s centre, per axis."""
    centre, target = widget.geometry().center(), parent.rect().center()
    return abs(centre.x() - target.x()), abs(centre.y() - target.y())


# --- BusyIndicator ---------------------------------------------------------


def test_busy_indicator_only_animates_while_running(qtbot):
    """start() shows and animates; stop() hides and stops the timer."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(400, 300)
    parent.show()
    indicator = BusyIndicator(parent)
    qtbot.addWidget(indicator)

    # Idle and invisible until asked, so it costs nothing on a page with no work.
    assert indicator.is_running() is False
    assert indicator.isVisible() is False
    assert indicator._timer.isActive() is False

    indicator.start()
    assert indicator.is_running() is True
    assert indicator.isVisible() is True
    assert indicator._timer.isActive() is True

    indicator.start()  # idempotent: a second start must not double up
    assert indicator.is_running() is True

    indicator.stop()
    assert indicator.is_running() is False
    assert indicator.isVisible() is False
    assert indicator._timer.isActive() is False


def test_busy_indicator_centres_itself_over_its_parent(qtbot):
    """It sits in the middle of where the content will appear, and stays there."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(400, 300)
    parent.show()
    indicator = BusyIndicator(parent)
    qtbot.addWidget(indicator)
    indicator.start()
    qtbot.waitExposed(parent)

    assert _centred_offset(indicator, parent) == (0, 0)  # exactly centred

    parent.resize(640, 480)
    qtbot.wait(20)
    offset = _centred_offset(indicator, parent)
    assert offset[0] <= 1 and offset[1] <= 1


def test_busy_indicator_paints_and_ignores_mouse_events(qtbot):
    """It draws (an overlay hit-testing QPixmap) without swallowing clicks."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(300, 240)
    parent.show()
    indicator = BusyIndicator(parent)
    qtbot.addWidget(indicator)
    indicator.start()
    qtbot.waitExposed(parent)

    assert indicator.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    pixmap = indicator.grab()  # really runs paintEvent
    assert not pixmap.isNull()
    assert pixmap.width() == indicator.width()

    # ...and the arc actually moves from frame to frame.
    before = indicator._angle
    indicator._advance()
    assert indicator._angle != before


def test_busy_indicator_caption_grows_the_panel(qtbot):
    """The caption widens and heightens the panel; blank means arc-only."""
    parent = QWidget()
    qtbot.addWidget(parent)
    bare = BusyIndicator(parent, caption="")
    wide = BusyIndicator(parent, caption="Loading a rather long file name.fits…")
    qtbot.addWidget(bare)
    qtbot.addWidget(wide)

    assert wide.sizeHint().width() > bare.sizeHint().width()
    assert wide.sizeHint().height() > bare.sizeHint().height()
    assert bare.sizeHint().width() < wide.sizeHint().width()


# --- ImageViewer: background loading ---------------------------------------


def test_show_file_decodes_off_the_gui_thread(qtbot, tmp_path, monkeypatch):
    """The expensive decode must not run on the GUI thread."""
    path = _png(tmp_path / "frame.png")
    viewer = _make_viewer(qtbot)
    gui_thread = threading.get_ident()

    threads: list[int] = []
    real = viewer_module.load_image_file

    def spy(source: object) -> QImage:
        threads.append(threading.get_ident())
        return real(source)

    monkeypatch.setattr(viewer_module, "load_image_file", spy)

    viewer.show_file(path)
    qtbot.waitUntil(lambda: bool(threads), timeout=5000)

    assert threads[0] != gui_thread
    qtbot.waitUntil(lambda: viewer._image is not None, timeout=5000)


def test_the_gui_keeps_running_while_a_frame_decodes(qtbot, tmp_path, monkeypatch):
    """A slow decode must not block the GUI thread: timers keep firing meanwhile.

    This is the whole point of the background load - before it, selecting a big FITS
    frame froze the window until the stretch finished.
    """
    release = threading.Event()

    def slow(_source: object) -> QImage:
        release.wait(timeout=5)
        return _filled(20, 10)

    monkeypatch.setattr(viewer_module, "load_image_file", slow)
    viewer = _make_viewer(qtbot)

    ticks: list[int] = []
    ticker = QTimer()
    ticker.setInterval(10)
    ticker.timeout.connect(lambda: ticks.append(1))
    ticker.start()

    viewer.show_file(tmp_path / "slow.fits")
    qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=5000)

    assert viewer.is_loading() is True  # the decode is still in progress...
    assert len(ticks) >= 5  # ...yet the event loop is alive and well

    ticker.stop()
    release.set()
    qtbot.waitUntil(lambda: viewer.is_loading() is False, timeout=5000)
    assert viewer._image is not None


def test_a_slow_load_shows_the_busy_arc_until_it_finishes(qtbot, tmp_path, monkeypatch):
    """The arc covers the view while decoding and disappears once it is done."""
    release = threading.Event()

    def slow(_source: object) -> QImage:
        release.wait(timeout=5)
        return _filled(20, 10)

    monkeypatch.setattr(viewer_module, "load_image_file", slow)
    viewer = _make_viewer(qtbot)

    viewer.show_file(tmp_path / "slow.fits")

    # Still decoding: nothing drawn yet, arc centred over the viewport.
    assert viewer.is_loading() is True
    assert viewer._image is None
    assert viewer._busy.isVisible() is True
    offset = _centred_offset(viewer._busy, viewer._scroll.viewport())
    assert offset[0] <= 1 and offset[1] <= 1

    release.set()
    qtbot.waitUntil(lambda: viewer.is_loading() is False, timeout=5000)

    assert viewer.is_loading() is False
    assert viewer._busy.isVisible() is False
    assert viewer._image is not None
    assert (viewer._image.width(), viewer._image.height()) == (20, 10)
    assert viewer._caption.text().startswith("slow.fits")


def test_a_slow_load_cannot_overwrite_a_newer_one(qtbot, tmp_path, monkeypatch):
    """Picking a second frame while the first decodes keeps the second."""
    release = threading.Event()
    slow_returned = threading.Event()

    def fake(source: object) -> QImage:
        if Path(str(source)).name == "slow.fits":
            release.wait(timeout=5)
            slow_returned.set()
            return _filled(11, 11)
        return _filled(22, 22)

    monkeypatch.setattr(viewer_module, "load_image_file", fake)
    viewer = _make_viewer(qtbot)

    viewer.show_file(tmp_path / "slow.fits")
    viewer.show_file(tmp_path / "fast.fits")
    qtbot.waitUntil(lambda: viewer._image is not None, timeout=5000)
    assert viewer._image.width() == 22

    # Now let the stale load finish; its result must be dropped on the floor.
    release.set()
    qtbot.waitUntil(slow_returned.is_set, timeout=5000)
    qtbot.wait(100)
    assert viewer._image.width() == 22
    assert viewer.is_loading() is False


def test_show_message_drops_a_pending_load(qtbot, tmp_path, monkeypatch):
    """Showing a message cancels any load still in flight."""
    release = threading.Event()

    def slow(_source: object) -> QImage:
        release.wait(timeout=5)
        return _filled(11, 11)

    monkeypatch.setattr(viewer_module, "load_image_file", slow)
    viewer = _make_viewer(qtbot)

    viewer.show_file(tmp_path / "slow.fits")
    viewer.show_message("nothing here")
    assert viewer.is_loading() is False

    release.set()
    qtbot.wait(100)
    assert viewer._image is None
    assert viewer._label.text() == "nothing here"


# --- ImageViewer: real files ----------------------------------------------


def test_show_file_displays_a_real_raster_image(qtbot, tmp_path):
    """The everyday path: a PNG on disk ends up on the label."""
    path = _png(tmp_path / "frame.png", 40, 30)
    viewer = _make_viewer(qtbot)

    viewer.show_file(path)
    qtbot.waitUntil(lambda: viewer._image is not None, timeout=5000)

    assert (viewer._image.width(), viewer._image.height()) == (40, 30)
    assert viewer.is_loading() is False
    assert "frame.png" in viewer._caption.text()
    assert "40 × 30" in viewer._caption.text()


def test_show_file_renders_a_fits_frame(qtbot, tmp_path):
    """FITS goes through the stretch renderer, off the GUI thread."""
    path = _fits(tmp_path / "frame.fits", 48, 32)
    viewer = _make_viewer(qtbot)

    viewer.show_file(path)
    qtbot.waitUntil(lambda: viewer._image is not None, timeout=5000)

    assert (viewer._image.width(), viewer._image.height()) == (48, 32)


def test_an_unreadable_frame_is_reported_in_the_viewer(qtbot, tmp_path):
    """A broken frame shows a message; it is never raised at the caller."""
    viewer = _make_viewer(qtbot)

    viewer.show_file(tmp_path / "missing.fits")  # never created

    qtbot.waitUntil(lambda: "Preview failed" in viewer._label.text(), timeout=5000)
    assert viewer.is_loading() is False
    assert "missing.fits" in viewer._label.text()
    assert viewer._image is None


def test_clear_resets_the_viewer(qtbot, tmp_path):
    """clear() returns to the empty prompt with no image or arc."""
    path = _png(tmp_path / "frame.png")
    viewer = _make_viewer(qtbot)
    viewer.show_file(path)
    qtbot.waitUntil(lambda: viewer._image is not None, timeout=5000)

    viewer.clear()

    assert viewer._image is None
    assert viewer.is_loading() is False
    assert viewer._label.text() == "Select a frame to preview."
    assert viewer._caption.text() == ""

