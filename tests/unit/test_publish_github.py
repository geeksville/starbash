"""Tests for local GitHub Pages site generation."""

from pathlib import Path
from types import SimpleNamespace

import tomlkit

from starbash.processed_target import ParameterOption, StageOption
from starbash.publish.github import GitHubPublisher, stage_tree_html


def _publisher(tmp_path: Path) -> GitHubPublisher:
    processed = tmp_path / "processed"
    processed.mkdir(exist_ok=True)
    repo = SimpleNamespace(get_path=lambda: processed)
    sb = SimpleNamespace(repo_manager=SimpleNamespace(get_repos_by_kind=lambda kind: [repo]))
    return GitHubPublisher(sb, tmp_path / "site")


def _publisher_for_user(tmp_path: Path, username: str) -> GitHubPublisher:
    processed = tmp_path / "processed"
    processed.mkdir(exist_ok=True)
    repo = SimpleNamespace(get_path=lambda: processed)
    sb = SimpleNamespace(repo_manager=SimpleNamespace(get_repos_by_kind=lambda kind: [repo]))
    return GitHubPublisher(sb, tmp_path / "site", github_username=username)


def test_publisher_reads_split_target_and_publishes_main_toml(tmp_path):
    """The publisher discovers split metadata and copies the workflow file."""
    processed = tmp_path / "processed"
    target = processed / "M 42!"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (metadata / "about.toml").write_text('[about]\nsummary = "A target"\n[target]\nid = "M 42!"\n')
    (metadata / "sessions.toml").write_text('[[sessions]]\ndate = "2026-08-31"\nframes = []\n')
    (target / "M 42.jpg").write_bytes(b"jpeg")

    publisher = _publisher(tmp_path)
    publisher.publish()

    asset = tmp_path / "site" / "assets" / "targets" / "m-42" / "main.toml"
    post = tmp_path / "site" / "targets" / "m-42.md"
    assert asset.read_text() == (metadata / "main.toml").read_text()
    assert "View processing workflow" in post.read_text()
    assert "../../assets/targets/m-42/main.toml" in post.read_text()
    assert 'image: "/assets/targets/m-42/M 42.jpg"' in post.read_text()
    assert "baseurl: /starbash-public" in (tmp_path / "site" / "_config.yml").read_text()
    assert (tmp_path / "site" / "favicon.ico").read_bytes() == (
        Path(__file__).parents[2] / "src" / "starbash" / "assets" / "favicon.ico"
    ).read_bytes()
    assert (
        "href=\"{{ '/favicon.ico' | relative_url }}\""
        in (tmp_path / "site" / "_layouts" / "default.html").read_text()
    )


def test_publisher_renders_github_username_in_target_title(tmp_path):
    """The publisher passes the authenticated GitHub username to Jinja."""
    processed = tmp_path / "processed"
    target = processed / "M 42"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (metadata / "about.toml").write_text('[target]\nid = "M 42"\n')

    _publisher_for_user(tmp_path, "geeksville").publish()

    post = (tmp_path / "site" / "targets" / "m-42.md").read_text()
    assert 'title: "M 42 by geeksville"' in post


def test_publisher_wipes_stale_site_files(tmp_path):
    """The publisher removes old generated files before rebuilding the site."""
    processed = tmp_path / "processed"
    target = processed / "M 42"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (metadata / "about.toml").write_text('[target]\nid = "M 42"\n')
    (target / "M 42.jpg").write_bytes(b"jpeg")

    site = tmp_path / "site"
    stale = site / "stale-file.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("should be removed")

    publisher = GitHubPublisher(_publisher(tmp_path).sb, site)
    publisher.publish()

    assert not stale.exists()
    assert (site / "index.md").exists()


def test_publisher_generates_distinct_pages_for_legacy_targets(tmp_path):
    """Legacy root-level target metadata does not collapse targets to one page."""
    processed = tmp_path / "processed"
    legacy = processed / "m31"
    legacy_metadata = legacy / ".starbash"
    legacy_metadata.mkdir(parents=True)
    (legacy_metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (legacy_metadata / "about.toml").write_text(
        'summary = "M 31 summary"\n'
        "[about]\n"
        'summary = "placeholder summary"\n'
        'target.id = "$target"\n'
        "[target]\n"
        'id = "M 31"\n'
    )

    modern = processed / "sh291"
    modern_metadata = modern / ".starbash"
    modern_metadata.mkdir(parents=True)
    (modern_metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (modern_metadata / "about.toml").write_text(
        '[about]\nsummary = "Sh2 91 summary"\ntarget.id = "Sh2 91"\n'
    )

    publisher = _publisher(tmp_path)
    publisher.publish()

    site = tmp_path / "site"
    index = (site / "index.md").read_text()
    m31_post = (site / "targets" / "m-31.md").read_text()
    assert "[M 31](targets/m-31)" in index
    assert "[Sh2 91](targets/sh2-91)" in index
    assert "M 31 summary" in m31_post
    assert "$target" not in m31_post
    assert (site / "assets" / "targets" / "m-31" / "main.toml").exists()
    assert (site / "assets" / "targets" / "sh2-91" / "main.toml").exists()


def test_stage_tree_html_shows_defaults_grey_and_overrides_bold():
    """Recipe defaults render in the grey class, overrides in the accent class."""
    tree = stage_tree_html(
        [
            StageOption(
                name="stack_osc",
                description="Basic OSC stacking",
                excluded=False,
                parameters=[
                    ParameterOption(
                        name="registration",
                        description="Registration options",
                        default="rej w 3 3",
                    ),
                    ParameterOption(name="framing", description=None, default="max", value="min"),
                ],
                recipe_url="https://github.com/geeksville/starbash-recipes",
                tool="siril",
            ),
            StageOption(
                name="starremoval",
                description=None,
                excluded=True,
                parameters=[],
            ),
        ]
    )

    assert (
        '<a class="sb-stage-name" href="https://github.com/geeksville/starbash-recipes">stack_osc</a>'
        in tree
    )
    assert '<span class="sb-tool">siril</span>' in tree
    assert "Basic OSC stacking" in tree
    # A stage without a browsable recipe URL stays plain (starremoval has none).
    assert '<span class="sb-stage-name">starremoval</span>' in tree
    # A plain default is shown in the grey styling.
    assert '<span class="sb-default">= &quot;rej w 3 3&quot;</span>' in tree
    # An override is bold/accent, with the grey default it replaced beside it.
    assert '<span class="sb-override">= &quot;min&quot;</span>' in tree
    assert '<span class="sb-default">(default &quot;max&quot;)</span>' in tree
    # Excluded stages stay visible but dimmed and marked skipped.
    assert 'class="sb-stage excluded"' in tree
    assert '<span class="sb-skip">skipped</span>' in tree
    # The legend explains the two colours.
    assert "recipe default" in tree
    assert "override" in tree


def test_stage_tree_html_escapes_recipe_and_target_text():
    """Stage names, descriptions and values are HTML-escaped."""
    tree = stage_tree_html(
        [
            StageOption(
                name='evil<script>"stage"',
                description="<&description>",
                excluded=False,
                parameters=[ParameterOption(name='p"name', description=None, default='"&<')],
            )
        ]
    )

    assert "<script>" not in tree
    assert "<&description>" not in tree
    assert "&amp;" in tree
    assert "&lt;" in tree


def test_stage_tree_html_is_empty_without_stages():
    """A target with no recorded stages renders no tree at all."""
    assert stage_tree_html([]) == ""


def test_publisher_renders_recipe_defaults_and_target_overrides(tmp_path):
    """The target page carries the stage tree, merging recipe declarations in."""
    processed = tmp_path / "processed"
    target = processed / "M 42"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text(
        "[repo]\n"
        'kind = "processed-target"\n'
        "[[stages]]\n"
        'name = "stack_osc"\n'
        "[[stages.overrides]]\n"
        'name = "registration"\n'
        'value = "rej w 4 4"\n'
        "[[stages]]\n"
        'name = "starremoval"\n'
        "excluded = true\n"
    )
    (metadata / "about.toml").write_text('[about]\nsummary = "A target"\n[target]\nid = "M 42"\n')

    recipe = SimpleNamespace(
        config=tomlkit.parse(
            "[[stages]]\n"
            'name = "stack_osc"\n'
            'description = "Basic OSC stacking"\n'
            'tool.name = "siril"\n'
            "[[stages.parameters]]\n"
            'name = "registration"\n'
            'default = "rej w 3 3"\n'
            'description = "Registration options for Siril stacking"\n'
            "[[stages.parameters]]\n"
            'name = "framing"\n'
            'default = "max"\n'
        )
    )
    repo = SimpleNamespace(get_path=lambda: processed)
    sb = SimpleNamespace(
        repo_manager=SimpleNamespace(get_repos_by_kind=lambda kind: [repo]),
        get_recipes=lambda: [recipe],
    )

    GitHubPublisher(sb, tmp_path / "site").publish()

    post = (tmp_path / "site" / "targets" / "m-42.md").read_text()
    assert '<div class="sb-stages">' in post
    assert "stack_osc" in post
    assert '<span class="sb-tool">siril</span>' in post
    assert "Basic OSC stacking" in post
    # Default in grey, override in the bold accent next to the default it replaced.
    assert '<span class="sb-default">= &quot;max&quot;</span>' in post
    assert '<span class="sb-override">= &quot;rej w 4 4&quot;</span>' in post
    assert '<span class="sb-default">(default &quot;rej w 3 3&quot;)</span>' in post
    # The excluded stage is visible but marked skipped.
    assert 'class="sb-stage excluded"' in post
    assert "starremoval" in post
    assert '<span class="sb-skip">skipped</span>' in post


def test_publisher_renders_stage_tree_without_recipe_repos(tmp_path):
    """Stages are still listed when the context has no recipe declarations."""
    processed = tmp_path / "processed"
    target = processed / "M 42"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text(
        '[repo]\nkind = "processed-target"\n'
        "[[stages]]\n"
        'name = "stack_osc"\n'
        "[[stages.overrides]]\n"
        'name = "registration"\n'
        'value = "rej w 4 4"\n'
    )
    (metadata / "about.toml").write_text('[about]\nsummary = "A target"\n[target]\nid = "M 42"\n')

    _publisher(tmp_path).publish()

    post = (tmp_path / "site" / "targets" / "m-42.md").read_text()
    assert '<div class="sb-stages">' in post
    assert "stack_osc" in post
    assert '<span class="sb-override">= &quot;rej w 4 4&quot;</span>' in post


def test_publisher_shows_target_coordinates(tmp_path):
    """The page includes RA/Dec when the target metadata carries them."""
    processed = tmp_path / "processed"
    target = processed / "M 42"
    metadata = target / ".starbash"
    metadata.mkdir(parents=True)
    (metadata / "main.toml").write_text('[repo]\nkind = "processed-target"\n')
    (metadata / "about.toml").write_text(
        "[about]\n"
        'summary = "A target"\n'
        "[target]\n"
        'id = "M 42"\n'
        'ra = "05 35 17.3"\n'
        'dec = "-05 23 28"\n'
    )

    _publisher(tmp_path).publish()

    post = (tmp_path / "site" / "targets" / "m-42.md").read_text()
    assert "**Coordinates:** RA 05 35 17.3 / Dec -05 23 28" in post
