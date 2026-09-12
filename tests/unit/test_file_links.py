"""Tests for shared file links: marking cells and opening them safely."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    _QApplication.instance() or _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtWidgets import QTreeWidgetItem  # noqa: E402

from starbash.ui.qt.models import LINK_ROLE  # noqa: E402
from starbash.ui.qt.widgets import file_links  # noqa: E402

pytestmark = pytest.mark.gui


def test_link_role_is_the_one_the_model_exposes():
    """The widgets and the table models agree on the shared link role."""
    assert file_links.LINK_ROLE == LINK_ROLE


def test_set_link_marks_and_underlines_a_cell():
    """A local file link is underlined and carries its URL."""
    item = QTreeWidgetItem(["label", "detail"])
    file_links.set_link(item, 0, "file:///tmp/frame.fits")

    assert item.data(0, LINK_ROLE) == "file:///tmp/frame.fits"
    assert item.font(0).underline() is True
    # Local files are previewable, so no native tooltip competes with the popup.
    assert item.toolTip(0) == ""


def test_set_link_ignores_empty_and_tooltips_remote_urls():
    """An empty URL leaves the cell alone; a remote one stays discoverable."""
    item = QTreeWidgetItem(["label", "detail"])
    file_links.set_link(item, 0, None)
    assert item.data(0, LINK_ROLE) is None
    assert item.font(0).underline() is False

    file_links.set_link(item, 1, "https://example.com/recipe.toml")
    assert item.data(1, LINK_ROLE) == "https://example.com/recipe.toml"
    assert item.toolTip(1) == "https://example.com/recipe.toml"


class _FakeDesktop:
    """A stand-in for QDesktopServices that can fail chosen paths."""

    def __init__(self, fail: set[str]) -> None:
        self.opened: list[str] = []
        self._fail = fail

    def openUrl(self, url: object) -> bool:  # noqa: N802 - Qt API
        target = url.toLocalFile()  # type: ignore[attr-defined]
        self.opened.append(target)
        return target not in self._fail


def test_open_link_opens_the_file_when_a_handler_exists(tmp_path, monkeypatch):
    path = tmp_path / "frame.fits"
    path.write_bytes(b"x")
    fake = _FakeDesktop(fail=set())
    monkeypatch.setattr(file_links, "QDesktopServices", fake)

    assert file_links.open_link(path.as_uri()) is True
    assert fake.opened == [str(path)]


def test_open_link_falls_back_to_the_folder_for_an_unhandled_type(tmp_path, monkeypatch):
    """The 'no application for mimetype' case opens the containing folder."""
    path = tmp_path / "frame.fits"
    path.write_bytes(b"x")
    fake = _FakeDesktop(fail={str(path)})
    monkeypatch.setattr(file_links, "QDesktopServices", fake)

    assert file_links.open_link(path.as_uri()) is True
    assert fake.opened == [str(path), str(tmp_path)]


def test_open_link_reports_failure_when_nothing_opens(tmp_path, monkeypatch):
    path = tmp_path / "frame.fits"
    path.write_bytes(b"x")
    fake = _FakeDesktop(fail={str(path), str(tmp_path)})
    monkeypatch.setattr(file_links, "QDesktopServices", fake)

    assert file_links.open_link(path.as_uri()) is False


def test_open_with_status_reports_the_outcome(tmp_path, monkeypatch):
    path = tmp_path / "frame.fits"
    path.write_bytes(b"x")
    monkeypatch.setattr(file_links, "QDesktopServices", _FakeDesktop(fail=set()))
    messages: list[str] = []

    file_links.open_with_status(path.as_uri(), messages.append)

    assert messages == [f"Opened {path.as_uri()}"]
