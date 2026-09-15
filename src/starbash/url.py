"""URL helpers: canonical ``file://`` URLs for local files, plus web links.

A repository (and every file Starbash indexes from it) is identified by its
``file://`` URL: it is written into config files and databases and compared for
equality, so the whole code base has to agree on one spelling.  Build URLs with
:func:`make_file_url` and read them back with :func:`path_from_file_url`; never
with ``f"file://{path}"``, which on Windows puts the filesystem path in the URL
*authority* (``file://C:\\data`` -- unparseable) instead of the path
(``file:///C:/data``).

Both helpers are ``toml_repo``'s, re-exported here rather than reimplemented:
Starbash *writes* these URLs and toml_repo *reads* them back when a repo is
loaded, so a second copy of the rule is exactly how the two used to disagree on
Windows.  A URL the canonical parser refuses (the legacy spelling, or a path that
is not absolute) raises :exc:`ValueError` rather than being guessed at.

The spelling is whatever :meth:`pathlib.Path.as_uri` produces::

    file:///home/user/data             POSIX
    file:///C:/Users/user/data         Windows: the drive is a path segment
    file:////server/share/data         Windows UNC share

Requires ``toml-repo >= 0.1.7``, the release that added the helpers.
"""

from toml_repo import make_file_url as make_file_url
from toml_repo import path_from_file_url as path_from_file_url

project = "https://github.com/geeksville/starbash"
analytics_docs = f"{project}/blob/main/doc/analytics.md"


def new_issue(report_id: str | None = None) -> str:
    if report_id:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem%2C%20but%20include%20this%3A%0ACrash%20ID%20{report_id}"
    else:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem"
