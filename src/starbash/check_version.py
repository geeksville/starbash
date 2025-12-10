import logging
import socket
from importlib.metadata import PackageNotFoundError, version

from update_checker import UpdateChecker

__all__ = [
    "check_version",
]

_is_connected: bool | None = None


def is_connected(host="8.8.8.8", port=53, timeout=3) -> bool:
    """
    Host: 1.1.1.1 (Cloudflare DNS) or 8.8.8.8 (Google DNS) (it is important to not use domain names)
    Port: 53/tcp
    Timeout: 3 seconds
    """
    global _is_connected
    if _is_connected is not None:
        return _is_connected

    old_timeout = socket.getdefaulttimeout()
    try:
        # This creates a TCP connection but doesn't send data.
        # It just checks if the handshake succeeds.
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
        _is_connected = True
        return True
    except OSError:
        _is_connected = False
        return False
    finally:
        socket.setdefaulttimeout(old_timeout)


def check_version():
    """Check if a newer version of starbash is available on PyPI."""
    try:
        if is_connected():
            checker = UpdateChecker()
            current_version = version("starbash")
            # This (somewhat optional) function can stall for up to 30 seconds if DNS is down.
            # So we use a faster heuristic to see if there is internet connectivity.
            result = checker.check("starbash", current_version)
            if result:
                logging.warning(result)
        else:
            logging.warning("Internet seems to be down, skipping app version check...")

    except PackageNotFoundError:
        # Package not installed (e.g., running from source during development)
        pass
