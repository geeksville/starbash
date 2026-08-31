"""Tests for the one-time processed-target migration command."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from starbash.main import app

runner = CliRunner(env={"NO_COLOR": "1"})


def test_fix_targets_migrates_every_legacy_target(tmp_path):
    """The command converts all legacy target directories in the processed repo."""
    processed = tmp_path / "processed"
    processed.mkdir()
    for name in ("sh291", "m42"):
        target = processed / name
        target.mkdir()
        (target / "starbash.toml").write_text("[repo]\nkind = 'processed-target'\n")

    repo = SimpleNamespace(get_path=lambda: processed)
    with patch("starbash.commands.fix_targets.Starbash") as starbash_class:
        sb = starbash_class.return_value.__enter__.return_value
        sb.repo_manager.get_repos_by_kind.return_value = [repo]
        result = runner.invoke(app, ["fix-targets"])

    assert result.exit_code == 0
    assert "Converted 2 processed target(s)" in result.stdout


def test_fix_targets_requires_one_local_processed_repo():
    """The command fails clearly when the processed repository is ambiguous."""
    with patch("starbash.commands.fix_targets.Starbash") as starbash_class:
        sb = starbash_class.return_value.__enter__.return_value
        sb.repo_manager.get_repos_by_kind.return_value = []
        result = runner.invoke(app, ["fix-targets"])

    assert result.exit_code != 0
    assert "Expected exactly one processed repository" in result.stdout
