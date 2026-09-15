"""Tests for the url module.

``make_file_url``/``path_from_file_url`` are the single spelling of a local
file URL used across Starbash (databases, config files, the GUI).  ``starbash.url``
re-exports toml_repo's helpers rather than keeping its own copy -- Starbash writes
those URLs and toml_repo has to read them back, so there must be one
implementation, not two that can drift apart.
"""

from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlparse

import pytest

from starbash.url import make_file_url, new_issue, path_from_file_url, project


def test_new_issue_without_report_id():
    """Test new_issue generates correct URL without report_id."""
    url = new_issue()

    assert url.startswith(project)
    assert "/issues/new" in url
    assert "body=Please%20describe%20the%20problem" in url
    assert "Crash%20ID" not in url


def test_new_issue_with_report_id():
    """Test new_issue generates correct URL with report_id."""
    report_id = "abc123-def456"
    url = new_issue(report_id)

    assert url.startswith(project)
    assert "/issues/new" in url
    assert "body=Please%20describe%20the%20problem" in url
    assert f"Crash%20ID%20{report_id}" in url


def test_new_issue_with_empty_string_report_id():
    """Test new_issue treats empty string as no report_id."""
    url = new_issue("")

    # Empty string is falsy in Python, so it should behave like None
    assert url.startswith(project)
    assert "/issues/new" in url
    assert "Crash%20ID" not in url


def test_new_issue_url_format():
    """Test the URL structure matches GitHub's issue creation format."""
    url = new_issue()

    # Should be a valid GitHub issue creation URL
    expected_base = f"{project}/issues/new"
    assert url.startswith(expected_base)

    # Should have query parameters
    assert "?" in url
    assert "body=" in url


def test_new_issue_with_special_characters_in_report_id():
    """Test new_issue handles special characters in report_id."""
    report_id = "test-123_456.789"
    url = new_issue(report_id)

    assert report_id in url
    assert "Crash%20ID" in url


def test_make_file_url_is_a_uri_for_the_given_file(tmp_path):
    """The URL is properly encoded, so it also works where paths use backslashes."""
    path = tmp_path / "cam" / "x" / "bias" / "master_bias.fit"
    path.parent.mkdir(parents=True)
    path.touch()

    url = make_file_url(path)

    assert url.startswith("file:///")
    assert "\\" not in url
    parsed = urlparse(url)
    assert parsed.scheme == "file"
    assert unquote(parsed.path).endswith("cam/x/bias/master_bias.fit")


def test_make_file_url_makes_a_relative_path_absolute(tmp_path, monkeypatch):
    """``as_uri`` refuses a relative path, and a URL nothing can open helps no caller."""
    (tmp_path / "frame.fits").touch()
    monkeypatch.chdir(tmp_path)

    url = make_file_url(Path("frame.fits"))

    assert url.startswith("file:///")
    assert unquote(urlparse(url).path).endswith("frame.fits")


def test_path_from_file_url_round_trips_a_real_path(tmp_path):
    """The two helpers are exact inverses -- that is what makes the URL an identity."""
    target = tmp_path / "my data" / "café"
    target.mkdir(parents=True)

    url = make_file_url(target)

    assert " " not in url and "café" not in url  # encoded, not raw
    assert path_from_file_url(url) == target


def test_path_from_file_url_reads_a_windows_drive_letter():
    """``file:///C:/dir`` is a drive path, not a path on the current drive.

    Parsed on POSIX too: the conversion is platform-independent, which is what
    lets the Linux CI catch a Windows regression.
    """
    path = path_from_file_url("file:///C:/Users/runner/data")

    assert PureWindowsPath(str(path)).drive == "C:"
    assert PureWindowsPath(str(path)).parts == ("C:\\", "Users", "runner", "data")


def test_path_from_file_url_handles_a_windows_unc_share():
    """Both spellings of a UNC share name the same server path.

    ``Path.as_uri()`` writes a UNC path as ``file:////server/share`` (an empty
    host, and a path starting with two slashes), while a hand-written URL puts
    the server in the host position.  Both must land on the same path.
    """
    from_as_uri = path_from_file_url("file:////server/share/data")
    from_host = path_from_file_url("file://server/share/data")

    assert str(from_as_uri) == str(from_host)
    assert str(PureWindowsPath(str(from_host))) == "\\\\server\\share\\data"


def test_path_from_file_url_ignores_a_localhost_host():
    """``file://localhost/data`` means ``file:///data`` -- the host is this machine."""
    assert str(path_from_file_url("file://localhost/data")) == "/data"
    assert str(path_from_file_url("file://127.0.0.1/data")) == "/data"


def test_path_from_file_url_keeps_a_posix_directory_that_looks_like_a_drive():
    """A POSIX "/C:" directory must not be mistaken for a Windows drive.

    ``as_uri()`` percent-encodes the colon of a POSIX path, so matching the drive
    pattern against the encoded path is what keeps the two apart.
    """
    assert str(path_from_file_url("file:///C%3A/x")) == "/C:/x"


@pytest.mark.parametrize(
    "url",
    [
        "file://C:\\Users\\runner\\data",
        "file://C:/Users/runner/data",
        "file://c:/data",
    ],
    ids=["backslashes", "forward-slashes", "lowercase-drive"],
)
def test_path_from_file_url_rejects_the_legacy_hand_built_form(url):
    """The old ``f"file://{path}"`` spelling is refused, not silently misread.

    Its filesystem path sits in the URL *authority*, so nothing distinguishes it
    from a host: reading it as a UNC share would resolve the real ``C:\\...`` path
    to something that does not exist.
    """
    with pytest.raises(ValueError, match="not canonical"):
        path_from_file_url(url)


@pytest.mark.parametrize("url", ["pkg://defaults", "https://example.com/x", "nonsense"])
def test_path_from_file_url_rejects_a_non_file_url(url):
    """A non-file scheme has no local path."""
    with pytest.raises(ValueError, match="Not a file:// URL"):
        path_from_file_url(url)


def test_starbash_exposes_toml_repos_helpers_itself():
    """The writer and the reader are one implementation, not two copies.

    Starbash records these URLs in its databases and config files and toml_repo
    resolves them when the repo is loaded again; a second implementation of the
    rule here is exactly how the two used to disagree on Windows.
    """
    import toml_repo

    assert make_file_url is toml_repo.make_file_url
    assert path_from_file_url is toml_repo.path_from_file_url


def test_agrees_with_toml_repo_on_encoding(tmp_path):
    """Starbash writes these URLs, toml_repo reads them back -- they must match."""
    import toml_repo

    for path in (tmp_path, tmp_path / "a b" / "c&d", tmp_path / "café"):
        assert make_file_url(path) == toml_repo.make_file_url(path)


@pytest.mark.parametrize(
    "url",
    [
        "file:///home/user/data",
        "file:///C:/Users/runner/data",
        "file:////server/share/data",
        "file://server/share/data",
        "file:///a%20b/c%26d",
        "file:///C%3A/x",
        "file://localhost/data",
    ],
)
def test_agrees_with_toml_repo_on_parsing(url):
    """Both read every URL spelling alike -- and reject the legacy one alike."""
    import toml_repo

    assert str(path_from_file_url(url)) == str(toml_repo.path_from_file_url(url))
    assert path_from_file_url(url) == toml_repo.path_from_file_url(url)


def test_agrees_with_toml_repo_on_rejecting_the_legacy_form():
    """Neither accepts a hand-built Windows URL."""
    import toml_repo

    with pytest.raises(ValueError):
        toml_repo.path_from_file_url("file://C:\\Users\\runner\\data")
