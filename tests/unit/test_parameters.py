"""Tests for parameter management in starbash."""

from pathlib import Path

from toml_repo.repo import Repo

from starbash.parameters import Parameter, ParameterStore


def test_parameter_is_override():
    """Parameter.is_override reflects whether a value was set."""
    param1 = Parameter(source=None, name="test", default=42, value=None)  # type: ignore
    assert not param1.is_override

    param2 = Parameter(source=None, name="test", default=42, value=100)  # type: ignore
    assert param2.is_override


def _recipe_repo(tmp_path: Path) -> Repo:
    """A recipe repo with two stages, each declaring its own parameters."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[stages]]
        name = "background"

        [[stages.parameters]]
        name = "smoothing_option"
        default = 0.5
        description = "Smoothing option for graxpert"

        [[stages.parameters]]
        name = "ai_version"
        default = "1.0.1"
        description = "AI version"

        [[stages]]
        name = "stack_osc"

        [[stages.parameters]]
        name = "smoothing_option"
        default = 0.9
        description = "Different stage, same param name"
        """,
        encoding="utf-8",
    )
    return Repo(toml_file)


def test_add_parameters_from_stage(tmp_path: Path):
    """Parameters are loaded and tagged with their owning stage."""
    repo = _recipe_repo(tmp_path)
    store = ParameterStore()
    for stage in repo.config["stages"]:
        store.add_parameters_from_stage(repo, stage)

    bg = [p for p in store._parameters if p.stage_name == "background"]
    names = {p.name for p in bg}
    assert names == {"smoothing_option", "ai_version"}
    smoothing = next(p for p in bg if p.name == "smoothing_option")
    assert smoothing.default == 0.5
    assert smoothing.description == "Smoothing option for graxpert"
    assert not smoothing.is_override
    assert smoothing.source == repo


def test_add_parameters_is_deduped(tmp_path: Path):
    """Adding the same stage twice does not duplicate its parameters."""
    repo = _recipe_repo(tmp_path)
    store = ParameterStore()
    stage = repo.config["stages"][0]
    store.add_parameters_from_stage(repo, stage)
    store.add_parameters_from_stage(repo, stage)

    smoothing = [
        p
        for p in store._parameters
        if p.stage_name == "background" and p.name == "smoothing_option"
    ]
    assert len(smoothing) == 1


def test_as_obj_for_stage_uses_defaults(tmp_path: Path):
    """as_obj_for_stage returns each stage's own defaults."""
    repo = _recipe_repo(tmp_path)
    store = ParameterStore()
    for stage in repo.config["stages"]:
        store.add_parameters_from_stage(repo, stage)

    bg = store.as_obj_for_stage("background")
    assert bg.smoothing_option == 0.5
    assert bg.ai_version == "1.0.1"

    # Same param name in a different stage resolves independently.
    stack = store.as_obj_for_stage("stack_osc")
    assert stack.smoothing_option == 0.9


def _target_repo(tmp_path: Path) -> Repo:
    """A per-target repo with an active override for one stage."""
    toml_file = tmp_path / "target.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "processed-target"

        [[stages]]
        name = "background"
        [[stages.overrides]]
        name = "smoothing_option"
        value = 0.8
        """,
        encoding="utf-8",
    )
    return Repo(toml_file)


def test_add_overrides_from_repo(tmp_path: Path):
    """Active [[stages.overrides]] are loaded and scoped to their stage."""
    repo = _target_repo(tmp_path)
    store = ParameterStore()
    store.add_overrides_from_repo(repo)

    overrides = [p for p in store._parameters if p.is_override]
    assert len(overrides) == 1
    ov = overrides[0]
    assert ov.stage_name == "background"
    assert ov.name == "smoothing_option"
    assert ov.value == 0.8


def test_override_wins_over_default(tmp_path: Path):
    """A stage override replaces the recipe default for that stage only."""
    recipe = _recipe_repo(tmp_path)
    target = _target_repo(tmp_path)

    store = ParameterStore()
    for stage in recipe.config["stages"]:
        store.add_parameters_from_stage(recipe, stage)
    store.add_overrides_from_repo(target)

    bg = store.as_obj_for_stage("background")
    assert bg.smoothing_option == 0.8  # overridden
    assert bg.ai_version == "1.0.1"  # still default

    # stack_osc's same-named param is unaffected by the background override.
    stack = store.as_obj_for_stage("stack_osc")
    assert stack.smoothing_option == 0.9


def test_commented_override_is_ignored(tmp_path: Path):
    """An override entry with no value (commented) does not apply."""
    toml_file = tmp_path / "target.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "processed-target"

        [[stages]]
        name = "background"
        [[stages.overrides]]
        name = "smoothing_option"
        # value = 0.8
        """,
        encoding="utf-8",
    )
    repo = Repo(toml_file)
    store = ParameterStore()
    store.add_overrides_from_repo(repo)
    assert [p for p in store._parameters if p.is_override] == []


def test_write_stage_overrides_scaffolds(tmp_path: Path):
    """write_stage_overrides nests [[stages.overrides]] with name set, value commented."""
    toml_file = tmp_path / "target.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "processed-target"
        """,
        encoding="utf-8",
    )
    repo = Repo(toml_file)
    store = ParameterStore()
    store._parameters.append(
        Parameter(
            source=repo,
            name="light_options",
            stage_name="light_vs_dark",
            default="-cfa -equalize_cfa",
            description="Light frame calibration options",
        )
    )
    store._parameters.append(
        Parameter(source=repo, name="smoothing", stage_name="background", default=0.5)
    )

    store.write_stage_overrides(repo)
    repo.write_config()

    content = toml_file.read_text()
    assert "[[stages]]" in content
    assert 'name = "light_options"' in content  # name uncommented
    assert '# value = "-cfa -equalize_cfa"' in content  # value stays commented
    assert "# value = 0.5" in content
    assert "Light frame calibration options" in content  # description carried onto name line


def test_write_stage_overrides_preserves_activated(tmp_path: Path):
    """An override the user already activated is not clobbered by re-scaffolding."""
    toml_file = tmp_path / "target.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "processed-target"

        [[stages]]
        name = "background"
        [[stages.overrides]]
        name = "smoothing"
        value = 0.9
        """,
        encoding="utf-8",
    )
    repo = Repo(toml_file)
    store = ParameterStore()
    store._parameters.append(
        Parameter(source=repo, name="smoothing", stage_name="background", default=0.5)
    )

    store.write_stage_overrides(repo)

    stages = repo.config["stages"]
    bg = next(s for s in stages if s["name"] == "background")
    overrides = [o for o in bg["overrides"] if o.get("name") == "smoothing"]
    # Only one entry, and the user's activated value is retained.
    assert len(overrides) == 1
    assert overrides[0].get("value") == 0.9
