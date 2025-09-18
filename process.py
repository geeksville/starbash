

import os
import shutil
import textwrap
from glob import glob
import tempfile
import subprocess
import re

import logging
logger = logging.getLogger(__name__)

target="NGC 281"

# paths of the form
# /images/from_astroboy/NGC 281/2025-09-16/FLAT/2025-09-17_00-00-29_HaOiii_-9.90_6.22s_0002.fits
# /images/from_astroboy/NGC 281/2025-09-16/LIGHT/2025-09-17_00-43-32_SiiOiii_-9.90_120.00s_0006.fits
repo="/images/from_astroboy"
siril_work="/images/siril_new"
process_dir=f"{siril_work}/process"

# directories of the form /images/from_astroboy/masters-raw/2025-09-09/BIAS/2025-09-09_20-33-19_Dark_-9.70_0.00s_0030.fits
masters_raw="/images/from_astroboy/masters-raw"

# Generated from masters raw
masters="/images/masters"

def siril_run(cwd, commands):
    """Executes Siril with a script of commands in a given working directory."""
    script_content = textwrap.dedent(f"""
        requires 1.4.0-beta3
        {commands}
        """)
    
    # The `-s -` arguments tell Siril to run in script mode and read commands from stdin.
    cmd = f"org.siril.Siril -d {cwd} -s -"

    logger.debug(f"Running Siril command in {cwd}: {commands}")
    result = subprocess.run(
        cmd, 
        input=script_content, 
        shell=True, 
        capture_output=True, 
        text=True, 
        cwd=cwd
    )

    if result.stdout:
        logger.debug(f"Siril output:\n")
        for line in result.stdout.splitlines():
            logger.debug(line)

    if result.stderr:
        logger.warning(f"Siril error message:")
        for line in result.stderr.splitlines():
            logger.warning(line)

    if result.returncode != 0:
        logger.error(f"Siril command failed with exit code {result.returncode}!")
        result.check_returncode()  # Child process returned an error code
    else:
        logger.info("Siril command successful.")



def siril_run_in_temp_dir(input_files, commands):
    # Create a temporary directory for processing
    temp_dir = tempfile.mkdtemp(prefix="siril_")

    # Create symbolic links for all input files in the temp directory
    for f in input_files:
        os.symlink(os.path.abspath(str(f)), os.path.join(temp_dir, os.path.basename(str(f))))

    # Run Siril commands in the temporary directory
    try:
        logger.info(f"Running Siril in temporary directory: {temp_dir}, cmds {commands}")
        siril_run(temp_dir, commands)
    finally:
        shutil.rmtree(temp_dir)


def get_master_bias_path():
    date = "2025-09-09"  # FIXME - later find latest date with bias frames
    output = f"{masters}/biases/{date}_stacked.fits"

    if os.path.exists(output):
        logger.info(f"Using existing master bias: {output}")
        return output
    else:
        frames = glob(f"{masters_raw}/{date}/BIAS/{date}_*.fits")

        siril_run_in_temp_dir(frames, textwrap.dedent(f"""
            # Convert Bias Frames to .fit files
            link bias -out={process_dir}
            cd {process_dir}

            # Stack Bias Frames to bias_stacked.fit
            stack bias rej 3 3 -nonorm -out={output}
            """))
        
        return output
    

def get_sessions(target):
    """
    Finds session directories for a given target.
    A session directory is expected to be a direct subdirectory of the target's path,
    with a name in the format YYYY-MM-DD.
    Returns a list of directory names (e.g., ['2025-09-16']).
    """
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    base_path = f"{repo}/{target}"
    
    if not os.path.isdir(base_path):
        logger.warning(f"Target directory not found: {base_path}")
        return []

    return [entry.name for entry in os.scandir(base_path)
            if entry.is_dir() and date_pattern.match(entry.name)]

def get_session_configs(sessionid):
    """
    Finds filter configurations for a given session by inspecting FLAT filenames.

    It looks for files in the session's FLAT directory and parses the filter name
    from filenames like 'DATE_TIME_FILTER_...'.

    Args:
        sessionid (str): The ID of the session, typically a date like '2025-09-16'.

    Returns:
        list[str]: A list of unique filter names found (e.g., ['HaOiii', 'SiiOiii']).
    """
    flat_dir = f"{repo}/{target}/{sessionid}/FLAT"
    if not os.path.isdir(flat_dir):
        logger.warning(f"FLAT directory not found for session {sessionid} at {flat_dir}")
        return []

    # Regex to capture the filter name (3rd component) from filenames like:
    # 2025-09-17_00-00-13_HaOiii_-10.00_6.22s_0000.fits
    filter_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(?P<filter>[^_]+)_.+\.fits$")

    # Use a set comprehension to efficiently find unique filter names from filenames.
    filters = {match.group('filter') for f in os.listdir(flat_dir) if (match := filter_pattern.match(f))}

    found_filters = sorted(list(filters))
    logger.info(f"Found filters for session {sessionid}: {found_filters}")
    return found_filters
"""
notes:

inputs:
targets have session (listed by sessionid(date) typically one per night)
each session has a sessionconfig (different filter names)
each session config has flats and lights

masters_raw:
    <date>/BIAS/*.fits

outputs:
  masters:
    bias

process: (one big flat directory)
  s<sessionid>_c<sessionconfig>_:
    flat.fits
    pp_light.seq (= calibrated lights)
    bkg_pp_light.seq (= calibrated and linear background corrected lights)

    Ha_bkg_pp_light.seq (seq extract by color)
    Oiii_bkg_pp_light.seq (seq extract by color)    

  c<sessionconfig>_: (accross all sessions, but per config)
    r_Ha_bkg_pp_light.seq (registered)  
    stacked_r_Ha_bkg_pp_light.fit (stacked)
    flipped_00001.fit (flipped for Ha)

    r_Oiii_bkg_pp_light.seq (registered)
    stacked_r_Oiii_bkg_pp_light.fit (stacked)
    flipped_00002.fit (flipped for Oiii)

    FIXME - later add 03 for Sii, and stack the two Oiii variants together
    r_Sii_bkg_pp_light.seq (registered)
    stacked_r_Sii_bkg_pp_light.fit (stacked)
    flipped_00003.fit (flipped for Sii)

    r_flipped.seq (flipped and registered)

preprocessed: (high value output files)
    result_Ha.fit
    result_Oiii.fit

later:
    result_Sii.fit
    graxpert bkg removal
    result_HaOiiiSii.fit (combined Ha, Oiii, Sii via pixel math post graxpert)
    with and without stars

FIXME:
  add caching of masters and flats in TBD directories
"""

def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s - %(message)s')
    logger.info("Starting processing")

    # find/create master bias as needed
    bias = get_master_bias_path()

    sessions = get_sessions(target)
    for sessionid in sessions:
        for sessionconfig in get_session_configs(sessionid):
            # find/create flat.fits as needed
            flat = get_flat_path(sessionid, sessionconfig, bias)
            make_pp_light()
            make_bkg_pp_light()
            seqextract_HaOiii()
    
    for sessionconfig in get_current_configs():
        make_registered()
        make_stacked()
        make_flipped()
        make_registered_flipped()
        make_result_Ha()
        make_result_Oiii()
    pass

if __name__ == "__main__":
    main()