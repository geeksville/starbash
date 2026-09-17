"""Tests for the widget-to-mp4 recorder used by the ``gui-integration`` suite.

The recorder has to be verifiable **without** ffmpeg (so the suite is not a coin flip on
whatever binary a machine happens to have), so almost everything here drives a real
``QTimer`` with an injected recording :class:`FrameEncoder`. One test at the end uses real
ffmpeg - skipped when there is none - to pin the rawvideo pipe and the probe together.

What these tests are really protecting:

* the frames are the widget's own geometry - no resize, and rounded down to what an
  ``Format_RGB888`` row stride and libx264's ``yuv420p`` can both represent;
* ``start()`` stores one frame immediately, then exactly one per tick, and a tick that
  arrives while the previous grab is still running is *dropped*, never queued;
* the capture rate is changeable (that is the fast-forward) while the movie's frame rate
  is not, with the segment bookkeeping to prove it.
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

from PySide6.QtWidgets import QLabel  # noqa: E402

from tests.gui_integration.qtmovie import (  # noqa: E402
    MovieRecorder,
    even_size,
    find_ffmpeg,
    interval_ms,
    parse_ffmpeg_report,
    probe_movie,
)

pytestmark = pytest.mark.gui

#: Trimmed from a real `ffmpeg -i … -f null -` (imageio-ffmpeg's bundled v7.0.2).
SAMPLED_REPORT = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/tmp/gui-check.mp4':
  Duration: 00:01:02.50, start: 0.000000, bitrate: 136 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), \
1280x820, 127 kb/s, 30 fps, 30 tbr, 15360 tbn (default)
[out#0/null @ 0x1b6559c0] video:15KiB audio:0KiB subtitle:0KiB other streams:0KiB
frame=  1875 fps=0.0 q=-0.0 Lsize=N/A time=00:01:02.50 bitrate=N/A speed=48.9x
"""

#: How long to wait for the recorder's 30 fps timer, in ms.
FRAME_WAIT = 5000


class RecordingEncoder:
    """A :class:`FrameEncoder` that keeps the frames in memory."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.frames: list[bytes] = []
        self.closes = 0
        self.delay = delay

    def write(self, frame: bytes) -> None:
        if self.delay:
            time.sleep(self.delay)  # simulate a slow encoder / a slow grab
        self.frames.append(frame)

    def close(self) -> None:
        self.closes += 1


class FailingCloseEncoder(RecordingEncoder):
    """An encoder that cannot flush - the recorder must report that, not swallow it."""

    def close(self) -> None:
        super().close()
        raise RuntimeError("flush failed")


def make_widget(qtbot, width: int, height: int, text: str = "starbash") -> QLabel:
    """A real, shown widget of a known size (offscreen)."""
    widget = QLabel(text)
    widget.resize(width, height)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((320, 200), (320, 200)),  # already aligned: untouched
        ((101, 49), (100, 48)),  # 101*3 = 303 is not a multiple of 4; 49 is odd
        ((1, 1), (4, 2)),  # never zero: the pipe needs a frame size
    ],
)
def test_even_size_rounds_down_for_the_raw_rgb_stride(size, expected):
    """The rounding is what keeps ``len(frame) == w*h*3`` true (see QtMovieFile)."""
    assert even_size(size) == expected


def test_interval_ms_is_the_sampling_period():
    assert interval_ms(30.0) == 33
    assert interval_ms(1.0) == 1000
    assert interval_ms(100.0) == 10
    with pytest.raises(ValueError):
        interval_ms(0)


def test_parse_ffmpeg_report_reads_a_real_report():
    """The "0x"-stripping trap: 1280x820 must survive it (a naive regex eats "0x820")."""
    info = parse_ffmpeg_report(SAMPLED_REPORT)
    assert (info.width, info.height) == (1280, 820)
    assert info.frames == 1875
    assert info.duration == pytest.approx(62.5)
    assert info.codec == "h264"


def test_parse_ffmpeg_report_needs_a_video_stream_and_a_frame_count():
    with pytest.raises(ValueError, match="no video stream"):
        parse_ffmpeg_report("ffmpeg version 7.0.2\nOutput #0, null, to 'pipe:'\n")

    with pytest.raises(ValueError, match="cannot parse"):
        parse_ffmpeg_report(SAMPLED_REPORT.replace("frame=  1875", ""))


def test_find_ffmpeg_honours_an_explicit_binary(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("STARBASH_FFMPEG", str(fake))
    assert find_ffmpeg() == str(fake)


def test_a_broken_starbash_ffmpeg_means_no_ffmpeg_at_all(monkeypatch, tmp_path):
    """If you name a binary you meant it: never fall through to some other ffmpeg."""
    monkeypatch.setenv("STARBASH_FFMPEG", str(tmp_path / "does-not-exist"))
    assert find_ffmpeg() is None


def test_frames_are_the_widgets_own_size(qtbot, tmp_path):
    """No resize: the geometry is the window's, and every frame is exactly w*h*3."""
    widget = make_widget(qtbot, 320, 200)
    encoder = RecordingEncoder()
    path = tmp_path / "gui.mp4"
    recorder = MovieRecorder(widget, path, encoder=encoder)

    assert recorder.size is None  # latched by start(), not before
    recorder.start()
    try:
        assert recorder.size == (320, 200)
        assert widget.size().toTuple() == (320, 200)  # the recorder resized nothing
        assert len(encoder.frames) == 1  # start() stores one frame immediately
        qtbot.waitUntil(lambda: recorder.frames >= 5, timeout=FRAME_WAIT)
    finally:
        result = recorder.stop()

    assert all(len(frame) == 320 * 200 * 3 for frame in encoder.frames)
    assert result.frames == len(encoder.frames)
    assert result.size == (320, 200)
    assert result.path == path
    assert result.dropped <= 1  # a stalled machine is the only way to skip a sample here


def test_an_unaligned_widget_is_rounded_down_to_a_codec_friendly_size(qtbot, tmp_path):
    """101x49 is not something a rawvideo pipe + yuv420p can be fed (see even_size)."""
    widget = make_widget(qtbot, 101, 49)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.start()
    result = recorder.stop()

    assert result.size == (100, 48)
    assert len(encoder.frames[0]) == 100 * 48 * 3


def test_a_window_resized_mid_recording_keeps_the_latched_geometry(qtbot, tmp_path):
    """A rawvideo pipe's -s cannot change mid-stream, so a resize must not leak in."""
    widget = make_widget(qtbot, 160, 100)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.start()
    try:
        widget.resize(400, 300)
        qtbot.waitUntil(lambda: recorder.frames >= 3, timeout=FRAME_WAIT)
    finally:
        result = recorder.stop()

    assert result.size == (160, 100)
    assert all(len(frame) == 160 * 100 * 3 for frame in encoder.frames)


def test_every_tick_stores_exactly_one_frame(qtbot, tmp_path):
    """start()'s immediate frame plus one per tick - no repeats, no catch-up."""
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.start()
    qtbot.waitUntil(lambda: recorder.ticks >= 10, timeout=FRAME_WAIT)
    result = recorder.stop()

    assert result.frames == recorder.ticks + 1
    assert result.frames == len(encoder.frames)
    assert result.seconds == pytest.approx(result.frames / 30.0)
    # Nothing was skipped either: the stored frames account for the whole stretch. (A
    # machine that stalls mid-test can add a drop, hence the small tolerance.)
    assert result.dropped <= 1
    assert result.frames == pytest.approx(result.segments[0].real_seconds * 30.0, abs=2)


def test_a_slow_encoder_drops_samples_instead_of_queueing(qtbot, tmp_path):
    """A live recording samples reality; it does not replay what it missed.

    With the GUI thread blocked inside the encoder, Qt cannot even deliver the ticks, so
    the movie is a coarse sample of the stretch - and `dropped` is the honest count of the
    samples the 30 fps cadence asked for and did not get. Nothing is written twice to
    "catch up".
    """
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder(delay=0.15)  # ~4 ticks' worth at 30 fps
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.start()
    qtbot.waitUntil(lambda: recorder.ticks >= 20, timeout=FRAME_WAIT)
    result = recorder.stop()

    assert result.dropped > 0  # it could not keep up, and says so
    # ... and the bookkeeping is honest: stored + missed accounts for the whole stretch,
    # less only the partial interval between the last stored frame and stop() (with a
    # 0.15 s encoder that leftover is up to ~4.5 samples), plus modest platform timer
    # scheduling variance while the GUI thread is deliberately blocked.
    assert result.frames + result.dropped == pytest.approx(
        result.segments[0].real_seconds * 30.0, abs=10
    )
    assert result.frames == len(encoder.frames)
    # One frame per delivered tick plus start()'s - never a burst of frames to catch up.
    assert result.frames == recorder.ticks + 1


def test_stop_closes_the_encoder_once_and_reports_the_movie(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    path = tmp_path / "gui.mp4"
    recorder = MovieRecorder(widget, path, encoder=encoder)
    recorder.start()
    qtbot.waitUntil(lambda: recorder.frames >= 2, timeout=FRAME_WAIT)
    result = recorder.stop()

    assert encoder.closes == 1
    assert recorder.running is False
    assert result.path == path
    assert result.capture_fps == 30.0
    assert result.size == (64, 48)
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.label == "recording"
    assert segment.capture_fps == 30.0
    assert segment.frames == result.frames
    assert segment.output_seconds == pytest.approx(result.seconds)
    assert segment.real_seconds >= 0.0

    assert recorder.stop() is result  # idempotent
    assert encoder.closes == 1


def test_start_is_idempotent(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.start()
    frames = len(encoder.frames)
    recorder.start()  # must not restart the timer or open a second segment
    assert recorder.running is True
    assert len(encoder.frames) == frames
    assert recorder.stop().segments[0].frames == frames


def test_stop_without_start_is_a_harmless_noop(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    path = tmp_path / "gui.mp4"
    recorder = MovieRecorder(widget, path)  # no encoder, and never started
    result = recorder.stop()

    assert result.frames == 0
    assert result.dropped == 0
    assert result.segments == ()
    assert result.size == (0, 0)
    assert not path.exists()


def test_grab_now_requires_a_running_recorder(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=RecordingEncoder())
    with pytest.raises(RuntimeError, match="before start"):
        recorder.grab_now()


def test_grab_now_stores_a_frame_on_demand(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder, fps=0.1)
    recorder.start()
    for _ in range(3):
        recorder.grab_now()
    result = recorder.stop()

    assert result.frames == 4  # the one start() took, plus three on demand
    assert len(encoder.frames) == 4


def test_the_context_manager_stops_and_flushes(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    with MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder) as recorder:
        recorder.start()
        qtbot.waitUntil(lambda: recorder.frames >= 2, timeout=FRAME_WAIT)

    assert recorder.running is False
    assert encoder.closes == 1


def test_exit_does_not_mask_an_exception_from_the_body(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    with pytest.raises(ValueError, match="boom"):
        with MovieRecorder(widget, tmp_path / "gui.mp4", encoder=FailingCloseEncoder()):
            raise ValueError("boom")


def test_a_failed_encoder_close_is_reported_not_swallowed(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=FailingCloseEncoder())
    recorder.start()
    with pytest.raises(RuntimeError, match="flush failed"):
        recorder.stop()


def test_set_capture_fps_changes_the_sampling_interval_only(qtbot, tmp_path):
    """The cadence knob: 5 Hz samples, but the movie stays 30 fps (and keeps its length)."""
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    assert recorder.interval_ms == 33

    recorder.set_capture_fps(5.0, label="slow")  # before start: just the initial rate
    assert recorder.capture_fps == 5.0
    recorder.start()
    assert recorder.interval_ms == 200
    assert len(encoder.frames) == 1  # start() still takes its frame immediately

    qtbot.waitUntil(lambda: recorder.ticks >= 1, timeout=FRAME_WAIT)
    ticks_before = recorder.ticks
    frames_before = len(encoder.frames)
    recorder.set_capture_fps(30.0, label="ui")
    assert recorder.interval_ms == 33
    assert len(encoder.frames) == frames_before + 1  # one frame at the moment of the change
    result = recorder.stop()

    assert [segment.label for segment in result.segments] == ["slow", "ui"]
    assert [segment.capture_fps for segment in result.segments] == [5.0, 30.0]
    assert sum(segment.frames for segment in result.segments) == result.frames
    assert result.segments[0].frames == ticks_before + 1
    assert result.capture_fps == 30.0  # the movie's rate never changed
    for segment in result.segments:
        assert segment.output_seconds == pytest.approx(segment.frames / 30.0)


def test_changing_the_rate_is_not_counted_as_dropped_samples(qtbot, tmp_path):
    """Decimating is the point of the cadence knob, not a failure to keep up."""
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.set_capture_fps(2.0, label="slow")
    recorder.start()
    qtbot.waitUntil(lambda: recorder.frames >= 2, timeout=FRAME_WAIT)
    qtbot.wait(300)  # land the change mid-interval, so a stale 500 ms gap is visible
    # Back to 30 fps: measured at the *new* interval that 300 ms gap would look like ~9
    # missed samples, but they were skipped on purpose.
    recorder.set_capture_fps(30.0, label="ui")
    result = recorder.stop()

    assert result.dropped <= 1
    assert [segment.label for segment in result.segments] == ["slow", "ui"]
    assert sum(segment.frames for segment in result.segments) == result.frames


def test_a_slowly_sampled_segment_plays_back_faster_than_it_happened(qtbot, tmp_path):
    """The point of the whole cadence mechanism: ~1 s of run, ~0.07 s of movie."""
    widget = make_widget(qtbot, 64, 48)
    encoder = RecordingEncoder()
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=encoder)
    recorder.set_capture_fps(1.0, label="processing")  # 1 fps => 30x fast-forward
    recorder.start()
    qtbot.wait(1000)
    result = recorder.stop()

    processing = result.segments[0]
    assert processing.real_seconds > 0.5
    assert processing.frames <= 2
    assert processing.output_seconds < processing.real_seconds / 10.0


def test_repeating_the_same_capture_fps_does_not_open_an_empty_segment(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=RecordingEncoder())
    recorder.start()
    recorder.set_capture_fps(30.0)  # same rate, no label
    recorder.set_capture_fps(30.0, label="recording")  # same rate and label
    result = recorder.stop()

    assert len(result.segments) == 1
    assert result.segments[0].label == "recording"


def test_set_capture_fps_rejects_a_useless_rate(qtbot, tmp_path):
    widget = make_widget(qtbot, 64, 48)
    recorder = MovieRecorder(widget, tmp_path / "gui.mp4", encoder=RecordingEncoder())
    with pytest.raises(ValueError, match="must be positive"):
        recorder.set_capture_fps(0.0)


@pytest.mark.skipif(find_ffmpeg() is None, reason="no ffmpeg available (see find_ffmpeg)")
def test_a_real_recording_is_a_real_movie(qtbot, tmp_path):
    """The whole pipe: widget -> rawvideo -> libx264 -> a file ffmpeg can read back.

    100 is deliberate: "100x48" contains "0x48", the shape that a naive hex-stripping
    regex eats out of ffmpeg's geometry report (see parse_ffmpeg_report).
    """
    path = tmp_path / "gui.mp4"  # an extension ffmpeg cannot map to a muxer
    widget = make_widget(qtbot, 100, 48, text="hello movie")
    recorder = MovieRecorder(widget, path, fps=10.0)
    recorder.start()
    qtbot.waitUntil(lambda: recorder.frames >= 5, timeout=FRAME_WAIT)
    result = recorder.stop()

    assert result.path.exists()
    info = probe_movie(path)
    assert (info.width, info.height) == (100, 48)
    assert info.codec == "h264"
    assert info.frames == result.frames
    assert info.duration == pytest.approx(result.seconds, abs=0.25)


@pytest.mark.skipif(find_ffmpeg() is None, reason="no ffmpeg available (see find_ffmpeg)")
def test_probe_rejects_a_missing_empty_or_garbage_file(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist or is empty"):
        probe_movie(tmp_path / "nothing.mp4")

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeError, match="does not exist or is empty"):
        probe_movie(empty)

    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a movie at all")
    with pytest.raises(RuntimeError, match="no video stream"):
        probe_movie(garbage)
