"""Tests for the url module."""

from starbash.url import new_issue, project


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
