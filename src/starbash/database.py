from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta
from tinydb import TinyDB, Query, table

from .paths import get_user_data_dir


class Database:
    """TinyDB-backed application database.

    Stores data under the OS-specific user data directory using platformdirs.
    Provides an `images` table for FITS metadata and basic helpers.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
    ) -> None:
        # Resolve base data directory (allow override for tests)
        if base_dir is None:

            data_dir = get_user_data_dir()
        else:
            data_dir = base_dir

        db_filename = "db.json"
        self.db_path = data_dir / db_filename

        # Open TinyDB JSON store
        self._db = TinyDB(self.db_path)

        # Public handle to the images table
        self.images = self._db.table("images")

        # Sessions are day and filter specific. They contain:
        #  * start & end - which are ISO8601 date strings.
        #  * image-doc - which is a document-id for some image within that session
        #  * num-images - which is the total # of images in that session
        #  * exptime-total - which is the total exposure time of all images in that session
        #  * filter - which is the filter found for this session (if known)
        self.sessions = self._db.table("sessions")

    # --- Convenience helpers for common image operations ---
    def upsert_image(self, record: dict[str, Any]) -> None:
        """Insert or update an image record by unique path.

        The record must include a 'path' key; other keys are arbitrary FITS metadata.
        """
        path = record.get("path")
        if not path:
            raise ValueError("record must include 'path'")

        Image = Query()
        self.images.upsert(record, Image.path == path)

    def search_image(self, q: Query) -> table.Document | list[table.Document] | None:
        return self.images.search(q)

    def get_image(self, path: str) -> table.Document | list[table.Document] | None:
        Image = Query()
        return self.images.get(Image.path == path)

    def all_images(self) -> list[dict[str, Any]]:
        return list(self.images.all())

    def get_session(
        self, date: str, filter: str
    ) -> table.Document | list[table.Document] | None:

        # Convert the provided ISO8601 date string to a datetime, then
        # search for sessions with the same filter whose start time is
        # within +/- 8 hours of the provided date.
        target_dt = datetime.fromisoformat(date)
        window = timedelta(hours=8)
        start_min = (target_dt - window).isoformat()
        start_max = (target_dt + window).isoformat()

        # Since session 'start' is stored as ISO8601 strings, lexicographic
        # comparison aligns with chronological ordering for a uniform format.
        Session = Query()
        q = (
            (Session.filter == filter)
            & (Session.start >= start_min)
            & (Session.start <= start_max)
        )
        return self.sessions.get(q)

    def upsert_session(
        self, new: dict[str, Any], existing: table.Document | None = None
    ) -> None:
        """Insert or update a session record."""
        if existing:
            # Update existing session with new data
            updated = existing.copy()
            if new["start"] < existing["start"]:
                updated["start"] = new["start"]
            if new["end"] > existing["end"]:
                updated["end"] = new["end"]
            updated["num-images"] = existing.get("num-images", 0) + new.get(
                "num-images", 0
            )
            updated["exptime-total"] = existing.get("exptime-total", 0) + new.get(
                "exptime-total", 0
            )
            self.sessions.update(updated, doc_ids=[existing.doc_id])
        else:
            self.sessions.insert(new)

    # --- Lifecycle ---
    def close(self) -> None:
        self._db.close()

    # Context manager support
    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
