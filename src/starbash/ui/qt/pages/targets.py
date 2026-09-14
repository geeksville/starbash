"""Review processed targets: pick stages, tune options, and choose calibration masters.

The page is a narrow target list on the left and a **target explorer** on the
right.  The explorer is a tree of two groups:

``Sessions``
    One row per session that recorded calibration masters (from the prior run's
    ``sessions.toml``), with a child row per calibration type (``Bias``/``Dark``/
    ``Flat``).  Listed **first**, because choosing the calibration master is what
    this screen is most often used for.

``Stages``
    Each top-level row is a stage (ticked = active) and its children are the
    parameters the recipe declares.

Selecting a parameter reveals the option editor below the tree; selecting a
calibration type reveals a :class:`~starbash.ui.qt.widgets.master_picker.MasterPicker`
instead.  With nothing selected the detail pane is hidden entirely.

Edits live in memory and are only written by **Save options**; **Undo changes**
discards them.  Leaving the page (or picking another target) with unsaved edits
prompts the user via :meth:`TargetsPage.can_leave`.  A user-picked master is saved
with ``selected_by = "user"``, which processing honours on the next run — see
``doc/plans/session-masters.md``.

Master names are links (as are stage/option names): hovering one previews the file
and activating the row opens it — see
:mod:`starbash.ui.qt.widgets.hover_preview`.
"""

from __future__ import annotations

import copy
from enum import StrEnum
from functools import partial
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starbash.aliases import normalize_target_name
from starbash.ui.qt.models import TARGET_COLUMNS, DictTableModel
from starbash.ui.qt.pages.base import Page
from starbash.ui.qt.services import (
    ParameterOption,
    SessionMasterOption,
    SessionOption,
    StageOption,
    coerce_override,
    load_session_options,
    load_stage_options,
    load_targets,
    master_url,
    preferred_target,
    save_master_selections,
    save_stage_options,
)
from starbash.ui.qt.theme import ACCENT
from starbash.ui.qt.widgets.busy_indicator import BusyIndicator
from starbash.ui.qt.widgets.file_links import LinkDecorator, open_with_status, set_link
from starbash.ui.qt.widgets.master_picker import MasterPicker
from starbash.ui.qt.workers import run_async
from starbash.url import make_file_url

__all__ = ["TargetsPage", "UnsavedChoice"]

#: Colour for a value the user has overridden (stands out against the theme).
_OVERRIDE_COLOR = QColor("#ffd75f")
#: Colour for a value the recipe supplies (deliberately muted, so overrides pop).
_DEFAULT_COLOR = QColor("#7f8c9b")
#: Smallest height that fits the option editor's title, description and tab pane.
_EDITOR_MIN_HEIGHT = 200
#: Horizontal gap between the target list and the target explorer, so the right
#: pane does not sit flush against the left table's scrollbar (the splitter handle
#: alone is only a few pixels wide).
_COLUMN_GAP = 12
#: Default share of the page width given to the target list.  It is a narrow
#: picker now: the selected target's details take the rest of the page.
_TARGET_LIST_SHARE = 0.22
#: Labels of the two top-level tree groups in the target explorer.
_STAGES_GROUP_LABEL = "Stages"
_SESSIONS_GROUP_LABEL = "Sessions"
#: Smallest height that lets the master picker show its title, hint and a few rows.
_MASTER_PICKER_MIN_HEIGHT = 220


def _load_session_options_job(_report: Any, _token: Any, *, path: str) -> list[SessionOption]:
    """Worker adapter: :func:`run_async` calls jobs as ``job(report, token)``."""
    return load_session_options(path)


class UnsavedChoice(StrEnum):
    """What the user decided when asked about unsaved option edits."""

    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


class TargetsPage(Page):
    """Pick a processed target, tick its stages and override their options."""

    nav_title = "Targets"
    subtitle = "Review processed targets, choose which stages run, and tune their options."

    def _build(self) -> None:
        #: Stages exactly as loaded from disk (the baseline for "dirty" and Undo).
        self._original: list[StageOption] = []
        #: Stages as currently edited in the UI.
        self._current: list[StageOption] = []
        self._stage_items: dict[str, QTreeWidgetItem] = {}
        self._param_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._editing: tuple[str, str] | None = None
        #: Per-session master selections, as loaded from disk and as currently edited.
        self._sessions_original: list[SessionOption] = []
        self._sessions_current: list[SessionOption] = []
        self._session_items: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._master_items: dict[tuple[tuple[str, ...], str], QTreeWidgetItem] = {}
        #: The top-level ``Stages``/``Sessions`` group items (rebuilt per target).
        self._stages_group: QTreeWidgetItem | None = None
        self._sessions_group: QTreeWidgetItem | None = None
        #: Path whose ``sessions.toml`` is being parsed off-thread (None when idle).
        self._pending_sessions_path: str | None = None
        #: Target whose options are loaded, and its on-disk directory.
        self._loaded_target: str | None = None
        self._loaded_path: str | None = None
        #: Target to select on the next refresh (keeps the row selected after a save).
        self._desired_target: str | None = None
        #: Suppresses selection/editor handlers while we mutate widgets ourselves.
        self._guard = False

        layout = QVBoxLayout(self)
        layout.addLayout(self.heading())

        self._model = DictTableModel(TARGET_COLUMNS)
        self._table = self.make_table(self._model)
        # A one-column picker should fill its pane: make_table deliberately leaves
        # the last section un-stretched (right for the multi-column tables, where
        # stretching gave a bare number a huge empty column), which here left the
        # 180px Target column stranded in a wider pane - a bare strip of table with
        # a scrollbar at its far edge.
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.selectionModel().selectionChanged.connect(self._on_target_selected)

        right = QWidget()
        self._right = right
        right_layout = QVBoxLayout(right)
        # The left margin separates this column from the target list's vertical
        # scrollbar; the bottom margin keeps the path box off the pane edge.
        right_layout.setContentsMargins(_COLUMN_GAP, 0, 0, 8)

        hint = QLabel(
            "Sessions — pick which calibration master each session uses. "
            "Stages — ticked = active. Expand to edit options."
        )
        hint.setObjectName("PageSubtitle")
        # Wrap so a long hint can't dictate a wide minimum for this column (which
        # would push the splitter off the target list's narrow default).
        hint.setWordWrap(True)
        right_layout.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Target / stage / session", "Value"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setColumnWidth(0, 240)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        right_layout.addWidget(self._tree, 1)

        #: A stage/session cell previews its recipe on hover and opens it when the
        #: row is *activated* (double-click / Enter) - a plain click still selects,
        #: so it never fights the stage checkbox or the detail pane.
        self._links = LinkDecorator(
            self._tree, parent=self, on_status=self.status.emit, open_on="activated"
        )

        #: The detail pane swaps between the stage-option editor and the master
        #: picker; it hides entirely when neither applies.
        self._detail = QStackedWidget()
        self._detail.addWidget(self._build_editor())

        self._master_picker = MasterPicker()
        self._master_picker.setMinimumHeight(_MASTER_PICKER_MIN_HEIGHT)
        self._master_picker.selectionChanged.connect(self._on_master_selection_changed)
        self._detail.addWidget(self._master_picker)

        right_layout.addWidget(self._detail)

        #: Overlays the tree while a large ``sessions.toml`` is parsed off-thread.
        self._busy = BusyIndicator(self._tree, "Reading sessions…")

        # Nothing is selected yet: keep the detail pane out of the way until there
        # is something to edit (see _clear_editor / _show_master_picker).
        self._detail.setVisible(False)

        self._save_button = QPushButton("Save options")
        self._save_button.setObjectName("Primary")
        self._save_button.clicked.connect(self._on_save_clicked)
        self._undo_button = QPushButton("Undo changes")
        self._undo_button.clicked.connect(self._on_undo_clicked)

        buttons = QHBoxLayout()
        buttons.addWidget(self._save_button)
        buttons.addWidget(self._undo_button)
        buttons.addStretch(1)
        right_layout.addLayout(buttons)

        self._path = QLabel("")
        self._path.setObjectName("PathLabel")
        self._path.setWordWrap(True)
        # A long output path must never dictate the explorer column's minimum width:
        # otherwise the splitter is pushed off its narrow default (and the target
        # list's share shrinks).  Ignored lets the label wrap into whatever width
        # the layout has, however long the path is.
        self._path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._path.setTextFormat(Qt.TextFormat.RichText)
        self._path.setOpenExternalLinks(False)
        self._path.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._path.linkActivated.connect(self._on_path_link)
        right_layout.addWidget(self._path)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._table)
        splitter.addWidget(right)
        # Stretch factors only govern how *extra* space is divided once the panes
        # have their initial sizes, so the default proportion is set explicitly:
        # the target list is a narrow picker, the explorer takes the rest (and all
        # of any extra width when the window grows).
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes(
            [
                int(_TARGET_LIST_SHARE * 1000),
                int((1.0 - _TARGET_LIST_SHARE) * 1000),
            ]
        )
        layout.addWidget(splitter, 1)

        self._mark_dirty()

    def _build_editor(self) -> QGroupBox:
        """Build the per-parameter editor shown below the tree."""
        self._editor = QGroupBox("Option")
        self._editor.setObjectName("OptionEditor")
        # The tree above soaks up all the slack, so this editor must never be
        # squeezed below what its tabs and value box need - otherwise the tab pane
        # clips its content.  A Minimum height policy lets it grow with a wrapping
        # description; the explicit floor is the smallest layout that fits.
        self._editor.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._editor.setMinimumHeight(_EDITOR_MIN_HEIGHT)
        editor_layout = QVBoxLayout(self._editor)

        self._param_title = QLabel("Select an option to edit it.")
        self._param_desc = QLabel("")
        self._param_desc.setObjectName("PageSubtitle")
        self._param_desc.setWordWrap(True)

        # "Use default" vs "Edit override" as two tabs, so the state is explicit
        # and there is no separate checkbox to reason about.
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_override_tab_changed)

        default_tab = QWidget()
        default_layout = QVBoxLayout(default_tab)
        self._default_label = QLabel("")
        self._default_label.setObjectName("PageSubtitle")
        self._default_label.setWordWrap(True)
        default_layout.addWidget(self._default_label)

        override_tab = QWidget()
        override_layout = QVBoxLayout(override_tab)
        self._override_value = QLineEdit()
        self._override_value.textEdited.connect(self._on_value_edited)
        override_layout.addWidget(self._override_value)

        self._tabs.addTab(default_tab, "Use default")
        self._tabs.addTab(override_tab, "Edit override")

        editor_layout.addWidget(self._param_title)
        editor_layout.addWidget(self._param_desc)
        editor_layout.addWidget(self._tabs)

        self._editor.setEnabled(False)
        return self._editor

    # --- tree -----------------------------------------------------------------
    def _rebuild_tree(self) -> None:
        """Rebuild the whole explorer from the working models."""
        self._links.dismiss()
        self._guard = True
        try:
            self._tree.clear()
            self._stage_items.clear()
            self._param_items.clear()
            self._session_items.clear()
            self._master_items.clear()
            self._editing = None
            self._stages_group = None
            self._sessions_group = None

            # Sessions lead the explorer: choosing each session's calibration master
            # is what this screen is most often opened for, and its rows are much
            # shorter than the stage list below it.
            self._build_sessions_group()

            if self._current:
                group = QTreeWidgetItem([_STAGES_GROUP_LABEL, ""])
                group.setFirstColumnSpanned(True)
                self._tree.addTopLevelItem(group)
                self._stages_group = group

            for stage in self._current:
                item = QTreeWidgetItem([stage.name, self._stage_value_text(stage)])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Unchecked if stage.excluded else Qt.CheckState.Checked
                )
                # The stage cell links to the recipe that declares the stage:
                # hovering previews it, activating opens it.  Set the link first so
                # the stage's description keeps the tooltip slot.
                set_link(item, 0, stage.recipe_url)
                if stage.description:
                    item.setToolTip(0, stage.description)
                self._add_stage_item(item)
                self._stage_items[stage.name] = item

                for parameter in stage.parameters:
                    child = QTreeWidgetItem([parameter.name, self._value_text(parameter)])
                    # An option is declared by the same recipe as its stage.
                    set_link(child, 0, stage.recipe_url)
                    if parameter.description:
                        child.setToolTip(0, parameter.description)
                        child.setToolTip(1, parameter.description)
                    item.addChild(child)
                    self._param_items[(stage.name, parameter.name)] = child
                    self._apply_param_style(stage.name, parameter.name)

            if self._stages_group is not None:
                self._stages_group.setExpanded(True)
        finally:
            self._guard = False

        self._clear_editor()

    def _add_stage_item(self, item: QTreeWidgetItem) -> None:
        """Attach a stage row under the Stages group (or at top level if absent)."""
        if self._stages_group is not None:
            self._stages_group.addChild(item)
        else:
            self._tree.addTopLevelItem(item)

    def _build_sessions_group(self) -> None:
        """Add the Sessions group — only when sessions recorded master choices.

        Listed above the Stages group (the caller builds it first): the master choice
        is the more common edit, and the group's rows are short.
        """
        if not self._sessions_current:
            return
        group = QTreeWidgetItem([_SESSIONS_GROUP_LABEL, ""])
        group.setFirstColumnSpanned(True)
        self._tree.addTopLevelItem(group)
        self._sessions_group = group

        for option in self._sessions_current:
            session_item = QTreeWidgetItem([option.label, ""])
            session_item.setFirstColumnSpanned(True)
            session_item.setToolTip(0, f"Session {option.label}")
            group.addChild(session_item)
            self._session_items[option.key] = session_item

            for master in option.masters:
                master_item = QTreeWidgetItem(
                    [master.type.title(), self._master_selection_text(master)]
                )
                # The value cell holds the master's file name, so that is the cell
                # that previews on hover and opens on activate.  The type cell stays
                # plain text - it names a calibration type, not a file.
                set_link(master_item, 1, master_url(self.sb, master.selected))
                master_item.setToolTip(0, self._master_selection_tooltip(master))
                session_item.addChild(master_item)
                self._master_items[(option.key, master.type)] = master_item

        group.setExpanded(True)

    @staticmethod
    def _master_selection_text(master: SessionMasterOption) -> str:
        """Row text for a calibration type: the chosen master's name + who chose it."""
        if not master.selected:
            return "(no master selected)"
        return f"{Path(master.selected).name}  ({master.selected_by})"

    @staticmethod
    def _master_selection_tooltip(master: SessionMasterOption) -> str:
        """Tooltip for a calibration row: the full path plus the alternatives count."""
        lines = [master.selected or "(no master selected)"]
        lines.append(f"Chosen by: {master.selected_by}")
        lines.append(f"{len(master.candidates)} candidate(s) considered")
        return "\n".join(lines)

    def _apply_param_style(self, stage_name: str, param_name: str) -> None:
        """Colour a parameter row: overrides stand out, defaults stay muted."""
        parameter = self._param(stage_name, param_name)
        item = self._param_items.get((stage_name, param_name))
        if parameter is None or item is None:
            return
        colour = _OVERRIDE_COLOR if parameter.is_overridden else _DEFAULT_COLOR
        item.setForeground(1, QBrush(colour))

    @staticmethod
    def _value_text(parameter: ParameterOption) -> str:
        """Row text for a parameter: the override value, or the recipe default."""
        if parameter.is_overridden:
            return f"{parameter.value}"
        if parameter.default is None:
            return "(no default)"
        return f"{parameter.default}  (default)"

    @staticmethod
    def _stage_value_text(stage: StageOption) -> str:
        """Row text for a stage: the values of any overridden options.

        Deliberately *not* a count of options - that told the user nothing useful.
        Showing ``crop_width=85%, crop_height=4150`` lets them see what they changed
        without expanding the stage.
        """
        overridden = [
            f"{parameter.name}={parameter.value}"
            for parameter in stage.parameters
            if parameter.is_overridden
        ]
        return ", ".join(overridden)

    def _stage(self, name: str) -> StageOption | None:
        """Return the working stage with ``name``, if present."""
        return next((stage for stage in self._current if stage.name == name), None)

    def _param(self, stage_name: str, param_name: str) -> ParameterOption | None:
        """Return the working parameter ``param_name`` of stage ``stage_name``."""
        stage = self._stage(stage_name)
        if stage is None:
            return None
        return next((param for param in stage.parameters if param.name == param_name), None)

    def _refresh_param_row(self, stage_name: str, param_name: str) -> None:
        """Re-render one parameter row (and its stage summary) after an edit."""
        parameter = self._param(stage_name, param_name)
        item = self._param_items.get((stage_name, param_name))
        if parameter is None or item is None:
            return
        self._guard = True
        try:
            item.setText(1, self._value_text(parameter))
        finally:
            self._guard = False
        self._apply_param_style(stage_name, param_name)
        self._refresh_stage_row(stage_name)

    def _refresh_stage_row(self, stage_name: str) -> None:
        """Re-render a stage row's option summary."""
        stage = self._stage(stage_name)
        item = self._stage_items.get(stage_name)
        if stage is None or item is None:
            return
        self._guard = True
        try:
            item.setText(1, self._stage_value_text(stage))
        finally:
            self._guard = False

    # --- editing --------------------------------------------------------------
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """A stage checkbox was toggled (parameter rows are not checkable)."""
        if self._guard or column != 0:
            return
        stage = self._stage(item.text(0))
        if stage is None:
            return
        stage.excluded = item.checkState(0) == Qt.CheckState.Unchecked
        self._mark_dirty()

    def _on_tree_selection_changed(self) -> None:
        """Show the option editor or master picker for the selected row, if any."""
        if self._guard:
            return
        items = self._tree.selectedItems()
        if not items:
            self._clear_editor()
            return

        item = items[0]
        if item is self._stages_group or item is self._sessions_group:
            # A group header carries no detail of its own.
            self._clear_editor()
            return

        parent = item.parent()
        if parent is self._stages_group:
            # A stage row: show its description rather than an editor.
            stage = self._stage(item.text(0))
            self._clear_editor()
            self._param_title.setText(item.text(0))
            self._param_desc.setText(
                (stage.description if stage else None) or "Expand to see this stage's options."
            )
            self._show_editor()
            self._sync_editor_height()
            return

        master = self._master_for_item(item)
        if master is not None:
            option, chosen = master
            self._show_master_picker(option, chosen)
            return

        if parent is not None:
            # A parameter row: its parent is a stage item.
            self._load_editor(parent.text(0), item.text(0))
            return

        self._clear_editor()

    def _master_for_item(
        self, item: QTreeWidgetItem
    ) -> tuple[SessionOption, SessionMasterOption] | None:
        """Return the ``(session, master)`` a tree item represents, if it is a master row."""
        for (key, master_type), candidate_item in self._master_items.items():
            if candidate_item is not item:
                continue
            option = next((o for o in self._sessions_current if o.key == key), None)
            master = (
                next((m for m in option.masters if m.type == master_type), None)
                if option is not None
                else None
            )
            if option is not None and master is not None:
                return option, master
        return None

    def _show_editor(self) -> None:
        """Show the stage-option editor in the detail pane."""
        self._detail.setCurrentWidget(self._editor)
        self._detail.setVisible(True)

    def _show_master_picker(self, option: SessionOption, master: SessionMasterOption) -> None:
        """Show the master picker for one session + calibration type."""
        self._editing = None
        self._master_picker.set_context(
            option.label,
            option.key,
            master,
            # Candidate paths are relative to the master repo; resolving them here
            # makes each row previewable (hover) and openable (activate) rather
            # than a dead name.
            resolve_url=partial(master_url, self.sb),
        )
        self._detail.setCurrentWidget(self._master_picker)
        self._detail.setVisible(True)

    def _hide_detail(self) -> None:
        """Hide the detail pane entirely (nothing selected to edit)."""
        self._detail.setVisible(False)

    def _on_master_selection_changed(self, selection: object) -> None:
        """Apply a picker choice to the working model and mark the page dirty."""
        if self._guard:
            return
        key, master_type, path = selection  # type: ignore[misc]
        if path is None:
            return
        option = next((o for o in self._sessions_current if o.key == key), None)
        master = (
            next((m for m in option.masters if m.type == master_type), None)
            if option is not None
            else None
        )
        if master is None:
            return
        if master.selected == path and master.selected_by == "user":
            return
        master.selected = path
        master.selected_by = "user"
        for candidate in master.candidates:
            candidate.selected = candidate.path == path
        self._refresh_master_row(key, master_type)
        self._mark_dirty()

    def _refresh_master_row(self, key: tuple[str, ...], master_type: str) -> None:
        """Re-render a calibration row after its selection changed."""
        item = self._master_items.get((key, master_type))
        option = next((o for o in self._sessions_current if o.key == key), None)
        master = (
            next((m for m in option.masters if m.type == master_type), None)
            if option is not None
            else None
        )
        if item is None or master is None:
            return
        self._guard = True
        try:
            item.setText(1, self._master_selection_text(master))
        finally:
            self._guard = False

    def _load_editor(self, stage_name: str, param_name: str) -> None:
        """Populate the editor for one parameter."""
        parameter = self._param(stage_name, param_name)
        if parameter is None:
            self._clear_editor()
            return

        self._editing = (stage_name, param_name)
        self._guard = True
        try:
            self._editor.setEnabled(True)
            self._param_title.setText(parameter.name)
            self._param_desc.setText(
                parameter.description or "This recipe gives no description for this option."
            )
            self._default_label.setText(self._default_text(parameter))
            self._override_value.setText(self._editor_value_text(parameter))
            self._override_value.setPlaceholderText(self._default_text(parameter))
            self._tabs.setCurrentIndex(1 if parameter.is_overridden else 0)
            # A long description wraps and grows the editor; make sure the taller
            # layout is allowed rather than clipped.
            self._sync_editor_height()
            self._show_editor()
        finally:
            self._guard = False

    def _sync_editor_height(self) -> None:
        """Floor the editor's height so a wrapping description cannot clip the tabs."""
        self._editor.setMinimumHeight(max(_EDITOR_MIN_HEIGHT, self._editor.sizeHint().height()))

    def _clear_editor(self) -> None:
        """Return the editor to its empty state and hide it (nothing to edit)."""
        self._editing = None
        self._guard = True
        try:
            self._editor.setEnabled(False)
            self._param_title.setText("Select an option to edit it.")
            self._param_desc.setText("")
            self._tabs.setCurrentIndex(0)
            self._override_value.clear()
            self._override_value.setPlaceholderText("")
            self._default_label.setText("")
            # No option (or no valid row) selected: hide the whole pane rather than
            # showing an inert editor taking up half the page.
            self._hide_detail()
        finally:
            self._guard = False

    @staticmethod
    def _default_text(parameter: ParameterOption) -> str:
        """Human text for the parameter's recipe default."""
        if parameter.default is None:
            return "Recipe default: (none)"
        return f"Recipe default: {parameter.default}"

    @staticmethod
    def _editor_value_text(parameter: ParameterOption) -> str:
        """Text to preload the value box with: the override, else the default."""
        if parameter.is_overridden:
            return str(parameter.value)
        return "" if parameter.default is None else str(parameter.default)

    def _on_override_tab_changed(self, index: int) -> None:
        """Switching to 'Use default' drops the override; 'Edit override' sets one."""
        if self._guard or self._editing is None:
            return
        stage_name, param_name = self._editing
        parameter = self._param(stage_name, param_name)
        if parameter is None:
            return

        if index == 0:
            parameter.value = None
        else:
            # Adopt the text (the default, unless the user already typed something).
            parameter.value = coerce_override(self._override_value.text(), parameter.default)

        self._refresh_param_row(stage_name, param_name)
        self._mark_dirty()

    def _on_value_edited(self, text: str) -> None:
        """Apply a typed value (only meaningful on the 'Edit override' tab)."""
        if self._guard or self._editing is None:
            return
        stage_name, param_name = self._editing
        parameter = self._param(stage_name, param_name)
        if parameter is None or not parameter.is_overridden:
            return

        parameter.value = coerce_override(text, parameter.default)
        self._refresh_param_row(stage_name, param_name)
        self._mark_dirty()

    # --- dirty state, save and undo -------------------------------------------
    def _is_dirty(self) -> bool:
        """True when the working model (stages or master choices) differs from disk."""
        return self._current != self._original or self._sessions_current != self._sessions_original

    def _mark_dirty(self) -> None:
        """Show Save/Undo only when there is something to save or discard."""
        dirty = self._is_dirty()
        self._save_button.setVisible(dirty)
        self._undo_button.setVisible(dirty)

    def _on_save_clicked(self) -> None:
        self._save()

    def _on_undo_clicked(self) -> None:
        self._undo()

    def _pending_master_edits(self) -> list[tuple[tuple[str, ...], str, str]]:
        """The user-selected masters that differ from what is on disk."""
        edits: list[tuple[tuple[str, ...], str, str]] = []
        for option in self._sessions_current:
            original = next((o for o in self._sessions_original if o.key == option.key), None)
            for master in option.masters:
                if master.selected is None:
                    continue
                prior = (
                    next((m for m in original.masters if m.type == master.type), None)
                    if original is not None
                    else None
                )
                if (
                    prior is None
                    or prior.selected != master.selected
                    or prior.selected_by != master.selected_by
                ):
                    edits.append((option.key, master.type, master.selected))
        return edits

    def _save(self) -> bool:
        """Write the working model to disk. Returns True on success."""
        if self._loaded_target is None or self._loaded_path is None:
            return True
        try:
            save_stage_options(self._loaded_path, self._current)
        except Exception as exc:  # noqa: BLE001 - report, never crash the page
            self.show_error(f"Could not save options for {self._loaded_target}: {exc}")
            return False

        # Only rewrite the (large) sessions.toml when a master choice actually
        # changed; stage-only edits never touch it.
        if self._sessions_current != self._sessions_original:
            edits = self._pending_master_edits()
            if edits:
                try:
                    save_master_selections(self._loaded_path, edits)
                except Exception as exc:  # noqa: BLE001 - report, never crash the page
                    self.show_error(
                        f"Could not save master choices for {self._loaded_target}: {exc}"
                    )
                    return False

        self._original = copy.deepcopy(self._current)
        self._sessions_original = copy.deepcopy(self._sessions_current)
        self._mark_dirty()
        self.status.emit(f"Saved options for {self._loaded_target}.")
        return True

    def _undo(self) -> None:
        """Discard in-memory edits and restore what is on disk."""
        self._current = copy.deepcopy(self._original)
        self._sessions_current = copy.deepcopy(self._sessions_original)
        self._rebuild_tree()
        self._mark_dirty()
        self.status.emit("Discarded option changes.")

    # --- unsaved-change prompts ----------------------------------------------
    def can_leave(self) -> bool:
        """Ask about unsaved edits before navigating away; False cancels it."""
        return self._resolve_unsaved()

    def _resolve_unsaved(self) -> bool:
        """True if it is OK to proceed (nothing dirty, or the user saved/discarded)."""
        if not self._is_dirty():
            return True
        choice = self._ask_unsaved()
        if choice is UnsavedChoice.SAVE:
            return self._save()
        if choice is UnsavedChoice.DISCARD:
            self._undo()
            return True
        return False

    def _ask_unsaved(self) -> UnsavedChoice:
        """Show the save/discard/cancel dialog. Split out so tests can drive it."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved options")
        box.setText(f"You have unsaved option changes for {self._loaded_target or 'this target'}.")
        box.setInformativeText("Save them before continuing?")
        save_button = box.addButton("Save options", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked is save_button:
            return UnsavedChoice.SAVE
        if clicked is discard_button:
            return UnsavedChoice.DISCARD
        return UnsavedChoice.CANCEL

    # --- target selection -----------------------------------------------------
    def refresh(self) -> None:
        """Reload the target list, selecting the current or preferred target."""
        self._model.set_rows(load_targets(self.sb))
        wanted = self._desired_target or preferred_target(self.sb)
        self._desired_target = None
        self._select_target(wanted)

    def _select_target(self, name: str | None) -> None:
        """Select the row for ``name`` (normalised), or clear the selection."""
        index = self._find_row(name)
        self._guard = True
        try:
            if index is None:
                self._table.clearSelection()
            else:
                self._table.selectRow(index)
                self._table.scrollTo(self._model.index(index, 0))
        finally:
            self._guard = False

        self._load_target(self._model.row_at(index) if index is not None else None)

    def _find_row(self, name: str | None) -> int | None:
        """Row index of the target matching ``name`` (ignoring case and separators)."""
        if not name:
            return None
        wanted = normalize_target_name(str(name))
        for index, row in enumerate(self._model.rows()):
            if normalize_target_name(str(row.get("target", ""))) == wanted:
                return index
        return None

    def _on_target_selected(self) -> None:
        """Load the selected target, resolving any unsaved edits first."""
        if self._guard:
            return
        indexes = self._table.selectionModel().selectedRows()
        row = self._model.row_at(indexes[0].row()) if indexes else None
        if row is None:
            self._load_target(None)
            return
        if row.get("target") == self._loaded_target:
            return
        if not self._resolve_unsaved():
            # The user cancelled: put the selection back where it was.
            self._select_target(self._loaded_target)
            return
        self._load_target(row)

    def _load_target(self, row: dict[str, Any] | None) -> None:
        """Load stage options and session masters for ``row`` (or clear when None)."""
        if row is None:
            self._loaded_target = None
            self._loaded_path = None
            self._original = []
            self._current = []
            self._sessions_original = []
            self._sessions_current = []
            self._pending_sessions_path = None
            self._busy.stop()
            self._rebuild_tree()
            self._mark_dirty()
            self._path.setText("")
            return

        target = str(row.get("target", ""))
        path = str(row.get("path", ""))
        try:
            stages = load_stage_options(self.sb, path)
        except Exception as exc:  # noqa: BLE001 - report, never crash the page
            self.show_error(f"Could not read options for {target}: {exc}")
            return

        self._loaded_target = target
        self._loaded_path = path
        self._original = stages
        self._current = copy.deepcopy(stages)
        # Master choices arrive asynchronously (sessions.toml can be large); show
        # the stages immediately and add the Sessions group when they land.
        self._sessions_original = []
        self._sessions_current = []
        self._rebuild_tree()
        self._mark_dirty()
        self._path.setText(self._path_link(path))
        self.status.emit(f"{len(stages)} stage(s) for {target}.")
        self._request_sessions(path)

    def _request_sessions(self, path: str) -> None:
        """Parse a target's per-session master choices off the GUI thread."""
        self._pending_sessions_path = path
        self._busy.start()
        run_async(
            partial(_load_session_options_job, path=path),
            on_finished=partial(self._on_sessions_loaded, path),
            on_failed=partial(self._on_sessions_failed, path),
        )

    def _on_sessions_loaded(self, path: str, options: list[SessionOption]) -> None:
        """Apply freshly parsed session masters, dropping a stale result."""
        if path != self._loaded_path:
            return
        self._pending_sessions_path = None
        self._busy.stop()
        self._sessions_original = options
        self._sessions_current = copy.deepcopy(options)
        self._rebuild_tree()
        self._mark_dirty()
        if options:
            sessions = len(options)
            self.status.emit(f"{sessions} session(s) with recorded calibration for this target.")

    def _on_sessions_failed(self, path: str, message: str) -> None:
        """A failed sessions read must not break the stage editor; just report it."""
        if path != self._loaded_path:
            return
        self._pending_sessions_path = None
        self._busy.stop()
        self.status.emit(f"Could not read session master choices: {message}")

    @staticmethod
    def _path_link(path: str) -> str:
        """Rich text for a target's output directory, as a clickable link."""
        url = make_file_url(Path(str(path)))
        return (
            f'<a href="{escape(url)}" style="color:{ACCENT}; '
            f'text-decoration:none;">{escape(str(path))}</a>'
        )

    def _on_path_link(self, url: str) -> None:
        """Open the target's output directory with the file manager."""
        open_with_status(url, self.status.emit)
