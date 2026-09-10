"""Tests for `sb gui`'s failure path.

`starbash.ui.qt` imports Qt lazily and checks availability before importing, so
these tests can simulate a broken/incomplete install without ever importing Qt.
PySide6 is normally present as a normal dependency, so they run in the default
suite.
"""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from starbash.main import app
from starbash.ui import qt

runner = CliRunner(env={"NO_COLOR": "1"})


def test_run_gui_raises_when_qt_is_unavailable():
    """run_gui() fails loudly (never silently) when PySide6 can't be imported."""
    with patch.object(qt, "qt_available", return_value=False):
        with pytest.raises(qt.GuiUnavailableError) as excinfo:
            qt.run_gui()

    assert "PySide6" in str(excinfo.value)


def test_gui_command_explains_how_to_fix_the_install():
    """`sb gui` exits 1 with an actionable message instead of a traceback."""
    with patch.object(qt, "qt_available", return_value=False):
        result = runner.invoke(app, ["gui"])

    assert result.exit_code == 1
    assert "PySide6" in result.stdout
    assert "reinstall" in result.stdout.lower()
