#!/usr/bin/env python3
"""Demonstration of ParameterStore with background.toml example."""

from pathlib import Path
from tempfile import TemporaryDirectory

from repo.repo import Repo
from starbash.parameters import ParameterStore

# Create a temporary directory for our example
with TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)

    # Create a recipe repo with parameters (like starbash-recipes/graxpert/background.toml)
    recipe_file = tmp_path / "recipe.toml"
    recipe_file.write_text(
        """
        [repo]
        kind = "recipe"

        [[parameters]]
        name = "smoothing_option"
        default = 0.5
        description = "Smoothing option for graxpert background extraction"

        [[parameters]]
        name = "bge_ai_version"
        default = "1.0.1"
        description = "AI version for graxpert background extraction"

        [[stages]]
        name = "background"
        description = "Do background subtraction with graxpert"
        """,
        encoding="utf-8",
    )

    # Create a target repo that might want to override parameters
    target_file = tmp_path / "target.toml"
    target_file.write_text(
        """
        [repo]
        kind = "target"

        [target]
        name = "M31"
        """,
        encoding="utf-8",
    )

    # Load repos
    recipe_repo = Repo(recipe_file)
    target_repo = Repo(target_file)

    # Create parameter store and load parameters from recipe
    store = ParameterStore()
    store.add_from_repo(recipe_repo)

    print("Parameters from recipe repo:")
    print(f"  {store.as_dict()}")
    print()

    # Write override template to target repo
    print("Writing override template to target repo...")
    store.write_overrides(target_repo)

    # Show what was written
    print("\nTarget repo TOML after write_overrides:")
    print(target_file.read_text())

    # Now let's add an actual override
    target_file.write_text(
        """
        [repo]
        kind = "target"

        [target]
        name = "M31"

        [[overrides]]
        name = "smoothing_option"
        value = 0.7
        """,
        encoding="utf-8",
    )

    # Reload and reprocess
    target_repo = Repo(target_file)
    store2 = ParameterStore()
    store2.add_from_repo(recipe_repo)  # Load parameters first
    store2.add_from_repo(target_repo)  # Then load overrides

    print("\nParameters after adding override:")
    print(f"  {store2.as_dict()}")
    print()
    print("Notice that smoothing_option is now 0.7 (overridden) instead of 0.5 (default)")
