"""Bundle Astropy's FITS support without importing optional visualization modules.

The upstream hook collects every Astropy submodule.  On Windows CI, that imports
``astropy.visualization.wcsaxes`` which skips when its optional Matplotlib extra
is absent, aborting PyInstaller's isolated module scan.  Starbash only uses FITS.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = collect_data_files("astropy")
datas += copy_metadata("astropy")
datas += copy_metadata("numpy")
# Astropy's PLY wrapper reads and may regenerate these tables beside its source
# modules, so they must be available as files rather than only in the PYZ.
datas += [
    item
    for item in collect_data_files("astropy", include_py_files=True)
    if item[0].endswith(("_parsetab.py", "_lextab.py"))
]
# Astropy selects the active CODATA/IAU datasets dynamically (for example,
# ``astropy.constants.codata2022``), so PyInstaller cannot infer them from FITS.
hiddenimports = (
    collect_submodules("astropy.io.fits")
    + collect_submodules("astropy.constants")
    + ["numpy.lib.recfunctions"]
)
