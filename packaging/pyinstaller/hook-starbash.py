"""Bundle Starbash package resources without forcing every module to import.

Templates, recipes, and icons are loaded through ``importlib.resources`` at
runtime.  ``--collect-all starbash`` also imports every optional feature and its
dependencies, which makes the Windows bundle needlessly large and fragile.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("starbash")
