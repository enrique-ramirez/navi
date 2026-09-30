"""The one test for a path that climbs out of the folder it is joined to, and the shapes of the names in a URL."""

from __future__ import annotations

import re

#: A drop's folder name, `YYYYMMDD-HHMMSS` with `-2`, `-3` where taken.
DROP_ID = re.compile(r"\d{8}-\d{6}(?:-\d+)?")
#: An album's folder name inside a drop, `01`, `02`, ...
ALBUM_NUMBER = re.compile(r"\d{2,}")
_ALBUM_ROUTE = re.compile(r"/api/drops/([^/]+)(?:/albums/([^/]+))?(?:/|$)")


def climbs(path: str) -> bool:
    """A `..` segment, split on either slash."""
    return ".." in path.replace("\\", "/").split("/")


def names_nothing_real(path: str) -> bool:
    """True where `path` is an API path whose drop id or album number is not one the server makes.

    Every route that joins those names to a folder is checked here, once, so
    `%2E` or `1` cannot select the drop's own folder or a sibling of it.
    """
    found = _ALBUM_ROUTE.match(path)
    if found is None:
        return False
    drop, n = found.groups()
    return DROP_ID.fullmatch(drop) is None or (n is not None and ALBUM_NUMBER.fullmatch(n) is None)
