"""Install the Linux desktop integration (a ``.desktop`` entry plus themed icons).

Without this, a launcher/dock (GNOME Shell, KDE, Xfce, ...) cannot name or iconify
the running window.  Three things have to line up, and this module arranges all
three:

* a ``<id>.desktop`` file in the user's ``applications/`` directory,
* its ``Icon=`` key naming an icon present in the ``hicolor`` theme, and
* the window's app id / ``WM_CLASS`` matching ``StartupWMClass`` - Qt is told the
  id via ``QGuiApplication.setDesktopFileName()`` (see :mod:`starbash.ui.qt.app`).

Installation is **idempotent** (files are only rewritten when their contents
change, which also repairs the entry after a pipx upgrade moves the executable) and
**best-effort**: it is skipped off Linux, can be disabled with
``STARBASH_NO_DESKTOP_INSTALL=1``, and never raises - a desktop integration
problem must never stop ``sb gui`` from starting.

This module deliberately imports no Qt, so it can be tested without a GUI stack.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

from starbash.paths import get_user_data_base_dir

logger = logging.getLogger(__name__)

__all__ = [
    "DESKTOP_FILE_NAME",
    "DISABLE_ENV_VAR",
    "ICON_NAME",
    "DesktopInstallResult",
    "install_desktop_entry",
    "should_install_desktop_entry",
]

#: Base name (no ``.desktop`` suffix) of the entry we install.  Must equal what is
#: handed to ``QGuiApplication.setDesktopFileName()``.
DESKTOP_FILE_NAME = "starbash"

#: Name the icons are installed under in the hicolor theme (used for ``Icon=``).
ICON_NAME = "starbash"

#: Escape hatch for users (or CI) who don't want Starbash touching their data dir.
DISABLE_ENV_VAR = "STARBASH_NO_DESKTOP_INSTALL"

#: Template shipped in the package; ``$exec``, ``$icon_name`` and ``$wm_class``
#: placeholders are filled in at install time.
DESKTOP_TEMPLATE = "starbash.desktop.in"

#: (hicolor size bucket, packaged asset) pairs to install.  The SVG covers
#: SVG-aware themes at any size; the PNG is the fallback.
ICON_INSTALLS = (
    ("scalable", "icon.svg"),
    ("512x512", "icon.png"),
)


@dataclass(frozen=True)
class DesktopInstallResult:
    """What an install attempt produced, so callers and tests can assert on it."""

    desktop_file: Path
    executable: str
    changed: bool


def should_install_desktop_entry() -> bool:
    """Whether desktop integration applies here (Linux, and not opted out)."""
    if not sys.platform.startswith("linux"):
        return False
    return not os.environ.get(DISABLE_ENV_VAR)


def _resolve_executable() -> str | None:
    """Absolute path of the console script that launches Starbash, if installed."""
    for name in ("starbash", "sb"):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    return None


def _asset(name: str) -> bytes:
    """Read a packaged asset by name."""
    return resources.files("starbash.assets").joinpath(name).read_bytes()


def _write_if_changed(path: Path, data: bytes) -> bool:
    """Write ``data`` to ``path`` only when it differs.  Returns True if written."""
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def install_desktop_entry() -> DesktopInstallResult | None:
    """Install or refresh the ``.desktop`` entry and its themed icons.

    Safe to call on every start-up: unchanged files are left alone, and a stale
    entry (e.g. after a pipx upgrade moved the executable) is silently repaired.

    Returns:
        A :class:`DesktopInstallResult`, or ``None`` when the install was skipped -
        not Linux, opted out, no console script on ``PATH``, or any failure.
    """
    if not should_install_desktop_entry():
        return None

    base = get_user_data_base_dir()
    desktop_file = base / "applications" / f"{DESKTOP_FILE_NAME}.desktop"
    executable = ""
    changed = False

    try:
        resolved = _resolve_executable()
        if resolved is None:
            logger.debug("Desktop entry skipped: no starbash/sb console script on PATH")
            return None
        executable = resolved

        template = Template(_asset(DESKTOP_TEMPLATE).decode("utf-8"))
        content = template.substitute(
            exec=executable,
            icon_name=ICON_NAME,
            wm_class=DESKTOP_FILE_NAME,
        )
        changed = _write_if_changed(desktop_file, content.encode("utf-8"))

        for bucket, asset_name in ICON_INSTALLS:
            target = (
                base
                / "icons"
                / "hicolor"
                / bucket
                / "apps"
                / f"{ICON_NAME}{Path(asset_name).suffix}"
            )
            changed |= _write_if_changed(target, _asset(asset_name))
    except Exception as exc:  # noqa: BLE001 - must never stop the GUI from starting
        logger.debug("Desktop entry not installed: %s", exc)
        return None

    logger.debug(
        "Desktop entry %s: %s", "written" if changed else "already up to date", desktop_file
    )
    return DesktopInstallResult(desktop_file=desktop_file, executable=executable, changed=changed)
