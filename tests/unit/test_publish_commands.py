"""Tests for the consolidated GitHub publishing command."""

from unittest.mock import patch

from typer.testing import CliRunner

from starbash.main import app

runner = CliRunner(env={"NO_COLOR": "1"})


def test_github_command_passes_options_to_publisher():
    """The command callback forwards dry-run and login flags."""
    with patch("starbash.commands.publish._publish_github") as publish:
        result = runner.invoke(app, ["publish", "github", "--dry-run", "--login"])

    assert result.exit_code == 0
    publish.assert_called_once_with(True, True)


def test_github_rewrite_remains_local_command():
    """The rewrite subcommand is not confused with the publishing callback."""
    with patch("starbash.commands.publish._rewrite") as rewrite:
        result = runner.invoke(app, ["publish", "github", "rewrite"])

    assert result.exit_code == 0
    rewrite.assert_called_once_with()


def test_old_github_commands_are_rejected():
    """The former init and upload command paths are no longer public."""
    for command in ("init", "upload"):
        result = runner.invoke(app, ["publish", "github", command])
        assert result.exit_code != 0


def test_dry_run_does_not_require_a_credential(tmp_path):
    """A dry run can generate and validate the site without signing in."""
    with patch("starbash.commands.publish._rewrite") as rewrite:
        rewrite.return_value = tmp_path
        result = runner.invoke(app, ["publish", "github", "--dry-run"])

    assert result.exit_code == 0
    rewrite.assert_called_once_with()
