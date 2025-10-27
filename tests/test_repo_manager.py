from pathlib import Path
import pytest
import tomlkit
from starbash.repo.manager import RepoManager


def test_repo_manager_initialization(monkeypatch, tmp_path: Path):
    """
    Tests that the RepoManager correctly initializes and processes repo references.
    """
    # Create a test repo with multiple repo-ref entries
    test_repo_path = tmp_path / "test-repo"
    test_repo_path.mkdir()
    
    # Create referenced repo directories
    ref_repo1_path = tmp_path / "recipes"
    ref_repo1_path.mkdir()
    (ref_repo1_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "recipes"
        """
    )
    
    ref_repo2_path = tmp_path / "my_raws"
    ref_repo2_path.mkdir()
    (ref_repo2_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "raws"
        """
    )

    # Write test repo config with repo-refs
    (test_repo_path / "starbash.toml").write_text(
        f"""
        [repo]
        kind = "test"
        
        [[repo-ref]]
        dir = "{ref_repo1_path}"
        
        [[repo-ref]]
        dir = "{ref_repo2_path}"
        """
    )

    # Initialize RepoManager and add the test repo
    repo_manager = RepoManager()
    repo_manager.add_repo(f"file://{test_repo_path}")

    # We expect the test repo plus the two referenced repos
    assert len(repo_manager.repos) >= 3
    urls = [r.url for r in repo_manager.repos]
    assert f"file://{test_repo_path}" in urls
    assert f"file://{ref_repo1_path}" in urls
    assert f"file://{ref_repo2_path}" in urls
    
    # Verify we can get values from all repos
    kinds = [r.kind for r in repo_manager.repos]
    assert "test" in kinds
    assert "recipes" in kinds
    assert "raws" in kinds


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
        kind = "user-prefs"
        [user]
        email = "user@example.com"
        """
    )

    # 2. Initialize the RepoManager and add repos in order
    repo_manager = RepoManager()
    repo_manager.add_repo(f"file://{recipe_repo_path}")
    repo_manager.add_repo(f"file://{user_prefs_path}")

    # 3. Assert that the values are retrieved correctly, respecting precedence
    # Last repo added wins for .get()
    assert repo_manager.get("repo.kind") == "user-prefs"
    assert repo_manager.get("user.name") == "default-user"
    assert repo_manager.get("user.email") == "user@example.com"
    assert repo_manager.get("non.existent.key", "default") == "default"
