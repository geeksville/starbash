import logging
from contextlib import AbstractContextManager
from typing import Any

from astropy.io import fits
from numpy import ndarray

from starbash import InputDef


class SirilInterface:
    """Experimenting with proving a mock interface to allow siril scripts to be run directly..."""

    # This static is
    Context: dict[str, Any] = {}

    def __init__(self) -> None:
        self.image_headers: dict[str, Any] = {}

    def log(self, message: str, color: Any) -> bool:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.log
        logging.info(f"SirilInterface.log: {message}")
        return True

    @property
    def connected(self) -> bool:
        return True

    def connect(self) -> bool:
        return True

    def undo_save_state(self, description: str) -> bool:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.undo_save_state
        logging.info(f"SirilInterface.undo_save_state: {description}")
        return True

    def get_image_pixeldata(self) -> ndarray:
        """Read image data from the input defined in the Context."""
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.get_image_pixeldata
        # FIXME currently we just provide "{input[0].full_paths[0]}"
        logging.debug("SirilInterface.get_image_pixeldata called")
        input: InputDef = SirilInterface.Context["stage_input"]
        inputf = input[0]
        f = inputf.full_paths[0] # FIXME, we currently we assume we only care about the first input
        (image_data, header) = fits.getdata(f, header=True)
        self.header = header
        return image_data

    def set_image_pixeldata(self, img: ndarray) -> bool:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.set_image_pixeldata
        # currently we just write to "{output.full_paths[0]}"
        output = SirilInterface.Context["output"]
        path = output.full_paths[0]
        logging.debug(f"SirilInterface.set_image_pixeldata: {path}")

        # Write FITS file with header from input and new image data
        hdu = fits.PrimaryHDU(data=img, header=self.header)
        hdu.writeto(path, overwrite=True)

        return True

    def image_lock(self) -> AbstractContextManager:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.image_lock
        # Return a stub context manager
        class StubContextManager(AbstractContextManager):
            def __enter__(self):
                pass

            def __exit__(self, exc_type, exc_value, traceback):
                pass

        return StubContextManager()

    def cmd(self, *args: str) -> None:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.cmd
        logging.warning(f"SirilInterface.cmd ignoring: {args}")
