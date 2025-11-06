# pyright: reportUndefinedVariable=false
# ('context' and 'logger' are injected by the starbash runtime)

import os
from glob import glob
from starbash.tool import tools
from starbash.aliases import normalize_target_name

siril = tools["siril"]

delete_temps = False


# FIXME move this into main starbash
def perhaps_delete_temps(temps: list[str]) -> None:
    if delete_temps:
        for t in temps:
            for path in glob(f"{context['process_dir']}/{t}_*"):
                os.remove(path)


def make_stacked(sessionconfig: str, variant: str, output_file: str):
    """
    Registers and stacks all pre-processed light frames for a given filter configuration
    across all sessions.
    """
    # The sequence name for all frames of this variant across all sessions
    # e.g. Ha_bkg_pp_light_cHaOiii
    merged_seq_base = f"all_{variant}_bkg_pp_light"

    # Absolute path for the output stacked file
    stacked_output_path = glob(f"{context["process_dir"]}/{output_file}.fit*")

    if stacked_output_path:
        logger.info(f"Using existing stacked file: {stacked_output_path}")
    else:
        # Merge all frames (from multiple sessions and configs) use those for stacking
        frames = glob(f"{context["process_dir"]}/{variant}_bkg_pp_light_s*.fit*")

        logger.info(
            f"Registering and stacking {len(frames)} frames for {sessionconfig}/{variant} -> {stacked_output_path}"
        )
        assert (
            len(frames) > 1
        ), f"Need at least two frames for {sessionconfig}/{variant}"

        # Siril commands for registration and stacking. We run this in process_dir.
        commands = f"""
            link {merged_seq_base} -out={context["process_dir"]}
            cd {context["process_dir"]}

            register {merged_seq_base}
            stack r_{merged_seq_base} rej g 0.3 0.05 -filter-wfwhm=3k -norm=addscale -output_norm -32b -out={output_file}

            # and flip if required
            mirrorx_single {output_file}
            """

        context["input_files"] = frames
        siril.run(commands, context=context)

    perhaps_delete_temps([merged_seq_base, f"r_{merged_seq_base}"])


def make_renormalize():
    """
    Aligns the stacked images (Sii, Ha, OIII) and renormalizes Sii and OIII
    to match the flux of the Ha channel.
    """
    logger.info("Aligning and renormalizing stacked images.")

    # Define file basenames for the stacked images created in the 'process' directory
    ha_base = "results_00001"
    oiii_base = "results_00002"
    sii_base = "results_00003"

    # Define final output paths. The 'results' directory is a symlink in the work dir.
    results_dir = context["output"]["base_path"]
    os.makedirs(results_dir, exist_ok=True)

    ha_final_path = f"{results_dir}/stacked_Ha.fits"
    oiii_final_path = f"{results_dir}/stacked_OIII.fits"

    # Check if final files already exist to allow resuming
    if all(os.path.exists(f) for f in [ha_final_path, oiii_final_path]):
        logger.info("Renormalized files already exist, skipping.")
        return

    # Basenames for registered files (output of 'register' command)
    r_ha = f"r_{ha_base}"
    r_oiii = f"r_{oiii_base}"

    # Pixel math formula for renormalization.
    # It matches the median and spread (MAD) of a channel to a reference channel (Ha).
    # Formula: new = old * (MAD(ref)/MAD(old)) - (MAD(ref)/MAD(old)) * MEDIAN(old) + MEDIAN(ref)
    pm_oiii = f'"${r_oiii}$*mad(${r_ha}$)/mad(${r_oiii}$)-mad(${r_ha}$)/mad(${r_oiii}$)*median(${r_oiii}$)+median(${r_ha}$)"'

    # Siril commands to be executed in the 'process' directory
    commands = f"""
        # -transf=shift fails sometimes, which I guess is possible because we have multiple sessions with possible different camera rotation
        # -interp=none also fails sometimes, so let default interp happen
        register results
        pm {pm_oiii}
        update_key FILTER Oiii "OSC dual Duo filter extracted"
        save "{oiii_final_path}"
        load {r_ha}
        update_key FILTER Ha "OSC dual Duo filter extracted"
        save "{ha_final_path}"
        """

    if os.path.exists(f"{results_dir}/{sii_base}.fit"):
        logger.info(f"Doing renormalisation of extra Sii channel")

        sii_final_path = f"{results_dir}/stacked_Sii.fits"
        r_sii = f"r_{sii_base}"
        pm_sii = f'"${r_sii}$*mad(${r_ha}$)/mad(${r_sii}$)-mad(${r_ha}$)/mad(${r_sii}$)*median(${r_sii}$)+median(${r_ha}$)"'
        commands += f"""
            pm {pm_sii}
            update_key FILTER Sii "OSC dual Duo filter extracted"
            save "{sii_final_path}"
            """

    siril.run(commands, context=context, cwd=context["process_dir"])
    logger.info(f"Saved final renormalized images to {results_dir}")


def osc_dual_duo_post_session():
    logger.info("Running osc_dual_duo_post_session python script")
    logger.info("Using context: %s", context)

    # red output channel - from the SiiOiii filter Sii is on the 672nm red channel (mistakenly called Ha by siril)
    make_stacked("SiiOiii", "Ha", f"results_00001")

    # green output channel - from the HaOiii filter Ha is on the 656nm red channel
    make_stacked("HaOiii", "Ha", f"results_00001")

    # blue output channel - both filters have Oiii on the 500nm blue channel.  Note the case here is uppercase to match siril output
    make_stacked("*", "OIII", f"results_00002")

    # There might be an old/state autogenerated .seq file, delete it so it doesn't confuse renormalize
    results_seq_path = f"{context["process_dir"]}/results_.seq"
    if os.path.exists(results_seq_path):
        os.remove(results_seq_path)

    make_renormalize()


osc_dual_duo_post_session()
