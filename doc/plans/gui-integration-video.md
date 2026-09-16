# Plan: `gui-integration` tests — scripted GUI runs that record an mp4

Status: **implemented** (2026-09-16) — all six phases of §8 are done and green, and the two
open questions in §10 (how to drive the modal wizard, and the default dataset) are *decided*
there, not open. `tests/gui_integration/{qtmovie,driver,conftest,__init__}.py` and the script
`tests/gui_integration/test_first_run.py` are in the tree, with `tests/unit/test_qtmovie.py`
(28 tests) and `tests/unit/test_gui_integration_driver.py` (14 tests) covering the recorder and
the driver; `just test-integration-gui` records the movie end to end. The recorder design (§4)
is measured — and re-measured against the **real `MainWindow`** while implementing it (1280×820
window recorded to a 1280×820 movie in one pass, no resize, no dropped frames). `imageio-ffmpeg`
is in the dev group (§4.3). Verified runs: `just test-integration-gui` passed in **254 s**
(1280×820, 790 frames, 26.33 s of h264 playback), and the full unit suite is green
(1336 passed, 1 skipped) with `just lint` reporting 0 errors.
Related: `doc/plans/gui-setup-wizard.md` (the wizard this drives, and the source of the
`setObjectName` handles), `doc/plans/qt-object-lifetimes.md` and
`doc/plans/gui-widget-teardown.md` (the Qt-lifetime rules the recorder must respect),
`doc/plans/cli-live-display.md` (the event bus the Processing page renders).

## 1. Goal

Add a **third test type**, alongside the unit and `integration` suites: `gui-integration`.
A `gui-integration` test drives the *real* application through a scripted user journey and
captures it to a movie file, so the journey can be reviewed, attached to a release note,
or diffed against yesterday's run — without a human sitting in front of a screen.

The first script (the only one in this phase) is the **first-run setup wizard, end to
end**:

1. start the app with **virgin** config/cache/data (temporary directories, so the run
   looks like a user's very first launch),
2. start recording,
3. show the wizard; fill in a mock username/email, agree to all tracking; walk the
   remaining pages; point the raw-image folder at `/test-data`,
4. pause ~1 s after each GUI action so the video is watchable,
5. press **Process all my targets** on the closing page,
6. watch the Processing page's run tree fill in,
7. end the recording when processing finishes and leave the finished movie at
   **`/tmp/gui.mp4`**.

Two deliverables, and they are separable:

- a **reusable recorder component** (no pytest, no `starbash` imports) that can film any
  Qt widget to mp4 — this is the part worth building carefully, because it is the part we
  will want elsewhere ("somewhere else one day": a `just` recipe, a demo script, a future
  `sb gui --record`);
- a **thin script** that presses the app's widgets by `objectName` (§6).

## 2. Where it lives

```
tests/
  gui_integration/
    __init__.py
    conftest.py          # the gui-integration plumbing + the virgin-dirs fixture
    qtmovie.py           # the recorder component (pytest-free)
    test_first_run.py    # the scripted journey from §5
```

- Root `tests/conftest.py` already pins `QT_QPA_PLATFORM=offscreen`, drains Qt's global
  thread pool and destroys test widgets on the GUI thread. **Keep all three** — the
  recording run is by far the longest-lived Qt session the suite starts, so those hooks
  matter more here, not less.
- `pyproject.toml` gains one marker:

  ```toml
  "gui-integration: marks tests that drive the GUI end to end and record a movie "
  "(needs /test-data; bundled ffmpeg via imageio-ffmpeg; deselect with "
  "'-m \"not gui-integration\"')"
  ```

  The **marker** is what makes a test this type; the package directory is only
  organisation (exactly as `tests/integration/` is organised, with its marker declared
  the same way). Unlike `integration`, though, this one is **deselected by default** —
  `pyproject.toml`'s `addopts` becomes
  `-m 'not slow and not integration and not gui-integration'` — because it is the only
  suite that costs minutes of *wall-clock* time and writes a fixed path (`/tmp/gui.mp4`,
  §10.4). It is opt-in via `-m gui-integration`.
- Run it **sequentially**: `pytest -m gui-integration -n 0` (a fixed output path and
  wall-clock-sensitive capture are not xdist-friendly — the same reason
  `tests/integration/README.md` mandates `-n 0`).

## 3. Why not extend `tests/integration/`

That suite is **CLI through Typer's `CliRunner`** (`tests/integration/README.md`: it needs
`/test-data` and exercises `sb repo add`, `sb process`, …). A `gui-integration` test is the
opposite shape: real widgets, a real event loop, real wall-clock time (the 1 s pauses, the
30 fps timer, and the 1 fps processing fast-forward of §4.5), and a long-lived `run_async`
job behind it. Keeping them apart means
`-m "not integration"` still means "no `/test-data` needed" and `-m "not gui"` still means
"no display needed" — a `gui-integration` test needs the display *and* `/test-data`, so it
must be its own marker rather than a sub-case of either.

### 3.1 What pointing the script at `/test-data` actually queues

This matters for the wall-clock cost, and it is measured, not assumed. The wizard's *Choose
folder…* ends in `sb.add_local_repo()`, whose reindex walks the repo path **recursively**
(`app.py` does `path.rglob("*.fit") + path.rglob("*.fits")`, with no depth limit), so
clicking `/test-data` indexes *every* dataset underneath it:

| dataset | size | FITS files |
|---|---|---|
| `asiair` | 1.4 GB | 27 |
| `dwarf3` | 819 MB | 35 |
| `nina` | 2.2 GB | 44 |
| `seestar` | 64 MB | 16 |
| **total** | **~4.5 GB** | **122** |

(counted here with `find`). So the script as specified runs **four pipelines over 122
frames** — which is the honest first-run story (a user does point at their whole archive),
but it is also the single biggest term in the test's runtime, and §4.5's fast-forward does
nothing to reduce it (it shrinks the movie, not the run — §10.2).

The dataset the picker is given is therefore a module constant read from the environment
(`TEST_DATA`, §5.1), so nothing else in the script changes to trim this — the cheap variants
are all one line each: `GUI_MOVIE_TEST_DATA=/test-data/asiair` (27 frames), or copy one
dataset into `tmp_path` and point at that. The folder picker takes
any directory, so all three go through identical code — only the amount of work differs.
There is one built-in escape hatch, and it is *not* usable here: reindex skips a file whose
path contains `.sbignore` (a substring test), which would mean putting marker files inside
`/test-data`'s datasets — i.e. mutating the shared test data, which is worse than choosing a
smaller `TEST_DATA`. §10.3 keeps the default open.

## 4. The recorder component (`tests/gui_integration/qtmovie.py`)

One module, no pytest import, no `starbash` import — a widget plus an output path is all
it needs. That is what makes it reusable.

### 4.1 Public API

```python
DEFAULT_FPS = 30

class MovieRecorder(QObject):
    """Record a QWidget to an H.264 mp4 by grabbing frames on a QTimer.

    The frames are the widget's **own** size: no window resize is needed or done.
    `size=None` (the default) latches `widget.size()` at `start()`, rounded down to a
    multiple of 4 (width) / 2 (height) - see 4.2. Pass `size=` only to force
    something else.
    """

    def __init__(self, widget: QWidget, path: str | Path, *,
                 size: tuple[int, int] | None = None,
                 fps: float = DEFAULT_FPS,
                 encoder: FrameEncoder | None = None) -> None: ...
    def start(self) -> None: ...          # latches the size, starts timer + pipe
    def grab_now(self) -> None: ...       # store one frame immediately (4.5)
    def set_capture_fps(self, fps: float, *, label: str = "") -> None: ...   # see 4.5
    def stop(self) -> MovieResult: ...    # closes the pipe, returns path/frames/seconds
    def __enter__(self) -> MovieRecorder: ...
    def __exit__(self, *exc) -> None: ... # stop(); never raises over an exception

# read-only, for tests and for a run's log line:
#   running, size (latched geometry, None before start), capture_fps, interval_ms,
#   frames, dropped, ticks

@dataclass(frozen=True)
class MovieSegment:
    """One stretch of the movie captured at a single capture rate (4.5)."""
    label: str
    capture_fps: float
    frames: int          # frames stored while this segment was active
    real_seconds: float  # wall-clock it took
    output_seconds: float  # its length in the finished movie (frames / output fps)

@dataclass(frozen=True)
class MovieResult:
    path: Path
    frames: int
    dropped: int      # samples the cadence called for but never stored (see 4.2)
    seconds: float    # the movie's length (frames / output fps), not wall clock
    size: tuple[int, int]
    capture_fps: float                     # the output fps (constant, §4.5)
    segments: tuple[MovieSegment, ...]     # what was captured at which rate

class FrameEncoder(Protocol):
    def write(self, frame: bytes) -> None: ...
    def close(self) -> None: ...          # flushes and waits for the muxer

def find_ffmpeg() -> str | None:
    """$STARBASH_FFMPEG, else imageio-ffmpeg's bundled binary, else which(ffmpeg)."""

@dataclass(frozen=True)
class MovieInfo:
    width: int
    height: int
    frames: int
    duration: float
    codec: str

def probe_movie(path: str | Path) -> MovieInfo:
    """Ask **ffmpeg itself** what is actually in the file (used by tests, §9)."""
```

`QtMovieFile` is the only ffmpeg-aware class; `FrameEncoder` is what makes the recorder
testable with no ffmpeg on the machine at all:

```python
class QtMovieFile:
    """Pipes raw RGB24 frames into an ffmpeg subprocess."""
    def __init__(self, path: str | Path, size: tuple[int, int], fps: int, *,
                 ffmpeg: str) -> None: ...
```

### 4.2 How a frame is produced (all of this is measured, not guessed)

| Step | Code | Measured here |
|---|---|---|
| size | `widget.size()` → `(width - width % 4, height - height % 2)` | **the window's own default size** — the script never resizes it. The rounding is not cosmetic: `Format_RGB888` pads every row to a 4-byte boundary, so an unaligned width makes `image.sizeInBytes()` larger than `w*h*3` (the 1920×1050 case below); and libx264's `yuv420p` refuses an odd height. Rounding down crops at most 3 px of window edge |
| grab | `widget.grab().toImage()` | `grab()` returns a **`QPixmap`**, so `.toImage()` first — a `QPixmap` has no `convertToFormat` |
| normalise | `.scaled(w, h).convertToFormat(QImage.Format.Format_RGB888)` | mandatory: the offscreen platform reports `devicePixelRatio = 1.25`, so a 1920×1200 widget grabs as **2400×1500**, and reading the bytes out of that image gives 6 048 000 (1920×1050×3) — a mismatch that makes ffmpeg emit garbage frames (`Invalid buffer size, packet size 6048000 < expected frame_size 6912000`). Scaling to the latched `(w, h)` also absorbs the 1.25 factor, so the movie is at *logical* window resolution on every platform |
| verify | `len(frame) == w*h*3` | after `scaled()` on an aligned size the bytes are exactly `w*h*3` (6 912 000 at 1920×1200); a frame that fails the check is **dropped**, never piped short |
| pipe | `subprocess.Popen([...,"-f","rawvideo","-pix_fmt","rgb24","-s","WxH","-framerate",fps,"-i","-", ...])` | 30 frames in → `nb_frames=30`, `duration=1.0`, `width=1920`, `height=1200` at a forced 1920×1200 (verified with the system ffmpeg *and* with imageio-ffmpeg's bundled v7.0.2, §4.3) |

The size is latched **once, in `start()`** — a window that is later resized (a splitter
drag, a maximise) keeps producing frames of the latched geometry, scaled to fit, because a
rawvideo pipe's `-s` cannot change mid-stream. So recording is immune to the window moving
under it; §9 asserts exactly that.

Cost: **3 ms per grab+convert at 1920×1200** (measured, offscreen, 30 iterations), i.e.
comfortably inside the 33 ms budget at 30 fps. It scales with area, so the app's own window
is cheaper still: recording the real 1280×820 `MainWindow` at 30 fps stored **31 frames in
1.01 s with 0 dropped**. The timer uses `Qt.TimerType.PreciseTimer`, and a sample the
cadence called for but did not get is **counted** (`MovieResult.dropped`) rather than queued
— a live screen recording is a sample of reality, not a queue.

That count is derived from the clock, not from re-entrancy, because the GUI thread is where
frames are made: a slow grab or a slow encoder *blocks* the timer, so Qt cannot even deliver
the ticks and there is nothing to count per-tick. `_capture` therefore compares the gap
between two stored frames against the current interval, carries the fraction forward, and
adds the whole missed samples to `dropped` — so `frames + dropped ≈ elapsed / interval`
always, however coarse a stretch the recorder had to be. (Verified: a spy encoder that takes
0.15 s per frame stores ~21 frames over 3.2 s at a 30 fps *cadence* and reports ~71 dropped,
never writing a frame twice to catch up.)

Encoder command (exactly the one verified end to end):

```
ffmpeg -y -loglevel error -f rawvideo -pix_fmt rgb24 -s WxH -framerate FPS -i - -an
       -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p
       -movflags +faststart -f mp4 OUT
```

`-f mp4` is passed explicitly (not left to the extension) because the requested output
path is `/tmp/gui.mp4` — an extension ffmpeg cannot map to a muxer. `-pix_fmt yuv420p`
keeps the file playable everywhere (browsers, QuickTime); `+faststart` makes it
streamable.

### 4.3 Why a pipe, and not `QMediaRecorder` / PyAV

- **PyAV** (`av`, a 36 MB wheel) would give us ffmpeg's libraries without a subprocess,
  but it is a new heavyweight binary dependency and the frame still has to be handed to it
  as a numpy/planar structure — the raw-bytes pipe is simpler and we already have the
  bytes.
- **Qt Multimedia's `QMediaRecorder`** cannot record a widget at all (it records screens
  and cameras), behaves differently per platform, and would tie the frame rate to the
  compositor rather than to our timer.
- **`imageio-ffmpeg`** is the one we take, and it is a **decided dependency** (not a
  fallback we hope for): `poetry add --group dev imageio-ffmpeg`. It is a thin pure-python
  wrapper (~29 MB wheel) that ships **one static ffmpeg binary** — on this platform
  `binaries/ffmpeg-linux-x86_64-v7.0.2` (verified by downloading the wheel; 80 MB
  uncompressed) — exposed as `imageio_ffmpeg.get_ffmpeg_exe()` (the public API also has
  `get_ffmpeg_version()`; both confirmed from the wheel's `__init__.py`). Why it is worth
  it:
  - **The bundled binary has been exercised here, end to end:** extracted from the wheel it
    encodes H.264 mp4 and answers the §4.6 probe exactly like the host's v9.0.1 — so the
    recorder genuinely does not need a system ffmpeg.
  - **The test no longer depends on the host.** `poetry install --with dev` is the whole
    requirement: no `apt install ffmpeg`, no CI package list, no "works on my box because
    linuxbrew happens to have v9.0.1". Every machine and CI runner encodes with the *same*
    ffmpeg build, so a movie that differs between two machines is a real difference.
  - **It is dev-only.** Runtime Starbash does not encode video, so it must not land in the
    main dependency group — the CLI's install stays lean (PySide6 is already the one big
    exception, and this is far smaller than that).
  - **Wheels exist for everywhere we run:** manylinux x86_64/aarch64, macOS 10.9+/arm64,
    win32/win_amd64 (checked against PyPI's file list for 0.6.0, which declares
    `requires-python >=3.9`).
  - **`find_ffmpeg()` prefers it, and only then the host:**

    ```python
    def find_ffmpeg() -> str | None:
        """$STARBASH_FFMPEG, else imageio-ffmpeg's bundled binary, else which(ffmpeg)."""
        if explicit := os.environ.get("STARBASH_FFMPEG"):
            # A bad override means "skip", never a silent fall-through to some other
            # binary: if you named one, you meant it.
            return explicit if Path(explicit).exists() else None
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()   # bundled, reproducible, the norm
        except Exception:
            pass
        return shutil.which("ffmpeg")                # last resort; version may vary
    ```

    `$STARBASH_FFMPEG` stays first so a developer can point at their own build while
    debugging a codec issue; the bundled binary is the path a normal run takes. The test
    still **skips** (with the reason printed) if none of the three resolves.
  - **It bundles no `ffprobe`** — the wheel's only executable is `ffmpeg` (verified). So
    `probe_movie()` must not shell out to ffprobe; §4.6 has the two `ffmpeg` invocations
    that report duration/size/fps and the frame count.

### 4.4 Lifetime rules (this repo's favourite bug class)

- The recorder owns a `QTimer` **and** a subprocess. `stop()` is idempotent, always runs
  on the GUI thread, and **closes stdin then waits** with a bounded timeout, escalating to
  `kill()` if ffmpeg does not exit — a leaked encoder would otherwise hang teardown.
- The filmed widget is also the recorder's Qt parent, so Qt destroys the recorder with
  the window; `__exit__` stops it explicitly, and `stop()` is safe to call twice.
- Nothing here is asynchronous in the `run_async` sense: no worker thread, no callback
  into a widget that may already be gone. Keep it that way — the whole point of
  `doc/plans/qt-object-lifetimes.md` is that late callbacks into dead widgets are how this
  suite crashes.

### 4.5 Variable capture rate — the "processing" fast-forward

A long run must not become a long movie. The recorder therefore samples at **two** rates:
~30 fps while the script is clicking through UI (so a 1 s pause reads as a 1 s pause), and a
much slower rate while the pipeline is working. Both write into **one constant-framerate
stream**, because an mp4 video track has exactly one frame rate — you cannot change a
stream's fps mid-file.

That is all the trick is: `set_capture_fps(1.0)` means *one stored frame per second*, and at
a stored 30 fps those samples play in 1/30 s each. Playback speed for a segment is
`output_fps / capture_fps`, so at `PROCESSING_CAPTURE_FPS = 1.0` a 10-minute pipeline
becomes **20 s of movie** — the requested ~30× speed-up, achieved by writing *fewer* frames
rather than by duplicating any.

```python
class MovieRecorder(QObject):
    ...
    def set_capture_fps(self, fps: float, *, label: str = "") -> None:
        """Change the sampling cadence. `fps` is *capture*, not output: the stream's
        framerate (and so the movie's timeline) never changes; a lower rate makes this
        stretch of real time play back faster (output_fps / fps). Grabs one frame
        immediately, then one per interval. Closes the current segment and opens a new
        one, so `MovieResult.segments` records what happened and when."""
```

Design points, all of them consequences of "the file has one frame rate":

- **The timer interval is the only thing that changes.** `start()` sets a
  `Qt.TimerType.PreciseTimer` to `1000 / capture_fps` ms (`33` ms at 30 fps, `1000` ms at
  1 fps); `set_capture_fps` calls `setInterval()` **and `start()`** (restarting the
  countdown, so the first frame of the new rate is one interval later, not immediately
  "caught up") and does **not** touch the encoder, whose `-framerate` stays the output fps.
  No frame is ever written twice.
- **A rate change also grabs one frame immediately.** Otherwise the slowed section's first
  1000 ms is uncaptured and the transition (the moment the pipeline starts) can fall between
  samples. One immediate grab makes the changeover visible and makes the arithmetic exact:
  *measured* on this container, 30 fps for 1.00 s stored **30** frames, then
  `set_capture_fps(1.0)` + 3.00 s stored exactly **3** (1 Hz, 30.0× speed-up), with **0
  dropped** and every frame exactly 6 912 000 bytes (i.e. `set_capture_fps` = "one frame
  now, then one per interval").
- **A tick still writes exactly one frame.** Frames carry no timestamps in a rawvideo pipe,
  so the fast-forward exists only in *our* bookkeeping: the file is honest video at 30 fps
  whose content is decimated, and the movie's total duration is
  `frames / output_fps`. `MovieResult.segments` (capture fps, frames, real seconds, output
  seconds per stretch, §4.1) is what lets the test assert the speed-up rather than assume it
  — sum of segments = `frames`, and the processing segment's `output_seconds` ≈ its
  `real_seconds / 30`. Those three measurements are the shape the unit test takes: a spy
  `FrameEncoder` and a real `QTimer`, no ffmpeg.
- **It is a variable *interval*, not a variable *fps*.** The 1 fps stretch is a plain 1 Hz
  sample of the screen; nothing accumulates a backlog, so the dropped-tick rule of §4.2
  still means exactly what it meant at 30 fps (a tick whose grab did not finish inside a
  1000 ms interval is a genuine drop). Do not "catch up" by writing several frames after a
  slow grab.
- **The event loop must keep running** for any of this to tick — which is what forces §5.3's
  pump loop rather than `Event.wait()`; at 1 fps a blocked loop loses a *second* per frame,
  not a 33 ms one.
- **A label, not guessing.** `set_capture_fps(1.0, label="processing")` at step 10 and
  `set_capture_fps(30.0, label="done")` after the run is what makes the movie's sections
  self-describing in the test output and in the log line the test prints.
- **A rate change resets the drop accounting.** Changing the cadence deliberately skips
  samples, so the missed-sample clock (§4.2) starts fresh with each segment - otherwise
  switching back from 1 fps to 30 fps would report ~30 "dropped" frames per second of
  fast-forward, which is exactly the thing we asked for, not a failure. (Both directions are
  unit-tested: with the reset removed, the switch reports 8 phantom drops.)
- **Bounded by design.** The value lives in the script as one constant
  (`PROCESSING_CAPTURE_FPS = 1.0`, §5.1) so a smoother movie (2 fps) or a very long run
  (0.5 fps) is a one-line change — the recorder has no opinion about what "processing" is.

### 4.6 Probing the result without `ffprobe`

`imageio-ffmpeg` ships **only** `ffmpeg` (§4.3), so `probe_movie()` uses the binary it
already has — and it turns out one invocation is enough (measured with the bundled v7.0.2):

```bash
ffmpeg -i OUT -f null -      2>&1      # decodes the stream, reports everything
#   Duration: 00:00:01.17, start: 0.000000, bitrate: 136 kb/s
#   Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive),
#     1280x820, 127 kb/s, 30 fps, 30 tbr, 15360 tbn (default)
#   frame=   35 fps=0.0 q=-0.0 Lsize=N/A time=00:00:01.16 bitrate=N/A speed=48.9x
```

(`-map 0:v:0 -c copy -f null -` does **not** work for the frame count: a *copied* stream is
reported in bytes — `video:15KiB` — with no `frame=` line. Decoding is the only way, which is
fine at test scale.)

`parse_ffmpeg_report()` turns that text into `MovieInfo` (split out from `probe_movie` so it
can be unit-tested against a canned report) and raises with ffmpeg's own stderr attached when
a stream is unreadable, so a zero-byte or garbage-muxed file fails the test with the encoder's
complaint rather than an empty `MovieInfo`. Two parsing traps, both now regression-tested:

- **Hex ids look like geometry.** `avc1 / 0x31637661` matches a naive `(\d+)x(\d+)`, so hex
  tokens are stripped first.
- **…and the stripping ate real geometry.** `0x820` is a suffix of **`1280x820`**, so the
  first version of this silently failed on every width ending in 0 — the real-window run
  caught it. The pattern needs a lookbehind: `(?<![0-9a-fA-F])0x[0-9a-fA-F]+`.

Regexes: `Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)`, `(\d+)x(\d+)` (on the hex-stripped
`Video:` line), `Video: (\w+)`, `frame=\s*(\d+)` (last match). Because the probe talks to the
*same* ffmpeg the encoder used, it also works when the bundled binary is the only one on the
machine.

## 5. The script (`test_first_run.py`)

### 5.1 Driver: a small helper, not a framework

Widgets are driven with `QTest.mouseClick` (a real press/release, i.e. the signals a user
generates) and typed into with `QTest.keyClicks`; between actions the script pumps the
event loop for a fixed pause. Three helpers do all of it:

```python
PAUSE_SECONDS = 1.0  # "pause 1s after each gui action so video can see the flow"

# Sampling cadences (recorder "capture fps", never the movie's playback fps — §4.5).
CAPTURE_FPS = 30.0           # UI sections: what you see is real time
PROCESSING_CAPTURE_FPS = 1.0 # pipeline sections: 1 fps ⇒ played back 30× fast

MOVIE_PATH = os.environ.get("STARBASH_GUI_MOVIE", "/tmp/gui.mp4")
TEST_DATA = os.environ.get("GUI_MOVIE_TEST_DATA", "/test-data")  # §3.1 — trim to a subset

def pump(app: QApplication, seconds: float) -> None:
    """Let the GUI breathe (and the recorder keep ticking) for `seconds`."""

def pump_until(app: QApplication, stop: Callable[[], bool], timeout: float,
               *, tick: float = 0.1) -> bool:
    """Spin the event loop until `stop()` (or `timeout`). True if it stopped."""

def click(widget: QWidget, app: QApplication, *, pause: float = PAUSE_SECONDS) -> None:
    """Send a real click, then let the video see the result."""
```

`PAUSE_SECONDS` and the two cadences are module constants so a future
`STARBASH_GUI_MOVIE_FAST=1` can shrink them without touching the script's flow — and
`PROCESSING_CAPTURE_FPS` is **the** knob for the length of the movie's processing section
(1.0 now, as asked; 2.0 gives a smoother but twice-as-long fast-forward).


### 5.2 The journey, step by step

| # | Step | How |
|---|---|---|
| 0 | virgin dirs | `paths.set_test_directories(tmp_config, tmp_data, tmp_cache, tmp_documents, tmp_state)` — the same override `tests/conftest.py`'s fixture uses, so the app can never read the developer's real config, database or cache |
| 1 | build the app | `QApplication` (already exists under pytest-qt), a real `Starbash` context, then `MainWindow(sb)`; `show()`, then pump ~0.5 s so layout and the window's default size (`1280×820`) settle — **no resize**: the recorder films the window as it is |
| 2 | start recording | `MovieRecorder(window, MOVIE_PATH, fps=CAPTURE_FPS).start()` — no `size=`, so the frames are the window's own geometry (§4.2), latched now |
| 3 | the wizard appears | `window.run_setup_wizard()` is **modal** (`run_setup_dialog` calls `wizard.exec()`), so it blocks the calling thread — the script drives it from within that call. §10.1 has the two options and the proposed one |
| 4 | page 1 → 2 | click the wizard's own *Next* (`SetupWizard.button(QWizard.NextButton)`) |
| 5 | fill in "you" | `QTest.keyClicks` into `YouPage`'s name/email fields, tick **both** tracking boxes ("agree to all tracking"), then *Next* |
| 6 | output folders | accept the default answer (the page's *Next* is only enabled once the folders are answered), then *Next* |
| 7 | raw-image folder | monkeypatch `QFileDialog.getExistingDirectory` in `starbash.ui.qt.pages.wizard` to return `TEST_DATA` (the `_FakeFileDialog` trick `tests/unit/test_setup_wizard.py` already uses), click the page's *Choose folder…*, then *Next* — so the folder is added **for real** through `sb.add_local_repo()` (which then indexes it: 122 frames across four datasets by default, §3.1) |
| 8 | tools | click *Next* (this container has Siril, GraXpert and StarNet, so no required tool is missing; `SetupWizard.nextId()` skips the page entirely when nothing is missing) |
| 9 | done page | wait for **Process all my targets** to become enabled (only `DonePage.refresh()` arms it, once the checklist is ticked), then click it |
| 10 | processing | the wizard is accepted, so `_apply_setup_action(ACTION_PROCESS)` reloads the context, clears the selection (`sb select any`) and calls `ProcessingPage.start_run()`; **first** slow the recorder to the processing cadence (`recorder.set_capture_fps(PROCESSING_CAPTURE_FPS, label="processing")`), then pump until the run finishes (§5.3) — so the long stretch is fast-forwarded in the movie |
| 11 | stop | `recorder.set_capture_fps(CAPTURE_FPS, label="done")`, pump ~2 s so it ends at real speed, then `recorder.stop()`; assert the file exists and `probe_movie()` reports a plausible frame count, size and duration (§9) |

### 5.3 Waiting for the run (no sleeps-by-guesswork — and no blocking waits)

The script waits on the **event bus**, which is also what fills the tree it is filming, so
there is no polling of a private widget. But it must wait **without blocking the Qt event
loop**: a `threading.Event.wait()` on the GUI thread would freeze the very thing we are
recording — the tree would stop repainting, `run_async` callbacks would not arrive, and at
the processing cadence the recorder would store *no* frames at all (§4.5). So the wait is a
pump loop:

```python
finished = threading.Event()

def _on_event(event: events.Event) -> None:
    if event.kind == events.EVENT_RUN_FINISHED:
        finished.set()          # set from the worker thread; read on the GUI thread

unsubscribe = events.subscribe(_on_event)
recorder.set_capture_fps(PROCESSING_CAPTURE_FPS, label="processing")
try:
    assert pump_until(app, finished.is_set, RUN_TIMEOUT_SECONDS), \
        "processing never finished"
finally:
    unsubscribe()
```

`events.EVENT_RUN_FINISHED` is the last event of a target's run — and the Processing page
renders exactly that — while `RUN_TIMEOUT_SECONDS` is a generous module constant, so a
stuck run *fails* the test instead of hanging pytest forever. (A `threading.Event` is still
the right primitive: the publisher is a worker thread, and only its `.is_set()` is read
from the GUI thread.) Afterwards the script calls
`recorder.set_capture_fps(CAPTURE_FPS, label="done")` and pumps ~2 s more, so the video ends
on a settled tree, at real speed, rather than mid-paint.

`/test-data` holds four real datasets, ~4.5 GB and 122 FITS files in total (§3.1). The
script points the picker at `TEST_DATA` — `/test-data` by default, `$GUI_MOVIE_TEST_DATA`
to override — so trimming the run (e.g. `/test-data/asiair`, 27 frames) is an environment
variable rather than a code change; §10.3 records the completeness-vs-runtime trade-off, and
note that this trade-off is now much cheaper than it was for the *movie*: at 1 fps the
movie's processing section is 30× smaller than the run, so a fuller dataset no longer means a
longer video — only a longer test.


## 6. Source changes: object names as the script's handles

A script that presses widgets must find them by something other than row order, and
`objectName` is the Qt-native answer (and what was asked for). The change is small,
additive, and **cannot affect styling**: the theme styles only the ids `Primary`,
`Danger`, `PageTitle`, `PageSubtitle`, `NavRail` and `CentralArea` — every id below is
new, and setting an object name does not disturb QSS applied by type selector.

| Widget | objectName | File |
|---|---|---|
| the wizard itself | `SetupWizard` | `pages/wizard.py` |
| name field / email field | `wizardName`, `wizardEmail` | `pages/wizard.py` (`YouPage`) |
| the two tracking checkboxes | `wizardAnalytics`, `wizardIncludeEmail` | `pages/wizard.py` (`YouPage`) |
| raw-image *Choose folder…* | `wizardChooseFolder` | `pages/wizard.py` (`ImagesPage`) |
| the two closing actions | `wizardProcessAllTargets`, `wizardPickTarget` | `pages/wizard.py` (`SetupWizard`) |
| the run tree / the caption | `processingTree`, `processingCaption` | `pages/processing.py` |
| main window (rail/stack already named) | `MainWindow` | `main_window.py` |

Three rules keep this honest:

- **Set names, never change behaviour.** No layout, no text, no enabled-state change. If a
  widget the script needs has no stable handle, give it a name — never reorder or re-parent
  anything to make the script easier.
- **A widget that already carries a theme id cannot take a second name.** `objectName` is a
  single string: `ImagesPage._choose` is `#Primary` (styling) and so is
  `ProcessingPage._run`, so neither can become `wizardChooseFolder` / `processingRun`. The
  script reaches those two through the component instead — a small public accessor
  (`ImagesPage.choose_button`, `ProcessingPage.run_button`) rather than a private attribute
  touched from a test. A `variant` dynamic property plus a QSS attribute selector would fix
  the general case, but that is a theme refactor and stays out of scope (see §11).
- Every named handle gets a **unit test assertion** — an `objectName` that silently
  disappears is a broken script waiting to happen. One
  `test_*_page_sets_object_names`-style check per touched page, in the style of
  `tests/unit/test_setup_wizard.py`.

## 7. Test-type plumbing

- `tests/gui_integration/conftest.py`:
  - `pytestmark = pytest.mark.gui_integration` (applied by the module, declared in
    `pyproject.toml`);
  - a `movie_output` fixture returning `$STARBASH_GUI_MOVIE` or `/tmp/gui.mp4`;
  - `skipif(not find_ffmpeg())` and `skipif(not Path(TEST_DATA).is_dir())` (TEST_DATA =
    `$GUI_MOVIE_TEST_DATA` or `/test-data`, §3.1), each with
    the reason spelled out — exactly how `tests/integration/` skips without `/test-data`;
  - the **virgin directories** fixture: `tmp_path_factory`-based `set_test_directories(...)`
    plus restore, mirroring `setup_test_environment` in `tests/conftest.py`.
- Keep the movie **out of the repository**: it lands in `/tmp` (the explicit requirement),
  never in a persisted artefact directory. If `/tmp` is not writable the test **skips**
  with a clear message rather than failing.
- `justfile`: an optional `just gui-movie` = `pytest -m gui-integration -k first_run -n 0`
  (plus a `gui-movie-fast` variant setting `GUI_MOVIE_TEST_DATA=/test-data/asiair` and a
  smaller pause, for iterating on the script), so the movie is one command away (mirroring
  the existing `movies:` recipe for CLI demos).

## 8. Implementation phases

1. **Recorder alone** — `qtmovie.py` + `tests/unit/test_qtmovie.py` (§9). No app, no
   wizard: a `QLabel` gets recorded, and its own output is probed to prove it is real video.
   **Done 2026-09-16** (28 tests, `just lint` clean), with the recorder re-verified against
   the real `MainWindow` outside pytest — 1280×820 in, 1.01 s of UI at 30 fps with no drops,
   then 3.01 s of "processing" at 1 fps for 0.13 s of movie, probed back as h264/35 frames.
   Two follow-ups the check turned up: the stage composites the wizard as an **overlay**
   (a modal dialog is its own top-level window and can never appear in a grab of
   `MainWindow`), which supersedes the re-parenting idea; and `MovieStage.window` had to be
   renamed `filmed_window` (`window` is a `QWidget` method, which basedpyright rejects as an
   incompatible override).
2. **Names** — the `objectName` table in §6, plus the unit assertions.
   **Done 2026-09-16** (`tests/unit/test_setup_wizard.py`, `test_gui.py`; `just lint` clean).
3. **The script** — `test_first_run.py`, run by hand, watch `/tmp/gui.mp4`.
   **Done 2026-09-16.** `driver.py` (pump/click/type/`go_to`/`WizardDriver`) plus the journey
   below. Two things only running it could teach: the closing caption on success is
   `"<n> task(s) run, <n> succeeded, <n> up-to-date, <n> failed."` — so a
   `"fail" not in caption` check fails on the summary that *proves* the run worked (a
   failed run is `"Failed: <why>"`, `ProcessingPage._on_failed`); and a test that raises
   mid-run must still `stop()` the recorder in a `finally`, because the movie is only muxed
   at `stop()` — otherwise the failing run leaves an unplayable file, i.e. the one artefact
   you wanted. Also: `tests/gui_integration/conftest.py`'s dataset helper is
   `dataset_root()`, not `test_data_root()` — importing a `test_`-prefixed function into a
   test module makes pytest *collect it as a test*.
4. **Wire-up** — the marker **and** the default deselect in `pyproject.toml` (§7),
   `just test-integration-gui`, and a CI note. Do **not** add it to the CI matrix yet: it
   wants `/test-data` *and* several minutes. **Done 2026-09-16** — the marker is
   `gui_integration` (underscore, so it is usable as `pytest.mark.gui_integration`), and the
   recipe records the movie, then opens it (`xdg-open`, else `ffplay`). (The
   `imageio-ffmpeg` dev dependency landed early, in phase 1, because the recorder's tests use
   it.)
5. **Driver tests** — `tests/unit/test_gui_integration_driver.py` (14 tests, `gui`-marked,
   no ffmpeg and no `/test-data`): `pump_until`'s live-loop *and* its deadline, a real click
   toggling a real checkbox, `go_to` pressing the real *Next* and being held by
   `YouPage` until a username arrives, and the `WizardDriver` contracts — step order, the
   `False`/retry poll, `STEP_TIMEOUT_SECONDS` closing the wizard and raising `TimeoutError`
   by step name, a raising step surfacing as *its own* error, un-run steps named by
   `result()`, and `install()` patching the name `run_setup_dialog` actually reads (and
   monkeypatch putting it back). **Done 2026-09-16.**
6. **Docs** — `tests/gui_integration/README.md`: what the type is, what it needs, how to
   watch the movie, and the rule that these tests are never the only place a behaviour is
   asserted. **Done 2026-09-16.**


## 9. Testing strategy

- **Unit (`tests/unit/test_qtmovie.py`, marked `gui`, no ffmpeg required):** inject a
  recording `FrameEncoder` through the `encoder=` parameter and assert real state, not
  mock calls:
  - `start()` writes one frame immediately, then one per tick: N ticks after `start()` → N+1
    frames, each `len(frame) == w*h*3` (the raw-bytes invariant that broke the first
    attempt);
  - **size defaults to the widget's own geometry (§4.2):** no `size=` means
    `result.size == (widget.width() - w % 4, widget.height() - h % 2)` and the window was
    never resized; a window forced to an unaligned `101×49` yields `100×48` frames of
    `100*48*3` bytes (the stride/codec rounding, asserted on the bytes, not on the intent);
  - `stop()` → `close()` called exactly once, the encoder ended, `MovieResult` fields
    correct and the path echoed back; `stop()` again returns the same result;
  - `start()` is idempotent; `stop()` without `start()` is a harmless no-op (no encoder is
    ever built, `frames == 0`);
  - a widget resized mid-recording still yields frames of the **latched** size (the
    `devicePixelRatio` and mid-stream-`-s` traps);
  - a deliberately slow encoder makes the recorder **report** the samples it could not take
    (`dropped > 0`, `frames + dropped ≈ elapsed / interval`) instead of queueing them to
    write later - and it never writes a burst to catch up (one frame per delivered tick);
  - **cadence (§4.5):** `set_capture_fps(5.0)` moves the `QTimer` to a 200 ms interval and
    grabs one frame immediately; subsequent ticks write exactly one frame each (no repeats,
    no catch-up); switching back restores 33 ms; **changing the rate reports no drops** (the
    decimation is the point of the knob, not a failure - asserted, and verified to fail
    without the reset); `MovieResult.segments` has one entry per
    rate with `sum(s.frames) == result.frames` and `s.output_seconds == s.frames / fps`, and a
    segment's `output_seconds` is far below its `real_seconds` (that *is* the speed-up
    assertion); `set_capture_fps` before `start()` just changes the initial interval, and
    calling it twice with the same value does not open an empty segment.
  - **live ffmpeg (skipped when `find_ffmpeg()` is None):** a small widget (100×48, which
    keeps the "`0x48`" parse trap covered live) recorded through a real `QtMovieFile`, then
    `probe_movie()` must report the widget's own geometry, `codec == "h264"` and the same
    frame count — the whole pipe in well under a second;
  - **the ffmpeg report parser**, against a canned real report (the 1280×820 one in §4.6), so
    the hex/geometry traps above fail a fast test rather than only a slow one;
  - `find_ffmpeg()`'s contract: a `$STARBASH_FFMPEG` that does not exist means *no* binary
    (skip), never a silent fall-through to some other ffmpeg.
- **End-to-end:** the script itself, plus an ffmpeg probe assertion — **not** "the file
  exists". `probe_movie()` asserts the container's frame count, `width`, `height` and
  `duration` as §4.2 does, so a recorder that silently writes zero-byte frames fails
  loudly. `probe_movie` lives in `qtmovie.py` so the script and the unit test share it. The
  script's own invariant: `probe_movie().duration ≈ result.frames / CAPTURE_FPS` and the
  "processing" segment is a small fraction of the movie's seconds compared with its share of
  the run's wall clock.
- **Never the only coverage:** the wizard flow itself stays unit-tested
  (`tests/unit/test_setup_wizard.py`). The movie test adds *integration* confidence and a
  reviewable artefact, not new assertions about wizard logic.
- Gate: `just lint`, then `poetry run pytest -q`. The new `gui`-marked unit test runs in
  the default suite; the `gui-integration` script is **deselected by default** (§7) and runs
  via `just gui-movie` / `pytest -m gui-integration -n 0`, skipping cleanly on a machine
  without ffmpeg or `/test-data`.

## 10. Risks and open questions

1. **A modal wizard blocks the script** (§5.2 step 3). Options:
   (a) drive `SetupWizard` directly with `show()`, bypassing `run_setup_dialog` — linear and
   simple, but it does **not** exercise the very wiring the journey is about
   (`run_setup_dialog` → `_apply_setup_action(ACTION_PROCESS)` → `start_run()`);
   (b) keep `run_setup_dialog` (modal) and drive it from a `QTimer.singleShot` step-chain
   while `exec()` spins the loop — exercises the real path end to end, at the cost of nested
   callbacks; (c) make the wizard non-modal in production — **rejected**: that changes real
   behaviour for a test's convenience.
   *Proposed:* (b), with the step-chain wrapped in one `WizardDriver` helper so the nesting
   lives in a single place and (a) remains a one-line fallback. **Decided: (b)** — and it
   worked exactly as hoped: timers do fire inside ``exec()``, so the script drives the real
   modal wizard, presses the real *Next*/*Process all my targets* buttons, and the real
   ``_apply_setup_action(ACTION_PROCESS)`` → ``start_run()`` follows. Note the movie had to
   change to match: a modal dialog is a separate top-level window, so ``MovieStage`` *draws*
   the wizard over the window instead of re-parenting it (§8 phase 1).
2. **The run's wall-clock cost is unchanged; only the movie shrinks.** Decimating to 1 fps
   (§4.5) makes the *file* 30× shorter for the pipeline stretch, but the *run* test still
   takes as long as the pipeline does. So a slow dataset is a slow test no matter how the
   recording is configured — the cadence knob is about watchability, not speed. The
   `gui-integration` suite is therefore deselected by default (§7) and must run *somewhere*
   regularly (a nightly job) or it will rot.
3. **Which dataset, and how long the movie runs.** **Decided: `/test-data/asiair`** (one
   target, M13, ~16 frames) as the default, with `$GUI_MOVIE_TEST_DATA=/test-data` running the
   whole tree for anyone who wants the four-pipeline version. The reason is measurement, not
   taste: the full tree took the better part of half an hour, while the M13 chain — Siril
   stack/crop, GraXpert bg-extract, BlurXTerminator, NoiseXTerminator, StarNet starless +
   merge-stars, broadband — completed end to end in **274 s** of wall clock. Since §10.2
   means the *run* is the cost, that is the difference between a suite you can run before
   pushing and one you schedule. `RUN_TIMEOUT_SECONDS` is therefore **600 s** (~2× the
   measured run, so a slow box is not a flake), and the full tree needs it raised. At 1 fps
   the resulting movie no longer grows with the dataset, so this choice is purely about how
   much of the pipeline the test should honestly cover — and one target covers the whole
   pipeline.
4. **`/tmp/gui.mp4` is a fixed path**, so two concurrent runs (xdist, or two developers on
   one box) overwrite each other. Acceptable for now — it is the explicit requirement — and
   `$STARBASH_GUI_MOVIE` is the override; §7's `-n 0` reduces the risk.
5. **The offscreen platform is not a desktop.** Widgets are real and laid out, but fonts,
   window decorations and the compositor are not what a user sees. That is fine for
   *driving* the app (the point of the test); a pixel-accurate demo movie would need a real
   display (Xvfb or a desktop session), which is a different mode of the same recorder.
6. **The movie's resolution is the window's, so it is whatever the platform gives us**
   (`1280×820` for `MainWindow`'s default geometry here, `§5.2`). On a developer's desktop
   that is the real window; offscreen it is the same logical size, since §4.2 scales off the
   1.25 `devicePixelRatio`. A fixed 1920×1200 canvas was considered and dropped: it meant
   resizing the window the test is supposed to be filming, and a resize is exactly the kind
   of thing a recording of a *real* run should not need. Pass `size=` to the constructor
   only if a specific canvas is ever wanted.

## 11. Out of scope

- Recording the CLI (the existing `just movies` recipes already do that).
- Narration, titles, captions, cursor highlighting, window chrome — the recorder is a
  straight widget grab.
- Audio, 4K, non-30 fps *output*, and any codec other than H.264. (A varying **capture**
  rate is in scope — §4.5; a varying **playback** rate is not, and cannot be.)
- Replacing theme ids with a `variant` property + QSS attribute selector (the §6 rule is
  the workaround; that refactor is its own plan).
- A user-facing recording feature (`sb gui --record`); `qtmovie.py` is written so that it
  would be a thin adapter later.


## 12. Source changes summary

**New:** `tests/gui_integration/{__init__,conftest,qtmovie,driver}.py`,
`tests/gui_integration/test_first_run.py`, `tests/gui_integration/README.md`,
`tests/unit/test_qtmovie.py`, `tests/unit/test_gui_integration_driver.py`, and the
`just test-integration-gui` recipe.

**Touched:**

- `pyproject.toml` — the `gui_integration` marker, the `not gui_integration` deselect in
  `addopts` (§7), and `imageio-ffmpeg` added to the **dev** dependency group (the recorder's
  bundled ffmpeg, §4.3 — no system ffmpeg required).
- `pages/wizard.py`, `pages/processing.py` and `main_window.py` for the `objectName` handles
  and the two public button accessors, plus the unit assertions for those names in
  `tests/unit/test_setup_wizard.py` (and a small Processing-page name check beside the
  existing page tests).

No production behaviour changes.



