from pathlib import Path

import pytest
import tomlkit

from repo import RepoManager


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
    # Use as_posix() to convert Windows paths to forward slashes for TOML compatibility
    (test_repo_path / "starbash.toml").write_text(
        f"""
        [repo]
        kind = "test"

        [[repo-ref]]
        dir = "{ref_repo1_path.as_posix()}"

        [[repo-ref]]
        dir = "{ref_repo2_path.as_posix()}"
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
    kinds = [r.kind() for r in repo_manager.repos]
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
        kind = "recipe"
        [user]
        name = "default-user"
        """
    )

    user_prefs_path = tmp_path / "user-prefs"
    user_prefs_path.mkdir()
    (user_prefs_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "preferences"
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
    assert repo_manager.get("repo.kind") == "preferences"
    assert repo_manager.get("user.name") == "default-user"
    assert repo_manager.get("user.email") == "user@example.com"
    assert repo_manager.get("non.existent.key", "default") == "default"


def test_repo_with_direct_toml_file(tmp_path: Path):
    """
    Tests that a Repo can be initialized with a direct .toml file URL
    instead of a directory containing starbash.toml.
    """
    # Create a custom named TOML file
    custom_toml = tmp_path / "my-custom-config.toml"
    custom_toml.write_text(
        """
        [repo]
        kind = "custom"
        [settings]
        value = "from-direct-file"
        """
    )

    # Initialize RepoManager and add the direct .toml file
    repo_manager = RepoManager()
    repo_manager.add_repo(f"file://{custom_toml}")

    # Verify the repo was loaded correctly
    assert len(repo_manager.repos) >= 1
    urls = [r.url for r in repo_manager.repos]
    assert f"file://{custom_toml}" in urls

    # Verify we can get values from the directly loaded .toml file
    assert repo_manager.get("repo.kind") == "custom"
    assert repo_manager.get("settings.value") == "from-direct-file"


def test_repo_direct_toml_vs_directory(tmp_path: Path):
    """
    Tests that both directory-based and direct .toml file repos work correctly
    and can coexist in the same RepoManager.
    """
    # Create a directory-based repo
    dir_repo_path = tmp_path / "dir-repo"
    dir_repo_path.mkdir()
    (dir_repo_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "directory"
        [settings]
        source = "dir"
        """
    )

    # Create a direct .toml file repo
    file_repo_path = tmp_path / "file-repo.toml"
    file_repo_path.write_text(
        """
        [repo]
        kind = "file"
        [settings]
        source = "file"
        """
    )

    # Initialize RepoManager and add both repos
    repo_manager = RepoManager()
    repo_manager.add_repo(f"file://{dir_repo_path}")
    repo_manager.add_repo(f"file://{file_repo_path}")

    # Verify both repos are loaded
    assert len(repo_manager.repos) >= 2
    kinds = [r.kind() for r in repo_manager.repos]
    assert "directory" in kinds
    assert "file" in kinds

    # Verify precedence - last added (file-based) should win
    assert repo_manager.get("repo.kind") == "file"
    assert repo_manager.get("settings.source") == "file"


def test_repo_direct_toml_resolve_path(tmp_path: Path):
    """
    Tests that resolve_path() works correctly for direct .toml file repos,
    resolving paths relative to the parent directory of the .toml file.
    """
    # Create a direct .toml file repo with a sibling file
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
        [repo]
        kind = "test"
        """
    )

    sibling_file = tmp_path / "data.txt"
    sibling_file.write_text("test data")

    # Create a repo from the direct .toml file
    from repo.repo import Repo

    repo = Repo(f"file://{config_file}")

    # Verify that resolve_path resolves relative to the parent directory
    resolved = repo.resolve_path("data.txt")
    assert resolved == sibling_file
    assert resolved.read_text() == "test data"


def test_repo_config_url_property(tmp_path: Path):
    """
    Tests that the config_url property returns the correct URL to the config file
    for both directory repos and direct .toml file repos.
    """
    from repo.repo import Repo

    # Test 1: Directory repo (should append /starbash.toml)
    dir_repo_path = tmp_path / "dir-repo"
    dir_repo_path.mkdir()
    (dir_repo_path / "starbash.toml").write_text(
        """
        [repo]
        kind = "directory"
        """
    )

    dir_repo = Repo(f"file://{dir_repo_path}")
    expected_dir_url = f"file://{dir_repo_path}/starbash.toml"
    assert dir_repo.config_url == expected_dir_url

    # Test 2: Direct .toml file repo (should return URL as-is)
    toml_file = tmp_path / "custom.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "direct"
        """
    )

    toml_repo = Repo(f"file://{toml_file}")
    expected_toml_url = f"file://{toml_file}"
    assert toml_repo.config_url == expected_toml_url

    # Test 3: pkg:// URL (directory form)
    pkg_repo = Repo("pkg://defaults")
    assert pkg_repo.config_url == "pkg://defaults/starbash.toml"

    # Test 4: pkg:// URL (direct .toml file)
    pkg_toml_repo = Repo("pkg://defaults/config.toml")
    assert pkg_toml_repo.config_url == "pkg://defaults/config.toml"
