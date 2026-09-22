"""The frozen (Windows exe) bundle must carry what recipe scripts import at runtime.

A recipe's python stage is *text* inside the recipe repos' TOML, so PyInstaller's
static analysis never sees its imports - ``from starbash.recipes import
report_registration`` and friends are invisible to it, and
``collect_data_files("starbash")`` copies only non-Python files (it picks up
``recipes/README.md``, which is enough to make ``starbash.recipes`` resolve as an
*empty namespace package* in the bundle).  ``packaging/pyinstaller/hook-starbash.py``
therefore has to declare those modules itself.  These tests run the hook the way
PyInstaller does and assert on what it declares.
"""

import importlib
import pkgutil
import re
from pathlib import Path
from typing import Any

import pytest

import starbash.recipes

REPO_ROOT = Path(__file__).parents[2]
HOOKS_DIR = REPO_ROOT / "packaging" / "pyinstaller"
RECIPE_REPO = REPO_ROOT / "starbash-recipes"

#: The import a python stage's script text uses, e.g. in ``osc/report_registration.toml``.
RECIPES_IMPORT = re.compile(r"^\s*from\s+starbash\.recipes\s+import\s+(\w+)", re.MULTILINE)


def run_hook(filename: str) -> dict[str, Any]:
    """Execute a packaging hook file and return the namespace PyInstaller reads."""
    pytest.importorskip("PyInstaller", reason="the packaging group is not installed")
    path = HOOKS_DIR / filename
    namespace: dict[str, Any] = {"__file__": str(path), "__name__": path.stem}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def starbash_hook() -> dict[str, Any]:
    """The evaluated ``hook-starbash.py`` (it shells out, so run it once)."""
    return run_hook("hook-starbash.py")


def hidden_imports(hook: dict[str, Any]) -> set[str]:
    """The hook's ``hiddenimports`` - empty when it declares none at all."""
    return set(hook.get("hiddenimports", []))


def recipe_helper_modules() -> set[str]:
    """Every module of ``starbash.recipes``, so the assertion tracks new helpers."""
    names = {
        f"starbash.recipes.{module.name}"
        for module in pkgutil.iter_modules(starbash.recipes.__path__)
    }
    return names | {"starbash.recipes"}


def modules_imported_by_recipe_scripts() -> set[str]:
    """The ``starbash.recipes`` modules the local recipe repo's stages import."""
    if not (RECIPE_REPO / "starbash.toml").exists():  # submodule not checked out
        pytest.skip("the starbash-recipes submodule is not checked out")
    found = {
        match
        for toml in RECIPE_REPO.rglob("*.toml")
        for match in RECIPES_IMPORT.findall(toml.read_text())
    }
    assert found, "no recipe script imports starbash.recipes - is the submodule stale?"
    return {f"starbash.recipes.{name}" for name in found}


def test_recipe_helpers_are_hidden_imports(starbash_hook):
    """All of ``starbash.recipes`` is declared, not just the module that broke."""
    missing = recipe_helper_modules() - hidden_imports(starbash_hook)
    assert not missing, f"the bundle would drop these recipe helpers: {sorted(missing)}"


def test_modules_the_recipe_scripts_import_are_hidden_imports(starbash_hook):
    """The exact imports the recipe TOMLs make survive bundling."""
    missing = modules_imported_by_recipe_scripts() - hidden_imports(starbash_hook)
    assert not missing, f"recipe scripts import modules the bundle drops: {sorted(missing)}"


def test_declared_hidden_imports_really_import(starbash_hook):
    """The declared names are real modules (a typo here would fail only on Windows)."""
    for name in sorted(hidden_imports(starbash_hook)):
        assert importlib.import_module(name) is not None


def test_recipe_helpers_reachable_only_from_scripts_are_declared(starbash_hook):
    """``starbash.siril`` is used only by the recipe helpers, so name it too."""
    declared = hidden_imports(starbash_hook)
    assert "starbash.siril.import_registration" in declared


def test_data_files_alone_would_not_carry_the_helpers(starbash_hook):
    """Documents the trap: ``collect_data_files`` brings the README, never the code."""
    recipes_data = [
        (Path(source).name, dest)
        for source, dest in starbash_hook["datas"]
        if dest == "starbash/recipes"
    ]
    assert recipes_data, "the recipes directory is no longer shipped as data at all"
    assert all(not name.endswith(".py") for name, _ in recipes_data)


def test_package_resources_are_still_shipped_as_data(starbash_hook):
    """The hook's original job (templates/defaults/assets) is unchanged."""
    destinations = {dest for _, dest in starbash_hook["datas"]}
    assert {
        "starbash/defaults",
        "starbash/templates",
        "starbash/templates/target/processed",
        "starbash/assets",
    } <= destinations
