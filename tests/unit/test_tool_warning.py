"""Tests for the missing-tool warning bars (``ui/qt/widgets/tool_warning.py``).

The core reports missing tools as :class:`~starbash.tool.base.ToolStatus` values;
these tests pin down how the GUI renders them - one bar per missing tool, most
important first, an install link, and an *Ignore* button that only the
non-required tools get (a missing Siril is not something to dismiss).

Qt is probed once at import so an unusable Qt skips this module rather than
erroring; ``tests/conftest.py`` sets ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    if _QApplication.instance() is None:
        _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel, QWidget  # noqa: E402

from starbash.tool import ToolSeverity, ToolStatus, plain_message  # noqa: E402
from starbash.ui.qt.widgets import file_links as file_links_module  # noqa: E402
from starbash.ui.qt.widgets.tool_warning import ToolWarningBar, ToolWarningPanel  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def installed(monkeypatch):
    """Control which external tools look installed, with clean ignore preferences.

    Returns the mutable ``{key: bool}`` the stubbed probes read, so a test can
    "install" a tool and call :meth:`ToolWarningPanel.refresh` to see the bar go.
    """

    from starbash.tool import Tool
    from starbash.tool.graxpert import GraxpertBuiltinTool
    from starbash.tool.python import PythonTool
    from starbash.tool.rcastro import RCAstroTool
    from starbash.tool.siril import SirilTool
    from starbash.tool.starnet import StarnetTool

    state = {"siril": False, "starnet": False, "rc-astro": False}
    monkeypatch.setattr(Tool, "Preferences", {})

    for tool_class, key in (
        (SirilTool, "siril"),
        (StarnetTool, "starnet"),
        (RCAstroTool, "rc-astro"),
    ):
        monkeypatch.setattr(tool_class, "is_available", property(lambda self, key=key: state[key]))

    # Built-in tools ship with Starbash, so they never warn.
    for tool_class in (GraxpertBuiltinTool, PythonTool):
        monkeypatch.setattr(tool_class, "is_available", property(lambda self: True))

    return state


#: Keeps test hosts alive: pytest-qt tracks widgets by *weak* reference, so a
#: parentless host would be garbage collected - taking its child panel with it -
#: the moment our local variable went out of scope.
_KEEPALIVE: list[QWidget] = []


def _make_panel(qtbot, **kwargs) -> ToolWarningPanel:
    """A panel parented to a real widget (a parentless one would be a window)."""
    host = QWidget()
    qtbot.addWidget(host)
    panel = ToolWarningPanel(parent=host, **kwargs)
    qtbot.addWidget(panel)
    _KEEPALIVE.append(host)
    return panel


def _label(bar: ToolWarningBar, name: str) -> QLabel:
    """The bar's label with the given object name (the theme styles these)."""
    label = bar.findChild(QLabel, name)
    assert label is not None, f"{bar.objectName()} has no {name} label"
    return label


def _shown_in_parent(panel: ToolWarningPanel) -> bool:
    """Whether the panel would show inside its parent (``parentWidget`` is Optional)."""
    parent = panel.parentWidget()
    assert parent is not None
    return panel.isVisibleTo(parent)


# --- bars ------------------------------------------------------------------


def test_panel_shows_one_bar_per_missing_tool_most_important_first(qtbot, installed):
    """Missing tools are listed required -> recommended -> optional."""
    panel = _make_panel(qtbot)

    assert [bar.tool_status.key for bar in panel.bars()] == ["siril", "starnet", "rc-astro"]
    assert _shown_in_parent(panel)


def test_bar_reports_the_tool_and_its_severity(qtbot, installed):
    """A bar names the tool, badges its severity and explains what is missing."""
    panel = _make_panel(qtbot)
    siril, starnet = panel.bars()[0], panel.bars()[1]

    assert _label(siril, "ToolWarningTitle").text() == "Siril was not found"
    assert _label(siril, "ToolWarningBadge").text() == "REQUIRED"
    assert _label(starnet, "ToolWarningBadge").text() == "RECOMMENDED"

    # The body is a one-liner (console markup stripped); the full text is a tooltip.
    detail = _label(siril, "ToolWarningDetail")
    assert "\n" not in detail.text()
    assert "The Siril executable was not found." in detail.text()
    assert "[link=" not in detail.text()
    full = siril.tool_status.detail
    assert full is not None
    assert detail.toolTip() == plain_message(full)


def test_only_non_required_tools_can_be_ignored(qtbot, installed):
    """A required tool keeps its bar; recommended and optional tools offer Ignore."""
    panel = _make_panel(qtbot)
    bars = {bar.tool_status.key: bar for bar in panel.bars()}

    assert bars["siril"]._ignore_button is None
    assert bars["starnet"]._ignore_button is not None
    assert bars["rc-astro"]._ignore_button is not None


def test_install_button_opens_the_tools_install_page(qtbot, installed, monkeypatch):
    """Clicking *How to install* opens the tool's page and reports it."""
    opened: list[str] = []

    class _FakeDesktopServices:
        @staticmethod
        def openUrl(url) -> bool:  # noqa: N802 - mirrors Qt's API
            opened.append(url.toString())
            return True

    monkeypatch.setattr(file_links_module, "QDesktopServices", _FakeDesktopServices)

    panel = _make_panel(qtbot)
    bar = panel.bars()[0]
    assert bar._install_button is not None

    with qtbot.waitSignal(bar.status, timeout=1000) as blocker:
        qtbot.mouseClick(bar._install_button, Qt.MouseButton.LeftButton)

    assert opened == [bar.tool_status.install_url]
    assert "Opened" in blocker.args[0]


# --- dismissing ------------------------------------------------------------


def test_ignoring_a_tool_drops_its_bar_and_silences_it(qtbot, installed):
    """Ignore records the choice, removes that bar and keeps the others."""
    from starbash.tool import missing_tool_statuses, set_tool_ignored

    panel = _make_panel(qtbot, on_ignore=set_tool_ignored)
    starnet = next(bar for bar in panel.bars() if bar.tool_status.key == "starnet")
    assert starnet._ignore_button is not None

    qtbot.mouseClick(starnet._ignore_button, Qt.MouseButton.LeftButton)

    assert [bar.tool_status.key for bar in panel.bars()] == ["siril", "rc-astro"]
    assert "starnet" not in [status.key for status in missing_tool_statuses()]


def test_panel_refresh_drops_a_bar_once_the_tool_is_installed(qtbot, installed):
    """Installing a tool makes its bar disappear on refresh."""
    panel = _make_panel(qtbot)
    assert [bar.tool_status.key for bar in panel.bars()] == ["siril", "starnet", "rc-astro"]

    installed["siril"] = True
    installed["starnet"] = True
    panel.refresh()

    assert [bar.tool_status.key for bar in panel.bars()] == ["rc-astro"]


def test_panel_hides_itself_when_every_tool_is_present(qtbot, installed):
    """A healthy install pays no vertical space for warnings."""
    installed.update({"siril": True, "starnet": True, "rc-astro": True})
    panel = _make_panel(qtbot)

    assert panel.bars() == []
    assert not _shown_in_parent(panel)


def test_ignore_reports_the_key_to_the_window(qtbot, installed):
    """The bar does not persist anything itself - it reports the key upward."""
    ignored: list[str] = []
    panel = _make_panel(qtbot, on_ignore=ignored.append)
    starnet = next(bar for bar in panel.bars() if bar.tool_status.key == "starnet")
    assert starnet._ignore_button is not None

    qtbot.mouseClick(starnet._ignore_button, Qt.MouseButton.LeftButton)

    assert ignored == ["starnet"]


def test_bar_from_a_builtin_tool_has_no_install_link(qtbot):
    """A tool with no install page offers no *How to install* button."""
    status = ToolStatus(
        name="Python",
        key="python",
        severity=ToolSeverity.RECOMMENDED,
        available=False,
        install_url=None,
        detail="The Python sandbox is unavailable.",
    )
    bar = ToolWarningBar(status)
    qtbot.addWidget(bar)

    assert bar._install_button is None
    assert bar._ignore_button is not None
    assert _label(bar, "ToolWarningDetail").text() == "The Python sandbox is unavailable."


# --- plain-text conversion -------------------------------------------------


def test_plain_message_rewrites_rich_links():
    """Console markup (Rich link tags) never reaches a plain-text widget."""
    message = "Install it from [link=https://siril.org/]here[/link] please."
    assert plain_message(message) == "Install it from here (https://siril.org/) please."
    assert plain_message("no markup at all") == "no markup at all"
