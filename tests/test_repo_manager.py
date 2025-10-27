from pathlib import Path
import pytest
import tomlkit
from starbash.repo.manager import RepoManager


def test_repo_manager_initialization(monkeypatch):
    """
    Tests that the RepoManager correctly initializes and processes repo references.
    """

    # We use a mock Repo class to prevent file system access during this unit test.
    class MockRepo:
        def __init__(self, manager, url, config: str | None = None):
            self.url = url
            self.config = tomlkit.parse(config) if config else {}
            # Simulate the real Repo behavior minimally: if a config string is provided,
            # parse it and ask the manager to add referenced repos.
            if config:
                manager.add_all_repos(tomlkit.parse(config))

    # Use the monkeypatch fixture to replace the real Repo class with our mock.
    # The fixture ensures this change is reverted after the test function finishes.
    monkeypatch.setattr("starbash.repo.manager.Repo", MockRepo)

    app_defaults_text = """
    [[repo-ref]]
    url = "https://github.com/user/recipes"

    [[repo-ref]]
    dir = "test_data/my_raws"
    """

    repo_manager = RepoManager(app_defaults_text)

    # With the root repo plus two referenced repos, we expect three entries.
    assert len(repo_manager.repos) == 3
    # Order-insensitive presence checks across all repos
    urls = [r.url for r in repo_manager.repos]
    assert "pkg://starbash-defaults" in urls
    assert "https://github.com/user/recipes" in urls
    assert any(
        u.startswith("file://") and u.endswith("/starbash/test_data/my_raws")
        for u in urls
    )


def test_repo_manager_get_with_real_repos(tmp_path: Path):
    """
    Tests that RepoManager.get() correctly retrieves values from the hierarchy
    of repository configurations using the real Repo class, respecting precedence.
    """
    # 1. Create temporary directories and config files for our test repos
    recipe_repo_path = tmp_path / "recipe-repo"
    recipe_repo_path.mkdir()
    (recipe_repo_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "recipe-repo"
        [user]
        name = "default-user"
        """
    )

    user_prefs_path = tmp_path / "user-prefs"
    user_prefs_path.mkdir()
    (user_prefs_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "user-prefs" # This should override the value from the recipe-repo
        [user]
        email = "user@example.com"
        """
    )

    # 2. Create a dynamic appdefaults content pointing to our temporary repos
    app_defaults_text = f"""
    [[repo-ref]]
    dir = "{recipe_repo_path}"

    [[repo-ref]]
    dir = "{user_prefs_path}"
    """

    # 3. Initialize the RepoManager, which will now use the real Repo class
    repo_manager = RepoManager(app_defaults_text)

    # 4. Assert that the values are retrieved correctly, respecting precedence
    assert repo_manager.get("repo.kind") == "user-prefs"
    assert repo_manager.get("user.name") == "default-user"
    assert repo_manager.get("user.email") == "user@example.com"
    assert repo_manager.get("non.existent.key", "default") == "default"
