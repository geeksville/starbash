import os
import platform


def linux_init():
    """Perform Linux-specific initialization."""

    if platform.system() == "Linux":
        # Suppress the GIO/dconf warning
        # Must be done before importing libraries that use GLib (such as graxpert)
        os.environ["GIO_MODULE_DIR"] = ""
        os.environ["GIO_USE_VFS"] = "local"
