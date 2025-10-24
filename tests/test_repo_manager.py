import pytest
from pathlib import Path
from astroglue.repo.manager import RepoManager


def test_repo_manager_initialization(monkeypatch):
    """
    Tests that the RepoManager correctly initializes and processes repo references.
    """

    # We use a mock Repo class to prevent file system access during this unit test.
    class MockRepo:
        def __init__(self, _manager, url):
            self.url = url
            # The real Repo.__init__ calls manager.add_all_repos, which can lead to
            # recursion. We don't need to test that behavior here, so we do nothing.

    # Use the monkeypatch fixture to replace the real Repo class with our mock.
    # The fixture ensures this change is reverted after the test function finishes.
    monkeypatch.setattr("astroglue.repo.manager.Repo", MockRepo)

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


def test_repo_manager_get_with_real_repos(tmp_path: Path):
    """
    Tests that RepoManager.get() correctly retrieves values from the hierarchy
    of repository configurations using the real Repo class, respecting precedence.
    """
    # 1. Create temporary directories and config files for our test repos
    recipe_repo_path = tmp_path / "recipe-repo"
    recipe_repo_path.mkdir()
    (recipe_repo_path / "astroglue.toml").write_text(
        """
        [repo]
        kind = "recipe-repo"
        [user]
        name = "default-user"
        """
    )

    user_prefs_path = tmp_path / "user-prefs"
    user_prefs_path.mkdir()
    (user_prefs_path / "astroglue.toml").write_text(
        """
        [repo]
        kind = "user-prefs" # This should override the value from the recipe-repo
        [user]
        email = "user@example.com"
        """
    )

    # 2. Create a dynamic appdefaults content pointing to our temporary repos
    app_defaults_text = f"""
    [[repo.ref]]
    dir = "{recipe_repo_path}"

    [[repo.ref]]
    dir = "{user_prefs_path}"
    """

    # 3. Initialize the RepoManager, which will now use the real Repo class
    repo_manager = RepoManager(app_defaults_text)

    # 4. Assert that the values are retrieved correctly, respecting precedence
    assert repo_manager.get("repo.kind") == "user-prefs"
    assert repo_manager.get("user.name") == "default-user"
    assert repo_manager.get("user.email") == "user@example.com"
    assert repo_manager.get("non.existent.key", "default") == "default"
