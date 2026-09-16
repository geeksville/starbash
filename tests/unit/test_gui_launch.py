"""Tests for *launching* the GUI: bare ``sb``, and the first-run wizard trigger.

Bare ``sb`` opens the window when there is a desktop session, and keeps the plain
CLI behaviour (help text, first-run questions) when there is not - an SSH user
must never be dropped into a PySide6 import failure.  That decision lives in
``starbash.main._try_launch_gui`` / ``starbash.ui.qt.desktop_session_available``,
and the wizard trigger in ``starbash.ui.qt.app.run`` (which asks
``is_wizard_complete``, the wizard's own checklist - see ``test_setup_wizard.py``);
these tests pin the *decisions*, not the window.

They are Qt-free on purpose (no ``gui`` marker): the point of half of them is that
nothing Qt-shaped is imported on the way to the answer.
"""

from __future__ import annotations

import pytest

from starbash import main as main_module

# --- bare `sb` -------------------------------------------------------------


def test_a_bare_sb_launches_the_gui_in_a_desktop_session(monkeypatch):
    """`sb` with no subcommand opens the window instead of printing help."""
    from starbash.ui import qt

    launches: list[str] = []
    monkeypatch.setattr(qt, "desktop_session_available", lambda: True)
    monkeypatch.setattr(qt, "run_gui", lambda: launches.append("gui"))

    assert main_module._try_launch_gui() is True
    assert launches == ["gui"]


def test_a_bare_sb_stays_on_the_cli_without_a_desktop_session(monkeypatch):
    """Headless (SSH) must not so much as try to import/start a GUI."""

    def surprise() -> None:  # pragma: no cover - only runs if the guard fails
        raise AssertionError("run_gui() must not be called without a desktop session")

    from starbash.ui import qt

    monkeypatch.setattr(qt, "desktop_session_available", lambda: False)
    monkeypatch.setattr(qt, "run_gui", surprise)

    assert main_module._try_launch_gui() is False


def test_a_broken_qt_install_falls_back_to_the_cli(monkeypatch, capsys):
    """A partial install says why, then lets the CLI carry on."""
    from starbash.ui import qt

    def broken() -> None:
        raise qt.GuiUnavailableError("PySide6 is not installed")

    monkeypatch.setattr(qt, "desktop_session_available", lambda: True)
    monkeypatch.setattr(qt, "run_gui", broken)

    assert main_module._try_launch_gui() is False
    assert "PySide6 is not installed" in capsys.readouterr().out


def test_the_opt_out_short_circuits_the_desktop_check(monkeypatch):
    """``STARBASH_NO_GUI`` ends the question before any platform sniffing."""
    from starbash.ui import qt

    monkeypatch.setenv("STARBASH_NO_GUI", "1")
    assert qt.desktop_session_available() is False


def test_an_offscreen_platform_is_not_a_desktop_session(monkeypatch):
    """The offscreen plugin draws nothing, so it is not somewhere to show a window.

    This is also what keeps the test suite (``QT_QPA_PLATFORM=offscreen``) from
    ever opening a window when a test runs a bare ``sb``.
    """
    from starbash.ui import qt

    monkeypatch.delenv("STARBASH_NO_GUI", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert qt.desktop_session_available() is False


# --- the first-run wizard trigger ------------------------------------------


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context, so `run()` never touches the user's."""
    from starbash.app import Starbash

    with Starbash("test.gui-launch") as sb:
        yield sb


@pytest.fixture
def fake_app_run(monkeypatch, app_context) -> list[str]:
    """Patch ``starbash.ui.qt.app.run``'s collaborators; record wizard opens.

    ``run()`` is left real, so what is under test is its own wiring: that the
    wizard is scheduled behind the event loop on a first run, and not at all once
    the user is known.
    """
    from starbash.ui.qt import app as app_module

    opened: list[str] = []

    class FakeWindow:
        """Stands in for MainWindow, which needs a real Qt window to exist."""

        def show(self) -> None:
            """Nothing to show in a fake window."""

        def run_setup_wizard(self) -> None:
            """Record that the first-run wizard was opened."""
            opened.append("wizard")

    class FakeApplication:
        """Stands in for QApplication: no event loop to sit in."""

        def exec(self) -> int:
            """Return an exit code without running a loop."""
            return 0

    class FakeInteraction:
        """Stands in for QtUserInteraction, which wants a real widget."""

        def __init__(self, _window: object) -> None:
            """Accept (and ignore) the window it would prompt through."""

    class FakeTimer:
        """Stands in for QTimer, firing a zero-delay call immediately."""

        @staticmethod
        def singleShot(_ms: int, callback: object) -> None:  # noqa: N802 - Qt API
            """Run the scheduled callback now, as a live loop would."""
            assert callable(callback)
            callback()

    monkeypatch.setattr(app_module, "Starbash", lambda *_a, **_k: app_context)
    monkeypatch.setattr(app_module, "create_application", lambda *_a, **_k: FakeApplication())
    monkeypatch.setattr(app_module, "install_desktop_entry", lambda: None)
    monkeypatch.setattr(app_module, "MainWindow", lambda *_a, **_k: FakeWindow())
    monkeypatch.setattr(app_module, "QtUserInteraction", FakeInteraction)
    monkeypatch.setattr(app_module, "set_interaction", lambda _interaction: None)
    monkeypatch.setattr(app_module, "QTimer", FakeTimer)
    return opened


@pytest.fixture
def required_tools_present(monkeypatch) -> None:
    """Pretend every required tool is installed.

    The suite runs on machines without Siril, so a test that wants to isolate one
    of the *other* setup minimums has to stub the tool gate.  It patches the
    wizard's own ``_required_tools_missing`` - the same check ``ToolsPage`` and
    ``setup_checklist`` use - so nothing here bypasses the real logic.
    """
    from starbash.ui.qt.pages import wizard as wizard_module

    monkeypatch.setattr(wizard_module, "_required_tools_missing", lambda: [])


def _finish_setup(app_context, tmp_path) -> None:
    """Meet every setup minimum, the way the wizard's pages would."""
    app_context.user_repo.set("user.name", "Ada Lovelace")
    app_context.add_local_repo(str(tmp_path / "master"), repo_type="master")
    app_context.add_local_repo(str(tmp_path / "processed"), repo_type="processed")
    lights = tmp_path / "lights"
    lights.mkdir()  # a raw-image repo must exist; the output repos need not
    app_context.add_local_repo(str(lights))


def test_run_opens_the_wizard_on_a_first_run(fake_app_run):
    """A first run gets the wizard, scheduled once the event loop is live."""
    from starbash.ui.qt import app as app_module

    assert app_module.run() == 0
    assert fake_app_run == ["wizard"]


def test_run_reopens_the_wizard_when_a_minimum_is_missing(
    app_context, fake_app_run, required_tools_present
):
    """A name is not *set up*: missing output folders still bring the wizard back."""
    from starbash.ui.qt import app as app_module

    app_context.user_repo.set("user.name", "Ada Lovelace")

    assert app_module.run() == 0
    assert fake_app_run == ["wizard"]


def test_run_skips_the_wizard_once_setup_is_complete(
    app_context, fake_app_run, required_tools_present, tmp_path
):
    """A user whose setup is finished goes straight to the window, not through it."""
    from starbash.ui.qt import app as app_module

    _finish_setup(app_context, tmp_path)

    assert app_module.run() == 0
    assert fake_app_run == []
