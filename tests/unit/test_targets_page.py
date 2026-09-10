"""Tests for the Targets page: stage/option editing, saving and unsaved prompts.

The interesting behaviour lives in :mod:`starbash.ui.qt.services` (merging recipe
parameter declarations with a target's overrides) and in the page's dirty-tracking
and navigation guard, so that is what these cover.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from starbash.ui.qt.pages.targets import TargetsPage, UnsavedChoice  # noqa: E402
from starbash.ui.qt.services import (  # noqa: E402
    TARGET_CONFIG_NAME,
    coerce_override,
    load_stage_options,
    save_stage_options,
)

pytestmark = pytest.mark.gui

#: A target config shaped exactly like the core scaffolds it: one overridden
#: parameter, one scaffolded-but-not-overridden, and one absent entirely.
TARGET_CONFIG = """[repo]
kind = "processed-target"

[[stages]]
name = "crop" # Crop and rotate stacked FITS outputs
[[stages.overrides]]
name = "crop_width" # Maximum crop width, in pixels or as a percentage of the source width
value = "85%"

[[stages.overrides]]
name = "crop_height" # Maximum crop height, in pixels or as a percentage of the source height
# value = "80%"

[[stages]]
name = "denoise" # Denoise the stacked result
"""


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context."""
    from starbash.app import Starbash

    with Starbash("test.targets") as sb:
        yield sb


@pytest.fixture
def processed_repo(app_context, tmp_path) -> Path:
    """A registered 'processed' output repo, so load_targets() finds targets."""
    repo_dir = tmp_path / "processed"
    repo_dir.mkdir()
    app_context.add_local_repo(str(repo_dir), repo_type="processed")
    return repo_dir


def _make_target(repo_dir: Path, name: str = "sh2126") -> Path:
    """Scaffold one processed target directory and return it."""
    target_dir = repo_dir / name
    config = target_dir / TARGET_CONFIG_NAME
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(TARGET_CONFIG, encoding="utf-8")
    return target_dir


def _stage(stages, name):
    return next(stage for stage in stages if stage.name == name)


def _param(stage, name):
    return next(parameter for parameter in stage.parameters if parameter.name == name)


# --- service layer ---------------------------------------------------------


def test_load_stage_options_merges_recipe_parameter_declarations(app_context, processed_repo):
    """Recipe-declared params are listed with their defaults, plus file overrides.

    This is the heart of the tree view: defaults and descriptions come from the
    recipe (``[[stages.parameters]]``), values come from the target file.
    """
    target_dir = _make_target(processed_repo)

    crop = _stage(load_stage_options(app_context, str(target_dir)), "crop")

    # Declared by the recipe, overridden in the file.
    width = _param(crop, "crop_width")
    assert width.default == "80%"  # recipe default
    assert width.value == "85%"  # file override
    assert width.is_overridden
    assert "Maximum crop width" in (width.description or "")

    # Scaffolded but not overridden -> default applies.
    height = _param(crop, "crop_height")
    assert height.default == "80%"
    assert height.value is None
    assert not height.is_overridden
    assert "Maximum crop height" in (height.description or "")

    # Not present in the file at all -> still surfaced from the recipe.
    rotate = _param(crop, "rotate_deg")
    assert rotate.default == 0  # int default is preserved, not stringified
    assert rotate.value is None
    assert "Rotation angle" in (rotate.description or "")


def test_save_stage_options_round_trips_and_is_idempotent(app_context, processed_repo):
    """Writing twice produces byte-identical files and preserves every edit."""
    target_dir = _make_target(processed_repo)

    stages = load_stage_options(app_context, str(target_dir))
    crop = _stage(stages, "crop")
    crop.excluded = True
    _param(crop, "rotate_deg").value = 15
    save_stage_options(str(target_dir), stages)

    config = target_dir / TARGET_CONFIG_NAME
    first_write = config.read_text(encoding="utf-8")

    reloaded = load_stage_options(app_context, str(target_dir))
    reloaded_crop = _stage(reloaded, "crop")
    assert reloaded_crop.excluded is True
    assert _param(reloaded_crop, "rotate_deg").value == 15
    assert _param(reloaded_crop, "crop_width").value == "85%"

    # Not-overridden defaults stay visible to hand-editors as a commented line.
    assert '# value = "80%"' in first_write

    save_stage_options(str(target_dir), reloaded)
    assert config.read_text(encoding="utf-8") == first_write


def test_save_stage_options_preserves_other_document_sections(app_context, processed_repo):
    """Only [[stages]] is rewritten; the rest of the file is untouched."""
    target_dir = _make_target(processed_repo)
    config = target_dir / TARGET_CONFIG_NAME
    config.write_text(
        TARGET_CONFIG + '\n[processing.citation]\ntitle = "My image"\n', encoding="utf-8"
    )

    save_stage_options(str(target_dir), load_stage_options(app_context, str(target_dir)))

    assert 'title = "My image"' in config.read_text(encoding="utf-8")


def test_coerce_override_keeps_the_declared_type():
    """Typed text adopts the parameter's declared type; junk falls back to text."""
    assert coerce_override("15", 0) == 15
    assert isinstance(coerce_override("15", 0), int)
    assert coerce_override("0.3", 0.5) == 0.3
    assert coerce_override("85%", "80%") == "85%"
    assert coerce_override("true", False) is True
    assert coerce_override("off", True) is False
    # Unparseable input must not raise; it stays a string.
    assert coerce_override("nonsense", 3) == "nonsense"


# --- page behaviour --------------------------------------------------------


def test_targets_page_selects_the_current_selection_target(qtbot, app_context, processed_repo):
    """`sb select target X` pre-selects that target's row."""
    _make_target(processed_repo, "sh2126")
    _make_target(processed_repo, "m31")
    app_context.selection.set_targets(["sh2126"])

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    assert page._loaded_target == "sh2126"
    assert page._table.selectionModel().selectedRows()[0].row() == page._find_row("sh2126")


def test_targets_page_has_no_selection_when_none_is_configured(qtbot, app_context, processed_repo):
    """With no selection (or no match) the page simply loads nothing."""
    _make_target(processed_repo, "m31")

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    assert page._loaded_target is None
    assert page._tree.topLevelItemCount() == 0


def test_targets_page_save_button_only_appears_when_dirty(qtbot, app_context, processed_repo):
    """Save/Undo stay hidden until something actually changes, and Undo reverts."""
    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.show()
    page.refresh()

    assert page._save_button.isVisible() is False
    assert page._undo_button.isVisible() is False

    page._stage("crop").excluded = True
    page._mark_dirty()
    assert page._is_dirty() is True
    assert page._save_button.isVisible() is True

    page._undo()
    assert page._is_dirty() is False
    assert page._stage("crop").excluded is False
    assert page._save_button.isVisible() is False


def test_targets_page_save_writes_to_disk(qtbot, app_context, processed_repo):
    """Saving persists the change and clears the dirty state."""
    target_dir = _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    page._stage("crop").excluded = True
    page._mark_dirty()
    assert page._save() is True
    assert page._is_dirty() is False

    reloaded = load_stage_options(app_context, str(target_dir))
    assert _stage(reloaded, "crop").excluded is True


def test_targets_page_asks_before_leaving_when_dirty(
    qtbot, app_context, processed_repo, monkeypatch
):
    """Cancel keeps edits, Discard drops them, Save writes them."""
    target_dir = _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    def dirty() -> None:
        page._stage("crop").excluded = True
        page._mark_dirty()

    # Cancel: stay put, edits intact.
    dirty()
    monkeypatch.setattr(page, "_ask_unsaved", lambda: UnsavedChoice.CANCEL)
    assert page.can_leave() is False
    assert page._is_dirty() is True

    # Discard: revert and allow leaving.
    monkeypatch.setattr(page, "_ask_unsaved", lambda: UnsavedChoice.DISCARD)
    assert page.can_leave() is True
    assert page._is_dirty() is False
    assert page._stage("crop").excluded is False

    # Save: persist and allow leaving.
    dirty()
    monkeypatch.setattr(page, "_ask_unsaved", lambda: UnsavedChoice.SAVE)
    assert page.can_leave() is True
    assert page._is_dirty() is False
    assert _stage(load_stage_options(app_context, str(target_dir)), "crop").excluded is True


def test_targets_page_does_not_ask_when_clean(qtbot, app_context, processed_repo, monkeypatch):
    """A clean page leaves immediately, without prompting."""

    def fail() -> UnsavedChoice:  # pragma: no cover - only runs on regression
        raise AssertionError("should not prompt with no unsaved edits")

    _make_target(processed_repo)
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()
    monkeypatch.setattr(page, "_ask_unsaved", fail)

    assert page.can_leave() is True


def test_navigation_is_blocked_when_a_page_refuses_to_leave(qtbot, app_context, monkeypatch):
    """The window honours can_leave(): a refused navigation leaves the page put."""
    from starbash.ui.qt.main_window import MainWindow

    window = MainWindow(app_context)
    qtbot.addWidget(window)
    targets_index = next(
        index for index, page in enumerate(window.pages()) if isinstance(page, TargetsPage)
    )
    window.show_page(targets_index)
    targets = window.current_page()
    assert isinstance(targets, TargetsPage)

    monkeypatch.setattr(targets, "can_leave", lambda: False)
    window.show_page(0)

    assert window.current_page() is targets
    assert window._nav.currentRow() == targets_index


def test_stage_summary_shows_overridden_values_not_counts(qtbot, app_context, processed_repo):
    """The summary line lists what was overridden - not how many options exist."""
    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    # Only crop_width is overridden; the summary shows its value, not "3 options".
    assert page._stage_items["crop"].text(1) == "crop_width=85%"
    # A stage with nothing overridden has an empty summary.
    assert page._stage_items["denoise"].text(1) == ""

    # Editing a value updates the summary live.
    page._param("crop", "crop_height").value = "4150"
    page._refresh_param_row("crop", "crop_height")
    assert page._stage_items["crop"].text(1) == "crop_width=85%, crop_height=4150"


def test_overridden_values_are_bright_and_defaults_dim(qtbot, app_context, processed_repo):
    """Overrides are highlighted in the tree; recipe defaults are muted."""
    from starbash.ui.qt.pages.targets import _DEFAULT_COLOR, _OVERRIDE_COLOR

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    overridden = page._param_items[("crop", "crop_width")]
    default = page._param_items[("crop", "crop_height")]
    assert overridden.foreground(1).color() == _OVERRIDE_COLOR
    assert default.foreground(1).color() == _DEFAULT_COLOR
    assert _OVERRIDE_COLOR != _DEFAULT_COLOR

    # Clearing the override re-mutes the row.
    page._param("crop", "crop_width").value = None
    page._refresh_param_row("crop", "crop_width")
    assert overridden.foreground(1).color() == _DEFAULT_COLOR


def test_editor_uses_use_default_and_edit_override_tabs(qtbot, app_context, processed_repo):
    """The editor is two tabs; switching them sets/clears the override."""
    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()
    page.show()

    # A not-overridden option opens on "Use default".
    page._tree.setCurrentItem(page._param_items[("crop", "crop_height")])
    assert page._tabs.currentIndex() == 0
    assert page._tabs.tabText(0) == "Use default"
    assert page._tabs.tabText(1) == "Edit override"
    assert page._param("crop", "crop_height").is_overridden is False

    # Switching to "Edit override" adopts the default as the starting value.
    page._tabs.setCurrentIndex(1)
    parameter = page._param("crop", "crop_height")
    assert parameter.is_overridden is True
    assert parameter.value == "80%"
    assert page._stage_items["crop"].text(1) == "crop_width=85%, crop_height=80%"

    # ...and switching back drops it.
    page._tabs.setCurrentIndex(0)
    assert page._param("crop", "crop_height").is_overridden is False
    assert page._stage_items["crop"].text(1) == "crop_width=85%"

    # An already-overridden option opens straight on "Edit override".
    page._tree.setCurrentItem(page._param_items[("crop", "crop_width")])
    assert page._tabs.currentIndex() == 1
