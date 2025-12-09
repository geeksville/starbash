import logging
import os
import shutil

_symlink_warning_logged = False

symlinks_supported = True  # assume yes

simulate_broken_symlinks = False  # for testing purposes


def symlink_or_copy(src: str, dest: str) -> bool:
    """Create a symbolic link from src to dest, or copy if symlink fails.

    Returns True if a symlink was created, False if a copy was made."""
    global _symlink_warning_logged
    try:
        if simulate_broken_symlinks:
            raise OSError("Simulated broken symlinks for testing")
        os.symlink(src, dest)
        return True
    except OSError:
        if not _symlink_warning_logged:
            logging.warning(
                "Symlinks are not enabled on your Windows install, falling back to file copies.\n"
                "We recommend enabling symlinks for better performance:\n"
                "Enable Developer Mode in Windows 11 settings.\n"
                "This allows for the creation of symbolic links without requiring elevated administrator privileges.\n"
                "• Navigate to Settings > Privacy & security > For developers.\n"
                '• Toggle the "Developer Mode" option to On.'
            )
            _symlink_warning_logged = True
        shutil.copy2(src, dest)
        global symlinks_supported
        symlinks_supported = False
    return False
