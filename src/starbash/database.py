from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .aliases import normalize_target_name
from .paths import get_user_data_dir

type SessionRow = dict[str, Any]
type ImageRow = dict[str, Any]


@dataclass(frozen=True)
class SearchCondition:
    """A search condition for database queries.

    Args:
        column_name: The column name to filter on (e.g., 'i.date_obs', 'r.url')
        comparison_op: The comparison operator (e.g., '=', '>=', '<=', 'LIKE')
        value: The value to compare against
    """

    column_name: str
    comparison_op: str
    value: Any


def get_column_name(k: str) -> str:
    """Convert keynames to SQL legal column names"""
    k = k.lower()
    k = k.replace(" ", "_")
    k = k.replace("-", "_")
    return k


def metadata_to_instrument_id(metadata: dict[str, Any]) -> str | None:
    """Extract a normalized instrument ID from the metadata."""
    instrument: str | None = metadata.get(Database.TELESCOP_KEY)
    if instrument:
        instrument = normalize_target_name(instrument)
    return instrument


def metadata_to_camera_id(metadata: dict[str, Any]) -> str | None:
    """Extract a normalized camera ID from the metadata."""
    camera_id = metadata.get(
        Database.INSTRUME_KEY, metadata_to_instrument_id(metadata)
    )  # Fall back to the telescope name

    if camera_id:
        camera_id = normalize_target_name(camera_id)

    return camera_id


class Database:
    """SQLite-backed application database.

    Stores data under the OS-specific user data directory using platformdirs.

    Tables:
    #1: repos
    A table with one row per repository. Contains only 'id' (primary key) and 'url' (unique).
    The URL identifies the repository root (e.g., 'file:///path/to/repo').

    #2: images
    Provides an `images` table for FITS metadata and basic helpers.

    The images table stores DATE-OBS, DATE, and IMAGETYP as indexed SQL columns for
    efficient date-based and type-based queries, while other FITS metadata is stored in JSON.

    The 'path' column contains a path **relative** to the repository root.
    Each image belongs to exactly one repo, linked via the repo_id foreign key.
    The combination of (repo_id, path) is unique.

    Image retrieval methods (get_image, search_image, all_images) join with the repos
    table to include repo_url in results, allowing callers to reconstruct absolute paths.

    #3: sessions
    The sessions table has one row per observing session, summarizing key info.
    Sessions are identified by filter, image type, target, telescope, etc, and start/end times.
    They correspond to groups of images taken together during an observing run (e.g.
    session start/end describes the range of images DATE-OBS).

    Each session also has an image_doc_id field which will point to a representative
    image in the images table. Eventually we'll use joins to add extra info from images to
    the exposed 'session' row.

    """

    EXPTIME_KEY = "EXPTIME"
    FILTER_KEY = "FILTER"
    START_KEY = "start"
    END_KEY = "end"
    NUM_IMAGES_KEY = "num-images"
    EXPTIME_TOTAL_KEY = "exptime-total"
    DATE_OBS_KEY = "DATE-OBS"
    DATE_KEY = "DATE"
    IMAGE_DOC_KEY = "image-doc-id"
    IMAGETYP_KEY = "IMAGETYP"
    OBJECT_KEY = "OBJECT"
    TELESCOP_KEY = "TELESCOP"
    INSTRUME_KEY = "INSTRUME"
    EXPTIME_KEY = "EXPTIME"  # in all image files
    TOTALEXP_KEY = "TOTALEXP"  # in stacked ASI files
    GAIN_KEY = "GAIN"

    ID_KEY = "id"  # for finding any row by its ID
    REPO_URL_KEY = "repo_url"

    SESSIONS_TABLE = "sessions"
    IMAGES_TABLE = "images"
    REPOS_TABLE = "repos"

    def __init__(
        self,
        base_dir: Path | None = None,
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
        """Create the repos, images and sessions tables if they don't exist."""
        cursor = self._db.cursor()

        # Create repos table
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.REPOS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL
            )
        """
        )

        # Create index on url for faster lookups
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_repos_url ON {self.REPOS_TABLE}(url)
        """
        )

        # Create images table with DATE-OBS, DATE, and IMAGETYP as indexed columns
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.IMAGES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                date_obs TEXT,
                date TEXT,
                imagetyp TEXT COLLATE NOCASE,
                metadata TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES {self.REPOS_TABLE}(id),
                UNIQUE(repo_id, path)
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

        # Create index on imagetyp for efficient image type filtering
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_images_imagetyp ON {self.IMAGES_TABLE}(imagetyp)
        """
        )

        # Create sessions table
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.SESSIONS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                filter TEXT COLLATE NOCASE,
                imagetyp TEXT COLLATE NOCASE NOT NULL,
                object TEXT,
                telescop TEXT COLLATENOCASE NOT NULL,
                num_images INTEGER NOT NULL,
                exptime_total REAL NOT NULL,
                exptime REAL NOT NULL,
                image_doc_id INTEGER,
                FOREIGN KEY (image_doc_id) REFERENCES {self.IMAGES_TABLE}(id)
            )
        """
        )

        # Create index on session attributes for faster queries
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_sessions_lookup
            ON {self.SESSIONS_TABLE}(filter, imagetyp, object, telescop, exptime, start, end)
        """
        )

        self._db.commit()

    # --- Convenience helpers for common repo operations ---
    def remove_repo(self, url: str) -> None:
        """Remove a repo record by URL.

        This will cascade delete all images belonging to this repo, and all sessions
        that reference those images via image_doc_id.

        The relationship is: repos -> images (via repo_id) -> sessions (via image_doc_id).
        Sessions have an image_doc_id field that points to a representative image.
        We delete sessions whose representative image belongs to the repo being deleted.

        Args:
            url: The repository URL (e.g., 'file:///path/to/repo')
        """
        cursor = self._db.cursor()

        # Use a 3-way join to find and delete sessions that reference images from this repo
        # repo_url -> repo_id -> images.id -> sessions.image_doc_id
        cursor.execute(
            f"""
            DELETE FROM {self.SESSIONS_TABLE}
            WHERE id IN (
                SELECT s.id
                FROM {self.SESSIONS_TABLE} s
                INNER JOIN {self.IMAGES_TABLE} i ON s.image_doc_id = i.id
                INNER JOIN {self.REPOS_TABLE} r ON i.repo_id = r.id
                WHERE r.url = ?
            )
            """,
            (url,),
        )

        # Delete all images from this repo (using repo_id from URL)
        cursor.execute(
            f"""
            DELETE FROM {self.IMAGES_TABLE}
            WHERE repo_id = (SELECT id FROM {self.REPOS_TABLE} WHERE url = ?)
            """,
            (url,),
        )

        # Finally delete the repo itself
        cursor.execute(f"DELETE FROM {self.REPOS_TABLE} WHERE url = ?", (url,))

        self._db.commit()

    def upsert_repo(self, url: str) -> int:
        """Insert or update a repo record by unique URL.

        Args:
            url: The repository URL (e.g., 'file:///path/to/repo')

        Returns:
            The rowid of the inserted/updated record.
        """
        cursor = self._db.cursor()
        cursor.execute(
            f"""
            INSERT INTO {self.REPOS_TABLE} (url) VALUES (?)
            ON CONFLICT(url) DO NOTHING
        """,
            (url,),
        )

        self._db.commit()

        # Get the rowid of the inserted/existing record
        cursor.execute(f"SELECT id FROM {self.REPOS_TABLE} WHERE url = ?", (url,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return cursor.lastrowid if cursor.lastrowid is not None else 0

    def get_repo_id(self, url: str) -> int | None:
        """Get the repo_id for a given URL.

        Args:
            url: The repository URL

        Returns:
            The repo_id if found, None otherwise
        """
        cursor = self._db.cursor()
        cursor.execute(f"SELECT id FROM {self.REPOS_TABLE} WHERE url = ?", (url,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_repo_url(self, repo_id: int) -> str | None:
        """Get the URL for a given repo_id.

        Args:
            repo_id: The repository ID

        Returns:
            The URL if found, None otherwise
        """
        cursor = self._db.cursor()
        cursor.execute(f"SELECT url FROM {self.REPOS_TABLE} WHERE id = ?", (repo_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # --- Convenience helpers for common image operations ---
    def upsert_image(self, record: dict[str, Any], repo_url: str) -> int:
        """Insert or update an image record by unique path.

        The record must include a 'path' key (relative to repo); other keys are arbitrary FITS metadata.
        The path is stored as-is - caller is responsible for making it relative to the repo.
        DATE-OBS, DATE, and IMAGETYP are extracted and stored as indexed columns for efficient queries.

        Args:
            record: Dictionary containing image metadata including 'path' (relative to repo)
            repo_url: The repository URL this image belongs to

        Returns:
            The rowid of the inserted/updated record.
        """
        path = record.get("path")
        if not path:
            raise ValueError("record must include 'path'")

        # Get or create the repo_id for this URL
        repo_id = self.get_repo_id(repo_url)
        if repo_id is None:
            repo_id = self.upsert_repo(repo_url)

        # Extract special fields for column storage
        date_obs = record.get(self.DATE_OBS_KEY)
        date = record.get(self.DATE_KEY)
        imagetyp = record.get(self.IMAGETYP_KEY)

        # Separate path and special fields from metadata
        metadata = {k: v for k, v in record.items() if k != "path"}
        metadata_json = json.dumps(metadata)

        cursor = self._db.cursor()
        cursor.execute(
            f"""
            INSERT INTO {self.IMAGES_TABLE} (repo_id, path, date_obs, date, imagetyp, metadata) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id, path) DO UPDATE SET
                date_obs = excluded.date_obs,
                date = excluded.date,
                imagetyp = excluded.imagetyp,
                metadata = excluded.metadata
        """,
            (repo_id, str(path), date_obs, date, imagetyp, metadata_json),
        )

        self._db.commit()

        # Get the rowid of the inserted/updated record
        cursor.execute(
            f"SELECT id FROM {self.IMAGES_TABLE} WHERE repo_id = ? AND path = ?",
            (repo_id, str(path)),
        )
        result = cursor.fetchone()
        if result:
            return result[0]
        return cursor.lastrowid if cursor.lastrowid is not None else 0

    def search_image(self, conditions: list[SearchCondition]) -> list[ImageRow]:
        """Search for images matching the given conditions.

        Args:
            conditions: List of SearchCondition tuples, each containing:
                       - column_name: The column to filter on (e.g., 'i.date_obs', 'r.url', 'i.imagetyp')
                       - comparison_op: The comparison operator (e.g., '=', '>=', '<=')
                       - value: The value to compare against

        Returns:
            List of matching image records with relative path, repo_id, and repo_url

        Example:
            conditions = [
                SearchCondition('r.url', '=', 'file:///path/to/repo'),
                SearchCondition('i.imagetyp', '=', 'BIAS'),
                SearchCondition('i.date_obs', '>=', '2025-01-01'),
            ]
        """
        # Build SQL query with WHERE clauses from conditions
        where_clauses = []
        params = []

        for condition in conditions:
            where_clauses.append(f"{condition.column_name} {condition.comparison_op} ?")
            params.append(condition.value)

        # Build the query with JOIN to repos table
        query = f"""
            SELECT i.id, i.repo_id, i.path, i.date_obs, i.date, i.imagetyp, i.metadata, r.url as repo_url
            FROM {self.IMAGES_TABLE} i
            JOIN {self.REPOS_TABLE} r ON i.repo_id = r.id
        """
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        cursor = self._db.cursor()
        cursor.execute(query, params)

        results: list[ImageRow] = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            # Store the relative path, repo_id, and repo_url for caller
            metadata["path"] = row["path"]
            metadata["repo_id"] = row["repo_id"]
            metadata[Database.REPO_URL_KEY] = row[Database.REPO_URL_KEY]
            metadata["id"] = row["id"]

            # Add special fields back to metadata for compatibility
            if row["date_obs"]:
                metadata[self.DATE_OBS_KEY] = row["date_obs"]
            if row["date"]:
                metadata[self.DATE_KEY] = row["date"]
            if row["imagetyp"]:
                metadata[self.IMAGETYP_KEY] = row["imagetyp"]

            results.append(metadata)

        return results

    def search_session(self, conditions: list[SearchCondition] = []) -> list[SessionRow]:
        """Search for sessions matching the given conditions.

        Args:
            conditions: List of SearchCondition tuples for filtering sessions.
                       Column names should be from the sessions table. If no table prefix
                       is given (e.g., "OBJECT"), it will be prefixed with "s." automatically.

        Returns:
            List of matching session records with metadata from the reference image and repo_url
        """
        # Build WHERE clause from SearchCondition list
        where_clauses = []
        params = []

        for condition in conditions:
            # Add table prefix 's.' if not already present to avoid ambiguous column names
            column_name = condition.column_name
            if "." not in column_name:
                # Session table columns that might be ambiguous with images table
                column_name = f"s.{column_name.lower()}"
            where_clauses.append(f"{column_name} {condition.comparison_op} ?")
            params.append(condition.value)

        # Build the query with JOIN to images and repos tables to get reference image metadata and repo_url
        where_clause = ""
        if where_clauses:
            where_clause = " WHERE " + " AND ".join(where_clauses)

        query = f"""
            SELECT s.id, s.start, s.end, s.filter, s.imagetyp, s.object, s.telescop,
                   s.num_images, s.exptime_total, s.exptime, s.image_doc_id, i.metadata, r.url as repo_url
            FROM {self.SESSIONS_TABLE} s
            LEFT JOIN {self.IMAGES_TABLE} i ON s.image_doc_id = i.id
            LEFT JOIN {self.REPOS_TABLE} r ON i.repo_id = r.id
            {where_clause}
        """

        cursor = self._db.cursor()
        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            session_dict = dict(row)
            # Parse the metadata JSON if it exists
            if session_dict.get("metadata"):
                session_dict["metadata"] = json.loads(session_dict["metadata"])
            results.append(session_dict)

        return results

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

    def get_image(self, repo_url: str, path: str) -> ImageRow | None:
        """Get an image record by repo_url and relative path.

        Args:
            repo_url: The repository URL
            path: Path relative to the repository root

        Returns:
            Image record with relative path, repo_id, and repo_url, or None if not found
        """
        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT i.id, i.repo_id, i.path, i.date_obs, i.date, i.imagetyp, i.metadata, r.url as repo_url
            FROM {self.IMAGES_TABLE} i
            JOIN {self.REPOS_TABLE} r ON i.repo_id = r.id
            WHERE r.url = ? AND i.path = ?
            """,
            (repo_url, path),
        )

        row = cursor.fetchone()
        if row is None:
            return None

        metadata = json.loads(row["metadata"])
        metadata["path"] = row["path"]
        metadata["repo_id"] = row["repo_id"]
        metadata[Database.REPO_URL_KEY] = row[Database.REPO_URL_KEY]
        metadata["id"] = row["id"]

        # Add special fields back to metadata for compatibility
        if row["date_obs"]:
            metadata[self.DATE_OBS_KEY] = row["date_obs"]
        if row["date"]:
            metadata[self.DATE_KEY] = row["date"]
        if row["imagetyp"]:
            metadata[self.IMAGETYP_KEY] = row["imagetyp"]

        return metadata

    def all_images(self) -> list[ImageRow]:
        """Return all image records with relative paths, repo_id, and repo_url."""
        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT i.id, i.repo_id, i.path, i.date_obs, i.date, i.imagetyp, i.metadata, r.url as repo_url
            FROM {self.IMAGES_TABLE} i
            JOIN {self.REPOS_TABLE} r ON i.repo_id = r.id
            """
        )

        results = []
        for row in cursor.fetchall():
            metadata = json.loads(row["metadata"])
            # Return relative path, repo_id, and repo_url for caller
            metadata["path"] = row["path"]
            metadata["repo_id"] = row["repo_id"]
            metadata[Database.REPO_URL_KEY] = row[Database.REPO_URL_KEY]
            metadata["id"] = row["id"]

            # Add special fields back to metadata for compatibility
            if row["date_obs"]:
                metadata[self.DATE_OBS_KEY] = row["date_obs"]
            if row["date"]:
                metadata[self.DATE_KEY] = row["date"]
            if row["imagetyp"]:
                metadata[self.IMAGETYP_KEY] = row["imagetyp"]

            results.append(metadata)

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
                   num_images, exptime_total, exptime, image_doc_id
            FROM {self.SESSIONS_TABLE}
            WHERE id = ?
        """,
            (session_id,),
        )

        row = cursor.fetchone()
        if row is None:
            return None

        return dict(row)

    def get_session(self, to_find: dict[str, str]) -> SessionRow | None:
        """Find a session matching the given criteria.

        Searches for sessions with the same filter, image type, target, and telescope
        whose start time is within +/- 8 hours of the provided date.
        """
        date = to_find.get(get_column_name(Database.START_KEY))
        assert date
        image_type = to_find.get(get_column_name(Database.IMAGETYP_KEY))
        assert image_type

        # Convert the provided ISO8601 date string to a datetime, then
        # search for sessions with the same filter whose start time is
        # within +/- 8 hours of the provided date.
        target_dt = datetime.fromisoformat(date)
        window = timedelta(hours=8)
        start_min = (target_dt - window).isoformat()
        start_max = (target_dt + window).isoformat()

        # Since session 'start' is stored as ISO8601 strings, lexicographic
        # comparison aligns with chronological ordering for a uniform format.

        # Build WHERE clause handling NULL values properly
        # In SQL, you cannot use = with NULL, must use IS NULL
        # If a field is not in to_find, we don't filter on it at all
        where_clauses = []
        params = []

        # Handle imagetyp (required)
        where_clauses.append("imagetyp = ?")
        params.append(image_type)

        # Handle filter (optional - only filter if present in to_find)
        filter_key = get_column_name(Database.FILTER_KEY)
        filter = to_find.get(filter_key)  # filter can be the string "None"
        if filter:
            if filter is None:
                where_clauses.append("filter IS NULL")
            else:
                where_clauses.append("filter = ?")
                params.append(filter)

        # Handle object/target (optional - only filter if present in to_find)
        object_key = get_column_name(Database.OBJECT_KEY)
        target = to_find.get(object_key)
        if target:
            target = normalize_target_name(target)
            if target is None:
                where_clauses.append("object IS NULL")
            else:
                where_clauses.append("object = ?")
                params.append(target)

        # Handle telescop (optional - only filter if present in to_find)
        telescop_key = get_column_name(Database.TELESCOP_KEY)
        telescop = to_find.get(telescop_key)
        if telescop:
            if telescop is None:
                where_clauses.append("telescop IS NULL")
            else:
                where_clauses.append("telescop = ?")
                params.append(telescop)

        # Handle exptime (optional - only filter if present in to_find)
        exptime_key = get_column_name(Database.EXPTIME_KEY)
        if exptime_key in to_find:
            exptime = to_find.get(exptime_key)
            if exptime is None:
                where_clauses.append("exptime IS NULL")
            else:
                where_clauses.append("exptime = ?")
                params.append(exptime)

        # Time window
        where_clauses.append("start >= ?")
        where_clauses.append("start <= ?")
        params.extend([start_min, start_max])

        where_clause = " AND ".join(where_clauses)

        cursor = self._db.cursor()
        cursor.execute(
            f"""
            SELECT id, start, end, filter, imagetyp, object, telescop,
                   num_images, exptime_total, exptime, image_doc_id
            FROM {self.SESSIONS_TABLE}
            WHERE {where_clause}
            LIMIT 1
        """,
            params,
        )

        row = cursor.fetchone()
        if row is None:
            return None

        return dict(row)

    def upsert_session(self, new: SessionRow, existing: SessionRow | None = None) -> None:
        """Insert or update a session record."""
        cursor = self._db.cursor()

        if existing:
            # Update existing session with new data
            updated_start = min(
                new[get_column_name(Database.START_KEY)],
                existing[get_column_name(Database.START_KEY)],
            )
            updated_end = max(
                new[get_column_name(Database.END_KEY)],
                existing[get_column_name(Database.END_KEY)],
            )
            updated_num_images = existing.get(
                get_column_name(Database.NUM_IMAGES_KEY), 0
            ) + new.get(get_column_name(Database.NUM_IMAGES_KEY), 0)
            updated_exptime_total = existing.get(
                get_column_name(Database.EXPTIME_TOTAL_KEY), 0
            ) + new.get(get_column_name(Database.EXPTIME_TOTAL_KEY), 0)

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
                (start, end, filter, imagetyp, object, telescop, num_images, exptime_total, exptime, image_doc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    new[get_column_name(Database.START_KEY)],
                    new[get_column_name(Database.END_KEY)],
                    new.get(get_column_name(Database.FILTER_KEY)),
                    new[get_column_name(Database.IMAGETYP_KEY)],
                    normalize_target_name(new.get(get_column_name(Database.OBJECT_KEY))),
                    new.get(get_column_name(Database.TELESCOP_KEY)),
                    new[get_column_name(Database.NUM_IMAGES_KEY)],
                    new[get_column_name(Database.EXPTIME_TOTAL_KEY)],
                    new[get_column_name(Database.EXPTIME_KEY)],
                    new[get_column_name(Database.IMAGE_DOC_KEY)],
                ),
            )

        self._db.commit()

    # --- Lifecycle ---
    def close(self) -> None:
        self._db.close()

    # Context manager support
    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
