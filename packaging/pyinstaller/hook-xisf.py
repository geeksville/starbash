"""Bundle the ``xisf`` package metadata that its module reads at import time.

``xisf.py`` sets ``__version__ = version(__name__)`` at module import, which
calls ``importlib.metadata.version("xisf")``.  PyInstaller bundles the module
itself but not its ``xisf-*.dist-info`` directory, so in the frozen Windows exe
that lookup raises ``PackageNotFoundError: No package metadata was found for
xisf`` the moment GraXpert imports ``xisf`` (via ``graxpert.astroimage``).
``copy_metadata`` ships the ``.dist-info`` so the version lookup succeeds.
"""

from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("xisf")
