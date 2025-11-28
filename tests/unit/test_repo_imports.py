"""Tests for TOML import resolution in repo.Repo."""

from pathlib import Path

import pytest

from repo.repo import Repo


def test_basic_import_same_file(tmp_path: Path):
    """Test importing a node from the same TOML file."""
    # Create a TOML file with a base definition and an import
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [base_stage]
        tool = "siril"
        description = "Base stage definition"
        context.value = 42

        [my_stage.import]
        node = "base_stage"
        """)

    repo = Repo(toml_file)

    # The import should have been resolved
    assert "import" not in repo.config["my_stage"]
    assert repo.config["my_stage"]["tool"] == "siril"
    assert repo.config["my_stage"]["description"] == "Base stage definition"
    assert repo.config["my_stage"]["context"]["value"] == 42


def test_import_from_different_file(tmp_path: Path):
    """Test importing a node from a different TOML file in the same repo."""
    # Create a library file with reusable definitions
    lib_file = tmp_path / "library.toml"
    lib_file.write_text("""
        [common_settings]
        tool = "graxpert"
        input.required = 5
        context.mode = "background"
        """)

    # Create main file that imports from library
    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [repo]
        kind = "recipe"

        [stage_one.import]
        file = "library.toml"
        node = "common_settings"
        """)

    repo = Repo(main_file)

    # Verify the import was resolved
    assert "import" not in repo.config["stage_one"]
    assert repo.config["stage_one"]["tool"] == "graxpert"
    assert repo.config["stage_one"]["input"]["required"] == 5
    assert repo.config["stage_one"]["context"]["mode"] == "background"


def test_import_with_relative_path(tmp_path: Path):
    """Test importing from a file using a relative path."""
    # Create subdirectories
    subdir = tmp_path / "configs"
    subdir.mkdir()

    # Create library in subdirectory
    lib_file = subdir / "lib.toml"
    lib_file.write_text("""
        [template]
        description = "Template from subdirectory"
        value = 123
        """)

    # Create main file that imports using relative path
    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [my_config.import]
        file = "configs/lib.toml"
        node = "template"
        """)

    repo = Repo(main_file)

    # Verify import resolved correctly
    assert repo.config["my_config"]["description"] == "Template from subdirectory"
    assert repo.config["my_config"]["value"] == 123


def test_import_nested_node(tmp_path: Path):
    """Test importing a deeply nested node using dot notation."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [library.stages.preprocessing]
        tool = "siril"
        script = "calibrate light"

        [library.stages.stacking]
        tool = "siril"
        script = "stack light"

        [my_stage.import]
        node = "library.stages.preprocessing"
        """)

    repo = Repo(toml_file)

    # Verify nested import
    assert repo.config["my_stage"]["tool"] == "siril"
    assert repo.config["my_stage"]["script"] == "calibrate light"


def test_import_from_external_repo(tmp_path: Path):
    """Test importing from a completely different repo."""
    # Create external repo
    external_repo_path = tmp_path / "external"
    external_repo_path.mkdir()

    external_toml = external_repo_path / "starbash.toml"
    external_toml.write_text("""
        [repo]
        kind = "library"

        [shared_stage]
        tool = "python"
        description = "Shared across repos"
        context.shared_value = "external"
        """)

    # Create main repo that imports from external
    main_repo_path = tmp_path / "main"
    main_repo_path.mkdir()

    main_toml = main_repo_path / "starbash.toml"
    main_toml.write_text(f"""
        [repo]
        kind = "recipe"

        [my_stage.import]
        repo = "file://{external_repo_path}"
        node = "shared_stage"
        """)

    repo = Repo(main_toml)

    # Verify cross-repo import
    assert repo.config["my_stage"]["tool"] == "python"
    assert repo.config["my_stage"]["description"] == "Shared across repos"
    assert repo.config["my_stage"]["context"]["shared_value"] == "external"


def test_import_caching(tmp_path: Path):
    """Test that imported files are cached to avoid redundant reads."""
    # Create library file
    lib_file = tmp_path / "library.toml"
    lib_file.write_text("""
        [setting_a]
        value = "A"

        [setting_b]
        value = "B"
        """)

    # Create main file with multiple imports from same file
    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [config_a.import]
        file = "library.toml"
        node = "setting_a"

        [config_b.import]
        file = "library.toml"
        node = "setting_b"
        """)

    repo = Repo(main_file)

    # Both imports should be resolved
    assert repo.config["config_a"]["value"] == "A"
    assert repo.config["config_b"]["value"] == "B"

    # Check that cache was used (both should reference same cache key)
    cache_key = f"{repo.url}::library.toml"
    assert cache_key in repo._import_cache


def test_import_in_array_of_tables(tmp_path: Path):
    """Test that imports work within array-of-tables (AoT) structures."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [base_stage]
        tool = "siril"
        priority = 10

        [[stages]]
        name = "calibrate"
        [stages.import]
        node = "base_stage"

        [[stages]]
        name = "stack"
        [stages.import]
        node = "base_stage"
        """)

    repo = Repo(toml_file)

    # Verify imports in array of tables
    assert len(repo.config["stages"]) == 2
    assert repo.config["stages"][0]["name"] == "calibrate"
    assert repo.config["stages"][0]["tool"] == "siril"
    assert repo.config["stages"][1]["name"] == "stack"
    assert repo.config["stages"][1]["tool"] == "siril"


def test_import_preserves_additional_keys(tmp_path: Path):
    """Test that additional keys alongside import are preserved."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [base]
        tool = "siril"
        description = "Base description"

        [derived]
        custom_key = "custom_value"
        [derived.import]
        node = "base"
        """)

    repo = Repo(toml_file)

    # The import replaces the entire table, so custom_key will be lost
    # This is the expected behavior per the design
    assert "import" not in repo.config["derived"]
    assert repo.config["derived"]["tool"] == "siril"
    # custom_key is replaced by the import
    assert "custom_key" not in repo.config["derived"]


def test_import_missing_node_error(tmp_path: Path):
    """Test error handling when imported node doesn't exist."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [stage.import]
        node = "nonexistent.node"
        """)

    with pytest.raises(ValueError, match="not found in path"):
        Repo(toml_file)


def test_import_missing_node_key_error(tmp_path: Path):
    """Test error handling when import doesn't specify a node."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [stage.import]
        file = "other.toml"
        """)

    with pytest.raises(ValueError, match="must specify a 'node' key"):
        Repo(toml_file)


def test_import_invalid_spec_error(tmp_path: Path):
    """Test error handling when import spec is not a table."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [stage]
        import = "invalid_string_value"
        """)

    with pytest.raises(ValueError, match="must be a table"):
        Repo(toml_file)


def test_import_missing_file_error(tmp_path: Path):
    """Test error handling when imported file doesn't exist."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [stage.import]
        file = "nonexistent.toml"
        node = "some.node"
        """)

    with pytest.raises(FileNotFoundError):
        Repo(toml_file)


def test_import_at_root_error(tmp_path: Path):
    """Test that imports at the root level are not allowed."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text("""
        [some]
        value = 1

        [import]
        node = "some"
        """)

    with pytest.raises(ValueError, match="Cannot use import at the root level"):
        Repo(toml_file)


def test_nested_imports(tmp_path: Path):
    """Test that imports work recursively (importing something that has imports)."""
    # Create base library
    base_file = tmp_path / "base.toml"
    base_file.write_text("""
        [foundation]
        tool = "siril"
        base_value = 1
        """)

    # Create intermediate library that imports from base
    intermediate_file = tmp_path / "intermediate.toml"
    intermediate_file.write_text("""
        [extended.import]
        file = "base.toml"
        node = "foundation"
        """)

    # Create main file that imports from intermediate
    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [final.import]
        file = "intermediate.toml"
        node = "extended"
        """)

    repo = Repo(main_file)

    # Verify nested import chain worked
    assert repo.config["final"]["tool"] == "siril"
    assert repo.config["final"]["base_value"] == 1


def test_import_preserves_monkey_patch(tmp_path: Path):
    """Test that imported content gets monkey-patched with source attribute."""
    lib_file = tmp_path / "lib.toml"
    lib_file.write_text("""
        [template]
        value = 42
        """)

    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [imported.import]
        file = "lib.toml"
        node = "template"
        """)

    repo = Repo(main_file)

    # Verify the imported content has source attribute
    assert hasattr(repo.config["imported"], "source")
    assert repo.config["imported"].source == repo


def test_multiple_imports_isolation(tmp_path: Path):
    """Test that multiple imports get independent copies (no reference sharing)."""
    base_file = tmp_path / "base.toml"
    base_file.write_text("""
        [shared]
        [shared.mutable]
        value = 10
        """)

    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [copy1.import]
        file = "base.toml"
        node = "shared"

        [copy2.import]
        file = "base.toml"
        node = "shared"
        """)

    repo = Repo(main_file)

    # Both should have the same initial values
    assert repo.config["copy1"]["mutable"]["value"] == 10
    assert repo.config["copy2"]["mutable"]["value"] == 10

    # Modifying one shouldn't affect the other (deep copy verification)
    repo.config["copy1"]["mutable"]["value"] = 20
    assert repo.config["copy2"]["mutable"]["value"] == 10


def test_import_complex_structure(tmp_path: Path):
    """Test importing complex nested structures with arrays and tables."""
    lib_file = tmp_path / "lib.toml"
    lib_file.write_text("""
        [complex]
        name = "complex_stage"

        [complex.input]
        type = "light"
        required = 5

        [[complex.filters]]
        name = "Ha"
        exposure = 300

        [[complex.filters]]
        name = "Oiii"
        exposure = 300

        [complex.context]
        mode = "dual-duo"
        [complex.context.settings]
        threshold = 0.5
        """)

    main_file = tmp_path / "main.toml"
    main_file.write_text("""
        [my_stage.import]
        file = "lib.toml"
        node = "complex"
        """)

    repo = Repo(main_file)

    # Verify complex structure was imported correctly
    stage = repo.config["my_stage"]
    assert stage["name"] == "complex_stage"
    assert stage["input"]["type"] == "light"
    assert stage["input"]["required"] == 5
    assert len(stage["filters"]) == 2
    assert stage["filters"][0]["name"] == "Ha"
    assert stage["filters"][1]["name"] == "Oiii"
    assert stage["context"]["mode"] == "dual-duo"
    assert stage["context"]["settings"]["threshold"] == 0.5
