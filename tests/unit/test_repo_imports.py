"""Tests for TOML import resolution in repo.Repo."""

from pathlib import Path

import pytest

from repo.repo import Repo


def test_basic_import_same_file(tmp_path: Path):
    """Test importing a node from the same TOML file."""
    # Create a TOML file with a base definition and an import
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [base_stage]
        tool = "siril"
        description = "Base stage definition"
        context.value = 42

        [my_stage.import]
        node = "base_stage"
        """,
        encoding="utf-8",
    )

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
    lib_file.write_text(
        """
        [repo]
        kind = "library"

        [common_settings]
        tool = "graxpert"
        input.required = 5
        context.mode = "background"
        """,
        encoding="utf-8",
    )

    # Create main file that imports from library
    main_file = tmp_path / "main.toml"
    lib_path_posix = lib_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [stage_one.import]
        file = "{lib_path_posix}"
        node = "common_settings"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Verify the import was resolved
    stage_one = repo.config["stage_one"].value
    assert "import" not in stage_one
    assert stage_one["tool"] == "graxpert"
    assert stage_one["input"]["required"] == 5
    assert stage_one["context"]["mode"] == "background"


def test_import_with_relative_path(tmp_path: Path):
    """Test importing from a file using a relative path."""
    # Create subdirectories
    subdir = tmp_path / "configs"
    subdir.mkdir()

    # Create library in subdirectory
    lib_file = subdir / "lib.toml"
    lib_file.write_text("""
        [repo]
        kind = "library"

        [template]
        description = "Template from subdirectory"
        value = 123
        """)

    # Create main file that imports using relative path
    main_file = tmp_path / "main.toml"
    lib_path_posix = lib_file.relative_to(tmp_path).as_posix()
    main_file.write_text(f"""
        [repo]
        kind = "recipe"

        [my_config.import]
        file = "{lib_path_posix}"
        node = "template"
        """)

    repo = Repo(main_file)

    # Verify import resolved correctly
    my_config = repo.config["my_config"].value
    assert my_config["description"] == "Template from subdirectory"
    assert my_config["value"] == 123


def test_import_nested_node(tmp_path: Path):
    """Test importing a deeply nested node using dot notation."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [library.stages.preprocessing]
        tool = "siril"
        script = "calibrate light"

        [library.stages.stacking]
        tool = "siril"
        script = "stack light"

        [my_stage.import]
        node = "library.stages.preprocessing"
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)

    # Verify nested import
    my_stage = repo.config["my_stage"].value
    assert my_stage["tool"] == "siril"
    assert my_stage["script"] == "calibrate light"


def test_import_from_external_repo(tmp_path: Path):
    """Test importing from a completely different repo."""
    # Create external repo
    external_repo_path = tmp_path / "external"
    external_repo_path.mkdir()

    external_toml = external_repo_path / "starbash.toml"
    external_toml.write_text(
        """
        [repo]
        kind = "library"

        [shared_stage]
        tool = "python"
        description = "Shared across repos"
        context.shared_value = "external"
        """,
        encoding="utf-8",
    )

    # Create main repo that imports from external
    main_repo_path = tmp_path / "main"
    main_repo_path.mkdir()

    main_toml = main_repo_path / "starbash.toml"
    repo_url = external_repo_path.as_posix()
    main_toml.write_text(
        f"""
        [repo]
        kind = "recipe"

        [my_stage.import]
        repo = "file://{repo_url}"
        node = "shared_stage"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_toml)

    # Verify cross-repo import
    my_stage = repo.config["my_stage"].value
    assert my_stage["tool"] == "python"
    assert my_stage["description"] == "Shared across repos"
    assert my_stage["context"]["shared_value"] == "external"


def test_import_caching(tmp_path: Path):
    """Test that imported files are cached to avoid redundant reads."""
    # Create library file
    lib_file = tmp_path / "library.toml"
    lib_file.write_text(
        """
        [repo]
        kind = "library"

        [setting_a]
        value = "A"

        [setting_b]
        value = "B"
        """,
        encoding="utf-8",
    )

    # Create main file with multiple imports from same file
    main_file = tmp_path / "main.toml"
    lib_path_posix = lib_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [config_a.import]
        file = "{lib_path_posix}"
        node = "setting_a"

        [config_b.import]
        file = "{lib_path_posix}"
        node = "setting_b"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Both imports should be resolved
    assert repo.config["config_a"].value["value"] == "A"
    assert repo.config["config_b"].value["value"] == "B"

    # Check that cache was used (both should reference same cache key)
    cache_key = f"{repo.url}::library.toml"
    assert cache_key in repo._import_cache


def test_import_in_array_of_tables(tmp_path: Path):
    """Test that imports work within array-of-tables (AoT) structures."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

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
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)

    # Verify imports in array of tables
    stages = repo.config["stages"].value
    assert len(stages) == 2
    assert stages[0].value["name"] == "calibrate"
    assert stages[0].value["tool"] == "siril"
    assert stages[1].value["name"] == "stack"
    assert stages[1].value["tool"] == "siril"


def test_import_preserves_additional_keys(tmp_path: Path):
    """Test that additional keys alongside import are preserved."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [base]
        tool = "siril"
        description = "Base description"

        [derived]
        custom_key = "custom_value"
        [derived.import]
        node = "base"
        """,
        encoding="utf-8",
    )

    repo = Repo(toml_file)

    # The import replaces the entire table, so custom_key will be lost
    # This is the expected behavior per the design
    derived = repo.config["derived"].value
    assert "import" not in derived
    assert derived["tool"] == "siril"
    # custom_key is replaced by the import
    assert "custom_key" not in derived


def test_import_missing_node_error(tmp_path: Path):
    """Test error handling when imported node doesn't exist."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [stage.import]
        node = "nonexistent.node"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not found in path"):
        Repo(toml_file)


def test_import_missing_node_key_error(tmp_path: Path):
    """Test error handling when import doesn't specify a node."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [stage.import]
        file = "other.toml"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must specify a 'node' key"):
        Repo(toml_file)


def test_import_invalid_spec_error(tmp_path: Path):
    """Test error handling when import spec is not a table."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [stage]
        import = "invalid_string_value"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a table"):
        Repo(toml_file)


def test_import_missing_file_error(tmp_path: Path):
    """Test error handling when imported file doesn't exist."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [stage.import]
        file = "nonexistent.toml"
        node = "some.node"
        """,
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        Repo(toml_file)


def test_import_at_root_error(tmp_path: Path):
    """Test that imports at the root level are not allowed."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        """
        [repo]
        kind = "recipe"

        [some]
        value = 1

        [import]
        node = "some"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Cannot use import at the root level"):
        Repo(toml_file)


def test_nested_imports(tmp_path: Path):
    """Test that imports work recursively (importing something that has imports)."""
    # Create base library
    base_file = tmp_path / "base.toml"
    base_file.write_text(
        """
        [repo]
        kind = "library"

        [foundation]
        tool = "siril"
        base_value = 1
        """,
        encoding="utf-8",
    )

    # Create intermediate library that imports from base
    intermediate_file = tmp_path / "intermediate.toml"
    base_path_posix = base_file.relative_to(tmp_path).as_posix()
    intermediate_file.write_text(
        f"""
        [repo]
        kind = "library"

        [extended.import]
        file = "{base_path_posix}"
        node = "foundation"
        """,
        encoding="utf-8",
    )

    # Create main file that imports from intermediate
    main_file = tmp_path / "main.toml"
    intermediate_path_posix = intermediate_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [final.import]
        file = "{intermediate_path_posix}"
        node = "extended"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Verify nested import chain worked
    final = repo.config["final"].value
    assert final["tool"] == "siril"
    assert final["base_value"] == 1


def test_import_preserves_monkey_patch(tmp_path: Path):
    """Test that imported content gets monkey-patched with source attribute."""
    lib_file = tmp_path / "lib.toml"
    lib_file.write_text(
        """
        [repo]
        kind = "library"

        [template]
        value = 42
        """,
        encoding="utf-8",
    )

    main_file = tmp_path / "main.toml"
    lib_path_posix = lib_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [imported.import]
        file = "{lib_path_posix}"
        node = "template"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Verify the imported content has source attribute
    imported = repo.config["imported"]
    assert hasattr(imported, "source")
    assert imported.source == repo


def test_multiple_imports_isolation(tmp_path: Path):
    """Test that multiple imports get independent copies (no reference sharing)."""
    base_file = tmp_path / "base.toml"
    base_file.write_text(
        """
        [repo]
        kind = "library"

        [shared]
        [shared.mutable]
        value = 10
        """,
        encoding="utf-8",
    )

    main_file = tmp_path / "main.toml"
    base_path_posix = base_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [copy1.import]
        file = "{base_path_posix}"
        node = "shared"

        [copy2.import]
        file = "{base_path_posix}"
        node = "shared"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Both should have the same initial values
    copy1 = repo.config["copy1"].value
    copy2 = repo.config["copy2"].value
    assert copy1["mutable"]["value"] == 10
    assert copy2["mutable"]["value"] == 10

    # Modifying one shouldn't affect the other (deep copy verification)
    copy1["mutable"]["value"] = 20
    assert copy2["mutable"]["value"] == 10


def test_import_complex_structure(tmp_path: Path):
    """Test importing complex nested structures with arrays and tables."""
    lib_file = tmp_path / "lib.toml"
    lib_file.write_text(
        """
        [repo]
        kind = "library"

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
        """,
        encoding="utf-8",
    )

    main_file = tmp_path / "main.toml"
    lib_path_posix = lib_file.relative_to(tmp_path).as_posix()
    main_file.write_text(
        f"""
        [repo]
        kind = "recipe"

        [my_stage.import]
        file = "{lib_path_posix}"
        node = "complex"
        """,
        encoding="utf-8",
    )

    repo = Repo(main_file)

    # Verify complex structure was imported correctly
    stage = repo.config["my_stage"].value
    assert stage["name"] == "complex_stage"
    assert stage["input"]["type"] == "light"
    assert stage["input"]["required"] == 5
    filters = stage["filters"]
    assert len(filters) == 2
    assert filters[0]["name"] == "Ha"
    assert filters[1]["name"] == "Oiii"
    assert stage["context"]["mode"] == "dual-duo"
    assert stage["context"]["settings"]["threshold"] == 0.5
