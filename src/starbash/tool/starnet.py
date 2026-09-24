import configparser
import logging
import os
import shutil
import sys
from pathlib import Path

from platformdirs import PlatformDirs

from starbash.tool.base import MissingToolError, Tool, ToolSeverity
from starbash.tool.siril import SIRIL_INSTALL_URL, SirilTool

logger = logging.getLogger(__name__)

__all__ = ["StarnetTool"]

#: Where the user can obtain StarNet (the CLI build Siril can call).
STARNET_INSTALL_URL = "https://starnetastro.com/cli-tools/"

#: Siril's flatpak app id - also one of :class:`SirilTool`'s candidate commands.
SIRIL_FLATPAK_APP_ID = "org.siril.Siril"

#: Default executable location used by the Windows StarNet installer.
STARNET_WINDOWS_PATH = Path(r"C:\Program Files\StarNet2\bin\starnet2.exe")


def _find_starnet_executable() -> str | None:
    """Find StarNet on ``PATH`` or at its standard Windows installer location."""
    if path := shutil.which("starnet2"):
        return path
    if sys.platform == "win32" and STARNET_WINDOWS_PATH.is_file():
        return str(STARNET_WINDOWS_PATH)
    return None


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
        """Location of the config directory of a natively installed Siril (OS-appropriate).

        ``appauthor=False`` matters on Windows: platformdirs appends the app author
        (which defaults to the app name) *and* the app name, so ``PlatformDirs("siril")``
        would resolve to ``AppData\\Local\\siril\\siril``.  Siril keeps its config in
        ``AppData\\Local\\siril`` (single level), so the author directory is dropped.
        On Linux/macOS ``appauthor`` is ignored, so this is safe everywhere.
        """
        return Path(PlatformDirs("siril", appauthor=False).user_config_dir)

    @staticmethod
    def _siril_flatpak_config_dir() -> Path:
        """Location of Siril's config directory when Siril is the flatpak app.

        A flatpak app cannot see ``~/.config``: its sandbox is given a private XDG
        config home (``XDG_CONFIG_HOME=$HOME/.var/app/$FLATPAK_ID/config``, see
        https://docs.flatpak.org/en/latest/sandbox-permissions.html), so Siril's
        settings land in ``~/.var/app/org.siril.Siril/config/siril`` instead.  A
        StarNet found on the host PATH has to be recorded *there* to be used, which
        is what this directory is for.  It simply does not exist off Linux (nor on a
        native Linux install), where scanning it finds nothing.
        """
        return Path.home() / ".var" / "app" / SIRIL_FLATPAK_APP_ID / "config" / "siril"

    def _siril_is_flatpak(self) -> bool:
        """Whether the Siril Starbash would run is the flatpak app.

        A flatpak install is launched by its app-id-named command, and
        ``userconfig.toml`` documents pointing ``siril.path`` at
        ``flatpak run --command=siril-cli org.siril.Siril`` by hand, so either the
        executable we resolved or that override identifies it.  This only decides
        which directory is *preferred* - both are scanned either way.
        """
        configured = Tool.Preferences.get("siril", {}).get("path", "")
        if SIRIL_FLATPAK_APP_ID in str(configured):
            return True
        try:
            return SIRIL_FLATPAK_APP_ID in self.executable_path
        except MissingToolError:
            # No Siril at all: is_available reports that before config files matter,
            # so there is nothing to prefer here.
            return False

    def _siril_config_dirs(self) -> list[Path]:
        """Siril's config directories to scan, the likely-live one first.

        Siril keeps ``config.<version>.ini`` in its XDG config directory, and there
        are two candidates: a distro/AppImage install uses ``~/.config/siril`` while
        the flatpak app uses the config home inside its sandbox (see
        :meth:`_siril_flatpak_config_dir`).  A user can have both installed, and only
        one of the two holds the settings the Siril we would run actually reads - so
        that one comes first, and is the one a newly found ``starnet_exe`` is written
        to.

        Directories are returned whether or not they exist, so a probe can report
        where it looked (globbing a missing directory finds nothing anyway).
        """
        native = self._siril_config_dir()
        flatpak = self._siril_flatpak_config_dir()
        candidates = [flatpak, native] if self._siril_is_flatpak() else [native, flatpak]
        # De-duplicated, in case an XDG_CONFIG_HOME already points into a flatpak
        # sandbox and the two names resolve to the same directory.
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _siril_config_to_write(config_dirs: list[Path]) -> Path | None:
        """The Siril config file a newly found ``starnet2`` should be recorded in.

        Only the first (live) directory is considered: a setting written into another
        install's config file may never be read.  A config file has to exist already -
        Siril writes one the first time it runs, and inventing one would be guesswork -
        and of the versioned files Siril leaves behind (``config.1.4.ini``), the newest
        is the one the current Siril reads.
        """
        for config_dir in config_dirs:
            in_dir = sorted(config_dir.glob("config.*.ini"))
            if in_dir:
                return in_dir[-1]
        return None

    def _starnet_configured(self) -> bool:
        """Ensure Siril has a usable ``starnet_exe`` and report whether it is configured."""
        # Every directory a Siril install could be reading the setting from (native
        # and flatpak).  All are scanned: a decayed setting in one must not hide a
        # usable one in another.
        config_dirs = self._siril_config_dirs()
        ini_paths: list[Path] = []
        for config_dir in config_dirs:
            # Siril versions its config file (e.g. config.1.4.ini); check whichever exist.
            ini_paths.extend(sorted(config_dir.glob("config.*.ini")))

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

        starnet_path = _find_starnet_executable()
        ini_path = self._siril_config_to_write(config_dirs)
        if not starnet_path or ini_path is None:
            # Nothing is configured, and there is nothing we can do about it - but say
            # where we looked, because "StarNet was not detected" is otherwise hard to
            # tell apart from "we looked in the wrong place".
            logger.debug(
                "No starnet_exe set in any Siril config (%s); starnet2 was %s",
                ", ".join(str(config_dir) for config_dir in config_dirs) or "no directory found",
                "found on PATH or at the standard Windows path"
                if starnet_path
                else "not found on the PATH or at the standard Windows path",
            )
            return False

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

    def invalidate_availability(self) -> None:
        """Forget the cached StarNet probe, so the next check re-probes.

        This tool keeps its own cache (``_starnet_available``, plus
        ``_starnet_dangling`` for a StarNet that has gone missing since the probe),
        and ``is_available`` never reads ``ExternalTool._is_available``: the base
        implementation would therefore clear Siril's cached answer while StarNet's
        stayed behind.  The GUI setup wizard's *Re-check* button is the caller that
        needs this - without the override it could never notice a StarNet installed
        while the wizard was open.
        """
        self._starnet_available = None
        # A stale path only describes the probe it was found in, so it goes with
        # ``is_available``'s cached answer: a re-check that now succeeds must not
        # keep reporting the last run's dead setting.
        self._starnet_dangling = None
        super().invalidate_availability()

    def missing_message(self) -> str:
        """Explain which of StarNet's prerequisites is missing.

        Three cases need three different fixes, so they are checked in order: Siril
        missing (nothing can run), StarNet missing (nothing to run), and StarNet
        present but Siril not able to use it.  The install check is done here rather
        than from the cached probe because "is StarNet installed *at all*" is
        independent of what Siril's config says - a stale setting must not be
        reported as an installed-but-misconfigured StarNet.
        """
        if not super().is_available:
            # StarNet is a Siril plugin, so Siril has to come first.
            return (
                f"StarNet is a Siril plugin, but Siril was not found.  Install Siril from "
                f"{SIRIL_INSTALL_URL} and then StarNet from {self.install_url}"
            )
        if _find_starnet_executable() is None:
            # No StarNet anywhere we look, so there is nothing for Siril to be pointed
            # at yet and installing it is the only fix.
            if self._starnet_dangling:
                # Siril *does* name a StarNet, that install is simply gone - so the
                # stale path is what the user will trip over.  Say both: the download
                # to make, and the setting that is waiting for something else.
                return (
                    f"StarNet is not installed. Siril is configured to use "
                    f"{self._starnet_dangling}, but that file no longer exists - install "
                    f"StarNet from {self.install_url} and then point Siril at it "
                    f"(Preferences > Miscellaneous)"
                )
            return (
                f"StarNet is not installed. Starbash could not find a starnet2 executable "
                f"on your PATH or in StarNet's usual install location; download and "
                f"install it from {self.install_url}"
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
