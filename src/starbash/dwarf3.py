"""Dwarf3 FITS header extension utilities."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from starbash.database import Database


def _extract_temperature(filename: str) -> float | None:
    """Extract temperature from filename in format like '16C' or '20C'.

    Args:
        filename: The filename to parse

    Returns:
        Temperature as float if found, None otherwise
    """
    # Match temperature in formats like _16C. or _20C_ or _20C.fits
    temp_match = re.search(r"_(\d+)C[._]", filename)
    if temp_match:
        return float(temp_match.group(1))
    return None


def _make_monotonic_datetime() -> str:
    """Return a guaranteed unique date starting Jan 1, 2000.  Increment by 1 hour per
    each call."""
    from datetime import datetime, timedelta

    # Use a function attribute to track call count
    if not hasattr(_make_monotonic_datetime, "counter"):
        _make_monotonic_datetime.counter = 0

    # Set base date to Jan 1, 2000 for factory calibration frames
    base = datetime(2000, 1, 1, 0, 0, 0)

    # Increment by 1 hour per call
    current = base + timedelta(hours=_make_monotonic_datetime.counter)
    _make_monotonic_datetime.counter += 1

    # Format as ISO 8601 with milliseconds
    return current.strftime("%Y-%m-%dT%H:%M:%S.000")


def extend_dwarf3_headers(headers: dict[str, Any], full_image_path: Path) -> bool:
    """Given a FITS header dictionary, if it was from a Dwarf3 extend it with additional computed fields.

    Returns True if headers were successfully extended, False otherwise.
    """
    short_path = headers["path"]
    # logging.debug(f"Dwarf3 check: {short_path}")

    # Check which type of Dwarf3 frame this is
    is_cali_frame = "CALI_FRAME" in short_path
    is_extra_dark_frame = "DWARF_DARK" in short_path

    # Check if this is a light frame by looking for shotsInfo.json in the parent directory
    is_light_frame = (full_image_path.parent / "shotsInfo.json").exists()

    # If none of these conditions match, this isn't a Dwarf3 file we need to process
    if not (is_cali_frame or is_extra_dark_frame or is_light_frame):
        return False

    # Determine camera/instrument from path (cam_0 = TELE, cam_1 = WIDE)
    if "cam_0" in short_path or "TELE" in short_path or "_tele_" in short_path.lower():
        headers[Database.INSTRUME_KEY] = "TELE"
    elif "cam_1" in short_path or "WIDE" in short_path or "_wide_" in short_path.lower():
        headers[Database.INSTRUME_KEY] = "WIDE"
    else:
        # Default to TELE if we can't determine
        headers[Database.INSTRUME_KEY] = "TELE"

    # Conceptually there are two different optical/paths/telescopes inside the Dwarf3.  We need to treat them differently
    # i.e. separate sets of flats/biases/lights etc...  So we give them different instrument names (D3TELE or D3WIDE)
    headers[Database.TELESCOP_KEY] = "D3" + headers["INSTRUME"]

    # Process CALI_FRAME files (bias/dark/flat from factory)
    if is_cali_frame:
        headers[Database.DATE_OBS_KEY] = _make_monotonic_datetime()

        # Determine frame type from path
        if "/bias/" in short_path:
            headers[Database.IMAGETYP_KEY] = "bias"
            headers[Database.EXPTIME_KEY] = 0.001  # bias frames have very short exposure times

            # Parse gain from filename: bias_gain_2_bin_1.fits
            gain_match = re.search(r"gain[_-](\d+)", full_image_path.name)
            if gain_match:
                headers[Database.GAIN_KEY] = int(gain_match.group(1))

        elif "/dark/" in short_path:
            headers[Database.IMAGETYP_KEY] = "dark"

            # Parse exposure and gain from filename: dark_exp_60.000000_gain_60_bin_1_20C_stack_8.fits
            exp_match = re.search(r"exp[_-]([\d.]+)", full_image_path.name)
            if exp_match:
                headers[Database.EXPTIME_KEY] = float(exp_match.group(1))

            gain_match = re.search(r"gain[_-](\d+)", full_image_path.name)
            if gain_match:
                headers[Database.GAIN_KEY] = int(gain_match.group(1))

            # Extract temperature if present
            temp = _extract_temperature(full_image_path.name)
            if temp is not None:
                headers["CCD-TEMP"] = temp

        elif "/flat/" in short_path:
            headers[Database.IMAGETYP_KEY] = "flat"
            headers[Database.EXPTIME_KEY] = 0.0  # Flats typically don't specify exposure

            # Parse gain from filename: flat_gain_2_bin_1_ir_0.fits
            gain_match = re.search(r"gain[_-](\d+)", full_image_path.name)
            if gain_match:
                headers[Database.GAIN_KEY] = int(gain_match.group(1))

            # Parse filter from ir number (0=VIS, 1=Astro, 2=Duo)
            ir_match = re.search(r"ir[_-](\d+)", full_image_path.name)
            if ir_match:
                ir_num = int(ir_match.group(1))
                filter_map = {0: "VIS", 1: "Astro", 2: "Duo"}
                headers[Database.FILTER_KEY] = filter_map.get(ir_num, "Unknown")

    # Process DWARF_DARK files (user-captured dark frames)
    elif is_extra_dark_frame:
        headers[Database.IMAGETYP_KEY] = "dark"

        # These dwarflab frames have some bogus fits data we don't want to confuse recipes with
        bad_keys = [Database.FILTER_KEY, "RA", "DEC", Database.OBJECT_KEY]
        for key in bad_keys:
            headers.pop(key, None)

        # Parse filename: raw_60s_60_0002_20251020-032310186_20C.fits
        # Format: raw_{exp}s_{gain}_{frame_num}_{datetime}_{temp}C.fits
        filename = full_image_path.name

        # Extract exposure time
        exp_match = re.search(r"raw_(\d+)s", filename)
        if exp_match:
            headers[Database.EXPTIME_KEY] = float(exp_match.group(1))

        # Extract gain
        gain_match = re.search(r"s_(\d+)_\d{4}_", filename)
        if gain_match:
            headers[Database.GAIN_KEY] = int(gain_match.group(1))

        # Extract date-time: 20251020-032310186 -> 2025-10-20T03:23:10.186
        date_match = re.search(r"(\d{8})-(\d{2})(\d{2})(\d{2})(\d{3})", filename)
        if date_match:
            date_str = date_match.group(1)  # YYYYMMDD
            hh = date_match.group(2)
            mm = date_match.group(3)
            ss = date_match.group(4)
            ms = date_match.group(5)

            # Format as ISO 8601
            year = date_str[0:4]
            month = date_str[4:6]
            day = date_str[6:8]
            headers[Database.DATE_OBS_KEY] = f"{year}-{month}-{day}T{hh}:{mm}:{ss}.{ms}"

        # Extract temperature if present
        temp = _extract_temperature(filename)
        if temp is not None:
            headers["CCD-TEMP"] = temp

    # Process light frames (from shotsInfo.json)
    elif is_light_frame:
        headers[Database.IMAGETYP_KEY] = "light"

        # Read shotsInfo.json
        shots_info_path = full_image_path.parent / "shotsInfo.json"
        try:
            with open(shots_info_path) as f:
                shots_info = json.load(f)

            # Extract metadata from shotsInfo.json
            if "exp" in shots_info:
                headers[Database.EXPTIME_KEY] = float(shots_info["exp"])

            if "gain" in shots_info:
                headers[Database.GAIN_KEY] = int(shots_info["gain"])

            if "ir" in shots_info:
                headers[Database.FILTER_KEY] = shots_info["ir"]

            if "target" in shots_info:
                headers["OBJECT"] = shots_info["target"]

        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logging.warning(f"Could not read shotsInfo.json for {full_image_path}: {e}")

        # Also parse date from filename: IC 434_60s60_Astro_20251018-045926401_16C.fits
        # Format: {target}_{exp}s{gain}_{filter}_{datetime}_{temp}C.fits
        filename = full_image_path.name
        date_match = re.search(r"(\d{8})-(\d{2})(\d{2})(\d{2})(\d{3})", filename)
        if date_match:
            date_str = date_match.group(1)  # YYYYMMDD
            hh = date_match.group(2)
            mm = date_match.group(3)
            ss = date_match.group(4)
            ms = date_match.group(5)

            # Format as ISO 8601
            year = date_str[0:4]
            month = date_str[4:6]
            day = date_str[6:8]
            headers[Database.DATE_OBS_KEY] = f"{year}-{month}-{day}T{hh}:{mm}:{ss}.{ms}"

        # Extract temperature if present
        temp = _extract_temperature(filename)
        if temp is not None:
            headers["CCD-TEMP"] = temp

    return True
