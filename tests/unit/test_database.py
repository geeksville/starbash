from pathlib import Path
from typing import Any

import pytest

from starbash.database import Database, RepoRemoval, get_column_name


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


def test_update_images_metadata_merges_without_changing_image_fields(tmp_path: Path):
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///tmp"
        image_id = db.upsert_image(
            {
                "path": "foo.fit",
                "DATE-OBS": "2025-01-01T00:00:00",
                "IMAGETYP": "Light Frame",
                "KEEP": "yes",
            },
            repo_url,
        )

        assert db.update_images_metadata({image_id: {"FWHM": 3.2, "Stars": 42}}) == 1
        image = db.get_image(repo_url, "foo.fit")
        assert image is not None
        assert image["KEEP"] == "yes"
        assert image["FWHM"] == 3.2
        assert image["Stars"] == 42
        assert image["DATE-OBS"] == "2025-01-01T00:00:00"
        assert image["IMAGETYP"] == "Light Frame"


def test_update_images_metadata_rolls_back_unknown_id(tmp_path: Path):
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///tmp"
        image_id = db.upsert_image({"path": "foo.fit", "KEEP": "yes"}, repo_url)

        with pytest.raises(ValueError, match="does not exist"):
            db.update_images_metadata({image_id: {"FWHM": 3.2}, 99999: {"FWHM": 4.2}})

        image = db.get_image(repo_url, "foo.fit")
        assert image is not None
        assert "FWHM" not in image


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
            get_column_name(Database.START_KEY): "2025-01-01T20:00:00",
            get_column_name(Database.END_KEY): "2025-01-01T21:00:00",
            get_column_name(Database.FILTER_KEY): "Ha",
            get_column_name(Database.IMAGETYP_KEY): "Light Frame",
            get_column_name(Database.OBJECT_KEY): "M42",
            get_column_name(Database.TELESCOP_KEY): "test-scope",
            get_column_name(Database.NUM_IMAGES_KEY): 1,
            get_column_name(Database.EXPTIME_TOTAL_KEY): 120.0,
            get_column_name(Database.EXPTIME_KEY): 120.0,
            get_column_name(Database.IMAGE_DOC_KEY): image_id,
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
        assert db.remove_repo("file:///nonexistent/repo") == RepoRemoval()

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
            get_column_name(Database.START_KEY): "2025-01-01T20:00:00",
            get_column_name(Database.END_KEY): "2025-01-01T21:00:00",
            get_column_name(Database.FILTER_KEY): "Ha",
            get_column_name(Database.IMAGETYP_KEY): "Light Frame",
            get_column_name(Database.OBJECT_KEY): "M42",
            get_column_name(Database.TELESCOP_KEY): "test-scope",
            get_column_name(Database.NUM_IMAGES_KEY): 1,
            get_column_name(Database.EXPTIME_TOTAL_KEY): 120.0,
            get_column_name(Database.EXPTIME_KEY): 120.0,
            get_column_name(Database.IMAGE_DOC_KEY): image1_id,
        }
        db.upsert_session(session1_rec)

        session2_rec = {
            get_column_name(Database.START_KEY): "2025-01-02T20:00:00",
            get_column_name(Database.END_KEY): "2025-01-02T21:00:00",
            get_column_name(Database.FILTER_KEY): "OIII",
            get_column_name(Database.IMAGETYP_KEY): "Light Frame",
            get_column_name(Database.OBJECT_KEY): "M42",
            get_column_name(Database.TELESCOP_KEY): "test-scope",
            get_column_name(Database.NUM_IMAGES_KEY): 1,
            get_column_name(Database.EXPTIME_TOTAL_KEY): 120.0,
            get_column_name(Database.EXPTIME_KEY): 120.0,
            get_column_name(Database.IMAGE_DOC_KEY): image2_id,
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


def test_session_telescop_matches_case_insensitively(tmp_path: Path):
    """``telescop`` uses a NOCASE collation.

    Regression: the column was declared ``COLLATENOCASE`` (no space), which SQLite
    silently accepts as part of the type name - so telescope matching was
    case-sensitive while its ``filter``/``imagetyp`` neighbours were not.
    """
    with Database(base_dir=tmp_path) as db:
        db.upsert_session(
            {
                get_column_name(Database.START_KEY): "2025-01-01T20:00:00",
                get_column_name(Database.END_KEY): "2025-01-01T21:00:00",
                get_column_name(Database.FILTER_KEY): "Ha",
                get_column_name(Database.IMAGETYP_KEY): "Light Frame",
                get_column_name(Database.OBJECT_KEY): "M42",
                get_column_name(Database.TELESCOP_KEY): "RigOne",
                get_column_name(Database.NUM_IMAGES_KEY): 1,
                get_column_name(Database.EXPTIME_TOTAL_KEY): 120.0,
                get_column_name(Database.EXPTIME_KEY): 120.0,
                get_column_name(Database.IMAGE_DOC_KEY): None,
            }
        )

        # The same telescope in a different case must still match.
        found = db.get_session(
            {
                get_column_name(Database.START_KEY): "2025-01-01T20:00:00",
                get_column_name(Database.IMAGETYP_KEY): "Light Frame",
                get_column_name(Database.TELESCOP_KEY): "rigone",
            }
        )
        assert found is not None
        assert found[get_column_name(Database.TELESCOP_KEY)] == "RigOne"


# --- what a repo removal drops from the index ------------------------------
def _index_frame(
    db: Database,
    repo_url: str,
    path: str,
    date_obs: str,
    *,
    imagetyp: str = "Light Frame",
    filter: str = "Ha",
    object: str = "M42",
    telescop: str = "test-scope",
    exptime: float = 120.0,
) -> int:
    """Index one frame and fold it into its session, the way :class:`Starbash` does.

    Mirrors ``Starbash.add_image_and_session``/``_add_session``, so the sessions
    under test are built the way the real index builds them.
    """
    record: dict[str, Any] = {
        "path": path,
        Database.DATE_OBS_KEY: date_obs,
        Database.IMAGETYP_KEY: imagetyp,
        Database.EXPTIME_KEY: exptime,
        Database.FILTER_KEY: filter,
        Database.OBJECT_KEY: object,
        Database.TELESCOP_KEY: telescop,
    }
    image_id = db.upsert_image(record, repo_url)

    new = {
        get_column_name(Database.START_KEY): date_obs,
        get_column_name(Database.END_KEY): date_obs,
        get_column_name(Database.IMAGE_DOC_KEY): image_id,
        get_column_name(Database.IMAGETYP_KEY): imagetyp,
        get_column_name(Database.FILTER_KEY): filter,
        get_column_name(Database.OBJECT_KEY): object,
        get_column_name(Database.TELESCOP_KEY): telescop,
        get_column_name(Database.NUM_IMAGES_KEY): 1,
        get_column_name(Database.EXPTIME_TOTAL_KEY): exptime,
        get_column_name(Database.EXPTIME_KEY): exptime,
    }
    db.upsert_session(new, existing=db.get_session(new))
    return image_id


def test_remove_repo_reports_what_it_dropped(tmp_path: Path):
    """The removal reports how many rows went, so both front ends can say so."""
    with Database(base_dir=tmp_path) as db:
        repo_url = "file:///test/repo"

        _index_frame(db, repo_url, "one.fit", "2025-01-01T20:00:00")
        _index_frame(db, repo_url, "two.fit", "2025-01-01T20:05:00")
        # A frame with no DATE-OBS never builds a session, so it counts as an image only.
        db.upsert_image({"path": "headerless.fit"}, repo_url)

        removal = db.remove_repo(repo_url)

        assert removal == RepoRemoval(images=3, sessions=1)
        assert db.get_repo_id(repo_url) is None
        assert db.len_table(Database.IMAGES_TABLE) == 0
        assert db.len_table(Database.SESSIONS_TABLE) == 0
        assert db.search_image([]) == []
        assert db.search_session() == []


def test_remove_repo_leaves_another_repos_session_alone(tmp_path: Path):
    """Only the removed repo's images and sessions go; a second repo is untouched."""
    with Database(base_dir=tmp_path) as db:
        gone = "file:///test/gone"
        kept = "file:///test/kept"

        # A different night, so the two repos hold separate sessions.
        _index_frame(db, gone, "g1.fit", "2025-01-01T20:00:00")
        _index_frame(db, kept, "k1.fit", "2025-02-01T20:00:00")
        _index_frame(db, kept, "k2.fit", "2025-02-01T20:05:00")

        sessions = db.search_session()
        assert len(sessions) == 2
        kept_session = next(s for s in sessions if s["start"].startswith("2025-02"))

        removal = db.remove_repo(gone)

        assert removal == RepoRemoval(images=1, sessions=1)
        untouched = db.get_session_by_id(kept_session["id"])
        assert untouched == {
            k: v for k, v in kept_session.items() if k not in ("metadata", "repo_url")
        }
        assert db.len_table(Database.IMAGES_TABLE) == 2
        assert db.get_image(kept, "k1.fit") is not None


def test_repo_removal_summary():
    """The summary line both front ends print after a removal."""
    assert RepoRemoval().summary() == "No indexed files or sessions were affected."
    assert RepoRemoval(images=3).summary() == "Removed 3 indexed image(s)."
    assert RepoRemoval(sessions=2).summary() == "Removed 2 session(s)."
    assert (
        RepoRemoval(images=3, sessions=2).summary()
        == "Removed 3 indexed image(s) and 2 session(s)."
    )
