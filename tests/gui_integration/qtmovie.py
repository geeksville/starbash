"""Record a Qt widget to an H.264 mp4, a frame at a time, on a ``QTimer``.

Written for the ``gui-integration`` test suite (see
``doc/plans/gui-integration-video.md``): it films a live ``sb gui`` window while the test
drives it, so a run can be reviewed as a movie instead of being trusted from a green tick.
Nothing under ``src/`` imports this module - it is test-only.

Three properties are deliberate:

* **The frames are the widget's own size.** No window is resized to record it; the
  geometry is latched in :meth:`MovieRecorder.start` and rounded down to what both
  ``Format_RGB888`` and libx264's ``yuv420p`` can represent (see :func:`even_size`).
* **The capture rate is adjustable, the output rate is not.** An mp4 has exactly one
  frame rate, so "fast forward the slow part" is done by storing *fewer* frames
  (:meth:`MovieRecorder.set_capture_fps`), which is what makes a slow pipeline watchable.
* **ffmpeg is a subprocess with a raw-bytes pipe, and it is injectable.** Tests drive a
  recording :class:`FrameEncoder` (no ffmpeg needed at all); real runs use
  :class:`QtMovieFile` with the binary from :func:`find_ffmpeg`.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: Frames stored per second of real time, and the finished movie's playback rate.
DEFAULT_FPS = 30.0

#: Label of the first segment when the caller never labeled one (see ``MovieResult``).
DEFAULT_SEGMENT_LABEL = "recording"

#: How long to wait for ffmpeg to flush the file and exit before killing it.
ENCODER_CLOSE_TIMEOUT = 30.0


def even_size(size: tuple[int, int]) -> tuple[int, int]:
    """Round a frame size down to a geometry both Qt and the codec can represent.

    Width goes down to a multiple of 4 because ``QImage`` pads every
    ``Format_RGB888`` row to a 4-byte boundary: at width 101 ``sizeInBytes()`` is
    14592 while ``w*h*3`` is 14544, and the extra 48 bytes per frame would make the
    rawvideo pipe short a row and ffmpeg emit garbage. Height goes down to a multiple
    of 2 because libx264's ``yuv420p`` refuses an odd one. At most 3 px of window edge
    is cropped, which is why this is cheaper than resizing the window.
    """
    width, height = size
    return max(width - width % 4, 4), max(height - height % 2, 2)


def interval_ms(capture_fps: float) -> int:
    """The ``QTimer`` interval, in ms, that samples at ``capture_fps``."""
    if capture_fps <= 0:
        raise ValueError(f"capture fps must be positive, not {capture_fps}")
    return max(round(1000.0 / capture_fps), 1)


class FrameEncoder(Protocol):
    """A sink for raw RGB24 frames - what makes the recorder testable."""

    def write(self, frame: bytes) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class MovieSegment:
    """One stretch of the movie captured at a single capture rate."""

    label: str
    capture_fps: float
    frames: int  # frames stored while this segment was active
    real_seconds: float  # wall-clock it took
    output_seconds: float  # its length in the finished movie (frames / output fps)


@dataclass(frozen=True)
class MovieResult:
    """What a finished recording turned out to be."""

    path: Path
    frames: int
    dropped: int  # samples the cadence called for but missed (a slow grab/encoder)
    seconds: float  # the movie's length (frames / output fps), not wall clock
    size: tuple[int, int]
    capture_fps: float  # the output fps (constant, see set_capture_fps)
    segments: tuple[MovieSegment, ...]


@dataclass(frozen=True)
class MovieInfo:
    """What ffmpeg says is actually inside a movie file."""

    width: int
    height: int
    frames: int
    duration: float
    codec: str


def find_ffmpeg() -> str | None:
    """``$STARBASH_FFMPEG``, else imageio-ffmpeg's bundled binary, else ``which(ffmpeg)``.

    The bundled binary is the normal path: it makes the tests independent of whatever
    ffmpeg the host happens to have (``poetry install --with dev`` is the whole
    requirement). A bad ``$STARBASH_FFMPEG`` means "skip", never a silent fall-through
    to some other binary - if you named one, you meant it.
    """
    if explicit := os.environ.get("STARBASH_FFMPEG", "").strip():
        return explicit if Path(explicit).exists() else None
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # pragma: no cover - depends on the install
        pass
    return shutil.which("ffmpeg")


def _run_ffmpeg(ffmpeg: str, args: list[str]) -> str:
    """Run ffmpeg and return everything it said on stderr (that is where it reports)."""
    result = subprocess.run([ffmpeg, *args], capture_output=True, text=True, check=False)
    return result.stderr


def parse_ffmpeg_report(report: str) -> MovieInfo:
    """Pull geometry, duration, codec and frame count out of ``ffmpeg -i``'s stderr.

    Split out from :func:`probe_movie` so the parsing - the only fragile part, since it
    reads human-readable log text - can be tested on a canned report.
    """
    video_line = next((line for line in report.splitlines() if "Video:" in line), "")
    if not video_line:
        raise ValueError(f"no video stream in ffmpeg's report:\n{report.strip()}")

    # Hex ids such as "avc1 / 0x31637661" contain an "NxN" shape, so strip them before
    # hunting for the geometry. The lookbehind matters: a plain "0x[0-9a-fA-F]+" also eats
    # the "0x820" out of "1280x820" and leaves no geometry at all.
    clean_line = re.sub(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]+", "", video_line)
    geometry = re.search(r"(\d+)x(\d+)", clean_line)
    duration = re.search(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)", report)
    codec = re.search(r"Video: (\w+)", video_line)
    frame_counts = re.findall(r"frame=\s*(\d+)", report)
    if geometry is None or duration is None or not frame_counts:
        raise ValueError(f"cannot parse ffmpeg's report:\n{report.strip()}")

    hours, minutes, seconds = duration.groups()
    return MovieInfo(
        width=int(geometry.group(1)),
        height=int(geometry.group(2)),
        frames=int(frame_counts[-1]),
        duration=int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        codec=codec.group(1) if codec else "",
    )


def probe_movie(path: str | Path, *, ffmpeg: str | None = None) -> MovieInfo:
    """Ask **ffmpeg itself** what is actually in the file.

    Used by the tests instead of "the file exists": a recorder that silently writes
    zero-byte frames fails loudly, with ffmpeg's own complaint attached. imageio-ffmpeg
    ships no ``ffprobe``, so this uses the binary we already have: ``ffmpeg -i OUT -f null
    -`` decodes the stream and its stderr carries both the header (duration, geometry,
    codec) and the ``frame=`` progress line. Note ``-c copy`` would *not* work here - a
    copied stream reports bytes, not frames.
    """
    binary = ffmpeg or find_ffmpeg()
    if binary is None:
        raise RuntimeError("no ffmpeg available (see find_ffmpeg)")

    movie = Path(path)
    if not movie.exists() or movie.stat().st_size == 0:
        raise RuntimeError(f"{movie} does not exist or is empty")

    report = _run_ffmpeg(binary, ["-i", str(movie), "-f", "null", "-"])
    try:
        return parse_ffmpeg_report(report)
    except ValueError as error:
        raise RuntimeError(f"ffmpeg could not describe {movie}: {error}") from error


class QtMovieFile:
    """Pipes raw RGB24 frames into an ffmpeg subprocess and muxes them to H.264 mp4."""

    def __init__(self, path: str | Path, size: tuple[int, int], fps: float, *, ffmpeg: str) -> None:
        self._path = Path(path)
        self._size = even_size(size)
        width, height = self._size
        self._closed = False
        # ffmpeg's diagnostics go to a temp file, not a pipe: nobody reads a pipe while
        # frames are streaming into stdin, so a chatty ffmpeg would deadlock us.
        self._stderr: IO[bytes] = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{width}x{height}",
                "-framerate",
                f"{fps:g}",
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",  # explicit: the output path may be /tmp/gui.mp4
                str(self._path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr,
        )

    @property
    def path(self) -> Path:
        return self._path

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def write(self, frame: bytes) -> None:
        """Hand one raw RGB24 frame to ffmpeg."""
        stream = self._proc.stdin
        if self._closed or stream is None:
            raise RuntimeError("writing to a closed movie encoder")
        try:
            stream.write(frame)
            stream.flush()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError(
                f"ffmpeg died while recording {self._path}:\n{self._stderr_text()}"
            ) from error

    def close(self) -> None:
        """Close stdin, wait for the muxer, and complain if ffmpeg failed."""
        if self._closed:
            return
        self._closed = True
        text = ""
        returncode = -1
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            try:
                returncode = self._proc.wait(timeout=ENCODER_CLOSE_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.error("ffmpeg did not exit within %gs; killing it", ENCODER_CLOSE_TIMEOUT)
                self._proc.kill()
                returncode = self._proc.wait()
            text = self._stderr_text()
        finally:
            self._stderr.close()
        if returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {returncode}) writing {self._path}:\n{text}")

    def _stderr_text(self) -> str:
        self._stderr.seek(0)
        return self._stderr.read().decode("utf-8", errors="replace")


class MovieRecorder(QObject):
    """Record a ``QWidget`` to an H.264 mp4 by grabbing frames on a ``QTimer``.

    The frames are the widget's **own** size: nothing is resized to record it. Passing
    ``size=None`` (the default) latches ``widget.size()`` at :meth:`start`, rounded down
    to a multiple of 4 (width) / 2 (height) - see :func:`even_size`.

    ``encoder`` is injectable so the recorder can be tested without ffmpeg; a real run
    builds a :class:`QtMovieFile` from :func:`find_ffmpeg` when it starts.
    """

    def __init__(
        self,
        widget: QWidget,
        path: str | Path,
        *,
        size: tuple[int, int] | None = None,
        fps: float = DEFAULT_FPS,
        encoder: FrameEncoder | None = None,
        ffmpeg: str | None = None,
    ) -> None:
        super().__init__(widget)  # Qt destroys the recorder with the filmed widget
        self._widget = widget
        self._path = Path(path)
        self._requested_size = size
        self._size: tuple[int, int] | None = None
        self._fps = fps
        self._capture_fps = fps
        self._encoder = encoder
        self._ffmpeg = ffmpeg
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(interval_ms(fps))
        self._timer.timeout.connect(self._on_tick)
        self._running = False
        self._busy = False
        self._frames = 0
        self._dropped = 0
        self._ticks = 0
        self._last_frame_at: float | None = None
        self._missed_samples = 0.0
        self._error: BaseException | None = None
        self._result: MovieResult | None = None
        self._segments: list[MovieSegment] = []
        self._seg_label = DEFAULT_SEGMENT_LABEL
        self._seg_fps = fps
        self._seg_frames = 0
        self._seg_started: float | None = None

    # -- state ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def size(self) -> tuple[int, int] | None:
        """The latched frame geometry, or ``None`` before :meth:`start`."""
        return self._size

    @property
    def capture_fps(self) -> float:
        """How often frames are sampled right now (not the movie's playback rate)."""
        return self._capture_fps

    @property
    def interval_ms(self) -> int:
        """The live timer interval in ms (how often a frame is sampled)."""
        return self._timer.interval()

    @property
    def ticks(self) -> int:
        """Timer ticks this recorder saw (dropped samples are counted separately)."""
        return self._ticks

    @property
    def frames(self) -> int:
        """Frames stored so far (for progress logging)."""
        return self._frames

    @property
    def dropped(self) -> int:
        """Samples the cadence called for but never stored (see MovieResult.dropped)."""
        return self._dropped

    # -- recording -----------------------------------------------------------

    def start(self) -> None:
        """Latch the geometry, start the timer and the pipe. Idempotent."""
        if self._running:
            return
        self._size = even_size(
            self._requested_size or (self._widget.width(), self._widget.height())
        )
        if self._encoder is None:
            binary = self._ffmpeg or find_ffmpeg()
            if binary is None:
                raise RuntimeError(
                    "no ffmpeg found: install it (poetry install --with dev, or "
                    "apt install ffmpeg) or set $STARBASH_FFMPEG"
                )
            self._encoder = QtMovieFile(self._path, self._size, self._fps, ffmpeg=binary)
        self._running = True
        self._frames = 0
        self._dropped = 0
        self._ticks = 0
        self._error = None
        self._last_frame_at = None
        self._missed_samples = 0.0
        self._segments.clear()
        self._open_segment(self._capture_fps, self._seg_label)
        self._timer.setInterval(interval_ms(self._capture_fps))
        self._timer.start()
        self._capture()

    def grab_now(self) -> None:
        """Store one frame immediately (the first of a segment, or on demand)."""
        if not self._running:
            raise RuntimeError("grab_now() before start()")
        self._capture()

    def set_capture_fps(self, fps: float, *, label: str = "") -> None:
        """Change the sampling cadence.

        ``fps`` is *capture*, not output: the stream's frame rate (and so the movie's
        timeline) never changes, and a lower rate makes this stretch of real time play
        back faster (output fps / fps). One frame is grabbed immediately, then one per
        interval - so the slowed section starts at the moment it was asked for, and the
        segment arithmetic (:attr:`MovieResult.segments`) stays exact.

        Before :meth:`start` it just sets the initial interval and label.
        """
        if not self._running:
            self._capture_fps = fps
            interval_ms(fps)  # validate
            if label:
                self._seg_label = label
            return
        if fps == self._capture_fps and (not label or label == self._seg_label):
            return  # nothing to do; never open an empty segment
        self._close_segment()
        self._capture_fps = fps
        # A new cadence starts a new clock: the samples this change deliberately skips are
        # the fast-forward, not a failure to keep up, so they must not appear as drops.
        self._last_frame_at = None
        self._missed_samples = 0.0
        self._timer.setInterval(interval_ms(fps))
        self._timer.start()  # restart the countdown: no catch-up burst
        self._open_segment(fps, label or DEFAULT_SEGMENT_LABEL)
        self._capture()

    def stop(self) -> MovieResult:
        """Stop ticking, flush ffmpeg, and report what was captured. Idempotent."""
        if self._result is not None:
            return self._result
        self._timer.stop()
        if self._running:
            self._running = False
            self._close_segment()
            if self._encoder is not None:
                try:
                    self._encoder.close()
                except Exception as error:  # noqa: BLE001 - re-raised below, not swallowed
                    self._error = self._error or error
        self._result = MovieResult(
            path=self._path,
            frames=self._frames,
            dropped=self._dropped,
            seconds=self._frames / self._fps,
            size=self._size or (0, 0),
            capture_fps=self._fps,
            segments=tuple(self._segments),
        )
        if error := self._error:
            # stop() without start() stays a harmless no-op, but a recording that broke
            # mid-flight must not be reported as a success.
            self._error = None
            raise error
        return self._result

    def __enter__(self) -> MovieRecorder:
        return self

    def __exit__(self, *exc: object) -> None:
        # Never raise over an exception that is already unwinding the caller.
        try:
            self.stop()
        except Exception:
            if exc[0] is None:
                raise
            logger.exception("failed to stop the movie recorder")

    # -- internals -----------------------------------------------------------

    def _on_tick(self) -> None:
        self._ticks += 1
        if self._busy:
            # A grab is already in flight (something else is pumping this event loop): the
            # frame it is producing is this tick's sample, so nothing to do. What the
            # cadence *missed* is counted by _capture, from the clock - a blocked or
            # re-entering GUI thread never queues frames to write later.
            return
        try:
            self._capture()
        except Exception as error:  # noqa: BLE001 - re-raised by stop()
            self._error = error
            self._timer.stop()
            logger.exception("movie recording failed; the recorder stopped itself")

    def _capture(self) -> None:
        frame = self._grab()
        if frame is None:
            return
        if self._encoder is None:  # pragma: no cover - start() always sets one
            raise RuntimeError("the recorder has no encoder")
        self._encoder.write(frame)
        self._frames += 1
        self._seg_frames += 1
        now = time.monotonic()
        interval_seconds = interval_ms(self._capture_fps) * 0.001
        if self._last_frame_at is not None and interval_seconds > 0:
            # How many samples the cadence asked for between these two frames. The fraction
            # is carried forward, so the total stays exact - `frames + dropped` is the
            # number of samples the interval implies, however coarse the stretch was. The
            # count is *reported*, never replayed: nothing is written twice to catch up.
            self._missed_samples += (now - self._last_frame_at) / interval_seconds - 1.0
            whole = math.floor(self._missed_samples)
            if whole > 0:
                self._dropped += whole
                self._missed_samples -= whole
        self._last_frame_at = now

    def _grab(self) -> bytes | None:
        if self._size is None:  # pragma: no cover - start() always sets one
            raise RuntimeError("the recorder has no frame size")
        width, height = self._size
        self._busy = True
        try:
            # grab() returns a QPixmap (which has no convertToFormat), and the offscreen
            # platform may hand back a high-DPI image, so scale to the latched geometry
            # and take the logical size's bytes.
            image = self._widget.grab().toImage()
            image = image.scaled(width, height).convertToFormat(QImage.Format.Format_RGB888)
            frame = bytes(image.constBits())
        finally:
            self._busy = False
        expected = width * height * 3
        if len(frame) != expected:
            # Never pipe a short frame: ffmpeg would treat it as garbage video. The missed
            # sample is accounted for by the next stored frame's clock arithmetic.
            logger.warning("dropping a %d-byte frame, expected %d", len(frame), expected)
            return None
        return frame

    def _open_segment(self, capture_fps: float, label: str) -> None:
        self._seg_fps = capture_fps
        self._seg_label = label
        self._seg_frames = 0
        self._seg_started = time.monotonic()

    def _close_segment(self) -> None:
        if self._seg_started is None:
            return
        self._segments.append(
            MovieSegment(
                label=self._seg_label,
                capture_fps=self._seg_fps,
                frames=self._seg_frames,
                real_seconds=max(time.monotonic() - self._seg_started, 0.0),
                output_seconds=self._seg_frames / self._fps,
            )
        )
        self._seg_started = None


class MovieStage(QWidget):
    """A canvas that composites the app's windows into one filmable widget.

    **Why this exists.** :meth:`MovieRecorder` films a widget by calling ``grab()`` on it,
    and ``QWidget.grab()`` renders *that widget's own window* - it cannot include a second
    top-level window.  That is exactly the situation the first-run journey is in: the setup
    wizard is a separate, modal window over the main window, so a movie of the main window
    would show an untouched app for the whole wizard (measured: the main window's grab is
    still 1280x820 with the wizard up, and the wizard's own grab is a separate 547x360
    image).

    So the recorder films *this* widget instead, at the main window's size, and its
    ``paintEvent`` draws what the screen would show: the window, dimmed where a dialog
    covers it, and the dialog on top.  The dialog is centred rather than at its real screen
    position, because a grab has no screen coordinates to honour - the movie is a faithful
    *composition*, not a screenshot, and the dimming is what makes the modality visible.

    It is a presentation device only: it owns no state, changes nothing about the app, and
    a recording that never calls :meth:`set_overlay` is just the window itself.
    """

    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._overlay: QWidget | None = None
        # The canvas is the window's own geometry - the recorder latches its size, so the
        # movie is exactly as big as the app (no resize, see the module docstring).
        self.resize(window.size())

    @property
    def filmed_window(self) -> QWidget:
        """The window this stage composites (``window`` itself is a ``QWidget`` method)."""
        return self._window

    def set_overlay(self, overlay: QWidget | None) -> None:
        """Draw ``overlay`` on top of the window (or stop drawing it, with ``None``)."""
        self._overlay = overlay

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Draw the window, dim it, then draw the overlay on top of it."""
        del event
        painter = QPainter(self)
        try:
            # render() (rather than grab()) draws straight into this painter: no second
            # QPixmap, and - the reason it matters here - no re-entrant grab while we are
            # already inside a paint event.
            self._window.render(painter, QPoint(0, 0))
            overlay = self._overlay
            if overlay is None or not overlay.isVisible():
                return
            painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
            # Centred: a grab has no screen position, so the dialog's real geometry says
            # nothing about where it should be drawn (see the class docstring).
            x = max((self.width() - overlay.width()) // 2, 0)
            y = max((self.height() - overlay.height()) // 2, 0)
            painter.translate(x, y)
            overlay.render(painter, QPoint(0, 0))
        finally:
            painter.end()
