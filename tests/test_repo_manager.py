import pytest
from pathlib import Path
from astroglue.repo.manager import RepoManager


def test_repo_manager_initialization():
    """
    Tests that the RepoManager correctly initializes and processes repo references.
    """

    # We use a mock Repo class to prevent file system access during this unit test.
    class MockRepo:
        def __init__(self, manager, url):
            self.manager = manager
            self.url = url
            # In the real Repo class, this is where it would load the repo's config.
            # We are keeping it simple here to just test the manager's parsing.

    # Temporarily replace the real Repo class with our mock during the test
    pytest.MonkeyPatch().setattr("astroglue.repo.manager.Repo", MockRepo)

    app_defaults_text = """
    [[repo.ref]]
    url = "https://github.com/user/recipes"

    [[repo.ref]]
    dir = "test_data/my_raws"
    """

    repo_manager = RepoManager(app_defaults_text)

    assert len(repo_manager.repos) == 2
    assert repo_manager.repos[0].url == "https://github.com/user/recipes"
    assert repo_manager.repos[1].url.startswith("file://")
    assert repo_manager.repos[1].url.endswith("/astroglue/test_data/my_raws")
