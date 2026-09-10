"""A missing Qt *system* library must produce guidance, not an INTERNALERROR.

PySide6's wheel bundles Qt but not the OS libraries Qt links against (libEGL,
libGL, ...).  pytest-qt imports QtGui while pytest is still configuring, so on a
machine missing them the whole run aborted with an opaque INTERNALERROR before a
single test was collected - even tests that never touch the GUI.  ``tests/conftest.py``
now detects that and prints the fix; these tests drive it through a real pytest
subprocess with a stubbed PySide6 that fails exactly like the CI runner did.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The failure the CI runner produced: PySide6 present, its libEGL missing.
_MISSING_LIBEGL = (
    'raise ImportError("libEGL.so.1: cannot open shared object file: '
    'No such file or directory")\n'
)


def _run_pytest_with_broken_qt(
    tmp_path: Path, args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run pytest in a subprocess whose PySide6 fails to import."""
    stub = tmp_path / "PySide6"
    stub.mkdir()
    (stub / "__init__.py").write_text(_MISSING_LIBEGL, encoding="utf-8")

    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(tmp_path), **(env or {})},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_a_missing_system_library_reports_the_fix(tmp_path):
    """Regression: this used to abort the run with an unreadable INTERNALERROR.

    The advice is platform-specific: on Linux Qt links against OS packages that the
    wheel does not ship, while on macOS/Windows those libraries are bundled and the
    fix is a reinstall.
    """
    result = _run_pytest_with_broken_qt(
        tmp_path, ["tests/unit/test_selection.py", "-q", "-p", "no:cacheprovider"]
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    # pytest's real marker is ``INTERNALERROR>``; a usage error exits 4, and an
    # internal error exits 3.  (Our own message mentions INTERNALERROR by name,
    # so check for the prefixed marker rather than the bare word.)
    assert result.returncode != 3, "the opaque internal error is back"
    assert "INTERNALERROR>" not in output, "the opaque crash is back"
    # The cause is named...
    assert "libEGL.so.1" in output

    # ...along with the fix for *this* platform.
    if sys.platform.startswith("linux"):
        assert "apt-get" in output
        assert "libegl1" in output
    else:
        assert "poetry install --with dev" in output
        assert "apt-get" not in output


def test_non_gui_tests_still_run_when_qt_cannot_load(tmp_path):
    """The documented workaround really works: no Qt, no pytest-qt, no GUI tests."""
    result = _run_pytest_with_broken_qt(
        tmp_path,
        [
            "tests/unit/test_selection.py",
            "-q",
            "-p",
            "no:pytest-qt",
            "-p",
            "no:cacheprovider",
            "-m",
            "not slow and not integration and not gui",
        ],
        env={"STARBASH_SKIP_QT_LOAD_CHECK": "1"},
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "passed" in output
