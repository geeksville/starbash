"""Fixtures for the ``gui-integration`` suite.

These tests drive the *real* GUI - ``MainWindow``, the setup wizard, a live processing run -
and film it, so they need Qt, an ffmpeg and ``/test-data`` to be worth anything, and they
take minutes rather than milliseconds.  Everything that can be skipped here is skipped with
the reason spelled out, exactly as ``tests/integration/`` does without ``/test-data``.

Nothing in this suite may become the *only* place a behaviour is asserted: the wizard flow
is unit-tested in ``tests/unit/test_setup_wizard.py``, so what these tests add is
integration confidence plus a movie a human can watch.  See
``doc/plans/gui-integration-video.md``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: Where the finished movie lands (``$STARBASH_GUI_MOVIE`` overrides).  Deliberately under
#: /tmp: a demo movie is not a build artefact and must never be committed.
DEFAULT_MOVIE_PATH = "/tmp/gui.mp4"

#: The raw-image tree the wizard's picker is pointed at.  One target (asiair's M13, ~16
#: frames) keeps the suite quick; ``$GUI_MOVIE_TEST_DATA=/test-data`` runs the whole tree,
#: which takes far longer and needs a bigger ``RUN_TIMEOUT_SECONDS``.
DEFAULT_TEST_DATA = "/test-data/asiair"


def movie_path() -> Path:
    """The movie's destination: ``$STARBASH_GUI_MOVIE``, else the /tmp default."""
    return Path(os.environ.get("STARBASH_GUI_MOVIE", DEFAULT_MOVIE_PATH))


def dataset_root() -> Path:
    """The dataset the run processes: ``$GUI_MOVIE_TEST_DATA``, else /test-data.

    Named without a ``test_`` prefix deliberately: this is a *helper*, and a test module
    that does ``from .conftest import dataset_root`` would have pytest collect it as a
    test of its own (a no-argument function called ``test_...``).
    """
    return Path(os.environ.get("GUI_MOVIE_TEST_DATA", DEFAULT_TEST_DATA))


def _skip_reason() -> str | None:
    """Why the suite cannot run on this machine, or ``None`` when it can.

    Imported lazily on purpose: ``qtmovie`` (and so PySide6) is pulled in only when this
    directory is actually collected, so a suite-wide ``-m "not gui_integration"`` run on a
    machine without Qt never trips over it.
    """
    try:
        from .qtmovie import find_ffmpeg
    except ImportError as error:  # Qt is not installed at all
        return f"the GUI needs PySide6: {error}"
    if find_ffmpeg() is None:
        return (
            "no ffmpeg to record with: the dev dependencies ship one (imageio-ffmpeg), so "
            "run `poetry install --with dev`, or point $STARBASH_FFMPEG at a binary"
        )
    if not dataset_root().is_dir():
        return f"no {dataset_root()} (or $GUI_MOVIE_TEST_DATA): the run needs real FITS frames"
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark this directory's tests, and skip them when their requirements are missing.

    The marker is applied here rather than per-module so a new script cannot forget it, and
    the skip reason is printed as one line rather than repeated per test.
    """
    reason = _skip_reason()
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).parent != here:
            continue
        item.add_marker(pytest.mark.gui_integration)
        if reason is not None:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def movie_output() -> Path:
    """Where to record, skipping (never failing) when it cannot be written.

    A stale file from an earlier run is removed, so "the movie exists" can only ever mean
    *this* run wrote it.
    """
    path = movie_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    except OSError as error:  # pragma: no cover - environment dependent
        pytest.skip(f"cannot write the movie to {path}: {error}")
    return path


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real ``Starbash`` context in isolated directories.

    It reuses the suite-wide ``setup_test_environment`` fixture rather than inventing a
    second isolation scheme, so the movie can never read (or write) the developer's real
    config, database or cache.
    """
    from starbash.app import Starbash

    with Starbash("test.gui-integration") as sb:
        yield sb


@pytest.fixture
def gui_app(qapp):
    """The process-wide app, themed, exactly as ``sb gui`` starts it.

    ``create_application`` completes the ``QApplication`` pytest-qt already made: it applies
    the stylesheet and icon, so the movie looks like the app rather than bare widgets.  It
    deliberately does *not* call ``run()``, which would also install the desktop entry.
    """
    from starbash.ui.qt.app import create_application

    return create_application([])


@pytest.fixture
def picked_folder(monkeypatch) -> Path:
    """Point the wizard's folder chooser at the dataset, and return that folder.

    A modal file dialog cannot be driven from a test, so this replaces ``QFileDialog`` **only
    in the wizard module** (the ``_FakeFileDialog`` trick ``tests/unit/test_setup_wizard.py``
    already uses).  Everything else stays real: the page's own *Choose folder…* button is
    clicked, the folder is checked for FITS files, and ``sb.add_local_repo()`` indexes it for
    real when the page is left - which is the whole point of filming this journey.
    """
    from starbash.ui.qt.pages import wizard as wizard_mod

    folder = dataset_root()

    class _Picker:
        """Returns the canned folder for either chooser the wizard uses."""

        def getExistingDirectory(self, *_args: object, **_kwargs: object) -> str:
            return str(folder)

    monkeypatch.setattr(wizard_mod, "QFileDialog", _Picker)
    return folder
