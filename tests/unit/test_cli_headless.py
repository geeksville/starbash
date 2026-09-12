"""The CLI must keep working with no display and no usable Qt.

PySide6 is a normal dependency, but only ``sb gui`` may ever load it.  These tests
lock that in: a plain command (``sb info``) must run on a headless machine such as
an SSH session, and the CLI must never import Qt at all.

They deliberately run in a **subprocess**:

* environment isolation — we can remove ``DISPLAY`` and make ``PySide6``
  unimportable, which an in-process test cannot do safely; and
* a fresh interpreter — asserting "Qt was not imported" in-process would be
  unreliable under ``pytest-xdist``, since whichever worker ran the GUI tests
  already has ``PySide6`` in ``sys.modules``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT_SECONDS = 240

#: Removed from the subprocess environment to model an SSH session with no display.
HEADLESS_ENV_KEYS = ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH")

#: Simulates a machine where Qt cannot be loaded at all (no/broken Qt libraries).
#: `sb info` and `sb --help` must both still work.
WITHOUT_QT_SCRIPT = '''
import sys


class _NoQtFinder:
    """Meta-path finder that makes PySide6 completely unimportable."""

    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ModuleNotFoundError(f"PySide6 is unreachable here: {name}")
        return None


sys.meta_path.insert(0, _NoQtFinder())

# Use the local recipes submodule so the run never touches the network.
from starbash import app as starbash_app

starbash_app.force_local_recipes = True

from typer.testing import CliRunner

from starbash.main import app as cli

runner = CliRunner()
info = runner.invoke(cli, ["info"])
help_result = runner.invoke(cli, ["--help"])

print("INFO_EXIT", info.exit_code)
print("INFO_STDOUT_LEN", len(info.stdout or ""))
print("HELP_EXIT", help_result.exit_code)

for label, result in (("info", info), ("help", help_result)):
    if result.exception is not None:
        import traceback

        print(f"--- {label} exception ---")
        traceback.print_exception(result.exception)

sys.exit(0 if info.exit_code == 0 and help_result.exit_code == 0 else 1)
'''

#: Proves the invariant behind the headless guarantee: the CLI never pulls in Qt.
NO_QT_IMPORT_SCRIPT = """
import sys

from starbash import app as starbash_app

starbash_app.force_local_recipes = True

from typer.testing import CliRunner

from starbash.main import app as cli

result = CliRunner().invoke(cli, ["info"])
print("INFO_EXIT", result.exit_code)

qt_modules = sorted(m for m in sys.modules if m == "PySide6" or m.startswith("PySide6."))
gui_modules = sorted(m for m in sys.modules if m.startswith("starbash.ui.qt"))
print("QT_MODULES", qt_modules)
print("GUI_MODULES", gui_modules)

sys.exit(0 if result.exit_code == 0 and not qt_modules and not gui_modules else 1)
"""


def _headless_env(tmp_path: Path) -> dict[str, str]:
    """Build an environment resembling a clean, display-less SSH session.

    Every user directory is redirected into ``tmp_path`` so the subprocess can never
    read or write the real user's config/database.
    """
    env = dict(os.environ)
    for key in HEADLESS_ENV_KEYS:
        env.pop(key, None)

    for variable, directory_name in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
        ("HOME", "home"),
    ):
        directory = tmp_path / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        env[variable] = str(directory)

    env["NO_COLOR"] = "1"
    return env


def _run_cli_script(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in a fresh interpreter with the headless, isolated environment."""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=_headless_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def test_sb_info_works_when_qt_is_unavailable(tmp_path):
    """`sb info` (and `--help`) succeed on a headless box where Qt cannot load."""
    result = _run_cli_script(WITHOUT_QT_SCRIPT, tmp_path)
    diagnostics = f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"

    assert result.returncode == 0, f"CLI failed without Qt.{diagnostics}"
    assert "INFO_EXIT 0" in result.stdout, f"`sb info` did not exit 0.{diagnostics}"
    assert "HELP_EXIT 0" in result.stdout, f"`sb --help` did not exit 0.{diagnostics}"
    # Non-empty output proves the command actually ran rather than short-circuiting.
    assert "INFO_STDOUT_LEN 0" not in result.stdout, f"`sb info` produced no output.{diagnostics}"


def test_cli_never_imports_qt(tmp_path):
    """A CLI command must not import PySide6 or the GUI package as a side effect."""
    result = _run_cli_script(NO_QT_IMPORT_SCRIPT, tmp_path)
    diagnostics = f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"

    assert result.returncode == 0, f"CLI failed.{diagnostics}"
    assert "QT_MODULES []" in result.stdout, f"CLI imported Qt.{diagnostics}"
    assert "GUI_MODULES []" in result.stdout, f"CLI imported the GUI package.{diagnostics}"
