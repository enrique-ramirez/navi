"""The response cache: what a warm run never asks the network for.

Every MusicBrainz, AcoustID and Cover Art Archive response goes through
`Cache.fetch(url, get)`, keyed by the full URL. One file per URL, named from
a hash of the URL rather than the URL itself, because a query string, a "/"
or a difference in case can collide on a real filesystem (and does, on the
MacBook's case-insensitive APFS) or simply not fit one.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Callable


class Cache:
    """Stores and replays byte responses under `directory`, one file per URL.

    With `refresh=True`, each URL is asked for again at most once per `Cache`
    instance.
    """

    def __init__(self, directory: Path, refresh: bool = False) -> None:
        self.directory = Path(directory)
        self.refresh = refresh
        self._refreshed: set[str] = set()

    def _path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.directory / digest

    def fetch(self, url: str, get: Callable[[], bytes]) -> bytes:
        """Return the stored body for `url`, or `get()`'s if there is none to keep.

        `get` is called exactly when the answer is not already trustworthy:
        cold, or `refresh` and not yet asked this instance. Whatever it
        returns is stored byte for byte before being handed back. If `get`
        raises, nothing is written - a 503 must not leave a cached failure
        behind for the next run to find and believe.
        """
        path = self._path(url)
        fresh = self.refresh and url not in self._refreshed
        if not fresh and path.exists():
            return path.read_bytes()

        body = get()
        self._refreshed.add(url)
        self._write(path, body)
        return body

    def _write(self, path: Path, body: bytes) -> None:
        # Temp file + rename: a process killed mid-write leaves the old
        # cached copy (or nothing), never a truncated one.
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
