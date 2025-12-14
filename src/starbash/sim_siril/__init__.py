# Experiment with siril script stubs
from .connection import SirilInterface
from .enums import LogColor
from .utility import ensure_installed

__all__ = ["SirilInterface", "LogColor", "ensure_installed"]
