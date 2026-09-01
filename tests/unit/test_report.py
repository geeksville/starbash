"""Tests for generated target report helpers."""

from jinja2 import Environment, PackageLoader

from starbash.report import image_scale_arcsec_per_pixel


def test_image_scale_uses_geometric_mean_for_non_square_pixels():
    """Calculate a scalar image scale from both pixel dimensions."""
    metadata = {"FOCALLEN": 500, "XPIXSZ": 3, "YPIXSZ": 4}

    assert image_scale_arcsec_per_pixel(metadata) == 206.265 * 12**0.5 / 500


def test_image_scale_is_unavailable_for_invalid_metadata():
    """Return no scale when required optical metadata is unusable."""
    assert image_scale_arcsec_per_pixel({"FOCALLEN": 500}) is None
    assert image_scale_arcsec_per_pixel({"FOCALLEN": 0, "XPIXSZ": 3.76}) is None
    assert image_scale_arcsec_per_pixel({"FOCALLEN": 500, "XPIXSZ": -1}) is None


def test_target_template_renders_available_session_optics():
    """Render focal length, focal ratio, and image scale in the session section."""
    environment = Environment(loader=PackageLoader("starbash", "templates/report"))
    template = environment.get_template("target.md.jinja")

    output = template.render(
        target={"name": "M42"},
        about={},
        images=[],
        sessions=[
            {
                "date": "2026-08-29",
                "metadata": {
                    "FOCALLEN": 384.0,
                    "FOCRATIO": 4.8,
                    "IMAGE_SCALE_ARCSEC_PER_PIXEL": 2.02,
                },
                "equipment_rows": [],
                "chart": "session-1.svg",
            }
        ],
    )

    assert "| Focal length | Focal ratio | Image scale |" in output
    assert "384.0 mm" in output
    assert "f/4.8" in output
    assert "2.02 arcsec/pixel" in output


def test_target_template_renders_workflow_link():
    """Render the published link to the complete processing workflow."""
    environment = Environment(loader=PackageLoader("starbash", "templates/report"))
    template = environment.get_template("target.md.jinja")

    output = template.render(
        target={"name": "M42"},
        about={},
        images=[],
        sessions=[],
        workflow_url="../../assets/targets/m42/main.toml",
    )

    assert "[View processing workflow](../../assets/targets/m42/main.toml)" in output


def test_target_template_renders_frontmatter_description_and_first_image():
    """Render SEO metadata from the page description and first page image."""
    environment = Environment(loader=PackageLoader("starbash", "templates/report"))
    template = environment.get_template("target.md.jinja")

    output = template.render(
        target={"name": "M42"},
        about={},
        description="A nebula image",
        image="../../assets/targets/m42/hero.jpg",
        images=["../../assets/targets/m42/hero.jpg", "../../assets/targets/m42/other.jpg"],
        sessions=[],
    )

    assert 'description: "A nebula image"' in output
    assert 'image: "../../assets/targets/m42/hero.jpg"' in output
