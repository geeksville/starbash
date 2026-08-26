from dataclasses import dataclass
from typing import Any

import tomlkit
from toml_repo import Repo
from tomlkit.items import AoT, Table

from starbash import StageDict
from starbash.stage_utils import upsert_stage


class ParameterObject:
    """Simple object to hold parameter attributes."""

    pass


@dataclass
class Parameter:
    """Describes a parameter or override, scoped to the stage that declares it."""

    source: Repo  # The repo where this parameter/override was defined
    name: str

    stage_name: str | None = None  # The stage this parameter/override belongs to

    description: str | None = None

    default: Any | None = (
        None  # Only used in [[stages.parameters]] toml - value to use if not overridden
    )
    value: Any | None = None  # Only used in [[stages.overrides]] toml - an overriden value

    @property
    def is_override(self) -> bool:
        """Return True if this Parameter is an override (i.e. has a value)"""
        return self.value is not None


class ParameterStore:
    """Store for parameters and overrides, scoped per stage, from multiple repos."""

    def __init__(self):
        # Store parameters keyed by name. Later additions override earlier ones.
        self._parameters: list[Parameter] = []
        # (stage_name, name) of default parameters already added, to avoid duplicates
        # when the same stage is processed multiple times (e.g. per session/multiplex).
        self._seen_defaults: set[tuple[str | None, str]] = set()

    def add_parameters_from_stage(self, repo: Repo, stage: StageDict) -> None:
        """Add the ``[[stages.parameters]]`` (defaults) declared by a recipe stage."""
        stage_name = stage.get("name")
        for param in stage.get("parameters", []):
            name = param.get("name")
            if not name:  # skip empty AoT placeholder tables
                continue

            key = (stage_name, name)
            if key in self._seen_defaults:
                continue
            self._seen_defaults.add(key)

            self._parameters.append(
                Parameter(
                    source=repo,
                    name=name,
                    stage_name=stage_name,
                    description=param.get("description"),
                    # A referenced parameter must declare a real default (a commented
                    # `# default =` is invisible here and expands to nothing at runtime).
                    default=param.get("default"),
                )
            )

    def add_overrides_from_repo(self, repo: Repo) -> None:
        """Add active ``[[stages.overrides]]`` (values) from a per-target repo.

        Only overrides whose ``value`` the user has set (uncommented) are applied.
        """
        stages_aot = repo.config.get("stages")
        if not isinstance(stages_aot, AoT):
            return

        for entry in stages_aot:
            stage_name = entry.get("name")
            overrides = entry.get("overrides")
            if not isinstance(overrides, AoT):
                continue
            for override in overrides:
                name = override.get("name")
                value = override.get("value")
                if not name or value is None:
                    continue
                self._parameters.append(
                    Parameter(
                        source=repo,
                        name=name,
                        stage_name=stage_name,
                        description=override.get("description"),
                        value=value,
                    )
                )

    def write_stage_overrides(self, repo: Repo) -> None:
        """Scaffold ``[[stages.overrides]]`` for every declared parameter.

        For each stage that declares parameters, ensure its ``[[stages]]`` entry has
        an ``overrides`` entry per parameter with ``name`` set and, unless the user has
        already activated it, a commented-out ``value`` line showing the default.
        """
        # Group declared (non-override) parameters by owning stage.
        by_stage: dict[str, list[Parameter]] = {}
        for param in self._parameters:
            if param.is_override or not param.stage_name:
                continue
            by_stage.setdefault(param.stage_name, []).append(param)

        for stage_name, params in by_stage.items():
            entry = upsert_stage(repo.config, {"name": stage_name})

            overrides_aot = entry.get("overrides")
            if not isinstance(overrides_aot, AoT):
                overrides_aot = tomlkit.aot()
                entry["overrides"] = overrides_aot

            existing: set[str] = {
                o.get("name") for o in overrides_aot if o.get("name")
            }  # names already present (possibly user-activated)

            for param in params:
                if param.name in existing:
                    continue  # leave user edits / prior scaffolding untouched
                overrides_aot.append(self._make_override_scaffold(param))

    @staticmethod
    def _make_override_scaffold(param: Parameter) -> Table:
        """Build a single ``[[stages.overrides]]`` table: name set, value commented."""
        ov = tomlkit.table()
        name_item = tomlkit.string(param.name)
        if param.description:
            name_item.comment(param.description)
        ov["name"] = name_item

        # The value stays commented until the user opts in by uncommenting it.
        if param.default is None:
            ov.add(tomlkit.comment("value ="))
        elif isinstance(param.default, str):
            ov.add(tomlkit.comment(f'value = "{param.default}"'))
        else:
            ov.add(tomlkit.comment(f"value = {param.default}"))
        return ov

    def as_obj_for_stage(self, stage_name: str | None) -> ParameterObject:
        """Return the effective parameters for ``stage_name`` as a context object.

        Defaults are applied first, then any overrides for the same stage win.
        """
        result = ParameterObject()
        for param in self._parameters:
            if param.stage_name == stage_name and not param.is_override:
                if not hasattr(result, param.name):
                    setattr(result, param.name, param.default)
        for param in self._parameters:
            if param.stage_name == stage_name and param.is_override:
                setattr(result, param.name, param.value)
        return result
