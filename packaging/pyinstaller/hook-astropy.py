"""Bundle Astropy's FITS support without importing optional visualization modules.

The upstream hook collects every Astropy submodule.  On Windows CI, that imports
``astropy.visualization.wcsaxes`` which skips when its optional Matplotlib extra
is absent, aborting PyInstaller's isolated module scan.  Starbash only uses FITS.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = collect_data_files("astropy")
datas += copy_metadata("astropy")
datas += copy_metadata("numpy")
hiddenimports = collect_submodules("astropy.io.fits") + ["numpy.lib.recfunctions"]
