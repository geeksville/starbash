"""Unit tests for the report_registration recipe helper."""

from __future__ import annotations

import logging
from pathlib import Path

from starbash.recipes import report_registration
from starbash.siril.import_registration import RegistrationResult


def _write_seq(path: Path, rows: list[tuple[int, int, tuple]]) -> None:
    lines = [f"S 'test' 1 {len(rows)} {sum(s for _, s, _ in rows)} 5 1 6 0 0 0"]
    for index, selected, _ in rows:
        lines.append(f"I {index} {selected}")
    for _, _, metrics in rows:
        fwhm, amplitude, roundness, background, stars = metrics
        lines.append(f"R0 {fwhm} {amplitude} {roundness} 0 {background} {stars} H 1")
    path.write_text("\n".join(lines) + "\n")


def _result(index: int, selected: bool = True) -> RegistrationResult:
    return RegistrationResult(index, selected, 3.0 + index, 4.0, 0.8, 0.001, 20 + index)


def test_build_updates_from_provenance_selected_only():
    results = [_result(1), _result(2, selected=False), _result(3)]
    provenance = {"in_00001.fits": 11, "in_00002.fits": 12, "in_00003.fits": 13}

    updates = report_registration.build_updates_from_provenance(results, provenance, "in")

    assert set(updates) == {11, 13}
    assert updates[11]["FWHM"] == 4.0
    assert updates[13]["Stars"] == 23


def test_build_updates_from_provenance_missing_mapping():
    results = [_result(1), _result(2)]
    provenance = {"in_00001.fits": 11}

    try:
        report_registration.build_updates_from_provenance(results, provenance, "in")
    except ValueError as exc:
        assert "sequence index 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_updates_from_provenance_duplicate_source():
    results = [_result(1), _result(2)]
    provenance = {"in_00001.fits": 11, "in_00002.fits": 11}

    try:
        report_registration.build_updates_from_provenance(results, provenance, "in")
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_updates_from_inputs_uses_retained_sequence_indexes():
    results = [_result(1), _result(2, selected=False), _result(3)]

    updates = report_registration.build_updates_from_inputs(results, [101, 102, 103])

    assert set(updates) == {101, 103}


def test_update_from_seq_merged_path(tmp_path: Path):
    seq = tmp_path / "r_in_.seq"
    _write_seq(seq, [(1, 1, (3.1, 4.0, 0.8, 0.001, 20)), (2, 0, (9.9, 1.0, 0.5, 0.002, 5))])
    seen: dict = {}

    def updater(updates):
        seen.update(updates)
        return len(updates)

    count = report_registration.update_from_seq(
        "r_in",
        process_dir=tmp_path,
        inputs={"frames": {"provenance": {"r_in_00001.fits": 7, "r_in_00002.fits": 8}}},
        updater=updater,
    )

    assert count == 1
    assert set(seen) == {7}
    assert seen[7]["FWHM"] == 3.1


def test_update_from_seq_prefers_provenance_when_filtered(tmp_path: Path):
    # sequence_provenance holds 3 merged inputs, but seqapplyreg filtering
    # compacted the registered seq to 2 rows: provenance pairing by
    # sequence_index must win over positional pairing with the full list.
    seq = tmp_path / "r_in_.seq"
    _write_seq(seq, [(1, 1, (3.1, 4.0, 0.8, 0.001, 20)), (3, 1, (3.2, 4.1, 0.7, 0.002, 30))])
    seen: dict = {}

    def updater(updates):
        seen.update(updates)
        return len(updates)

    count = report_registration.update_from_seq(
        "r_in",
        process_dir=tmp_path,
        inputs={
            "frames": {
                "provenance": {"r_in_00001.fits": 7, "r_in_00002.fits": 9},
                "sequence_provenance": {"in_.seq": [7, 8, 9]},
            }
        },
        updater=updater,
    )

    assert count == 2
    assert set(seen) == {7, 9}


def test_update_from_seq_missing_seq_warns(tmp_path: Path):
    count = report_registration.update_from_seq(
        "r_in",
        process_dir=tmp_path,
        inputs={"frames": {"provenance": {"r_in_00001.fits": 7}}},
        updater=lambda updates: len(updates),
    )
    assert count == 0


def test_update_from_seq_single_input_fallback(tmp_path: Path):
    seq = tmp_path / "r_Ha_bkg_pp_light_s9_.seq"
    _write_seq(seq, [(1, 1, (3.3, 4.0, 0.8, 0.001, 21))])
    seen: dict = {}

    def updater(updates):
        seen.update(updates)
        return len(updates)

    count = report_registration.update_from_seq(
        "all_ha",
        process_dir=tmp_path,
        inputs={
            "frames": {
                "provenance": {},
                "sequence_provenance": {"r_Ha_bkg_pp_light_s9_.seq": [42]},
            }
        },
        updater=updater,
    )

    assert count == 1
    assert set(seen) == {42}


def test_update_from_seq_failure_returns_zero(tmp_path: Path, caplog):
    seq = tmp_path / "r_in_.seq"
    _write_seq(seq, [(1, 1, (3.1, 4.0, 0.8, 0.001, 20))])

    with caplog.at_level(logging.WARNING):
        count = report_registration.update_from_seq(
            "r_in",
            process_dir=tmp_path,
            inputs={"frames": {"provenance": {}}},
            updater=lambda updates: len(updates),
        )

    assert count == 0
    assert "Unable to update Siril registration metadata" in caplog.text
