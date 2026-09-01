"""Generate a local GitHub Pages-compatible Jekyll site."""

from __future__ import annotations

import re
import shutil
import warnings
from importlib import resources
from pathlib import Path
from typing import Any

import pygal
import tomlkit
from jinja2 import Environment, PackageLoader
from tomlkit.exceptions import ParseError

from starbash.paths import get_publish_site_dir


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


class GitHubPublisher:
    """Generate a complete local Jekyll site from one processed repository."""

    def __init__(self, sb: Any, site_dir: Path | None = None) -> None:
        self.sb = sb
        self.site_dir = site_dir or get_publish_site_dir()
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

    def _targets(self, root: Path) -> list[tuple[Path, dict[str, Any]]]:
        targets: list[tuple[Path, dict[str, Any]]] = []
        for directory in sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=lambda path: path.name.lower(),
        ):
            metadata_dir = directory / ".starbash"
            main_config = metadata_dir / "main.toml"
            about_config = metadata_dir / "about.toml"
            sessions_config = metadata_dir / "sessions.toml"
            if not main_config.exists() or not about_config.exists():
                warnings.warn(
                    f"Skipping incomplete processed target {directory}; "
                    "expected .starbash/main.toml and .starbash/about.toml",
                    stacklevel=2,
                )
                continue
            try:
                document: dict[str, Any] = {}
                document.update(plain(tomlkit.parse(main_config.read_text(encoding="utf-8"))))
                document.update(plain(tomlkit.parse(about_config.read_text(encoding="utf-8"))))
                if sessions_config.exists():
                    document.update(
                        plain(tomlkit.parse(sessions_config.read_text(encoding="utf-8")))
                    )
                document["_main_config"] = main_config
                targets.append((directory, document))
            except (OSError, ParseError) as exc:
                warnings.warn(f"Skipping malformed target {metadata_dir}: {exc}", stacklevel=2)
        return targets

    def publish(self) -> Path:
        """Regenerate the complete site and return its root directory."""
        root = self._processed_root()
        posts = self.site_dir / "targets"
        assets_root = self.site_dir / "assets" / "targets"
        posts.mkdir(parents=True, exist_ok=True)
        assets_root.mkdir(parents=True, exist_ok=True)
        config = resources.files("starbash.templates.report").joinpath("_config.yml")
        (self.site_dir / "_config.yml").write_text(
            config.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.site_dir / "Gemfile").write_text(
            'source "https://rubygems.org"\n'
            'gem "github-pages", group: :jekyll_plugins\n'
        )
        layouts = self.site_dir / "_layouts"
        layouts.mkdir(exist_ok=True)
        default_layout = resources.files("starbash.templates.report").joinpath("default.html")
        (layouts / "default.html").write_text(default_layout.read_text(encoding="utf-8"), encoding="utf-8")
        index_targets: list[dict[str, Any]] = []
        for directory, document in self._targets(root):
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
            page_name = f"{slug}.md"
            post = self.environment.get_template("target.md.jinja").render(
                target={**target, "name": name},
                about=about,
                images=[f"../../{s}" for s in image_urls],
                sessions=sessions,
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
        index = self.environment.get_template("index.md.jinja").render(
            targets=index_targets
        )
        (self.site_dir / "index.md").write_text(index)
        return self.site_dir
