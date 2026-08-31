"""Tests for the consolidated GitHub publishing command."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def test_github_login_starts_analytics_span():
    """GitHub device authentication is recorded as an analytics span."""
    from starbash.commands import publish

    span = MagicMock()
    with (
        patch.object(publish, "GitHubService") as github_service,
        patch.object(publish, "analytics_start_span", return_value=span) as start_span,
        patch.object(publish, "GitHubCredentialStore"),
        patch.object(publish.typer, "prompt", return_value=""),
        patch.object(publish.webbrowser, "open", return_value=False),
    ):
        service = github_service.return_value
        service.device_code.return_value = SimpleNamespace(
            verification_uri="https://github.com/login/device",
            user_code="ABCD-EFGH",
        )
        service.poll_device_token.return_value = {"access_token": "token"}
        service.app_is_installed.return_value = True

        publish._authenticate()

    start_span.assert_called_once_with(name="github", op="init")


def test_github_upload_starts_analytics_span(tmp_path):
    """A real GitHub Pages publication is recorded as an analytics span."""
    from starbash.commands import publish
    from starbash.publish.credentials import GitHubCredential

    (tmp_path / "index.html").write_text("site")
    span = MagicMock()
    service = MagicMock()
    service.user.return_value = {"login": "owner"}
    service.app_is_installed.return_value = True
    service.repository.return_value = {"name": "starbash-public"}
    service.branch_exists.return_value = True
    service.create_blob.return_value = "blob-sha"
    service.create_tree.return_value = "tree-sha"
    service.create_commit.return_value = "commit-sha"

    with (
        patch.object(publish, "_rewrite", return_value=tmp_path),
        patch.object(
            publish,
            "GitHubCredentialStore",
            return_value=MagicMock(load=MagicMock(return_value=GitHubCredential("token"))),
        ),
        patch.object(publish, "_credential_service", return_value=service),
        patch.object(publish, "analytics_start_span", return_value=span) as start_span,
    ):
        publish._publish_github(False, False)

    start_span.assert_called_once_with(name="github", op="upload")
