"""The Cover Art Archive client: a release's images and their bytes.

Shares `mb.default_transport` and `mb.USER_AGENT` with the MusicBrainz
client; every answer goes through `cache`, keyed by URL like every other
response.
"""

from __future__ import annotations

import http.client
import json
import urllib.error

from musiclib import mb
from musiclib.cache import Cache

_BASE = "https://coverartarchive.org"

Transport = mb.Transport


class CoverArtError(Exception):
    """The Cover Art Archive did not answer, or answered with something unusable."""

    def __init__(self, url: str, status: str | int):
        super().__init__(f"cover art archive: {url} -> {status}")
        self.url = url
        self.status = str(status)


def _no_answer(url: str, error: OSError | http.client.HTTPException) -> CoverArtError:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    word = "timeout" if isinstance(reason, TimeoutError) else "no connection"
    return CoverArtError(url, word)


class CoverArt:
    """Looks up a release's images and downloads them, through `cache`."""

    def __init__(
        self,
        cache: Cache,
        transport: Transport | None = None,
    ) -> None:
        self.cache = cache
        self.transport = transport or mb.default_transport

    def images(self, release_id: str) -> list[dict]:
        """The release's images, or `[]` for a release the archive has none for."""
        return self._listing(f"{_BASE}/release/{release_id}")

    def release_group_images(self, release_group_id: str) -> list[dict]:
        return self._listing(f"{_BASE}/release-group/{release_group_id}")

    def _get(self, url: str) -> tuple[int, bytes]:
        try:
            return self.transport(url, {"User-Agent": mb.USER_AGENT})
        # `URLError` and `TimeoutError` are both `OSError`; an answer cut short raises `HTTPException`, which is not.
        except (OSError, http.client.HTTPException) as error:
            raise _no_answer(url, error) from error

    def _listing(self, url: str) -> list[dict]:
        def fetch() -> bytes:
            status, body = self._get(url)
            if status == 404:
                # "Nothing here" is a fact worth keeping: cached as an empty
                # list, a warm cache plans the album without the network.
                return b"[]"
            if status != 200:
                raise CoverArtError(url, status)
            return json.dumps(json.loads(body)["images"]).encode()

        return json.loads(self.cache.fetch(url, fetch))

    def download(self, url: str) -> bytes:
        """One image's bytes, byte for byte, cached under its own URL."""

        def fetch() -> bytes:
            status, body = self._get(url)
            if status != 200:
                raise CoverArtError(url, status)
            return body

        return self.cache.fetch(url, fetch)
