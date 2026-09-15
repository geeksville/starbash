"""URL helpers: canonical ``file://`` URLs for local files, plus web links.

A repository (and every file Starbash indexes from it) is identified by its
``file://`` URL: it is written into config files and databases and compared for
equality, so the whole code base has to agree on one spelling.  Build URLs with
:func:`make_file_url` and read them back with :func:`path_from_file_url`; never
with ``f"file://{path}"``, which on Windows puts the filesystem path in the URL
*authority* (``file://C:\\data`` -- unparseable) instead of the path
(``file:///C:/data``).

The spelling is whatever :meth:`pathlib.Path.as_uri` produces::

    file:///home/user/data             POSIX
    file:///C:/Users/user/data         Windows: the drive is a path segment
    file:////server/share/data         Windows UNC share
"""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

project = "https://github.com/geeksville/starbash"
analytics_docs = f"{project}/blob/main/doc/analytics.md"

#: A canonical drive-letter path segment, e.g. the ``/C:/`` of ``file:///C:/data``.
_DRIVE_SEGMENT = re.compile(r"^/[A-Za-z]:(?:/|$)")

#: URL hosts that mean "this machine", i.e. no host at all.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def new_issue(report_id: str | None = None) -> str:
    if report_id:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem%2C%20but%20include%20this%3A%0ACrash%20ID%20{report_id}"
    else:
        return f"{project}/issues/new?body=Please%20describe%20the%20problem"


def make_file_url(f: Path | str) -> str:
    """Canonical ``file://`` URL for a filesystem path.

    Delegates the encoding to ``Path.as_uri()``, which is the only spelling that
    is right on every platform: a hand-built URL has to cope with backslashes,
    drive letters, UNC shares, spaces and non-ASCII characters, and gets at
    least one of them wrong.

    Args:
        f: The path to encode.  A relative path is made absolute first, since
            ``as_uri()`` refuses relative paths and a URL that cannot be opened
            helps no caller.

    Returns:
        The URL, e.g. ``file:///C:/Users/me/lights`` on Windows (never
        ``file://C:\\Users\\me\\lights``) or ``file:///home/me/lights`` on POSIX.
    """
    path = Path(f)
    if not path.is_absolute():
        path = path.resolve()
    return path.as_uri()


def path_from_file_url(url: str) -> Path:
    """The filesystem path named by a canonical ``file://`` URL.

    The inverse of :func:`make_file_url`: percent-encoding is decoded and the
    URL's spelling of a Windows drive letter is mapped back to the one ``Path``
    expects.  Parsing is deliberately platform-independent (a Windows path URL
    yields a Windows path even when parsed on POSIX), so it can be tested
    anywhere.

    Args:
        url: The URL to parse.

    Returns:
        The path the URL names.

    Raises:
        ValueError: If ``url`` is not a ``file://`` URL, or uses the legacy
            hand-built spelling (``file://C:\\data``).  That form puts the
            filesystem path in the URL *authority*, so nothing distinguishes it
            from a URL host: reading it as a UNC share would silently resolve to
            a path that does not exist, so it is refused instead.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "file":
        raise ValueError(f"Not a file:// URL: {url!r}")

    host = parsed.netloc
    if host.lower() in _LOCAL_HOSTS:
        # "file://localhost/data" is just "file:///data".
        host = ""

    if host:
        if "\\" in host or _DRIVE_SEGMENT.match(f"/{host}"):
            raise ValueError(
                f"file:// URL is not canonical: {url!r}.  Build it with "
                f"make_file_url() (i.e. Path.as_uri()), which gives "
                f"'file:///C:/data', not 'file://C:\\data'."
            )
        # A UNC share written with a host: file://server/share/data.
        path_text = f"//{host}{parsed.path}"
    elif _DRIVE_SEGMENT.match(parsed.path):
        # file:///C:/data -> C:/data.  Matching the *still encoded* path is
        # deliberate: a POSIX directory that really is named "/C:" has its colon
        # percent-encoded by as_uri() ("file:///C%3A/x"), so only a Windows drive
        # letter can match here.
        path_text = parsed.path[1:]
    else:
        path_text = parsed.path

    return Path(unquote(path_text))
