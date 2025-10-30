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

    The images table stores DATE-OBS and DATE as indexed SQL columns for
    efficient date-based queries, while other FITS metadata is stored in JSON.
    """

    EXPTIME_KEY = "EXPTIME"
    FILTER_KEY = "FILTER"
    START_KEY = "start"
    END_KEY = "end"
    NUM_IMAGES_KEY = "num-images"
    EXPTIME_TOTAL_KEY = "exptime-total"
    DATE_OBS_KEY = "DATE-OBS"
    DATE_KEY = "DATE"
    IMAGE_DOC_KEY = "image-doc"
    IMAGETYP_KEY = "IMAGETYP"
    OBJECT_KEY = "OBJECT"
    TELESCOP_KEY = "TELESCOP"

    SESSIONS_TABLE = "sessions"
    IMAGES_TABLE = "images"

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

        # Create images table with DATE-OBS and DATE as indexed columns
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.IMAGES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                date_obs TEXT,
                date TEXT,
                metadata TEXT NOT NULL
            )
        """
        )

        # Create index on path for faster lookups
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_images_path ON {self.IMAGES_TABLE}(path)
        """
        )

        # Create index on date_obs for efficient date range queries
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_images_date_obs ON {self.IMAGES_TABLE}(date_obs)
        """
        )

        # Create index on date for queries using DATE field
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_images_date ON {self.IMAGES_TABLE}(date)
        """
        )

        # Create sessions table
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.SESSIONS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                filter TEXT NOT NULL,
                imagetyp TEXT NOT NULL,
                object TEXT NOT NULL,
                telescop TEXT NOT NULL,
                num_images INTEGER NOT NULL,
                exptime_total REAL NOT NULL,
                image_doc_id INTEGER
            )
        """
        )

        # Create index on session attributes for faster queries
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_sessions_lookup
            ON {self.SESSIONS_TABLE}(filter, imagetyp, object, telescop, start, end)
        """
        )

        self._db.commit()

    # --- Convenience helpers for common image operations ---
    def upsert_image(self, record: dict[str, Any]) -> int:
        """Insert or update an image record by unique path.

        The record must include a 'path' key; other keys are arbitrary FITS metadata.
        DATE-OBS and DATE are extracted and stored as indexed columns for efficient queries.
        Returns the rowid of the inserted/updated record.
        """
        path = record.get("path")
        if not path:
            raise ValueError("record must include 'path'")

        # Extract date fields for column storage
        date_obs = record.get(self.DATE_OBS_KEY)
        date = record.get(self.DATE_KEY)

        # Separate path and date fields from metadata
        metadata = {k: v for k, v in record.items() if k != "path"}
        metadata_json = json.dumps(metadata)

        cursor = self._db.cursor()
        cursor.execute(
            f"""
            INSERT INTO {self.IMAGES_TABLE} (path, date_obs, date, metadata) VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                date_obs = excluded.date_obs,
                date = excluded.date,
                metadata = excluded.metadata
        """,
            (path, date_obs, date, metadata_json),
        )

        self._db.commit()

        # Get the rowid of the inserted/updated record
        cursor.execute(f"SELECT id FROM {self.IMAGES_TABLE} WHERE path = ?", (path,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return cursor.lastrowid if cursor.lastrowid is not None else 0

    def search_image(self, conditions: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Search for images matching the given conditions.

        Args:
            conditions: Dictionary of metadata key-value pairs to match.
                       Special keys:
                       - 'date_start': Filter images with DATE-OBS >= this date
                       - 'date_end': Filter images with DATE-OBS <= this date

        Returns:
            List of matching image records or None if no matches
        """
        # Extract special date filter keys (make a copy to avoid modifying caller's dict)
        conditions_copy = dict(conditions)
        date_start = conditions_copy.pop("date_start", None)
        date_end = conditions_copy.pop("date_end", None)

        # Build SQL query with WHERE clauses for date filtering
        where_clauses = []
        params = []

        if date_start:
            where_clauses.append("date_obs >= ?")
            params.append(date_start)

        if date_end:
            where_clauses.append("date_obs <= ?")
            params.append(date_end)

        # Build the query
        query = f"SELECT id, path, date_obs, date, metadata FROM {self.IMAGES_TABLE}"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        cursor = self._db.cursor()
        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            metadata["path"] = row["path"]
            metadata["id"] = row["id"]

            # Add date fields back to metadata for compatibility
            if row["date_obs"]:
                metadata[self.DATE_OBS_KEY] = row["date_obs"]
            if row["date"]:
                metadata[self.DATE_KEY] = row["date"]

            # Check if remaining conditions match (those stored in JSON metadata)
            match = all(metadata.get(k) == v for k, v in conditions_copy.items())

            if match:
                results.append(metadata)

        return results if results else None

    def search_session(
        self, conditions: dict[str, Any] | None
    ) -> list[dict[str, Any]] | None:
        """Search for sessions matching the given conditions.

        Args:
            conditions: Dictionary of session key-value pairs to match, or None for all.
                       Special keys:
                       - 'date_start': Filter sessions starting on or after this date
                       - 'date_end': Filter sessions starting on or before this date

        Returns:
            List of matching session records or None
        """
        if conditions is None:
            return self.all_sessions()

        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT id, start, end, filter, imagetyp, object, telescop,
                   num_images, exptime_total, image_doc_id
            FROM {self.SESSIONS_TABLE}
        """
        )

        # Extract date range conditions if present
        date_start = conditions.get("date_start")
        date_end = conditions.get("date_end")

        # Create a copy without date range keys for standard matching
        standard_conditions = {
            k: v
            for k, v in conditions.items()
            if k not in ("date_start", "date_end") and v is not None
        }

        results = []
        for row in cursor.fetchall():
            session = {
                "id": row["id"],
                self.START_KEY: row["start"],
                self.END_KEY: row["end"],
                self.FILTER_KEY: row["filter"],
                self.IMAGETYP_KEY: row["imagetyp"],
                self.OBJECT_KEY: row["object"],
                self.TELESCOP_KEY: row["telescop"],
                self.NUM_IMAGES_KEY: row["num_images"],
                self.EXPTIME_TOTAL_KEY: row["exptime_total"],
                self.IMAGE_DOC_KEY: row["image_doc_id"],
            }

            # Check if all standard conditions match
            match = all(session.get(k) == v for k, v in standard_conditions.items())

            # Apply date range filtering
            if match and date_start:
                session_start = session.get(self.START_KEY, "")
                match = match and session_start >= date_start

            if match and date_end:
                session_start = session.get(self.START_KEY, "")
                match = match and session_start <= date_end

            if match:
                results.append(session)

        return results if results else None

    def len_table(self, table_name: str) -> int:
        """Return the total number of rows in the specified table."""
        cursor = self._db.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_column(self, table_name: str, column_name: str) -> list[Any]:
        """Return all values from a specific column in the specified table."""
        cursor = self._db.cursor()
        cursor.execute(f'SELECT "{column_name}" FROM {table_name}')

        results = []
        for row in cursor.fetchall():
            results.append(row[column_name])

        return results

    def sum_column(self, table_name: str, column_name: str) -> float:
        """Return the SUM of all values in a specific column in the specified table."""
        cursor = self._db.cursor()
        cursor.execute(f'SELECT SUM("{column_name}") FROM {table_name}')
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else 0

    def get_image(self, path: str) -> dict[str, Any] | None:
        """Get an image record by path."""
        cursor = self._db.cursor()
        cursor.execute(
            f"SELECT id, path, date_obs, date, metadata FROM {self.IMAGES_TABLE} WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        metadata = json.loads(row["metadata"])
        metadata["path"] = row["path"]
        metadata["id"] = row["id"]

        # Add date fields back to metadata for compatibility
        if row["date_obs"]:
            metadata[self.DATE_OBS_KEY] = row["date_obs"]
        if row["date"]:
            metadata[self.DATE_KEY] = row["date"]

        return metadata

    def all_images(self) -> list[dict[str, Any]]:
        """Return all image records."""
        cursor = self._db.cursor()
        cursor.execute(
            f"SELECT id, path, date_obs, date, metadata FROM {self.IMAGES_TABLE}"
        )

        results = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            metadata["path"] = row["path"]
            metadata["id"] = row["id"]

            # Add date fields back to metadata for compatibility
            if row["date_obs"]:
                metadata[self.DATE_OBS_KEY] = row["date_obs"]
            if row["date"]:
                metadata[self.DATE_KEY] = row["date"]

            results.append(metadata)

        return results

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all session records."""
        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT id, start, end, filter, imagetyp, object, telescop,
                   num_images, exptime_total, image_doc_id
            FROM {self.SESSIONS_TABLE}
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
                self.TELESCOP_KEY: row["telescop"],
                self.NUM_IMAGES_KEY: row["num_images"],
                self.EXPTIME_TOTAL_KEY: row["exptime_total"],
                self.IMAGE_DOC_KEY: row["image_doc_id"],
            }
            results.append(session)

        return results

    def get_session_by_id(self, session_id: int) -> dict[str, Any] | None:
        """Get a session record by its ID.

        Args:
            session_id: The database ID of the session

        Returns:
            Session record dictionary or None if not found
        """
        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT id, start, end, filter, imagetyp, object, telescop,
                   num_images, exptime_total, image_doc_id
            FROM {self.SESSIONS_TABLE}
            WHERE id = ?
        """,
            (session_id,),
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
            self.TELESCOP_KEY: row["telescop"],
            self.NUM_IMAGES_KEY: row["num_images"],
            self.EXPTIME_TOTAL_KEY: row["exptime_total"],
            self.IMAGE_DOC_KEY: row["image_doc_id"],
        }

    def get_session(self, to_find: dict[str, str]) -> dict[str, Any] | None:
        """Find a session matching the given criteria.

        Searches for sessions with the same filter, image type, target, and telescope
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
        telescop = to_find.get(Database.TELESCOP_KEY, "unspecified")

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
            f"""
            SELECT id, start, end, filter, imagetyp, object, telescop,
                   num_images, exptime_total, image_doc_id
            FROM {self.SESSIONS_TABLE}
            WHERE filter = ? AND imagetyp = ? AND object = ? AND telescop = ?
              AND start >= ? AND start <= ?
            LIMIT 1
        """,
            (filter, image_type, target, telescop, start_min, start_max),
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
            self.TELESCOP_KEY: row["telescop"],
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
                f"""
                UPDATE {self.SESSIONS_TABLE}
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
                f"""
                INSERT INTO {self.SESSIONS_TABLE}
                (start, end, filter, imagetyp, object, telescop, num_images, exptime_total, image_doc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    new[Database.START_KEY],
                    new[Database.END_KEY],
                    new[Database.FILTER_KEY],
                    new[Database.IMAGETYP_KEY],
                    new[Database.OBJECT_KEY],
                    new.get(Database.TELESCOP_KEY, "unspecified"),
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
