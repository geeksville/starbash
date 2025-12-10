from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

import tomlkit
from tomlkit.exceptions import ConvertError
from tomlkit.items import Array, Item
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
        s = self.__str__()
        result = tomlkit.string(s)
        c = self.get_comment
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
    if obj is None:
        return tomlkit.string(
            "NonePlaceholder"
        )  # FIXME if we have Nones inside of dicts it would be better to just drop that key?

    raise ConvertError(f"Object of type {obj.__class__.__name__} is not TOML serializable")


tomlkit.register_encoder(_toml_encoder)


def toml_from_list(items: list[Any]) -> Array:
    """Convert a list of items to a tomlkit Array - with nice AsTomlMixin comments."""
    arr = tomlkit.array()
    for item in items:
        if isinstance(item, AsTomlMixin):
            arr.add_line(item.as_toml, comment=item.get_comment)
        elif isinstance(item, dict):
            arr.add_line(tomlkit.item(item))
        else:
            arr.add_line(item)

    arr.add_line()  # MUST add a trailing line so the closing ] is on its own line
    return arr


def toml_from_template(
    template_name: str, dest_path: Path | None = None, overrides: dict[str, Any] | None = {}
) -> tomlkit.TOMLDocument:
    """Load a TOML document from a template file.
    expand {vars} in the template using the `overrides` dictionary.

    Args:
        template_name (str): name of the template file (without .toml extension)
        dest_path (Path | None, optional): if provided, write the resulting toml to
            this path. Defaults to None.
        overrides (dict[str, Any], optional): variables to override in the template. If None, no overrides.
    """

    tomlstr = resources.files("starbash").joinpath(f"templates/{template_name}.toml").read_text()

    if overrides is not None:
        # add default vars always available
        vars = {"PROJECT_URL": url.project}
        vars.update(overrides)
        t = Template(tomlstr)
        tomlstr = t.substitute(vars)

    toml = tomlkit.parse(tomlstr)

    if dest_path is not None:
        # create parent dirs as needed
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # write the resulting toml
        TOMLFile(dest_path).write(toml)
    return toml
