"""Data access for the GUI.

There are deliberately two families of helpers:

``load_*``
    Run on the **GUI thread** against the single long-lived
    :class:`~starbash.app.Starbash` instance and return plain dicts shaped to
    match the table models.  These are quick SQLite reads, so keeping them on the
    GUI thread avoids all cross-thread connection problems.

``run_*``
    The long operations (reindex / process / publish).  Each builds its **own**
    ``Starbash`` - and therefore its own SQLite connection - so it can run safely
    on a worker thread.  They report progress through the core event bus, which
    the :class:`~starbash.ui.qt.bridge.EventBusBridge` forwards to the GUI.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.toml_file import TOMLFile

from starbash.app import Starbash
from starbash.database import Database
from starbash.stage_utils import get_stages_aot, upsert_stage

__all__ = [
    "TARGET_CONFIG_NAME",
    "image_basename",
    "load_sessions",
    "load_session_images",
    "load_repos",
    "load_masters",
    "load_targets",
    "load_target_config",
    "save_target_stages",
    "load_selection",
    "dashboard_stats",
]

#: Path (relative to a target's output dir) of its processed-target config.
TARGET_CONFIG_NAME = Path(".starbash") / "main.toml"


def image_basename(image: dict[str, Any]) -> str:
    """Return the display filename for an image row."""
    path = image.get("abspath") or image.get("path") or ""
    return Path(str(path)).name


def load_sessions(sb: Starbash) -> list[dict[str, Any]]:
    """Return the sessions matching the current selection, shaped for the table."""
    rows: list[dict[str, Any]] = []
    for session in sb.search_session():
        row = dict(session)  # search_session already returns plain dicts
        total = row.get(Database.EXPTIME_TOTAL_KEY)
        try:
            row[Database.EXPTIME_TOTAL_KEY] = round(float(total), 1) if total else 0.0
        except (TypeError, ValueError):
            row[Database.EXPTIME_TOTAL_KEY] = 0.0
        rows.append(row)
    return rows


def load_session_images(sb: Starbash, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the frames belonging to ``session``, shaped for the table."""
    rows: list[dict[str, Any]] = []
    for image in sb.get_session_images(session):
        row = dict(image)
        row["basename"] = image_basename(row)
        rows.append(row)
    return rows


def load_repos(sb: Starbash) -> list[dict[str, Any]]:
    """Return every managed repository with its indexed image count."""
    counts: Counter[int] = Counter(sb.db.get_column(Database.IMAGES_TABLE, "repo_id"))
    per_url: dict[str, int] = {}
    for repo_id, count in counts.items():
        url = sb.db.get_repo_url(repo_id)
        if url:
            per_url[url] = count

    rows: list[dict[str, Any]] = []
    for repo in sb.repo_manager.repos:
        repo_path = repo.get_path()
        rows.append(
            {
                "kind": repo.kind(),
                "url": repo.url,
                "images": per_url.get(repo.url, 0),
                "path": str(repo_path) if repo_path else "",
            }
        )
    return rows


def load_masters(sb: Starbash) -> list[dict[str, Any]]:
    """Return the indexed master calibration frames."""
    try:
        images = sb.get_master_images()
    except Exception:  # noqa: BLE001 - no master repo configured is not an error here
        return []
    rows: list[dict[str, Any]] = []
    for image in images:
        row = dict(image)
        row["basename"] = image_basename(row)
        rows.append(row)
    return rows


def load_targets(sb: Starbash) -> list[dict[str, Any]]:
    """Enumerate processed targets by scanning the processed output repository."""
    rows: list[dict[str, Any]] = []
    repo = sb.repo_manager.get_repo_by_kind("processed")
    if repo is None:
        return rows
    path = repo.get_path()
    if path is None or not path.exists():
        return rows

    for child in sorted(path.iterdir()):
        config = child / TARGET_CONFIG_NAME
        if not child.is_dir() or not config.exists():
            continue
        used, excluded = _stage_counts(config)
        rows.append(
            {
                "target": child.name,
                "path": str(child),
                "used": used,
                "excluded": excluded,
            }
        )
    return rows


def _stage_counts(config_path: Path) -> tuple[int, int]:
    """Return ``(active, excluded)`` stage counts for a target config file."""
    try:
        document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    except (OSError, ParseError):
        return (0, 0)

    used = excluded = 0
    for entry in get_stages_aot(document):
        if not entry.get("name"):
            continue
        if entry.get("excluded", False):
            excluded += 1
        else:
            used += 1
    return (used, excluded)


def load_target_config(target_path: str) -> list[dict[str, Any]]:
    """Return the ``[[stages]]`` entries from a target's config file."""
    config = Path(target_path) / TARGET_CONFIG_NAME
    if not config.exists():
        return []
    document = tomlkit.parse(config.read_text(encoding="utf-8"))

    stages: list[dict[str, Any]] = []
    for entry in get_stages_aot(document):
        name = entry.get("name")
        if not name:
            continue
        overrides = entry.get("overrides")
        stages.append(
            {
                "name": str(name),
                "excluded": bool(entry.get("excluded", False)),
                "overrides": [dict(o) for o in overrides] if overrides else [],
            }
        )
    return stages


def save_target_stages(target_path: str, used: list[str], excluded: list[str]) -> None:
    """Persist which stages are active vs excluded for one processed target.

    Uses the same ``[[stages]]`` schema the core reads (see
    :mod:`starbash.stage_utils`), so the CLI and GUI agree on the file format.
    """
    config = Path(target_path) / TARGET_CONFIG_NAME
    document = (
        tomlkit.parse(config.read_text(encoding="utf-8"))
        if config.exists()
        else tomlkit.document()
    )

    for name in used:
        upsert_stage(document, {"name": name}, excluded=False)
    for name in excluded:
        upsert_stage(document, {"name": name}, excluded=True)

    config.parent.mkdir(parents=True, exist_ok=True)
    TOMLFile(config).write(document)


def load_selection(sb: Starbash) -> dict[str, Any]:
    """Return the persisted selection state in a GUI-friendly shape."""
    selection = sb.selection
    return {
        "targets": list(selection.targets),
        "telescopes": list(selection.telescopes),
        "filters": list(selection.filters),
        "image_types": list(selection.image_types),
        "date_start": selection.date_start,
        "date_end": selection.date_end,
        "summary": selection.summary(),
    }


def dashboard_stats(sb: Starbash) -> dict[str, Any]:
    """Return headline counts for the dashboard cards."""
    sessions = sb.search_session()
    frames = sum(int(s.get(Database.NUM_IMAGES_KEY) or 0) for s in sessions)
    seconds = 0.0
    for session in sessions:
        try:
            seconds += float(session.get(Database.EXPTIME_TOTAL_KEY) or 0.0)
        except (TypeError, ValueError):
            continue

    return {
        "sessions": len(sessions),
        "frames": frames,
        "integration_hours": round(seconds / 3600.0, 1),
        "repos": len(sb.repo_manager.repos),
        "images_indexed": sb.db.len_table(Database.IMAGES_TABLE),
    }

