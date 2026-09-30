"""Which MusicBrainz release an album unit is, and how sure the engine is.

An album unit with a release ID tagged on every file is looked up directly
and never searched. Anything else is searched by album title and album
artist, and the candidates ranked so the top one can be trusted automatically
only when nothing about it is in doubt. A unit that cannot be planned at all -
because a person has to look at it, because a file could not be read, or
because MusicBrainz itself is down - comes back with a status
instead of asking anything. `release_ref` and `chosen` let an owner name the
release directly, by URL or bare MBID.
"""

from __future__ import annotations

import calendar
import datetime
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

from musiclib import acoustid, artists, genres, images, mapping, titles
from musiclib.caa import CoverArt, CoverArtError
from musiclib.mb import MusicBrainz, MusicBrainzError, MusicBrainzUnavailable
from musiclib.units import TrackPair, Unit, first_value, pair, position_key

_MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_MB_HOSTS = {"musicbrainz.org", "beta.musicbrainz.org"}
_MIN_TRACK_SHARE = 0.6


@dataclass
class Candidate:
    """One release under consideration: what it fetched to, and how well it fits."""

    release_id: str
    release: dict | None
    matches_counts: bool
    duration_diff: float | None
    year: str | None
    pairs: list[TrackPair] | None = None
    artist_agrees: bool = False
    latin: list[dict] | None = None
    listing: dict | None = None


@dataclass
class Identification:
    """The outcome of trying to place an album unit: a status, why, and the candidates behind it."""

    status: str
    reason: str | None
    candidates: list


# --- reading what the files already say ------------------------------------


def _release_id(track) -> str | None:
    return first_value(track, mapping.PICARD["release id"])


def _consistent_release_id(tracks: list) -> str | None:
    if not tracks:
        return None
    ids = [_release_id(t) for t in tracks]
    first = ids[0]
    if first is None:
        return None
    return first if all(i == first for i in ids) else None


def _album_value(track) -> str | None:
    return first_value(track, mapping.PICARD["album"])


def _file_genres(unit: Unit) -> list[str]:
    """Every track's genres, unioned in first-seen order.

    A laundered rip can carry the genre on any one file and not the rest
    (see the soundtrack safety net below), so reading only the first track
    would leave an album unsettled that a later file already settles.
    """
    seen: dict[str, None] = {}
    for track in unit.tracks:
        key = mapping.PICARD["genre"].get(track.family)
        if not key:
            continue
        for value in track.tags.get(key, []):
            seen.setdefault(value, None)
    return list(seen)


# --- comparing files against a fetched release ------------------------------


def _mb_length(mb_track: dict) -> float | None:
    length_ms = mb_track.get("length")
    if length_ms is None:
        length_ms = mb_track.get("recording", {}).get("length")
    return None if length_ms is None else length_ms / 1000.0


def _latin_titles(p: TrackPair, latin: list[dict]) -> list[str]:
    """The title at `p`'s place on each Latin pseudo-release.

    `pseudo["media"][p.medium - 1]` is safe because `MusicBrainz.latin_releases`
    keeps only pseudo-releases with the same track count on each medium.
    """
    titles_ = []
    for pseudo in latin:
        tracks = pseudo["media"][p.medium - 1]["tracks"]
        if 0 < p.position <= len(tracks):
            titles_.append(tracks[p.position - 1]["title"])
    return titles_


def _pair_fits(p: TrackPair, edited: dict, latin: list[dict] | None = None) -> bool:
    wanted = [p.mb_track["title"], *edited.get(position_key(p), {}).get("title", [])[:1],
              *_latin_titles(p, latin or [])]
    title = titles.file_title(p.file)
    mb_length = _mb_length(p.mb_track)
    return any(titles.pair_passes(title, p.file.length, w, mb_length) for w in wanted)


def _failing_pairs(candidate: Candidate, owner_input: dict | None) -> int:
    edited = ((owner_input or {}).get("edits") or {}).get(candidate.release_id, {})
    return sum(not _pair_fits(p, edited, candidate.latin) for p in candidate.pairs or [])


def failing_tracks(candidate: Candidate, owner_input: dict | None) -> int | None:
    return None if candidate.pairs is None else _failing_pairs(candidate, owner_input)


def _fits(candidate: Candidate, owner_input: dict | None = None) -> bool:
    return candidate.pairs is not None and _failing_pairs(candidate, owner_input) == 0


def _candidate(release_id: str, release: dict, unit: Unit, client: MusicBrainz) -> Candidate:
    """`release` paired against the unit's files, with the seconds the pairs are off by in total.

    A title of the files may also agree with the same track on a Latin
    pseudo-release of `release`, which `client` looks up.

    `duration_diff` is `None` when the medium or per-medium track counts do not
    match, and `0.0` when they do but MusicBrainz has no lengths to compare.
    """
    pairs = pair(unit, release)
    diff = None
    if pairs is not None:
        diff = float(sum(abs(p.file.length - length) for p in pairs if (length := _mb_length(p.mb_track)) is not None))
    latin = client.latin_releases(release) if pairs is not None else []
    return Candidate(release_id, release, pairs is not None, diff, _year(release), pairs, latin=latin)


def _year(release: dict) -> str | None:
    date = release.get("date")
    return date[:4] if date else None


def _date_sort_value(date: str | None) -> tuple:
    """A sortable value for a release date: earliest first, undated last.

    A year or a year-month is the last day it could still mean, so a partial
    date never looks older than a full date that actually falls within it.
    A date that does not parse as a real calendar day counts as undated,
    since nothing sorts a value that isn't one.
    """
    if not date:
        return (1, 0, 0, 0)
    parts = date.split("-")
    try:
        year = int(parts[0])
        if len(parts) == 1:
            month, day = 12, 31
        elif len(parts) == 2:
            month = int(parts[1])
            day = calendar.monthrange(year, month)[1]
        elif len(parts) == 3:
            month, day = int(parts[1]), int(parts[2])
            datetime.date(year, month, day)  # raises on a day that doesn't exist
        else:
            raise ValueError(date)
    except (ValueError, IndexError):
        return (1, 0, 0, 0)
    return (0, year, month, day)


# --- the soundtrack safety net ----------------------------------------------

#: Why a Soundtrack-type album is held: the type does not say game or film,
#: and `soundtrack` on the files is only what an earlier job wrote from it.
SOUNDTRACK_CHOICE = "soundtrack choice"


def awaits_soundtrack_choice(release_group: dict, release: dict, unit: Unit, owner_input, incoming) -> bool:
    """Whether `release_group` is Soundtrack-type and nothing yet says game or film for this album.

    A game tag, `video game music` on the files, an incoming game genre or
    the owner's choice for this release settles it; `soundtrack` on the
    files does not.
    """
    if "Soundtrack" not in release_group.get("secondary-types", []):
        return False
    file_genres = _file_genres(unit)
    return not (
        genres.tag_says_game(release_group)
        or genres.files_say(file_genres, genres.VIDEO_GAME_MUSIC)
        or genres.incoming_says_game(incoming)
        or genres.owner_choice(owner_input or {}, release.get("id")) is not None
    )


def _soundtrack_hold(
    status: str, candidate: Candidate, candidates: list, unit: Unit, client: MusicBrainz, owner_input, incoming
) -> Identification | None:
    """`None` to keep `status`, or the `review` it must fall back to.

    Only `certain` and `auto` are ever held: a Soundtrack release group could
    still turn out to be a game score, and guessing wrong before a person
    looks would file a game's music next to film scores.
    """
    if status not in ("certain", "auto"):
        return None
    group_id = candidate.release.get("release-group", {}).get("id")
    if not group_id:
        return None
    try:
        group = client.release_group(group_id)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])
    if not awaits_soundtrack_choice(group, candidate.release, unit, owner_input, incoming):
        return None
    return Identification("review", SOUNDTRACK_CHOICE, candidates)


# --- search and ranking ------------------------------------------------------


def _rank_key(candidate: Candidate, owner_input: dict | None = None):
    return (
        0 if candidate.matches_counts else 1,
        _failing_pairs(candidate, owner_input),
        0 if candidate.artist_agrees else 1,
        candidate.duration_diff if candidate.duration_diff is not None else float("inf"),
        candidate.release_id,
    )


def _judge_artists(candidates: list, unit: Unit, client: MusicBrainz) -> None:
    """Record on each candidate that paired with the files whether its credit agrees with their artist."""
    for candidate in candidates:
        if candidate.matches_counts:
            candidate.artist_agrees = artists.agrees(unit, candidate.release, client)


_COVER_SHOWN_WITHIN = 10


def _showing_cover(fitting: list, caa: CoverArt | None, local_cover: bytes | None) -> set[str]:
    """The ids of the `fitting` candidates whose front looks like `local_cover`.

    Nothing is fetched unless two or more fit and the folder has a cover that
    is an image. A candidate whose front, listing or thumbnail cannot be had
    does not show it.
    """
    local = images.average_hash_or_none(local_cover) if local_cover is not None else None
    if caa is None or local is None or len(fitting) < 2:
        return set()
    shown = set()
    for candidate in fitting:
        try:
            url = images.front_thumbnail_url(caa.images(candidate.release_id))
            thumbnail = caa.download(url) if url else None
        except CoverArtError:
            continue
        theirs = images.average_hash_or_none(thumbnail) if thumbnail is not None else None
        if theirs is not None and images.hash_distance(local, theirs) <= _COVER_SHOWN_WITHIN:
            shown.add(candidate.release_id)
    return shown


def _choose_fitting(candidates: list, owner_input, caa: CoverArt | None = None,
                    local_cover: bytes | None = None) -> Candidate:
    """Among the candidates that fit: those showing the folder's cover, then those whose artist agrees, then the Official release, then the oldest, then the best ranked."""
    fitting = [c for c in candidates if _fits(c, owner_input)]
    shown = _showing_cover(fitting, caa, local_cover)
    return min(fitting, key=lambda c: (
        c.release_id not in shown, not c.artist_agrees, c.release.get("status") != "Official",
        _date_sort_value(c.release.get("date")),
    ))


def _settle(candidates: list, unit: Unit, client: MusicBrainz, owner_input, incoming,
            caa: CoverArt | None = None, local_cover: bytes | None = None) -> Identification:
    """`candidates` is non-empty, ranked and judged on artist.

    An artist that does not agree and the soundtrack hold can each turn an `auto` into a `review`.
    """
    if not _fits(candidates[0], owner_input):
        return Identification("review", None, candidates)
    chosen = _choose_fitting(candidates, owner_input, caa, local_cover)
    ordered = [chosen] + [c for c in candidates if c is not chosen]
    if not chosen.artist_agrees:
        # Files with no artist at all have nothing to disagree with.
        reason = "artist does not agree" if artists.files_artist(unit) is not None else None
        return Identification("review", reason, ordered)
    hold = _soundtrack_hold("auto", chosen, ordered, unit, client, owner_input, incoming)
    return hold if hold is not None else Identification("auto", None, ordered)


def _listed_too_short(entry: dict, files: int) -> bool:
    # A result's listed counts include data tracks and pregap, so a count above the
    # files' proves nothing; only a total below does.
    listed = [medium.get("track-count") for medium in entry.get("media", [])]
    return sum(have or 0 for have in listed) < files


def _various_artists(unit: Unit) -> bool:
    artists = {a for t in unit.tracks if (a := first_value(t, mapping.PICARD["artist"])) is not None}
    album_artists = (first_value(t, mapping.PICARD["albumartist"]) for t in unit.tracks)
    return len(artists) > 1 and all(a is None or a.strip().casefold() == "various artists" for a in album_artists)


def _search(
    unit: Unit, client: MusicBrainz, acoustid_client, owner_input, incoming,
    env: Mapping[str, str], which: Callable[[str], str | None],
    caa: CoverArt | None = None, local_cover: bytes | None = None,
) -> Identification:
    first_track = unit.tracks[0]
    album = _album_value(first_track) or ""
    artist = artists.track_artist(first_track) or ""

    various = _various_artists(unit)
    if not album and (various or not artist):
        return _fingerprint_fallback(unit, client, [], acoustid_client, owner_input, incoming, env, which,
                                     caa, local_cover)

    try:
        found = client.search_releases(album, artist or None, various)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])

    candidates = []
    for entry in found.get("releases", []):
        if _listed_too_short(entry, len(unit.tracks)):
            candidates.append(Candidate(entry["id"], None, False, None, None, listing=entry))
            continue
        try:
            release = client.release(entry["id"])
            candidates.append(_candidate(entry["id"], release, unit, client))
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", [])

    try:
        _judge_artists(candidates, unit, client)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])
    candidates.sort(key=lambda c: _rank_key(c, owner_input))

    top = candidates[0] if candidates else None
    if top is None or not top.matches_counts:
        return _fingerprint_fallback(
            unit, client, candidates, acoustid_client, owner_input, incoming, env, which, caa, local_cover
        )

    return _settle(candidates, unit, client, owner_input, incoming, caa, local_cover)


# --- falling back to fingerprints when no search count matches --------------


def _fingerprint_fallback(
    unit: Unit, client: MusicBrainz, search_candidates: list,
    acoustid_client, owner_input, incoming, env: Mapping[str, str], which: Callable[[str], str | None],
    caa: CoverArt | None = None, local_cover: bytes | None = None,
) -> Identification:
    reason = acoustid.unavailable(env, which)
    if reason is not None:
        return Identification("unidentified", reason, search_candidates)
    if acoustid_client is None:
        return Identification("unidentified", "no match", search_candidates)

    # A laundered rip can have a wrong or missing tag on every file, so
    # nothing here trusts the tags.
    votes: Counter[str] = Counter()
    for track in unit.tracks:
        try:
            duration, fingerprint = acoustid_client.fingerprint(Path(track.path))
            releases = acoustid_client.lookup(duration, fingerprint)
        except acoustid.AcoustIDError:
            return Identification("unidentified", "fingerprint failed", search_candidates)
        votes.update(set(releases))

    fp_candidates = []
    for release_id, count in votes.items():
        if count / len(unit.tracks) <= _MIN_TRACK_SHARE:
            continue
        try:
            release = client.release(release_id)
            fp_candidates.append(_candidate(release_id, release, unit, client))
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", search_candidates)
        except MusicBrainzError:
            continue

    if not fp_candidates:
        return Identification("unidentified", "no match", search_candidates)

    try:
        _judge_artists(fp_candidates, unit, client)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", search_candidates)
    fp_candidates.sort(key=lambda c: _rank_key(c, owner_input))
    return _settle(fp_candidates, unit, client, owner_input, incoming, caa, local_cover)


# --- the entry point ---------------------------------------------------------


def identify(
    unit: Unit, mb: MusicBrainz, acoustid=None, owner_input=None, incoming=None,
    env: Mapping[str, str] = os.environ, which: Callable[[str], str | None] = shutil.which,
    caa: CoverArt | None = None, local_cover: bytes | None = None,
) -> Identification:
    if unit.status:
        return Identification(unit.status, unit.reason, [])
    if unit.unreadable:
        return Identification("unidentified", "unreadable files", [])

    tagged_id = _consistent_release_id(unit.tracks)
    if tagged_id is not None:
        try:
            release = mb.release(tagged_id)
            candidate = _candidate(tagged_id, release, unit, mb)
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", [])
        except MusicBrainzError:
            # A tagged ID MusicBrainz no longer knows is no ID at all.
            candidate = None
        if candidate is not None:
            if candidate.matches_counts:
                status = "certain" if _fits(candidate, owner_input) else "review"
                hold = _soundtrack_hold(status, candidate, [candidate], unit, mb, owner_input, incoming)
                return hold if hold is not None else Identification(status, None, [candidate])

    return _search(unit, mb, acoustid, owner_input, incoming, env, which, caa, local_cover)


# --- a release named directly ------------------------------------------------


def release_ref(value: str) -> str:
    """The MBID `value` names, from a MusicBrainz release URL or a bare MBID.

    Anything else - a release group, a recording, plain text - is refused
    with the value named, so the owner sees which paste was wrong.
    """
    stripped = value.strip()
    if _MBID.fullmatch(stripped):
        return stripped.lower()

    parts = urlsplit(stripped)
    if parts.scheme in ("http", "https") and parts.netloc.lower() in _MB_HOSTS:
        segments = parts.path.strip("/").split("/")
        if len(segments) >= 2 and segments[0] == "release" and _MBID.fullmatch(segments[1]):
            return segments[1].lower()

    raise ValueError(f"not a MusicBrainz release URL or MBID: {value}")


def chosen(unit: Unit, mb: MusicBrainz, value: str, owner_input=None, incoming=None) -> Identification:
    """Fetch and plan against the release the owner named, always for review.

    A Soundtrack-type release nothing has settled is held for the choice,
    the same as one the engine picked.
    """
    release_id = release_ref(value)
    try:
        release = mb.release(release_id)
        candidate = _candidate(release_id, release, unit, mb)
        _judge_artists([candidate], unit, mb)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])
    hold = _soundtrack_hold("auto", candidate, [candidate], unit, mb, owner_input, incoming)
    if hold is not None:
        return hold
    # An owner's own pick is still reviewed before it is written, never auto
    # or certain: the album might still be the wrong one.
    return Identification("review", None, [candidate])
