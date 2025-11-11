from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

import tomlkit
from tomlkit.toml_file import TOMLFile

from starbash import url


def toml_from_template(
    template_name: str, dest_path: Path, overrides: dict[str, Any] = {}
) -> tomlkit.TOMLDocument:
    """Load a TOML document from a template file.
    expand {vars} in the template using the `overrides` dictionary.
    """

    tomlstr = resources.files("starbash").joinpath(f"templates/{template_name}.toml").read_text()

    # add default vars always available
    vars = {"PROJECT_URL": url.project}
    vars.update(overrides)
    t = Template(tomlstr)
    tomlstr = t.substitute(vars)

    toml = tomlkit.parse(tomlstr)

    # create parent dirs as needed
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # write the resulting toml
    TOMLFile(dest_path).write(toml)
    return toml
