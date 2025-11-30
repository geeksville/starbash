import logging
import os
import shutil

_symlink_warning_logged = False


def symlink_or_copy(src: str, dest: str) -> None:
    """Create a symbolic link from src to dest, or copy if symlink fails."""
    global _symlink_warning_logged
    try:
        os.symlink(src, dest)
    except OSError:
        if not _symlink_warning_logged:
            logging.warning(
                "Symlinks are not enabled on your Windows install, falling back to file copies.  We recommend enabling symlinks for better performance."
            )
            _symlink_warning_logged = True
        shutil.copy2(src, dest)
