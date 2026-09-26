"""The Cover Art Archive client: a release's images and their bytes.

Shares `mb.default_transport` and `mb.USER_AGENT` with the MusicBrainz
client; every answer goes through `cache`, keyed by URL like every other
response.
"""

from __future__ import annotations

import json

from musiclib import mb
from musiclib.cache import Cache

_BASE = "https://coverartarchive.org"

Transport = mb.Transport


class CoverArtError(Exception):
    """The Cover Art Archive answered, but not with something usable."""


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
        url = f"{_BASE}/release/{release_id}"

        def fetch() -> bytes:
            status, body = self.transport(url, {"User-Agent": mb.USER_AGENT})
            if status == 404:
                # "Nothing here" is a fact worth keeping: cached as an empty
                # list, a warm cache plans the album without the network.
                return b"[]"
            if status != 200:
                raise CoverArtError(f"cover art archive: {url} -> {status}")
            return json.dumps(json.loads(body)["images"]).encode()

        return json.loads(self.cache.fetch(url, fetch))

    def download(self, url: str) -> bytes:
        """One image's bytes, byte for byte, cached under its own URL."""

        def fetch() -> bytes:
            status, body = self.transport(url, {"User-Agent": mb.USER_AGENT})
            if status != 200:
                raise CoverArtError(f"cover art archive: {url} -> {status}")
            return body

        return self.cache.fetch(url, fetch)
