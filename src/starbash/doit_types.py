"""Shared types and utilities for doit processing to avoid circular imports."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from starbash.paths import get_user_cache_dir

type TaskDict = dict[str, Any]  # a doit task dictionary

max_contexts = 2  # FIXME, eventually make customizable via user preferences


def get_processing_dir() -> Path:
    """Get the base directory for processing contexts."""
    cache_dir = get_user_cache_dir()
    processing_dir = cache_dir / "processing"
    processing_dir.mkdir(parents=True, exist_ok=True)
    return processing_dir


def cleanup_old_contexts() -> None:
    """Remove oldest context directories if we exceed max_contexts."""
    processing_dir = get_processing_dir()
    if not processing_dir.exists():
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
