import logging
from contextlib import AbstractContextManager


class SirilInterface:
    """Experimenting with proving a mock interface to allow siril scripts to be run directly..."""

    def __init__(self) -> None:
        pass

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

    def get_image_pixeldata(self) -> Any:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.get_image_pixeldata
        logging.info("SirilInterface.get_image_pixeldata called")
        return None

    def set_image_pixeldata(self, img) -> bool:
        # https://siril.readthedocs.io/en/latest/Python-API.html#sirilpy.connection.SirilInterface.set_image_pixeldata
        logging.info(f"SirilInterface.set_image_pixeldata: {img}")
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
