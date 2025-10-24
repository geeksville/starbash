import pytest
from pathlib import Path
from astroglue.repo.manager import RepoManager
import tomlkit


def test_repo_manager_initialization():
    """
    Tests that the RepoManager correctly initializes and processes repo references.
    """

    # We use a mock Repo class to prevent file system access during this unit test.
    class MockRepo:
        def __init__(self, manager, url):
            self.manager = manager
            self.url = url
            self.config = {}  # Mock config
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


def test_repo_manager_get():
    """
    Tests that RepoManager.get() correctly retrieves values from the hierarchy
    of repository configurations, respecting precedence.
    """

    # A dictionary to hold mock file contents for our repos
    mock_files = {
        "/workspaces/astroglue/doc/toml/example/recipe-repo/astroglue.toml": """
            [repo]
            kind = "recipe-repo"
            [user]
            name = "default-user"
            """,
        "/workspaces/astroglue/doc/toml/example/config/user/astroglue.toml": """
            [repo]
            kind = "user-prefs" # This should override the value from the recipe-repo
            [user]
            email = "user@example.com"
            """,
    }

    # We use a more advanced mock Repo that simulates loading config from our mock_files
    class MockRepoWithGet:
        def __init__(self, manager, url):
            self.manager = manager
            self.url = url
            self.path = Path(url[len("file://") :])
            self.config = self._load_config()
            # The real Repo calls this to handle nested repos, but we don't need it for this test.
            # self.manager.add_all_repos(self.config, base_path=self.path)

        def _load_config(self) -> dict:
            config_path = self.path / "astroglue.toml"
            content = mock_files.get(str(config_path.resolve()))
            return tomlkit.parse(content) if content else {}

        def get(self, key: str, default=None):
            # A simple re-implementation of the real Repo.get() for our mock
            value = self.config
            for k in key.split("."):
                if not isinstance(value, dict):
                    return default
                value = value.get(k)
            return value if value is not None else default

    pytest.MonkeyPatch().setattr("astroglue.repo.manager.Repo", MockRepoWithGet)

    # Use the real appdefaults.ag.toml content
    app_defaults_text = Path(
        "/workspaces/astroglue/src/astroglue/appdefaults.ag.toml"
    ).read_text()
    repo_manager = RepoManager(app_defaults_text)

    # Test that the value from the *last* loaded repo (user prefs) is returned
    assert repo_manager.get("repo.kind") == "user-prefs"
    # Test retrieving a value that only exists in the first repo
    assert repo_manager.get("user.name") == "default-user"
    # Test retrieving a value that only exists in the second repo
    assert repo_manager.get("user.email") == "user@example.com"
    # Test a non-existent key with a default value
    assert repo_manager.get("non.existent.key", "default") == "default"
