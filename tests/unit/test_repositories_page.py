"""Tests for the Repositories page: which repos show, add-kind limits, buttons.

The interesting behaviour is (a) the page defaulting to the same "interesting"
repository set the CLI's ``sb repo list`` shows, (b) refusing to *offer* a second
master or processed repo (the CLI refuses to add one), and (c) keeping
*Remove selected* honest about the table selection - including leaving it off for
the repositories Starbash manages itself, which are listed but cannot be removed
individually.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from starbash import events  # noqa: E402
from starbash.ui.qt.pages.repositories import ADD_KINDS, RepositoriesPage  # noqa: E402
from starbash.ui.qt.services import load_repos  # noqa: E402
from starbash.url import make_file_url  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def app_context(setup_test_environment, mock_analytics):
    """A real (isolated) Starbash context."""
    from starbash.app import Starbash

    with Starbash("test.repositories") as sb:
        yield sb


@pytest.fixture
def bus():
    """A live event bridge, closed after the test."""
    from starbash.ui.qt.bridge import EventBusBridge

    bridge = EventBusBridge()
    yield bridge
    bridge.close()


@pytest.fixture(autouse=True)
def _clean_bus():
    """Give each test a pristine event bus."""
    events.clear_subscribers()
    yield
    events.clear_subscribers()


@pytest.fixture
def input_repo(app_context, tmp_path: Path) -> str:
    """A registered raw-image repo, so the default view is never empty."""
    repo_dir = (tmp_path / "lights").resolve()
    repo_dir.mkdir()
    app_context.add_local_repo(str(repo_dir))
    return make_file_url(repo_dir)


def _kind_index(kind: str | None) -> int:
    """Index of the add-kind entry with ``kind`` (``None`` is raw images)."""
    return next(index for index, (_label, value) in enumerate(ADD_KINDS) if value == kind)


def _urls(page: RepositoriesPage) -> list[str]:
    """Every repository URL currently shown in the page's table."""
    return [row["url"] for row in page._model.rows()]


def _row_for(page: RepositoriesPage, url: str) -> int:
    """Row index of ``url`` in the page's table (fails if it is not listed)."""
    return _urls(page).index(url)


def _managed_url(page: RepositoriesPage) -> str:
    """A listed URL Starbash manages itself, i.e. one the user cannot remove."""
    return next(url for url in _urls(page) if not page.sb.is_repo_removable(url))


def _kind_enabled(page: RepositoriesPage, kind: str | None) -> bool:
    """Whether the add-kind entry for ``kind`` is currently selectable."""
    return page._kind_enabled(_kind_index(kind))


# --- which repositories show -----------------------------------------------


def test_load_repos_defaults_to_the_cli_listing(app_context, input_repo):
    """``load_repos`` mirrors ``sb repo list`` unless ``show_all`` is set."""
    default_urls = [row["url"] for row in load_repos(app_context)]
    regular_urls = [repo.url for repo in app_context.repo_manager.regular_repos]

    assert default_urls == regular_urls
    assert input_repo in default_urls

    all_urls = [row["url"] for row in load_repos(app_context, show_all=True)]
    assert all_urls == [repo.url for repo in app_context.repo_manager.repos]
    # The test environment really does have internal repos to hide.
    assert len(all_urls) > len(default_urls)


def test_default_view_hides_internal_repos(qtbot, app_context, bus, input_repo):
    """A freshly opened page lists only the repos the CLI shows."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    assert _urls(page) == [repo.url for repo in app_context.repo_manager.regular_repos]
    assert input_repo in _urls(page)
    assert "pkg://defaults" not in _urls(page)


def test_show_all_checkbox_toggles_the_internal_repos(qtbot, app_context, bus):
    """Ticking *Show all repositories* reveals the internal repos again."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    assert "pkg://defaults" not in _urls(page)

    page._show_all.setChecked(True)
    assert _urls(page) == [repo.url for repo in app_context.repo_manager.repos]
    assert "pkg://defaults" in _urls(page)

    page._show_all.setChecked(False)
    assert "pkg://defaults" not in _urls(page)


# --- one master / one processed repo ---------------------------------------


def test_master_and_processed_kinds_disabled_once_present(qtbot, app_context, bus, tmp_path: Path):
    """The add-kind list drops master/processed once such a repo exists."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    # Nothing of either kind exists yet, and raw repos are never restricted.
    assert _kind_enabled(page, None) is True
    assert _kind_enabled(page, "master") is True
    assert _kind_enabled(page, "processed") is True

    # Pretend the user picked "Master frames", then a master repo appears.
    page._kind.setCurrentIndex(_kind_index("master"))
    master_dir = (tmp_path / "masters").resolve()
    master_dir.mkdir()
    app_context.add_local_repo(str(master_dir), repo_type="master")
    page.refresh()

    assert _kind_enabled(page, "master") is False
    assert _kind_enabled(page, "processed") is True
    # The selection must not stay on an entry we just made unselectable.
    assert page._kind.currentData() != "master"

    processed_dir = (tmp_path / "processed").resolve()
    processed_dir.mkdir()
    app_context.add_local_repo(str(processed_dir), repo_type="processed")
    page.refresh()

    assert _kind_enabled(page, "processed") is False
    assert _kind_enabled(page, None) is True
    assert page._kind.currentData() is None


# --- remove button ---------------------------------------------------------


def test_remove_is_disabled_until_a_repo_is_selected(qtbot, app_context, bus, input_repo):
    """*Remove selected* follows the table selection."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    assert page._remove.isEnabled() is False

    page._table.selectRow(_row_for(page, input_repo))
    assert page._remove.isEnabled() is True

    page._table.clearSelection()
    assert page._remove.isEnabled() is False


def test_remove_stays_disabled_while_a_job_runs(qtbot, app_context, bus, input_repo):
    """A running add/reindex keeps *Remove selected* unavailable."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()
    page._table.selectRow(_row_for(page, input_repo))
    assert page._remove.isEnabled() is True

    page._busy(True, "Re-indexing repositories…")
    assert page._remove.isEnabled() is False

    page._busy(False)
    assert page._remove.isEnabled() is True


def test_remove_is_off_for_repos_starbash_manages(qtbot, app_context, bus, input_repo):
    """A listed-but-managed repo (the recipes checkout) cannot be selected for removal."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    managed = _managed_url(page)
    page._table.selectRow(_row_for(page, managed))

    assert page._remove.isEnabled() is False
    assert "managed by Starbash" in page._remove.toolTip()

    # Selecting a repo the user added offers removal again, tooltip included.
    page._table.selectRow(_row_for(page, input_repo))
    assert page._remove.isEnabled() is True
    assert page._remove.toolTip() == ""


def test_remove_is_off_for_internal_repos_when_showing_all(qtbot, app_context, bus):
    """The internal repos revealed by *Show all* are not removable either."""
    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page._show_all.setChecked(True)

    internal = ["pkg://defaults", app_context.user_repo.url]
    for url in internal:
        assert url in _urls(page)
        page._table.selectRow(_row_for(page, url))
        assert page._remove.isEnabled() is False


def test_removing_a_managed_repo_leaves_the_user_config_alone(
    qtbot, app_context, bus, input_repo, monkeypatch
):
    """Even if it is invoked directly, removing a managed repo changes nothing."""
    from tomlkit import dumps

    page = RepositoriesPage(app_context, bus)
    qtbot.addWidget(page)
    page.refresh()

    # A regression here would fall through to a modal error dialog, which blocks
    # a headless run forever; record it instead so the test fails rather than hangs.
    errors: list[str] = []
    monkeypatch.setattr(page, "show_error", errors.append)

    before = dumps(app_context.user_repo.config)
    statuses: list[str] = []
    page.status.connect(statuses.append)

    managed = _managed_url(page)
    page._table.selectRow(_row_for(page, managed))
    page._on_remove()

    assert errors == []
    assert dumps(app_context.user_repo.config) == before
    assert app_context.is_repo_removable(input_repo) is True
    assert statuses == [f"{managed} is managed by Starbash and cannot be removed."]
