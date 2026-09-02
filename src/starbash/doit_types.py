"""Shared types and utilities for doit processing to avoid circular imports."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from starbash.paths import get_user_cache_dir

type TaskDict = dict[str, Any]  # a doit task dictionary

DEFAULT_MAX_CONTEXTS = 2
max_contexts = DEFAULT_MAX_CONTEXTS


def configure_max_contexts(value: Any) -> None:
    """Set the maximum number of processing contexts from user configuration.

    Invalid values are ignored so a malformed preference cannot prevent
    Starbash from starting.
    """
    global max_contexts

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        logging.warning(
            "Ignoring invalid max_contexts preference %r; using %d.",
            value,
            DEFAULT_MAX_CONTEXTS,
        )
        max_contexts = DEFAULT_MAX_CONTEXTS
        return

    max_contexts = value


def get_processing_dir() -> Path:
    """Get the base directory for processing contexts."""
    cache_dir = get_user_cache_dir()
    processing_dir = cache_dir / "processing"
    processing_dir.mkdir(parents=True, exist_ok=True)
    return processing_dir


def cleanup_old_contexts() -> None:
    """Remove oldest context directories if we exceed max_contexts."""
    processing_dir = get_processing_dir()
    logging.debug(f"Removing old processing contexts in: {processing_dir}")
    if not processing_dir.exists():
        return

    # Safety guard: if we're running under pytest but the processing dir is NOT a test
    # override (no explicit cache override and no STARBASH_CACHE_DIR), refuse to delete
    # anything. A leaked test global (e.g. a small max_contexts from a test config) must
    # never prune the real user's cache.
    from starbash import paths

    if os.environ.get("PYTEST_CURRENT_TEST") is not None:
        using_override = (
            paths._override_cache_dir is not None or os.getenv("STARBASH_CACHE_DIR")
        )
        if not using_override:
            logging.warning(
                "Refusing to clean processing contexts during tests without a cache override: %s",
                processing_dir,
            )
            return

    # Get all subdirectories in processing_dir
    contexts = [d for d in processing_dir.iterdir() if d.is_dir()]

    # If we have more than max_contexts, delete the oldest ones
    if len(contexts) > max_contexts:
        # Sort by modification time (oldest first)
        contexts.sort(key=lambda d: d.stat().st_mtime)

        # Calculate how many to delete
        num_to_delete = len(contexts) - max_contexts

        # Delete the oldest directories
        for context_dir in contexts[:num_to_delete]:
            logging.debug(f"Removing old processing context: {context_dir}")
            shutil.rmtree(context_dir, ignore_errors=True)
