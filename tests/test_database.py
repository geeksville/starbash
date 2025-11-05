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


def test_remove_repo_basic(tmp_path: Path):
    """Test basic repo removal without any images or sessions."""
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///test/repo"
        repo_id = db.upsert_repo(repo_url)

        # Verify repo exists
        assert db.get_repo_id(repo_url) == repo_id
        assert db.len_table(Database.REPOS_TABLE) == 1

        # Remove the repo
        db.remove_repo(repo_url)

        # Verify repo is gone
        assert db.get_repo_id(repo_url) is None
        assert db.len_table(Database.REPOS_TABLE) == 0


def test_remove_repo_with_images(tmp_path: Path):
    """Test repo removal cascades to delete associated images."""
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///test/repo"

        # Add multiple images to the repo
        db.upsert_image({"path": "image1.fit", "FILTER": "Ha"}, repo_url)
        db.upsert_image({"path": "image2.fit", "FILTER": "OIII"}, repo_url)
        db.upsert_image({"path": "image3.fit", "FILTER": "SII"}, repo_url)

        # Verify images exist
        assert db.len_table(Database.IMAGES_TABLE) == 3
        assert db.get_image(repo_url, "image1.fit") is not None

        # Remove the repo
        db.remove_repo(repo_url)

        # Verify repo and all images are gone
        assert db.get_repo_id(repo_url) is None
        assert db.len_table(Database.REPOS_TABLE) == 0
        assert db.len_table(Database.IMAGES_TABLE) == 0
        assert db.get_image(repo_url, "image1.fit") is None


def test_remove_repo_with_sessions(tmp_path: Path):
    """Test repo removal cascades to delete sessions referencing its images."""
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///test/repo"

        # Add an image
        image_rec = {
            "path": "light.fit",
            "DATE-OBS": "2025-01-01T20:00:00",
            "FILTER": "Ha",
            "IMAGETYP": "Light Frame",
            "OBJECT": "M42",
            "TELESCOP": "test-scope",
            "EXPTIME": 120.0,
        }
        image_id = db.upsert_image(image_rec, repo_url)

        # Create a session referencing this image
        session_rec = {
            Database.START_KEY: "2025-01-01T20:00:00",
            Database.END_KEY: "2025-01-01T21:00:00",
            Database.FILTER_KEY: "Ha",
            Database.IMAGETYP_KEY: "Light Frame",
            Database.OBJECT_KEY: "M42",
            Database.TELESCOP_KEY: "test-scope",
            Database.NUM_IMAGES_KEY: 1,
            Database.EXPTIME_TOTAL_KEY: 120.0,
            Database.IMAGE_DOC_KEY: image_id,
        }
        db.upsert_session(session_rec)

        # Verify session exists
        assert db.len_table(Database.SESSIONS_TABLE) == 1

        # Remove the repo
        db.remove_repo(repo_url)

        # Verify repo, images, and sessions are all gone
        assert db.get_repo_id(repo_url) is None
        assert db.len_table(Database.REPOS_TABLE) == 0
        assert db.len_table(Database.IMAGES_TABLE) == 0
        assert db.len_table(Database.SESSIONS_TABLE) == 0


def test_remove_repo_preserves_other_repos(tmp_path: Path):
    """Test that removing one repo doesn't affect other repos."""
    with Database(base_dir=tmp_path) as db:
        repo1_url = "file:///test/repo1"
        repo2_url = "file:///test/repo2"

        # Add images to both repos
        db.upsert_image({"path": "image1.fit", "FILTER": "Ha"}, repo1_url)
        db.upsert_image({"path": "image2.fit", "FILTER": "OIII"}, repo2_url)

        # Verify both repos and images exist
        assert db.len_table(Database.REPOS_TABLE) == 2
        assert db.len_table(Database.IMAGES_TABLE) == 2

        # Remove first repo
        db.remove_repo(repo1_url)

        # Verify repo1 and its image are gone, but repo2 remains
        assert db.get_repo_id(repo1_url) is None
        assert db.get_repo_id(repo2_url) is not None
        assert db.len_table(Database.REPOS_TABLE) == 1
        assert db.len_table(Database.IMAGES_TABLE) == 1
        assert db.get_image(repo1_url, "image1.fit") is None
        assert db.get_image(repo2_url, "image2.fit") is not None


def test_remove_repo_nonexistent(tmp_path: Path):
    """Test that removing a non-existent repo doesn't raise an error."""
    with Database(base_dir=tmp_path) as db:
        # Try to remove a repo that doesn't exist
        db.remove_repo("file:///nonexistent/repo")

        # Should not raise an error and tables should be empty
        assert db.len_table(Database.REPOS_TABLE) == 0
        assert db.len_table(Database.IMAGES_TABLE) == 0
        assert db.len_table(Database.SESSIONS_TABLE) == 0


def test_remove_repo_with_multiple_sessions(tmp_path: Path):
    """Test repo removal with multiple sessions referencing different images."""
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///test/repo"

        # Add multiple images
        image1_rec = {
            "path": "light1.fit",
            "DATE-OBS": "2025-01-01T20:00:00",
            "FILTER": "Ha",
            "IMAGETYP": "Light Frame",
            "OBJECT": "M42",
            "TELESCOP": "test-scope",
            "EXPTIME": 120.0,
        }
        image1_id = db.upsert_image(image1_rec, repo_url)

        image2_rec = {
            "path": "light2.fit",
            "DATE-OBS": "2025-01-02T20:00:00",
            "FILTER": "OIII",
            "IMAGETYP": "Light Frame",
            "OBJECT": "M42",
            "TELESCOP": "test-scope",
            "EXPTIME": 120.0,
        }
        image2_id = db.upsert_image(image2_rec, repo_url)

        # Create sessions referencing each image
        session1_rec = {
            Database.START_KEY: "2025-01-01T20:00:00",
            Database.END_KEY: "2025-01-01T21:00:00",
            Database.FILTER_KEY: "Ha",
            Database.IMAGETYP_KEY: "Light Frame",
            Database.OBJECT_KEY: "M42",
            Database.TELESCOP_KEY: "test-scope",
            Database.NUM_IMAGES_KEY: 1,
            Database.EXPTIME_TOTAL_KEY: 120.0,
            Database.IMAGE_DOC_KEY: image1_id,
        }
        db.upsert_session(session1_rec)

        session2_rec = {
            Database.START_KEY: "2025-01-02T20:00:00",
            Database.END_KEY: "2025-01-02T21:00:00",
            Database.FILTER_KEY: "OIII",
            Database.IMAGETYP_KEY: "Light Frame",
            Database.OBJECT_KEY: "M42",
            Database.TELESCOP_KEY: "test-scope",
            Database.NUM_IMAGES_KEY: 1,
            Database.EXPTIME_TOTAL_KEY: 120.0,
            Database.IMAGE_DOC_KEY: image2_id,
        }
        db.upsert_session(session2_rec)

        # Verify both sessions exist
        assert db.len_table(Database.SESSIONS_TABLE) == 2

        # Remove the repo
        db.remove_repo(repo_url)

        # Verify all data is cleaned up
        assert db.len_table(Database.REPOS_TABLE) == 0
        assert db.len_table(Database.IMAGES_TABLE) == 0
        assert db.len_table(Database.SESSIONS_TABLE) == 0
