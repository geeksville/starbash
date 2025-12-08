from pathlib import Path
from urllib.parse import quote

project = "https://github.com/geeksville/starbash"
analytics_docs = f"{project}/blob/main/doc/analytics.md"


def new_issue(report_id: str | None = None) -> str:
    if report_id:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem%2C%20but%20include%20this%3A%0ACrash%20ID%20{report_id}"
    else:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem"


def make_file_url(f: Path) -> str:
    """Create a file:// URL for the given path."""
    return f"file://{quote(str(f))}"
