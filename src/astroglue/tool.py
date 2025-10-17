import os
import shutil
import textwrap
from glob import glob
import tempfile
import subprocess

import logging

logger = logging.getLogger(__name__)


def tool_run(cmd: str, cwd: str, commands: str = None) -> None:
    """Executes an external tool with an optional script of commands in a given working directory."""

    logger.debug(f"Running {cmd} in {cwd}: stdin={commands}")
    result = subprocess.run(
        cmd, input=commands, shell=True, capture_output=True, text=True, cwd=cwd
    )

    if result.stdout:
        logger.debug(f"Tool output:\n")
        for line in result.stdout.splitlines():
            logger.debug(line)

    if result.stderr:
        logger.warning(f"Tool error message:")
        for line in result.stderr.splitlines():
            logger.warning(line)

    if result.returncode != 0:
        logger.error(f"Tool failed with exit code {result.returncode}!")
        result.check_returncode()  # Child process returned an error code
    else:
        logger.info("Tool command successful.")


# siril_path = "/home/kevinh/packages/Siril-1.4.0~beta3-x86_64.AppImage"
siril_path = "org.siril.Siril"  # flatpak


def siril_run(cwd: str, commands: str) -> None:
    """Executes Siril with a script of commands in a given working directory."""

    # We dedent here because the commands are often indented multiline strings
    script_content = textwrap.dedent(
        f"""
        requires 1.4.0-beta3
        {textwrap.dedent(commands)}
        """
    )

    # The `-s -` arguments tell Siril to run in script mode and read commands from stdin.
    # It seems like the -d command may also be required when siril is in a flatpak
    cmd = f"{siril_path} -d {cwd} -s -"

    tool_run(cmd, cwd, script_content)


def graxpert_run(cwd: str, arguments: str) -> None:
    """Executes Graxpert with the specified command line arguments"""

    # Arguments look similar to: graxpert -cmd background-extraction -output /tmp/testout tests/test_images/real_crummy.fits
    cmd = f"graxpert {arguments}"

    tool_run(cmd, cwd)


def siril_run_in_temp_dir(input_files: list[str], commands: str) -> None:
    # Create a temporary directory for processing
    temp_dir = tempfile.mkdtemp(prefix="siril_")

    # Create symbolic links for all input files in the temp directory
    for f in input_files:
        os.symlink(
            os.path.abspath(str(f)), os.path.join(temp_dir, os.path.basename(str(f)))
        )

    # Run Siril commands in the temporary directory
    try:
        logger.info(
            f"Running Siril in temporary directory: {temp_dir}, cmds {commands}"
        )
        siril_run(temp_dir, commands)
    finally:
        shutil.rmtree(temp_dir)
