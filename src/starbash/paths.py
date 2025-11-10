import os
from pathlib import Path

from platformdirs import PlatformDirs

app_name = "starbash"
app_author = "geeksville"
dirs = PlatformDirs(app_name, app_author)
config_dir = Path(dirs.user_config_dir)
data_dir = Path(dirs.user_data_dir)
cache_dir = Path(dirs.user_cache_dir)
documents_dir = Path(dirs.user_documents_dir) / "starbash"

# These can be overridden for testing
_override_config_dir: Path | None = None
_override_data_dir: Path | None = None
_override_cache_dir: Path | None = None
_override_documents_dir: Path | None = None


def set_test_directories(
    config_dir_override: Path | None = None,
    data_dir_override: Path | None = None,
    cache_dir_override: Path | None = None,
    documents_dir_override: Path | None = None,
) -> None:
    """Set override directories for testing. Used by test fixtures to isolate test data."""
    global _override_config_dir, _override_data_dir, _override_cache_dir, _override_documents_dir
    _override_config_dir = config_dir_override
    _override_data_dir = data_dir_override
    _override_cache_dir = cache_dir_override
    _override_documents_dir = documents_dir_override


def get_user_config_dir() -> Path:
    """Get the user config directory. Returns test override if set, otherwise the real user directory."""
    dir_to_use = _override_config_dir if _override_config_dir is not None else config_dir
    os.makedirs(dir_to_use, exist_ok=True)
    return dir_to_use


def get_user_config_path() -> Path:
    """Returns the path to the user config file (starbash.toml)."""
    from repo import repo_suffix  # Lazy import to avoid circular dependency

    config_dir = get_user_config_dir()
    return config_dir / repo_suffix


def get_user_data_dir() -> Path:
    """Get the user data directory. Returns test override if set, otherwise the real user directory."""
    dir_to_use = _override_data_dir if _override_data_dir is not None else data_dir
    os.makedirs(dir_to_use, exist_ok=True)
    return dir_to_use


def get_user_cache_dir() -> Path:
    """Get the user cache directory. Returns test override if set, otherwise the real user directory."""
    dir_to_use = _override_cache_dir if _override_cache_dir is not None else cache_dir
    os.makedirs(dir_to_use, exist_ok=True)
    return dir_to_use


def get_user_documents_dir() -> Path:
    """Get the user documents directory. Returns test override if set, otherwise the real user directory."""
    dir_to_use = _override_documents_dir if _override_documents_dir is not None else documents_dir
    os.makedirs(dir_to_use, exist_ok=True)
    return dir_to_use
