"""Tests for local GitHub Pages site generation."""

from pathlib import Path
from types import SimpleNamespace

from starbash.publish.github import GitHubPublisher


def _publisher(tmp_path: Path) -> GitHubPublisher:
    processed = tmp_path / "processed"
    processed.mkdir(exist_ok=True)
    repo = SimpleNamespace(get_path=lambda: processed)
    sb = SimpleNamespace(repo_manager=SimpleNamespace(get_repos_by_kind=lambda kind: [repo]))
    return GitHubPublisher(sb, tmp_path / "site")


def test_publisher_reads_split_target_and_publishes_main_toml(tmp_path):
    """The publisher discovers split metadata and copies the workflow file."""
    processed = tmp_path / "processed"
    target = processed / "M 42!"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (metadata / "about.toml").write_text(
        '[about]\nsummary = "A target"\n[target]\nid = "M 42!"\n'
    )
    (metadata / "sessions.toml").write_text(
        '[[sessions]]\ndate = "2026-08-31"\nframes = []\n'
    )

    publisher = _publisher(tmp_path)
    publisher.publish()

    asset = tmp_path / "site" / "assets" / "targets" / "m-42" / "main.toml"
    post = tmp_path / "site" / "targets" / "m-42.md"
    assert asset.read_text() == (metadata / "main.toml").read_text()
    assert "View processing workflow" in post.read_text()
    assert "../../assets/targets/m-42/main.toml" in post.read_text()

