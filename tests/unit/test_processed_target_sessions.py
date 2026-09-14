"""Tests for per-session master selections in ``sessions.toml``.

Covers both the structured (new) shape and the legacy ``used``/``excluded``
string arrays, plus the read/write round-trip through
:class:`~starbash.processed_target.ProcessedTarget`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit

from starbash.processed_target import ProcessedTarget

MAIN_TOML = """[repo]
kind = "processed-target"

[[stages]]
name = "stack_osc"
"""

NEW_SHAPE = """[[sessions]]
date = "2025-08-25"
start = "2025-08-25T04:23:18"
end = "2025-08-25T04:50:10"
filter = "None"
imagetyp = "Light"
object = "m13"
telescop = "OnStep"

[sessions.masters.bias]
selected = "cam/a/bias/master_bias_gain100.fit"
selected_by = "auto"

[[sessions.masters.bias.candidates]]
path = "cam/a/bias/master_bias_gain100.fit"
score = -169472.0
gain_match = true
temp_delta_c = 2.2
in_future = true
reasons = ["gain match", "time Δ=9.0d (in future!)"]

[[sessions.masters.bias.candidates]]
path = "cam/b/bias/master_bias_gain100.fit"
score = -169500.0
gain_match = true
reasons = ["gain match"]

[sessions.masters.flat]
selected = "cam/flat/master_flat_None_gain100.fit"
selected_by = "auto"

[[sessions.masters.flat.candidates]]
path = "cam/flat/master_flat_None_gain100.fit"
score = -169500.0
filter_match = true
reasons = ["filter match"]
"""

LEGACY_SHAPE = """[[sessions]]
date = "2025-08-25"
start = "2025-08-25T04:23:18"
end = "2025-08-25T04:50:10"
filter = "None"
imagetyp = "Light"
object = "m13"
telescop = "OnStep"

[sessions.masters.bias]
used = [
    "cam/a/bias/master_bias_gain100.fit", # -169472 gain match, instrument mismatch
    ]
excluded = [
    "cam/b/bias/master_bias_gain100.fit", # -169500 gain match, in future!
    ]
"""


def _write_target(root: Path, name: str, sessions_toml: str) -> Path:
    """Create a processed-target dir with a main.toml and a sessions.toml."""
    target = root / name
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text(MAIN_TOML, encoding="utf-8")
    (metadata / "sessions.toml").write_text(sessions_toml, encoding="utf-8")
    return target


class TestReadStructured:
    def test_session_options_reads_candidates_and_details(self, tmp_path):
        target = _write_target(tmp_path, "m13", NEW_SHAPE)
        options = ProcessedTarget.open(target).session_options()

        assert len(options) == 1
        option = options[0]
        assert option.label == "2025-08-25 · None · OnStep"
        assert option.key[:2] == ("2025-08-25T04:23:18", "2025-08-25T04:50:10")
        assert [master.type for master in option.masters] == ["bias", "flat"]

        bias = option.masters[0]
        assert bias.selected == "cam/a/bias/master_bias_gain100.fit"
        assert bias.selected_by == "auto"
        assert len(bias.candidates) == 2
        chosen = [c for c in bias.candidates if c.selected]
        assert [c.path for c in chosen] == ["cam/a/bias/master_bias_gain100.fit"]
        assert bias.candidates[0].score == -169472.0
        assert bias.candidates[0].details["gain_match"] is True
        assert bias.candidates[0].details["temp_delta_c"] == 2.2
        assert bias.candidates[0].details["in_future"] is True
        assert bias.candidates[0].reasons == ["gain match", "time Δ=9.0d (in future!)"]
        # Flat-only evidence is carried through as data.
        assert option.masters[1].candidates[0].details["filter_match"] is True

    def test_sessions_without_masters_are_skipped(self, tmp_path):
        target = _write_target(
            tmp_path,
            "m13",
            """[[sessions]]
date = "2025-01-01"
start = "2025-01-01T00:00:00"
end = "2025-01-01T01:00:00"
""",
        )
        assert ProcessedTarget.open(target).session_options() == []


class TestReadLegacy:
    def test_legacy_used_excluded_is_understood(self, tmp_path):
        target = _write_target(tmp_path, "m13", LEGACY_SHAPE)
        options = ProcessedTarget.open(target).session_options()

        assert len(options) == 1
        bias = options[0].masters[0]
        assert bias.type == "bias"
        assert bias.selected_by == "auto"
        # The first `used` entry is the selection; entries keep their comment as data.
        assert bias.selected == "cam/a/bias/master_bias_gain100.fit"
        assert [c.path for c in bias.candidates] == [
            "cam/a/bias/master_bias_gain100.fit",
            "cam/b/bias/master_bias_gain100.fit",
        ]
        assert bias.candidates[0].selected is True
        assert bias.candidates[1].selected is False
        assert bias.candidates[0].score is None
        # tomlkit drops inline-array comments, so legacy entries have no reason data.
        assert bias.candidates[1].reasons == []


class TestWriteSelections:
    def test_save_sets_user_selection_and_preserves_the_document(self, tmp_path):
        target = _write_target(tmp_path, "m13", NEW_SHAPE)
        sessions_path = target / ".starbash" / "sessions.toml"
        pt = ProcessedTarget.open(target)
        options = pt.session_options()
        key = options[0].key
        other = "cam/b/bias/master_bias_gain100.fit"

        pt.save_master_selections([(key, "bias", other)])

        document: Any = tomlkit.parse(sessions_path.read_text(encoding="utf-8"))
        session = document["sessions"][0]
        bias = session["masters"]["bias"]
        assert str(bias["selected"]) == other
        assert str(bias["selected_by"]) == "user"
        # Sibling sections and the candidate evidence survive untouched.
        assert session["date"] == "2025-08-25"
        assert "flat" in session["masters"]
        candidate_paths = [str(c["path"]) for c in bias["candidates"]]
        assert candidate_paths == [
            "cam/a/bias/master_bias_gain100.fit",
            "cam/b/bias/master_bias_gain100.fit",
        ]
        assert bias["candidates"][0]["gain_match"] is True

    def test_save_creates_a_missing_master_table(self, tmp_path):
        target = _write_target(
            tmp_path,
            "m13",
            """[[sessions]]
date = "2025-08-25"
start = "2025-08-25T04:23:18"
end = "2025-08-25T04:50:10"
filter = "None"
""",
        )
        sessions_path = target / ".starbash" / "sessions.toml"
        pt = ProcessedTarget.open(target)
        # No masters yet, so there is nothing to read — but we can still write one.
        pt.save_master_selections(
            [(("2025-08-25T04:23:18", "2025-08-25T04:50:10"), "dark", "cam/dark/master.fit")]
        )

        document: Any = tomlkit.parse(sessions_path.read_text(encoding="utf-8"))
        dark = document["sessions"][0]["masters"]["dark"]
        assert str(dark["selected"]) == "cam/dark/master.fit"
        assert str(dark["selected_by"]) == "user"

    def test_empty_edits_do_not_rewrite_the_file(self, tmp_path):
        target = _write_target(tmp_path, "m13", NEW_SHAPE)
        sessions_path = target / ".starbash" / "sessions.toml"
        before = sessions_path.read_text(encoding="utf-8")

        ProcessedTarget.open(target).save_master_selections([])

        assert sessions_path.read_text(encoding="utf-8") == before


class TestOrdering:
    def test_sessions_are_ordered_by_start(self, tmp_path):
        second = NEW_SHAPE.replace("2025-08-25", "2026-07-03")
        text = NEW_SHAPE + "\n" + second
        target = _write_target(tmp_path, "m13", text)
        options = ProcessedTarget.open(target).session_options()

        assert [option.key[0] for option in options] == [
            "2025-08-25T04:23:18",
            "2026-07-03T04:23:18",
        ]
