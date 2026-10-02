"""Suggestions on the review page: what the planned artist's library albums say about a planned album.

Only the artist folders under the planned letter are looked at. Each album
in them is summarised by its album artist ids, taken from its first track
that has any. The genres of each track are read too, but only for the albums
of an artist folder that matched the plan. The summary is kept in
`library-summary.json` under the jobs folder. It is keyed on the album's
track names, sizes and mtimes, so a rating written in place is seen and
nothing is read again where nothing changed. The file can be deleted at any time.
"""

from __future__ import annotations

import threading
import unicodedata
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Iterator

from musiclib import files, genres, walk
from musiclib.mapping import PICARD

from . import drops

if TYPE_CHECKING:
    from .server import Config

_GAME_GENRES = (genres.SOUNDTRACK, genres.VIDEO_GAME_MUSIC)
_SUMMARY = "library-summary.json"
_LOCK = threading.Lock()


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _folded(name: str) -> str:
    """`name` with case and accents removed, for the rule that matches a folder by its name."""
    decomposed = unicodedata.normalize("NFD", _nfc(name).casefold())
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))


def _planned(entry: dict[str, Any], field: str) -> list[str]:
    """Every value of `field` across the plan's files, in first-seen order, whichever family each file is."""
    keys = {key for key in PICARD[field].values() if key}
    seen: list[str] = []
    for planned in entry.get("files", []):
        for key, values in planned.get("after", {}).items():
            if key in keys:
                seen.extend(value for value in values if value not in seen)
    return seen


def _stat_key(album: Path) -> list[list[Any]] | None:
    """Name, size and mtime in nanoseconds of every candidate track, or None where the folder cannot be listed."""
    paths, unlistable = walk.album_contents(album)
    if unlistable:
        return None
    key = []
    for path in paths:
        rel = path.relative_to(album)
        if path.is_symlink() or not files.is_track_by_name(path, PurePosixPath(rel.as_posix())):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        key.append([rel.as_posix(), stat.st_size, stat.st_mtime_ns])
    return key


def _readable(album: Path) -> Iterator[files.Track]:
    paths, _unlistable = walk.album_contents(album)
    for path in paths:
        if path.is_symlink() or not files.is_track(path, PurePosixPath(path.relative_to(album).as_posix())):
            continue
        try:
            yield files.read(path)
        except files.Unreadable:
            continue


def _read_ids(album: Path) -> list[str]:
    """The album artist ids of the album's first readable track that carries any; reading stops there."""
    for track in _readable(album):
        key = PICARD["album artist id"].get(track.family)
        found = track.tags.get(key, []) if key else []
        if found:
            return sorted(found)
    return []


def _read_genres(album: Path) -> list[list[str]]:
    rows = []
    for track in _readable(album):
        key = PICARD["genre"].get(track.family)
        rows.append(list(track.tags.get(key, [])) if key else [])
    return rows


class _Summaries:
    """The summary file for one request: loaded once, written back only where an album was read.

    A row holds the album's ids from the first pass and, once the album's
    artist folder has matched, its genres. A changed track drops both.
    """

    def __init__(self, config: Config) -> None:
        self.path = config.jobs / _SUMMARY
        with _LOCK:
            self.rows = drops.read_json(self.path) or {}
        self.changed = False

    def _row(self, rel: str, album: Path) -> dict[str, Any] | None:
        key = _stat_key(album)
        if key is None:
            return None
        row = self.rows.get(rel)
        if not (isinstance(row, dict) and row.get("key") == key and "ids" in row):
            row = {"key": key, "ids": _read_ids(album)}
            self.rows[rel] = row
            self.changed = True
        return row

    def ids(self, rel: str, album: Path) -> list[str] | None:
        row = self._row(rel, album)
        return None if row is None else row["ids"]

    def genres(self, rel: str, album: Path) -> list[list[str]] | None:
        row = self._row(rel, album)
        if row is None:
            return None
        if "genres" not in row:
            row["genres"] = _read_genres(album)
            self.changed = True
        return row["genres"]

    def save(self) -> None:
        if self.changed:
            try:
                with _LOCK:
                    drops.replace_json(self.path, self.rows)
            except OSError:
                pass


def _subfolders(folder: Path) -> list[str]:
    try:
        return sorted(entry.name for entry in folder.iterdir() if entry.is_dir() and not walk.is_ignored(entry.name))
    except OSError:
        return []


def _carries(tracks: list[list[str]], genre: str) -> bool:
    return bool(tracks) and all(genre in track for track in tracks)


def suggestions(config: Config, entry: dict[str, Any] | None, replaces: str | None) -> list[dict[str, Any]]:
    """The suggestions for the plan `entry`; `replaces` is the library-relative path of the album a match replaces."""
    destination = (entry or {}).get("destination")
    if not entry or not entry.get("files") or not destination:
        return []
    parts = PurePosixPath(destination).parts
    if len(parts) < 3:
        return []
    letter, folder_name, album_name = parts[0], parts[1], parts[2]
    ids = set(_planned(entry, "album artist id"))
    left_out = _nfc(replaces) if replaces else None
    own = _nfc(f"{letter}/{folder_name}/{album_name}")

    summaries = _Summaries(config)
    matching: list[tuple[str, list[list[list[str]]]]] = []
    for name in _subfolders(config.library / letter):
        home = config.library / letter / name
        found = []
        for album in _subfolders(home):
            carried = summaries.ids(f"{letter}/{name}/{album}", home / album)
            if carried is not None:
                found.append((album, set(carried)))
        by_id = bool(ids) and any(carried == ids for _album, carried in found)
        # An album with no ids does not tell the folder apart from the plan's artist.
        allowed = (ids, set())
        by_name = _folded(name) == _folded(folder_name) and all(carried in allowed for _album, carried in found)
        if not (by_id or by_name):
            continue
        # Genres are read for the albums of a matching folder only.
        albums = [rows for album, _carried in found
                  if _nfc(f"{letter}/{name}/{album}") not in (left_out, own)
                  and (rows := summaries.genres(f"{letter}/{name}/{album}", home / album)) is not None]
        matching.append((name, albums))
    summaries.save()

    return _decide(entry, letter, folder_name, matching)


def _decide(entry: dict[str, Any], letter: str, folder_name: str,
            matching: list[tuple[str, list[list[list[str]]]]]) -> list[dict[str, Any]]:
    """The suggestions from the matching artist folders: each with its albums, each album a list of its tracks' genres."""
    artist = (_planned(entry, "albumartist") or [folder_name])[0]
    plan_genres = set(_planned(entry, "genre"))
    albums = [album for _name, kept in matching for album in kept]
    result: list[dict[str, Any]] = []

    spelled = sorted(f"{letter}/{name}" for name, _kept in matching if _nfc(name) != _nfc(folder_name))
    if spelled:
        result.append({
            "kind": "spelling", "artist": artist, "lands_in": f"{letter}/{folder_name}",
            "folders": [{"path": path, "name": path.split("/", 1)[1]} for path in spelled],
        })
    if not albums:
        return result

    def reach(genre: str) -> int:
        return sum(_carries(tracks, genre) for tracks in albums)

    def half(count: int) -> bool:
        return count * 2 >= len(albums)

    # The owner's choice, else the release's own tags, says which of the two the plan holds.
    chosen = entry.get("game")
    held = chosen if chosen in _GAME_GENRES else next((g for g in _GAME_GENRES if g in plan_genres), None)
    waiting = entry.get("game_choice") and entry.get("game") is None
    if held is not None:
        others = [g for g in _GAME_GENRES if g != held]
    else:
        others = list(_GAME_GENRES) if waiting else []
    result.extend({"kind": "soundtrack", "genre": genre, "albums": reach(genre), "of": len(albums), "artist": artist}
                  for genre in others if reach(genre) > 0 and half(reach(genre)))

    every = sorted({genre for tracks in albums for track in tracks for genre in track})
    # Only a genre the editor takes, so Add never puts a name in the draft that holds the album.
    counted = [(reach(genre), genre) for genre in every
               if genre in genres.OFFICIAL and genre not in plan_genres and genre not in _GAME_GENRES]
    result.extend({"kind": "genre", "genre": genre, "albums": count, "of": len(albums), "artist": artist}
                  for count, genre in sorted(counted, key=lambda one: (-one[0], one[1])) if half(count))
    return result
