def ensure_installed(*packages: str) -> None:
    # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.utility.ensure_installed
    import importlib
    import shutil
    import subprocess
    import sys

    for package in packages:
        try:
            importlib.import_module(package)
        except ImportError:
            # Check if we're running under pipx
            if _is_pipx_install():
                # Try to auto-inject via pipx
                pipx_path = shutil.which("pipx")
                if pipx_path:
                    subprocess.check_call([pipx_path, "inject", "starbash", package])
                else:
                    # Fallback if pipx not found on PATH
                    raise RuntimeError(
                        f"Package '{package}' not found and pipx not available. "
                        f"Please run: pipx inject starbash {package}"
                    )
            else:
                # Regular pip install for poetry/venv installs
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])


def _is_pipx_install() -> bool:
    import sys

    return "pipx" in sys.prefix or "pipx" in getattr(sys, "_base_executable", "")
