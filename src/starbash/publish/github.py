"""Generate a local GitHub Pages-compatible Jekyll site."""

from __future__ import annotations

import html
import re
import shutil
import warnings
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import pygal
from jinja2 import Environment, PackageLoader
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from tomlkit.exceptions import ParseError

from starbash import console
from starbash.paths import get_publish_site_dir
from starbash.processed_target import ProcessedTarget, StageOption, stage_declarations


def slugify(value: str) -> str:
    """Return a stable, URL-safe target slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "target"


def plain(value: Any) -> Any:
    """Convert TOML containers into ordinary Python containers."""
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def equipment_rows(equipment: Any) -> list[dict[str, str | None]]:
    """Normalize current and legacy equipment records for the report table."""
    if not isinstance(equipment, dict):
        return []
    rows: list[dict[str, str | None]] = []
    for kind, record in equipment.items():
        if not isinstance(record, dict):
            continue
        model_value = record.get("model")
        if isinstance(model_value, dict):
            model = model_value.get("long") or model_value.get("short")
        else:
            model = model_value
        if not model:
            fits = record.get("fits", {})
            if isinstance(fits, dict):
                model = next((value for value in fits.values() if value), None)
        url = record.get("url", {})
        info_url = url.get("info") if isinstance(url, dict) else None
        rows.append(
            {
                "kind": str(kind),
                "model": str(model) if model else "Unknown",
                "url": str(info_url) if info_url else None,
            }
        )
    return rows


#: Stylesheet for :func:`stage_tree_html`, scoped to its wrapper so it cannot
#: fight the site theme.  Colours are tuned for the dark ``jekyll-theme-midnight``
#: look: defaults are a muted grey-blue, overrides a bold amber accent.
_STAGE_TREE_CSS = """\
.sb-stages{margin:1.25em 0;font-size:.92rem;line-height:1.5}
.sb-stages ul{list-style:none;margin:.25rem 0;padding:0}
.sb-stages .sb-stage{margin:.35rem 0;padding-left:1.1rem;border-left:2px solid rgba(128,150,180,.45)}
.sb-stages .sb-stage-name{font-weight:600}
.sb-stages a.sb-stage-name{color:inherit;text-decoration:underline dotted;text-underline-offset:.15em}
.sb-stages .sb-tool,.sb-stages .sb-role,.sb-stages .sb-skip{display:inline-block;margin-left:.45rem;padding:.05rem .45rem;border:1px solid rgba(128,150,180,.55);border-radius:.7rem;font-size:.7rem;letter-spacing:.05em;text-transform:uppercase;opacity:.85;vertical-align:.1em}
.sb-stages .sb-skip{border-style:dashed}
.sb-stages .sb-stage.excluded{opacity:.55}
.sb-stages .sb-stage.excluded .sb-stage-name{text-decoration:line-through}
.sb-stages .sb-recipe{margin-left:.45rem;font-size:.78rem;opacity:.9}
.sb-stages .sb-stage-desc{margin-left:.45rem;opacity:.7;font-size:.85rem}
.sb-stages .sb-params{padding-left:1.35rem;margin:.1rem 0}
.sb-stages .sb-param{margin:.05rem 0}
.sb-stages .sb-pname{opacity:.92}
.sb-stages .sb-default{color:#9fb0c3;font-weight:400}
.sb-stages .sb-override{color:#ffb454;font-weight:700}
.sb-stages .sb-legend{font-size:.8rem;opacity:.85;margin:.2rem 0 .6rem}"""


def _display_value(value: Any) -> str:
    """Render a parameter value the way its TOML line would be written."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _esc(value: Any) -> str:
    """HTML-escape any value bound for the stage tree."""
    return html.escape(str(value), quote=True)


def _param_row(param: Any) -> str:
    """One parameter line: grey default, or a bold amber override beside it."""
    bits = ['<li class="sb-param"']
    if param.description:
        bits.append(f' title="{_esc(param.description)}"')
    bits.append(f'><span class="sb-pname">{_esc(param.name)}</span>')
    if param.is_overridden:
        bits.append(f' <span class="sb-override">= {_esc(_display_value(param.value))}</span>')
        if param.default is not None:
            bits.append(
                f' <span class="sb-default">(default {_esc(_display_value(param.default))})</span>'
            )
    elif param.default is not None:
        bits.append(f' <span class="sb-default">= {_esc(_display_value(param.default))}</span>')
    else:
        bits.append(' <span class="sb-default">(no default)</span>')
    bits.append("</li>")
    return "".join(bits)


def _stage_row(stage: StageOption) -> list[str]:
    """The ``<li>`` for one stage: header line plus its parameter lines."""
    css = "sb-stage excluded" if stage.excluded else "sb-stage"
    # The stage name links to the recipe its TOML came from, when that recipe
    # has a browsable (http(s)) URL; local/`pkg://` sources stay plain text.
    recipe_url = str(stage.recipe_url) if stage.recipe_url else ""
    if recipe_url.startswith("http"):
        name_html = f'<a class="sb-stage-name" href="{_esc(recipe_url)}">{_esc(stage.name)}</a>'
    else:
        name_html = f'<span class="sb-stage-name">{_esc(stage.name)}</span>'
    head = [name_html]
    if stage.tool:
        head.append(f'<span class="sb-tool">{_esc(stage.tool)}</span>')
    if stage.role:
        head.append(f'<span class="sb-role">{_esc(stage.role)}</span>')
    if stage.excluded:
        head.append('<span class="sb-skip">skipped</span>')
    if stage.description:
        head.append(f'<span class="sb-stage-desc">{_esc(stage.description)}</span>')

    lines = [f'<li class="{css}">', f'<div class="sb-stage-head">{" ".join(head)}</div>']
    if stage.parameters:
        lines.append('<ul class="sb-params">')
        lines.extend(_param_row(param) for param in stage.parameters)
        lines.append("</ul>")
    lines.append("</li>")
    return lines


def stage_tree_html(stages: Sequence[StageOption]) -> str:
    """Render a target's stages as an HTML tree for its report page.

    Every stage the target records is shown, in order, with the parameters its
    recipe declares: the recipe *defaults* render in muted grey, while values
    this target *overrides* render in a bolder amber accent right beside the
    default they replaced.  Excluded stages stay visible but dimmed and marked
    "skipped", so the tree shows exactly which stages were used.

    Returns ``""`` for a target with no recorded stages.
    """
    if not stages:
        return ""

    lines = [
        '<div class="sb-stages">',
        "<style>",
        _STAGE_TREE_CSS,
        "</style>",
        '<div class="sb-legend">Parameters: <span class="sb-default">grey = recipe default</span>'
        ' &middot; <span class="sb-override">amber = this target&rsquo;s override</span></div>',
        '<ul class="sb-stage-list">',
    ]
    for stage in stages:
        lines.extend(_stage_row(stage))
    lines.extend(["</ul>", "</div>"])
    return "\n".join(lines)


class GitHubPublisher:
    """Generate a complete local Jekyll site from one processed repository."""

    def __init__(
        self,
        sb: Any,
        site_dir: Path | None = None,
        github_username: str | None = None,
    ) -> None:
        self.sb = sb
        self.site_dir = site_dir or get_publish_site_dir()
        self.github_username = github_username
        self.environment = Environment(loader=PackageLoader("starbash", "templates/report"))

    def _processed_root(self) -> Path:
        """Return the sole local processed repository root."""
        repos = self.sb.repo_manager.get_repos_by_kind("processed")
        if len(repos) != 1:
            raise RuntimeError(
                f"publish requires exactly one processed repository, found {len(repos)}"
            )
        root = repos[0].get_path()
        if root is None:
            raise RuntimeError("publish requires a local processed repository")
        return root

    @staticmethod
    def _images(directory: Path) -> list[Path]:
        """Select hero images, or all JPEGs when no heroes are present."""
        images = sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
            ),
            key=lambda path: path.name.lower(),
        )
        heroes = [path for path in images if path.name.lower().startswith("hero")]
        return heroes or images

    def _stage_declarations(self) -> dict[str, dict[str, Any]]:
        """Map stage name -> declared description/parameters from the recipe repos.

        Best effort: contexts without ``get_recipes`` (bare front ends, tests)
        get an empty map, and the report then simply omits recipe-declared
        defaults while still showing the target's recorded stages.
        """
        get_recipes = getattr(self.sb, "get_recipes", None)
        if not callable(get_recipes):
            return {}
        try:
            return stage_declarations(get_recipes())
        except Exception:  # noqa: BLE001 - a broken recipe repo must not kill the report
            warnings.warn(
                "Could not read recipe declarations; the report omits defaults", stacklevel=2
            )
            return {}

    def _targets(self, root: Path) -> list[tuple[Path, dict[str, Any], ProcessedTarget]]:
        targets: list[tuple[Path, dict[str, Any], ProcessedTarget]] = []
        for directory in sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=lambda path: path.name.lower(),
        ):
            metadata_dir = directory / ".starbash"
            main_config = metadata_dir / "main.toml"
            about_config = metadata_dir / "about.toml"
            if not main_config.exists() or not about_config.exists():
                warnings.warn(
                    f"Skipping incomplete processed target {directory}; "
                    "expected .starbash/main.toml and .starbash/about.toml",
                    stacklevel=2,
                )
                continue
            try:
                target = ProcessedTarget.open(directory)
                document: dict[str, Any] = {}
                document.update(plain(target.repo.config))
                document.update(plain(target.about))
                document.update(plain(target.sessions))
                document["_main_config"] = main_config
                targets.append((directory, document, target))
            except (OSError, ParseError) as exc:
                warnings.warn(f"Skipping malformed target {metadata_dir}: {exc}", stacklevel=2)
        return targets

    def publish(self) -> Path:
        """Regenerate the complete site and return its root directory."""
        root = self._processed_root()
        targets = self._targets(root)
        declarations = self._stage_declarations()

        # Wipe any previously generated site so stale files don't persist.
        if self.site_dir.exists():
            shutil.rmtree(self.site_dir)
        self.site_dir.mkdir(parents=True, exist_ok=True)

        posts = self.site_dir / "targets"
        assets_root = self.site_dir / "assets" / "targets"
        posts.mkdir(parents=True, exist_ok=True)
        assets_root.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating site", total=2 + len(targets))

            config = resources.files("starbash.templates.report").joinpath("_config.yml")
            (self.site_dir / "_config.yml").write_text(
                config.read_text(encoding="utf-8"), encoding="utf-8"
            )
            gemfile = resources.files("starbash.templates.report").joinpath("Gemfile")
            (self.site_dir / "Gemfile").write_text(
                gemfile.read_text(encoding="utf-8"), encoding="utf-8"
            )
            layouts = self.site_dir / "_layouts"
            layouts.mkdir(exist_ok=True)
            default_layout = resources.files("starbash.templates.report").joinpath("default.html")
            (layouts / "default.html").write_text(
                default_layout.read_text(encoding="utf-8"), encoding="utf-8"
            )
            favicon = resources.files("starbash.assets").joinpath("favicon.ico")
            with (
                favicon.open("rb") as source,
                (self.site_dir / "favicon.ico").open("wb") as destination,
            ):
                shutil.copyfileobj(source, destination)
            progress.update(task, description="Copied static assets", advance=1)
            index_targets: list[dict[str, Any]] = []
            for directory, document, processed in targets:
                about = document.get("about", {})
                if not isinstance(about, dict):
                    about = {}
                target = document.get("target")
                if not isinstance(target, dict):
                    target = about.get("target", {})
                if not isinstance(target, dict):
                    target = {}
                summary = document.get("summary")
                if isinstance(summary, str):
                    about = {**about, "summary": summary}
                name = str(target.get("id") or directory.name)
                description = about.get("description")
                if not isinstance(description, str) or not description.strip():
                    description = about.get("summary")
                if not isinstance(description, str) or not description.strip():
                    description = f"Processed Starbash target: {name}."
                slug = slugify(name)
                asset_dir = assets_root / slug
                asset_dir.mkdir(parents=True, exist_ok=True)
                main_config = document.pop("_main_config")
                shutil.copy2(main_config, asset_dir / "main.toml")
                image_urls: list[str] = []
                for image in self._images(directory):
                    shutil.copy2(image, asset_dir / image.name)
                    image_urls.append(f"assets/targets/{slug}/{image.name}")
                sessions: list[dict[str, Any]] = []
                for number, session in enumerate(document.get("sessions", []), start=1):
                    frames = session.get("frames", [])
                    chart = pygal.Line(
                        title=f"Session {session.get('date', number)}",
                        height=300,
                        show_x_labels=False,
                    )
                    chart.add(
                        "Wind gust",
                        [frame.get("metadata", {}).get("WINDGUST", 0) for frame in frames],
                    )
                    fwhm_values = [frame.get("metadata", {}).get("FWHM") for frame in frames]
                    if any(value is not None for value in fwhm_values):
                        chart.add("FWHM", fwhm_values)
                    chart_name = f"session-{number}.svg"
                    chart.render_to_file(str(asset_dir / chart_name))
                    sessions.append(
                        {
                            **session,
                            "equipment_rows": equipment_rows(session.get("equipment", {})),
                            "chart": f"../../assets/targets/{slug}/{chart_name}",
                        }
                    )
                page_images = [f"../../{url}" for url in image_urls]
                seo_image = f"/{image_urls[0]}" if image_urls else None
                stage_tree = stage_tree_html(processed.stage_options(declarations))
                page_name = f"{slug}.md"
                post = self.environment.get_template("target.md.jinja").render(
                    target={**target, "name": name},
                    about=about,
                    description=description,
                    github_username=self.github_username,
                    images=page_images,
                    image=seo_image,
                    sessions=sessions,
                    stage_tree=stage_tree,
                    workflow_url=f"../../assets/targets/{slug}/main.toml",
                )
                (posts / page_name).write_text(post)
                index_targets.append(
                    {
                        "name": name,
                        "url": f"targets/{slug}",
                        "image": image_urls[0] if image_urls else None,
                    }
                )
                progress.update(task, description=f"Generated {name}", advance=1)

            index = self.environment.get_template("index.md.jinja").render(targets=index_targets)
            (self.site_dir / "index.md").write_text(index)
            progress.update(task, description="Wrote index", advance=1)

        return self.site_dir
