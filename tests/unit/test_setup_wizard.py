"""Tests for the setup wizard: the flow `sb gui` shows on a first run.

The interesting behaviour is the *flow* rather than the form: which page you land
on, what holds the wizard open, what the closing checklist gates, and that every
page re-reads the world when it is revisited.  Those are exactly the things the
dialog this replaced got wrong (it blocked nothing and wrote its config only if
you pressed Save), so they are what these cover.

Qt needs a platform plugin: ``tests/conftest.py`` pins ``QT_QPA_PLATFORM=offscreen``
so this module runs headless, and it skips if Qt cannot start at all.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # Probe Qt startup once, so an unusable Qt skips rather than erroring.
    from PySide6.QtWidgets import QApplication as _QApplication

    if _QApplication.instance() is None:
        _QApplication([])
except Exception as _qt_error:  # pragma: no cover - environment dependent
    pytest.skip(f"Qt cannot start here: {_qt_error}", allow_module_level=True)

from PySide6.QtCore import Qt as QtCore  # noqa: E402
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWizard  # noqa: E402

from starbash import events  # noqa: E402
from starbash.tool.base import ToolSeverity, ToolStatus  # noqa: E402
from starbash.ui.qt.pages import wizard as wizard_mod  # noqa: E402
from starbash.ui.qt.pages.wizard import (  # noqa: E402
    ACTION_PROCESS,
    ACTION_TARGETS,
    DonePage,
    FoldersPage,
    ImagesPage,
    Page,
    SetupWizard,
    ToolsPage,
    YouPage,
    is_wizard_complete,
    run_setup_dialog,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context for these tests."""
    from starbash.app import Starbash

    with Starbash("test.setup-wizard") as sb:
        yield sb


@pytest.fixture(autouse=True)
def _clean_bus():
    """Give each test a pristine event bus."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


@pytest.fixture
def wizard(qtbot, app_context) -> SetupWizard:
    """A wizard with all six pages, shown (offscreen) and registered with qtbot.

    It is *shown* on purpose: ``QWizard.setCurrentId`` only has an effect once the
    wizard is visible, which is what the page-flow tests drive it with.
    """
    widget = SetupWizard(app_context)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def _make_fits_folder(tmp_path: Path, name: str = "lights", suffix: str = ".fit") -> Path:
    """Create a folder holding one real (tiny) FITS file, and return it."""
    from astropy.io import fits as astropy_fits

    folder = tmp_path / name
    folder.mkdir()
    hdu = astropy_fits.PrimaryHDU()
    hdu.header["DATE-OBS"] = "2023-10-15T20:30:00"
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["FILTER"] = "Ha"
    hdu.header["OBJECT"] = "M31"
    astropy_fits.HDUList([hdu]).writeto(folder / f"frame{suffix}", overwrite=True)
    return folder


class _FakeFileDialog:
    """Stands in for QFileDialog so a folder can be "chosen" without a dialog."""

    def __init__(self, folder: str) -> None:
        self._folder = folder

    def getExistingDirectory(self, *_args, **_kwargs) -> str:  # noqa: N802 - Qt API
        """Return the canned folder, as the real chooser would."""
        return self._folder


class _CachedTool:
    """A tool that caches its probe, exactly as ``ExternalTool`` does.

    ``available`` stands in for the user installing the tool while the wizard is
    open.  The reported answer only changes once the cache is invalidated, which
    is precisely why *Re-check* has to call ``invalidate_availability()`` — the
    bug this fake exists to catch.
    """

    def __init__(
        self,
        *,
        severity: ToolSeverity,
        name: str = "Siril",
        key: str = "siril",
    ) -> None:
        self._severity = severity
        self._name = name
        self._key = key
        self.available = False
        self.reprobes = 0
        self._cached: ToolStatus | None = None

    def status(self) -> ToolStatus:
        """Report availability, caching the first answer."""
        if self._cached is None:
            self._cached = ToolStatus(
                name=self._name,
                key=self._key,
                severity=self._severity,
                available=self.available,
                install_url="https://example.invalid/siril",
            )
        return self._cached

    def invalidate_availability(self) -> None:
        """Forget the cached probe — the documented way to force a re-probe."""
        self.reprobes += 1
        self._cached = None


@pytest.fixture
def tools_ok(monkeypatch) -> None:
    """Pretend every required tool is installed."""
    monkeypatch.setattr(wizard_mod, "_required_tools_missing", lambda: [])
    # ToolsPage.refresh() builds its rows (and its "all installed" caption) from
    # tool_statuses(), so a host without Siril would otherwise show a missing
    # required tool on this fixture and fail test_tools_page_is_complete_*.
    monkeypatch.setattr(wizard_mod, "tool_statuses", lambda: [])


@pytest.fixture
def siril_missing(monkeypatch) -> _CachedTool:
    """A system where the one required tool (Siril) is not installed."""
    tool = _CachedTool(severity=ToolSeverity.REQUIRED)
    monkeypatch.setattr(wizard_mod, "tools", {"siril": tool})
    monkeypatch.setattr(wizard_mod, "tool_statuses", lambda: [tool.status()])
    return tool


# --- page flow -------------------------------------------------------------


def test_the_wizard_has_the_six_documented_pages(wizard):
    """Ids are the flow: welcome -> you -> folders -> images -> tools -> done."""
    assert list(wizard.pageIds()) == [int(page_id) for page_id in Page]
    assert wizard.startId() == int(Page.WELCOME)
    for page_id in wizard.pageIds():
        assert wizard.page(page_id).title()


def test_next_id_skips_the_tools_page_when_nothing_is_missing(wizard, tools_ok):
    """A run of tidy tools must not cost the user a page of ticks."""
    wizard.setCurrentId(int(Page.IMAGES))
    assert wizard.nextId() == int(Page.DONE)


def test_next_id_visits_the_tools_page_when_siril_is_missing(wizard, siril_missing):
    """A missing required tool has to be shown, not skipped past."""
    wizard.setCurrentId(int(Page.IMAGES))
    assert wizard.nextId() == int(Page.TOOLS)


def test_the_username_is_required(wizard):
    """No name means no *Next* — and that is also how a first run is detected."""
    page = wizard.page_of_type(YouPage)
    assert isinstance(page, YouPage)

    page._name.setText("")
    assert page.isComplete() is False

    page._name.setText("Ada Lovelace")
    assert page.isComplete() is True


def test_the_left_pane_mark_is_centred(wizard):
    """Qt paints the watermark top-left in a full-height label; we centre it.

    Qt owns that label and builds it during the first show, so this is the only
    place it can be caught — see ``_centre_pane_mark``.
    """
    watermark = wizard.pixmap(QWizard.WizardPixmap.WatermarkPixmap)
    assert not watermark.isNull()

    marks = [
        label
        for label in wizard.findChildren(QLabel)
        if not label.pixmap().isNull() and label.pixmap().cacheKey() == watermark.cacheKey()
    ]
    assert marks, "Qt built no watermark label to centre"
    for label in marks:
        assert label.alignment() == QtCore.AlignmentFlag.AlignCenter

    # The logo is a different pixmap, so it must not have been caught by the match.
    logo = wizard.pixmap(QWizard.WizardPixmap.LogoPixmap)
    assert logo.isNull() or watermark.cacheKey() != logo.cacheKey()


# --- page 2: who to credit -------------------------------------------------


def test_you_page_writes_the_same_keys_as_sb_user_setup(wizard, app_context):
    """Leaving the page saves, so the wizard is not a form you must Submit."""
    page = wizard.page_of_type(YouPage)
    assert isinstance(page, YouPage)

    page._name.setText("Ada Lovelace")
    page._email.setText("ada@example.com")
    page._analytics.setChecked(True)
    page._include_email.setChecked(True)
    assert page.validatePage() is True

    repo = app_context.user_repo
    assert repo.get("user.name") == "Ada Lovelace"
    assert repo.get("user.email") == "ada@example.com"
    assert repo.get("analytics.enabled") is True
    assert repo.get("analytics.include_user") is True


def test_you_page_refuses_a_blank_name(wizard, app_context):
    """A blank name writes nothing, so the config never records an empty user."""
    page = wizard.page_of_type(YouPage)
    assert isinstance(page, YouPage)

    page._name.setText("   ")
    assert page.validatePage() is False
    assert not str(app_context.user_repo.get("user.name", "") or "").strip()


def test_you_page_shows_the_documented_analytics_defaults(wizard):
    """An unset preference shows the documented defaults, not an unchecked box."""
    page = wizard.page_of_type(YouPage)
    assert isinstance(page, YouPage)

    assert page._analytics.isChecked() is True
    assert page._include_email.isChecked() is False


def test_the_email_checkbox_needs_an_email(wizard):
    """*Include my email* is meaningless without one, so it is off and disabled."""
    page = wizard.page_of_type(YouPage)
    assert isinstance(page, YouPage)

    page._email.setText("")
    assert page._include_email.isEnabled() is False

    page._email.setText("ada@example.com")
    assert page._include_email.isEnabled() is True

    # Clearing the email again must not leave "include my email" armed.
    page._include_email.setChecked(True)
    page._email.setText("")
    assert page._include_email.isChecked() is False


# --- page 3: output folders ------------------------------------------------


def test_folders_page_creates_the_default_output_folders(wizard, app_context):
    """The pre-selected answer becomes two real repos, and then retires itself."""
    page = wizard.page_of_type(FoldersPage)
    assert isinstance(page, FoldersPage)

    assert page._missing is True
    assert page._default_radio.isChecked() is True  # the one-click path
    assert page._custom_radio.isChecked() is False
    assert page.isComplete() is True
    assert page.validatePage() is True

    manager = app_context.repo_manager
    assert manager.get_repo_by_kind("master") is not None
    assert manager.get_repo_by_kind("processed") is not None

    # Both exist now, so the question goes away and the page reports them instead.
    page.refresh()
    assert page._missing is False
    assert page._default_radio.isHidden() is True
    assert page._custom_radio.isHidden() is True
    assert "already" in page._paths.text()


def test_folders_page_refuses_somewhere_else_with_no_folder(wizard, app_context):
    """*Somewhere else* with nothing picked is not an answer, so Next is refused.

    This is the issue the old checkbox had: unticking it counted as an answer
    ("I keep my masters elsewhere"), so the wizard walked on with nowhere to
    write anything.
    """
    page = wizard.page_of_type(FoldersPage)
    assert isinstance(page, FoldersPage)

    page._custom_radio.setChecked(True)
    assert page._custom_base is None  # nothing picked yet

    assert page.isComplete() is False
    assert page.validatePage() is False
    assert app_context.repo_manager.get_repo_by_kind("master") is None

    assert page._note.isHidden() is False
    assert "Choose folder" in page._note.text()


def test_folders_page_uses_the_folder_it_was_given(wizard, app_context, monkeypatch, tmp_path):
    """A folder picked through *Choose folder…* gets master/ and processed/ inside it."""
    base = tmp_path / "big-disk" / "astro"
    base.mkdir(parents=True)
    monkeypatch.setattr(wizard_mod, "QFileDialog", _FakeFileDialog(str(base)))

    page = wizard.page_of_type(FoldersPage)
    assert isinstance(page, FoldersPage)
    page._on_choose()

    # Picking a folder *is* choosing the custom answer, so it ticks itself.
    assert page._custom_radio.isChecked() is True
    assert page._custom_base == base
    assert page.isComplete() is True
    assert page.validatePage() is True

    manager = app_context.repo_manager
    master = manager.get_repo_by_kind("master")
    processed = manager.get_repo_by_kind("processed")
    assert master is not None
    assert processed is not None
    assert str(wizard_mod._repo_path(master) or "") == str(base.resolve() / "master")
    assert str(wizard_mod._repo_path(processed) or "") == str(base.resolve() / "processed")
    assert (base / "master").is_dir()
    assert (base / "processed").is_dir()


# --- page 4: the raw images ------------------------------------------------


def _raw_paths(sb) -> list[str]:
    """The resolved paths of the raw-image repos Starbash knows about."""
    paths: list[str] = []
    for repo in wizard_mod._raw_image_repos(sb):
        path = wizard_mod._repo_path(repo)
        if path is not None:
            paths.append(str(path))
    return paths


def test_images_page_reports_a_folder_of_fits_files(wizard, monkeypatch, tmp_path):
    """Picking a folder says what was found there, before anything is added."""
    folder = _make_fits_folder(tmp_path)
    monkeypatch.setattr(wizard_mod, "QFileDialog", _FakeFileDialog(str(folder)))

    page = wizard.page_of_type(ImagesPage)
    assert isinstance(page, ImagesPage)
    page._on_choose()

    assert "Found FITS images" in page._status.text()
    assert str(folder) in page._list.text()


def test_images_page_notices_a_folder_without_fits_files(wizard, monkeypatch, tmp_path):
    """A folder of JPEGs is reported as having no images, not silently accepted."""
    folder = tmp_path / "phone-photos"
    folder.mkdir()
    (folder / "IMG_1234.jpg").write_bytes(b"not a fits file")
    monkeypatch.setattr(wizard_mod, "QFileDialog", _FakeFileDialog(str(folder)))

    page = wizard.page_of_type(ImagesPage)
    assert isinstance(page, ImagesPage)
    page._on_choose()

    assert "No FITS images" in page._status.text()
    # The warning is advice, not a refusal: plenty of people keep their lights a
    # level down (raw/M31/lights), and refusing those would trap the very users
    # this page exists for.
    assert page.isComplete() is True


def test_images_page_will_not_go_on_without_a_folder(wizard, monkeypatch, tmp_path):
    """No folder anywhere means nothing to process, so the wizard stays put."""
    page = wizard.page_of_type(ImagesPage)
    assert isinstance(page, ImagesPage)

    assert page.isComplete() is False
    assert page.validatePage() is False
    assert "at least one folder" in page._status.text()

    monkeypatch.setattr(
        wizard_mod, "QFileDialog", _FakeFileDialog(str(_make_fits_folder(tmp_path)))
    )
    page._on_choose()

    assert page.isComplete() is True
    assert page.validatePage() is True


def test_images_page_adds_the_chosen_folder_once(wizard, app_context, monkeypatch, tmp_path):
    """Leaving the page adds the folder as a raw-image repo - exactly once."""
    folder = _make_fits_folder(tmp_path)
    monkeypatch.setattr(wizard_mod, "QFileDialog", _FakeFileDialog(str(folder)))

    page = wizard.page_of_type(ImagesPage)
    assert isinstance(page, ImagesPage)
    page._on_choose()
    assert page.validatePage() is True
    assert _raw_paths(app_context) == [str(folder.resolve())]

    # Leaving the page again must not add the same folder a second time.
    page._chosen = folder
    assert page.validatePage() is True
    assert _raw_paths(app_context) == [str(folder.resolve())]


# --- page 5: the tools (and the Siril gate) --------------------------------


def test_tools_page_blocks_the_wizard_while_siril_is_missing(wizard, siril_missing):
    """A required tool is the one thing allowed to hold the wizard open."""
    page = wizard.page_of_type(ToolsPage)
    assert isinstance(page, ToolsPage)
    page.refresh()

    assert page.isComplete() is False
    # validatePage is the belt to isComplete's braces: it re-checks and refuses,
    # which is also how the re-run case fails loudly.
    assert page.validatePage() is False
    assert "Siril" in page._status.text()


def test_tools_page_is_complete_when_everything_is_present(wizard, tools_ok):
    """With no required tool missing, the gate opens and the empty state shows."""
    page = wizard.page_of_type(ToolsPage)
    assert isinstance(page, ToolsPage)
    page.refresh()

    assert page.isComplete() is True
    assert page._empty.isHidden() is False
    assert page.validatePage() is True


def test_tools_page_recheck_notices_a_tool_installed_meanwhile(wizard, siril_missing):
    """*Re-check* must forget the cached probe, or a new install stays invisible.

    ``ExternalTool.is_available`` caches its first answer, so a user who installs
    Siril while this page is open would otherwise be told "missing" for ever.
    """
    page = wizard.page_of_type(ToolsPage)
    assert isinstance(page, ToolsPage)
    assert page.isComplete() is False

    # The user goes away and installs Siril; our cached answer still says missing.
    siril_missing.available = True
    assert page.isComplete() is False

    page._on_recheck()

    assert siril_missing.reprobes == 1
    assert page.isComplete() is True
    assert page.validatePage() is True


# --- page 6: the checklist, and the two ways out ---------------------------


def test_done_page_gates_the_actions_but_not_finish(wizard, tools_ok):
    """Missing images must not trap the user: they gate the buttons, not Finish."""
    page = wizard.page_of_type(DonePage)
    assert isinstance(page, DonePage)
    page.refresh()

    assert page.blockers()  # nothing is set up in a fresh context
    assert page.isComplete() is True  # ...but Finish is still available

    buttons = page._action_buttons()
    assert len(buttons) == 2
    for button in buttons:
        assert isinstance(button, QPushButton)
        assert button.isEnabled() is False
        assert button.toolTip()  # the caption names what is still missing
    assert "not quite ready" in page._status.text().lower()


def test_done_page_enables_the_actions_once_the_checklist_is_ticked(
    wizard, app_context, tools_ok, tmp_path
):
    """Every row ticked -> both closing actions come alive together."""
    app_context.user_repo.set("user.name", "Ada Lovelace")
    app_context.add_local_repo(str(_make_fits_folder(tmp_path)))

    folders = wizard.page_of_type(FoldersPage)
    assert isinstance(folders, FoldersPage)
    assert folders.validatePage() is True  # creates the master/processed repos

    page = wizard.page_of_type(DonePage)
    assert isinstance(page, DonePage)
    page.refresh()

    assert page.blockers() == []
    for button in page._action_buttons():
        assert button.isEnabled() is True
        assert button.toolTip() == ""


def test_the_closing_checklist_refreshes_when_it_is_visited_again(
    wizard, app_context, tools_ok, tmp_path
):
    """Page 6 re-reads the world: adding a folder on the way round must show up.

    ``IndependentPages`` means ``initializePage()`` runs only once, so a page that
    leant on it would have kept reporting a stale checklist for ever.
    """
    page = wizard.page_of_type(DonePage)
    assert isinstance(page, DonePage)
    wizard.setCurrentId(int(Page.DONE))
    assert "Your raw images" in page.blockers()

    app_context.add_local_repo(str(_make_fits_folder(tmp_path)))

    wizard.setCurrentId(int(Page.WELCOME))
    wizard.setCurrentId(int(Page.DONE))
    assert "Your raw images" not in page.blockers()


# --- the closing actions ---------------------------------------------------


def test_the_closing_actions_start_disabled(qtbot, app_context):
    """A half-built wizard must not offer a live *Process all my targets*.

    Qt builds its custom buttons enabled and never consults ``isComplete()`` for
    them, so they used to be clickable from page one — and clicking one closes the
    wizard with nothing set up.
    """
    wizard = SetupWizard(app_context)
    qtbot.addWidget(wizard)

    buttons = wizard.action_buttons()
    assert len(buttons) == 2
    for button in buttons:
        assert isinstance(button, QPushButton)
        assert button.isEnabled() is False
        assert button.toolTip()  # the tooltip says when they come alive


def test_the_closing_actions_are_armed_on_the_last_page_only(
    wizard, app_context, tools_ok, tmp_path
):
    """The checklist arms them; the next page change puts them back to sleep."""
    app_context.user_repo.set("user.name", "Ada Lovelace")
    app_context.add_local_repo(str(_make_fits_folder(tmp_path)))
    folders = wizard.page_of_type(FoldersPage)
    assert isinstance(folders, FoldersPage)
    assert folders.validatePage() is True

    wizard.setCurrentId(int(Page.DONE))
    assert [button.isEnabled() for button in wizard.action_buttons()] == [True, True]

    wizard.setCurrentId(int(Page.WELCOME))
    assert [button.isEnabled() for button in wizard.action_buttons()] == [False, False]


def test_the_custom_buttons_record_which_action_was_used(qtbot, app_context):
    """The wizard reports *how* the user left it, not merely that they did."""
    first = SetupWizard(app_context)
    second = SetupWizard(app_context)
    qtbot.addWidget(first)
    qtbot.addWidget(second)

    first._on_custom_button(QWizard.WizardButton.CustomButton1.value)
    second._on_custom_button(QWizard.WizardButton.CustomButton2.value)

    assert first.action == ACTION_PROCESS
    assert second.action == ACTION_TARGETS
    assert first.result() == QDialog.DialogCode.Accepted.value


def test_a_click_on_something_else_is_not_an_action(qtbot, app_context):
    """Only the two custom buttons mean anything; the rest just close the wizard."""
    wizard = SetupWizard(app_context)
    qtbot.addWidget(wizard)

    wizard._on_custom_button(QWizard.WizardButton.HelpButton.value)
    assert wizard.action is None


def test_run_setup_dialog_reports_the_closing_action(monkeypatch, app_context):
    """Its return value is the caller's instruction (main_window acts on it)."""

    def fake_exec(self) -> int:
        self.action = ACTION_TARGETS
        return QDialog.DialogCode.Accepted.value

    monkeypatch.setattr(SetupWizard, "exec", fake_exec)
    assert run_setup_dialog(app_context) == ACTION_TARGETS


def test_run_setup_dialog_returns_none_when_cancelled(monkeypatch, app_context):
    """Cancelling is not a request to do anything - the config is saved anyway."""

    def fake_exec(_self) -> int:
        return QDialog.DialogCode.Rejected.value

    monkeypatch.setattr(SetupWizard, "exec", fake_exec)
    assert run_setup_dialog(app_context) is None


# --- the start-up test: is the setup finished? -----------------------------


def _incomplete(sb) -> list[str]:
    """The titles of the setup minimums that are not met yet."""
    return [title for title, complete, _hint in wizard_mod.setup_checklist(sb) if not complete]


def test_is_wizard_complete_needs_every_minimum(wizard, app_context, tools_ok, tmp_path):
    """A username is *not* "set up": each of the four minimums is asked in turn."""
    assert _incomplete(app_context) == ["Your details", "Output folders", "Your raw images"]
    assert is_wizard_complete(app_context) is False

    app_context.user_repo.set("user.name", "Ada Lovelace")
    assert _incomplete(app_context) == ["Output folders", "Your raw images"]
    assert is_wizard_complete(app_context) is False

    folders = wizard.page_of_type(FoldersPage)
    assert isinstance(folders, FoldersPage)
    assert folders.validatePage() is True  # creates master *and* processed
    assert _incomplete(app_context) == ["Your raw images"]
    assert is_wizard_complete(app_context) is False

    # The *folder* is the requirement, not the FITS files in it, exactly as on
    # ImagesPage: turning "no .fit/.fits directly inside" into "not set up" would
    # re-open the wizard for every user who keeps their lights a level down.
    lights = tmp_path / "lights"
    lights.mkdir()
    (lights / "IMG_1234.jpg").write_bytes(b"not a fits file")
    app_context.add_local_repo(str(lights))

    assert _incomplete(app_context) == []
    assert is_wizard_complete(app_context) is True


def test_is_wizard_complete_needs_the_required_tools(wizard, app_context, siril_missing, tmp_path):
    """Everything but Siril is still not set up - the one thing that can block."""
    app_context.user_repo.set("user.name", "Ada Lovelace")
    folders = wizard.page_of_type(FoldersPage)
    assert isinstance(folders, FoldersPage)
    assert folders.validatePage() is True
    lights = tmp_path / "lights"
    lights.mkdir()
    app_context.add_local_repo(str(lights))

    assert _incomplete(app_context) == ["Tools"]
    assert is_wizard_complete(app_context) is False


def test_the_last_page_and_the_start_up_test_share_one_definition(
    wizard, app_context, tools_ok, tmp_path
):
    """What the checklist shows is what reopens the wizard: one list, not two."""
    page = wizard.page_of_type(DonePage)
    assert isinstance(page, DonePage)
    page.refresh()
    assert page.blockers() == _incomplete(app_context)

    app_context.user_repo.set("user.name", "Ada Lovelace")
    folders = wizard.page_of_type(FoldersPage)
    assert isinstance(folders, FoldersPage)
    assert folders.validatePage() is True
    lights = tmp_path / "lights"
    lights.mkdir()
    app_context.add_local_repo(str(lights))
    page.refresh()

    assert page.blockers() == []
    assert _incomplete(app_context) == []
    assert is_wizard_complete(app_context) is True
