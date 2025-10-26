from pathlib import Path

from astroglue.database import Database


def test_database_images_table(tmp_path: Path):
    # Use a temp base dir to avoid touching real user data
    with Database(base_dir=tmp_path) as db:
        # Upsert and retrieve an image record
        rec = {"path": "/tmp/foo.fit", "FILTER": "Ha", "EXPTIME": 120.0}
        db.upsert_image(rec)

        got = db.get_image("/tmp/foo.fit")
        assert got is not None
        assert got["FILTER"] == "Ha"

        all_rows = db.all_images()
        assert len(all_rows) == 1
        assert all_rows[0]["path"] == "/tmp/foo.fit"

        # Ensure the file was written to disk under the provided base dir
        assert (tmp_path / "db.json").exists()
