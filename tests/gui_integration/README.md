# `tests/gui_integration` — the scripted GUI movie

This suite drives the **real** `sb gui` app through a whole user journey and records it to an
mp4, so the result can be *watched* rather than inferred:

1. the setup wizard — as the real modal dialog, driven from inside its own `exec()`
   (`driver.WizardDriver`), typing a name, ticking the analytics boxes, and picking a
   raw-image folder through the real *Choose folder…* button;
2. the closing *Process all my targets* action, and the real
   `_apply_setup_action(ACTION_PROCESS)` → `run_button` flow it triggers;
3. the processing run itself — Siril, GraXpert, BlurXTerminator, NoiseXTerminator and
   StarNet — recorded at one frame per second, so the slow stretch plays back 30× fast.

## Running it

```bash
just test-integration-gui          # records /tmp/gui.mp4, then opens it
```

That is the whole entry point. It is **deselected by default** (`pyproject.toml`'s
`addopts` excludes `-m gui_integration`), because it wants real FITS frames *and* several
minutes, and because the movie must come from one process (`-n 0`). Equivalently:

```bash
poetry run pytest tests/gui_integration -m gui_integration -n 0 -v
```

The suite **skips** (with a printed reason, never a failure) when there is no ffmpeg, no
PySide6, or no dataset; and the test skips when a **required** tool (Siril) is missing,
since there is no run to film.

| variable | default | what it does |
|---|---|---|
| `STARBASH_GUI_MOVIE` | `/tmp/gui.mp4` | where the movie is written |
| `GUI_MOVIE_TEST_DATA` | `/test-data/asiair` | the tree the wizard's picker is pointed at (`/test-data` is every target and takes far longer) |
| `STARBASH_GUI_MOVIE_FAST` | unset | shrinks every scripted pause, for iterating on the script without re-watching a leisurely movie |
| `STARBASH_FFMPEG` | bundled `imageio-ffmpeg` | which ffmpeg to record (and probe) with |

## What it asserts

Not "the file exists": after the run the test probes the movie back through ffmpeg
(`qtmovie.probe_movie`) and checks its geometry, codec, frame count and duration against the
recorder's own report, plus the drop fraction and the time-lapse arithmetic; and it decodes a
spread of frames (`_sampled_frames`) to prove they *differ*, because a movie of one frozen
window satisfies every metadata check. The run's own assertions read resulting state too —
the config the wizard wrote (`user.name`), the caption the run finished on
(`"<n> task(s) run, <n> succeeded, <n> up-to-date, <n> failed."`), and the movie's bytes.

## The rule for this directory

**These tests are never the only place a behaviour is asserted.** A movie run is slow and
platform-dependent (offscreen means real widgets, but not a real compositor or font stack), so
it adds *integration* confidence and a reviewable artefact — it does not replace the
`gui`-marked unit tests that cover the same flows quickly.

Two consequences worth remembering when editing here:

- **Never block the GUI thread.** Every wait spins `QApplication.processEvents()` with a
  deadline (`driver.pump_until`); a `threading.Event.wait()` or a bare `time.sleep` would stop
  the app painting *and* stop the recorder's timer — i.e. no movie.
- **Steps must be idempotent.** A step that answers `False` is called again after the pause
  (that is how waiting works), so it must ask for the state it wants rather than
  "do the thing and report where it ended up" — a bare `wizard.next()` called twice
  overshoots its page.

Implementation notes, the recorder's API and the traps behind these rules are in
`doc/plans/gui-integration-video.md`. `qtmovie.py`'s own behaviour is unit-tested in
`tests/unit/test_qtmovie.py`, and `driver.py`'s in
`tests/unit/test_gui_integration_driver.py`.
