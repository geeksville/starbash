"""Desktop user interfaces for Starbash.

This package hosts the PySide6 desktop app launched by ``sb gui``.  The Qt code
lives in :mod:`starbash.ui.qt` and is imported **lazily** so a plain CLI run never
pays for loading Qt.
"""

__all__: list[str] = []
