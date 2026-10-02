"""`GET /api/library/<letter>/<artist>/<album>/order`: two tracks that look swapped, by their lengths.

The answer is worked out from the album's files and MusicBrainz's release
for the album's release id, each time the route is called, so a saved swap
reads clean at once. The release is kept by the engine's response cache under
`config.jobs`, so MusicBrainz is asked once and the answer survives a restart.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musiclib import identify, units
from musiclib.cache import Cache
from musiclib.mb import MusicBrainz, MusicBrainzError, MusicBrainzNotFound

from . import library

if TYPE_CHECKING:
    from .server import Config, Handler

#: Seconds a length may be off and still be the same track.
TOLERANCE = 3.0
NO_RELEASE = "Track order not checked: no MusicBrainz release"
NO_FIT = "Track order not checked: the files do not fit the release's track list"
NO_ANSWER = "Track order not checked: MusicBrainz did not answer"


class _Cold(Exception):
    """The cache holds no answer for the request."""


def _cold(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    raise _Cold


class Lookup:
    """The one MusicBrainz client of this process, behind a lock: its rate limit is kept per client.

    A release already in the cache is read without the lock, so it does not
    wait behind a lookup that is asking MusicBrainz.
    """

    def __init__(self, config: Config) -> None:
        cache = Cache(config.jobs / "musicbrainz")
        self._client = MusicBrainz(cache, transport=config.mb_transport)
        # Over the same cache, and unable to reach MusicBrainz: it answers from the cache or says `_Cold`.
        self._cached = MusicBrainz(cache, transport=_cold, sleep=lambda _seconds: None)
        self._lock = threading.Lock()

    def release(self, release_id: str) -> dict[str, Any]:
        try:
            return self._cached.release(release_id)
        except _Cold:
            pass
        with self._lock:
            return self._client.release(release_id)


def _unchecked(reason: str, retry: bool = False) -> dict[str, Any]:
    return {"checked": False, "reason": reason, "retry": retry}


def _off(runs: float, wants: float) -> bool:
    return abs(runs - wants) > TOLERANCE


def flags(folder: Path, pairs: list[units.TrackPair]) -> list[dict[str, Any]]:
    """Each two tracks of one disc that both run more than `TOLERANCE` from their own position's length and within it of the other's.

    A position with no length on MusicBrainz is not compared.
    """
    found = []
    for disc in dict.fromkeys(pair.disc for pair in pairs):
        known = [(pair, identify.mb_length(pair.mb_track)) for pair in pairs if pair.disc == disc]
        known = [(pair, wants) for pair, wants in known if wants is not None]
        for at, (one, one_wants) in enumerate(known):
            for other, other_wants in known[at + 1:]:
                runs_one, runs_other = one.file.length, other.file.length
                if (_off(runs_one, one_wants) and _off(runs_other, other_wants)
                        and not _off(runs_one, other_wants) and not _off(runs_other, one_wants)):
                    found.append({"a": Path(one.file.path).relative_to(folder).as_posix(),
                                  "b": Path(other.file.path).relative_to(folder).as_posix(),
                                  "a_runs": runs_one, "a_wants": one_wants,
                                  "b_runs": runs_other, "b_wants": other_wants})
    return found


def _verdict(lookup: Lookup, folder: Path, unit: units.Unit) -> dict[str, Any]:
    release_id = library.release_id((track.family, track.tags) for track in unit.tracks)
    if release_id is None:
        return _unchecked(NO_RELEASE)
    if unit.unreadable:
        return _unchecked(NO_FIT)
    try:
        release = lookup.release(release_id)
    except MusicBrainzNotFound:
        return _unchecked(NO_RELEASE)
    except (MusicBrainzError, ValueError, OSError):
        return _unchecked(NO_ANSWER, retry=True)
    pairs = units.pair(unit, release)
    if pairs is None:
        return _unchecked(NO_FIT)
    return {"checked": True, "flags": flags(folder, pairs)}


def show(request: Handler, match: re.Match[str], config: Config) -> None:
    folder = library.open_folder(config, *match.group(1, 2, 3))
    unit = units.unit_at(folder, library.library_root(config))
    request.send_json(200, _verdict(request.server.release_lookup, folder, unit))
