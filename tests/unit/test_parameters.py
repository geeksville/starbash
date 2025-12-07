"""Tests for parameter management in starbash."""

from pathlib import Path

import pytest
import tomlkit

from repo.repo import Repo
from starbash.parameters import Parameter, ParameterStore


def test_parameter_is_override():
    """Test that Parameter.is_override property works correctly."""
    # Create a minimal repo for testing
    # Parameter with only default (not an override)
    param1 = Parameter(source=None, name="test", default=42, value=None)  # type: ignore
    assert not param1.is_override

    # Parameter with value (is an override)
    param2 = Parameter(source=None, name="test", default=42, value=100)  # type: ignore
    assert param2.is_override


def test_add_parameters_from_repo(tmp_path: Path):
    """Test loading [[parameters]] from a repo."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[parameters]]
        name = "smoothing_option"
        default = 0.5
        description = "Smoothing option for graxpert"

        [[parameters]]
        name = "ai_version"
        default = "1.0.1"
        description = "AI version"
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)
    store = ParameterStore()
    store.add_from_repo(repo)

    # Verify parameters were loaded
    assert "smoothing_option" in store._parameters
    assert "ai_version" in store._parameters

    # Check smoothing_option details
    param = store._parameters["smoothing_option"]
    assert param.name == "smoothing_option"
    assert param.default == 0.5
    assert param.description == "Smoothing option for graxpert"
    assert not param.is_override
    assert param.source == repo

    # Check ai_version details
    param = store._parameters["ai_version"]
    assert param.name == "ai_version"
    assert param.default == "1.0.1"
    assert param.description == "AI version"


def test_add_overrides_from_repo(tmp_path: Path):
    """Test loading [[overrides]] from a repo."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "target"

        [[overrides]]
        name = "smoothing_option"
        value = 0.7
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)
    store = ParameterStore()
    store.add_from_repo(repo)

    # Verify override was loaded
    assert "smoothing_option" in store._parameters
    param = store._parameters["smoothing_option"]
    assert param.name == "smoothing_option"
    assert param.value == 0.7
    assert param.is_override


def test_override_replaces_parameter(tmp_path: Path):
    """Test that overrides replace parameter defaults."""
    # First repo with parameter
    param_file = tmp_path / "params.toml"
    param_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[parameters]]
        name = "smoothing_option"
        default = 0.5
        description = "Smoothing option"
        """,
        encoding="utf-8",
    )

    # Second repo with override
    override_file = tmp_path / "overrides.toml"
    override_file.write_text(
        """
        [repo]
        kind = "target"

        [[overrides]]
        name = "smoothing_option"
        value = 0.8
        """,
        encoding="utf-8",
    )

    param_repo = Repo(param_file)
    override_repo = Repo(override_file)

    store = ParameterStore()
    store.add_from_repo(param_repo)
    store.add_from_repo(override_repo)

    # Verify the override replaced the parameter
    param = store._parameters["smoothing_option"]
    assert param.value == 0.8
    assert param.default == 0.5  # Should still have original default
    assert param.is_override
    assert param.source == override_repo  # Source should be updated


def test_as_dict_with_defaults(tmp_path: Path):
    """Test as_dict returns defaults when no overrides."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[parameters]]
        name = "smoothing_option"
        default = 0.5

        [[parameters]]
        name = "ai_version"
        default = "1.0.1"
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)
    store = ParameterStore()
    store.add_from_repo(repo)

    result = store.as_dict()
    assert result == {"smoothing_option": 0.5, "ai_version": "1.0.1"}


def test_as_dict_with_overrides(tmp_path: Path):
    """Test as_dict returns override values instead of defaults."""
    # Repo with parameters
    param_file = tmp_path / "params.toml"
    param_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[parameters]]
        name = "smoothing_option"
        default = 0.5

        [[parameters]]
        name = "ai_version"
        default = "1.0.1"
        """,
        encoding="utf-8",
    )

    # Repo with overrides
    override_file = tmp_path / "overrides.toml"
    override_file.write_text(
        """
        [repo]
        kind = "target"

        [[overrides]]
        name = "smoothing_option"
        value = 0.9
        """,
        encoding="utf-8",
    )

    param_repo = Repo(param_file)
    override_repo = Repo(override_file)

    store = ParameterStore()
    store.add_from_repo(param_repo)
    store.add_from_repo(override_repo)

    result = store.as_dict()
    # smoothing_option should use override, ai_version should use default
    assert result == {"smoothing_option": 0.9, "ai_version": "1.0.1"}


def test_write_overrides_creates_section(tmp_path: Path):
    """Test write_overrides creates [[overrides]] section with commented examples."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "target"
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)
    store = ParameterStore()

    # Add parameters to the store
    store._parameters["test_param"] = Parameter(
        source=repo, name="test_param", default=42, description="Test parameter"
    )
    store._parameters["another_param"] = Parameter(
        source=repo, name="another_param", default="value", description="Another test parameter"
    )

    # Write overrides
    store.write_overrides(repo)

    # Reload and verify [[overrides]] section exists with comments
    updated_content = toml_file.read_text()
    assert "[[overrides]]" in updated_content

    # Check for commented example entries for parameters without overrides
    # The comments should show how to override the parameters
    assert '# name = "test_param"' in updated_content or 'name = "test_param"' in updated_content
    assert "# Test parameter" in updated_content
    assert "# value = 42" in updated_content or "value = 42" in updated_content


def test_write_overrides_preserves_existing(tmp_path: Path):
    """Test write_overrides preserves existing overrides."""
    toml_file = tmp_path / "starbash.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "target"

        [[overrides]]
        name = "existing_param"
        value = 123
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)
    store = ParameterStore()
    store.write_overrides(repo)

    # Reload and verify existing override is still there
    updated_repo = Repo(toml_file)
    overrides = updated_repo.config.get("overrides")
    assert overrides is not None

    # Check that existing override is preserved
    override_list = overrides.value if hasattr(overrides, "value") else overrides
    found = False
    for item in override_list:
        override = item.value if hasattr(item, "value") else item
        if override["name"] == "existing_param":
            assert override["value"] == 123
            found = True
            break
    assert found, "Existing override was not preserved"
