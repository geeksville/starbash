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

from starbash.app import Starbash
from starbash.database import Database, get_column_name
from starbash.processed_target import (
    MasterCandidate,
    MasterSelectionEdit,
    ParameterOption,
    ProcessedTarget,
    SessionMasterOption,
    SessionOption,
    StageOption,
    coerce_override,
    stage_declarations,
)
from starbash.url import make_file_url

__all__ = [
    "TARGET_CONFIG_NAME",
    "MasterCandidate",
    "MasterSelectionEdit",
    "ParameterOption",
    "SessionMasterOption",
    "SessionOption",
    "StageOption",
    "coerce_override",
    "image_basename",
    "load_sessions",
    "load_session_images",
    "load_session_options",
    "load_repos",
    "load_masters",
    "master_url",
    "load_targets",
    "load_stage_options",
    "save_stage_options",
    "save_master_selections",
    "selected_targets",
    "load_selection",
    "dashboard_stats",
]

#: Path (relative to a target's output dir) of its processed-target config.
TARGET_CONFIG_NAME = Path(".starbash") / "main.toml"
#: Path (relative to a target's output dir) of its per-session metadata/masters.
SESSIONS_CONFIG_NAME = Path(".starbash") / "sessions.toml"


def image_basename(image: dict[str, Any]) -> str:
    """Return the display filename for an image row."""
    path = image.get("abspath") or image.get("path") or ""
    return Path(str(path)).name


def _as_float(value: Any) -> float:
    """Best-effort numeric coercion for values coming back out of SQLite."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_sessions(sb: Starbash) -> list[dict[str, Any]]:
    """Return the sessions matching the current selection, shaped for the table.

    ``search_session()`` already returns plain dicts, but keyed by **SQL column
    name** (``num_images``, ``exptime_total``, ...).  Display formatting is the
    model's job (via each :class:`Column`'s formatter), so rows pass through as-is.
    """
    return [dict(session) for session in sb.search_session()]


def load_session_images(sb: Starbash, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the frames belonging to ``session``, shaped for the table."""
    rows: list[dict[str, Any]] = []
    for image in sb.get_session_images(session):
        row = dict(image)
        row["basename"] = image_basename(row)
        rows.append(row)
    return rows


def load_repos(sb: Starbash, *, show_all: bool = False) -> list[dict[str, Any]]:
    """Return managed repositories with their indexed image count.

    By default this lists only the repositories users care about - the exact set
    the CLI's ``sb repo list`` shows, since both go through
    :attr:`~toml_repo.manager.RepoManager.regular_repos` (preferences, recipe and
    ``pkg://`` repos are hidden).  Pass ``show_all=True`` for the CLI's verbose
    listing, which includes those too.
    """
    counts: Counter[int] = Counter(sb.db.get_column(Database.IMAGES_TABLE, "repo_id"))
    per_url: dict[str, int] = {}
    for repo_id, count in counts.items():
        url = sb.db.get_repo_url(repo_id)
        if url:
            per_url[url] = count

    repos = sb.repo_manager.repos if show_all else sb.repo_manager.regular_repos
    rows: list[dict[str, Any]] = []
    for repo in repos:
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


def master_url(sb: Starbash, path: str | None) -> str | None:
    """Absolute file URL for a master frame recorded relative to the master repo.

    ``sessions.toml`` stores calibration masters as repo-relative paths (the same
    strings ``Processing`` writes), so anything that wants to *preview* or *open*
    one needs the master repo's directory on top of them.

    Returns ``None`` when there is no master repo, it is not a local one, or the
    frame is not on disk - a preview needs a real file, and a link that goes
    nowhere is worse than plain text.
    """
    if not path:
        return None
    repo = sb.repo_manager.get_repo_by_kind("master")
    if repo is None:
        return None
    try:
        resolved = repo.resolve_path(path)
    except (OSError, ValueError):  # a non-local repo cannot resolve a filepath
        return None
    return make_file_url(resolved) if resolved.is_file() else None


def load_targets(sb: Starbash) -> list[dict[str, Any]]:
    """Enumerate processed targets by scanning the processed output repository."""
    rows: list[dict[str, Any]] = []
    repo = sb.repo_manager.get_repo_by_kind("processed")
    if repo is None:
        return rows
    path = repo.get_path()
    if path is None or not path.exists():
        return rows

    for target in ProcessedTarget.discover(path):
        rows.append(
            {
                "target": target.name.name,
                "path": str(target.name),
                # Lets the target table's Output cell be a clickable link.
                "path_url": make_file_url(target.name),
            }
        )
    return rows


def selected_targets(sb: Starbash) -> list[str]:
    """The targets the user currently has selected (``sb select target ...``).

    An empty list means "no target filter", which ``sb select`` treats as *every*
    target being in effect; the Targets page mirrors that by pre-highlighting all
    of its rows (see ``doc/plans/targets-selection-sync.md``).
    """
    return [str(target) for target in sb.selection.targets]


def load_stage_options(sb: Starbash, target_path: str) -> list[StageOption]:
    """Load a target's stages, merged with the parameters each recipe declares.

    Delegates to :meth:`ProcessedTarget.stage_options`; the declared parameter
    defaults/descriptions come from the loaded recipe repos.
    """
    if not (Path(target_path) / TARGET_CONFIG_NAME).exists():
        return []
    target = ProcessedTarget.open(target_path)
    return target.stage_options(stage_declarations(sb.get_recipes()))


def save_stage_options(target_path: str, stages: list[StageOption]) -> None:
    """Write the stage/parameter selection back to the target's config file.

    Delegates to :meth:`ProcessedTarget.save_stage_options`, which rebuilds the
    ``stages`` array-of-tables in the same shape the scaffold writes so repeated
    saves stay stable and hand-editable.
    """
    ProcessedTarget.open(target_path).save_stage_options(stages)


def load_session_options(target_path: str) -> list[SessionOption]:
    """Load the per-session master selections recorded in ``sessions.toml``.

    This is a file-only read (no SQLite), so callers may run it on a worker
    thread: ``sessions.toml`` carries every frame's metadata and can be large.
    Returns an empty list for a target with no recorded calibration.
    """
    if not (Path(target_path) / SESSIONS_CONFIG_NAME).exists():
        return []
    return ProcessedTarget.open(target_path).session_options()


def save_master_selections(target_path: str, edits: list[MasterSelectionEdit]) -> None:
    """Record explicit (user) master choices back to the target's ``sessions.toml``.

    ``edits`` is a batch of ``(session_key, master_type, path)``; each is written
    with ``selected_by = "user"`` so a later processing run honours it.
    """
    ProcessedTarget.open(target_path).save_master_selections(edits)


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
    """Return headline counts for the dashboard cards.

    Session rows are keyed by **SQL column name**, whereas ``Database.*_KEY``
    constants are metadata/toml-style names (``"num-images"`` vs ``"num_images"``).
    Translating through :func:`get_column_name` is what keeps these totals correct.
    """
    frames_key = get_column_name(Database.NUM_IMAGES_KEY)
    exptime_key = get_column_name(Database.EXPTIME_TOTAL_KEY)

    sessions = sb.search_session()
    frames = 0
    seconds = 0.0
    for session in sessions:
        frames += int(_as_float(session.get(frames_key)))
        seconds += _as_float(session.get(exptime_key))

    return {
        "sessions": len(sessions),
        "frames": frames,
        "integration_hours": round(seconds / 3600.0, 1),
        "repos": len(sb.repo_manager.repos),
        "images_indexed": sb.db.len_table(Database.IMAGES_TABLE),
    }
