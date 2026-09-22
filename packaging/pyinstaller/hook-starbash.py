"""Bundle Starbash package resources without forcing every module to import.

Templates, recipes, and icons are loaded through ``importlib.resources`` at
runtime.  ``--collect-all starbash`` also imports every optional feature and its
dependencies, which makes the Windows bundle needlessly large and fragile.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("starbash")

# ``collect_data_files`` only picks up *non*-Python files, so it copies
# ``recipes/README.md`` and leaves the helper modules behind.  Recipe scripts are
# text inside the recipe repos' TOML, so PyInstaller's static analysis never sees
# their imports: a python stage runs ``from starbash.recipes import
# report_registration`` (or ``crop``/``osc``) inside the RestrictedPython sandbox
# in ``starbash/tool/python.py``, and those helpers are the only thing that
# imports ``starbash.siril``.  Without the explicit list the bundle contains just
# the README, the ``recipes`` directory then resolves as an *empty namespace
# package*, and the stage dies with "cannot import name 'report_registration'
# from 'starbash.recipes' (unknown location)".
hiddenimports = collect_submodules("starbash.recipes") + collect_submodules("starbash.siril")
