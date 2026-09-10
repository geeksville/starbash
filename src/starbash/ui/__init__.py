"""Optional desktop user interfaces for Starbash.

This package hosts the PySide6 desktop app launched by ``sb gui``.  The Qt code
lives in :mod:`starbash.ui.qt` and is imported **lazily** so the base CLI keeps
working perfectly when the optional ``gui`` extra is not installed.
"""

__all__: list[str] = []
