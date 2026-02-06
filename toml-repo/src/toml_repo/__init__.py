"""
The toml_repo package provides a generic TOML-based repository manager.

It handles finding, loading, merging, and searching TOML configuration repositories
with support for multiple URL schemes (file://, pkg://, http://), import resolution,
and precedence-based configuration merging.
"""

from .manager import RepoManager
from .repo import REPO_REF, Repo, get_config_suffix, set_config_suffix, set_pkg_resource_root

__all__ = [
    "RepoManager",
    "Repo",
    "get_config_suffix",
    "set_config_suffix",
    "set_pkg_resource_root",
    "REPO_REF",
]
