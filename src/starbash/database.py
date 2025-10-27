from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta
import json

from .paths import get_user_data_dir


class Database:
    """SQLite-backed application database.

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

        db_filename = "db.sqlite3"
        self.db_path = data_dir / db_filename

        # Open SQLite database
        self._db = sqlite3.connect(str(self.db_path))
        self._db.row_factory = sqlite3.Row  # Enable column access by name

        # Initialize tables
        self._init_tables()

    def _init_tables(self) -> None:
        """Create the images and sessions tables if they don't exist."""
        cursor = self._db.cursor()

        # Create images table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                metadata TEXT NOT NULL
            )
        """
        )

        # Create index on path for faster lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_images_path ON images(path)
        """
        )

        # Create sessions table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                filter TEXT NOT NULL,
                imagetyp TEXT NOT NULL,
                object TEXT NOT NULL,
                num_images INTEGER NOT NULL,
                exptime_total REAL NOT NULL,
                image_doc_id INTEGER
            )
        """
        )

        # Create index on session attributes for faster queries
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_lookup
            ON sessions(filter, imagetyp, object, start, end)
        """
        )

        self._db.commit()

    # --- Convenience helpers for common image operations ---
    def upsert_image(self, record: dict[str, Any]) -> int:
        """Insert or update an image record by unique path.

        The record must include a 'path' key; other keys are arbitrary FITS metadata.
        Returns the rowid of the inserted/updated record.
        """
        path = record.get("path")
        if not path:
            raise ValueError("record must include 'path'")

        # Separate path from metadata
        metadata = {k: v for k, v in record.items() if k != "path"}
        metadata_json = json.dumps(metadata)

        cursor = self._db.cursor()
        cursor.execute(
            """
            INSERT INTO images (path, metadata) VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET metadata = excluded.metadata
        """,
            (path, metadata_json),
        )

        self._db.commit()

        # Get the rowid of the inserted/updated record
        cursor.execute("SELECT id FROM images WHERE path = ?", (path,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return cursor.lastrowid if cursor.lastrowid is not None else 0

    def search_image(self, conditions: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Search for images matching the given conditions.

        Args:
            conditions: Dictionary of metadata key-value pairs to match

        Returns:
            List of matching image records or None if no matches
        """
        cursor = self._db.cursor()
        cursor.execute("SELECT id, path, metadata FROM images")

        results = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            metadata["path"] = row["path"]
            metadata["id"] = row["id"]

            # Check if all conditions match
            match = all(metadata.get(k) == v for k, v in conditions.items())
            if match:
                results.append(metadata)

        return results if results else None

    def search_session(
        self, conditions: dict[str, Any] | None
    ) -> list[dict[str, Any]] | None:
        """Search for sessions matching the given conditions.

        Args:
            conditions: Dictionary of session key-value pairs to match, or None for all

        Returns:
            List of matching session records or None
        """
        if conditions is None:
            return self.all_sessions()

        cursor = self._db.cursor()
        cursor.execute(
            """
            SELECT id, start, end, filter, imagetyp, object,
                   num_images, exptime_total, image_doc_id
            FROM sessions
        """
        )

        results = []
        for row in cursor.fetchall():
            session = {
                "id": row["id"],
                self.START_KEY: row["start"],
                self.END_KEY: row["end"],
                self.FILTER_KEY: row["filter"],
                self.IMAGETYP_KEY: row["imagetyp"],
                self.OBJECT_KEY: row["object"],
                self.NUM_IMAGES_KEY: row["num_images"],
                self.EXPTIME_TOTAL_KEY: row["exptime_total"],
                self.IMAGE_DOC_KEY: row["image_doc_id"],
            }

            # Check if all conditions match
            match = all(session.get(k) == v for k, v in conditions.items())
            if match:
                results.append(session)

        return results if results else None

    def len_session(self) -> int:
        """Return the total number of sessions."""
        cursor = self._db.cursor()
        cursor.execute("SELECT COUNT(*) FROM sessions")
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_image(self, path: str) -> dict[str, Any] | None:
        """Get an image record by path."""
        cursor = self._db.cursor()
        cursor.execute("SELECT id, path, metadata FROM images WHERE path = ?", (path,))
        row = cursor.fetchone()

        if row is None:
            return None

        metadata = json.loads(row["metadata"])
        metadata["path"] = row["path"]
        metadata["id"] = row["id"]
        return metadata

    def all_images(self) -> list[dict[str, Any]]:
        """Return all image records."""
        cursor = self._db.cursor()
        cursor.execute("SELECT id, path, metadata FROM images")

        results = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            metadata["path"] = row["path"]
            metadata["id"] = row["id"]
            results.append(metadata)

        return results

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all session records."""
        cursor = self._db.cursor()
        cursor.execute(
            """
            SELECT id, start, end, filter, imagetyp, object,
                   num_images, exptime_total, image_doc_id
            FROM sessions
        """
        )

        results = []
        for row in cursor.fetchall():
            session = {
                "id": row["id"],
                self.START_KEY: row["start"],
                self.END_KEY: row["end"],
                self.FILTER_KEY: row["filter"],
                self.IMAGETYP_KEY: row["imagetyp"],
                self.OBJECT_KEY: row["object"],
                self.NUM_IMAGES_KEY: row["num_images"],
                self.EXPTIME_TOTAL_KEY: row["exptime_total"],
                self.IMAGE_DOC_KEY: row["image_doc_id"],
            }
            results.append(session)

        return results

    def get_session(self, to_find: dict[str, str]) -> dict[str, Any] | None:
        """Find a session matching the given criteria.

        Searches for sessions with the same filter, image type, and target
        whose start time is within +/- 8 hours of the provided date.
        """
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

        # Since session 'start' is stored as ISO8601 strings, lexicographic
        # comparison aligns with chronological ordering for a uniform format.
        cursor = self._db.cursor()
        cursor.execute(
            """
            SELECT id, start, end, filter, imagetyp, object,
                   num_images, exptime_total, image_doc_id
            FROM sessions
            WHERE filter = ? AND imagetyp = ? AND object = ?
              AND start >= ? AND start <= ?
            LIMIT 1
        """,
            (filter, image_type, target, start_min, start_max),
        )

        row = cursor.fetchone()
        if row is None:
            return None

        return {
            "id": row["id"],
            self.START_KEY: row["start"],
            self.END_KEY: row["end"],
            self.FILTER_KEY: row["filter"],
            self.IMAGETYP_KEY: row["imagetyp"],
            self.OBJECT_KEY: row["object"],
            self.NUM_IMAGES_KEY: row["num_images"],
            self.EXPTIME_TOTAL_KEY: row["exptime_total"],
            self.IMAGE_DOC_KEY: row["image_doc_id"],
        }

    def upsert_session(
        self, new: dict[str, Any], existing: dict[str, Any] | None = None
    ) -> None:
        """Insert or update a session record."""
        cursor = self._db.cursor()

        if existing:
            # Update existing session with new data
            updated_start = min(new[Database.START_KEY], existing[Database.START_KEY])
            updated_end = max(new[Database.END_KEY], existing[Database.END_KEY])
            updated_num_images = existing.get(Database.NUM_IMAGES_KEY, 0) + new.get(
                Database.NUM_IMAGES_KEY, 0
            )
            updated_exptime_total = existing.get(
                Database.EXPTIME_TOTAL_KEY, 0
            ) + new.get(Database.EXPTIME_TOTAL_KEY, 0)

            cursor.execute(
                """
                UPDATE sessions
                SET start = ?, end = ?, num_images = ?, exptime_total = ?
                WHERE id = ?
            """,
                (
                    updated_start,
                    updated_end,
                    updated_num_images,
                    updated_exptime_total,
                    existing["id"],
                ),
            )
        else:
            # Insert new session
            cursor.execute(
                """
                INSERT INTO sessions
                (start, end, filter, imagetyp, object, num_images, exptime_total, image_doc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    new[Database.START_KEY],
                    new[Database.END_KEY],
                    new[Database.FILTER_KEY],
                    new[Database.IMAGETYP_KEY],
                    new[Database.OBJECT_KEY],
                    new[Database.NUM_IMAGES_KEY],
                    new[Database.EXPTIME_TOTAL_KEY],
                    new.get(Database.IMAGE_DOC_KEY),
                ),
            )

        self._db.commit()

    # --- Lifecycle ---
    def close(self) -> None:
        self._db.close()

    # Context manager support
    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
