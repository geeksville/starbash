"""Tests for the Linux desktop integration (``.desktop`` entry + icons).

No Qt is involved: :mod:`starbash.ui.qt.desktop` is deliberately Qt-free, so these
run in the default suite.

The installer is **Linux-only** by design - it writes an XDG ``.desktop`` entry plus
hicolor theme icons.  Elsewhere it deliberately does nothing, so there is no install
path to exercise and these tests are skipped rather than passing for the wrong
reason.  The skip itself is still covered:
:func:`test_skipped_on_non_linux_platforms` simulates the platform by patching
``sys.platform``, so it runs wherever this module runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from starbash.ui.qt import desktop

#: Keys a usable launcher entry must have.
REQUIRED_KEYS = ("Type", "Name", "Exec", "Icon", "Terminal", "Categories", "StartupWMClass")

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the .desktop/XDG integration is Linux-only",
)


@pytest.fixture
def fake_executable(monkeypatch, tmp_path):
    """Point executable resolution at a real file so ``Exec=`` can be asserted."""
    exe = tmp_path / "bin" / "sb"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(desktop, "_resolve_executable", lambda: str(exe))
    return exe


def _base(setup_test_environment) -> Path:
    """The XDG data base the installer writes into (the temp test root)."""
    return Path(setup_test_environment["tmp_path"])


def test_installs_desktop_entry_and_themed_icons(setup_test_environment, fake_executable):
    """A full install writes a valid entry plus icons in the hicolor theme."""
    result = desktop.install_desktop_entry()
    assert result is not None
    assert result.changed is True
    assert result.executable == str(fake_executable)
    assert (
        result.desktop_file == _base(setup_test_environment) / "applications" / "starbash.desktop"
    )

    content = result.desktop_file.read_text(encoding="utf-8")
    for key in REQUIRED_KEYS:
        assert f"{key}=" in content, f"missing {key}= in the installed entry"

    assert content.startswith("[Desktop Entry]")
    assert f'Exec="{fake_executable}" gui' in content
    assert "Icon=starbash" in content
    assert "Terminal=false" in content
    assert "StartupWMClass=starbash" in content
    # Every template placeholder must have been substituted.
    assert "$" not in content

    icons = _base(setup_test_environment) / "icons" / "hicolor"
    assert (icons / "512x512" / "apps" / "starbash.png").is_file()
    assert (icons / "scalable" / "apps" / "starbash.svg").is_file()


def test_reinstall_leaves_identical_files_alone(setup_test_environment, fake_executable):
    """Calling install on every start-up must not rewrite unchanged files."""
    first = desktop.install_desktop_entry()
    assert first is not None and first.changed is True

    second = desktop.install_desktop_entry()
    assert second is not None
    assert second.changed is False
    assert second.desktop_file == first.desktop_file


def test_reinstall_repairs_a_moved_executable(
    setup_test_environment, fake_executable, monkeypatch, tmp_path
):
    """After an upgrade moves the console script, the entry is rewritten."""
    desktop.install_desktop_entry()

    moved = tmp_path / "elsewhere" / "sb"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("#!/bin/sh\n")
    monkeypatch.setattr(desktop, "_resolve_executable", lambda: str(moved))

    result = desktop.install_desktop_entry()
    assert result is not None and result.changed is True
    assert f'Exec="{moved}" gui' in result.desktop_file.read_text(encoding="utf-8")


def test_opt_out_env_var_skips_installation(setup_test_environment, fake_executable, monkeypatch):
    """STARBASH_NO_DESKTOP_INSTALL=1 leaves the user's data dir untouched."""
    monkeypatch.setenv(desktop.DISABLE_ENV_VAR, "1")

    assert desktop.should_install_desktop_entry() is False
    assert desktop.install_desktop_entry() is None
    assert not (_base(setup_test_environment) / "applications").exists()


def test_skipped_on_non_linux_platforms(setup_test_environment, fake_executable, monkeypatch):
    """.desktop entries are a Linux concept; other platforms are left alone."""
    monkeypatch.setattr(desktop.sys, "platform", "darwin")

    assert desktop.should_install_desktop_entry() is False
    assert desktop.install_desktop_entry() is None


def test_skipped_when_no_console_script_is_on_path(setup_test_environment, monkeypatch):
    """Without a ``starbash``/``sb`` executable there is nothing to point Exec at."""
    monkeypatch.setattr(desktop, "_resolve_executable", lambda: None)

    assert desktop.install_desktop_entry() is None
    assert not (_base(setup_test_environment) / "applications").exists()


def test_failures_never_raise(setup_test_environment, fake_executable, monkeypatch):
    """A broken asset must not break `sb gui` start-up."""
    monkeypatch.setattr(desktop, "_asset", _raise_oserror)

    assert desktop.install_desktop_entry() is None
    assert not (_base(setup_test_environment) / "applications").exists()


def _raise_oserror(name: str) -> bytes:
    """Stand-in for :func:`desktop._asset` that always fails."""
    raise OSError(f"cannot read asset: {name}")
