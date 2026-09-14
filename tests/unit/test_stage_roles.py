"""Tests for stage roles: interchangeable implementations with automatic fallback.

See ``doc/plans/stage-roles.md``.  A stage may declare a ``role`` ("deblur",
"denoise", ...); when several *non-disabled, tool-available* stages share a role
only the best ``priority`` one runs, and an ``after`` pattern may name either a
stage or the role.
"""

from pathlib import Path
from typing import Any

import tomlkit

from starbash.stages import StageSelection, select_stages, sort_stages

RECIPES = Path(__file__).parents[2] / "starbash-recipes"


def _stage(
    name: str,
    role: str | None = None,
    priority: int | None = None,
    tool: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal stage dict, like the recipe loader would."""
    stage: dict[str, Any] = {"name": name}
    if role is not None:
        stage["role"] = role
    if priority is not None:
        stage["priority"] = priority
    if tool is not None:
        stage["tool"] = {"name": tool}
    stage.update(extra)
    return stage


def _role_catalog() -> list[dict[str, Any]]:
    """The phase-1 deblur/denoise catalog, in recipe-registration order."""
    return [
        _stage("deconv-obj", role="deblur", priority=300, tool="graxpert"),
        _stage("denoise", role="denoise", priority=300, tool="graxpert"),
        _stage("blur_exterminator", role="deblur", priority=350, tool="rc-astro"),
        _stage("noise_exterminator", role="denoise", priority=350, tool="rc-astro"),
    ]


def _available(*tools: str):
    """An ``is_available`` predicate for the given tool names."""
    return lambda tool: tool in tools


class TestSelectStages:
    """Picking one implementation per role."""

    def test_prefers_the_highest_priority_implementation(self):
        selection = select_stages(_role_catalog(), is_available=_available("graxpert", "rc-astro"))
        assert [s["name"] for s in selection.stages] == [
            "blur_exterminator",
            "noise_exterminator",
        ]
        assert selection.roles == {"deblur": "blur_exterminator", "denoise": "noise_exterminator"}

    def test_records_why_the_loser_was_dropped(self):
        selection = select_stages(_role_catalog(), is_available=_available("graxpert", "rc-astro"))
        assert "blur_exterminator" in selection.dropped["deconv-obj"]
        assert "deblur" in selection.dropped["deconv-obj"]
        assert "noise_exterminator" in selection.dropped["denoise"]

    def test_logs_which_implementation_won(self, caplog):
        """The loser is announced at INFO so a user can see which one ran."""
        with caplog.at_level("INFO"):
            select_stages(_role_catalog(), is_available=_available("graxpert", "rc-astro"))

        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "shares role 'deblur' with 'blur_exterminator'" in m and "priority 350" in m
            for m in messages
        ), messages
        assert any("shares role 'denoise' with 'noise_exterminator'" in m for m in messages), (
            messages
        )

    def test_logs_a_role_nobody_can_implement(self, caplog):
        """A role with no candidate takes its consumers with it - say so at INFO.

        This is the ``exclude_by_default`` migration case (§3.4): the user's
        persisted exclusion is the reason, and the message names it.
        """
        with caplog.at_level("INFO"):
            select_stages(
                _role_catalog(),
                is_available=_available("graxpert", "rc-astro"),
                is_excluded=lambda s: s["name"] in {"denoise", "noise_exterminator"},
            )

        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "No available stage implements role 'denoise'" in m
            and "'denoise': excluded for this target" in m
            for m in messages
        ), messages

    def test_falls_back_to_graxpert_when_rc_astro_is_missing(self):
        """The whole point: no rc-astro must not mean no deblur/denoise."""
        selection = select_stages(_role_catalog(), is_available=_available("graxpert"))
        assert [s["name"] for s in selection.stages] == ["deconv-obj", "denoise"]
        assert selection.roles == {"deblur": "deconv-obj", "denoise": "denoise"}

    def test_excluding_the_winner_promotes_the_other_implementation(self):
        selection = select_stages(
            _role_catalog(),
            is_available=_available("graxpert", "rc-astro"),
            is_excluded=lambda s: s["name"] in {"blur_exterminator", "noise_exterminator"},
        )
        assert [s["name"] for s in selection.stages] == ["deconv-obj", "denoise"]
        assert selection.dropped["blur_exterminator"] == "excluded for this target"

    def test_no_implementation_available_leaves_the_role_unfilled(self):
        selection = select_stages(_role_catalog(), is_available=_available("siril"))
        assert selection.stages == []
        assert selection.roles == {}
        assert selection.dropped["deconv-obj"] == "tool 'graxpert' is not installed"
        assert selection.dropped["noise_exterminator"] == "tool 'rc-astro' is not installed"

    def test_roles_by_stage_includes_dropped_members(self):
        selection = select_stages(_role_catalog(), is_available=_available("graxpert"))
        assert selection.roles_by_stage == {
            "deconv-obj": "deblur",
            "denoise": "denoise",
            "blur_exterminator": "deblur",
            "noise_exterminator": "denoise",
        }

    def test_equal_priority_keeps_catalog_order(self):
        """Ties are broken by catalog order (earlier wins), as elsewhere in stages.py."""
        catalog = [
            _stage("first", role="r", priority=100),
            _stage("second", role="r", priority=100),
        ]
        assert select_stages(catalog).roles == {"r": "first"}

        # Asserted the other way round too: the winner follows registration order,
        # not some incidental property of the names (e.g. alphabetical).
        reversed_catalog = [
            _stage("second", role="r", priority=100),
            _stage("first", role="r", priority=100),
        ]
        assert select_stages(reversed_catalog).roles == {"r": "second"}

    def test_higher_priority_wins_not_lower(self):
        """Pin the §7.1 decision, so a future flip of the rule is deliberate.

        The code has always read a larger ``priority`` as "more important"; roles
        adopt that rule rather than inventing a second one.  If this ever needs to
        change, this test is the place the decision is recorded.
        """
        catalog = [
            _stage("low_but_first", role="r", priority=10),
            _stage("high_but_second", role="r", priority=20),
        ]
        # Higher wins, even though the lower-priority stage comes first in the catalog.
        assert select_stages(catalog).roles == {"r": "high_but_second"}

    def test_missing_priority_counts_as_zero(self):
        catalog = [_stage("plain", role="r"), _stage("boosted", role="r", priority=1)]
        assert select_stages(catalog).roles == {"r": "boosted"}

    def test_disabled_stage_is_dropped(self):
        catalog = [_stage("off", role="r", disabled=True), _stage("on", role="r")]
        selection = select_stages(catalog)
        assert [s["name"] for s in selection.stages] == ["on"]
        assert selection.dropped["off"] == "disabled"

    def test_stages_without_a_role_are_untouched(self):
        """Recipes that never opt into roles must behave exactly as before."""
        catalog = [_stage("crop"), _stage("stack_osc", priority=310)]
        selection = select_stages(catalog, is_available=_available("siril"))
        assert selection.stages == catalog
        assert selection.roles == {}
        assert selection.dropped == {}

    def test_unavailable_non_role_stage_is_dropped(self):
        """A stage with no role is still dropped when its tool is missing."""
        catalog = [_stage("crop", tool="siril"), _stage("report", tool="python")]
        selection = select_stages(catalog, is_available=_available("siril"))
        assert [s["name"] for s in selection.stages] == ["crop"]
        assert selection.dropped["report"] == "tool 'python' is not installed"

    def test_stage_without_a_tool_is_available(self):
        assert select_stages([_stage("crop")], is_available=_available()).stages != []


class TestResolveAfterPattern:
    """``after`` may name a stage *or* a role (doc/plans/stage-roles.md §6)."""

    @staticmethod
    def _rc_astro_selection() -> StageSelection:
        return select_stages(_role_catalog(), is_available=_available("graxpert", "rc-astro"))

    def test_role_name_resolves_to_the_winning_stage(self):
        assert self._rc_astro_selection().resolve("denoise") == ["noise_exterminator"]
        assert self._rc_astro_selection().resolve("deblur") == ["blur_exterminator"]

    def test_dropped_member_redirects_to_the_winner(self):
        """A reference to the loser must still produce a real dependency."""
        selection = self._rc_astro_selection()
        assert selection.resolve("deconv-obj") == ["blur_exterminator"]
        assert selection.resolve("denoise") == ["noise_exterminator"]

    def test_selected_stage_name_resolves_to_itself(self):
        selection = self._rc_astro_selection()
        assert selection.resolve("blur_exterminator") == ["blur_exterminator"]

    def test_graxpert_only_resolves_to_graxpert(self):
        selection = select_stages(_role_catalog(), is_available=_available("graxpert"))
        assert selection.resolve("denoise") == ["denoise"]
        assert selection.resolve("noise_exterminator") == ["denoise"]
        assert selection.resolve("deblur") == ["deconv-obj"]

    def test_stage_and_role_name_collision_yields_one_provider(self):
        """``denoise`` is both the GraXpert stage *and* the role name.

        The union of namespaces must canonicalize to exactly one provider, not both.
        """
        selection = self._rc_astro_selection()
        assert selection.resolve("denoise") == ["noise_exterminator"]

        graxpert = select_stages(_role_catalog(), is_available=_available("graxpert"))
        assert graxpert.resolve("denoise") == ["denoise"]

    def test_regex_still_works(self):
        assert self._rc_astro_selection().resolve(".*exterminator") == [
            "blur_exterminator",
            "noise_exterminator",
        ]

    def test_unmatched_pattern_resolves_to_nothing(self):
        assert self._rc_astro_selection().resolve("no_such_stage") == []

    def test_invalid_regex_resolves_to_nothing(self):
        assert self._rc_astro_selection().resolve("(unclosed") == []

    def test_pattern_naming_an_unimplemented_role_resolves_to_nothing(self):
        selection = select_stages(_role_catalog(), is_available=_available("siril"))
        assert selection.resolve("denoise") == []

    def test_empty_selection_resolves_to_nothing(self):
        """An empty catalog must not crash resolution (it is a real situation: a
        target whose every stage lost its tool, or a unit-test stub)."""
        selection: StageSelection = select_stages([])
        assert selection.stages == []
        assert selection.roles == {}
        assert selection.resolve("denoise") == []
        assert selection.resolve(".*") == []
        assert selection.unimplemented_role("denoise") is None

    def test_unimplemented_role_is_reported_for_a_hint(self):
        selection = select_stages(_role_catalog(), is_available=_available("siril"))
        assert selection.unimplemented_role("denoise") == "denoise"
        assert selection.unimplemented_role("deblur") == "deblur"

    def test_implemented_role_is_not_reported(self):
        assert self._rc_astro_selection().unimplemented_role("denoise") is None
        assert self._rc_astro_selection().unimplemented_role("crop") is None


class TestSortStagesWithResolve:
    """Ordering after selection, when the palette follows a role."""

    @staticmethod
    def _palette(after: str) -> dict[str, Any]:
        return _stage("palette_broadband", inputs=[{"after": after}])

    def test_follows_the_winner_when_rc_astro_is_missing(self):
        selection = select_stages(
            [*_role_catalog(), self._palette("denoise")], is_available=_available("graxpert")
        )
        ordered = sort_stages(selection.stages, resolve=selection.resolve)
        names = [s["name"] for s in ordered]
        assert names.index("deconv-obj") < names.index("denoise") < names.index("palette_broadband")

    def test_role_reference_orders_after_the_rc_astro_winner(self):
        selection = select_stages(
            [*_role_catalog(), self._palette("denoise")],
            is_available=_available("graxpert", "rc-astro"),
        )
        ordered = sort_stages(selection.stages, resolve=selection.resolve)
        names = [s["name"] for s in ordered]
        assert names.index("blur_exterminator") < names.index("noise_exterminator")
        assert names.index("noise_exterminator") < names.index("palette_broadband")

    def test_reference_to_the_loser_still_orders_after_the_winner(self):
        selection = select_stages(
            [*_role_catalog(), self._palette("deconv-obj")], is_available=_available("graxpert")
        )
        ordered = sort_stages(selection.stages, resolve=selection.resolve)
        names = [s["name"] for s in ordered]
        assert names.index("denoise") < names.index("palette_broadband")

    def test_a_pattern_nobody_will_run_adds_no_dependency(self):
        """A reference to a stage that is not in the graph simply adds no edge.

        (The resolver is a superset of the plain name regex, so this is the
        genuinely-empty case: ``_get_prior_tasks()`` later raises
        ``NoPriorTaskException`` and the consumer is skipped.)
        """
        selection = select_stages(
            [_stage("other"), self._palette("nosuchstage")], is_available=_available()
        )
        ordered = sort_stages(selection.stages, resolve=selection.resolve)
        names = [s["name"] for s in ordered]
        assert set(names) == {"other", "palette_broadband"}  # nothing dropped, no crash

    def test_an_invalid_regex_falls_back_to_the_regex_path_and_warns(self, caplog):
        """The resolver returns [] for an uncompilable pattern, so the old
        regex path still runs - and still warns instead of crashing."""
        selection = select_stages(
            [_stage("other"), self._palette("(unclosed")], is_available=_available()
        )
        with caplog.at_level("WARNING"):
            ordered = sort_stages(selection.stages, resolve=selection.resolve)
        names = [s["name"] for s in ordered]
        assert set(names) == {"other", "palette_broadband"}
        assert any("Invalid regex pattern" in record.message for record in caplog.records)

    def test_without_a_resolve_callable_behaviour_is_unchanged(self):
        stages = [_stage("a", inputs=[{"after": "b"}]), _stage("b")]
        names = [s["name"] for s in sort_stages(stages)]
        assert names == ["b", "a"]


def _recipe(relative: str) -> dict[str, Any]:
    """Parse a recipe TOML from the starbash-recipes submodule."""
    return dict(tomlkit.parse((RECIPES / relative).read_text()))


def _all_recipe_docs() -> list[tuple[str, dict[str, Any]]]:
    """Every recipe document in the submodule, with its path."""
    docs: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(RECIPES.rglob("*.toml")):
        docs.append((str(path.relative_to(RECIPES)), dict(tomlkit.parse(path.read_text()))))
    return docs


class TestRecipeRoles:
    """The recipes that use roles, and the removal of ``exclude_by_default``."""

    def test_graxpert_stages_declare_their_roles(self):
        deconv = _recipe("graxpert/deconv-obj.toml")["stages"][0]
        assert deconv["role"] == "deblur"
        assert deconv["priority"] == 300

        denoise = _recipe("graxpert/grax-denoise.toml")["stages"][0]
        assert denoise["name"] == "grax-denoise"  # same as the role name, deliberately
        assert denoise["role"] == "denoise"
        assert denoise["priority"] == 300

    def test_rc_astro_stages_are_the_preferred_implementations(self):
        """rc-astro must outrank GraXpert, or the fallback order inverts."""
        blur = _recipe("rc-astro/blur-exterminator.toml")["stages"][0]
        assert blur["role"] == "deblur"
        assert blur["priority"] > _recipe("graxpert/deconv-obj.toml")["stages"][0]["priority"]

        noise = _recipe("rc-astro/noise-exterminator.toml")["stages"][0]
        assert noise["role"] == "denoise"
        assert noise["priority"] > _recipe("graxpert/grax-denoise.toml")["stages"][0]["priority"]

    def test_no_recipe_uses_exclude_by_default_any_more(self):
        """Roles subsume the flag (doc/plans/stage-roles.md §3.4)."""
        offenders = [
            f"{path}:{stage['name']}"
            for path, doc in _all_recipe_docs()
            for stage in doc.get("stages", [])
            if "exclude_by_default" in stage
        ]
        assert offenders == []

    def test_palettes_follow_the_denoise_role(self):
        """Not a denoiser implementation: the palette works with either tool."""
        for relative in ("palette/broadband.toml", "palette/hoo.toml", "palette/sho.toml"):
            doc = _recipe(relative)
            afters = [
                inp["after"]
                for stage in doc["stages"]
                for inp in stage.get("inputs", [])
                if "after" in inp
            ]
            assert afters, f"{relative} has no 'after' inputs"
            assert set(afters) == {"denoise"}, f"{relative} still names an implementation: {afters}"


class TestRoleFallbackPipeline:
    """End-to-end over the real recipe catalog: the palette survives either tool."""

    @staticmethod
    def _catalog() -> list[dict[str, Any]]:
        stages: list[dict[str, Any]] = []
        for relative in (
            "graxpert/deconv-obj.toml",
            "graxpert/grax-denoise.toml",
            "rc-astro/blur-exterminator.toml",
            "rc-astro/noise-exterminator.toml",
            "palette/broadband.toml",
        ):
            stages.extend(dict(s) for s in _recipe(relative)["stages"])
        return stages

    def test_with_rc_astro_the_rc_astro_stages_run(self):
        selection = select_stages(
            self._catalog(), is_available=_available("graxpert", "rc-astro", "siril")
        )
        assert [s["name"] for s in selection.stages] == [
            "blur_exterminator",
            "noise_exterminator",
            "palette_broadband",
        ]
        ordered = [s["name"] for s in sort_stages(selection.stages, resolve=selection.resolve)]
        assert ordered.index("noise_exterminator") < ordered.index("palette_broadband")

    def test_without_rc_astro_the_palette_still_runs_after_graxpert(self):
        """Regression: the palette used to be hard-wired to rc-astro, so a user
        without it got no palette, starnet, merge_stars or thumbnail at all."""
        selection = select_stages(self._catalog(), is_available=_available("graxpert", "siril"))
        assert [s["name"] for s in selection.stages] == [
            "deconv-obj",
            "grax-denoise",
            "palette_broadband",
        ]
        ordered = [s["name"] for s in sort_stages(selection.stages, resolve=selection.resolve)]
        assert ordered.index("deconv-obj") < ordered.index("grax-denoise")
        assert ordered.index("grax-denoise") < ordered.index("palette_broadband")
