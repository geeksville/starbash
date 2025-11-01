import tomlkit
from tomlkit.toml_file import TOMLFile
from pathlib import Path
from importlib import resources
from typing import Any

from starbash import url

def toml_from_template(template_name: str, dest_path: Path, overrides: dict[str, Any] = {}) -> tomlkit.TOMLDocument:
    """Load a TOML document from a template file.
    expand {vars} in the template using the `overrides` dictionary.
    """

    tomlstr = (
        resources.files("starbash")
        .joinpath(f"templates/{template_name}.toml")
        .read_text()
    )

    # add default vars always available
    vars = {
        "PROJECT_URL": url.project
    }
    vars.update(overrides)
    tomlstr = tomlstr.format(**vars)

    toml = tomlkit.parse(tomlstr)
    TOMLFile(dest_path).write(toml)
    return toml
