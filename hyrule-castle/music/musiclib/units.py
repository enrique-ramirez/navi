"""Album units: what the engine finds under the root, and when it stops.

An album unit is one folder under `Letter/Artist/`, together with its `CDn`
subfolders. When its files disagree on the album tag, the folder holds more
than one album - a single filed together with the album it came from - and
the engine marks it `needs a person` rather than plan it as one release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from musiclib import files, mapping, walk


@dataclass
class Unit:
    """One album folder: its tracks, what could not be read, and everything else."""

    path: Path
    rel: str
    tracks: list[files.Track]
    unreadable: list[tuple[str, str]]
    others: list[str]
    status: str | None
    reason: str | None


TRACK_NUMBER_KEY = {"id3": "TRCK", "vorbis": "tracknumber", "mp4": "trkn", "asf": "WM/TrackNumber"}
DISC_NUMBER_KEY = {"id3": "TPOS", "vorbis": "discnumber", "mp4": "disk", "asf": "WM/PartOfSet"}
TRACK_TOTAL_KEY = {"vorbis": "tracktotal"}
DISC_TOTAL_KEY = {"vorbis": "disctotal"}

_DISC_FOLDER_LEADING = re.compile(r"^(?:cd|disc|disk)\s*(\d+)(?:[\s_.:-].*)?$", re.IGNORECASE)
# A disc marker at the end of a folder name counts only inside brackets or after
# ` - `; a bare trailing `Bonus CD 2` names a folder of its own.
_DISC_FOLDER_TRAILING = re.compile(
    r"(?:[\[(]\s*(?:cd|disc|disk)\s*(\d+)\s*[\])]|\s-\s+(?:cd|disc|disk)\s*(\d+))$", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"\d+")


def disc_number(folder_name: str) -> int | None:
    """The disc a folder name marks (`CD2`, `Album [Disc 2]`), or `None` for a folder that is not a disc folder."""
    match = _DISC_FOLDER_LEADING.match(folder_name)
    if match:
        return int(match.group(1))
    match = _DISC_FOLDER_TRAILING.search(folder_name)
    if match:
        return int(match.group(1) or match.group(2))
    return None


@dataclass(frozen=True)
class TrackPair:
    """One file matched to one recording of a release.

    `medium` and `position` are 1-based into `release["media"]` and that
    medium's `tracks`, the way `mapping.plan_tags` takes them; a pregap is
    position 0. `number`, `total`, `disc` and `discs` are what gets written:
    audio tracks only, and media counted without the ones left with none.
    """

    medium: int
    position: int
    file: files.Track
    mb_track: dict
    number: int
    total: int
    disc: int
    discs: int


def position_key(pair: TrackPair) -> str:
    """`"<medium>-<position>"`, the key that names a planned file in memory, decisions and the page."""
    return f"{pair.medium}-{pair.position}"


@dataclass(frozen=True)
class CountedMedium:
    index: int
    tracks: list[tuple[int, dict]]
    pregap: dict | None


def first_value(track: files.Track, key_map: dict[str, str | None]) -> str | None:
    key = key_map.get(track.family)
    if not key:
        return None
    values = track.tags.get(key)
    return values[0] if values else None


def _leading_number(track: files.Track, key_map: dict[str, str]) -> int | None:
    value = first_value(track, key_map)
    if value is None:
        return None
    found = _LEADING_NUMBER.search(value)
    return int(found.group()) if found else None


def disc_marker_stem(folder_name: str) -> str | None:
    """The name before a trailing disc marker, or None where the name has no such marker."""
    match = _DISC_FOLDER_TRAILING.search(folder_name)
    return folder_name[:match.start()].strip().casefold() if match else None


def _folder_medium(track: files.Track, album_path: Path) -> int | None:
    rel = Path(track.path).relative_to(album_path)
    if len(rel.parts) == 2:
        return disc_number(rel.parts[0])
    return None


def filename_number(filename: str) -> int | None:
    leading = _LEADING_NUMBER.match(filename)
    return int(leading.group()) if leading else None


def _sort_key(track: files.Track):
    number = _leading_number(track, TRACK_NUMBER_KEY)
    filename = Path(track.path).name
    # A track-number tag sorts before its filename fallback so a rip named
    # out of order still pairs with the right recording.
    if number is not None:
        return (0, number, filename)
    leading = filename_number(filename)
    return (1, leading, filename) if leading is not None else (2, 0, filename)


def group_media(unit: Unit) -> list[list[files.Track]]:
    """The unit's tracks split into media, in medium order: `CDn` folder, then disc number, then one medium."""
    folder_keys = [_folder_medium(t, unit.path) for t in unit.tracks]
    if unit.tracks and all(k is not None for k in folder_keys):
        keys = folder_keys
    else:
        disc_keys = [_leading_number(t, DISC_NUMBER_KEY) for t in unit.tracks]
        keys = disc_keys if unit.tracks and all(k is not None for k in disc_keys) else [1] * len(unit.tracks)

    grouped: dict[int, list[files.Track]] = {}
    for key, track in zip(keys, unit.tracks):
        grouped.setdefault(key, []).append(track)
    return [sorted(grouped[key], key=_sort_key) for key in sorted(grouped)]


def counted_media(release: dict) -> list[CountedMedium]:
    """The release's media that hold audio, in order, each with its audio tracks as `(position, track)` in track order."""
    counted = []
    for index, medium in enumerate(release.get("media", []), start=1):
        tracks = medium.get("tracks", [])
        audio = [(position, track) for position, track in sorted(enumerate(tracks, start=1), key=lambda t: t[1].get("position", 0))
                 if track.get("recording", {}).get("video") is not True]
        if audio:
            counted.append(CountedMedium(index, audio, medium.get("pregap")))
    return counted


def _unlabelled(unit: Unit) -> bool:
    if any(_folder_medium(t, unit.path) is not None for t in unit.tracks):
        return False
    return all(_leading_number(t, DISC_NUMBER_KEY) is None for t in unit.tracks)


def _cut(unit: Unit, counted: list[CountedMedium]) -> list[list[files.Track]] | None:
    """The unit's files split by the counted media, or `None` when the counts do not fit."""
    media = group_media(unit)
    if len(media) == len(counted):
        return media
    if len(media) == 1 and _unlabelled(unit) and len(media[0]) == sum(len(m.tracks) for m in counted):
        cuts, start = [], 0
        for medium in counted:
            cuts.append(media[0][start:start + len(medium.tracks)])
            start += len(medium.tracks)
        return cuts
    return None


def _with_pregap(medium: CountedMedium, file_count: int) -> list[tuple[int, dict]]:
    if medium.pregap is not None and file_count == len(medium.tracks) + 1:
        return [(0, medium.pregap), *medium.tracks]
    return list(medium.tracks)


def pair(unit: Unit, release: dict) -> list[TrackPair] | None:
    """Every file of `unit` paired with its recording on `release`, or `None` when the counts do not fit.

    Each medium's files, in track order, go with that medium's audio
    recordings in order. A medium with a pregap and one file more than it has
    tracks takes the first file as the pregap. Files that say nothing about
    media are cut across the media in order.
    """
    counted = counted_media(release)
    media = _cut(unit, counted)
    if media is None:
        return None
    pairs = []
    for disc, (tracks, medium) in enumerate(zip(media, counted), start=1):
        mb_tracks = _with_pregap(medium, len(tracks))
        if len(tracks) != len(mb_tracks):
            return None
        first = 0 if mb_tracks[0][0] == 0 else 1
        for number, (track, (position, mb_track)) in enumerate(zip(tracks, mb_tracks), start=first):
            pairs.append(TrackPair(medium.index, position, track, mb_track, number, len(medium.tracks), disc, len(counted)))
    return pairs


def _claimed_number(track: files.Track) -> int | None:
    """The position a file says it holds: its track number tag, else its filename's leading number."""
    number = _leading_number(track, TRACK_NUMBER_KEY)
    return number if number is not None else filename_number(Path(track.path).name)


def missing_positions(unit: Unit, release: dict, unreadable: int) -> tuple[int, list[int]] | None:
    """`(medium position in counted_media, missing track numbers)` where the gap can be told, else `None`.

    `unit` holds the readable files only and `unreadable` is how many files
    were left out. The gap is told when exactly one medium of `release` has
    `unreadable` more tracks than files, every other medium has as many, and
    no file's claimed position is out of range or claimed twice. The missing
    numbers are the ones no file claims.
    """
    counted = counted_media(release)
    media = group_media(unit)
    if not unreadable or len(media) != len(counted):
        return None
    short = [(index, medium) for index, (medium, tracks) in enumerate(zip(counted, media))
             if len(medium.tracks) != len(tracks)]
    if len(short) != 1:
        return None
    index, medium = short[0]
    if len(medium.tracks) - len(media[index]) != unreadable:
        return None
    claimed = [_claimed_number(t) for t in media[index]]
    if None in claimed or len(set(claimed)) != len(claimed) or not all(1 <= c <= len(medium.tracks) for c in claimed):
        return None
    return index, [k for k in range(1, len(medium.tracks) + 1) if k not in claimed]


def pair_around(unit: Unit, release: dict, gap: tuple[int, list[int]]) -> list[TrackPair]:
    """Every file of `unit` paired with its recording on `release`, the numbers `gap` names left unpaired.

    `gap` is what `missing_positions` returned. A file takes the recording
    at its place in track order among the numbers that are not missing, so
    the file after the gap is the track after it, not the gap's.
    """
    counted = counted_media(release)
    gap_medium, missing = gap
    pairs = []
    for n, (tracks, medium) in enumerate(zip(group_media(unit), counted)):
        numbered = [(k, entry) for k, entry in enumerate(medium.tracks, start=1) if n != gap_medium or k not in missing]
        for track, (number, (position, mb_track)) in zip(tracks, numbered):
            pairs.append(TrackPair(medium.index, position, track, mb_track, number, len(medium.tracks), n + 1, len(counted)))
    return pairs


def _album_value(track: files.Track) -> str | None:
    values = track.tags.get(mapping.PICARD["album"][track.family])
    if not values:
        return None
    value = values[0].strip()
    return value or None


_DISC_SUFFIX = re.compile(
    r"\s*(?:[-:,]\s*)?(?:\(\s*|\[\s*)?(?<!\w)(?:disc|disk|cd)\s*-?\s*\d+(?:\s*(?:of|/)\s*\d+)?\s*[)\]]?\s*$",
    re.IGNORECASE)

NEEDS_A_PERSON = "needs a person"

DISAGREEMENT = "files disagree on the album tag"


def _without_disc(value: str) -> str:
    return _DISC_SUFFIX.sub("", value) or value


def _disagreement(tracks: list[files.Track]) -> tuple[str | None, str | None]:
    values: list[str] = []
    albums: set[str] = set()
    for track in tracks:
        value = _album_value(track)
        if value is not None and value not in values:
            values.append(value)
            albums.add(_without_disc(value))
    if len(albums) <= 1:
        return None, None
    return NEEDS_A_PERSON, f"{DISAGREEMENT}: " + ", ".join(values)


def unit_at(album_path: Path, root: Path) -> Unit:
    tracks: list[files.Track] = []
    unreadable: list[tuple[str, str]] = []
    others: list[str] = []

    paths, unlistable = walk.album_contents(album_path)
    for folder, reason in unlistable:
        unreadable.append((folder.relative_to(album_path).as_posix(), reason))
    for path in paths:
        rel = path.relative_to(album_path)
        # `files.is_track` is the one place this and `check.read_album` agree
        # on what a track is: in the album folder or one level down - that
        # subfolder is its disc folder, whatever it is called - and never a
        # video-carrying `.mp4`. Audio two levels down (a `Scans/extra/`
        # subfolder, say) is just another file to leave alone.
        if files.is_track(path, rel):
            try:
                tracks.append(files.read(path))
            except files.Unreadable as exc:
                unreadable.append((rel.as_posix(), str(exc)))
        else:
            others.append(rel.as_posix())

    status, reason = _disagreement(tracks)

    return Unit(
        path=album_path,
        rel=album_path.relative_to(root).as_posix(),
        tracks=tracks,
        unreadable=unreadable,
        others=others,
        status=status,
        reason=reason,
    )


def units(root: Path) -> list[Unit]:
    """Every album unit under `root` (`Letter/Artist/Album`), sorted by `rel`."""
    root = Path(root)
    found = [unit_at(album_dir, root) for album_dir in walk.album_dirs(root)]
    found.sort(key=lambda u: u.rel)
    return found
