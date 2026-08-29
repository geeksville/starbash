from pathlib import Path

import pytest

from starbash.siril.import_registration import (
    SirilSequenceError,
    parse_siril_conversion,
    parse_siril_seq,
)


def write_sequence(path: Path, *, selected: str = "1 1\n2 0\n") -> None:
    path.write_text(
        "S 'test' 1 2 1 5 1 6 0 0 0\n"
        f"{''.join(f'I {line}\n' for line in selected.splitlines())}"
        "R0 3.2 4.5 0.8 0 0.001 20 H 1\n"
        "R0 4.2 5.5 0.7 0 0.002 30 H 1\n"
    )


def test_parse_siril_seq_preserves_positional_selection_and_metrics(tmp_path: Path):
    sequence = tmp_path / "test.seq"
    write_sequence(sequence)

    results = parse_siril_seq(sequence)

    assert len(results) == 2
    assert results[0].sequence_index == 1
    assert results[0].selected is True
    assert results[0].as_metadata() == {
        "FWHM": 3.2,
        "Amplitude": 4.5,
        "Roundness": 0.8,
        "Background": 0.001,
        "Stars": 20,
    }
    assert results[1].sequence_index == 2
    assert results[1].selected is False


def test_parse_siril_seq_rejects_count_mismatch(tmp_path: Path):
    sequence = tmp_path / "test.seq"
    sequence.write_text(
        "S 'test' 1 2 1 5 1 6 0 0 0\nI 1 1\n"
        "R0 3.2 4.5 0.8 0 0.001 20 H 1\n"
    )

    with pytest.raises(SirilSequenceError, match="I records"):
        parse_siril_seq(sequence)


def test_parse_siril_conversion_preserves_noncontiguous_mapping(tmp_path: Path):
    conversion = tmp_path / "conversion.txt"
    conversion.write_text(
        "'./r_source_00001.fit' -> 'all_00001.fit'\n"
        "'./r_source_00003.fit' -> 'all_00002.fit'\n"
    )

    result = parse_siril_conversion(conversion)

    assert [(item.source_name, item.merged_name, item.merged_index) for item in result] == [
        ("r_source_00001.fit", "all_00001.fit", 1),
        ("r_source_00003.fit", "all_00002.fit", 2),
    ]
