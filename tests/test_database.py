from pathlib import Path

from starbash.database import Database


def test_database_images_table(tmp_path: Path):
    # Use a temp base dir to avoid touching real user data
    with Database(base_dir=tmp_path) as db:
        # Upsert and retrieve an image record with relative path
        rec = {"path": "foo.fit", "FILTER": "Ha", "EXPTIME": 120.0}
        repo_url = "file:///tmp"
        db.upsert_image(rec, repo_url)

        got = db.get_image(repo_url, "foo.fit")
        assert got is not None
        assert got["FILTER"] == "Ha"  # type: ignore
        assert got["path"] == "foo.fit"  # Database returns relative path
        assert got["repo_url"] == repo_url

        all_rows = db.all_images()
        assert len(all_rows) == 1
        assert all_rows[0]["path"] == "foo.fit"  # Relative path
        assert all_rows[0]["repo_url"] == repo_url

        # Ensure the file was written to disk under the provided base dir
        assert (tmp_path / "db.sqlite3").exists()
