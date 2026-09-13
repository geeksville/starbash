import configparser
import logging
import os
import shutil
from pathlib import Path

from platformdirs import PlatformDirs

from starbash.tool.base import ToolSeverity
from starbash.tool.siril import SIRIL_INSTALL_URL, SirilTool

logger = logging.getLogger(__name__)

__all__ = ["StarnetTool"]

#: Where the user can obtain StarNet (the CLI build Siril can call).
STARNET_INSTALL_URL = "https://starnetastro.com/cli-tools/"


def _starnet_exe_usable(configured: str) -> bool:
    """Whether a Siril ``starnet_exe`` setting points at something runnable.

    Siril's setting is either an explicit path - what Starbash writes when it
    finds ``starnet2`` on the PATH - or a bare command name Siril resolves
    itself.  An explicit path is only usable while the file is still there, and
    that file can go away (StarNet removed, upgraded or moved) while the setting
    lingers, leaving Siril just as broken as an unconfigured one.  Only
    existence is required, not the executable bit: a false "StarNet is missing"
    for a binary StarNet's own installer left non-executable would be worse than
    staying quiet.
    """
    if os.sep in configured or (os.altsep is not None and os.altsep in configured):
        return Path(configured).expanduser().is_file()
    return shutil.which(configured) is not None


class StarnetTool(SirilTool):
    """Expose Starnet as a tool (but really just via Siril, since Starnet is a Siril plugin)."""

    def __init__(self) -> None:
        super().__init__()
        self.name = "starnet"
        # Star removal is used by most workflows but plenty of people stack without
        # it, so this is recommended (warn, but ignorable) rather than required.
        self.severity = ToolSeverity.RECOMMENDED
        self.install_url = STARNET_INSTALL_URL
        self._starnet_available: bool | None = None  # cached result of is_available probe
        #: The configured ``starnet_exe`` that no longer exists, if we found one.
        self._starnet_dangling: str | None = None

    @staticmethod
    def _siril_config_dir() -> Path:
        """Location of Siril's own config directory (OS-appropriate)."""
        return Path(PlatformDirs("siril").user_config_dir)

    def _starnet_configured(self) -> bool:
        """Ensure Siril has a usable ``starnet_exe`` and report whether it is configured."""
        config_dir = self._siril_config_dir()
        # Siril versions its config file (e.g. config.1.4.ini); check whichever exist.
        ini_paths = sorted(config_dir.glob("config.*.ini"))
        dangling: str | None = None
        saw_value = False
        for ini_path in ini_paths:
            parser = configparser.ConfigParser()
            try:
                parser.read(ini_path)
            except (OSError, configparser.Error):
                continue
            configured = parser.get("core", "starnet_exe", fallback="").strip()
            if not configured:
                continue
            saw_value = True
            if _starnet_exe_usable(configured):
                return True
            if dangling is None:
                dangling = configured

        self._starnet_dangling = dangling
        if saw_value:
            # Siril *is* configured, its setting just names a file that is gone.
            # Never silently rewrite a path the user (or an earlier Starbash run)
            # chose - report it instead, and let missing_message() explain it.
            logger.debug("Siril's starnet_exe %s no longer exists", dangling)
            return False

        starnet_path = shutil.which("starnet2")
        if starnet_path and ini_paths:
            ini_path = ini_paths[-1]
            parser = configparser.ConfigParser()
            try:
                parser.read(ini_path)
                if not parser.has_section("core"):
                    parser.add_section("core")
                parser.set("core", "starnet_exe", str(Path(starnet_path).resolve()))
                with ini_path.open("w", encoding="utf-8") as config_file:
                    parser.write(config_file)
            except (OSError, configparser.Error) as exc:
                logger.warning("Unable to add starnet2 to Siril config %s: %s", ini_path, exc)
            else:
                logger.warning(
                    "Added starnet2 at %s to the Siril config file %s",
                    Path(starnet_path).resolve(),
                    ini_path,
                )
                return True
        return False

    @property
    def is_available(self) -> bool:
        """Whether Siril is installed and its StarNet plugin points at a usable exe."""
        if self._starnet_available is None:
            if not super().is_available:
                # Siril itself is missing.
                self._starnet_available = False
            elif not self._starnet_configured():
                self._starnet_available = False
            else:
                self._starnet_available = True
        return self._starnet_available

    def missing_message(self) -> str:
        """Explain which of the two StarNet prerequisites is missing."""
        if not super().is_available:
            # StarNet is a Siril plugin, so Siril has to come first.
            return (
                f"StarNet is a Siril plugin, but Siril was not found.  Install Siril from "
                f"{SIRIL_INSTALL_URL} and then StarNet from {self.install_url}"
            )
        if self._starnet_dangling:
            return (
                f"StarNet is configured in Siril as {self._starnet_dangling}, but that "
                f"file no longer exists. Point Siril at your StarNet install "
                f"(Preferences > Miscellaneous), or download it again from "
                f"{self.install_url}"
            )
        return (
            "StarNet is not enabled in Siril. Set the StarNet executable in "
            "Siril's settings (Preferences > Miscellaneous) to use star removal. "
            f"You can download StarNet from {self.install_url}"
        )
