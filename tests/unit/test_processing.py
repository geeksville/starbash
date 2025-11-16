"""Tests for the Processing class and related functionality."""

from unittest.mock import MagicMock

import pytest

from starbash.app import Starbash
from starbash.database import Database
from starbash.processing import Processing


class TestGetRecipeForSession:
    """Tests for the get_recipe_for_session method."""

    def test_get_recipe_no_recipes(self, setup_test_environment, mock_analytics):
        """Test that get_recipe_for_session returns None when no recipe repos exist."""
        with Starbash() as app:
            with Processing(app) as processing:
                # Create a mock session
                session = {
                    "metadata": {
                        Database.FILTER_KEY: "Ha",
                        "INSTRUME": "TestCamera",
                    },
                    "imagetyp": "BIAS",
                }

                step = {"name": "master-bias", "input": "bias"}
                result = processing.get_recipe_for_session(session, step)
                assert result is None

    def test_get_recipe_no_matching_stage(self, setup_test_environment, mock_analytics):
        """Test that recipes without the requested stage are skipped."""
        with Starbash() as app:
            with Processing(app) as processing:
                # Create a mock recipe repo without the requested stage
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.get.return_value = None  # No stage config
                mock_recipe.url = "file:///test/recipe"

                app.repo_manager.repos = [mock_recipe]

                session = {
                    "metadata": {
                        Database.FILTER_KEY: "Ha",
                        "INSTRUME": "TestCamera",
                    },
                    "imagetyp": "BIAS",
                }

                step = {"name": "nonexistent-stage", "input": "bias"}
                result = processing.get_recipe_for_session(session, step)
                assert result is None

    def test_get_recipe_filter_mismatch(self, setup_test_environment, mock_analytics):
        """Test that recipes with mismatched filter requirements are skipped."""
        with Starbash() as app:
            with Processing(app) as processing:
                # Create a mock recipe repo that requires a different filter
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.url = "file:///test/recipe"

                def get_side_effect(key, default=None):
                    if key == "recipe.stage.master-bias":
                        return {"tool": "siril"}
                    elif key == "recipe.auto.require.filter":
                        return ["SiiOiii"]  # Requires SiiOiii
                    elif key == "recipe.auto.require.camera":
                        return []
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe.get.side_effect = get_side_effect

                app.repo_manager.repos = [mock_recipe]

                # Session has Ha filter, recipe requires SiiOiii
                session = {
                    "metadata": {
                        Database.FILTER_KEY: "Ha",
                        "INSTRUME": "TestCamera",
                    },
                    "imagetyp": "BIAS",
                }

                step = {"name": "master-bias", "input": "bias"}
                result = processing.get_recipe_for_session(session, step)
                assert result is None

    def test_get_recipe_camera_mismatch(self, setup_test_environment, mock_analytics):
        """Test that recipes with mismatched camera requirements are skipped."""
        with Starbash() as app:
            with Processing(app) as processing:
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.url = "file:///test/recipe"

                def get_side_effect(key, default=None):
                    if key == "recipe.stage.light":
                        return {"tool": "siril"}
                    elif key == "recipe.auto.require.filter":
                        return []
                    elif key == "recipe.auto.require.camera":
                        return ["OSC"]  # Requires OSC camera
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe.get.side_effect = get_side_effect

                app.repo_manager.repos = [mock_recipe]

                # Session has Mono camera, recipe requires OSC
                session = {
                    "metadata": {
                        Database.FILTER_KEY: "Ha",
                        "INSTRUME": "MonoCamera",
                    },
                    "imagetyp": "LIGHT",
                }

                step = {"name": "light", "input": "light"}
                result = processing.get_recipe_for_session(session, step)
                assert result is None

    def test_get_recipe_successful_match(self, setup_test_environment, mock_analytics):
        """Test successful recipe matching with all requirements met."""
        with Starbash() as app:
            with Processing(app) as processing:
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.url = "file:///test/recipe"

                def get_side_effect(key, default=None):
                    if key == "recipe.stage.light":
                        return {"tool": "siril", "script": "test"}
                    elif key == "recipe.auto.require.filter":
                        return ["SiiOiii", "HaOiii"]  # Accepts multiple filters
                    elif key == "recipe.auto.require.camera":
                        return ["OSC"]
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe.get.side_effect = get_side_effect

                app.repo_manager.repos = [mock_recipe]

                # Session matches all requirements
                session = {
                    "metadata": {
                        Database.FILTER_KEY: "SiiOiii",
                        "INSTRUME": "OSC",
                    },
                    "imagetyp": "LIGHT",
                }

                step = {"name": "light", "input": "light"}
                result = processing.get_recipe_for_session(session, step)
                assert result is mock_recipe

    def test_get_recipe_no_requirements(self, setup_test_environment, mock_analytics):
        """Test that recipes without requirements match any session."""
        with Starbash() as app:
            with Processing(app) as processing:
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.url = "file:///test/recipe"

                def get_side_effect(key, default=None):
                    if key == "recipe.stage.master-bias":
                        return {"tool": "siril", "script": "test"}
                    elif key == "recipe.auto.require.filter":
                        return []  # No filter requirement
                    elif key == "recipe.auto.require.camera":
                        return []  # No camera requirement
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe.get.side_effect = get_side_effect

                app.repo_manager.repos = [mock_recipe]

                # Session with arbitrary metadata
                session = {
                    "metadata": {
                        Database.FILTER_KEY: "AnyFilter",
                        "INSTRUME": "AnyCamera",
                    },
                    "imagetyp": "BIAS",
                }

                step = {"name": "master-bias", "input": "bias"}
                result = processing.get_recipe_for_session(session, step)
                assert result is mock_recipe

    def test_get_recipe_first_match_wins(self, setup_test_environment, mock_analytics):
        """Test that the first matching recipe is returned."""
        with Starbash() as app:
            with Processing(app) as processing:
                # Create two matching recipes
                mock_recipe1 = MagicMock()
                mock_recipe1.kind.return_value = "recipe"
                mock_recipe1.url = "file:///test/recipe1"

                mock_recipe2 = MagicMock()
                mock_recipe2.kind.return_value = "recipe"
                mock_recipe2.url = "file:///test/recipe2"

                def get_side_effect1(key, default=None):
                    if key == "recipe.stage.master-dark":
                        return {"tool": "siril"}
                    elif key == "recipe.auto.require.filter":
                        return []
                    elif key == "recipe.auto.require.camera":
                        return []
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                def get_side_effect2(key, default=None):
                    if key == "recipe.stage.master-dark":
                        return {"tool": "siril"}
                    elif key == "recipe.auto.require.filter":
                        return []
                    elif key == "recipe.auto.require.camera":
                        return []
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe1.get.side_effect = get_side_effect1
                mock_recipe2.get.side_effect = get_side_effect2

                app.repo_manager.repos = [mock_recipe1, mock_recipe2]

                session = {"metadata": {}, "imagetyp": "DARK"}

                step = {"name": "master-dark", "input": "dark"}
                result = processing.get_recipe_for_session(session, step)
                # First recipe should be returned
                assert result is mock_recipe1

    def test_get_recipe_session_without_metadata(self, setup_test_environment, mock_analytics):
        """Test handling of sessions without metadata field."""
        with Starbash() as app:
            with Processing(app) as processing:
                mock_recipe = MagicMock()
                mock_recipe.kind.return_value = "recipe"
                mock_recipe.url = "file:///test/recipe"

                def get_side_effect(key, default=None):
                    if key == "recipe.stage.master-flat":
                        return {"tool": "siril"}
                    elif key == "recipe.auto.require.filter":
                        return ["Ha"]  # Requires filter
                    elif key == "recipe.auto.require.camera":
                        return []
                    elif key == "recipe.auto.require.color":
                        return False
                    return default

                mock_recipe.get.side_effect = get_side_effect

                app.repo_manager.repos = [mock_recipe]

                # Session without metadata should not match if requirements exist
                session = {"imagetyp": "FLAT"}

                step = {"name": "master-flat", "input": "flat"}
                result = processing.get_recipe_for_session(session, step)
                assert result is None
