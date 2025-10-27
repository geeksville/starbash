import os
from pathlib import Path
from platformdirs import PlatformDirs

app_name = "starbash"
app_author = "geeksville"
dirs = PlatformDirs(app_name, app_author)
config_dir = Path(dirs.user_config_dir)
data_dir = Path(dirs.user_data_dir)


def get_user_config_dir() -> Path:
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_user_data_dir() -> Path:
    os.makedirs(data_dir, exist_ok=True)
    return data_dir
