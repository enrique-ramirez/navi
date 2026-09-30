"""`musiclib check ROOT`: every rule in `docs/music-library.md` an album breaks.

`check` never touches MusicBrainz, so it only judges what the files and
folders themselves can say: it does not know a release's true medium count or
track titles, only what the tags claim for themselves.

`read_album` does the one disk-touching pass (files, folder names, embedded
pictures, an MP3's ID3 version). `check_album` then judges an `AlbumState`
with no disk access at all, so a plan can build the same shape and be judged
by the same rules before anything is written.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, NamedTuple

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from musiclib import files, genres, mapping, names, residue, tagwrite, units, walk

#: MP3's documented rating: one POPM from this email, on the WMP byte scale.
_WMP_EMAIL = "Windows Media Player 9 Series"
_WMP_RATINGS = {1, 64, 128, 196, 255}

#: The two genres MusicBrainz has no genre for (docs *Tags*, *Genres*).
_CUSTOM_GENRES = {"video game music", "soundtrack"}

#: (`mapping.PICARD` name, the label a person reads) for *Every track has*.
_REQUIRED = [
    ("title", "title"), ("artist", "artist"), ("album", "album"),
    ("albumartist", "album artist"), ("date", "date"),
    ("release id", "release id"), ("release group id", "release group id"),
    ("artist id", "artist id"), ("recording id", "recording id"),
]

_DISC_DIR_RE = re.compile(r"^CD\d+$")
_ALBUM_FOLDER_RE = re.compile(r"^\((?P<year>[^)]*)\)(?P<prefixes>(?: \[[^\]]+\])*) (?P<title>.+)$")
_EDITION_RE = re.compile(r" \[[^\[\]]+\]$")
_PREFIX_RE = re.compile(r"\[([^\]]+)\]")
_ALLOWED_PREFIXES = {"EP", "Single", "Mixtape", "Live"}

#: `(disc 1)`, `[CD 2]`, `(bonus disc)`, ... anywhere in the album title.
_DISC_MARKER_RE = re.compile(
    r"(?i)[\(\[]\s*(?:disc|disk|cd)\s*\d+\s*[\)\]]|[\(\[]\s*bonus\s*(?:disc|disk|cd)\s*[\)\]]"
)

#: Exact junk names from docs *What an album folder may contain*, lower-cased.
_REMOVED_NAMES = {
    ".ds_store", "thumbs.db", "desktop.ini", ".directory", "icon\r", "albumartsmall.jpg",
}
_REMOVED_EXTS = {".cue", ".m3u", ".m3u8", ".sfv", ".accurip", ".ffp", ".md5",
                 ".nfo", ".url", ".ini", ".ico", ".lrc"}
#: Extensions for videos, disc images and CD-ROM software (decision: the doc
#: names the kinds, not the extensions; `.mp4` is deliberately not here since
#: the library holds `.mp4` audio too).
_EXTRA_EXTS = {
    ".mkv", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".vob", ".wmv", ".webm",
    ".iso", ".img", ".bin", ".nrg", ".mdf", ".mds", ".ccd",
    ".exe", ".msi", ".dll", ".app",
}
#: Every image type the doc's *What an album folder may contain* allows,
#: cover.jpg's own type plus the other formats the Cover Art Archive and rip
#: scans turn up in (decision).
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
_OTHER_KEPT_EXTS = {".pdf", ".log", ".txt"}


class Violation(NamedTuple):
    """One rule an album breaks. `album` is relative to the checked ROOT."""

    album: Path
    rule: str
    detail: str


@dataclass(frozen=True)
class TrackState:
    """One audio file's judged state, gathered once, off disk."""

    filename: str
    disc_dir: str | None  # the CDn it actually sits in, or None
    track: files.Track
    front_covers: int
    cover_size: tuple[int, int] | None  # only meaningful when front_covers == 1
    id3_version: tuple[int, int, int] | None  # None for a non-MP3
    has_id3v1: bool


@dataclass(frozen=True)
class AlbumState:
    """An album unit's judged state. Never holds a live mutagen object."""

    album: Path  # relative to ROOT
    letter: str
    artist: str
    folder: str
    tracks: tuple[TrackState, ...]
    # Every non-track file, already classified (`classify_other`'s answer,
    # from whichever side had disk access to decide it): a plan's own state
    # is built with no disk at all, and even a real `read_album` may be
    # judged after the album is gone (`ABadFile`), so `_folder_content_violations`
    # never calls `classify_other` itself.
    other_files: tuple[tuple[str, str], ...]
    subdirs: tuple[str, ...]  # the album folder's direct child directories
    has_cover_jpg: bool
    # (posix path from the album folder, what went wrong): a file mutagen
    # could not read at all, or one whose embedded picture is not an image.
    # A plan never contains one of these - `units` refuses such an album
    # before it reaches `plan_album` - so `state_from_plan` always supplies
    # an empty tuple here.
    unreadable: tuple[tuple[str, str], ...]


# --- reading -----------------------------------------------------------

def _id3_format(path: Path) -> tuple[tuple[int, int, int] | None, bool]:
    """The on-disk ID3 version and whether an ID3v1 trailer follows.

    Read straight off the bytes rather than through mutagen, so this can
    never be tempted into a `.save()`.
    """
    data = path.read_bytes()
    has_v1 = len(data) >= 128 and data[-128:-125] == b"TAG"
    version = (2, data[3], data[4]) if data[:3] == b"ID3" else None
    return version, has_v1


def _cover_info(path: Path, family: str) -> tuple[int, tuple[int, int] | None]:
    """The count of embedded front-cover pictures, and the one's pixel size.

    MP4 has no picture types (`tests.builders.embed_picture`), so every
    `covr` counts as a front cover there. An MP3 with no ID3 header at all
    has no pictures either, the same as any other missing tag, never a
    reading error - `read_album` treats every other exception here (a
    picture that is not an image, a corrupt block) as the track's own
    unreadable, so it is left to propagate rather than caught here. ASF's
    `WM/Picture` does carry a type, unlike MP4's `covr`, so it goes through
    `images.embedded_pictures` (the one place that already parses its byte
    layout) rather than being repeated here.
    """
    from PIL import Image

    import io

    from musiclib import images

    pictures: list[bytes] = []
    try:
        if family == "id3":
            for frame in ID3(path).getall("APIC"):
                if frame.type == 3:
                    pictures.append(frame.data)
        elif family == "vorbis":
            if path.suffix.lower() == ".flac":
                for picture in FLAC(path).pictures:
                    if picture.type == 3:
                        pictures.append(picture.data)
            else:
                for blob in OggVorbis(path).get("metadata_block_picture", []):
                    picture = Picture(base64.b64decode(blob))
                    if picture.type == 3:
                        pictures.append(picture.data)
        elif family == "mp4":
            for cover in MP4(path).get("covr", []):
                pictures.append(bytes(cover))
        elif family == "asf":
            for picture_type, data in images.embedded_pictures(path):
                if picture_type == 3:
                    pictures.append(data)
    except ID3NoHeaderError:
        return 0, None

    if len(pictures) != 1:
        return len(pictures), None
    image = Image.open(io.BytesIO(pictures[0]))
    return 1, image.size


def _read_track(path: Path, rel: PurePosixPath) -> TrackState:
    track = files.read(path)
    disc_dir = rel.parts[0] if len(rel.parts) > 1 else None
    front_covers, cover_size = _cover_info(path, track.family)
    id3_version = has_id3v1 = None
    if track.family == "id3":
        id3_version, has_id3v1 = _id3_format(path)
    return TrackState(filename=rel.name, disc_dir=disc_dir, track=track,
                      front_covers=front_covers, cover_size=cover_size,
                      id3_version=id3_version, has_id3v1=bool(has_id3v1))


def read_album(album_dir: Path, root: Path) -> AlbumState:
    """Everything `check_album` needs to judge `album_dir`, read once."""
    album_dir, root = Path(album_dir), Path(root)
    rel = album_dir.relative_to(root)

    tracks: list[TrackState] = []
    other_files: list[tuple[str, str]] = []
    unreadable: list[tuple[str, str]] = []
    subdirs = [p.name for p in walk.child_dirs(album_dir)]
    entries, unlistable = walk.album_contents(album_dir)
    for folder, reason in unlistable:
        unreadable.append((folder.relative_to(album_dir).as_posix(), reason))
    for entry in entries:
        entry_rel = PurePosixPath(entry.relative_to(album_dir).as_posix())
        # `files.is_track` is the one place this and `units.units` agree on
        # what a track is: a video-carrying `.mp4` reads its content to say
        # so, which only works while the file is still here to read - the
        # one reason `classify_other` is ever called with disk access at all.
        if files.is_track(entry, entry_rel):
            # Anything that goes wrong reading one file - mutagen unable to
            # parse it, a picture that is not an image, a corrupt block -
            # becomes that file's own `unreadable` rather than aborting the
            # whole run: the album's other files and its next sibling still
            # get judged, the one thing that matters on a 30,000-file
            # library (`ABadFile`).
            try:
                tracks.append(_read_track(entry, entry_rel))
            except Exception as exc:
                unreadable.append((str(entry_rel), f"{type(exc).__name__}: {exc}"))
        else:
            other_files.append((str(entry_rel), classify_other(entry, str(entry_rel))))

    return AlbumState(
        album=rel, letter=rel.parts[0], artist=album_dir.parent.name, folder=album_dir.name,
        tracks=tuple(tracks), other_files=tuple(other_files), subdirs=tuple(subdirs),
        has_cover_jpg=(album_dir / "cover.jpg").is_file(), unreadable=tuple(unreadable),
    )


# --- field access --------------------------------------------------------

def _field(track: files.Track, name: str) -> list[str] | None:
    key = mapping.PICARD[name].get(track.family)
    return None if key is None else track.tags.get(key)


def _first(track: files.Track, name: str) -> str | None:
    values = _field(track, name)
    return values[0] if values else None


def _number_text(track: files.Track, key_map: dict[str, str]) -> str:
    return units.first_value(track, key_map) or ""


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_pair(value: str) -> tuple[int | None, int | None]:
    """`"n"` or `"n/total"` -> `(n, total)`, ID3's TRCK/TPOS shape."""
    number, _, total = value.partition("/")
    return _int_or_none(number), (_int_or_none(total) if total else None)


def _numbers(track: files.Track) -> tuple[int | None, int | None, int | None, int | None]:
    """`(track number, track total, disc number, disc total)`, per format."""
    if track.family == "id3":
        number, total = _split_pair(_number_text(track, units.TRACK_NUMBER_KEY))
        disc, discs = _split_pair(_number_text(track, units.DISC_NUMBER_KEY))
    elif track.family == "vorbis":
        number = _int_or_none(_number_text(track, units.TRACK_NUMBER_KEY))
        total = _int_or_none(units.first_value(track, units.TRACK_TOTAL_KEY))
        disc = _int_or_none(_number_text(track, units.DISC_NUMBER_KEY))
        discs = _int_or_none(units.first_value(track, units.DISC_TOTAL_KEY))
    elif track.family == "mp4":
        # files.mp4_pair_text renders trkn/disk the same "n" or "n/total"
        # shape as ID3's TRCK/TPOS, so the same parser reads both.
        number, total = _split_pair(_number_text(track, units.TRACK_NUMBER_KEY))
        disc, discs = _split_pair(_number_text(track, units.DISC_NUMBER_KEY))
    elif track.family == "asf":
        # Picard has no ASF name for the track total (decision: a WMA carries
        # none), so there is nothing to read back into it. WM/PartOfSet does
        # hold a disc total, the same "n/total" shape as TPOS.
        number = _int_or_none(_number_text(track, units.TRACK_NUMBER_KEY))
        total = None
        disc, discs = _split_pair(_number_text(track, units.DISC_NUMBER_KEY))
    else:
        number = total = disc = discs = None
    return number, total, disc, discs


# --- per-track rules -------------------------------------------------------

def _is_year_key(family: str, key: str) -> bool:
    if family == "id3":
        return key.startswith("TXXX:") and key[len("TXXX:"):].lower() == "year"
    if family == "vorbis":
        return key == "year"
    if family == "mp4":
        return key.startswith("----:") and key.rsplit(":", 1)[-1].lower() == "year"
    # ASF falls through to False too: no stray "Year" attribute turned up in
    # the residue dump this engine's denylist is built from, so there is
    # nothing yet to name as one.
    return False


def _required_field_violations(track: files.Track) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, label in _REQUIRED:
        values = _field(track, name)
        if not values or not values[0]:
            out.append(("required field", label))
    return out


def _number_violations(family: str, number: int | None, total: int | None,
                       disc: int | None, discs: int | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if number is None:
        out.append(("required field", "track number"))
    # Picard has no ASF name for the track total, so a WMA is never asked
    # for one (decision).
    if total is None and family != "asf":
        out.append(("required field", "track total"))
    if disc is None:
        out.append(("required field", "disc number"))
    if discs is None:
        out.append(("required field", "disc total"))
    return out


def _filename_violations(state: TrackState, number: int | None, total: int | None) -> list[tuple[str, str]]:
    """`total` is the tag's own, or the disc's track count when the tag has none (`_track_violations`)."""
    title = _first(state.track, "title")
    if title is None or number is None or total is None:
        return []
    ext = Path(state.filename).suffix.lstrip(".")
    expected_name = names.track_filename(number, title, ext, total)
    if state.filename == expected_name:
        return []
    return [("file name", f"{state.filename!r}, expected {expected_name!r}")]


def _disc_folder_violations(state: TrackState, disc: int | None, discs: int | None) -> list[tuple[str, str]]:
    if disc is None or discs is None:
        return []
    expected_dir = names.disc_folder(disc, discs)
    if state.disc_dir == expected_dir:
        return []
    return [("disc folder", f"in {state.disc_dir!r}, expected {expected_dir!r}")]


def _tag_format_violations(state: TrackState) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if state.track.family != "id3":
        return out
    if state.id3_version != (2, 4, 0):
        out.append(("tag format", f"ID3 {state.id3_version}, not v2.4"))
    if state.has_id3v1:
        out.append(("tag format", "carries an ID3v1 trailer"))
    return out


def _genre_violations(state: TrackState) -> list[tuple[str, str]]:
    track = state.track
    values = _field(track, "genre") or []
    # No field at all, and a field holding only blank or whitespace-only
    # values (a blank cannot mean "not asked" the way a missing key does),
    # both leave the track with nothing a person would call a genre. Named
    # by file, not just "no genre" repeated: a plan's own problem list
    # (`plan._dedupe`) collapses identical strings, and two different tracks
    # both missing a genre must not fold into the one problem the owner sees.
    if not any(value.strip() for value in values):
        return [("no genre", f"{state.filename} carries no genre on the official list; "
                             "tag one into the files or add genres on MusicBrainz, then plan again")]
    return [("genre", f"{state.filename}: {value!r} is not an official genre")
            for value in values
            if value not in genres.OFFICIAL and value not in _CUSTOM_GENRES]


def _rating_violations(track: files.Track) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if track.family == "id3":
        for key, values in track.tags.items():
            if not key.startswith("POPM:"):
                continue
            email = key[len("POPM:"):]
            rating = None
            for part in (values[0] if values else "").split(","):
                field, _, val = part.partition("=")
                if field == "rating":
                    rating = _int_or_none(val)
            if email != _WMP_EMAIL or rating not in _WMP_RATINGS:
                out.append(("rating", f"POPM:{email} rating={rating}"))
    elif track.family == "vorbis":
        for value in track.tags.get("rating", []):
            if not (value.isdigit() and 1 <= int(value) <= 5):
                out.append(("rating", f"RATING={value!r}"))
    return out


def _duplicate_field_violations(track: files.Track) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key in track.tags:
        if tagwrite.is_forbidden_duplicate(track.family, key):
            rule = "year tag" if _is_year_key(track.family, key) else "duplicate field"
            out.append((rule, key))
    return out


def _disc_marker_violations(track: files.Track) -> list[tuple[str, str]]:
    album_title = _first(track, "album")
    if album_title and _DISC_MARKER_RE.search(album_title):
        return [("disc in album title", album_title)]
    return []


def _cover_violations(state: TrackState) -> list[tuple[str, str]]:
    if state.front_covers != 1:
        return [("embedded cover", f"{state.front_covers} embedded front covers")]
    if state.cover_size and max(state.cover_size) > 1200:
        return [("embedded cover", f"{state.cover_size[0]}x{state.cover_size[1]}")]
    return []


def _residue_violations(track: files.Track) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    kept, removals = residue.strip(track.family, track.tags)
    for key, values in kept.items():
        if tagwrite.is_non_text_key(track.family, key):
            continue
        for value in values:
            if tagwrite.keeps_whitespace(track.family, key, value) or tagwrite.has_line_break(value):
                continue
            if value != value.strip() or "  " in value:
                out.append(("whitespace", f"{key}={value!r}"))
    for removal in removals:
        detail = removal.key if removal.value is None else f"{removal.key}={removal.value!r}"
        out.append((f"residue: {removal.rule}", detail))
    return out


def _track_violations(state: TrackState, disc_counts: dict[str | None, int]) -> list[tuple[str, str]]:
    """Every rule `state`'s track breaks, each check named for the one rule it judges."""
    track = state.track
    number, total, disc, discs = _numbers(track)

    out: list[tuple[str, str]] = []
    out.extend(_required_field_violations(track))
    out.extend(_number_violations(track.family, number, total, disc, discs))
    # With no total in the tag (every WMA; an MP3 whose TRCK is bare "n"),
    # the *Files* rule still has a medium size to check the name against: how
    # many tracks the album state itself holds in this file's own disc.
    name_total = total if total is not None else disc_counts.get(state.disc_dir)
    out.extend(_filename_violations(state, number, name_total))
    out.extend(_disc_folder_violations(state, disc, discs))
    out.extend(_tag_format_violations(state))
    out.extend(_genre_violations(state))
    out.extend(_rating_violations(track))
    out.extend(_duplicate_field_violations(track))
    out.extend(_disc_marker_violations(track))
    out.extend(_cover_violations(state))
    out.extend(_residue_violations(track))
    return out


# --- album-level rules -------------------------------------------------

def _album_title(state: AlbumState) -> str | None:
    for track_state in state.tracks:
        value = _first(track_state.track, "album")
        if value:
            return value
    return None


def _album_date_year(state: AlbumState) -> str | None:
    for track_state in state.tracks:
        value = _first(track_state.track, "date")
        if value and len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    return None


def _disc_track_counts(state: AlbumState) -> dict[str | None, int]:
    """How many of `state`'s tracks sit in each disc folder (`None` for no disc folder)."""
    counts: dict[str | None, int] = {}
    for track_state in state.tracks:
        counts[track_state.disc_dir] = counts.get(track_state.disc_dir, 0) + 1
    return counts


def _has_other_edition(folder: str, siblings: Iterable[str]) -> bool:
    """Whether another of `siblings` has `folder`'s name once each one's trailing ` [..]` is removed, case aside."""
    bare = _EDITION_RE.sub("", folder).casefold()
    return any(other != folder and _EDITION_RE.sub("", other).casefold() == bare for other in siblings)


def _album_folder_violations(state: AlbumState, siblings: Iterable[str],
                             suffix_given: bool) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    match = _ALBUM_FOLDER_RE.match(state.folder)
    if not match:
        out.append(("album folder", f"{state.folder!r} is not shaped (YYYY) Title"))
    else:
        year = match.group("year")
        prefixes = _PREFIX_RE.findall(match.group("prefixes"))
        album_title = _album_title(state)
        bad = not (len(year) == 4 and year.isdigit())
        bad = bad or len(prefixes) > 1 or any(p not in _ALLOWED_PREFIXES for p in prefixes)
        if album_title is not None:
            head = f"({year}){''.join(f' [{p}]' for p in prefixes)} "
            expected = names.fit(names.sanitize(f"{head}{album_title}"), start=len(head))
            # One trailing ` [edition]` is what a job adds to editions that
            # would share a folder; the tags do not say which field it is, so
            # it is believed only beside its other edition (or where a plan
            # has just given it, the other edition not yet on disk).
            edition = _EDITION_RE.search(state.folder)
            believed = suffix_given or _has_other_edition(state.folder, siblings)
            with_edition = edition and believed and names.fit(
                names.sanitize(f"{head}{album_title}"), suffix=edition.group(0), start=len(head))
            bad = bad or state.folder not in (expected, with_edition)
        if bad:
            out.append(("album folder", f"{state.folder!r}"))
        if len(year) == 4 and year.isdigit():
            date_year = _album_date_year(state)
            if date_year is not None and date_year != year:
                out.append(("album year", f"folder says {year!r}, DATE says {date_year!r}"))
    return out


def classify_other(path: Path | None, rel: str) -> str:
    """`"delete"`, `"extra"`, `"keep"` or `"unexpected"` for one non-track file, by name, extension and content.

    Public: `plan` sorts a rip's own leftover files into the same piles
    before anything is written, so a plan and a finished write agree on what
    disappears, what moves to extras, and what stays. `"unexpected"` is a
    type *What an album folder may contain* neither allows, removes nor
    moves to extras, so `check` names it.

    `path` is the file's absolute path, needed only to tell an `.mp4` video
    (an extra) from `.mp4` audio: every other rule here is name-only.
    `None` is for a caller that already knows the answer without it - only
    `state_from_plan` (`plan.py`), classifying a file `plan.sort_others`
    already sorted out of `extras` with the real file in hand, so any `.mp4`
    reaching it here is never a video.
    """
    rel_path = PurePosixPath(rel)
    lower_name = rel_path.name.lower()
    ext = rel_path.suffix.lower()
    if lower_name in _REMOVED_NAMES or rel_path.name.startswith("._") or ext in _REMOVED_EXTS or (
        lower_name.startswith("albumart_") and lower_name.endswith(".jpg")
    ):
        return "delete"
    if ext == ".mp4":
        return "extra" if path is not None and files.is_mp4_video(path) else "unexpected"
    if ext in _EXTRA_EXTS:
        return "extra"
    if ext in IMAGE_EXTS or ext in _OTHER_KEPT_EXTS:
        return "keep"
    return "unexpected"


def _folder_content_violations(state: AlbumState) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not state.has_cover_jpg:
        out.append(("cover.jpg", "no cover.jpg"))
    for name in state.subdirs:
        if not _DISC_DIR_RE.match(name):
            out.append(("subfolder", name))
    for rel, kind in state.other_files:
        if kind == "delete":
            out.append(("removed file", rel))
        elif kind == "extra":
            out.append(("extras", rel))
        elif kind == "unexpected":
            out.append(("unexpected file", rel))
        else:
            path = PurePosixPath(rel)
            if len(path.parts) > 1 and _DISC_DIR_RE.match(path.parts[0]) and path.suffix.lower() in IMAGE_EXTS:
                out.append(("image in disc folder", rel))
    return out


def check_album(state: AlbumState, siblings: Iterable[str] = (), suffix_given: bool = False) -> list[Violation]:
    """Every rule `state` breaks. Never touches disk.

    `siblings` are the names of the other album folders under the same
    artist folder; `suffix_given` is a plan saying the folder's trailing
    ` [..]` is its own, whatever is on disk.
    """
    found: list[tuple[str, str]] = []

    expected_letter = names.letter(state.artist)
    if state.letter != expected_letter:
        found.append(("letter", f"under {state.letter!r}, expected {expected_letter!r}"))
    if names.sanitize(state.artist) != state.artist:
        found.append(("characters", state.artist))

    found.extend(_album_folder_violations(state, siblings, suffix_given))
    disc_counts = _disc_track_counts(state)
    for track_state in state.tracks:
        found.extend(_track_violations(track_state, disc_counts))
    found.extend(_folder_content_violations(state))
    found.extend(("unreadable", f"{rel}: {reason}") for rel, reason in state.unreadable)

    return [Violation(album=state.album, rule=rule, detail=detail) for rule, detail in found]


def check(root: Path | str) -> list[Violation]:
    """Every rule any album under `root` breaks. Reads; never writes."""
    root = Path(root)
    violations: list[Violation] = []
    album_dirs = list(walk.album_dirs(root))
    folders: dict[Path, list[str]] = {}
    for album_dir in album_dirs:
        folders.setdefault(album_dir.parent, []).append(album_dir.name)
    for album_dir in album_dirs:
        violations.extend(check_album(read_album(album_dir, root), folders[album_dir.parent]))
    return violations
