"""Preview FITS and ordinary raster images.

Qt can read JPEG/PNG/TIFF itself; FITS needs a hand because it is 16/32-bit
floating point data.  We render it with a percentile stretch so faint nebula
signal is actually visible instead of a black rectangle.

Loading is **slow** (hundreds of megabytes of pixels to read and stretch), so it
never happens on the GUI thread: :meth:`ImageViewer.show_file` hands the work to a
worker thread and shows a :class:`~starbash.ui.qt.widgets.busy_indicator.BusyIndicator`
in the middle of the view until the image is ready.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from starbash.ui.qt.widgets.busy_indicator import BusyIndicator
from starbash.ui.qt.workers import CancelToken, run_async

__all__ = ["ImageViewer", "load_image_file", "fits_to_qimage"]

FITS_SUFFIXES = {".fit", ".fits", ".fts"}


@dataclass(frozen=True)
class _LoadResult:
    """Outcome of one background load, tagged with the request that asked for it."""

    #: The value of ``ImageViewer._request`` when the load was started.
    request: int
    #: The decoded image, or ``None`` when the load failed.
    image: QImage | None
    #: A human-readable reason, or ``None`` on success.
    error: str | None



def fits_to_qimage(path: Path) -> QImage:
    """Render a FITS file to an 8-bit greyscale :class:`QImage`.

    Uses a 1%/99.5% percentile stretch, which is what makes astronomical frames
    legible by default.
    """
    import numpy as np
    from astropy.io import fits

    with fits.open(str(path), memmap=False) as hdul:
        data = next((getattr(hdu, "data", None) for hdu in hdul), None)
    if data is None:
        raise ValueError("no image data in FITS file")

    array = np.asarray(data, dtype=float)
    if array.ndim == 3:
        # Cube / RGB-ish data: show a single plane so we always have a 2-D image.
        array = array[0] if array.shape[0] <= 4 else array[..., 0]
    if array.ndim != 2:
        raise ValueError(f"unsupported FITS shape {array.shape}")

    finite = array[np.isfinite(array)]
    if finite.size == 0:
        raise ValueError("FITS image has no finite pixels")

    low, high = (float(value) for value in np.percentile(finite, [1.0, 99.5]))
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    span = high - low if high > low else 1.0

    scaled = np.clip((array - low) / span, 0.0, 1.0)
    scaled[~np.isfinite(scaled)] = 0.0
    buffer = np.ascontiguousarray((scaled * 255.0).astype(np.uint8))

    height, width = buffer.shape
    image = QImage(buffer.data, width, height, width, QImage.Format.Format_Grayscale8)
    return image.copy()  # detach from the numpy buffer before it is collected


def load_image_file(path: str | Path) -> QImage:
    """Load a FITS or raster image from disk as a :class:`QImage`."""
    path = Path(path)
    if path.suffix.lower() in FITS_SUFFIXES:
        return fits_to_qimage(path)
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"could not read image: {path}")
    return image


class ImageViewer(QWidget):
    """Show an image, scaled to fit (default) or at an explicit zoom level."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._scale = 1.0
        #: Bumped for every request, so a slow load cannot overwrite a newer one.
        self._request = 0
        #: The file currently being loaded (for the caption/error message).
        self._pending: Path | None = None

        self._label = QLabel("Select a frame to preview.")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)

        #: Busy arc shown in the middle of the view while an image loads.
        self._busy = BusyIndicator(self._scroll.viewport())

        self._fit = QCheckBox("Fit to window")
        self._fit.setChecked(True)
        self._fit.toggled.connect(self._on_fit_toggled)

        self._zoom_in = QPushButton("Zoom +")
        self._zoom_out = QPushButton("Zoom –")
        self._zoom_in.clicked.connect(lambda: self._nudge(1.25))
        self._zoom_out.clicked.connect(lambda: self._nudge(1 / 1.25))

        self._caption = QLabel("")
        self._caption.setObjectName("PageSubtitle")

        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self._fit)
        controls.addWidget(self._zoom_in)
        controls.addWidget(self._zoom_out)
        controls.addWidget(self._caption)
        controls.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll, 1)
        layout.addLayout(controls)

    # --- public API -------------------------------------------------------
    def show_file(self, path: str | Path) -> None:
        """Display the image at ``path``, decoding it on a worker thread.

        Returns immediately - the image appears when the load finishes, with a
        :class:`BusyIndicator` covering the spot meanwhile.  A file that cannot be
        read is reported *in the viewer* rather than raised, because the failure
        happens after this call has returned.  Starting a new load cancels the
        display of any load still in flight.
        """
        path = Path(path)
        self._request += 1
        request = self._request
        self._pending = path
        self._image = None
        self._scale = 1.0
        self._label.setPixmap(QPixmap())
        self._label.setText("")
        self._caption.setText(path.name)
        self._busy.start()

        def job(_report: Callable[[Any], None], _token: CancelToken) -> _LoadResult:
            # A broken frame is an expected outcome here, so it travels back as
            # data.  Raising would surface as a dialog, which is far too loud for
            # "this one frame is unreadable".
            try:
                return _LoadResult(request=request, image=load_image_file(path), error=None)
            except Exception as exc:  # noqa: BLE001 - reported in the viewer
                return _LoadResult(
                    request=request, image=None, error=str(exc) or exc.__class__.__name__
                )

        # The job only ever *returns data*; Qt queues ``_on_loaded`` (a bound method
        # of this QObject) back onto the GUI thread, so no widget is touched from
        # the worker.  The worker keeps itself alive until it finishes.
        run_async(job, on_finished=self._on_loaded)

    def show_message(self, text: str) -> None:
        """Clear the image and show ``text`` instead (dropping any pending load)."""
        self._request += 1
        self._pending = None
        self._busy.stop()
        self._image = None
        self._caption.setText("")
        self._label.setPixmap(QPixmap())
        self._label.setText(text)

    def clear(self) -> None:
        """Reset to the empty state."""
        self.show_message("Select a frame to preview.")

    def is_loading(self) -> bool:
        """Return ``True`` while an image is being decoded in the background."""
        return self._busy.is_running()

    # --- internals --------------------------------------------------------
    def _on_loaded(self, result: object) -> None:
        """Show a finished load, unless a newer request has superseded it.

        Runs on the GUI thread: the worker only ever hands back data.
        """
        if not isinstance(result, _LoadResult) or result.request != self._request:
            return

        self._busy.stop()
        name = self._pending.name if self._pending is not None else "frame"
        image = result.image
        if image is None:
            self.show_message(f"{name}\n\nPreview failed:\n{result.error}")
            return

        self._image = image
        self._scale = 1.0
        self._caption.setText(f"{name}\n{image.width()} × {image.height()}")
        self._render()

    def _on_fit_toggled(self, _checked: bool) -> None:
        self._render()

    def _nudge(self, factor: float) -> None:
        if self._image is None:
            return
        self._scale = max(0.05, min(20.0, self._scale * factor))
        self._fit.setChecked(False)
        self._render()

    def _render(self) -> None:
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image)
        if self._fit.isChecked():
            target = self._scroll.viewport().size()
            pixmap = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pixmap = pixmap.scaled(
                int(self._image.width() * self._scale),
                int(self._image.height() * self._scale),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._label.setText("")
        self._label.setPixmap(pixmap)

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self._fit.isChecked():
            self._render()

