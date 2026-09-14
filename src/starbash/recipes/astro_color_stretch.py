"""astro-color-stretch - a Starbash port of David M. Jones' astro-color-stretch 1.2.

    astro-color-stretch
    Copyright (c) 2025/2026, David M. Jones, dmjonesphotography.com
    An adaptation of Roger N. Clark's original rnc-color-stretch.

Ported from ``astro-color-stretch-1.2.py`` (upstream version 1.2) with the author's
permission under the GPL. This file is a port, not the original: keep the upstream file
and version above in sync when merging upstream fixes.

SPDX-License-Identifier: GPL-3.0-or-later

Deliberate deviations from the reference (everything else is a 1:1 port)
-----------------------------------------------------------------------
1. **Channel order is RGB, not BGR.** The reference reads with ``cv2.imread`` (BGR) and
   compensates with ``RED, GREEN, BLUE = 2, 1, 0``. Starbash hands us RGB FITS data, so
   every colour-space constant is the ``...RGB...`` variant. See ``doc/plans/astro-stretch.md``
   section 5.3 for the exhaustive list of order-sensitive sites.
2. **Richardson-Lucy luminance weights fixed.** The reference applies the Rec.709 weights
   ``0.2126/0.7152/0.0722`` to channels 0/1/2 of its BGR array, so its *blue* channel received
   the *red* weight. With RGB order the standard weights land on the right channels. Opt-in
   (``rl_deconvolve`` defaults to false).
3. **``HSVadjust`` scaling fixed.** ``hsv_adjust`` fed 0..65535 data straight into OpenCV's
   float HSV colour space, which expects S/V in 0..1; every value therefore came out ~65535x
   too bright. We normalise to 0..1 for the conversion and scale back, matching what the
   reference's own HSV colour-correction branch already did. Opt-in (``hsv_adjust`` defaults
   to false).
4. **The discarded ``rgb_sky_zero`` call at the end of the s-curve loop is dropped.** The
   reference called it without using the result, which cannot change the image (``rgb_sky_zero``
   does not mutate its input in place) - it only wasted a histogram plus two full image passes
   per s-curve step.
5. **Mono (2-D) input raises** instead of being silently mis-handled; the reference aborted
   with "not a 3 color RGB image". The stage targets colour OSC/palette stacks.
6. **scikit-image's RL entry point is called with its current keyword.** Upstream calls
   ``richardson_lucy(..., iterations=...)``; the installed scikit-image (0.26) names that
   parameter ``num_iter``, so the port adapts the call. Also inert for the default settings
   (``rl_deconvolve`` defaults to false).
7. **``ca_correct`` defaults to off, not on.** Upstream defaults it to true, but this stage
   runs in the VeraLux slot - i.e. on the *starless* frame that StarNet produced (the stars
   are blended back later by the ``merge_stars`` recipe, from the starmask that never reaches
   us). Channel misalignment is a star-centric defect, so at this point in the pipeline there
   is nothing for the alignment to fix, while the ECC solve costs a full extra pass over two
   channels *and* can fail to converge. The parameter is honoured when set to true - it is
   only the default that differs (recipe default and dataclass default are both false).

Also dropped: ``cv2.imread``/``cv2.imwrite`` (Starbash owns file I/O via ``starbash.sim_siril``),
input extension/format checks, the unique-output-filename logic, the matplotlib histogram plots,
the two debug TIFFs written by ``select_dark_region``, and ``sys.exit()`` in favour of exceptions.
Added: parameter validation naming *every* offender, bounds validation for the manual
dark-region window, logging instead of ``print``, and a timing summary.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, fields
from typing import Any

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.restoration import richardson_lucy

from starbash.sim_siril import SirilInterface

logger: logging.Logger = logging.getLogger(__name__)

# These globals are populated by recipe scripts before calling ``run``.
context: dict[str, Any] = {}

DN_MAX = 65535.0  # astro-color-stretch works in 16-bit "DN" internally, as the guide documents
STACK_MIN = 4096.0  # the level the stretch loops lift the darkest pixel to

# The upstream release this port follows (see the module docstring's attribution header).
ACS_VERSION = "1.2"

# Enumerations, matching the reference's module constants.
STRETCH_NONE, STRETCH_RTP, STRETCH_ASINH, STRETCH_LOG = 0, 1, 2, 3
COLORCOR_NONE, COLORCOR_RATIO, COLORCOR_HSV = 0, 1, 2
WB_NONE, WB_GRAY, WB_TEMP_TINT = 0, 1, 2
SKYZERO_FULL, SKYZERO_AUTO, SKYZERO_MANUAL = 0, 1, 2

TS_FULL = cv2.COLOR_RGB2HSV_FULL
TS_BACK_FULL = cv2.COLOR_HSV2RGB_FULL


@dataclass
class StretchParams:
    """Every knob the astro-color-stretch algorithm understands.

    Defaults are transcribed from ``astro-color-stretch-1.2.py``; parameter *names* match
    the recipe's ``[[stages.parameters]]`` entries so the GUI can override them by name.
    See ``doc/plans/astro-stretch.md`` section 4.4 for the name-by-name mapping to the
    symbol names used by the setup guide.

    The algorithm only ever runs on linear data: the caller (``run``) normalises the input
    to float64 ``[0, 65535]`` before any of this is used.
    """

    # --- Stretch ---------------------------------------------------------------
    stretch_type: int = STRETCH_RTP
    skylevelfactor: float = 0.06  # black point, as a fraction of the channel's histogram peak
    zeroskyred: float = 4096.0  # sky DN the red channel is zeroed to
    zeroskygreen: float = 4096.0
    zeroskyblue: float = 4096.0
    setmin: bool = False  # floor the darkest pixels, so noise/fringes do not crush to black
    setminr: float = 4096.0
    setming: float = 4096.0
    setminb: float = 4096.0

    # Root-power stretch
    rootiter: int = 1
    rootpower: float = 20.0
    rootpower2: float = 2.0

    # Asinh stretch
    asinhiter: int = 1
    k1: float = 100.0  # the setup guide's K1
    k2: float = 5.0  # the setup guide's K2 (2nd iteration only)

    # Logarithmic stretch
    logiter: int = 1
    log_k1: float = 100.0  # the setup guide's logK1
    log_k2: float = 5.0  # the setup guide's logK2 (2nd iteration only)

    # S-curve: 0 = off, 1..4 = that many passes (curve numbers cycle 1,2,1,2)
    scurve: int = 1

    # --- Dark-sky region -------------------------------------------------------
    rgbskyzero_method: int = SKYZERO_FULL
    win_frac: int = 10
    ulx: int = 1000
    uly: int = 1000
    win_width: int = 500
    win_height: int = 700

    # --- Colour ----------------------------------------------------------------
    color_correction_type: int = COLORCOR_RATIO
    colorenhance: float = 1.0
    gamma: float = 5.0  # HSV colour-correction method only
    hsv_adjust: bool = False
    hue_adjust: float = 0.0
    sat_adjust: float = 1.0
    val_adjust: float = 1.0
    vib_adjust: float = 0.0

    # --- Corrections -----------------------------------------------------------
    # Off by default, unlike upstream: this stage runs on the starless frame (see deviation 7).
    ca_correct: bool = False
    vn_correct: bool = False
    vn_strength: float = 30.0
    lg_correct: bool = False
    lg_strength: float = 100.0
    star_reduction: bool = False
    reduction_strength: float = 1.0
    rl_deconvolve: bool = False
    rl_iterations: int = 15
    psf_sigma: float = 0.8

    # --- White balance ---------------------------------------------------------
    wb_mode: int = WB_NONE
    temp: float = 1.0
    tint: float = 1.0

    def __post_init__(self) -> None:
        """Coerce values that arrived from TOML as strings (e.g. ``"10"`` or ``"0.06"``)."""
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, str):
                # ``expand_context_typed`` turns numeric strings into floats; TOML numbers
                # stay numeric. Only a stray string (a quoted parameter override) lands here.
                try:
                    setattr(self, field.name, float(value))
                except ValueError:
                    pass

    @classmethod
    def from_parameter_object(cls, parameters: Any) -> StretchParams:
        """Build params from a ``context["parameters"]`` object.

        Only fields this dataclass knows are read, so a recipe may declare unrelated
        parameters (and future upstream options) without breaking the engine; anything
        missing keeps its upstream default.
        """
        known = {field.name for field in fields(cls)}
        kwargs = {name: getattr(parameters, name) for name in known if hasattr(parameters, name)}
        return cls(**kwargs)

    @classmethod
    def from_context(cls, ctx: dict[str, Any]) -> StretchParams:
        """Build params from a Starbash stage context."""
        return cls.from_parameter_object(ctx["parameters"])

    def validate(self) -> None:
        """Raise ``ValueError`` listing every out-of-range parameter (see ``validate_params``)."""
        validate_params(self)

    def describe(self) -> list[str]:
        """Echo the effective settings, one line per setting.

        This is the reference's ``print_parameters`` adapted to logging: upstream encoded the
        parameters in the *filename* (``-rtp=20-sc=1-...``), Starbash replaces one fixed
        ``acs_*`` output instead, so the echo is how a run stays reproducible.
        """
        lines = [f"{field.name} = {getattr(self, field.name)}" for field in fields(self)]

        stretch_names = {
            STRETCH_NONE: "none",
            STRETCH_RTP: "root-power",
            STRETCH_ASINH: "asinh",
            STRETCH_LOG: "logarithmic",
        }
        lines.append(
            f"stretch: {stretch_names.get(self.stretch_type, self.stretch_type)}"
            f" | black point {self.skylevelfactor * 100.0:.2f}% of histogram peak"
            f" -> sky DN {self.zeroskyred}/{self.zeroskygreen}/{self.zeroskyblue}"
        )

        if self.rgbskyzero_method == SKYZERO_FULL:
            region = "full image histogram"
        elif self.rgbskyzero_method == SKYZERO_AUTO:
            region = f"auto-scan {self.win_width}x{self.win_height} (step 1/{self.win_frac})"
        else:
            region = f"manual {self.win_width}x{self.win_height} at ({self.ulx},{self.uly})"
        lines.append(f"dark-sky region: {region}")

        cc_names = {COLORCOR_NONE: "none", COLORCOR_RATIO: "ratio", COLORCOR_HSV: "hsv"}
        lines.append(
            f"colour correction: {cc_names.get(self.color_correction_type, self.color_correction_type)}"
        )
        wb_names = {WB_NONE: "none", WB_GRAY: "gray-world", WB_TEMP_TINT: "temp/tint"}
        lines.append(f"white balance: {wb_names.get(self.wb_mode, self.wb_mode)}")
        return lines


def validate_params(params: StretchParams) -> None:
    """Raise ``ValueError`` listing *every* out-of-range parameter.

    Replaces the reference's ``check_parameters``, which printed the offenders and then
    exited the process; we raise so the surrounding task can report and skip the file.
    """
    problems: list[str] = []

    def check_range(name: str, value: float, min_val: float, max_val: float) -> None:
        if not (min_val <= value <= max_val):
            problems.append(f"'{name}' must be between {min_val} and {max_val} (got {value})")

    def check_choice(name: str, value: Any, choices: tuple[Any, ...]) -> None:
        if value not in choices:
            problems.append(f"'{name}' must be one of {choices} (got {value})")

    check_choice("stretch_type", params.stretch_type, (0, 1, 2, 3))
    check_choice("scurve", params.scurve, (0, 1, 2, 3, 4))
    check_choice("color_correction_type", params.color_correction_type, (0, 1, 2))
    check_choice("rgbskyzero_method", params.rgbskyzero_method, (0, 1, 2))
    check_choice("wb_mode", params.wb_mode, (0, 1, 2))

    check_range("skylevelfactor", params.skylevelfactor, 0.0, 1.0)
    check_range("colorenhance", params.colorenhance, 0.0, 2.0)
    check_range("gamma", params.gamma, 0.1, 10.0)

    if params.stretch_type == STRETCH_RTP:
        check_choice("rootiter", params.rootiter, (1, 2))
        check_range("rootpower", params.rootpower, 1, 600)
        check_range("rootpower2", params.rootpower2, 1, 600)

    if params.stretch_type == STRETCH_ASINH:
        check_choice("asinhiter", params.asinhiter, (1, 2))
        check_range("k1", params.k1, 1, 1000)
        check_range("k2", params.k2, 1, 1000)

    if params.stretch_type == STRETCH_LOG:
        check_choice("logiter", params.logiter, (1, 2))
        check_range("log_k1", params.log_k1, 1, 500)
        check_range("log_k2", params.log_k2, 1, 500)

    check_range("rl_iterations", params.rl_iterations, 1, 40)
    check_range("psf_sigma", params.psf_sigma, 0.1, 3.0)

    for name in ("zeroskyred", "zeroskygreen", "zeroskyblue"):
        check_range(name, getattr(params, name), 0, 25000)

    for name in ("setminr", "setming", "setminb"):
        check_range(name, getattr(params, name), 0.0, 20000.0)

    if params.hsv_adjust:
        check_range("hue_adjust", params.hue_adjust, -180, 180)
        check_range("sat_adjust", params.sat_adjust, 0.0, 2.0)
        check_range("val_adjust", params.val_adjust, 0.1, 2.0)
        check_range("vib_adjust", params.vib_adjust, -1.0, 1.0)

    if params.rgbskyzero_method != SKYZERO_FULL:
        check_range("win_frac", params.win_frac, 1, 10)
        if params.win_width <= 0 or params.win_height <= 0:
            problems.append(
                f"'win_width'/'win_height' must be greater than zero "
                f"(got {params.win_width}x{params.win_height})"
            )
        if params.rgbskyzero_method == SKYZERO_MANUAL and (params.ulx < 0 or params.uly < 0):
            problems.append(f"'ulx'/'uly' must not be negative (got {params.ulx},{params.uly})")

    if params.vn_correct:
        check_range("vn_strength", params.vn_strength, 0, 200)

    if params.lg_correct:
        check_range("lg_strength", params.lg_strength, 0, 200)

    if params.star_reduction:
        check_range("reduction_strength", params.reduction_strength, 0.0, 1.0)

    if params.wb_mode == WB_TEMP_TINT:
        check_range("temp", params.temp, 0.8, 1.2)
        check_range("tint", params.tint, 0.7, 1.3)

    if problems:
        raise ValueError("astro-color-stretch parameter error:\n  - " + "\n  - ".join(problems))


def split_channels(im: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split an interleaved ``(H, W, 3)`` RGB image into r, g, b channel arrays."""
    return im[:, :, 0], im[:, :, 1], im[:, :, 2]


def merge_channels(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Merge r, g, b channel arrays back into an interleaved ``(H, W, 3)`` RGB image."""
    return np.stack((r, g, b), axis=-1)


def to_interleaved(image_data: np.ndarray) -> np.ndarray:
    """Return ``image_data`` as an interleaved ``(H, W, 3)`` array.

    Starbash's ``get_image_pixeldata`` hands back FITS data, i.e. planar ``(3, H, W)`` for
    a colour image. The reference works on cv2-style interleaved arrays, so we transpose at
    the boundary and transpose back in ``to_stacked``. A 2-D (mono) input is rejected: the
    algorithm is defined for 3-channel colour data.
    """
    if image_data.ndim != 3:
        raise ValueError(
            f"astro-color-stretch requires a 3-channel colour image, got shape {image_data.shape}"
        )
    if image_data.shape[0] == 3 and image_data.shape[2] != 3:
        return np.moveaxis(image_data, 0, -1)  # (3, H, W) FITS plane order -> (H, W, 3)
    if image_data.shape[2] < 3:
        raise ValueError(
            f"astro-color-stretch requires a 3-channel colour image, got shape {image_data.shape}"
        )
    return image_data[..., :3]  # already interleaved; drop any alpha


def to_stacked(im: np.ndarray) -> np.ndarray:
    """Return an interleaved ``(H, W, 3)`` image as a planar ``(3, H, W)`` FITS array."""
    return np.moveaxis(im, -1, 0)


def normalize_input(image_data: np.ndarray) -> np.ndarray:
    """Convert raw FITS pixel data into the ``float64`` interleaved 0..65535 working array.

    The scaling rules are kept verbatim from the reference's ``read_file`` so that every
    number the setup guide quotes (``4096``, ``skylevelfactor``, ``setmin*``) means the same
    thing here: uint8 is expanded to 16-bit, a normalised float stack is scaled to 0..65535,
    anything else is used as-is.
    """
    im = to_interleaved(image_data)

    if im.dtype == np.uint8:
        im = im.astype(np.float64) * 257.0  # 255 * 257 = 65535
    elif im.dtype.kind == "f":
        im = im.astype(np.float64)
        peak = float(im.max()) if im.size else 0.0
        if peak <= 1.0:
            im = (im * DN_MAX).round()
    else:
        im = im.astype(np.float64)

    return im


def _human_seconds(seconds: float) -> str:
    """Convert input seconds to a compact H:M:S style string (upstream ``convert_seconds``)."""
    if seconds < 1:
        return "< 1 second"
    h, m, s = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    if h:
        return f"{h} hr {m} min"
    if m:
        return f"{m} min {s} sec"
    return f"{s} sec"


def log_image_stats(im: np.ndarray, label: str = "") -> None:
    """Log min/max/mean for each RGB channel (upstream ``image_stats``)."""
    r, g, b = split_channels(np.clip(im, 0, DN_MAX).astype(np.uint16))
    for name, channel in (("RED", r), ("GREEN", g), ("BLUE", b)):
        logger.debug(
            "%s%s: Min = %d, Max = %d, Mean = %d",
            name,
            f" ({label})" if label else "",
            int(channel.min()),
            int(channel.max()),
            int(channel.mean()),
        )


def log_channel_stats(channel: np.ndarray, channel_name: str) -> None:
    """Log min/max/mean for a single 2-D channel.

    The vignette and gradient corrections work channel by channel and upstream printed these
    stats per channel; ``log_image_stats`` is for whole (H, W, 3) images.
    """
    logger.debug(
        "%s channel stats: Min = %d, Max = %d, Mean = %d",
        channel_name,
        int(channel.min()),
        int(channel.max()),
        int(channel.mean()),
    )


def max_histogram(hist: np.ndarray, hist_lo: int = 400, hist_hi: int = 65500) -> tuple[int, int]:
    """Return the index and value of the maximum histogram bin between the given bounds.

    Returns ``(0, 0)`` if the range is invalid or all-zero (upstream ``max_histogram``).
    """
    if hist_lo >= len(hist):  # not enough bins to process
        return 0, 0

    sub_hist = hist[hist_lo : hist_hi + 1]
    if not np.any(sub_hist):  # all-zero range
        return 0, 0

    max_index = int(np.argmax(sub_hist)) + hist_lo
    return max_index, int(hist[max_index])


def smooth_histogram(hst: np.ndarray, ism: int = 300) -> np.ndarray:
    """Smooth a histogram with a uniform moving-average filter (upstream ``smooth_histogram``)."""
    hst = np.asarray(hst).flatten()
    # Zero out the low bins: the moving average would otherwise spike there, because the
    # kernel has too little real data to average near 0.
    hst[:5] = 0

    window_size = 2 * ism + 1
    kernel = np.ones(window_size) / window_size
    return np.convolve(hst, kernel, mode="same")


def select_dark_region(
    im: np.ndarray, params: StretchParams
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Pick the dark-sky window used for the black point, per ``rgbskyzero_method``.

    Returns the upper-left and lower-right ``(x, y)`` corners. Upstream also wrote two debug
    TIFFs (``-selected-dark-sky-region``/``-location``) here; those are dropped, but the
    selected corners are logged so the choice can be checked in the run tree.
    """
    height, width = im.shape[:2]

    if params.rgbskyzero_method == SKYZERO_FULL:
        return (0, 0), (width, height)

    # Bounds validation the reference lacked: a window larger than the frame (or the
    # guide's 1000/1000 start coordinates on a small image) used to crash deep inside numpy.
    if params.win_width > width or params.win_height > height:
        raise ValueError(
            f"dark-sky window {params.win_width}x{params.win_height} exceeds the "
            f"{width}x{height} image - lower win_width/win_height"
        )

    im_uint16 = np.clip(im, 0, DN_MAX).astype(np.uint16)

    if params.rgbskyzero_method == SKYZERO_MANUAL:
        x1, y1 = params.ulx, params.uly
        if x1 + params.win_width > width or y1 + params.win_height > height:
            raise ValueError(
                f"manual dark-sky window at ({x1},{y1}) size "
                f"{params.win_width}x{params.win_height} runs off the {width}x{height} image"
            )
    else:
        logger.info(
            "Auto-scanning for the darkest %dx%d window (step 1/%d)...",
            params.win_width,
            params.win_height,
            params.win_frac,
        )
        # Declared as a plain ndarray: the OpenCV stubs return a union of dtypes here, which
        # makes numpy's ``mean`` overloads unresolvable below.
        gray: np.ndarray = cv2.cvtColor(im_uint16, cv2.COLOR_RGB2GRAY)

        min_avg = float("inf")
        x1 = y1 = 0
        step_y = max(1, params.win_height // params.win_frac)
        step_x = max(1, params.win_width // params.win_frac)

        for y in range(0, height - params.win_height + 1, step_y):
            for x in range(0, width - params.win_width + 1, step_x):
                region = gray[y : y + params.win_height, x : x + params.win_width]
                avg_brightness = float(region.mean())
                if avg_brightness < min_avg:
                    min_avg = avg_brightness
                    x1, y1 = x, y

        logger.info("Darkest window average brightness: %.2f DN", min_avg)

    x2, y2 = x1 + params.win_width, y1 + params.win_height
    logger.info("Dark-sky window ulc: (x=%d, y=%d), lrc: (x=%d, y=%d)", x1, y1, x2, y2)
    return (x1, y1), (x2, y2)


def rgb_sky_zero(
    im: np.ndarray,
    ulxy: tuple[tuple[int, int], tuple[int, int]],
    params: StretchParams,
    passes: int = 2,
) -> np.ndarray:
    """Set each channel's sky level to its zero reference (upstream ``rgb_sky_zero``).

    The histogram peak is found, the dark-sky level is taken as ``skylevelfactor`` of that
    peak, and each channel is shifted so its sky level lands on the matching ``zerosky*`` DN.
    This is the *black point* step, and because it runs again after every stretch iteration it
    is also what re-neutralises the sky those stretches brightened.

    Args:
        ulxy: upper-left and lower-right corners of the dark-sky region.
        passes: passes to run. Upstream sends 3 for high stretch values (``rootpower > 60``,
            ``K1/K2 > 100``, ``logK1/logK2 > 100``) and 2 otherwise; the extra pass matters
            because a hard stretch leaves the histogram peak far from where a single pass
            expects it.
    """
    (x1, y1), (x2, y2) = ulxy
    logger.debug("Computing RGB sky zero (%d pass(es))", passes)

    for pass_num in range(passes):
        logger.debug("RGB sky zero pass %d of %d", pass_num + 1, passes)

        selected_region = im[y1:y2, x1:x2]
        rfs, gfs, bfs = (c.astype(np.float32) for c in split_channels(selected_region))

        # cv2.calcHist needs float32 input and gives us 65536 DN bins; smoothing tames the
        # per-bin noise so "the peak" is a feature rather than a fluke.
        # (OpenCV's stubs describe ``images`` as ``Sequence[UMat]``, so the ndarray argument
        # needs the suppression below; the call itself is the documented OpenCV form.)
        rhistsm = smooth_histogram(cv2.calcHist([rfs], [0], None, [65536], [0, 65536]))  # pyright: ignore[reportCallIssue, reportArgumentType]
        ghistsm = smooth_histogram(cv2.calcHist([gfs], [0], None, [65536], [0, 65536]))  # pyright: ignore[reportCallIssue, reportArgumentType]
        bhistsm = smooth_histogram(cv2.calcHist([bfs], [0], None, [65536], [0, 65536]))  # pyright: ignore[reportCallIssue, reportArgumentType]

        rmax_dn, rmax_val = max_histogram(rhistsm)
        gmax_dn, gmax_val = max_histogram(ghistsm)
        bmax_dn, bmax_val = max_histogram(bhistsm)

        if 0 in (rmax_dn, gmax_dn, bmax_dn):
            raise ValueError(
                "rgb_sky_zero cannot find a histogram peak for one or more channels "
                f"(red dn={rmax_dn}, green dn={gmax_dn}, blue dn={bmax_dn}). "
                "Try a larger dark-sky window, or increase sky_level_factor."
            )

        logger.debug(
            "Histogram peaks: RED %d (%d px), GREEN %d (%d px), BLUE %d (%d px)",
            rmax_dn,
            rmax_val,
            gmax_dn,
            gmax_val,
            bmax_dn,
            bmax_val,
        )

        # Sky level, as a fraction of the channel's own histogram peak. Note that only the
        # *green* level is used below: green is the reference channel, and red/blue are
        # searched against it so all three are neutralised to the same sky brightness.
        gsky_level = gmax_val * params.skylevelfactor

        def find_sky_dn(histsm: np.ndarray, max_dn: int, sky_level: float) -> int:
            """Walk left from the histogram peak to where the count falls through sky_level."""
            for ih in range(max_dn, 1, -1):
                if histsm[ih] >= sky_level >= histsm[ih - 1]:
                    return ih
            return 0  # not found

        # All three channels are searched against the *green* sky level, i.e. green is the
        # reference channel and R/B are brought to its level (see the guide's neutralisation).
        rsky_dn = find_sky_dn(rhistsm, rmax_dn, gsky_level)
        gsky_dn = find_sky_dn(ghistsm, gmax_dn, gsky_level)
        bsky_dn = find_sky_dn(bhistsm, bmax_dn, gsky_level)

        if 0 in (rsky_dn, gsky_dn, bsky_dn):
            # Upstream only warns here and stretches anyway: the result may show colour casts,
            # which the user fixes by raising skylevelfactor or cropping edge artifacts.
            logger.warning(
                "Histogram sky level not found for one or more channels "
                "(red=%d, green=%d, blue=%d) - the stretch may show artifacts or colour "
                "shifts. Try increasing skylevelfactor, cropping edge artifacts, or "
                "enabling the vignette/gradient correction.",
                rsky_dn,
                gsky_dn,
                bsky_dn,
            )

        logger.debug(
            "Sky level (%.2f%% of peak): RED %d, GREEN %d, BLUE %d",
            params.skylevelfactor * 100.0,
            rsky_dn,
            gsky_dn,
            bsky_dn,
        )

        shifts = {
            "red": float(rsky_dn - params.zeroskyred),
            "green": float(gsky_dn - params.zeroskygreen),
            "blue": float(bsky_dn - params.zeroskyblue),
        }
        logger.debug(
            "Subtracting sky shifts: red %g -> %g, green %g -> %g, blue %g -> %g",
            shifts["red"],
            params.zeroskyred,
            shifts["green"],
            params.zeroskygreen,
            shifts["blue"],
            params.zeroskyblue,
        )

        rf, gf, bf = split_channels(im)
        # Shift, then rescale so the (now sky-zeroed) white point stays at 65535 rather than
        # clipping a bright sky-band's worth of highlights.
        rf = np.clip((rf - shifts["red"]) * (DN_MAX / (DN_MAX - shifts["red"])), 0, DN_MAX)
        gf = np.clip((gf - shifts["green"]) * (DN_MAX / (DN_MAX - shifts["green"])), 0, DN_MAX)
        bf = np.clip((bf - shifts["blue"]) * (DN_MAX / (DN_MAX - shifts["blue"])), 0, DN_MAX)

        im = merge_channels(rf, gf, bf)
        log_image_stats(im, "after sky zero")

    return im.astype(np.float64)


def _sky_zero_passes(stretch: float, params: StretchParams) -> int:
    """Return 3 passes for a hard stretch, 2 otherwise (upstream's per-iteration rule)."""
    if params.stretch_type == STRETCH_RTP:
        return 3 if stretch > 60 else 2
    return 3 if stretch > 100 else 2


def image_stretch(
    im: np.ndarray, ulxy: tuple[tuple[int, int], tuple[int, int]], params: StretchParams
) -> np.ndarray:
    """Apply the chosen stretch (root-power, asinh or log) once per configured iteration.

    Each iteration is: stretch, lift the darkest pixel to ``STACK_MIN`` (4096 DN), then run
    ``rgb_sky_zero`` again - the lifts and re-zeroings are what keep the sky neutral as the
    exponent goes up, so they are not optional detail.
    """
    if params.stretch_type == STRETCH_NONE:
        return im

    stretch_names = {
        STRETCH_RTP: "root-power",
        STRETCH_ASINH: "asinh",
        STRETCH_LOG: "logarithmic",
    }
    logger.info("Computing %s stretch", stretch_names.get(params.stretch_type, "?"))

    if params.stretch_type == STRETCH_RTP:
        iterations = params.rootiter
        factors = (params.rootpower, params.rootpower2)
    elif params.stretch_type == STRETCH_ASINH:
        iterations = params.asinhiter
        factors = (params.k1, params.k2)
    else:
        iterations = params.logiter
        factors = (params.log_k1, params.log_k2)

    for index in range(iterations):
        factor = factors[min(index, 1)]
        logger.info("Stretch iteration %d of %d (factor %s)", index + 1, iterations, factor)

        if params.stretch_type == STRETCH_RTP:
            exponent = 1.0 / factor
            im = DN_MAX * ((im + 1) / (DN_MAX + 1)) ** exponent
        elif params.stretch_type == STRETCH_ASINH:
            im = DN_MAX * (np.arcsinh(factor * (im + 1) / (DN_MAX + 1)) / np.arcsinh(factor))
        else:
            im = DN_MAX * (np.log1p(factor * (im + 1) / (DN_MAX + 1)) / np.log1p(factor))

        log_image_stats(im, "after stretch")

        # Upstream subtracts the overshoot above a 4096 DN floor, i.e. it brings the darkest
        # pixel *down* to 4096 DN when there is room (and leaves the image alone when there is
        # not). 4096 is the black floor the guide assumes, so sky zero has signal to measure.
        lift = max(float(np.amin(im)) - STACK_MIN, 0.0)
        logger.debug(
            "Subtracting %d DN to bring the darkest pixel to %d DN", int(lift), int(STACK_MIN)
        )
        im = DN_MAX * ((im - lift) / (DN_MAX - lift))
        log_image_stats(im, "after stretch floor")

        passes = _sky_zero_passes(factor, params)
        im = rgb_sky_zero(im, ulxy, params, passes=passes)

    return im


def s_curve(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Apply the S-curve contrast boost ``scurve`` times.

    Curve numbers cycle 1,2,1,2: odd passes use ``xfactor=5.0, xoffset=0.42`` (crossover at
    about 1/3 of the range: brighter above it, darker below) and even passes use
    ``3.0``/``0.22`` (a gentle overall brightening).
    """
    if params.scurve <= 0:
        return im

    logger.info("Computing s-curve stretch (%d pass(es))", params.scurve)
    for index in range(params.scurve):
        curve_num = index + 1
        xfactor, xoffset = (5.0, 0.42) if curve_num % 2 == 1 else (3.0, 0.22)

        # Normalise the curve so that 0 -> 0 and 1 -> 1 (upstream's scurvemin/max/scurveminsc).
        scurvemin = xfactor / (1.0 + math.exp(-1.0 * ((0.0 - xoffset) * xfactor))) - (1.0 - xoffset)
        scurvemax = xfactor / (1.0 + math.exp(-1.0 * ((1.0 - xoffset) * xfactor))) - (1.0 - xoffset)
        scurveminsc = scurvemin / scurvemax

        logger.debug(
            "s-curve pass %d: xfactor=%s xoffset=%s scurvemin=%.4f scurvemax=%.4f",
            curve_num,
            xfactor,
            xoffset,
            scurvemin,
            scurvemax,
        )

        im = (
            xfactor / (1.0 + np.exp(-1.0 * ((im / DN_MAX - xoffset) * xfactor))) - (1.0 - xoffset)
        ) / scurvemax
        im = DN_MAX * (im - scurveminsc) / (1.0 - scurveminsc)

        # Upstream called rgb_sky_zero() here and discarded the result; because rgb_sky_zero
        # does not mutate its input, that call could only ever cost time (four full-image
        # passes plus histograms per s-curve step). It is intentionally not ported.

    return im


def set_minimum(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Raise near-black pixels to a floor, keeping a little of the original noise.

    Only active when ``setmin``. Noise and chromatic fringes can round down to pure black
    around stars; this puts a floor under them while retaining 20% of the local value so the
    result does not look plasticky.
    """
    if not params.setmin:
        return im

    logger.info(
        "Applying set minimum (R/G/B floors %g/%g/%g DN)",
        params.setminr,
        params.setming,
        params.setminb,
    )
    r, g, b = split_channels(im)
    zx = 0.2  # keep some of the low level, which is noise, so it looks more natural
    r = np.where(r < params.setminr, params.setminr + zx * r, r)
    g = np.where(g < params.setming, params.setming + zx * g, g)
    b = np.where(b < params.setminb, params.setminb + zx * b, b)
    return merge_channels(r, g, b)


def fix_out_of_bounds(corrected: np.ndarray, channel_name: str, mode: str = "clip") -> np.ndarray:
    """Bring a channel back into 0..65535 by clipping or rescaling (upstream ``fix_out_of_bounds``).

    The vignette/gradient subtractions below can push a channel outside the valid range; the
    reference's default is to clip, and to report how many pixels were affected.
    """
    max_val, min_val = float(np.max(corrected)), float(np.min(corrected))

    if max_val <= DN_MAX and min_val >= 0.0:
        return corrected

    count_hi = int(np.sum(corrected > DN_MAX))
    count_lo = int(np.sum(corrected < 0))
    if count_hi:
        logger.warning(
            "%s channel has %d value(s) above 0-65535; %s to fit", channel_name, count_hi, mode
        )
    if count_lo:
        logger.warning(
            "%s channel has %d value(s) below 0; %s to fit", channel_name, count_lo, mode
        )

    if mode == "clip":
        return np.clip(corrected, 0, DN_MAX)

    if mode == "scale":
        denom = max_val - min_val
        if denom == 0.0:  # guard against divide by zero
            return np.full_like(corrected, 0.0)
        return DN_MAX * (corrected - min_val) / denom

    raise ValueError(f"Invalid mode '{mode}'. Use 'clip' or 'scale'.")


# =========================================================================================
# Chromatic aberration correction
# =========================================================================================


def align_channels(im: np.ndarray) -> np.ndarray:
    """Align the R and B channels to G to reduce star chromatic aberration.

    Uses OpenCV's ECC translation-only alignment. This is the port's slowest early step and
    depends entirely on the data (a bare star field can fail to converge), so it is opt-in.
    """
    r, g, b = split_channels(im)

    def align(ref: np.ndarray, target: np.ndarray) -> np.ndarray:
        warp_matrix = np.eye(2, 3, dtype=np.float32)
        _cc, warp_matrix = cv2.findTransformECC(
            ref.astype(np.float32),
            target.astype(np.float32),
            warp_matrix,
            cv2.MOTION_TRANSLATION,
        )
        aligned = cv2.warpAffine(
            target.astype(np.float32),
            warp_matrix,
            (target.shape[1], target.shape[0]),
            flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
        )
        return aligned.astype(np.float64)

    logger.info("Aligning red channel...")
    r_aligned = align(g, r)
    logger.info("Aligning blue channel...")
    b_aligned = align(g, b)

    # RGB order (upstream merges as BGR).
    result = merge_channels(r_aligned, g, b_aligned)
    return np.clip(result, 0, DN_MAX)


def ca_correction(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Correct star chromatic aberration when ``ca_correct`` is set."""
    if not params.ca_correct:
        return im

    logger.info("Correcting star chromatic aberration")
    corrected = align_channels(im)
    logger.info("Chromatic aberration correction complete")
    return corrected


# =========================================================================================
# Vignette and gradient correction
# =========================================================================================


def subtract_vignetting(
    channel: np.ndarray, channel_name: str, params: StretchParams
) -> np.ndarray:
    """Estimate and subtract a radial vignetting pattern ``Z(r) = a*r + b*r^2 + c``.

    The coefficients come from a least-squares fit against radius, and only ``vn_strength``
    percent of the fitted background is removed (the fit is deliberately conservative - the
    guide warns that over-correcting flattens real nebulosity).
    """
    logger.info("Subtracting radial vignetting for %s channel...", channel_name)
    h, w = channel.shape

    x = np.arange(w) - w // 2
    y = np.arange(h) - h // 2
    r = np.sqrt(y[:, None] ** 2 + x[None, :] ** 2)

    # Design matrix [r, r^2, 1] against the flattened channel.
    a = np.c_[r.ravel(), (r**2).ravel(), np.ones(channel.size)]
    coeffs, _res, _rank, _sv = np.linalg.lstsq(a, channel.ravel(), rcond=None)

    background = coeffs[0] * r + coeffs[1] * r**2 + coeffs[2]
    corrected = channel - (params.vn_strength / 100.0) * background
    corrected -= corrected.min()

    log_channel_stats(corrected, channel_name)
    return fix_out_of_bounds(corrected, channel_name)


def vignette_correction(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Remove a radial vignette from each channel when ``vn_correct`` is set."""
    if not params.vn_correct or params.vn_strength == 0:
        return im

    logger.info("Subtracting radial vignetting (strength %s%%)", params.vn_strength)
    r, g, b = split_channels(im)
    r = subtract_vignetting(r, "RED", params)
    g = subtract_vignetting(g, "GREEN", params)
    b = subtract_vignetting(b, "BLUE", params)
    logger.info("Vignetting correction complete")
    return merge_channels(r, g, b)


def subtract_gradient(channel: np.ndarray, channel_name: str, params: StretchParams) -> np.ndarray:
    """Estimate and subtract a planar gradient ``Z(x, y) = a*x + b*y + c`` from a channel.

    Planar rather than radial: this is the term that removes a linear tilt (light pollution
    rising from one side, a corner-brighter field) that a radial vignette model cannot fit.
    """
    logger.info("Subtracting gradient background for %s channel...", channel_name)
    h, w = channel.shape

    x_grid, y_grid = np.meshgrid(np.arange(w), np.arange(h))
    z = channel.ravel()

    # Design matrix [x, y, 1].
    a = np.c_[x_grid.ravel(), y_grid.ravel(), np.ones_like(z)]
    coeffs, _res, _rank, _sv = np.linalg.lstsq(a, z, rcond=None)

    background = coeffs[0] * x_grid + coeffs[1] * y_grid + coeffs[2]
    corrected = channel - (params.lg_strength / 100.0) * background
    corrected -= corrected.min()

    log_channel_stats(corrected, channel_name)
    return fix_out_of_bounds(corrected, channel_name)


def gradient_correction(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Remove a planar gradient from each channel when ``lg_correct`` is set."""
    if not params.lg_correct or params.lg_strength == 0:
        return im

    logger.info("Subtracting linear gradients (strength %s%%)", params.lg_strength)
    r, g, b = split_channels(im)
    r = subtract_gradient(r, "RED", params)
    g = subtract_gradient(g, "GREEN", params)
    b = subtract_gradient(b, "BLUE", params)
    logger.info("Gradient correction complete")
    return merge_channels(r, g, b)


# =========================================================================================
# Colour correction
# =========================================================================================


def color_correct_ratio(imz: np.ndarray, im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Restore colour by comparing the stretched ratios against the un-stretched ones.

    Upstream's ``color_correction_type = ratio`` branch, split out as its own function so it
    is directly testable. ``imz`` is the sky-zeroed image *before* the stretch (the source of
    the true colour ratios), ``im`` the stretched image (whose ratios show the colour the
    stretch washed out). Applying the ratio of the two avoids the over-correction a plain
    saturation boost causes.
    """
    logger.info("Colour correction (ratio method)")

    rs, gs, bs = split_channels(imz)
    # Sky level subtracted to the real zero point, then clipped to a small positive number so
    # the divisions below cannot blow up (upstream clips to 10/65535).
    rs = np.clip(rs - params.zeroskyred, 10.0, None)
    gs = np.clip(gs - params.zeroskygreen, 10.0, None)
    bs = np.clip(bs - params.zeroskyblue, 10.0, None)

    r, g, b = split_channels(im)
    r = np.clip(r, 10.0, None)
    g = np.clip(g, 10.0, None)
    b = np.clip(b, 10.0, None)

    # The ratios are limited to 0.2..1.0: a value above 1.0 would *desaturate* (upstream's
    # comment), so the correction may only pull colours back, never push them past the
    # un-stretched ratio.
    zmin, zmax = 0.2, 1.0

    def clamp_ratio(value: np.ndarray) -> np.ndarray:
        """Limit a ratio array to 0.2..1.0 (upstream's ``zmin``/``zmax``)."""
        return np.clip(value, zmin, zmax)

    grratio = clamp_ratio((gs / rs) / (g / r))
    brratio = clamp_ratio((bs / rs) / (b / r))
    rgratio = clamp_ratio((rs / gs) / (r / g))
    bgratio = clamp_ratio((bs / gs) / (b / g))
    gbratio = clamp_ratio((gs / bs) / (g / b))
    rbratio = clamp_ratio((rs / bs) / (r / b))

    # Intensity-dependent strength: the correction is applied gently in the dark background
    # and at full strength in the bright areas, so noise in the sky is not amplified along
    # with the colour. ``cavgn`` is the mean channel value normalised to the brightest pixel.
    cavgn = np.clip((r + g + b) / 3.0 / DN_MAX, 0, None)
    cmax = float(np.amax(cavgn))
    if cmax < 1.0:
        cavgn = cavgn / cmax
    cavgn = cavgn**0.2
    cavgn = (cavgn + 0.3) / 1.3

    cfe = 1.2 * params.colorenhance * cavgn

    grratio = 1.0 + (cfe * (grratio - 1.0))
    brratio = 1.0 + (cfe * (brratio - 1.0))
    rgratio = 1.0 + (cfe * (rgratio - 1.0))
    bgratio = 1.0 + (cfe * (bgratio - 1.0))
    gbratio = 1.0 + (cfe * (gbratio - 1.0))
    rbratio = 1.0 + (cfe * (rbratio - 1.0))

    c2gr = np.abs(g * grratio)
    c3br = np.abs(b * brratio)
    c1rg = np.abs(r * rgratio)
    c3bg = np.abs(b * bgratio)
    c1rb = np.abs(r * rbratio)
    c2gb = np.abs(g * gbratio)

    # Signal-dependent recovery: each channel keeps its own value where it is the brightest
    # of the three, and receives a ratio-corrected contribution from the others. The sequence
    # matters and is ported verbatim: ``g`` is masked against the *already masked* ``r`` (and
    # ``b`` against both), which is what makes red win ties, then green, then blue.
    r = np.where(r >= g, r, 0)
    r = np.where(r >= b, r, 0)

    g = np.where(g > r, g, 0)
    g = np.where(g >= b, g, 0)

    b = np.where(b > r, b, 0)
    b = np.where(b > g, b, 0)

    rmask = np.where(r > 0, 1, 0)
    gmask = np.where(g > 0, 1, 0)
    bmask = np.where(b > 0, 1, 0)

    r = r + c1rg * gmask + c1rb * bmask
    g = g + c2gr * rmask + c2gb * bmask
    b = b + c3br * rmask + c3bg * gmask

    return np.clip(merge_channels(r, g, b), 0, DN_MAX)


def color_correct_hsv(imz: np.ndarray, im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Restore colour by taking hue/saturation from the un-stretched image and value from the stretch.

    Upstream's ``color_correction_type = hsv`` branch. Saturation is boosted by an amount
    proportional to the stretched brightness (``V ** (1/gamma)``), so faint areas gain
    saturation without the background being pushed into noise.
    """
    logger.info("Colour correction (HSV method)")

    # ``.astype`` (not ``np.float32(...)``) so the result stays an array as far as the type
    # checker is concerned - ``np.float32(x)`` is typed as the scalar.
    original = np.clip(imz / DN_MAX, 0.0, 1.0).astype(np.float32)
    stretched = np.clip(im / DN_MAX, 0.0, 1.0).astype(np.float32)

    # OpenCV float HSV expects S and V in 0..1 and H in degrees; ``_FULL`` gives 0..360 hue.
    hsv_orig = cv2.cvtColor(original, TS_FULL)
    hsv_str = cv2.cvtColor(stretched, TS_FULL)

    hue = hsv_orig[..., 0]
    sat = hsv_orig[..., 1]
    val = hsv_str[..., 2]

    sat_boost = 1.0 + params.colorenhance * (val ** (1.0 / params.gamma))
    sat = np.clip(sat * sat_boost, 0.0, 1.0)

    hsv_new = np.stack([hue, sat, val], axis=-1).astype(np.float32)
    rgb = cv2.cvtColor(hsv_new, TS_BACK_FULL)

    return np.clip(np.asarray(rgb, dtype=np.float64) * DN_MAX, 0.0, DN_MAX)


def color_correct(imz: np.ndarray, im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Dispatch to the configured colour-correction method (``color_correction_type``).

    Args:
        imz: the sky-zeroed image from *before* the stretch (the colour reference).
        im: the stretched image to correct.
    """
    if params.color_correction_type == COLORCOR_NONE:
        return im
    if params.color_correction_type == COLORCOR_RATIO:
        return color_correct_ratio(imz, im, params)
    if params.color_correction_type == COLORCOR_HSV:
        return color_correct_hsv(imz, im, params)
    raise ValueError(f"Unknown color_correction_type {params.color_correction_type}")


# =========================================================================================
# HSV adjustment and white balance
# =========================================================================================


def apply_hsv_adjust(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Adjust hue, saturation, value and vibrance in HSV space (upstream ``hsv_adjust``).

    Unlike upstream's ``color_correct`` HSV branch - which scaled to 0..1 first - the
    reference's ``hsv_adjust`` fed 0..65535 data straight into OpenCV's float HSV space, so
    every pixel came out maximally bright (S/V are expected in 0..1; ``v *= val_adjust`` on
    a value of ~50000 then clipped to 1.0). Deviation 3 in the module docstring: we normalise
    and scale back.
    """
    if not params.hsv_adjust:
        return im

    logger.info("HSV adjustment (hue %+g, saturation %g)", params.hue_adjust, params.sat_adjust)

    scaled = np.clip(im / DN_MAX, 0.0, 1.0).astype(np.float32)
    hsv = cv2.cvtColor(scaled, cv2.COLOR_RGB2HSV)
    hue, sat, val = cv2.split(hsv)

    # Float32 HSV keeps hue in degrees (0..360) and S/V in 0..1 - unlike the 8-bit form,
    # whose hue is 0..179 - so ``hue_adjust`` stays in degrees exactly as documented.
    hue = (hue + params.hue_adjust) % 360.0
    sat = sat * params.sat_adjust

    if params.vib_adjust != 0:
        # Vibrance protects already-saturated colours: the boost tapers to zero as S -> 1.
        sat = sat + params.vib_adjust * sat * (1 - sat)

    val = val * params.val_adjust

    hsv = cv2.merge([hue, np.clip(sat, 0.0, 1.0), np.clip(val, 0.0, 1.0)])
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    return np.clip(np.asarray(rgb, dtype=np.float64) * DN_MAX, 0.0, DN_MAX)


def apply_white_balance(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Neutralise a colour cast (upstream ``apply_white_balance``).

    ``wb_mode = 1`` is the gray-world assumption (scale each channel so the means match);
    ``wb_mode = 2`` applies an explicit temperature/tint adjustment, where ``temp`` moves
    red against blue and ``tint`` moves green against magenta.
    """
    if params.wb_mode == WB_NONE:
        return im

    r, g, b = split_channels(im)

    if params.wb_mode == WB_GRAY:
        logger.info("White balancing using the gray-world assumption")

        mean_gray = (float(np.mean(r)) + float(np.mean(g)) + float(np.mean(b))) / 3.0
        r = r * (mean_gray / float(np.mean(r)))
        g = g * (mean_gray / float(np.mean(g)))
        b = b * (mean_gray / float(np.mean(b)))

    elif params.wb_mode == WB_TEMP_TINT:
        logger.info("White balancing with temp %g / tint %g", params.temp, params.tint)

        r = r * params.temp
        b = b * (1.0 / params.temp)

        g = g * (1.0 / params.tint)
        magenta_boost = math.sqrt(params.tint)
        r = r * magenta_boost
        b = b * magenta_boost

    else:
        raise ValueError(f"Unknown wb_mode {params.wb_mode}")

    # RGB order (upstream merges as BGR, which only matters for the merge itself).
    return np.clip(merge_channels(r, g, b), 0.0, DN_MAX)


# =========================================================================================
# Star size reduction
# =========================================================================================


def detect_stars(image: np.ndarray, threshold_factor: float = 1.5, min_area: int = 5) -> np.ndarray:
    """Build a binary star mask by bandpass filtering (upstream ``detect_stars``).

    The difference of two Gaussians isolates small-scale structure (stars) from the smooth
    background, an adaptive threshold on that band picks the star pixels, and connected
    components below ``min_area`` are discarded so hot pixels and noise do not count.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32) / DN_MAX

    blur_small = cv2.GaussianBlur(gray, (3, 3), 0)
    blur_large = cv2.GaussianBlur(gray, (15, 15), 0)
    dog = blur_small - blur_large

    # ``meanStdDev``/``threshold`` are declared for ``UMat`` in OpenCV's stubs; the ndarray
    # form below is what the library documents for Python (hence the suppressions).
    mean, std = cv2.meanStdDev(dog)  # pyright: ignore[reportCallIssue, reportArgumentType]
    thresh_val = float((mean + threshold_factor * std)[0][0])
    _, binary_mask = cv2.threshold(  # pyright: ignore[reportCallIssue]
        dog,  # pyright: ignore[reportArgumentType]
        thresh_val,
        1.0,
        cv2.THRESH_BINARY,
    )
    binary_mask = (binary_mask * 255).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel)

    _num_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        cleaned, connectivity=8
    )
    large_components = np.where(stats[1:, cv2.CC_STAT_AREA] >= min_area)[0] + 1
    return np.isin(labels, large_components).astype(np.uint8) * 255


def preserve_core_shrink_halo(
    image: np.ndarray,
    star_mask: np.ndarray,
    erosion_size: int = 3,
    core_thresh_percentile: float = 90,
    feather_size: int = 5,
) -> np.ndarray:
    """Shrink star halos while protecting the bright cores (upstream name of the same thing).

    Star pixels brighter than the given percentile of all star pixels are the "core" and are
    left alone; the rest (halo) are eroded, and the eroded version is blended in through a
    feathered mask so the transition is not a visible ring.
    """
    image = image.astype(np.float32)
    r, g, b = split_channels(image)

    star_gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    star_pixels = star_gray[star_mask > 0]
    if len(star_pixels) == 0:
        logger.info("No stars detected; skipping star reduction pass")
        return image

    # ``asarray`` pins the element type, which is what numpy's ``percentile`` overloads want.
    core_thresh = float(
        np.percentile(np.asarray(star_pixels, dtype=np.float64), core_thresh_percentile)
    )

    core_mask = np.zeros_like(star_mask, dtype=np.float32)
    halo_mask = np.zeros_like(star_mask, dtype=np.float32)
    core_mask[(star_gray >= core_thresh) & (star_mask > 0)] = 1.0
    halo_mask[(star_gray < core_thresh) & (star_mask > 0)] = 1.0

    feathered_halo = np.clip(cv2.GaussianBlur(halo_mask, (feather_size, feather_size), 0), 0, 1)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erosion_size, erosion_size))

    def shrink_halo_only(channel: np.ndarray) -> np.ndarray:
        eroded = cv2.erode(channel, kernel, iterations=1)
        return channel * (1 - feathered_halo) + eroded * feathered_halo

    # RGB order (upstream merges as BGR).
    result = merge_channels(shrink_halo_only(r), shrink_halo_only(g), shrink_halo_only(b))
    return np.clip(result, 0, DN_MAX)


def reduce_star_sizes(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Shrink stars over three passes, with the parameters interpolated from ``reduction_strength``.

    One mask is detected up front and reused; the three passes use progressively higher core
    percentiles, so each pass touches a smaller, fainter part of the halo.
    """
    if not params.star_reduction or params.reduction_strength <= 0.0:
        return im

    strength = float(np.clip(params.reduction_strength, 0.0, 1.0))
    logger.info("Beginning star size reduction (strength %.2f)", strength)

    im = im.astype(np.float32)

    logger.info("Creating star mask...")
    star_mask = detect_stars(im)

    # Interpolated pass parameters (upstream's tables, kept as-is so results match).
    pass_params = [
        (int(1 + strength * 2), 60 + strength * 10, int(3 + strength * 4)),
        (int(1 + strength * 2), 75 + strength * 10, int(5 + strength * 4)),
        (int(1 + strength * 1), 85 + strength * 7, int(5 + strength * 4)),
    ]

    result = im
    for index, (erosion, percentile, feather) in enumerate(pass_params, start=1):
        logger.debug(
            "Star reduction pass %d: erosion=%d percentile=%.1f feather=%d",
            index,
            erosion,
            percentile,
            feather,
        )
        result = preserve_core_shrink_halo(
            result,
            star_mask,
            erosion_size=erosion,
            core_thresh_percentile=percentile,
            feather_size=feather,
        )

    logger.info("Star halo reduction complete")
    return np.asarray(result, dtype=np.float64)


# =========================================================================================
# Richardson-Lucy deconvolution
# =========================================================================================


def richardson_lucy_deconvolution(
    im: np.ndarray, params: StretchParams, use_moffat: bool = True
) -> np.ndarray:
    """Sharpen the luminance with Richardson-Lucy deconvolution (upstream name of the same thing).

    Only the luminance is deconvolved; the result is applied back to RGB as a per-pixel ratio
    (clipped to 0..5), which sharpens without shifting colour.

    ``psf_sigma`` is a Gaussian-equivalent sigma: a Moffat PSF is derived from its FWHM
    (``2.355 * sigma``), which is a better match to real stellar profiles.
    """
    if not params.rl_deconvolve:
        return im

    logger.info("Running Richardson-Lucy deconvolution (%d iterations)", params.rl_iterations)
    lum_blur_sigma = 0.5
    moffat_beta = 4.0

    normalized = im.astype(np.float64) / DN_MAX

    # Rec.709 luma weights. The reference applied these to its BGR channels, giving blue the
    # red weight (deviation 2 in the module docstring); with RGB order they land correctly.
    lum = 0.2126 * normalized[..., 0] + 0.7152 * normalized[..., 1] + 0.0722 * normalized[..., 2]

    # Mild pre-smoothing, so the deconvolution does not amplify noise.
    lum = gaussian_filter(lum, sigma=lum_blur_sigma)

    eps = 1e-6
    lum = np.clip(lum, eps, 1.0)

    size = max(3, int(np.ceil(params.psf_sigma * 8)))  # minimum kernel size of 3
    if size % 2 == 0:  # must be odd
        size += 1

    half = size // 2
    y, x = np.mgrid[-half : half + 1, -half : half + 1]
    r2 = x**2 + y**2

    if use_moffat:
        fwhm = 2.355 * params.psf_sigma
        alpha = fwhm / (2 * np.sqrt(2 ** (1 / moffat_beta) - 1))
        psf = (1 + (r2 / alpha**2)) ** (-moffat_beta)
        logger.debug("Using Moffat PSF | alpha: %.3f, beta: %s", alpha, moffat_beta)
    else:
        psf = np.exp(-r2 / (2 * params.psf_sigma**2))
        logger.debug("Using Gaussian PSF | sigma: %s", params.psf_sigma)

    psf /= psf.sum()
    logger.debug("PSF kernel size: %d", size)

    # Reflect-pad so the deconvolution does not ring along the frame edges, then unpad.
    # Note: upstream passes ``iterations=``; that keyword was renamed to ``num_iter`` in
    # scikit-image (0.26 here), so the port adapts the call, not the algorithm.
    pad = size // 2
    lum_pad = np.pad(lum, pad, mode="reflect")
    lum_processed = richardson_lucy(lum_pad, psf, num_iter=params.rl_iterations, clip=True)
    lum_processed = lum_processed[pad:-pad, pad:-pad]

    ratio = np.clip(lum_processed / (lum + eps), 0, 5)
    result = np.clip(normalized * ratio[..., None], 0, 1)

    logger.info("Richardson-Lucy deconvolution complete")
    return np.clip(result * DN_MAX, 0, DN_MAX)


# =========================================================================================
# The pipeline
# =========================================================================================


def stretch_array(im: np.ndarray, params: StretchParams) -> np.ndarray:
    """Run the whole astro-color-stretch pipeline on a 0..65535 float64 ``(H, W, 3)`` image.

    This is the reference's ``main`` block with the file I/O stripped out, in the same order
    (the ordering is what the guide's workflow documents):

    1. optional chromatic-aberration, vignette and gradient corrections (they must run before
       the sky is zeroed, since they change what "sky level" means);
    2. pick the dark-sky region, then zero each channel's sky to its ``zerosky*`` DN;
    3. keep a copy of that sky-zeroed image - it is the colour reference for step 6;
    4. the stretch, the S-curve and the optional minimum floor;
    5. colour restore, HSV adjust and white balance;
    6. optional Richardson-Lucy deconvolution and star-size reduction.

    The function is pure: no context, no filesystem, no Siril. That is what makes it testable
    with synthetic arrays, and reusable by a GUI preview later. Progress goes to this module's
    ``logger`` (the recipe script sets it so output lands in the CLI/GUI run tree).

    Args:
        im: interleaved ``(H, W, 3)`` float64 RGB data in 0..65535.
        params: the user settings (already validated by ``run``).

    Returns:
        The stretched image, same shape, 0..65535 float64.
    """
    log_image_stats(im, "input")

    im = ca_correction(im, params)
    im = vignette_correction(im, params)
    im = gradient_correction(im, params)

    ulc = select_dark_region(im, params)

    # Initial sky zero, so the stretch starts from a neutral, known black point.
    im = rgb_sky_zero(im, ulc, params)

    # The un-stretched colour reference for color_correct (upstream ``imagezf``).
    imz = np.copy(im)

    im = image_stretch(im, ulc, params)
    im = s_curve(im, params)
    im = set_minimum(im, params)

    im = color_correct(imz, im, params)
    im = apply_hsv_adjust(im, params)
    im = apply_white_balance(im, params)

    im = richardson_lucy_deconvolution(im, params)
    im = reduce_star_sizes(im, params)

    log_image_stats(im, "final")
    return np.clip(im, 0, DN_MAX)


# =========================================================================================
# FITS boundary and stage entry point
# =========================================================================================


def load_image(siril: SirilInterface) -> np.ndarray:
    """Read the stage input through Siril and return it as a 0..65535 float64 ``(H, W, 3)`` array."""
    return normalize_input(siril.get_image_pixeldata())


def save_image(siril: SirilInterface, im: np.ndarray) -> None:
    """Write a 0..65535 ``(H, W, 3)`` image back as the 0..1 float32 planar FITS colour data.

    This matches what the rest of the Starbash post-processing chain expects of a stretched
    output (VeraLux and the shipped ``merge_stars`` recipe both read this convention).
    """
    normalized = np.clip(im, 0, DN_MAX) / DN_MAX
    siril.set_image_pixeldata(to_stacked(normalized.astype(np.float32)))


def run(context: dict[str, Any]) -> None:
    """Stage entry point: read the input, stretch it and write the output.

    Called from the recipe's inline script, which sets this module's ``logger`` first (the
    ``crop.py`` convention) so progress lands in the CLI/GUI run tree. Settings come from
    ``context["parameters"]``; file paths come from the Siril interface's stage context.
    """
    started = time.time()
    logger.info(
        "astro-color-stretch %s (port of David M. Jones' version %s)", __name__, ACS_VERSION
    )

    params = StretchParams.from_context(context)
    params.validate()

    logger.info("Effective settings:")
    for line in params.describe():
        logger.info("  %s", line)

    siril = SirilInterface()
    image = load_image(siril)

    result = stretch_array(image, params)

    save_image(siril, result)
    logger.info(
        "astro-color-stretch complete - elapsed time: %s", _human_seconds(time.time() - started)
    )
