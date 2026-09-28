"""Which MusicBrainz release an album unit is, and how sure the engine is.

An album unit with a release ID tagged on every file is looked up directly
and never searched. Anything else is searched by album title, album artist
and track count, and the candidates ranked so the top one can be trusted
automatically only when nothing about it is in doubt. A unit that cannot be
planned at all - because a person has to look at it, because a file could not
be read, or because MusicBrainz itself is down - comes back with a status
instead of asking anything. `release_ref` and `chosen` let an owner name the
release directly, by URL or bare MBID.
"""

from __future__ import annotations

import calendar
import datetime
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

from musiclib import acoustid, genres, mapping
from musiclib.mb import MusicBrainz, MusicBrainzError, MusicBrainzUnavailable
from musiclib.units import Unit

# Track and disc number have no place in mapping.PICARD (their shape differs
# per format, so plan_tags builds them directly instead); everything else
# this module reads off a file's own tags is already there under its neutral
# name, so it is read from there rather than re-tabulated here.
_TRACK_NUMBER_KEY = {"id3": "TRCK", "vorbis": "tracknumber", "mp4": "trkn", "asf": "WM/TrackNumber"}
_DISC_NUMBER_KEY = {"id3": "TPOS", "vorbis": "discnumber", "mp4": "disk", "asf": "WM/PartOfSet"}

_CD_FOLDER = re.compile(r"^CD(\d+)$")
_LEADING_NUMBER = re.compile(r"\d+")
_WITHIN = 3.0  # seconds: the per-track duration tolerance for a tagged or searched match.

_MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_MB_HOSTS = {"musicbrainz.org", "beta.musicbrainz.org"}


@dataclass
class Candidate:
    """One release under consideration: what it fetched to, and how well it fits."""

    release_id: str
    release: dict | None
    matches_counts: bool
    duration_diff: float | None
    year: str | None


@dataclass
class Identification:
    """The outcome of trying to place an album unit: a status, why, and the candidates behind it."""

    status: str
    reason: str | None
    candidates: list


# --- reading what the files already say ------------------------------------


def _first(track, key_map: dict[str, str | None]) -> str | None:
    key = key_map.get(track.family)
    if not key:
        return None
    values = track.tags.get(key)
    return values[0] if values else None


def _release_id(track) -> str | None:
    return _first(track, mapping.PICARD["release id"])


def _leading_number(track, key_map: dict[str, str]) -> int | None:
    value = _first(track, key_map)
    if value is None:
        return None
    found = _LEADING_NUMBER.search(value)
    return int(found.group()) if found else None


def _consistent_release_id(tracks: list) -> str | None:
    if not tracks:
        return None
    ids = [_release_id(t) for t in tracks]
    first = ids[0]
    if first is None:
        return None
    return first if all(i == first for i in ids) else None


def _folder_medium(track, album_path: Path) -> int | None:
    rel = Path(track.path).relative_to(album_path)
    if len(rel.parts) == 2:
        match = _CD_FOLDER.match(rel.parts[0])
        if match:
            return int(match.group(1))
    return None


def _sort_key(track):
    number = _leading_number(track, _TRACK_NUMBER_KEY)
    filename = Path(track.path).name
    # A track-number tag sorts before its filename fallback so a rip named
    # out of order still pairs with the right recording.
    return (0, number, filename) if number is not None else (1, 0, filename)


def _group_media(unit: Unit) -> list[list]:
    """The unit's tracks split into media, in medium order: `CDn` folder, then disc number, then one medium."""
    folder_keys = [_folder_medium(t, unit.path) for t in unit.tracks]
    if unit.tracks and all(k is not None for k in folder_keys):
        keys = folder_keys
    else:
        disc_keys = [_leading_number(t, _DISC_NUMBER_KEY) for t in unit.tracks]
        keys = disc_keys if unit.tracks and all(k is not None for k in disc_keys) else [1] * len(unit.tracks)

    grouped: dict[int, list] = {}
    for key, track in zip(keys, unit.tracks):
        grouped.setdefault(key, []).append(track)
    return [sorted(grouped[key], key=_sort_key) for key in sorted(grouped)]


def _album_value(track) -> str | None:
    return _first(track, mapping.PICARD["album"])


def _album_artist_value(track) -> str | None:
    return _first(track, mapping.PICARD["albumartist"]) or _first(track, mapping.PICARD["artist"])


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


def _track_seconds(mb_track: dict) -> float:
    length_ms = mb_track.get("length")
    if length_ms is None:
        length_ms = mb_track.get("recording", {}).get("length")
    return (length_ms or 0) / 1000.0


def _compare(unit: Unit, release: dict) -> tuple[bool, list[float] | None]:
    """Whether `release`'s medium and per-medium track counts match the unit's files.

    Returns the counts match and, only when they do, the per-track absolute
    duration differences in seconds, pairing each medium's files with that
    medium's recordings in order.
    """
    media = _group_media(unit)
    release_media = release.get("media", [])
    if len(media) != len(release_media):
        return False, None
    for tracks, medium in zip(media, release_media):
        if len(tracks) != len(medium.get("tracks", [])):
            return False, None
    diffs = []
    for tracks, medium in zip(media, release_media):
        mb_tracks = sorted(medium.get("tracks", []), key=lambda t: t.get("position", 0))
        for track, mb_track in zip(tracks, mb_tracks):
            diffs.append(abs(track.length - _track_seconds(mb_track)))
    return True, diffs


def _year(release: dict) -> str | None:
    date = release.get("date")
    return date[:4] if date else None


def _max_diff(unit: Unit, release: dict) -> float:
    _, diffs = _compare(unit, release)
    return max(diffs) if diffs else 0.0


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


def _oldest_key(candidate: Candidate):
    return (_date_sort_value(candidate.release.get("date")), candidate.release_id)


# --- the soundtrack safety net ----------------------------------------------


def _soundtrack_settled(release_group: dict, release: dict, unit: Unit, owner_input, incoming) -> bool:
    file_genres = _file_genres(unit)
    composer = genres.composer(release)
    owner = owner_input or {}
    return (
        genres.tag_says_game(release_group)
        or genres.files_say(file_genres, "video game music")
        or genres.files_say(file_genres, "soundtrack")
        or genres.incoming_says_game(incoming)
        or genres.composer_remembered_as(composer, owner, "video game music")
        or genres.composer_remembered_as(composer, owner, "not game music")
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
    if "Soundtrack" not in group.get("secondary-types", []):
        return None
    if _soundtrack_settled(group, candidate.release, unit, owner_input, incoming):
        return None
    return Identification("review", "unsettled soundtrack", candidates)


# --- search and ranking ------------------------------------------------------


def _rank_key(candidate: Candidate):
    return (
        0 if candidate.matches_counts else 1,
        candidate.duration_diff if candidate.duration_diff is not None else float("inf"),
        candidate.release_id,
    )


def _search(
    unit: Unit, client: MusicBrainz, acoustid_client, owner_input, incoming,
    env: Mapping[str, str], which: Callable[[str], str | None],
) -> Identification:
    media = _group_media(unit)
    first_track = unit.tracks[0]
    # A file with no album or artist tag at all still gets searched, on
    # whatever it does have, rather than crash the lucene query builder.
    album = _album_value(first_track) or ""
    artist = _album_artist_value(first_track) or ""
    tracks = sum(len(medium) for medium in media)
    counts = [len(medium) for medium in media]

    try:
        found = client.search_releases(album, artist, tracks)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])

    candidates = []
    for entry in found.get("releases", []):
        entry_counts = [medium.get("track-count") for medium in entry.get("media", [])]
        if entry_counts != counts:
            candidates.append(Candidate(entry["id"], None, False, None, None))
            continue
        try:
            release = client.release(entry["id"])
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", [])
        matches, diffs = _compare(unit, release)
        candidates.append(Candidate(entry["id"], release, matches, sum(diffs) if diffs else 0.0, _year(release)))

    candidates.sort(key=_rank_key)

    top = candidates[0] if candidates else None
    if top is None or not top.matches_counts:
        return _fingerprint_fallback(unit, client, candidates, acoustid_client, env, which)

    top_is_full = _max_diff(unit, top.release) <= _WITHIN
    chosen = top
    ordered = candidates
    status = "review"

    if top_is_full:
        status = "auto"
        full = [top] + [
            other for other in candidates[1:]
            if other.matches_counts and other.release is not None and _max_diff(unit, other.release) <= _WITHIN
        ]
        if any(other.year != top.year for other in full[1:]):
            # Several full editions and not all the same year: the top of
            # the ranking is whichever fits the files best, not necessarily
            # the original pressing, so the earliest edition wins instead.
            chosen = min(full, key=_oldest_key)
            ordered = [chosen] + [c for c in candidates if c is not chosen]

    hold = _soundtrack_hold(status, chosen, ordered, unit, client, owner_input, incoming)
    return hold if hold is not None else Identification(status, None, ordered)


# --- falling back to fingerprints when no search count matches --------------


def _fingerprint_fallback(
    unit: Unit, client: MusicBrainz, search_candidates: list,
    acoustid_client, env: Mapping[str, str], which: Callable[[str], str | None],
) -> Identification:
    reason = acoustid.unavailable(env, which)
    if reason is not None:
        return Identification("unidentified", reason, search_candidates)
    if acoustid_client is None:
        return Identification("unidentified", "no match", search_candidates)

    # Every recording any track's fingerprint matches, released on any
    # release: a laundered rip can have a wrong or missing tag on every
    # file, so nothing here trusts the tags at all.
    release_ids: dict[str, None] = {}
    for track in unit.tracks:
        try:
            duration, fingerprint = acoustid_client.fingerprint(Path(track.path))
            recordings = acoustid_client.lookup(duration, fingerprint)
        except acoustid.AcoustIDError:
            return Identification("unidentified", "fingerprint failed", search_candidates)
        for recording_id in recordings:
            try:
                found = client.recording_releases(recording_id)
            except MusicBrainzUnavailable:
                return Identification("unidentified", "musicbrainz unavailable", search_candidates)
            except MusicBrainzError:
                continue  # a recording MusicBrainz no longer has is skipped
            for release_id in found:
                release_ids.setdefault(release_id, None)

    fp_candidates = []
    for release_id in release_ids:
        try:
            release = client.release(release_id)
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", search_candidates)
        except MusicBrainzError:
            continue
        matches, diffs = _compare(unit, release)
        fp_candidates.append(
            Candidate(release_id, release, matches, sum(diffs) if diffs else None, _year(release))
        )

    if not fp_candidates:
        return Identification("unidentified", "no match", search_candidates)

    fp_candidates.sort(key=_rank_key)
    # A fingerprint match is never certain enough to skip a person: it never
    # comes from the files' own tags, only from what they sound like.
    return Identification("review", None, fp_candidates)


# --- the entry point ---------------------------------------------------------


def identify(
    unit: Unit, mb: MusicBrainz, acoustid=None, owner_input=None, incoming=None,
    env: Mapping[str, str] = os.environ, which: Callable[[str], str | None] = shutil.which,
) -> Identification:
    if unit.status:
        return Identification(unit.status, unit.reason, [])
    if unit.unreadable:
        return Identification("unidentified", "unreadable files", [])

    tagged_id = _consistent_release_id(unit.tracks)
    if tagged_id is not None:
        try:
            release = mb.release(tagged_id)
        except MusicBrainzUnavailable:
            return Identification("unidentified", "musicbrainz unavailable", [])
        except MusicBrainzError:
            # A tagged ID MusicBrainz no longer knows is no ID at all.
            release = None
        if release is not None:
            matches, diffs = _compare(unit, release)
            if matches:
                candidate = Candidate(tagged_id, release, True, sum(diffs), _year(release))
                status = "certain" if all(d <= _WITHIN for d in diffs) else "review"
                hold = _soundtrack_hold(status, candidate, [candidate], unit, mb, owner_input, incoming)
                return hold if hold is not None else Identification(status, None, [candidate])

    return _search(unit, mb, acoustid, owner_input, incoming, env, which)


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


def chosen(unit: Unit, mb: MusicBrainz, value: str) -> Identification:
    """Fetch and plan against the release the owner named, always for review."""
    release_id = release_ref(value)
    try:
        release = mb.release(release_id)
    except MusicBrainzUnavailable:
        return Identification("unidentified", "musicbrainz unavailable", [])
    matches, diffs = _compare(unit, release)
    candidate = Candidate(release_id, release, matches, sum(diffs) if diffs else None, _year(release))
    # An owner's own pick is still reviewed before it is written, never auto
    # or certain: the album might still be the wrong one.
    return Identification("review", None, [candidate])
