"""Tests for `sb gui` that do NOT need PySide6 installed.

`starbash.ui.qt` imports Qt lazily, so these run in the default test suite and
verify the graceful-degradation path the plan requires.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from starbash.main import app
from starbash.ui import qt

runner = CliRunner(env={"NO_COLOR": "1"})


def test_run_gui_raises_when_qt_is_missing():
    """run_gui() fails loudly (never silently) when PySide6 isn't installed."""
    with patch.object(qt, "qt_available", return_value=False):
        try:
            qt.run_gui()
        except qt.GuiUnavailableError as exc:
            assert "gui" in str(exc)  # the hint names the extra to install
        else:  # pragma: no cover - only hit if the guard regressed
            raise AssertionError("run_gui() should have raised GuiUnavailableError")


def test_gui_command_explains_how_to_install_qt():
    """`sb gui` exits 1 with an actionable message instead of a traceback."""
    with patch.object(qt, "qt_available", return_value=False):
        result = runner.invoke(app, ["gui"])

    assert result.exit_code == 1
    assert "PySide6" in result.stdout
    assert "gui" in result.stdout
