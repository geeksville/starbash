"""Tests for the Targets page: stage/option editing, saving and unsaved prompts.

The interesting behaviour lives in :mod:`starbash.ui.qt.services` (merging recipe
parameter declarations with a target's overrides) and in the page's dirty-tracking
and navigation guard, so that is what these cover.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomlkit

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

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


@pytest.fixture
def master_repo(app_context, tmp_path) -> Path:
    """A registered 'master' repo, so recorded master paths resolve to a real dir.

    ``sessions.toml`` stores calibration masters relative to this repo (that is what
    ``Processing`` writes), so a hover preview/open needs it to exist.
    """
    repo_dir = tmp_path / "masters"
    repo_dir.mkdir()
    app_context.add_local_repo(str(repo_dir), repo_type="master")
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


def _stage_of(page: Any, name: str) -> Any:
    """Return ``page._stage(name)``, asserting the stage exists."""
    stage = page._stage(name)
    assert stage is not None
    return stage


def _param_of(page: Any, stage_name: str, param_name: str) -> Any:
    """Return ``page._param(stage_name, param_name)``, asserting it exists."""
    param = page._param(stage_name, param_name)
    assert param is not None
    return param


def _parent(widget: Any) -> Any:
    """Return a widget's parent, asserting it exists."""
    parent = widget.parentWidget()
    assert parent is not None
    return parent


def _layout(widget: Any) -> Any:
    """Return a widget's layout, asserting it exists."""
    layout = widget.layout()
    assert layout is not None
    return layout


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

    _stage_of(page, "crop").excluded = True
    page._mark_dirty()
    assert page._is_dirty() is True
    assert page._save_button.isVisible() is True

    page._undo()
    assert page._is_dirty() is False
    assert _stage_of(page, "crop").excluded is False
    assert page._save_button.isVisible() is False


def test_targets_page_save_writes_to_disk(qtbot, app_context, processed_repo):
    """Saving persists the change and clears the dirty state."""
    target_dir = _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    _stage_of(page, "crop").excluded = True
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
        _stage_of(page, "crop").excluded = True
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
    assert _stage_of(page, "crop").excluded is False

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
    _param_of(page, "crop", "crop_height").value = "4150"
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
    _param_of(page, "crop", "crop_width").value = None
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
    assert _param_of(page, "crop", "crop_height").is_overridden is False

    # Switching to "Edit override" adopts the default as the starting value.
    page._tabs.setCurrentIndex(1)
    parameter = _param_of(page, "crop", "crop_height")
    assert parameter.is_overridden is True
    assert parameter.value == "80%"
    assert page._stage_items["crop"].text(1) == "crop_width=85%, crop_height=80%"

    # ...and switching back drops it.
    page._tabs.setCurrentIndex(0)
    assert _param_of(page, "crop", "crop_height").is_overridden is False
    assert page._stage_items["crop"].text(1) == "crop_width=85%"

    # An already-overridden option opens straight on "Edit override".
    page._tree.setCurrentItem(page._param_items[("crop", "crop_width")])
    assert page._tabs.currentIndex() == 1


def test_option_editor_is_tall_enough_for_the_tab_pane(qtbot, app_context, processed_repo):
    """Regression: the option editor must not clip the tab pane's value box.

    The tree above soaks up all the slack, which previously squeezed the editor and
    cut off the bottom of the value box.
    """
    from starbash.ui.qt.pages.targets import _EDITOR_MIN_HEIGHT

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)

    page._tree.setCurrentItem(page._param_items[("crop", "crop_height")])
    qtbot.wait(20)

    # The editor keeps a floor big enough for its chrome + tab pane...
    assert page._editor.minimumHeight() >= _EDITOR_MIN_HEIGHT

    # ...and it is actually as tall as it wants to be.  Previously the tree above
    # squeezed it (height 172 vs a 188 size hint), which clipped the value box.
    assert page._editor.height() >= page._editor.sizeHint().height()
    assert page._tabs.height() >= page._tabs.sizeHint().height()


def test_editor_pane_is_hidden_until_a_row_is_selected(qtbot, app_context, processed_repo):
    """Nothing selected => no option-editor pane at all (not an inert one)."""
    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)
    qtbot.wait(20)

    # A freshly refreshed tree has no selection, so the pane stays hidden.
    assert page._tree.selectedItems() == []
    assert page._editor.isVisible() is False

    # Selecting a stage still shows the pane (it describes the stage)...
    page._tree.setCurrentItem(page._stage_items["crop"])
    qtbot.wait(20)
    assert page._editor.isVisible() is True
    assert page._param_desc.text().startswith("Crop and rotate")

    # ...and selecting a parameter fills in the editor.
    page._tree.setCurrentItem(page._param_items[("crop", "crop_height")])
    qtbot.wait(20)
    assert page._editor.isVisible() is True
    assert page._editing == ("crop", "crop_height")

    # Dropping the selection hides it again.
    page._tree.clearSelection()
    qtbot.wait(20)
    assert page._tree.selectedItems() == []
    assert page._editor.isVisible() is False


def test_columns_are_separated_by_a_horizontal_gap(qtbot, app_context, processed_repo):
    """Regression: the stages column must not touch the target list's scrollbar.

    The splitter handle alone is only a few pixels wide, so the right pane needs its
    own left margin or the stages tree / editor sit flush against the left table.
    """
    from PySide6.QtCore import QPoint

    from starbash.ui.qt.pages.targets import _COLUMN_GAP

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)
    qtbot.wait(20)

    assert _layout(page._right).contentsMargins().left() >= _COLUMN_GAP

    # ...and the gap is real on screen.  The layout margin insets this column's
    # *children*, so measure from the table's right edge to the tree's left edge.
    splitter = _parent(page._table)
    table_right = page._table.mapTo(splitter, QPoint(page._table.width(), 0)).x()
    tree_left = page._tree.mapTo(splitter, QPoint(0, 0)).x()
    assert tree_left - table_right >= _COLUMN_GAP


def test_target_list_is_a_narrow_picker(qtbot, app_context, processed_repo):
    """The target list is a narrow picker; the explorer takes the rest.

    Stretch factors alone don't set the initial proportion (they only divide extra
    space), so the page also calls ``setSizes``; without it the table took the
    larger share and crowded out the selected target's details.
    """
    from starbash.ui.qt.pages.targets import _TARGET_LIST_SHARE

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)

    splitter = _parent(page._table)

    def _share() -> float:
        return page._table.width() / max(1, splitter.width())

    # `setSizes` lands during the first layout pass, so wait for the splitter to
    # settle instead of racing a fixed sleep.
    qtbot.waitUntil(lambda: abs(_share() - _TARGET_LIST_SHARE) < 0.05, timeout=2000)

    total = splitter.width()
    assert total > 0

    # The splitter handle eats a few pixels, so allow a small tolerance.
    assert abs(_share() - _TARGET_LIST_SHARE) < 0.05
    # ...and the explorer column gets the lion's share of the page.
    assert page._right.width() > page._table.width()


def _indicator_size() -> int:
    """Pixel height of the checkbox indicator, read from the theme stylesheet.

    Read rather than hard-coded so the assertion below tracks the theme instead of
    duplicating a number that a later theme tweak would silently invalidate.
    """
    from starbash.ui.qt import theme

    match = re.search(r"QCheckBox::indicator[^{]*\{[^}]*height:\s*(\d+)px", theme.STYLESHEET)
    assert match is not None, "the theme no longer pins the checkbox indicator size"
    return int(match.group(1))


def _tree_row_min_height() -> int:
    """Minimum *content* height the theme pins on a tree row, from its stylesheet."""
    from starbash.ui.qt import theme

    match = re.search(r"QTreeView::item\s*\{[^}]*min-height:\s*(\d+)px", theme.STYLESHEET)
    assert match is not None, "the theme no longer floors the tree row height"
    return int(match.group(1))


def test_stage_rows_are_tall_enough_to_separate_their_checkboxes(
    qtbot, qapp, app_context, processed_repo
):
    """Regression: stage checkboxes used to touch - a row was only a font tall.

    The indicator is 16px, but an unpadded tree row inherited roughly the font
    height, so the boxes of consecutive stages abutted.  The fix is vertical padding
    on tree items; assert the *rendered* rows are taller than a box (i.e. the padding
    really took effect rather than merely being text in the stylesheet).
    """
    from starbash.ui.qt import theme

    theme.apply_theme(qapp)
    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)
    qtbot.wait(20)

    indicator = _indicator_size()
    crop = page._tree.visualItemRect(page._stage_items["crop"])
    denoise = page._tree.visualItemRect(page._stage_items["denoise"])

    # A row's natural height follows the *font* metrics, which differ per platform
    # (Windows' Segoe UI gives a shorter row than Linux's default), so the theme
    # also floors the row's content box at the indicator size.  Check that floor is
    # declared, then that it renders on top of the padding - a Linux-only run would
    # otherwise never notice the floor going missing.
    assert _tree_row_min_height() == indicator
    assert crop.height() >= indicator + 8
    # ...and tree rows are laid out back-to-back, so that daylight is all that
    # separates one stage's checkbox from the next one's.
    assert denoise.top() == crop.bottom() + 1


def test_path_label_has_its_own_padded_style(qtbot, app_context, processed_repo):
    """The target's output directory uses a padded style, not a plain subtitle."""
    from starbash.ui.qt import theme

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    assert page._path.objectName() == "PathLabel"
    assert "QLabel#PathLabel" in theme.STYLESHEET
    assert "padding: 6px 10px;" in theme.STYLESHEET


def test_target_rows_expose_recipe_and_folder_links(qtbot, app_context, processed_repo):
    """A Stage/option cell links to its recipe; the path label is a folder link."""
    from starbash.ui.qt.models import LINK_ROLE

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    # There is no separate recipe column; the Stage/option cell itself is the link.
    assert page._tree.columnCount() == 2

    crop = page._stage_items["crop"]
    # The default recipe repo supplies a source URL for each declared stage.
    assert crop.data(0, LINK_ROLE)
    assert crop.font(0).underline() is True
    # The stage description still owns the tooltip (the link doesn't clobber it).
    assert crop.toolTip(0) and crop.toolTip(0) != crop.data(0, LINK_ROLE)

    # An option row links to the same recipe as the stage that declares it.
    option = page._param_items[("crop", "crop_width")]
    assert option.data(0, LINK_ROLE) == crop.data(0, LINK_ROLE)

    # The output-directory label is a clickable anchor to the target's folder.
    text = page._path.text()
    assert "<a href=" in text
    assert "file://" in text


def test_target_link_opens_on_activate_not_on_click(
    qtbot, app_context, processed_repo, monkeypatch
):
    """A plain click selects; only activating the row opens the recipe."""
    from starbash.ui.qt.models import LINK_ROLE
    from starbash.ui.qt.widgets import file_links

    opened: list[str] = []
    monkeypatch.setattr(file_links, "open_link", lambda url: opened.append(url) or True)

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.refresh()

    crop = page._stage_items["crop"]
    index = page._tree.indexFromItem(crop, 0)

    # Clicking a stage row (even its checkbox) must only select it.
    page._tree.clicked.emit(index)
    assert opened == []

    # Activating it (double-click / Enter) opens the recipe.
    page._tree.activated.emit(index)
    assert opened == [crop.data(0, LINK_ROLE)]


# --- session master selection ---------------------------------------------

#: A sessions.toml in the new structured shape: one session, masters per type.
SESSIONS_TOML = """[[sessions]]
date = "2025-08-25"
start = "2025-08-25T04:23:18"
end = "2025-08-25T04:50:10"
filter = "None"
imagetyp = "Light"
object = "sh2126"
telescop = "OnStep"

[sessions.masters.bias]
selected = "cam/2025-09-03_04-33-21/bias/master_bias_gain100.fit"
selected_by = "auto"

[[sessions.masters.bias.candidates]]
path = "cam/2025-09-03_04-33-21/bias/master_bias_gain100.fit"
score = -169472.0
gain_match = true
temp_delta_c = 2.2
in_future = true
reasons = ["gain match", "time Δ=9.0d (in future!)"]

[[sessions.masters.bias.candidates]]
path = "cam/2025-09-06_06-05-55/bias/master_bias_gain100.fit"
score = -169500.0
gain_match = true
reasons = ["gain match"]

[sessions.masters.dark]
selected = "cam/2025-09-10_03-48-47/dark/master_dark_120s_gain100.fit"
selected_by = "auto"

[[sessions.masters.dark.candidates]]
path = "cam/2025-09-10_03-48-47/dark/master_dark_120s_gain100.fit"
score = -169490.0
reasons = ["gain match"]
"""


def _write_sessions(target_dir: Path, text: str = SESSIONS_TOML) -> Path:
    """Write a sessions.toml next to the target's main.toml."""
    path = target_dir / ".starbash" / "sessions.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _refresh_and_wait(page: Any, qtbot: Any, name: str = "sh2126") -> Any:
    """Show the page on ``name`` and wait for the async sessions load."""
    page.sb.selection.set_targets([name])
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)
    qtbot.waitUntil(lambda: page._pending_sessions_path is None, timeout=3000)
    return page


def test_sessions_group_lists_sessions_with_recorded_masters(qtbot, app_context, processed_repo):
    """A target whose sessions.toml records masters grows a Sessions group."""
    target_dir = _make_target(processed_repo)
    _write_sessions(target_dir)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    assert len(page._sessions_current) == 1
    session = page._sessions_current[0]
    assert session.label == "2025-08-25 · None · OnStep"
    assert [master.type for master in session.masters] == ["bias", "dark"]
    assert page._sessions_group is not None
    assert {master_type for (_key, master_type) in page._master_items} == {"bias", "dark"}
    labels: list[str] = []
    for index in range(page._tree.topLevelItemCount()):
        item = page._tree.topLevelItem(index)
        assert item is not None
        labels.append(item.text(0))
    # Sessions lead the explorer; see test_sessions_group_is_listed_above_stages.
    assert labels == ["Sessions", "Stages"]


def test_sessions_group_is_listed_above_the_stages_group(qtbot, app_context, processed_repo):
    """The Sessions group is rendered *above* Stages.

    Asserted on the rendered geometry, not just the tree's index order: the position
    the user sees is the point of the change (choosing a session's calibration master
    is the common edit, and the stage list is long).
    """
    target_dir = _make_target(processed_repo)
    _write_sessions(target_dir)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)
    qtbot.wait(20)

    assert page._sessions_group is not None
    assert page._stages_group is not None
    assert page._sessions_group.parent() is None  # a top-level group, not a stage
    assert page._tree.indexOfTopLevelItem(page._sessions_group) == 0

    sessions_top = page._tree.visualItemRect(page._sessions_group).top()
    stages_top = page._tree.visualItemRect(page._stages_group).top()
    assert sessions_top < stages_top


def test_picking_a_master_shows_the_picker_and_marks_dirty(qtbot, app_context, processed_repo):
    """Selecting a calibration row opens the picker; choosing a candidate dirties."""
    target_dir = _make_target(processed_repo)
    _write_sessions(target_dir)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    key, master_type = next(iter(page._master_items))
    page._tree.setCurrentItem(page._master_items[(key, master_type)])

    assert page._detail.isVisible() is True
    assert page._detail.currentWidget() is page._master_picker
    assert page._save_button.isVisible() is False

    other = "cam/2025-09-06_06-05-55/bias/master_bias_gain100.fit"
    page._on_master_selection_changed((key, master_type, other))

    assert page._save_button.isVisible() is True
    master = page._sessions_current[0].masters[0]
    assert master.selected == other
    assert master.selected_by == "user"


def test_saving_a_master_choice_writes_user_selection(qtbot, app_context, processed_repo):
    """Save records the pick with ``selected_by = "user"`` in sessions.toml."""
    target_dir = _make_target(processed_repo)
    sessions_path = _write_sessions(target_dir)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    key, master_type = next(iter(page._master_items))
    other = "cam/2025-09-06_06-05-55/bias/master_bias_gain100.fit"
    page._on_master_selection_changed((key, master_type, other))
    assert page._save() is True

    document: Any = tomlkit.parse(sessions_path.read_text(encoding="utf-8"))
    session = document["sessions"][0]
    bias = session["masters"]["bias"]
    assert str(bias["selected"]) == other
    assert str(bias["selected_by"]) == "user"
    # The rest of the session (and the sibling master) is preserved.
    assert session["date"] == "2025-08-25"
    assert "dark" in session["masters"]


def test_undo_restores_the_on_disk_master_choice(qtbot, app_context, processed_repo):
    """Undo reverts a master pick without touching sessions.toml."""
    target_dir = _make_target(processed_repo)
    sessions_path = _write_sessions(target_dir)
    before = sessions_path.read_text(encoding="utf-8")

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    key, master_type = next(iter(page._master_items))
    page._on_master_selection_changed(
        (key, master_type, "cam/2025-09-06_06-05-55/bias/master_bias_gain100.fit")
    )
    assert page._is_dirty() is True

    page._undo()

    assert page._is_dirty() is False
    assert page._sessions_current[0].masters[0].selected_by == "auto"
    assert sessions_path.read_text(encoding="utf-8") == before


def test_master_picker_is_exclusive_and_resettable(qapp):
    """The picker behaves as a radio list and can revert to the automatic pick.

    ``qapp`` is required rather than implied: the picker is a ``QWidget``, and Qt
    aborts (not raises) if one is constructed with no ``QApplication`` alive - which
    is exactly what happens when this test lands first on an xdist worker.
    """
    from starbash.ui.qt.services import MasterCandidate, SessionMasterOption
    from starbash.ui.qt.widgets.master_picker import MasterPicker

    option = SessionMasterOption(
        type="bias",
        selected="b",
        selected_by="user",
        candidates=[
            MasterCandidate(path="a", score=1.0, selected=False, reasons=[], details={}),
            MasterCandidate(path="b", score=2.0, selected=True, reasons=[], details={}),
        ],
    )
    picker = MasterPicker()
    changes: list[Any] = []
    picker.selectionChanged.connect(changes.append)
    picker.set_context("2025-08-25", ("k",), option)

    assert picker.selection() == (("k",), "bias", "b")
    assert picker._checked_path() == "b"

    # Choosing the other row makes it the only checked one.
    picker._on_cell_clicked(0, 0)
    assert picker._checked_path() == "a"
    assert changes[-1] == (("k",), "bias", "a")
    checked = []
    for row in range(len(picker._paths)):
        check_item = picker._table.item(row, 0)
        assert check_item is not None
        checked.append(check_item.checkState() == Qt.CheckState.Checked)
    assert checked == [True, False]

    # Reset goes back to the automatic pick recorded in the file.
    picker._on_reset()
    assert picker.selection() == (("k",), "bias", "b")


# --- master names as links (hover preview / open) --------------------------


def test_master_url_needs_a_master_repo_and_a_real_file(app_context, master_repo):
    """`master_url` resolves repo-relative masters, and only when they exist."""
    from starbash.ui.qt.services import master_url

    # Nothing to resolve: no path at all.
    assert master_url(app_context, None) is None
    assert master_url(app_context, "") is None
    # A recorded path with no frame behind it is deliberately not a link.
    assert master_url(app_context, "cam/x/bias/master_bias.fit") is None

    frame = master_repo / "cam/x/bias/master_bias.fit"
    frame.parent.mkdir(parents=True)
    frame.touch()

    url = master_url(app_context, "cam/x/bias/master_bias.fit")
    assert url is not None
    assert url.startswith("file://")
    assert url.endswith("cam/x/bias/master_bias.fit")


def test_master_url_is_none_without_a_master_repo(app_context, processed_repo):
    """With no master repo registered there is nothing to resolve against."""
    from starbash.ui.qt.services import master_url

    assert master_url(app_context, "cam/x/bias/master_bias.fit") is None


def _write_master_frame(master_repo: Path, relative: str) -> Path:
    """Create the (empty) file a recorded master path points at."""
    frame = master_repo / relative
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.touch()
    return frame


def test_master_names_link_to_their_frame(qtbot, app_context, processed_repo, master_repo):
    """The master name - in the tree and in the picker - previews/opens its frame.

    Stage and option rows have long linked to their recipe; this is the same idea for
    calibration masters, which is what makes the Sessions subpane worth hovering.
    """
    from starbash.ui.qt.models import LINK_ROLE
    from starbash.ui.qt.services import master_url

    target_dir = _make_target(processed_repo)
    _write_sessions(target_dir)
    selected = "cam/2025-09-03_04-33-21/bias/master_bias_gain100.fit"
    alternative = "cam/2025-09-06_06-05-55/bias/master_bias_gain100.fit"
    _write_master_frame(master_repo, selected)
    _write_master_frame(master_repo, alternative)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    key, master_type = next(iter(page._master_items))
    assert (key, master_type) == (page._sessions_current[0].key, "bias")
    row = page._master_items[(key, master_type)]

    # The *name* cell is the link; the calibration type is not a file.
    assert row.data(1, LINK_ROLE) == master_url(app_context, selected)
    assert row.font(1).underline() is True
    assert row.data(0, LINK_ROLE) is None

    # Selecting the row opens the picker, whose rows link to *their own* candidate.
    page._tree.setCurrentItem(row)
    assert page._detail.currentWidget() is page._master_picker
    names = [
        page._master_picker._table.item(index, 1)
        for index in range(page._master_picker._table.rowCount())
    ]
    assert [item.data(LINK_ROLE) for item in names if item is not None] == [
        master_url(app_context, selected),
        master_url(app_context, alternative),
    ]


def test_master_names_stay_plain_when_the_frame_is_missing(qtbot, app_context, processed_repo):
    """A master we cannot resolve to a real file is left as plain text.

    An underlined link that previews nothing and opens nothing would be a lie; the
    row's tooltip still shows the full recorded path.
    """
    from starbash.ui.qt.models import LINK_ROLE

    target_dir = _make_target(processed_repo)
    _write_sessions(target_dir)

    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    _refresh_and_wait(page, qtbot)

    row = page._master_items[next(iter(page._master_items))]
    assert row.data(1, LINK_ROLE) is None
    assert row.font(1).underline() is False
    assert row.toolTip(0)


# --- the target picker's single column ------------------------------------


def test_target_column_fills_the_picker_up_to_the_scrollbar(qtbot, app_context, processed_repo):
    """A one-column table stretches, so no bare strip sits before the scrollbar.

    ``make_table`` deliberately leaves the last section un-stretched (right for the
    multi-column tables, where a stretched column gave a bare number a huge empty
    cell), which left the 180px Target column stranded in a wider pane.
    """
    from starbash.ui.qt.models import TARGET_COLUMNS

    _make_target(processed_repo)
    app_context.selection.set_targets(["sh2126"])
    page = TargetsPage(app_context, None)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    page.refresh()
    qtbot.waitExposed(page)

    header = page._table.horizontalHeader()
    assert header.stretchLastSection() is True

    # Wait for the splitter/layout to settle, then check the column really filled the
    # viewport (which is the table minus any vertical scrollbar).
    qtbot.waitUntil(
        lambda: page._table.columnWidth(0) >= page._table.viewport().width() - 2, timeout=2000
    )
    assert page._table.columnWidth(0) > TARGET_COLUMNS[0].width
