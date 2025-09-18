

import os
import shutil
import textwrap
from glob import glob
import tempfile
import subprocess

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

    logger.info(f"Running Siril command in {cwd}")
    result = subprocess.run(
        cmd, 
        input=script_content, 
        shell=True, 
        capture_output=True, 
        text=True, 
        cwd=cwd
    )

    if result.returncode != 0:
        logger.error(f"Siril command failed with exit code {result.returncode}!")
        logger.error(f"STDOUT:\n{result.stdout}")
        logger.error(f"STDERR:\n{result.stderr}")
        result.check_returncode()  # Child process returned an error code
    else:
        logger.info("Siril command successful.")
        if result.stdout:
            logger.info(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            # Siril often prints info to stderr, so we log it as info on success
            logger.info(f"STDERR:\n{result.stderr}")


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
    frames = glob(f"{masters_raw}/{date}/BIAS/{date}_*.fits")        
    output = f"{masters}/biases/{date}_stacked.fits"

    siril_run_in_temp_dir(frames, textwrap.dedent(f"""
        # Convert Bias Frames to .fit files
        link bias -out={process_dir}
        cd {process_dir}

        # Stack Bias Frames to bias_stacked.fit
        stack bias rej 3 3 -nonorm -out={output}
        """))
    

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