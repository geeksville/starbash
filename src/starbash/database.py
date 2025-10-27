from __future__ import annotations

import logging
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

    EXPTIME_KEY = "EXPTIME"
    FILTER_KEY = "FILTER"
    START_KEY = "start"
    END_KEY = "end"
    NUM_IMAGES_KEY = "num-images"
    EXPTIME_TOTAL_KEY = "exptime-total"
    DATE_OBS_KEY = "DATE-OBS"
    IMAGE_DOC_KEY = "image-doc"
    IMAGETYP_KEY = "IMAGETYP"
    OBJECT_KEY = "OBJECT"

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

        # Sessions are day+filter+target+imagetyp specific. They contain:
        #  * start & end - which are ISO8601 date strings.
        #  * image-doc - which is a document-id for some image within that session
        #  * num-images - which is the total # of images in that session
        #  * exptime-total - which is the total exposure time of all images in that session
        #  * filter - which is the filter found for this session (if known)
        self.sessions = self._db.table("sessions")

    # --- Convenience helpers for common image operations ---
    def upsert_image(self, record: dict[str, Any]) -> int:
        """Insert or update an image record by unique path.

        The record must include a 'path' key; other keys are arbitrary FITS metadata.
        """
        path = record.get("path")
        if not path:
            raise ValueError("record must include 'path'")

        Image = Query()
        r = self.images.upsert(record, Image.path == path)
        assert len(r) == 1
        return r[0]

    def search_image(self, q: Query) -> table.Document | list[table.Document] | None:
        return self.images.search(q)

    def get_image(self, path: str) -> table.Document | list[table.Document] | None:
        Image = Query()
        return self.images.get(Image.path == path)

    def all_images(self) -> list[dict[str, Any]]:
        return list(self.images.all())

    def get_session(self, to_find: dict[str, str]) -> table.Document | None:

        date = to_find.get(Database.START_KEY)
        assert date
        image_type = to_find.get(Database.IMAGETYP_KEY)
        assert image_type
        filter = to_find.get(Database.FILTER_KEY)
        assert filter
        target = to_find.get(Database.OBJECT_KEY)
        assert target

        # Convert the provided ISO8601 date string to a datetime, then
        # search for sessions with the same filter whose start time is
        # within +/- 8 hours of the provided date.
        target_dt = datetime.fromisoformat(date)
        window = timedelta(hours=8)
        start_min = (target_dt - window).isoformat()
        start_max = (target_dt + window).isoformat()

        # FOR DEBUGGING, FIXME REMOVE
        debugging = False
        if debugging:
            Session = Query()
            q = ~(Session.filter == filter)
            pr = self.sessions.get(q)
            logging.debug(f"Matches {pr}")

        # Since session 'start' is stored as ISO8601 strings, lexicographic
        # comparison aligns with chronological ordering for a uniform format.
        Session = Query()
        q = (
            (Session[Database.FILTER_KEY] == filter)
            & (Session[Database.IMAGETYP_KEY] == image_type)
            & (Session[Database.OBJECT_KEY] == target)
            & (Session.start >= start_min)
            & (Session.start <= start_max)
        )
        result = self.sessions.get(q)
        assert result is None or isinstance(result, table.Document)
        return result

    def upsert_session(
        self, new: dict[str, Any], existing: table.Document | None = None
    ) -> None:
        """Insert or update a session record."""
        if existing:
            # Update existing session with new data
            updated = existing.copy()
            if new[Database.START_KEY] < existing[Database.START_KEY]:
                updated[Database.START_KEY] = new[Database.START_KEY]

            if new[Database.END_KEY] > existing[Database.END_KEY]:
                updated[Database.END_KEY] = new[Database.END_KEY]

            updated[Database.NUM_IMAGES_KEY] = existing.get(
                Database.NUM_IMAGES_KEY, 0
            ) + new.get(Database.NUM_IMAGES_KEY, 0)

            updated[Database.EXPTIME_TOTAL_KEY] = existing.get(
                Database.EXPTIME_TOTAL_KEY, 0
            ) + new.get(Database.EXPTIME_TOTAL_KEY, 0)

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
