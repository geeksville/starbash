from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

import tomlkit
from tomlkit.exceptions import ConvertError
from tomlkit.items import Item
from tomlkit.toml_file import TOMLFile

from starbash import url

__all__ = [
    "toml_from_template",
]


class AsTomlMixin(ABC):
    """Mixin to provide a .as_toml property for converting to a tomlkit Item with comment."""

    @property
    @abstractmethod
    def get_comment(self) -> str | None:
        """Human friendly comment for this field."""
        return None

    @property
    def as_toml(self) -> Item:
        """As a formatted toml node with documentation comment"""
        s = str(self)
        result = tomlkit.string(s)
        c = self.comment
        if c:
            result.comment(c)
        return result


@dataclass
class CommentedString(AsTomlMixin):
    """A string with optional comment for toml serialization."""

    value: str
    comment: str | None

    @property
    def get_comment(self) -> str | None:
        """Human friendly comment for this field."""
        return self.comment

    def __str__(self) -> str:
        return self.value


def _toml_encoder(obj: Any) -> Item:
    if isinstance(obj, AsTomlMixin):
        return obj.as_toml
    raise ConvertError(f"Object of type {obj.__class__.__name__} is not TOML serializable")


tomlkit.register_encoder(_toml_encoder)


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
