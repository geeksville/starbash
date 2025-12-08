"""Windows platform specific utilities."""

import logging
import os
import platform


def is_under_powershell() -> bool:
    """
    Check if we are running under PowerShell.

    Returns True if running under PowerShell (either Windows PowerShell or PowerShell Core),
    False if running under cmd.exe or other shells.

    The detection is based on the presence of PowerShell-specific environment variables:
    - PSModulePath: Present in all PowerShell sessions
    - PSEdition: Present in PowerShell Core (6.0+)

    Returns:
        bool: True if running under PowerShell, False otherwise
    """
    # PSModulePath is set by both Windows PowerShell and PowerShell Core
    # but not by cmd.exe
    return "PSModulePath" in os.environ


def windows_init():
    """Perform any Windows-specific initialization if needed."""

    # Check if running on Windows without PowerShell
    if platform.system() == "Windows":
        if not is_under_powershell():
            logging.warning(
                "You seem to be using the 'old school' windows cmd.exe - we highly recommend "
                "using Windows Powershell instead.\n"
                "We provide clickable links and other improvements in that environment."
            )
