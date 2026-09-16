"""The first-run / re-run setup **wizard** (a ``QWizard``, not a dialog).

This is the GUI equivalent of ``sb user setup``: it writes the same user config
keys, so the two front ends stay interchangeable.  It is a wizard rather than a
form because the questions have an order and a purpose — *who are you* → *where
should output go* → *where are your images* → *can we actually run* — and because
the last page is a checklist the user can act on.

Design notes (see ``doc/plans/gui-setup-wizard.md``):

* Pages are addressed by the :class:`Page` enum, and the two dynamic edges live in
  one :meth:`SetupWizard.nextId` rather than being copied into every page.
* :class:`SetupPage` is the shared base: ``refresh()`` re-reads the world and is
  called on *every* visit (via ``currentIdChanged``), because ``IndependentPages``
  means ``initializePage()`` only ever runs once — and ``validatePage()`` commits
  this page's answers, so a half-finished wizard still leaves a usable config.
* Each page saves as it is left, so cancelling is safe and the wizard can be
  re-run at any time from *File ▸ Run setup wizard…*.
* :func:`setup_checklist` is the single definition of "set up": the last page
  draws it and :func:`is_wizard_complete` - the test the GUI asks before opening
  the wizard at start-up - folds it into one bool, so the two cannot disagree.
* Only a **required** tool (Siril) can hold the wizard open; everything else on
  the closing checklist gates the two action buttons, not *Finish*.
"""

from __future__ import annotations

import logging
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)
from toml_repo import Repo

from starbash.analytics import analytics_enabled, analytics_include_user
from starbash.app import Starbash
from starbash.paths import get_user_documents_dir
from starbash.tool import tool_statuses, tools
from starbash.tool.base import ToolSeverity, ToolStatus
from starbash.ui.qt.theme import wizard_logo_pixmap, wizard_watermark_pixmap

logger = logging.getLogger(__name__)

__all__ = [
    "ACTION_PROCESS",
    "ACTION_TARGETS",
    "Page",
    "SetupWizard",
    "is_wizard_complete",
    "run_setup_dialog",
    "setup_checklist",
]

#: Returned by :func:`run_setup_dialog` when the user chose *Process all my targets*.
ACTION_PROCESS = "process"
#: Returned by :func:`run_setup_dialog` when the user chose *Pick a target*.
ACTION_TARGETS = "targets"
#: Suffixes we accept as a raw image (so a folder of JPEGs reads as "no images").
_FITS_SUFFIXES = (".fit", ".fits")

#: Repo kinds that are *not* the user's raw images: the two output kinds, the
#: preference repo, and the recipe checkouts Starbash installs for itself.
_NON_IMAGE_REPO_KINDS = frozenset({"master", "processed", "recipe", "std-recipe", "preferences"})


class Page(IntEnum):
    """The wizard's page ids, in the order they are normally visited."""

    WELCOME = 1
    YOU = 2
    FOLDERS = 3
    IMAGES = 4
    TOOLS = 5
    DONE = 6


def _output_folders_base() -> Path:
    """Where the default ``master``/``processed`` repos live."""
    return get_user_documents_dir() / "repos"


def _has_fits_images(path: Path) -> bool:
    """True when ``path`` directly contains at least one FITS file."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    return any(entry.is_file() and entry.suffix.lower() in _FITS_SUFFIXES for entry in entries)


def _required_tools_missing() -> list[ToolStatus]:
    """The missing tools Starbash cannot work without (Siril, in practice)."""
    return [
        status
        for status in tool_statuses()
        if not status.available and status.severity >= ToolSeverity.REQUIRED
    ]


def _repo_path(repo: Repo) -> Path | None:
    """The local directory behind ``repo``, or ``None`` for a non-file repo.

    A repo may be a remote URL or a package resource, so this reports a path only
    when there really is one on disk - the raw-image check reads real files.
    """
    path = repo.get_path()
    return path if isinstance(path, Path) else None


def _raw_image_repos(sb: Starbash) -> list[Repo]:
    """The user's raw-image repositories.

    A raw-image repo is one added without a type (see ``ADD_KINDS`` in the
    Repositories page): it gets no ``[repo] kind`` of its own, so its kind reads
    back as ``"unknown"``.  Everything else is *not* the user's images, and the
    list has to be explicit because ``regular_repos`` only hides a plain
    ``"recipe"`` - the default recipes published on GitHub carry ``"std-recipe"``
    and would otherwise be reported as one of the user's image folders.
    """
    return [
        repo for repo in sb.repo_manager.regular_repos if repo.kind() not in _NON_IMAGE_REPO_KINDS
    ]


def setup_checklist(sb: Starbash) -> list[tuple[str, bool, str]]:
    """Every setup minimum, as ``(title, complete, what to do about it)``.

    This is the wizard's definition of "set up", and deliberately the **only**
    one: the closing page draws this list, and :func:`is_wizard_complete` - the
    test the GUI asks at start-up - folds the same list into a single bool.  Two
    lists would drift, and the user would then be shown a tick beside a wizard
    that reopens every morning.

    Each row mirrors the page that asks for it, so the list cannot demand
    something a page let through: the raw-image row wants a *folder*, exactly as
    :meth:`ImagesPage.isComplete` does, and not FITS files inside it - plenty of
    people keep their lights a level down (``raw/M31/lights``), and demanding
    FITS here would re-ask them at every start.
    """
    repo = sb.user_repo
    has_name = bool(str(repo.get("user.name", "") or "").strip())

    manager = sb.repo_manager
    has_folders = (
        manager.get_repo_by_kind("master") is not None
        and manager.get_repo_by_kind("processed") is not None
    )

    return [
        ("Your details", has_name, "Enter your name on the About you page"),
        (
            "Output folders",
            has_folders,
            "Create your output folders on the Output folders page",
        ),
        (
            "Your raw images",
            bool(_raw_image_repos(sb)),
            "Add the folder with your raw images first",
        ),
        (
            "Tools",
            not _required_tools_missing(),
            "Install the missing tool, then press Re-check",
        ),
    ]


def is_wizard_complete(sb: Starbash) -> bool:
    """True when every setup minimum in :func:`setup_checklist` is met.

    The GUI asks this at start-up instead of "is there a username?" (see
    ``doc/plans/gui-setup-wizard.md`` §5.4): the name is only the first of the
    wizard's four requirements, so a user who has one but no output folders - or
    no image folder, or no Siril - has not finished setting Starbash up and gets
    the wizard again rather than a window that cannot do anything.
    """
    return all(complete for _title, complete, _hint in setup_checklist(sb))


def _centre_pane_mark(wizard: QWizard) -> None:
    """Centre Qt's watermark mark in the wizard's left pane.

    ModernStyle paints ``WatermarkPixmap`` at the **top-left** of a label that runs
    the full height of the page body, which parked our telescope in the upper third
    of the pane instead of its middle.

    Qt owns that label and builds it in ``showEvent`` — after our constructor has
    returned — so it is found by the pixmap we handed Qt (``QPixmap.cacheKey``
    identifies the *contents*, and the label's copy of the watermark shares ours)
    and only its alignment is changed.  An ``AlignCenter`` label keeps the mark
    centred by itself as the window is resized or restyled.  A Qt that painted the
    watermark some other way leaves this a no-op.
    """
    watermark = wizard.pixmap(QWizard.WizardPixmap.WatermarkPixmap)
    if watermark.isNull():
        return
    for label in wizard.findChildren(QLabel):
        mark = label.pixmap()
        if mark.isNull() or mark.cacheKey() != watermark.cacheKey():
            continue
        if label.alignment() != Qt.AlignmentFlag.AlignCenter:
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)


class SetupPage(QWizardPage):
    """Base class for the wizard's pages.

    Pages that show live state (the tool rows, the closing checklist) override
    :meth:`refresh`, which the wizard calls on every visit — not just the first,
    which is all ``IndependentPages`` gives us.
    """

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sb = sb

    def refresh(self) -> None:
        """Re-read anything this page displays.  Called on every visit."""

    def initializePage(self) -> None:  # noqa: N802 - Qt API
        """Qt's first-visit hook; the default is simply to refresh."""
        super().initializePage()
        self.refresh()


class WelcomePage(SetupPage):
    """Page 1: what Starbash does, and the promise that nothing is destructive."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("Welcome to Starbash")
        self.setSubTitle("Starbash turns your raw astronomy frames into finished pictures.")

        # The telescope in the left pane is Qt's watermark label, which Qt centres
        # for us in SetupWizard.showEvent - see _centre_pane_mark.

        layout = QVBoxLayout(self)
        for text in (
            "Thank you for trying Starbash.  This project is young but with your feedback "
            "we hope it will improve workflow sharing/collaboration.",
            "This wizard will guide you through the initial setup.",
            "You can re-run this wizard at any time from <b>File ▸ Run setup wizard…</b>.",
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)


class YouPage(SetupPage):
    """Page 2: who to credit.  The name is required — it is the first-run test."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("About you")
        self.setSubTitle("Starbash credits this name in the images it produces.")

        repo = sb.user_repo
        self._name = QLineEdit(str(repo.get("user.name", "") or ""))
        # objectName is the gui-integration script's handle (doc/plans/gui-integration-video.md
        # §6). These four are named, never restyled - the theme styles by type here.
        self._name.setObjectName("wizardName")
        self._email = QLineEdit(str(repo.get("user.email", "") or ""))
        self._email.setObjectName("wizardEmail")
        self._analytics = QCheckBox("Send anonymous crash reports and usage data (please!)")
        self._analytics.setObjectName("wizardAnalytics")
        self._analytics.setChecked(analytics_enabled(repo))
        self._include_email = QCheckBox(
            "Include my email with crash reports (so we can contact you)"
        )
        self._include_email.setObjectName("wizardIncludeEmail")
        self._include_email.setChecked(analytics_include_user(repo))

        # The *include email* option only means something once an email is typed.
        self._email.textChanged.connect(self._on_email_changed)
        self._on_email_changed(self._email.text())

        form = QFormLayout(self)
        form.addRow("Name", self._name)
        form.addRow("Email (optional)", self._email)
        form.addRow("", self._analytics)
        form.addRow("", self._include_email)

        # Completeness is computed from the widget's own text rather than a
        # mandatory (`user.name*`) field: Qt defines a filled field as "different
        # from the value it had in initializePage()", which would leave *Next*
        # disabled for the already-configured user on a re-run.
        self._name.textChanged.connect(self._on_name_changed)
        self.registerField("user.name", self._name)
        self.registerField("user.email", self._email)

    def _on_name_changed(self, _text: str) -> None:
        """*Next* follows the name's non-emptiness (see :meth:`isComplete`)."""
        self.completeChanged.emit()

    def _on_email_changed(self, text: str) -> None:
        """Only offer *include my email* when there is an email to include."""
        has_email = bool(text.strip())
        self._include_email.setEnabled(has_email)
        if not has_email:
            self._include_email.setChecked(False)

    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        """A username is required; without one the setup is unfinished."""
        return bool(self._name.text().strip())

    def validatePage(self) -> bool:  # noqa: N802 - Qt API
        """Save the answers now, so a later Cancel still leaves a usable config."""
        name = self._name.text().strip()
        if not name:
            return False
        repo = self.sb.user_repo
        repo.set("user.name", name)
        repo.set("user.email", self._email.text().strip())
        repo.set("analytics.enabled", self._analytics.isChecked())
        repo.set("analytics.include_user", self._include_email.isChecked())
        repo.write_config()
        return True


class FoldersPage(SetupPage):
    """Page 3: create the default output folders, or report that they exist."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("Output folders")
        self.setSubTitle(
            "Where Starbash writes your master calibration frames and finished images."
        )

        layout = QVBoxLayout(self)
        base = _output_folders_base()
        #: Whether the output folders are still missing; see :meth:`refresh`.
        self._missing = True
        #: Where a *custom* answer creates them (``None`` until one is picked).
        self._custom_base: Path | None = None

        # There is no "skip this page" answer: Starbash has nowhere to write without
        # these folders, so the choice is the default place or one the user names.
        # Creating the default stays pre-selected, which keeps the one-click path -
        # read nothing, press Next - working exactly as before.
        self._default_radio = QRadioButton(f"Create the default output folders under {base}")
        self._default_radio.setChecked(self._missing_output_repos())
        layout.addWidget(self._default_radio)

        self._custom_radio = QRadioButton("Create them under a folder I choose instead")
        layout.addWidget(self._custom_radio)

        self._custom_row = QWidget()
        row = QHBoxLayout(self._custom_row)
        row.setContentsMargins(24, 0, 0, 0)
        self._custom_path = QLabel()
        self._custom_path.setWordWrap(True)
        row.addWidget(self._custom_path, 1)
        self._choose = QPushButton("Choose folder…")
        self._choose.clicked.connect(self._on_choose)
        row.addWidget(self._choose)
        layout.addWidget(self._custom_row)

        self._paths = QLabel()
        self._paths.setWordWrap(True)
        layout.addWidget(self._paths)

        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        layout.addStretch(1)

        # Connected after the initial state is set, so building the page does not
        # fire a refresh (and a completeChanged) at a half-built widget.
        self._default_radio.toggled.connect(self._on_choice_changed)

        self.refresh()

    def _on_choice_changed(self, _checked: bool) -> None:
        """Re-describe the answer, and let Qt re-evaluate *Next* (see isComplete)."""
        self.refresh()
        self.completeChanged.emit()

    def _on_choose(self) -> None:
        """Ask for the folder to create ``master``/``processed`` under."""
        start = self._custom_base if self._custom_base is not None else get_user_documents_dir()
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where to create your output folders", str(start)
        )
        if not folder:
            return
        # Picking a folder *is* choosing the custom answer, so tick it for them.
        self._custom_base = Path(folder)
        self._custom_radio.setChecked(True)
        self.refresh()
        self.completeChanged.emit()

    def _missing_output_repos(self) -> bool:
        """True when a master or processed output repo has not been created yet."""
        manager = self.sb.repo_manager
        return (
            manager.get_repo_by_kind("master") is None
            or manager.get_repo_by_kind("processed") is None
        )

    def _existing_paths(self) -> dict[str, str]:
        """The configured output repos, by kind (empty when not set up yet)."""
        manager = self.sb.repo_manager
        found: dict[str, str] = {}
        for kind in ("master", "processed"):
            repo = manager.get_repo_by_kind(kind)
            if repo is not None:
                found[kind] = str(_repo_path(repo) or repo.url)
        return found

    def refresh(self) -> None:
        """Report the folders that exist, or the paths the current answer creates.

        Called on every visit *and* whenever the answer changes, so the caption
        always describes what the current answer will do.
        """
        existing = self._existing_paths()
        # Asked of the world, not of the widget: while the wizard's window is not
        # shown yet, isVisible() would tell validatePage() there is nothing to do.
        missing = self._missing_output_repos()
        self._missing = missing

        # Do not fight the user: once the folders exist there is nothing left to
        # create, so the question disappears rather than sitting there answered.
        self._default_radio.setVisible(missing)
        self._custom_radio.setVisible(missing)

        if not missing:
            listed = "\n".join(f"    • {kind}: {path}" for kind, path in existing.items())
            self._paths.setText(f"You already have these:\n{listed}")
            self._custom_row.setVisible(False)
            self._note.setVisible(False)
            return

        # Read from the radio, not from the widget's visibility: this runs while the
        # wizard is still hidden in tests (and for a frame during a page change).
        custom = self._custom_radio.isChecked()
        chosen = self._custom_base if custom else None
        self._custom_row.setVisible(custom)
        self._custom_path.setText(str(chosen) if chosen is not None else "No folder picked yet")

        if custom and chosen is None:
            # The one answer this page refuses: no folder is no answer at all.
            self._paths.setText("")
            self._note.setText(
                "Press “Choose folder…” — Starbash needs somewhere to write your "
                "masters and finished images before it can go on."
            )
            self._note.setVisible(True)
            return

        base = chosen if chosen is not None else _output_folders_base()
        listed = "\n".join(f"    • {base / kind}" for kind in ("master", "processed"))
        self._paths.setText(f"Will create:\n{listed}")
        self._note.setVisible(False)

    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        """This page cannot be skipped: answer it, one way or the other.

        Creating the default folders is the pre-selected answer, so a user who
        reads nothing and presses *Next* still gets a working setup; the custom
        radio only counts once a folder has actually been picked.
        """
        if not self._missing:
            return True
        if self._default_radio.isChecked():
            return True
        return self._custom_radio.isChecked() and self._custom_base is not None

    def validatePage(self) -> bool:  # noqa: N802 - Qt API
        """Create the output repos the answer calls for.

        Refuses only "somewhere else" with no folder picked, because there is
        nothing to create.  A folder that cannot be created is logged and skipped
        rather than raising: the wizard must stay usable (the checklist on the last
        page reports what is still missing), and the same creation is available
        from the Repositories page.
        """
        if not self._missing:
            return True

        custom = self._custom_radio.isChecked()
        chosen = self._custom_base if custom else None
        if custom and chosen is None:
            # Hold the wizard here and say why on the page itself.
            self.refresh()
            return False
        base = chosen if chosen is not None else _output_folders_base()

        manager = self.sb.repo_manager
        for kind in ("master", "processed"):
            if manager.get_repo_by_kind(kind) is not None:
                continue
            try:
                self.sb.add_local_repo(str(base / kind), repo_type=kind)
            except Exception as exc:  # noqa: BLE001 - a failed folder must not trap the wizard
                logger.warning(f"Could not create the {kind} output folder: {exc}")
        return True


class ImagesPage(SetupPage):
    """Page 4: point Starbash at the folder holding the raw frames."""

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("Your images")
        self.setSubTitle("The folder (or folders) holding your raw astronomy frames.")
        #: A folder picked on this visit, added when the page is left.
        self._chosen: Path | None = None

        layout = QVBoxLayout(self)
        self._list = QLabel()
        self._list.setWordWrap(True)
        layout.addWidget(self._list)

        bar = QHBoxLayout()
        self._choose = QPushButton("Choose folder…")
        self._choose.setObjectName("Primary")
        self._choose.clicked.connect(self._on_choose)
        bar.addWidget(self._choose)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        hint = QLabel(
            "Starbash only reads these from these folders — nothing is ever written back into "
            "them.  It will automatically discover sessions, targets, flats, biases, etc... "
            "You can add more folders later from the Repositories page."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        self.refresh()

    @property
    def choose_button(self) -> QPushButton:
        """The *Choose folder…* button — the movie script's handle for it.

        It cannot carry an ``objectName`` of its own: it is ``#Primary`` (the theme's
        accent style) and a widget has only one ``objectName``.  A public accessor is
        the workaround the plan settled on — see ``doc/plans/gui-integration-video.md``
        §6.
        """
        return self._choose

    def _known_paths(self) -> set[str]:
        """The filesystem paths of the raw-image repos we already know about."""
        known: set[str] = set()
        for repo in _raw_image_repos(self.sb):
            path = _repo_path(repo)
            if path is not None:
                known.add(str(path))
        return known

    def _on_choose(self) -> None:
        """Ask for a folder and report what we found in it straight away."""
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder with your raw images", str(Path.home())
        )
        if not folder:
            return

        self._chosen = Path(folder)
        if _has_fits_images(self._chosen):
            self._status.setText(f"Found FITS images in {self._chosen}.")
        else:
            self._status.setText(
                f"No FITS images (.fit/.fits) directly inside {self._chosen} — you can "
                "still add it, but check you picked the folder with your raw frames."
            )
        self.refresh()
        # Picking a folder is what makes this page complete (see isComplete).
        self.completeChanged.emit()

    def refresh(self) -> None:
        """List the raw-image folders and whether each really holds FITS files."""
        repos = _raw_image_repos(self.sb)
        lines: list[str] = []
        for repo in repos:
            path = _repo_path(repo)
            location = str(path) if path is not None else repo.url
            if path is not None and not _has_fits_images(path):
                lines.append(f"    ○ {location}  (no FITS files found here yet)")
            else:
                lines.append(f"    ✓ {location}")
        if self._chosen is not None and str(self._chosen) not in self._known_paths():
            lines.append(f"    + {self._chosen}  (will be added when you continue)")

        if lines:
            self._list.setText("Your image folders:\n" + "\n".join(lines))
        else:
            self._list.setText(
                "No source image folders yet.  Choose the folder that holds your raw "
                "frames — Starbash has nothing to process without it."
            )

    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        """A folder has to be here: Starbash cannot process anything without one.

        The requirement is the *folder*, not FITS files inside it —
        :func:`_has_fits_images` only looks directly inside a folder, and plenty of
        people keep their lights a level down (``raw/M31/lights``), so demanding
        FITS here would trap the very people this page is for.
        """
        return bool(_raw_image_repos(self.sb)) or self._chosen is not None

    def validatePage(self) -> bool:  # noqa: N802 - Qt API
        """Add the folder the user picked, then require at least one folder.

        A folder that cannot be added is reported in the page's status line and
        does **not** count as an answer: the wizard stays on this page so the next
        press of *Next* retries, rather than walking on with nothing to show for
        the chosen folder.
        """
        chosen = self._chosen
        if chosen is not None and str(chosen) in self._known_paths():
            self._chosen = None
            self._status.setText(f"{chosen} is already one of your image folders.")
        elif chosen is not None:
            try:
                # No repo_type: a folder added without a type is a raw-image repo.
                self.sb.add_local_repo(str(chosen))
            except Exception as exc:  # noqa: BLE001 - report, never raise from a page
                logger.warning(f"Could not add the image folder {chosen}: {exc}")
                self._status.setText(f"Could not add {chosen}: {exc}")
            else:
                self._chosen = None
                self._status.setText(f"Added {chosen}.")

        if _raw_image_repos(self.sb):
            return True

        self.refresh()
        if chosen is None:
            self._status.setText(
                "Starbash needs at least one folder with your raw frames.  Press "
                "“Choose folder…” to point at it."
            )
        return False


class ToolsPage(SetupPage):
    """Page 5: the external programs Starbash drives, and a Siril gate.

    A missing **required** tool disables *Next*/Finish (Qt drives both from
    :meth:`isComplete`), which is the documented way to express "do not let the
    user past this" — and :meth:`validatePage` re-checks as well, so the
    [Return]/auto-advance path cannot slip through either.
    """

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("Tools")
        self.setSubTitle("Starbash drives a few external programs to do its work.")

        layout = QVBoxLayout(self)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rows_host)

        self._empty = QLabel("Everything Starbash needs is installed.")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)

        self.refresh()

    # --- probing ----------------------------------------------------------
    @staticmethod
    def _recheck_required() -> list[ToolStatus]:
        """Re-probe the required tools, then report which are still missing.

        ``is_available`` caches its first answer, so a user who installs Siril
        while this page is open would otherwise keep seeing "missing" forever.
        """
        for tool in tools.values():
            if tool.status().severity >= ToolSeverity.REQUIRED:
                tool.invalidate_availability()
        return _required_tools_missing()

    def _on_recheck(self) -> None:
        """*Re-check* for one tool: forget the cached probe and repaint."""
        missing = self._recheck_required()
        self.refresh()
        if missing:
            self._status.setText(f"Still not found: {', '.join(t.name for t in missing)}")
        else:
            self._status.setText("Everything found — you can continue.")

    def _on_install(self, url: str) -> None:
        """Open a tool's install page in the user's browser."""
        QDesktopServices.openUrl(QUrl(url))

    # --- rendering --------------------------------------------------------
    def _clear_rows(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _add_row(self, status: ToolStatus) -> None:
        """One tool: its state, how important it is, and how to fix it."""
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)

        mark = "✓" if status.available else "○"
        label = QLabel(f"{mark}  <b>{status.name}</b> — {status.severity.label}")
        label.setWordWrap(True)
        line.addWidget(label, 1)

        if not status.available:
            if status.install_url:
                install = QPushButton("Install…")
                url = status.install_url
                install.clicked.connect(lambda _checked=False, u=url: self._on_install(u))
                line.addWidget(install)
            recheck = QPushButton("Re-check")
            recheck.clicked.connect(lambda _checked=False: self._on_recheck())
            line.addWidget(recheck)

        self._rows.addWidget(row)

        if not status.available and status.summary:
            note = QLabel(f"      {status.summary}")
            note.setWordWrap(True)
            self._rows.addWidget(note)

    def refresh(self) -> None:
        """Rebuild the tool rows from a fresh look at the system."""
        self._clear_rows()
        statuses = tool_statuses()
        for status in statuses:
            self._add_row(status)

        missing_required = [
            s for s in statuses if not s.available and s.severity >= ToolSeverity.REQUIRED
        ]
        self._empty.setVisible(not missing_required)
        if missing_required:
            self._status.setText(
                f"Starbash cannot process images until {missing_required[0].name} is "
                "installed.  Install it, then press Re-check."
            )

    # --- Qt page API ------------------------------------------------------
    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        """Only a missing *required* tool holds the wizard open."""
        return not _required_tools_missing()

    def validatePage(self) -> bool:  # noqa: N802 - Qt API
        """Belt to :meth:`isComplete`'s braces, and the loud re-run failure."""
        missing = self._recheck_required()
        self.refresh()
        if not missing:
            return True
        first = missing[0]
        self._status.setText(first.detail or first.summary or f"{first.name} is required.")
        return False


class DonePage(SetupPage):
    """Page 6: the closing checklist, and the two ways out of the wizard.

    Only the **Tools** row gates *Finish* (:meth:`isComplete`); the other rows
    gate the two action buttons, because images may genuinely not be on this
    machine yet and "let me look around first" must not be a trap.
    """

    def __init__(self, sb: Starbash, parent: QWidget | None = None) -> None:
        super().__init__(sb, parent)
        self.setTitle("You're ready")
        self.setSubTitle("Here is what Starbash has so far.  All of it can be changed later.")

        layout = QVBoxLayout(self)
        self._rows = QVBoxLayout()
        layout.addLayout(self._rows)
        self._labels: list[QLabel] = []

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)

    # --- the checklist ----------------------------------------------------
    def _checklist(self) -> list[tuple[str, bool, str]]:
        """``(title, complete, what to do about it)`` for every row.

        The rows are :func:`setup_checklist` - the very list
        :func:`is_wizard_complete` folds into the GUI's start-up test - so what
        the user is shown here and what reopens the wizard cannot drift apart.
        """
        return setup_checklist(self.sb)

    def blockers(self) -> list[str]:
        """The titles of the rows that are not ticked yet."""
        return [title for title, complete, _hint in self._checklist() if not complete]

    # --- rendering --------------------------------------------------------
    def _ensure_rows(self, count: int) -> None:
        """Create the row labels once; :meth:`refresh` only re-words them."""
        while len(self._labels) < count:
            label = QLabel()
            label.setWordWrap(True)
            self._labels.append(label)
            self._rows.addWidget(label)

    def _action_buttons(self) -> list[QPushButton]:
        """The two closing-action buttons, as the wizard owns them."""
        wizard = self.wizard()
        if isinstance(wizard, SetupWizard):
            return wizard.action_buttons()
        return []

    def refresh(self) -> None:
        """Repaint the checklist, and move the buttons with it."""
        items = self._checklist()
        self._ensure_rows(len(items))
        for label, (title, complete, hint) in zip(self._labels, items, strict=True):
            text = f"{'✓' if complete else '○'}  <b>{title}</b>"
            if not complete:
                text += f"\n      {hint}"
            label.setText(text)

        # Qt does *not* gate custom buttons on isComplete() (ours stay enabled
        # with it returning False), so the page moves them itself - and it must,
        # or the user gets a live *Process all* beside a dead *Finish*.
        missing = next((hint for _title, complete, hint in items if not complete), None)
        for button in self._action_buttons():
            button.setEnabled(missing is None)
            button.setToolTip("" if missing is None else missing)

        if missing is None:
            self._status.setText("Everything is in place — choose how you want to start.")
        else:
            self._status.setText(f"Not quite ready yet: {missing[0].lower()}{missing[1:]}.")

    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        """Only a missing *required* tool holds *Finish* back."""
        return not _required_tools_missing()


class SetupWizard(QWizard):
    """The setup wizard itself.  Callers use :func:`run_setup_dialog`."""

    def __init__(
        self,
        sb: Starbash,
        parent: QWidget | None = None,
        bus: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.sb = sb
        #: Kept for callers that want to observe a wizard-driven run; the wizard
        #: itself publishes nothing (pages read state directly).
        self.bus = bus
        #: Which closing action was used; ``None`` means plain *Finish*.
        self.action: str | None = None

        self.setWindowTitle("Starbash setup")
        # A stable handle for the gui-integration movie (doc/plans/gui-integration-video.md
        # §6); names, not behaviour.
        self.setObjectName("SetupWizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        # Page 1 is the start of the story, so a greyed-out *Back* is just noise.
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        # We repaint pages ourselves on every visit - see SetupPage.refresh().
        self.setOption(QWizard.WizardOption.IndependentPages)

        logo = wizard_logo_pixmap()
        if not logo.isNull():
            self.setPixmap(QWizard.WizardPixmap.LogoPixmap, logo)
        watermark = wizard_watermark_pixmap()
        if not watermark.isNull():
            self.setPixmap(QWizard.WizardPixmap.WatermarkPixmap, watermark)

        self.pages: dict[Page, SetupPage] = {
            Page.WELCOME: WelcomePage(sb, self),
            Page.YOU: YouPage(sb, self),
            Page.FOLDERS: FoldersPage(sb, self),
            Page.IMAGES: ImagesPage(sb, self),
            Page.TOOLS: ToolsPage(sb, self),
            Page.DONE: DonePage(sb, self),
        }
        for page_id, page in self.pages.items():
            self.setPage(page_id, page)
        self.setStartId(int(Page.WELCOME))

        # The two closing actions take QWizard's own custom-button slots (Qt
        # pre-creates them hidden), so Qt keeps owning the button row and
        # *Finish* stays the plain "just close" path.
        self.setOption(QWizard.WizardOption.HaveCustomButton1)
        self.setOption(QWizard.WizardOption.HaveCustomButton2)
        self.setButtonText(QWizard.WizardButton.CustomButton1, "Process all my targets")
        self.setButtonText(QWizard.WizardButton.CustomButton2, "Pick a target to process")
        # The script's handles for those two actions (doc/plans/gui-integration-video.md
        # §6). Qt pre-created the buttons, so naming them here is enough - and the
        # names are new ids, so the theme (which styles nothing of theirs) is untouched.
        self._name_action_button(QWizard.WizardButton.CustomButton1, "wizardProcessAllTargets")
        self._name_action_button(QWizard.WizardButton.CustomButton2, "wizardPickTarget")
        # Qt creates those two *enabled* and shows them on every page, and it never
        # consults isComplete() for custom buttons - so without this the wizard
        # offered a live "Process all my targets" on page 1 and only switched it off
        # once a later page had been reached.  They are closing actions: the last
        # page is the only place they belong, and DonePage.refresh() is the one thing
        # allowed to arm them - see _disable_action_buttons.
        self._disable_action_buttons()
        self.customButtonClicked.connect(self._on_custom_button)
        self.currentIdChanged.connect(self._on_current_id_changed)

    # --- Qt window hooks --------------------------------------------------
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        """Centre the mark in the wizard's left pane (see :func:`_centre_pane_mark`).

        Qt builds that label *during* the first show, so this cannot be done in the
        constructor; afterwards it stays put (an ``AlignCenter`` label re-centres
        the mark itself as the window is resized).
        """
        super().showEvent(event)
        _centre_pane_mark(self)

    # --- page flow --------------------------------------------------------
    def nextId(self) -> int:  # noqa: N802 - Qt API
        """Skip the tools page when nothing is missing.

        A user whose tools are all present should not be walked through a page of
        ticks.  The page still exists (and still reports the empty state) for the
        user who reaches it and then installs Siril while it is open.
        """
        current = self.currentId()
        if current == Page.IMAGES and not _required_tools_missing():
            return int(Page.DONE)
        if current >= Page.DONE or current < Page.WELCOME:
            return -1
        return int(current) + 1

    def _on_current_id_changed(self, page_id: int) -> None:
        """Re-read the world whenever a page is entered (``IndependentPages``)."""
        page = self.page(page_id)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()
        if page_id != int(Page.DONE):
            # DonePage.refresh() (just above) is the only thing allowed to arm these.
            self._disable_action_buttons()

    def action_buttons(self) -> list[QPushButton]:
        """The two closing-action buttons Qt owns (see :meth:`_disable_action_buttons`)."""
        buttons: list[QPushButton] = []
        for which in (
            QWizard.WizardButton.CustomButton1,
            QWizard.WizardButton.CustomButton2,
        ):
            button = self.button(which)
            if isinstance(button, QPushButton):
                buttons.append(button)
        return buttons

    def _name_action_button(self, which: QWizard.WizardButton, name: str) -> None:
        """Give one of Qt's custom buttons an ``objectName`` (see the constructor).

        Qt types :meth:`button` as ``QAbstractButton``; the closing actions are the
        ``QPushButton`` it actually created.
        """
        button = self.button(which)
        if isinstance(button, QPushButton):
            button.setObjectName(name)

    def _disable_action_buttons(self) -> None:
        """Switch the closing actions off, and say when they come alive.

        Called at construction and on entering any page but the last, so a wizard
        that has not got there yet never offers them.  Disabled rather than hidden:
        Qt re-shows a hidden custom button on the next page change, and a greyed
        button still explains itself through its tooltip.
        """
        for button in self.action_buttons():
            button.setEnabled(False)
            button.setToolTip("Finish the setup first — the last page has this action.")

    def _on_custom_button(self, which: object) -> None:
        """One of the two closing actions: remember which, then accept.

        Qt hands the slot the enum's *value* (``customButtonClicked(int)``), so the
        comparison is against ``.value`` - and ``which`` is taken as ``object`` so
        the two shapes (a plain int, or the enum itself) both work.
        """
        value = which if isinstance(which, int) else getattr(which, "value", which)
        if value == QWizard.WizardButton.CustomButton1.value:
            self.action = ACTION_PROCESS
        elif value == QWizard.WizardButton.CustomButton2.value:
            self.action = ACTION_TARGETS
        else:
            return
        self.accept()

    # --- accessors --------------------------------------------------------
    def page_of_type(self, page_type: type[SetupPage]) -> SetupPage | None:
        """The page instance of ``page_type`` (used by the GUI and the tests)."""
        for page in self.pages.values():
            if isinstance(page, page_type):
                return page
        return None


def run_setup_dialog(
    sb: Starbash,
    parent: QWidget | None = None,
    bus: object | None = None,
) -> str | None:
    """Show the setup wizard modally.

    Args:
        sb: The application context to read and write.
        parent: The window the wizard belongs to, if any.
        bus: Unused by the wizard today; accepted so callers can pass their event
            bus (and so a wizard-driven run can be observed later).

    Returns:
        :data:`ACTION_PROCESS` / :data:`ACTION_TARGETS` when the user chose one of
        the closing actions, or ``None`` when they simply finished or cancelled.
        The config is written either way — every page saves as it is left — so a
        cancelled wizard is never a lost one.
    """
    wizard = SetupWizard(sb, parent, bus=bus)
    if wizard.exec() != QDialog.DialogCode.Accepted:
        return None
    return wizard.action
