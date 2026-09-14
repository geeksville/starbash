"""Tests for per-session master selection during processing.

``_pick_master`` decides between the scorer's top candidate and a prior explicit
(``user``) choice; ``_master_selection_table`` renders the structured
``[sessions.masters.<type>]`` entry written to ``sessions.toml``.
"""

from __future__ import annotations

import logging

import pytest

from starbash.processing import _master_selection_table, _pick_master
from starbash.score import ScoredCandidate


def _scored(path: str, score: float = 1.0) -> ScoredCandidate:
    """A minimal scored candidate (only ``path``/``score`` matter here)."""
    return ScoredCandidate(
        candidate={"path": path}, score=score, reason="gain match", reasons=["gain match"]
    )


class TestPickMaster:
    def test_auto_entry_takes_the_top_scorer(self):
        session = {"masters": {"bias": {"selected": "b", "selected_by": "auto"}}}
        chosen, chosen_by = _pick_master("bias", [_scored("a", 2), _scored("b", 1)], session)

        assert chosen.candidate["path"] == "a"
        assert chosen_by == "auto"

    def test_user_entry_is_honoured(self):
        session = {"masters": {"bias": {"selected": "b", "selected_by": "user"}}}
        chosen, chosen_by = _pick_master("bias", [_scored("a", 2), _scored("b", 1)], session)

        assert chosen.candidate["path"] == "b"
        assert chosen_by == "user"

    def test_user_entry_that_no_longer_exists_falls_back(self, caplog):
        session = {"masters": {"bias": {"selected": "gone", "selected_by": "user"}}}
        with caplog.at_level(logging.WARNING):
            chosen, chosen_by = _pick_master("bias", [_scored("a", 2)], session)

        assert chosen.candidate["path"] == "a"
        assert chosen_by == "auto"
        assert "no longer a candidate" in caplog.text

    def test_legacy_entry_is_not_treated_as_user(self):
        session = {"masters": {"bias": {"used": ["a"]}}}
        chosen, chosen_by = _pick_master("bias", [_scored("a", 2), _scored("b", 1)], session)

        assert chosen.candidate["path"] == "a"
        assert chosen_by == "auto"

    def test_no_prior_entry_picks_the_top_scorer(self):
        chosen, chosen_by = _pick_master("bias", [_scored("a", 2)], {})

        assert chosen.candidate["path"] == "a"
        assert chosen_by == "auto"


class TestMasterSelectionTable:
    def test_writes_selected_and_structured_candidates(self):
        chosen = _scored("b", 1.0)
        table = _master_selection_table(chosen, "user", [_scored("a", 2.0), chosen])

        assert str(table["selected"]) == "b"
        assert str(table["selected_by"]) == "user"
        candidates = table["candidates"]
        assert [str(candidate["path"]) for candidate in candidates] == ["a", "b"]
        assert float(candidates[0]["score"]) == pytest.approx(2.0)
        assert list(candidates[0]["reasons"]) == ["gain match"]
