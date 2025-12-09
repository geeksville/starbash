from dataclasses import dataclass
from typing import Any

from tomlkit import aot, table
from tomlkit.items import AoT

from repo import Repo
from starbash.safety import get_safe


class ParameterObject:
    """Simple object to hold parameter attributes."""

    pass


@dataclass
class Parameter:
    """Describes a parameter or override"""

    source: Repo  # The repo where this parameter/override was defined
    name: str

    description: str | None = None

    default: Any | None = (
        None  # Only used in [[parameters]] toml - specifies the value to use if not overridden
    )
    value: Any | None = None  # Only used in [[overrides]] toml - species an overriden value

    @property
    def is_override(self) -> bool:
        """Return True if this Parameter is an override (i.e. has a value)"""
        return self.value is not None


class ParameterStore:
    """Store for parameters and overrides from multiple repos."""

    def __init__(self):
        # Store parameters keyed by name. Later additions override earlier ones.
        self._parameters: list[Parameter] = []

    def add_from_repo(self, repo: Repo) -> None:
        """Look at the toml file in the repo and add any parameters/overrides defined there."""
        config = repo.config

        # Process [[parameters]] array-of-tables
        param_list = config.get("parameters", [])
        for param in param_list:
            name = param.get("name")
            # If the AoT is empty we'll get a single empty table - ignore it
            if not name:
                continue

            p = Parameter(
                source=repo,
                name=name,
                description=param.get("description"),
                default=get_safe(param, "default"),
            )
            self._parameters.append(p)

        # Process [[overrides]] array-of-tables
        override_list = config.get("overrides", [])
        for override in override_list:
            name = override.get("name")
            # If the AoT is empty we'll get a single empty table - ignore it
            if not name:
                continue

            value = get_safe(override, "value")

            # Create new parameter with just the override
            p = Parameter(
                source=repo,
                name=name,
                description=override.get("description"),
                value=value,
            )
            # Just blindly append the override - it will be applied last when generating as_obj
            self._parameters.append(p)

    def write_overrides(self, repo: Repo) -> None:
        """Write any overrides for the given repo to its starbash.toml file.

        We do this by looking in the toml to see if it already contains an [[overrides]] section.
        If it does we assume any overrides we have in our store are already there.
        For **all** parameters that are not overrides, we write TOML comments with example override entries based on
        the parameters, description, name and default value.
        We write these comments just after the [[overrides]] section.  If necessary we will create an empty [[overrides]]."""
        config = repo.config

        # Get or create [[overrides]] section
        overrides_aot: AoT | None = config.get("overrides")
        has_existing_overrides = False
        existing_overrides: set[str] = set()  # the names of existing overrides
        if overrides_aot is None or not isinstance(overrides_aot, AoT):
            overrides_aot = aot()
            config["overrides"] = overrides_aot
        else:
            # Check if there are existing overrides
            has_existing_overrides = len(list(overrides_aot)) > 0
            if has_existing_overrides:
                # remove all empty tables from the overrides_aot list, but be careful to not create a new list.
                # must do in-place removal to keep tomlkit happy
                indices_to_remove = []
                for i, item in enumerate(overrides_aot):
                    name = item.get("name")
                    if not name:
                        indices_to_remove.append(i)
                    else:
                        existing_overrides.add(name)

                for i in reversed(indices_to_remove):
                    del overrides_aot[i]

                # Update has_existing_overrides after removal
                has_existing_overrides = len(list(overrides_aot)) > 0

        # If no existing overrides, we need to add commented examples
        if len(self._parameters) > 0:
            # Build comment lines for all parameters without overrides
            comment_lines: list[str] = []
            comment_lines.append(
                "# Uncomment and modify any of the following to override parameters:"
            )

            if not has_existing_overrides:  # FIXME, currently addeding these comments causes comments to grow without bounds if there are any overrides
                for param in self._parameters:
                    if not param.is_override and param.name not in existing_overrides:
                        comment_lines.append("#")
                        comment_lines.append("# [[overrides]]")
                        name_line = f'# name = "{param.name}"'
                        if param.description:
                            name_line += f" # {param.description}"
                        comment_lines.append(name_line)
                        if param.default is not None:
                            if isinstance(param.default, str):
                                comment_lines.append(f'# value = "{param.default}"')
                            else:
                                comment_lines.append(f"# value = {param.default}")

                comment_lines.append("")  # one blank line at the end

            if not has_existing_overrides:
                # Add a dummy entry so the AoT gets written
                dummy = table()
                overrides_aot.append(dummy)
                last = dummy
            else:
                last = overrides_aot[-1]

            # join the comments into a single multiline string, then add it as a comment to overrides_aot
            comment_str = "\n".join(comment_lines)
            # tomlkit has a bug, comments on AoT are not rendered.  So add it to the last entry instead
            last.comment(comment_str)

    @property
    def as_obj(self) -> ParameterObject:
        """Return the parameters/overrides as an object suitable for including as context.parameters.

        Note: if there are multiple overrides for the same parameter name, the last one added takes precedence.
        If there is no override for a parameter, its default value is used."""
        result = ParameterObject()
        for param in self._parameters:
            # Use override value if present, otherwise use default
            if param.is_override:
                setattr(result, param.name, param.value)
            elif not hasattr(
                result, param.name
            ):  # only set default if not already set by an override
                setattr(result, param.name, param.default)
        return result
