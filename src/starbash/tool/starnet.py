

import configparser
import logging
from pathlib import Path

from platformdirs import PlatformDirs

from starbash.tool.siril import SirilTool

logger = logging.getLogger(__name__)


class StarnetTool(SirilTool):
    """Expose Starnet as a tool (but really just via Siril, since Starnet is a Siril plugin)."""

    def __init__(self) -> None:
        super().__init__()
        self.name = "starnet"
        self._starnet_available: bool | None = None  # cached result of is_available probe

    @staticmethod
    def _siril_config_dir() -> Path:
        """Location of Siril's own config directory (OS-appropriate)."""
        return Path(PlatformDirs("siril").user_config_dir)

    def _starnet_configured(self) -> bool:
        """True if any Siril config file has a non-empty ``starnet_exe`` in ``[core]``."""
        config_dir = self._siril_config_dir()
        # Siril versions its config file (e.g. config.1.4.ini); check whichever exist.
        for ini_path in sorted(config_dir.glob("config.*.ini")):
            parser = configparser.ConfigParser()
            try:
                parser.read(ini_path)
            except (OSError, configparser.Error):
                continue
            if parser.get("core", "starnet_exe", fallback="").strip():
                return True
        return False

    @property
    def is_available(self) -> bool:
        """Available only when Siril is installed and the StarNet plugin is configured."""
        if self._starnet_available is None:
            if not super().is_available:
                # Siril itself is missing; base class handles user messaging.
                self._starnet_available = False
            elif not self._starnet_configured():
                logger.warning(
                    "StarNet is not enabled in Siril. Set the StarNet executable in "
                    "Siril's settings (Preferences > Miscellaneous) to use star removal. "
                    "You can download StarNet from https://starnetastro.com/cli-tools/"
                )
                self._starnet_available = False
            else:
                self._starnet_available = True
        return self._starnet_available
