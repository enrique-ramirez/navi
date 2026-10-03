"""The library, read: `GET /api/library/...` and `GET /api/genres`.

Every path is resolved under `config.library` and refused (404, nothing read)
where it leaves it, so a `..`, an absolute name or a symlink out reads as no
such folder. An answer reads the one letter, artist or album it names and
nothing wider.

The one write is `remove`, `DELETE` of an artist or an album folder that
holds nothing.
"""

from __future__ import annotations

import errno
import os
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from musiclib import genres, images, mapping, names, walk
from musiclib.batch.decisions import raw_key_offence

from . import drops, log, ranges, review, swap
from .refusal import Refusal
from .state import LETTER_FOLDERS

if TYPE_CHECKING:
    from .server import Config, Handler

CUSTOM_GENRES = (genres.SOUNDTRACK, genres.VIDEO_GAME_MUSIC)
COVER = "cover.jpg"
LEADING_NUMBER = re.compile(r"\d+")
_RELEASE_ID = mapping.PICARD["release id"]
_TRACK_NUMBER = mapping.READABLE["Track number"]
_DISC_NUMBER = mapping.READABLE["Disc number"]


def key_offence(family: str, key: str) -> str | None:
    """Why an owner may not set or remove `key`, a key of `family`, or `None`: `raw_key_offence`'s reasons and the added time."""
    added = mapping.ADDED.get(family)
    if added is not None and key.casefold() == added.casefold() and (family == "vorbis" or key == added):
        return "is the time the album was added"
    return raw_key_offence(family, key)


def library_root(config: Config) -> Path:
    # Resolved, because the root may sit behind a symlink and `is_relative_to` compares real paths.
    return config.library.resolve()


def open_folder(config: Config, *parts: str) -> Path:
    """The folder `parts` name under the library root; raises a 404 for anything else, a `..` or a NUL in a part included."""
    root = library_root(config)
    if not LETTER_FOLDERS.fullmatch(parts[0]) or any(
            part in ("", ".", "..") or "/" in part or "\0" in part for part in parts):
        raise Refusal(404, "No such folder.")
    target = root.joinpath(*parts).resolve()
    if target == root or not target.is_relative_to(root) or not target.is_dir():
        raise Refusal(404, "No such folder.")
    return target


def open_unlinked(config: Config, *parts: str) -> Path:
    folder = open_folder(config, *parts)
    if folder != library_root(config).joinpath(*parts):
        raise Refusal(404, "No such folder.")
    return folder


def open_album(config: Config, path: str) -> Path:
    """The album folder a library-relative `Letter/Artist/Album` path names; a 404 for anything else."""
    parts = path.split("/")
    if len(parts) != 3:
        raise Refusal(404, "No such folder.")
    return open_folder(config, *parts)


def find_file(folder: Path, root: Path, rel: str) -> Path | None:
    """The file `rel` names inside the album `folder`, or `None` where nothing is there.

    A name that leads outside the folder or the library is a 404, so a caller can tell a file that is gone from a path that is refused.
    """
    # `folder / "/abs"` is "/abs", so an absolute name is refused before the join.
    if "\0" in rel or PurePosixPath(rel).is_absolute():
        raise Refusal(404, "No such file.")
    target = (folder / rel).resolve()
    if not (target.is_relative_to(root) and target.is_relative_to(folder)):
        raise Refusal(404, "No such file.")
    return target if target.is_file() else None


def open_file(folder: Path, root: Path, rel: str) -> Path:
    """The file `rel` names inside the album `folder`; raises a 404 for anything that is not a file there."""
    target = find_file(folder, root, rel)
    if target is None:
        raise Refusal(404, "No such file.")
    return target


def _address(path: str) -> str:
    return f"/api/library/{quote(path)}"


def leading_digits(values: list[str] | None) -> str | None:
    """The digits a tag's first value starts with, as written, `n` of `n/total`; `None` where there are none."""
    found = LEADING_NUMBER.match(values[0]) if values else None
    return found.group() if found else None


def leading_number(family: str, tags: dict[str, list[str]], keys: dict[str, str | None]) -> int:
    """The leading number of the tag `keys` names for `family`, `n` of `n/total`; 0 where the tags carry none."""
    digits = leading_digits(tags.get(keys.get(family) or ""))
    return int(digits) if digits else 0


def read_tracks(config: Config, path: str, folder: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The album's tracks in disc then track order by the numbers they carry, and its unreadable files."""
    root = library_root(config)
    found, unreadable = review.read_folder(folder, lambda rel: f"{_address(path)}/audio/{quote(rel)}", inside=root)
    tracks = []
    for track in found:
        try:
            stat = (folder / track["path"]).stat()
        except OSError:
            # A save swapped the folder away between the read and here.
            raise Refusal(404, "No such folder.") from None
        tracks.append({
            **track,
            "loaded": {"size": stat.st_size, "mtime": stat.st_mtime},
            "disc": leading_number(track["family"], track["tags"], _DISC_NUMBER) or 1,
            "number": leading_number(track["family"], track["tags"], _TRACK_NUMBER),
            "readonly": [key for key in track["tags"] if key_offence(track["family"], key)],
        })
    tracks.sort(key=lambda track: (track["disc"], track["number"], track["path"]))
    return tracks, unreadable


def _cover_file(folder: Path, root: Path) -> Path | None:
    try:
        return open_file(folder, root, COVER)
    except Refusal:
        return None


def release_id(tracks: Iterable[tuple[str, dict[str, list[str]]]]) -> str | None:
    """The MusicBrainz release id the first of the `(family, tags)` that carries one names."""
    for family, tags in tracks:
        values = tags.get(_RELEASE_ID.get(family, ""))
        if values and values[0]:
            return values[0]
    return None


def root_view(request: Handler, match: re.Match[str], config: Config) -> None:
    root = library_root(config)
    try:
        os.listdir(root)
        readable = True
    except OSError:
        readable = False
    letters = sorted((path.name for path in walk.child_dirs(root) if LETTER_FOLDERS.fullmatch(path.name)),
                     key=lambda name: (name == "#", name))
    request.send_json(200, {"root": str(config.library), "readable": readable, "letters": letters})


def _is_empty(folder: Path) -> bool:
    try:
        with os.scandir(folder) as entries:
            return next(entries, None) is None
    except OSError:
        return False


def letter(request: Handler, match: re.Match[str], config: Config) -> None:
    folder = open_folder(config, match.group(1))
    request.send_json(200, {"artists": [{"name": path.name, "empty": _is_empty(path)}
                                        for path in walk.child_dirs(folder)]})


def artist(request: Handler, match: re.Match[str], config: Config) -> None:
    letter_name, artist_name = match.group(1), match.group(2)
    root = library_root(config)
    albums = []
    open_ones = drops.open_matches(config)
    for folder in walk.child_dirs(open_folder(config, letter_name, artist_name)):
        path = f"{letter_name}/{artist_name}/{folder.name}"
        named = names.DATED_FOLDER_RE.fullmatch(folder.name)
        has_cover = _cover_file(folder, root) is not None
        albums.append({
            "path": path, "name": folder.name, "empty": _is_empty(folder),
            "year": named.group(1) if named else "", "title": named.group(2) if named else folder.name,
            "cover_url": f"{_address(path)}/cover" if has_cover else None,
            "match": open_ones.get(path),
            "tracks": read_tracks(config, path, folder)[0],
        })
    request.send_json(200, {"albums": albums, "names": review.names()})


def remove(request: Handler, match: re.Match[str], config: Config) -> None:
    """`DELETE` of an artist or an album folder that holds nothing: one `os.rmdir`, so nothing that holds a file can go."""
    parts = match.groups()
    path = "/".join(parts)
    folder = open_unlinked(config, *parts)
    if not _is_empty(folder):
        raise Refusal(409, f"not empty: {path}")
    try:
        os.rmdir(folder)
    except OSError as exc:
        log.failed("remove-folder", path, exc.strerror or exc)
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            raise Refusal(409, f"not empty: {path}") from None
        raise Refusal(500, f"could not remove {path}: {exc.strerror or exc}") from None
    log.write("remove-folder", path)
    removed = [path]
    if len(parts) == 2:
        swap.prune(folder.parent, library_root(config))
        if not folder.parent.exists():
            log.write("remove-folder", parts[0])
            removed.append(parts[0])
    request.send_json(200, {"removed": removed})


def _album_folder(config: Config, match: re.Match[str]) -> tuple[str, Path]:
    parts = match.group(1, 2, 3)
    return "/".join(parts), open_folder(config, *parts)


def album(request: Handler, match: re.Match[str], config: Config) -> None:
    path, folder = _album_folder(config, match)
    tracks, unreadable = read_tracks(config, path, folder)
    found = _cover_file(folder, library_root(config))
    cover = None
    if found is not None:
        try:
            width, height, passes, problem = images.cover_check(found.read_bytes())
            cover = {"url": f"{_address(path)}/cover", "width": width, "height": height,
                     "passes": passes, "problem": problem}
        except OSError:
            pass
    request.send_json(200, {
        "path": path, "release_id": release_id((track["family"], track["tags"]) for track in tracks), "cover": cover, "tracks": tracks,
        "unreadable": unreadable, "names": review.names(), "match": drops.open_match(config, path),
        "job": request.server.save_jobs.active(path),
    })


def cover(request: Handler, match: re.Match[str], config: Config) -> None:
    _path, folder = _album_folder(config, match)
    found = _cover_file(folder, library_root(config))
    if found is None:
        raise Refusal(404, "No cover.")
    request.send_file(found)


def audio(request: Handler, match: re.Match[str], config: Config) -> None:
    _path, folder = _album_folder(config, match)
    target = open_file(folder, library_root(config), match.group(4))
    ranges.serve(request, target)


def genre_list(request: Handler, match: re.Match[str], config: Config) -> None:
    request.send_json(200, {"genres": sorted({*genres.OFFICIAL, *CUSTOM_GENRES})})
