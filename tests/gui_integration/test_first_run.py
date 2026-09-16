"""The scripted first run, recorded to a movie - the point of this suite.

One test plays a whole new user's journey through the **real** app: the setup wizard (as the
real modal dialog, via ``MainWindow.run_setup_wizard``), adding a raw-image folder for real,
the closing *Process all my targets* action, and the processing run it starts - filmed to an
mp4 so the result can be *watched* rather than inferred.

Run it with::

    just test-integration-gui          # records /tmp/gui.mp4, then opens it

``$STARBASH_GUI_MOVIE_FAST=1`` shrinks every pause while iterating on the script, and
``$GUI_MOVIE_TEST_DATA`` swaps the dataset the run processes - the default is the one-target
``/test-data/asiair``; ``/test-data`` is the whole tree and takes far longer (raise
:data:`RUN_TIMEOUT_SECONDS` for it).

Three design points worth knowing before editing it:

* **The movie is filmed from a** :class:`~tests.gui_integration.qtmovie.MovieStage`, not the
  window.  A modal dialog is a *separate* top-level window, so it cannot appear in a
  ``grab()`` of ``MainWindow`` at all; the stage draws the window and the wizard over it,
  which is also what makes the modality visible (see the stage's docstring).
* **No resize.**  The stage is the window's own geometry and the recorder latches that size,
  so the movie is as big as the app on screen - the recorder is *never* the reason to resize.
* **Waiting is always a pump** (see :mod:`tests.gui_integration.driver`): blocking the GUI
  thread would stop the app painting **and** stop the recorder's timer - i.e. no movie.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QWidget,
)

from starbash.tool import missing_tool_statuses
from starbash.tool.base import ToolSeverity
from starbash.ui.qt.main_window import MainWindow
from starbash.ui.qt.pages.processing import ProcessingPage
from starbash.ui.qt.pages.wizard import (
    ACTION_PROCESS,
    ImagesPage,
    Page,
    SetupWizard,
)

from .conftest import dataset_root
from .driver import (
    PAUSE_SECONDS,
    WizardDriver,
    click,
    go_to,
    pump,
    pump_until,
    set_checked,
    type_text,
)
from .qtmovie import MovieRecorder, MovieStage, even_size, find_ffmpeg, probe_movie

pytestmark = pytest.mark.gui_integration

logger = logging.getLogger(__name__)

#: The movie's constant playback rate.  It is *output* fps, never sampling: changing the
#: sampling rate below is what makes the slow pipeline play back fast.
MOVIE_FPS = 30.0

#: Sampling during the pipeline: one frame per second of real time, so this stretch plays
#: back at 30x and a 10-minute run costs 20 seconds of movie.  Until this is switched on the
#: recorder samples at :data:`MOVIE_FPS` - i.e. the wizard plays back in real time.
PROCESSING_CAPTURE_FPS = 1.0

#: Longest the pipeline may take before the test gives up waiting for it.  A stuck run must
#: FAIL the test - never hang the job - so every wait in here is bounded by a deadline.
#: Sized for the default dataset; ``$GUI_MOVIE_TEST_DATA=/test-data`` needs a larger one.
RUN_TIMEOUT_SECONDS = 600.0

#: How long the movie lingers on the finished tree, at real speed, before it stops.
SETTLE_SECONDS = 2.0

#: The name the script types in, so the finished config can be asserted on.
USER_NAME = "Ada Lovelace"
USER_EMAIL = "ada@example.invalid"

#: Fraction of the sample cadence the recorder may miss before we call the movie unreliable.
#: Generous on purpose: a busy CI box is slower than the capture timer, and a decimated
#: section is deliberately not counted as a drop at all (see MovieRecorder.set_capture_fps).
MAX_DROPPED_FRACTION = 0.25


def _missing_required_tools() -> list[str]:
    """Names of required tools that are not installed, if any.

    A machine without Siril cannot run the pipeline at all, so this journey is pointless
    there - and worse than pointless, it would sit on the wizard's tools page until the step
    timeout.  Better to say so up front.
    """
    return [
        status.name
        for status in missing_tool_statuses()
        if status.severity == ToolSeverity.REQUIRED
    ]


def _typed[T: QWidget](wizard: SetupWizard, kind: type[T], name: str) -> T:
    """The widget the movie script delivers keystrokes to, found by the §6 handle name.

    ``findChild`` returns ``None`` when the name has been renamed out from under this test, so
    the failure message must say *which* handle is gone rather than raising on ``None``.
    """
    widget = wizard.findChild(kind, name)
    assert widget is not None, f"no {kind.__name__} called {name!r} in the wizard"
    return widget


class _Journey:
    """The steps of the first-run journey, as pollable closures.

    Each one returns ``True`` once its part is *done* and ``False`` while it is still waiting
    (the driver polls, so waiting never blocks the event loop - see :mod:`driver`).  Keeping
    them here, away from the assertions, is what makes the test itself read as a script.
    """

    def __init__(self, app: QApplication, wizard_holder: list[SetupWizard]) -> None:
        self._app = app
        self._holder = wizard_holder
        #: Set once the folder picker has been clicked, so a retry cannot open it twice.
        self.folder_picked = False

    def wizard(self) -> SetupWizard:
        """The wizard under test (put here by the driver's ``on_wizard`` hook)."""
        assert self._holder, "the wizard was never created"
        return self._holder[0]

    def details(self, _wizard: SetupWizard) -> bool:
        """Type the name (and email), and tick both analytics boxes.

        Keystrokes are not idempotent, so this does its work once and answers ``True``
        immediately rather than asking to be retried.
        """
        wizard = self.wizard()
        type_text(_typed(wizard, QLineEdit, "wizardName"), USER_NAME, self._app)
        type_text(_typed(wizard, QLineEdit, "wizardEmail"), USER_EMAIL, self._app)
        set_checked(_typed(wizard, QCheckBox, "wizardAnalytics"), True, self._app)
        set_checked(_typed(wizard, QCheckBox, "wizardIncludeEmail"), True, self._app)
        return True

    def choose_folder(self, _wizard: SetupWizard) -> bool:
        """Click *Choose folder…* once; the picker is stubbed at the dataset.

        The page reports no folder until ``_chosen`` is set, which is what its
        ``isComplete()`` reflects - so this waits for the page rather than for a click.
        """
        images = self.wizard().page_of_type(ImagesPage)
        assert isinstance(images, ImagesPage)
        if images.isComplete():
            return True
        if not self.folder_picked:
            self.folder_picked = True
            click(images.choose_button, self._app)
        return images.isComplete()

    def process_everything(self, _wizard: SetupWizard) -> bool:
        """Press the closing *Process all my targets* action, once it is armed.

        The button is disabled until the last page's own checklist passes (the wizard arms it
        on entry - see ``DonePage.refresh``), so waiting for ``isEnabled`` is how the movie
        stays honest: it cannot click a button a user could not.
        """
        wizard = self.wizard()
        button = _typed(wizard, QPushButton, "wizardProcessAllTargets")
        if not button.isEnabled():
            return False
        click(button, self._app)
        return True


# --- reading the movie back --------------------------------------------------

#: Coarse signature a sampled frame is reduced to before being compared.  Big enough that a
#: page switch or a progress bar changes it, small enough that a whole movie's worth of
#: samples costs kilobytes instead of gigabytes.
_SAMPLE_SIZE = (64, 41)


def _sampled_frames(movie: Path, frames: int, *, samples: int = 12) -> list[bytes]:
    """Decode a spread of ``samples`` frames out of ``movie`` as tiny RGB signatures.

    Every other assertion in this file reads *metadata*, and all of them pass for a movie of
    one frozen window - which is exactly the failure this test would otherwise miss.  The only
    honest check is to decode what was really written, so this pulls frames from the start,
    middle and end and hands back a coarse image of each.  ``-fps_mode passthrough`` is what
    stops ffmpeg duplicating the sparse selection back up to a constant frame rate.
    """
    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None, "ffmpeg is required to read the movie back"
    if frames <= 0:
        return []
    count = min(samples, frames)
    picked = sorted({round(i * (frames - 1) / max(count - 1, 1)) for i in range(count)})
    select = "+".join(f"eq(n\\,{n})" for n in picked)
    width, height = _SAMPLE_SIZE
    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(movie),
            "-vf",
            f"select='{select}',scale={width}:{height}",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    stride = width * height * 3
    return [proc.stdout[i * stride : (i + 1) * stride] for i in range(len(proc.stdout) // stride)]


def test_first_run_is_filmed_end_to_end(
    qtbot,
    gui_app: QApplication,
    app_context,
    movie_output: Path,
    picked_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new user's whole first run, filmed: wizard → folder → processing run → done.

    The assertions are deliberately about *resulting state* rather than "something was
    called": the config the wizard wrote, the run actually starting and finishing, and the
    bytes of the movie at the end.
    """
    missing = _missing_required_tools()
    if missing:
        pytest.skip(f"the pipeline needs these tools installed: {', '.join(missing)}")

    # --- the app, up and being filmed ---------------------------------------
    window = MainWindow(app_context)
    qtbot.addWidget(window)
    window.show()
    pump(gui_app, PAUSE_SECONDS)

    # Film the *stage*, not the window: the wizard is a separate top-level window and could
    # never appear in a grab of `window` (see MovieStage's docstring).
    stage = MovieStage(window)
    qtbot.addWidget(stage)
    stage.show()
    recorder = MovieRecorder(stage, movie_output, fps=MOVIE_FPS)

    wizard_holder: list[SetupWizard] = []

    def on_wizard(wizard: SetupWizard) -> None:
        wizard_holder.append(wizard)
        stage.set_overlay(wizard)

    driver = WizardDriver(gui_app, on_wizard=on_wizard)
    driver.install(monkeypatch)
    journey = _Journey(gui_app, wizard_holder)
    (
        driver.add("welcome → you", go_to(Page.YOU, gui_app))
        .add("type the details", journey.details)
        .add("you → folders", go_to(Page.FOLDERS, gui_app))
        .add("folders → images", go_to(Page.IMAGES, gui_app))
        .add("choose the image folder", journey.choose_folder)
        .add("images → done", go_to(Page.DONE, gui_app))
        .add("process all my targets", journey.process_everything)
    )

    # `run_setup_wizard` opens the wizard's *nested* event loop and only returns once the last
    # step has pressed the closing action - so this call is the whole scripted setup.
    recorder.start()
    try:
        driver.start()
        window.run_setup_wizard()
        driver.result()  # re-raises whatever a step failed with
        stage.set_overlay(None)

        assert wizard_holder, "the wizard never opened"
        assert wizard_holder[0].action == ACTION_PROCESS, (
            "the scripted journey did not end on *Process all my targets*"
        )
        assert app_context.user_repo.get("user.name") == USER_NAME, (
            "the wizard's details were not saved"
        )
        assert picked_folder.exists()
        logger.info("the wizard indexed the dataset at %s", dataset_root())

        # --- the run it started ----------------------------------------------
        page = window.show_page_of_type(ProcessingPage)
        assert page is not None, "the closing action did not open the processing page"

        # `start_run` disables the run button and `_finish` re-enables it, so that pair is the
        # run's own begin/end signal - no internals to poll, and a run that never starts fails
        # here instead of quietly filming an idle window.
        assert pump_until(gui_app, lambda: not page.run_button.isEnabled(), 60.0), (
            "the processing run never started"
        )
        logger.info("run started; sampling at %s fps", PROCESSING_CAPTURE_FPS)
        recorder.set_capture_fps(PROCESSING_CAPTURE_FPS, label="processing")

        finished = pump_until(
            gui_app, lambda: page.run_button.isEnabled(), RUN_TIMEOUT_SECONDS, tick=0.5
        )
        caption = page.caption_label.text()
        assert finished, f"did not finish in {RUN_TIMEOUT_SECONDS:.0f}s ({caption!r})"
        # The end-of-run caption is "<n> task(s) run, <n> succeeded, <n> up-to-date, <n>
        # failed." - so "0 failed" is the success case, and a bare ``"fail" not in caption``
        # would fail on the very summary that proves it worked.  A run that broke carries
        # "Failed: <why>" instead (``ProcessingPage._on_failed``).
        assert not caption.startswith("Failed:"), f"the run failed: {caption}"
        assert "0 failed" in caption, f"the run did not report a clean summary: {caption}"

        # A real-time tail, so the movie ends on the finished tree rather than mid-frame.
        recorder.set_capture_fps(MOVIE_FPS, label="settle")
        pump(gui_app, SETTLE_SECONDS)
        recorder.grab_now()
        result = recorder.stop()

        # --- what the movie turned out to be ---------------------------------
        assert result.path == movie_output
        assert result.path.stat().st_size > 0, "the movie file is empty"
        assert result.size == even_size((window.width(), window.height())), (
            "the movie is not the app's size"
        )
        assert result.frames > 0 and result.seconds > 1.0
        assert result.dropped <= result.frames * MAX_DROPPED_FRACTION, (
            f"{result.dropped} of {result.frames} samples were dropped - a slideshow"
        )

        labels = [segment.label for segment in result.segments]
        assert "processing" in labels, f"the pipeline stretch was never sampled ({labels})"
        fast = next(s for s in result.segments if s.label == "processing")
        assert fast.output_seconds < fast.real_seconds, (
            "the pipeline stretch was not time-lapsed - the movie would be as long as the run"
        )

        ffmpeg = find_ffmpeg()
        assert ffmpeg is not None
        info = probe_movie(movie_output, ffmpeg=ffmpeg)
        assert (info.width, info.height) == result.size
        assert "h264" in info.codec
        assert info.frames == result.frames, "ffmpeg disagrees with the recorder's frame count"
        assert info.duration > 1.0

        # The movie has to *move*: a frozen window satisfies every check above.
        screens = _sampled_frames(movie_output, result.frames)
        assert len(screens) >= 4, f"only {len(screens)} frames could be read back"
        assert len(set(screens)) >= 4, (
            "the sampled frames are all identical - the recording is a still image"
        )

        logger.info(
            "wrote %s: %sx%s, %s frames, %.1fs of movie from %.1fs of wall clock",
            result.path,
            result.size[0],
            result.size[1],
            result.frames,
            result.seconds,
            sum(segment.real_seconds for segment in result.segments),
        )
    finally:
        # Two cleanups that must survive a mid-run failure.  The movie is *muxed* only by
        # `stop()`, so a test that fails before it would leave an unplayable file - and a
        # watchable movie of the failure is exactly what this suite exists to produce.
        # `stop()` is idempotent, so this is a no-op on the happy path.
        stage.set_overlay(None)
        if recorder.running:
            try:
                recorder.stop()
            except Exception:  # noqa: BLE001 - never mask the real failure
                logger.exception("could not finalise the movie after a failure")
