"""Driving a live GUI from a test: pump, click, type - and drive the modal wizard.

Kept small on purpose (``doc/plans/gui-integration-video.md`` §5.1): four primitives
(:func:`pump`, :func:`click`, :func:`type_text`, :func:`set_checked`), one step factory
(:func:`go_to`) and one helper class (:class:`WizardDriver`).  It is *not* a framework - it is
the smallest thing that lets a test press real widgets and let the recorder keep filming
while it waits.

Two rules are load-bearing here:

* **Never block the GUI thread.** A ``threading.Event.wait()`` (or ``time.sleep``) on the GUI
  thread would freeze the very app being filmed: no repaints, no ``run_async`` callbacks, and
  - because the recorder's ``QTimer`` could not fire either - no frames at all.  Every wait
  therefore spins ``QApplication.processEvents()``, which is what lets a *nested* wait (one
  inside an open modal dialog) work too.
* **Ultimate timeouts are mandatory.** ``pump_until`` gives up after a deadline, so a stuck
  app fails the test with a message instead of hanging a CI job forever.
* **Steps must be idempotent.** A step that answers ``False`` is called again after the
  pause, so a step must not simply do something and report where it ended up: simplest is
  to ask for the state you want each time (see :func:`go_to` and :func:`set_checked`) - a
  bare ``wizard.next()`` called twice overshoots its page.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QWidget,
    QWizard,
)

from starbash.ui.qt.pages import wizard as wizard_mod
from starbash.ui.qt.pages.wizard import SetupWizard

logger = logging.getLogger(__name__)

#: How long to let the event loop spin after each GUI action, so the movie shows the result.
#: ``$STARBASH_GUI_MOVIE_FAST`` shrinks it to iterate on a script without re-watching a
#: leisurely movie.
PAUSE_SECONDS = 0.2 if os.environ.get("STARBASH_GUI_MOVIE_FAST") else 1.0

#: Longest a single wizard step may keep answering "not yet" before the driver gives up.
STEP_TIMEOUT_SECONDS = 300.0

#: Slice of event loop each wait runs. Short enough that the GUI and its timers stay live.
_PUMP_SLICE_SECONDS = 0.01


def pump(app: QApplication, seconds: float) -> None:
    """Let the GUI breathe (and the recorder keep ticking) for ``seconds``."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        app.processEvents()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        # Sleeping between passes matters: processEvents in a tight loop would spin a core
        # while the timer events this is waiting for stay queued behind us.
        time.sleep(min(_PUMP_SLICE_SECONDS, remaining))


def pump_until(
    app: QApplication,
    stop: Callable[[], bool],
    timeout: float,
    *,
    tick: float = 0.05,
) -> bool:
    """Spin the event loop until ``stop()`` (or ``timeout``). True if it stopped."""
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if stop():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(tick)


def click(widget: QWidget, app: QApplication, *, pause: float = PAUSE_SECONDS) -> None:
    """Send a real click, then let the video see the result."""
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    pump(app, pause)


def type_text(
    widget: QWidget, text: str, app: QApplication, *, pause: float = PAUSE_SECONDS
) -> None:
    """Type into ``widget`` the way a user would (focus, then keystrokes)."""
    widget.setFocus()
    QTest.keyClicks(widget, text)
    pump(app, pause)


def set_checked(
    box: QCheckBox, checked: bool, app: QApplication, *, pause: float = PAUSE_SECONDS
) -> None:
    """Click a checkbox until it has the wanted state (a click, not ``setChecked``).

    ``setChecked`` emits nothing, so it would leave the page's own handlers unfired - and
    the point of driving real widgets is that the real wiring runs.
    """
    if box.isChecked() != checked:
        click(box, app, pause=pause)
    else:
        pump(app, pause)


def go_to(
    page: object, app: QApplication, *, pause: float = PAUSE_SECONDS
) -> Callable[[SetupWizard], bool]:
    """A pollable step that presses the wizard's own *Next* until it reaches ``page``.

    It presses the **real button** (not ``wizard.next()``) so the enabled/disabled state the
    pages compute is part of what is being tested, and it is idempotent by construction -
    where the wizard already is gets checked before anything is pressed - which is what the
    driver's retry contract needs (see the module docstring).

    A page that refuses to be left (``validatePage`` returning ``False``: a missing username,
    no image folder) keeps *Next* disabled or stays put, so the step just waits: the driver
    reports it by name when :data:`STEP_TIMEOUT_SECONDS` runs out, rather than the script
    marching past a page it never satisfied.
    """
    target = int(page)  # type: ignore[arg-type]

    def step(wizard: SetupWizard) -> bool:
        if wizard.currentId() == target:
            return True
        button = wizard.button(QWizard.WizardButton.NextButton)
        if isinstance(button, QAbstractButton) and button.isEnabled():
            click(button, app, pause=pause)
        else:
            # Not this page's turn to be left yet; ask again after the pause.
            pump(app, pause)
        return wizard.currentId() == target

    return step


class WizardDriver(QObject):
    """Drive the **modal** setup wizard, from inside its own ``exec()`` loop.

    ``MainWindow.run_setup_wizard()`` calls ``run_setup_dialog()``, which calls
    ``wizard.exec()``: a nested event loop that blocks the *calling Python frame*, not the
    loop itself.  Timers still fire there (measured: a 20 ms timer ticked four times during a
    real ``exec()``), so a step chain scheduled with ``QTimer.singleShot`` runs normally while
    the wizard is up - which is what makes the honest path testable: the real modal wizard,
    real button presses, and the real ``_apply_setup_action(ACTION_PROCESS)`` afterwards.

    Steps are *pollable*: a step returns ``False`` to mean "not ready, ask me again after the
    pause" (so waiting never blocks the loop) and ``True`` when its part of the journey is
    done.  A step that raises - or one that answers ``False`` past
    :data:`STEP_TIMEOUT_SECONDS` - closes the wizard so ``exec()`` returns and the failure
    surfaces in the test instead of hanging it.
    """

    def __init__(
        self,
        app: QApplication,
        *,
        pause: float = PAUSE_SECONDS,
        on_wizard: Callable[[SetupWizard], None] | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._pause = pause
        #: Called the instant the wizard exists - the script composes it into the movie
        #: here (``MovieStage.set_overlay``); the driver itself knows nothing about video.
        self._on_wizard = on_wizard
        self._steps: list[tuple[str, Callable[[SetupWizard], bool]]] = []
        #: The wizard, once ``run_setup_dialog`` has built it (set by :meth:`install`).
        self.wizard: SetupWizard | None = None
        #: The first exception a step raised, if any (re-raised by :meth:`result`).
        self.error: BaseException | None = None
        #: The step that never completed, if the driver gave up waiting for it.
        self.timed_out: str | None = None

    # --- building the journey ---------------------------------------------
    def add(self, label: str, step: Callable[[SetupWizard], bool]) -> WizardDriver:
        """Append a step; returns ``self`` so a journey reads as one expression."""
        self._steps.append((label, step))
        return self

    def wait_for(self, label: str, condition: Callable[[SetupWizard], bool]) -> WizardDriver:
        """Append a step that only waits for ``condition`` to hold.

        The condition is re-read against :attr:`wizard` on every retry, so it may reference
        the wizard the driver has not been handed yet (e.g. "the page picked the folder up").
        """

        def step(wizard: SetupWizard) -> bool:
            return condition(wizard)

        return self.add(label, step)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make ``run_setup_dialog`` hand its wizard to this driver as it builds it.

        The driver must not construct the wizard itself - ``run_setup_dialog`` owns that, and
        exercising it is the point - so the class is *subclassed* and the subclass installed
        in its place: a test seam that changes nothing about the class, and is undone by the
        monkeypatch.

        A subclass rather than a factory function on purpose: the pages ask
        ``isinstance(self.wizard(), SetupWizard)`` (see ``DonePage._action_buttons``), and a
        plain callable in that module-global turns that into a ``TypeError`` - which is
        exactly what the first version of this did.
        """
        driver = self
        real = wizard_mod.SetupWizard

        class RecordingWizard(real):  # type: ignore[misc, valid-type]
            """The real wizard, announcing itself the moment it is built."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                driver.wizard = self
                if driver._on_wizard is not None:
                    driver._on_wizard(self)

        monkeypatch.setattr(wizard_mod, "SetupWizard", RecordingWizard)  # type: ignore[attr-defined]

    def start(self) -> None:
        """Begin the chain. Must be called *before* ``exec()`` opens the nested loop."""
        QTimer.singleShot(0, self._advance)

    # --- the chain --------------------------------------------------------
    def _advance(self) -> None:
        """Run the next step (or wait for a wizard, or finish)."""
        wizard = self.wizard
        if wizard is None:
            # exec() has not built the wizard yet; the loop is running by now, so try again.
            self._later()
            return
        if not self._steps:
            return  # every step is done - the wizard's own buttons finish the journey

        label, step = self._steps[0]
        logger.info("movie: %s", label)
        started = time.monotonic()
        try:
            # Poll, rather than block: processEvents keeps the app (and the recorder) alive
            # while we wait for whatever the step is waiting for.
            while not step(wizard):
                self._app.processEvents()
                if time.monotonic() - started > STEP_TIMEOUT_SECONDS:
                    self.timed_out = label
                    self._close()
                    return
                time.sleep(_PUMP_SLICE_SECONDS)
        except BaseException as error:  # noqa: BLE001 - reported, then re-raised by result()
            logger.exception("movie wizard step failed: %s", label)
            self.error = error
            self._close()
            return

        self._steps.pop(0)
        self._later()

    def _later(self) -> None:
        """Run the next step after the pause, so the movie keeps up."""
        QTimer.singleShot(int(self._pause * 1000), self._advance)

    def _close(self) -> None:
        """Close the wizard so ``exec()`` returns and the test can report the failure."""
        if self.wizard is not None:
            self.wizard.reject()

    def result(self) -> None:
        """Raise whatever went wrong, or return quietly if the journey completed."""
        if self.error is not None:
            raise self.error
        if self.timed_out is not None:
            raise TimeoutError(f"the wizard step {self.timed_out!r} never completed")
        if self._steps:
            raise TimeoutError(
                "the wizard closed before these steps ran: "
                + ", ".join(label for label, _ in self._steps)
            )
