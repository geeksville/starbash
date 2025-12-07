from dataclasses import dataclass
from typing import Any

import tomlkit
from tomlkit import aot, table

from repo import Repo
from starbash.safety import get_safe


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
        self._parameters: dict[str, Parameter] = {}

    def add_from_repo(self, repo: Repo) -> None:
        """Look at the toml file in the repo and add any parameters/overrides defined there."""
        config = repo.config

        # Process [[parameters]] array-of-tables
        param_list = config.get("parameters", [])
        for param in param_list:
            p = Parameter(
                source=repo,
                name=param["name"],
                description=param.get("description"),
                default=param.get("default"),
            )
            self._parameters[p.name] = p

        # Process [[overrides]] array-of-tables
        override_list = config.get("overrides", [])
        for override in override_list:
            name = get_safe(override, "name")
            # Get existing parameter or create new one
            existing = self._parameters.get(name)
            value = get_safe(override, "value")
            if existing:
                # Update existing parameter with override value
                existing.value = value
                existing.source = repo
            else:
                # Create new parameter with just the override
                p = Parameter(
                    source=repo,
                    name=name,
                    description=override.get("description"),
                    value=value,
                )
                self._parameters[name] = p

    def write_overrides(self, repo: Repo) -> None:
        """Write any overrides for the given repo to its starbash.toml file.

        We do this by looking in the toml to see if it already contains an [[overrides]] section.
        If it does we assume any overrides we have in our store are already there.
        For **all** parameters that are not overrides, we write TOML comments with example override entries based on
        the parameters, description, name and default value.
        We write these comments just after the [[overrides]] section.  If necessary we will create an empty [[overrides]]."""
        config = repo.config

        # Get or create [[overrides]] section
        overrides_aot = config.get("overrides")
        has_existing_overrides = False
        if overrides_aot is None:
            overrides_aot = aot()
            config["overrides"] = overrides_aot
        else:
            # Check if there are existing overrides
            has_existing_overrides = len(list(overrides_aot)) > 0

        # If no existing overrides, we need to add commented examples
        if not has_existing_overrides and len(self._parameters) > 0:
            # Build comment lines for all parameters without overrides
            comment_lines = []
            comment_lines.append(
                "# Uncomment and modify any of the following to override parameters:"
            )

            for param in self._parameters.values():
                if not param.is_override:
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

            # Add a dummy entry so the AoT gets written
            dummy = table()
            dummy.add(tomlkit.comment("\n".join(comment_lines)))
            overrides_aot.append(dummy)

        # Write the config back to the file
        repo.write_config()

    def as_dict(self) -> dict[str, Any]:
        """Return the parameters/overrides as a dictionary suitable for including as context.parameters.

        Note: if there are multiple overrides for the same parameter name, the last one added takes precedence.
        If there is no override for a parameter, its default value is used."""
        result = {}
        for param in self._parameters.values():
            # Use override value if present, otherwise use default
            if param.is_override:
                result[param.name] = param.value
            elif param.default is not None:
                result[param.name] = param.default
        return result
