"""Migration helpers for processed-target metadata."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.toml_document import TOMLDocument
from tomlkit.toml_file import TOMLFile

from starbash.toml import toml_from_template

logger = logging.getLogger(__name__)


def _as_document(document: Any) -> TOMLDocument:
    """Normalize a template result to a TOML document."""
    if isinstance(document, TOMLDocument):
        return document
    converted = tomlkit.document()
    converted.update(document)
    return converted


def migrate_legacy_target(target_dir: Path) -> bool:
    """Upgrade one legacy processed target to the ``.starbash`` layout.

    Returns:
        ``True`` when a legacy file was converted, otherwise ``False``.

    Raises:
        ValueError: If the target has an incomplete or malformed migration.
    """
    legacy_path = target_dir / "starbash.toml"
    metadata_dir = target_dir / ".starbash"
    main_path = metadata_dir / "main.toml"
    about_path = metadata_dir / "about.toml"
    sessions_path = metadata_dir / "sessions.toml"

    if not legacy_path.exists():
        return False
    if main_path.exists() or about_path.exists() or sessions_path.exists():
        raise ValueError(f"Cannot migrate {target_dir}: new metadata files already exist")

    legacy = tomlkit.parse(legacy_path.read_text(encoding="utf-8"))
    main = _as_document(toml_from_template("target/processed/main", overrides=None))
    about = _as_document(toml_from_template("target/processed/about", overrides=None))
    sessions = _as_document(toml_from_template("target/processed/sessions", overrides=None))

    for key, value in legacy.items():
        if key not in {"about", "sessions"}:
            main[key] = deepcopy(value)

    old_about = legacy.get("about", {})
    if isinstance(old_about, dict):
        for key, value in old_about.items():
            if key != "sessions":
                about[key] = deepcopy(value)

    report_sessions = old_about.get("sessions", []) if isinstance(old_about, dict) else []
    state_sessions = legacy.get("sessions", [])
    state_by_id = {
        state.get("id"): state
        for state in state_sessions
        if isinstance(state, dict) and state.get("id") is not None
    }
    migrated_sessions = tomlkit.aot()
    for report_session in report_sessions:
        if not isinstance(report_session, dict):
            continue
        session = deepcopy(report_session)
        state = state_by_id.get(session.pop("id", None))
        if isinstance(state, dict):
            for key in ("stages", "masters"):
                if key in state:
                    session[key] = deepcopy(state[key])
        migrated_sessions.append(session)

    if not migrated_sessions:
        for state in state_sessions:
            if not isinstance(state, dict):
                continue
            session = tomlkit.table()
            for key in ("date", "start", "end", "filter", "imagetyp", "object", "telescop"):
                if state.get(key) is not None:
                    session[key] = deepcopy(state[key])
            for key in ("stages", "masters"):
                if key in state:
                    session[key] = deepcopy(state[key])
            migrated_sessions.append(session)

    metadata_dir.mkdir(parents=True, exist_ok=True)
    sessions["sessions"] = migrated_sessions
    TOMLFile(main_path).write(main)
    TOMLFile(about_path).write(about)
    TOMLFile(sessions_path).write(sessions)

    for path in (main_path, about_path, sessions_path):
        tomlkit.parse(path.read_text(encoding="utf-8"))
    legacy_path.unlink()
    logger.info("Migrated processed target %s", target_dir)
    return True


def migrate_processed_repository(repo_dir: Path) -> tuple[int, int]:
    """Migrate every legacy target directory beneath a processed repository."""
    converted = 0
    skipped = 0
    for target_dir in sorted(path for path in repo_dir.iterdir() if path.is_dir()):
        if (target_dir / "starbash.toml").exists():
            migrate_legacy_target(target_dir)
            converted += 1
        else:
            skipped += 1
    return converted, skipped
