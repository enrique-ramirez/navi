"""The MusicBrainz client: rate limiting, retries and what each lookup asks for.

MusicBrainz wants a proper User-Agent and no more than one request a second;
a 503, a 502/504 or the network itself failing all mean back off and retry,
sharing one budget of five attempts, after which the album is `unidentified:
musicbrainz unavailable` rather than stuck retrying forever. Genres and
folksonomy tags live on the release group, not the release, and share one
lookup.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import quote

from musiclib import __version__
from musiclib.cache import Cache

USER_AGENT = f"musiclib/{__version__} ( hello@enrique-ramirez.com )"

_BASE = "https://musicbrainz.org/ws/2"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
_MIN_INTERVAL = 1.0
# Growing waits after a 503, measured start to start. All above the 1 s
# floor, so the rate limit itself never swallows a step and makes it look
# like the backoff stopped growing.
_BACKOFF = [2.0, 4.0, 8.0, 16.0]
_MAX_ATTEMPTS = 5
# 502/503/504 all say "try again later", the same as a 503, and share its
# budget and backoff rather than getting a separate count each.
_RETRYABLE_STATUSES = {502, 503, 504}
# A stand-in body for a cached 404: distinct from anything MusicBrainz could
# answer with, so `_get` can tell a remembered "no such release" apart from
# a cached real response.
_NOT_FOUND = b"\x00musiclib:not-found\x00"

Transport = Callable[[str, dict[str, str]], "tuple[int, bytes]"]


class Throttle:
    """No more than one `wait()` call's worth of gap between calls to `hold`, start to start.

    Shared by `MusicBrainz` and `AcoustID`, which only differ in the wait
    they pass. One read of the clock and at most one sleep per call - never
    a loop polling for the wait to pass, which a clock that only moves when
    slept on would spin on forever.
    """

    def __init__(self, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.clock = clock
        self.sleep = sleep
        self._last_start: float | None = None

    def hold(self, wait: float) -> None:
        now = self.clock()
        if self._last_start is not None:
            remaining = wait - (now - self._last_start)
            if remaining > 0:
                self.sleep(remaining)
                now += remaining
        self._last_start = now


class MusicBrainzError(Exception):
    """MusicBrainz answered, but not with something usable."""


class MusicBrainzNotFound(MusicBrainzError):
    """MusicBrainz answered 404: it has no such record."""


class MusicBrainzUnavailable(MusicBrainzError):
    """Five failures in a row, of any retryable kind: MusicBrainz itself is
    down, or unreachable, not this one lookup."""

    def __init__(self) -> None:
        super().__init__("musicbrainz unavailable")


def _lucene_escape(value: str) -> str:
    # Reserved Lucene characters, escaped so a title or artist that happens
    # to contain one is searched for literally rather than parsed as an
    # operator.
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", value)


def default_transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """The real network path for a live run: shared with the AcoustID client.

    Never exercised by the tests, which always pass their own `transport`.
    """
    request = urllib.request.Request(url, headers=headers)
    try:
        # A stalled connection must fail, not hang the run forever.
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _track_counts(release: dict) -> list[int]:
    return [len(medium.get("tracks", [])) for medium in release.get("media", [])]


class MusicBrainz:
    """Every lookup goes through `cache`, so a warm cache never reaches
    `transport`. `clock` and `sleep` default to `time.monotonic` and
    `time.sleep`; tests pass a fake pair so the 1 second waits do not
    actually cost a second.
    """

    def __init__(
        self,
        cache: Cache,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.transport = transport or default_transport
        self._throttle = Throttle(clock, sleep)

    def _ask(self, url: str) -> bytes:
        """What MusicBrainz answers for `url`, asked now: the body, or `_NOT_FOUND` for a 404."""
        attempt = 0
        while True:
            wait = _MIN_INTERVAL if attempt == 0 else _BACKOFF[attempt - 1]
            self._throttle.hold(wait)
            try:
                status, body = self.transport(url, {"User-Agent": USER_AGENT})
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                # The network itself, not MusicBrainz, said no: retried
                # the same as a 503, out of the same budget.
                status, body = None, b""
            if status == 200:
                return body
            if status == 404:
                # Cached like any other answer: a wrong or withdrawn MBID
                # would otherwise cost a request and a second of rate
                # limit on every warm run.
                return _NOT_FOUND
            if status is None or status in _RETRYABLE_STATUSES:
                attempt += 1
                if attempt >= _MAX_ATTEMPTS:
                    raise MusicBrainzUnavailable()
                continue
            raise MusicBrainzError(f"musicbrainz: {url} -> {status}")

    def _get(self, url: str) -> bytes:
        # A 404 is the one answer that is remembered: `_ask` returns a
        # marker for it instead of raising, and it is turned back into
        # `MusicBrainzError` below.
        body = self.cache.fetch(url, lambda: self._ask(url))
        if body == _NOT_FOUND:
            raise MusicBrainzNotFound(f"musicbrainz: {url} -> 404")
        return body

    def release(self, mbid: str) -> dict:
        url = (
            f"{_BASE}/release/{mbid}"
            "?inc=artist-credits+labels+media+recordings+release-groups&fmt=json"
        )
        return json.loads(self._get(url))

    def release_relations(self, mbid: str) -> dict:
        url = f"{_BASE}/release/{mbid}?inc=release-rels&fmt=json"
        return json.loads(self._get(url))

    def release_works(self, mbid: str) -> dict:
        """The release's recordings with the works they perform and those works' relationships."""
        url = (
            f"{_BASE}/release/{mbid}"
            "?inc=recordings+recording-level-rels+work-rels+work-level-rels+artist-rels&fmt=json"
        )
        return json.loads(self._get(url))

    def latin_releases(self, release: dict) -> list[dict]:
        """The Latin-script pseudo-releases that translate or transliterate `release`, English first.

        Only a release whose script is given and is not `Latn` is asked for
        its relations. A pseudo-release qualifies when its script is `Latn`
        and it has the same number of tracks on each medium, so title n of
        one is title n of the other. Among those, the ones in English come
        before the rest, each group in the order MusicBrainz lists them.
        """
        script = (release.get("text-representation") or {}).get("script")
        if not script or script == "Latn":
            return []
        try:
            relations = self.release_relations(release["id"]).get("relations", [])
        except MusicBrainzUnavailable:
            raise
        except MusicBrainzError:
            return []
        counts = _track_counts(release)
        found: dict[str, dict] = {}
        for relation in relations:
            if relation.get("type") != "transl-tracklisting":
                continue
            target = (relation.get("release") or {}).get("id")
            if not target or target == release["id"] or target in found:
                continue
            try:
                candidate = self.release(target)
            except MusicBrainzUnavailable:
                raise
            except MusicBrainzError:
                continue
            if (candidate.get("text-representation") or {}).get("script") == "Latn" and _track_counts(candidate) == counts:
                found[target] = candidate
        return sorted(found.values(), key=lambda r: (r.get("text-representation") or {}).get("language") != "eng")

    def release_group(self, mbid: str) -> dict:
        url = f"{_BASE}/release-group/{mbid}?inc=genres+tags&fmt=json"
        return json.loads(self._get(url))

    def artist_release_groups(self, mbid: str) -> list[dict]:
        """Every release group the artist `mbid` is credited on, a page of 100 at a time."""
        groups: list[dict] = []
        while True:
            url = f"{_BASE}/release-group?artist={mbid}&limit=100&offset={len(groups)}&fmt=json"
            page = json.loads(self._get(url))
            found = page.get("release-groups", [])
            groups.extend(found)
            if not found or len(groups) >= page.get("release-group-count", 0):
                return groups

    def artist(self, mbid: str) -> dict:
        url = f"{_BASE}/artist/{mbid}?inc=aliases+genres&fmt=json"
        return json.loads(self._get(url))

    def search_artists(self, name: str, limit: int = 8) -> list[dict]:
        """The artists MusicBrainz finds for `name` as far as it is typed, best first, by name or by alias.

        The search matches whole words, so the last word typed also stands
        for any word it starts. The answer is never cached: an artist added
        to MusicBrainz since is found by asking again.
        """
        words = [_lucene_escape(word) for word in name.lower().split()]
        if not words:
            return []
        terms = " AND ".join([*words[:-1], f"({words[-1]}* OR {words[-1]})"])
        lucene = f"artist:({terms}) OR alias:({terms})"
        url = f"{_BASE}/artist/?query={quote(lucene, safe='')}&fmt=json&limit={limit}"
        body = self._ask(url)
        return [] if body == _NOT_FOUND else json.loads(body).get("artists", [])

    def search_releases(self, title: str, artist: str | None, various_artists: bool = False) -> dict:
        # No track-count term: a search result counts data tracks and pregap
        # that the files never have, so filtering on it hides enhanced CDs.
        terms = [f"release:({_lucene_escape(title.lower())})"] if title else []
        if various_artists:
            terms.append(f"arid:{VARIOUS_ARTISTS}")
        elif artist:
            terms.append(f"artist:({_lucene_escape(artist.lower())})")
        # MusicBrainz joins bare terms with OR, which lets a common title crowd the artist's own
        # releases out of the 25 ("Weezer (White Album)" found 25 White Albums, none of them Weezer's).
        # The OR search is kept for an artist the files spell unlike MusicBrainz.
        found = self._search(" AND ".join(terms))
        if len(terms) > 1 and not found.get("releases"):
            found = self._search(" ".join(terms))
        return found

    def _search(self, lucene: str) -> dict:
        url = f"{_BASE}/release/?query={quote(lucene, safe='')}&fmt=json&limit=25"
        return json.loads(self._get(url))
