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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.toml_file import TOMLFile

from starbash.app import Starbash
from starbash.database import Database, get_column_name
from starbash.stage_utils import get_stages_aot

__all__ = [
    "TARGET_CONFIG_NAME",
    "ParameterOption",
    "StageOption",
    "coerce_override",
    "image_basename",
    "load_sessions",
    "load_session_images",
    "load_repos",
    "load_masters",
    "load_targets",
    "load_stage_options",
    "save_stage_options",
    "preferred_target",
    "load_selection",
    "dashboard_stats",
]

#: Path (relative to a target's output dir) of its processed-target config.
TARGET_CONFIG_NAME = Path(".starbash") / "main.toml"


@dataclass
class ParameterOption:
    """One overridable stage parameter, with its declared default and current value.

    ``value is None`` means "not overridden", i.e. the recipe default applies.
    """

    name: str
    description: str | None
    default: Any
    value: Any | None = None

    @property
    def is_overridden(self) -> bool:
        """True when the user has set an explicit value."""
        return self.value is not None


@dataclass
class StageOption:
    """A stage of a processed target: whether it runs, plus its parameters."""

    name: str
    description: str | None
    excluded: bool
    parameters: list[ParameterOption]


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


def preferred_target(sb: Starbash) -> str | None:
    """The target the user currently has selected (``sb select target ...``)."""
    targets = sb.selection.targets
    return str(targets[0]) if targets else None


def _comment_of(table: Any, key: str) -> str | None:
    """Return the ``#`` comment attached to ``table[key]``, if any."""
    item = table.get(key) if table is not None else None
    comment = getattr(getattr(item, "trivia", None), "comment", None)
    if not comment:
        return None
    return comment.lstrip("#").strip() or None


def _stage_declarations(sb: Starbash) -> dict[str, dict[str, Any]]:
    """Map stage name -> its declared description and parameters.

    Recipes are the authoritative source of a parameter's default and description
    (declared as ``[[stages.parameters]]``).  Scanning the recipe repos is cheap
    because their config is already loaded; later definitions win, mirroring repo
    precedence.
    """
    declarations: dict[str, dict[str, Any]] = {}
    for repo in sb.get_recipes():
        try:
            stages = repo.config.get("stages")
        except Exception:  # noqa: BLE001 - one malformed recipe must not break the page
            continue
        if not stages:
            continue

        for stage in stages:
            name = stage.get("name")
            if not name:
                continue
            entry = declarations.setdefault(str(name), {"description": None, "parameters": {}})
            if stage.get("description"):
                entry["description"] = stage.get("description")
            for param in stage.get("parameters") or []:
                param_name = param.get("name")
                if not param_name:
                    continue
                entry["parameters"][str(param_name)] = {
                    "default": param.get("default"),
                    "description": param.get("description"),
                }
    return declarations


def load_stage_options(sb: Starbash, target_path: str) -> list[StageOption]:
    """Load a target's stages, merged with the parameters each recipe declares.

    Declared parameters are listed first, in declaration order, so the UI is
    consistent between targets.  Any override present in the file but *not* declared
    by a recipe is still surfaced, so hand-edited files are never silently dropped.
    """
    config = Path(target_path) / TARGET_CONFIG_NAME
    if not config.exists():
        return []

    document = tomlkit.parse(config.read_text(encoding="utf-8"))
    declarations = _stage_declarations(sb)

    stages: list[StageOption] = []
    for entry in get_stages_aot(document):
        name = entry.get("name")
        if not name:
            continue
        name = str(name)
        declared = declarations.get(name, {})
        declared_params: dict[str, Any] = declared.get("parameters", {})

        overrides: dict[str, Any] = {}
        for override in entry.get("overrides") or []:
            override_name = override.get("name")
            if override_name:
                overrides[str(override_name)] = override

        parameters: list[ParameterOption] = []
        for param_name, param_decl in declared_params.items():
            override = overrides.pop(param_name, None)
            parameters.append(
                ParameterOption(
                    name=param_name,
                    description=param_decl.get("description") or _comment_of(override, "name"),
                    default=param_decl.get("default"),
                    value=override.get("value") if override is not None else None,
                )
            )
        for param_name, override in overrides.items():
            parameters.append(
                ParameterOption(
                    name=param_name,
                    description=_comment_of(override, "name"),
                    default=None,
                    value=override.get("value"),
                )
            )

        stages.append(
            StageOption(
                name=name,
                description=declared.get("description") or _comment_of(entry, "name"),
                excluded=bool(entry.get("excluded", False)),
                parameters=parameters,
            )
        )
    return stages


def _toml_literal(value: Any) -> str:
    """Render a value the way the scaffold writes its commented-out ``value =`` line."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def coerce_override(text: str, default: Any) -> Any:
    """Convert user-typed text to the type of the parameter's declared default.

    Parameter values are substituted into tool scripts, so preserving the declared
    type matters (a number must stay a number).  Input that cannot be parsed falls
    back to the raw string rather than raising.
    """
    text = text.strip()
    if isinstance(default, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(text)
        except ValueError:
            pass
    if isinstance(default, (int, float)):
        try:
            return float(text)
        except ValueError:
            return text
    if isinstance(default, str):
        return text
    # No declared default to learn from: infer the most specific type that fits.
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            continue
    return text


def save_stage_options(target_path: str, stages: list[StageOption]) -> None:
    """Write the stage/parameter selection back to the target's config file.

    The ``stages`` array-of-tables is rebuilt from ``stages`` in exactly the shape
    :meth:`starbash.parameters.ParameterStore.write_stage_overrides` scaffolds, so
    repeated saves are stable and the file stays hand-editable.  The rest of the
    document (repo header, citation, ...) is preserved untouched.
    """
    config = Path(target_path) / TARGET_CONFIG_NAME
    document = (
        tomlkit.parse(config.read_text(encoding="utf-8"))
        if config.exists()
        else tomlkit.document()
    )

    stages_aot = tomlkit.aot()
    for stage in stages:
        entry = tomlkit.table()
        name_item = tomlkit.string(stage.name)
        if stage.description:
            name_item.comment(stage.description)
        entry["name"] = name_item
        if stage.excluded:
            entry["excluded"] = True

        if stage.parameters:
            overrides_aot = tomlkit.aot()
            for parameter in stage.parameters:
                override = tomlkit.table()
                param_name = tomlkit.string(parameter.name)
                if parameter.description:
                    param_name.comment(parameter.description)
                override["name"] = param_name
                if parameter.value is not None:
                    override["value"] = parameter.value
                else:
                    # Keep the default visible to hand-editors, as the scaffold does.
                    override.add(tomlkit.comment(f"value = {_toml_literal(parameter.default)}"))
                overrides_aot.append(override)
            entry["overrides"] = overrides_aot

        stages_aot.append(entry)

    document["stages"] = stages_aot
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

