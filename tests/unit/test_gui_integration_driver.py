"""Tests for the ``gui_integration`` driver: the pump/click primitives and the step chain.

``tests/gui_integration/driver.py`` has one job - let a test drive a *live* GUI without
blocking it - and its contract is what makes that safe: **poll, never block**, **give up at
a deadline**, and **name the step** that went wrong.  Those are all cheap to test here, with
no ffmpeg and no ``/test-data``, so the driver's own bugs fail a fast test rather than a
several-minute movie run.

Qt needs a platform plugin: ``tests/conftest.py`` pins ``QT_QPA_PLATFORM=offscreen`` so this
module runs headless, and it skips if Qt cannot start at all.
"""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    if _QApplication.instance() is None:
        _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton  # noqa: E402

from starbash import events  # noqa: E402
from starbash.ui.qt.pages import wizard as wizard_mod  # noqa: E402
from starbash.ui.qt.pages.wizard import Page, SetupWizard  # noqa: E402
from tests.gui_integration import driver as driver_mod  # noqa: E402
from tests.gui_integration.driver import (  # noqa: E402
    WizardDriver,
    click,
    go_to,
    pump_until,
    set_checked,
    type_text,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context, so the wizard under test is the real one."""
    from starbash.app import Starbash

    with Starbash("test.gui-driver") as sb:
        yield sb


@pytest.fixture(autouse=True)
def _clean_bus():
    """Give each test a pristine event bus."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


@pytest.fixture
def wizard(qtbot, app_context) -> SetupWizard:
    """A real, shown (offscreen) wizard - what the driver drives in the movie script."""
    widget = SetupWizard(app_context)
    qtbot.addWidget(widget)
    widget.show()
    return widget


@pytest.fixture
def driver(qapp, wizard) -> WizardDriver:
    """A driver handed the wizard the way :meth:`WizardDriver.install` would.

    ``install()`` needs ``exec()`` to be reached for real; setting ``wizard`` directly is
    the same state, without a nested loop - and the install seam has its own test below.
    """
    made = WizardDriver(qapp, pause=0.01)
    made.wizard = wizard
    return made


# --- the primitives ----------------------------------------------------------


def test_pump_until_processes_events_while_it_waits(qapp) -> None:
    """The loop it spins is a *live* one: a timer scheduled before it still fires."""
    fired: list[int] = []
    QTimer.singleShot(30, lambda: fired.append(1))
    assert pump_until(qapp, lambda: bool(fired), 5.0) is True


def test_pump_until_gives_up_at_its_deadline(qapp) -> None:
    """A stuck app must fail the test - never hang the job (the mandatory-deadline rule)."""
    started = time.monotonic()
    assert pump_until(qapp, lambda: False, 0.2, tick=0.01) is False
    elapsed = time.monotonic() - started
    assert 0.2 <= elapsed < 3.0, f"waited {elapsed:.2f}s for a 0.2s deadline"


def test_click_presses_the_real_button(qapp) -> None:
    """A real click, wired to the real signal - not a ``button.click()`` shortcut."""
    button = QPushButton("Go")
    hits: list[int] = []
    button.clicked.connect(lambda: hits.append(1))
    try:
        click(button, qapp, pause=0.0)
    finally:
        button.deleteLater()
    assert hits == [1]


def test_type_text_focuses_the_widget_and_enters_the_text(qapp) -> None:
    """The keystrokes land *in this widget* - which is only true if focus() took."""
    edit = QLineEdit()
    try:
        type_text(edit, "Ada Lovelace", qapp, pause=0.0)
    finally:
        edit.deleteLater()
    # The text *is* the focus assertion: QTest.keyClicks sends to the focused widget, so an
    # empty field would mean focus never arrived.  (`hasFocus()` itself is not usable here -
    # offscreen, an unshown top-level is never the active window.)
    assert edit.text() == "Ada Lovelace"


def test_set_checked_clicks_rather_than_setting_the_state(qtbot, qapp) -> None:
    """It emits what a user click emits - ``setChecked`` would fire nothing.

    The wizard's pages read that signal, so a driver that quietly called ``setChecked``
    would leave the page's own handlers unfired and the journey would stall for reasons
    that look nothing like a checkbox.
    """
    box = QCheckBox("analytics")
    qtbot.addWidget(box)
    box.show()  # a real click only toggles a *shown* widget
    seen: list[bool] = []
    box.toggled.connect(seen.append)

    set_checked(box, True, qapp, pause=0.0)
    assert box.isChecked() is True
    assert seen == [True]

    # Already in the wanted state: nothing to click, so nothing is emitted.
    set_checked(box, True, qapp, pause=0.0)
    assert seen == [True]

    set_checked(box, False, qapp, pause=0.0)
    assert box.isChecked() is False
    assert seen == [True, False]


# --- go_to: press the real Next, and wait for the page -----------------------


def test_go_to_presses_next_and_waits_for_a_page_that_refuses_to_be_left(qapp, wizard) -> None:
    """``go_to`` presses the wizard's own *Next* and cannot be hurried past a page.

    Two contracts in one journey: the press is the **real button** (so the enabled state the
    pages compute is part of what is tested), and a page that refuses to be left makes the
    step answer ``False`` - which is how the movie script waits instead of marching on.
    """
    first = go_to(Page.YOU, qapp, pause=0.0)
    assert wizard.currentId() == int(Page.WELCOME)
    assert first(wizard) is True
    assert wizard.currentId() == int(Page.YOU)

    second = go_to(Page.FOLDERS, qapp, pause=0.0)
    # No username yet: the page's validatePage() refuses, so no amount of pressing helps.
    assert second(wizard) is False
    assert wizard.currentId() == int(Page.YOU)

    type_text(wizard.findChild(QLineEdit, "wizardName"), "Ada", qapp, pause=0.0)
    assert second(wizard) is True
    assert wizard.currentId() == int(Page.FOLDERS)


def test_go_to_does_nothing_when_it_is_already_there(qapp, wizard) -> None:
    """Idempotent by construction - the retry contract depends on it."""
    step = go_to(Page.WELCOME, qapp, pause=0.0)
    assert wizard.currentId() == int(Page.WELCOME)
    assert step(wizard) is True
    assert wizard.currentId() == int(Page.WELCOME)


# --- the step chain ----------------------------------------------------------


def test_add_and_wait_for_chain_off_the_driver(qapp) -> None:
    """Both builders return the driver, which is what makes a journey one expression."""
    made = WizardDriver(qapp, pause=0.0)
    assert made.add("a", lambda _w: True) is made
    assert made.wait_for("b", lambda _w: True) is made


def test_the_chain_runs_every_step_in_order(qapp, driver) -> None:
    seen: list[str] = []
    for label in ("one", "two", "three"):
        driver.add(label, lambda _w, label=label: seen.append(label) or True)

    driver.start()
    assert pump_until(qapp, lambda: len(seen) == 3, 5.0), f"only got to {seen}"
    assert seen == ["one", "two", "three"]
    driver.result()  # a completed journey reports nothing


def test_wait_for_re_reads_its_condition_against_the_live_wizard(qapp, driver) -> None:
    """A condition may reference state that only exists once the step runs.

    It is re-evaluated every retry, which is what lets a script say "the page picked the
    folder up" before the page has had a chance to.
    """
    driver.wait_for("wizard is on the welcome page", lambda w: w.currentId() == 1)
    driver.start()
    assert pump_until(qapp, lambda: not driver._steps, 5.0)  # noqa: SLF001 - the chain itself
    driver.result()


def test_a_step_that_never_completes_times_out_and_closes_the_wizard(
    qapp, driver, wizard, monkeypatch
) -> None:
    """The deadline is the whole reason a stuck app fails a test instead of hanging a job."""
    monkeypatch.setattr(driver_mod, "STEP_TIMEOUT_SECONDS", 0.1)
    driver.add("never", lambda _w: False)

    driver.start()
    assert pump_until(qapp, lambda: driver.timed_out is not None, 5.0)
    assert driver.timed_out == "never"
    # It closed the wizard on the way out, so a blocking exec() would have returned.
    assert wizard.isVisible() is False
    with pytest.raises(TimeoutError, match="never"):
        driver.result()


def test_a_raising_step_is_reported_rather_than_swallowed(qapp, driver) -> None:
    """A failed step must surface as *its own* error, not as a mystery timeout."""
    boom = ValueError("no wizard page today")

    def explode(_wizard) -> bool:
        raise boom

    driver.add("boom", explode)
    driver.start()
    assert pump_until(qapp, lambda: driver.error is not None, 5.0)
    assert driver.error is boom
    with pytest.raises(ValueError, match="no wizard page today"):
        driver.result()


def test_result_names_the_steps_that_never_ran(qapp, driver) -> None:
    """A journey that stopped early is a failure, and the report says which steps."""
    driver.add("first", lambda _w: True)
    driver.add("second", lambda _w: True)

    with pytest.raises(TimeoutError, match="first, second"):
        driver.result()


def test_install_hands_over_the_real_wizard_and_is_undone(qapp, app_context, monkeypatch) -> None:
    """``install`` subclasses the class the *factory* reads, and monkeypatch puts it back.

    The seam has to sit on ``wizard_mod.SetupWizard``: ``run_setup_dialog`` looks that name
    up in its own globals, so patching anywhere else would silently record nothing.
    """
    handed: list[SetupWizard] = []
    made = WizardDriver(qapp, pause=0.0, on_wizard=handed.append)
    made.install(monkeypatch)

    patched = wizard_mod.SetupWizard
    assert patched is not SetupWizard
    assert issubclass(patched, SetupWizard)
    assert wizard_mod.run_setup_dialog.__globals__["SetupWizard"] is patched

    built = patched(app_context)
    try:
        assert made.wizard is built
        assert handed == [built]
    finally:
        built.deleteLater()

    monkeypatch.undo()
    assert wizard_mod.SetupWizard is SetupWizard
