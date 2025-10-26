from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tinydb import TinyDB, Query, table
from platformdirs import PlatformDirs


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
            app_name = "astroglue"
            app_author = "geeksville"
            dirs = PlatformDirs(app_name, app_author)
            data_dir = Path(dirs.user_data_dir)
        else:
            data_dir = base_dir

        db_filename = "db.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / db_filename

        # Open TinyDB JSON store
        self._db = TinyDB(self.db_path)

        # Public handle to the images table
        self.images = self._db.table("images")

    def add_from_fits(self, file_path: Path, headers: dict[str, Any]) -> None:
        # FIXME, currently we don't use this whitelist - we are just dumping everything
        whitelist = set(
            [
                "INSTRUME",
                "FILTER",
                "TELESCOP",
                "IMAGETYP",
                "DATE-OBS",
                "DATE",
                "EXPTIME",
                "FWHEEL",
                "OBJECT",
                "OBJCTRA",
                "OBJCTDEC",
                "OBJCTROT",
                "FOCPOS",
            ]
        )

        data = {}
        data.update(headers)
        data["path"] = str(file_path)
        self.upsert_image(data)

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

    def get_image(self, path: str) -> table.Document | list[table.Document] | None:
        Image = Query()
        return self.images.get(Image.path == path)

    def all_images(self) -> list[dict[str, Any]]:
        return list(self.images.all())

    # --- Lifecycle ---
    def close(self) -> None:
        self._db.close()

    # Context manager support
    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
