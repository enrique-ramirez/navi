"""Finding the albums of a drop and staging each one for its own musiclib job.

A drop arrives as `raw/<item>/...`. A folder is an album when it holds an
audio file of its own or a disc folder holding audio; any other folder is
searched in turn. Each album is moved to `<n>/drop/album/<name>/`, numbered in
the order the items were dropped and then in path order, and `raw/` goes away.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from musiclib.files import AUDIO_EXTENSIONS
from musiclib.units import disc_marker_stem, disc_number

from .drops import read_record

NO_AUDIO = "no audio files"
OUTSIDE = "outside every album"


@dataclass
class StagedAlbum:
    n: str
    name: str
    item: str


@dataclass
class Ignored:
    item: str
    path: str
    reason: str


@dataclass
class Staging:
    albums: list[StagedAlbum]
    ignored: list[Ignored]


def _subdirs(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir())


def _has_audio(folder: Path) -> bool:
    return any(p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS for p in folder.iterdir())


def _disc_subdirs(folder: Path) -> list[Path]:
    """The subfolders of `folder` that are its discs.

    A leading marker (`CD1`) always counts. Trailing markers (`Album [Disc 1]`)
    count only when every one of them follows the same name, so the folders of
    two albums under one artist folder are not read as discs of the artist.
    """
    subdirs = _subdirs(folder)
    stems = {disc_marker_stem(d.name) for d in subdirs if disc_number(d.name) is not None} - {None}
    trailing_agree = len(stems) <= 1
    return [d for d in subdirs
            if disc_number(d.name) is not None and (disc_marker_stem(d.name) is None or trailing_agree)]


def _is_album(folder: Path) -> bool:
    return _has_audio(folder) or any(_has_audio(d) for d in _disc_subdirs(folder))


def _find(folder: Path) -> list[Path]:
    """The album folders at or below `folder`, the outermost first."""
    if not _is_album(folder):
        return [a for d in _subdirs(folder) for a in _find(d)]
    found = [folder]
    discs = _disc_subdirs(folder)
    for d in _subdirs(folder):
        for inner in (_subdirs(d) if d in discs else [d]):
            found.extend(_find(inner))
    return found


def _item_names(drop: Path) -> list[str]:
    names: list[str] = []
    record = read_record(drop)
    if record is not None:
        names = [item["name"] for item in record.get("items", [])]
    raw = drop / "raw"
    if raw.is_dir():
        names += [p.name for p in sorted(raw.iterdir()) if p.is_dir() and p.name not in names]
    return names


def stage(drop: Path) -> Staging:
    raw = drop / "raw"
    albums: list[StagedAlbum] = []
    ignored: list[Ignored] = []
    moves: list[tuple[Path, Path]] = []
    roots: list[tuple[str, Path]] = []
    for item in _item_names(drop):
        root = raw / item
        found = _find(root) if root.is_dir() else []
        if not found:
            ignored.append(Ignored(item, "", NO_AUDIO))
            continue
        roots.append((item, root))
        for folder in sorted(found, key=lambda f: f.relative_to(root).parts):
            n = f"{len(albums) + 1:02d}"
            name = folder.name
            albums.append(StagedAlbum(n, name, item))
            moves.append((folder, drop / n / "drop" / "album" / name))
    for source, dest in sorted(moves, key=lambda m: len(m[0].parts), reverse=True):
        dest.parent.mkdir(parents=True)
        shutil.move(str(source), str(dest))
    for item, root in roots:
        if root.is_dir():
            ignored += [Ignored(item, p.relative_to(root).as_posix(), OUTSIDE)
                        for p in sorted(root.rglob("*")) if p.is_file()]
    shutil.rmtree(raw, ignore_errors=True)
    return Staging(albums, ignored)
