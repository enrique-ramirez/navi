"""Album units: what the engine finds under the root, and when it stops.

An album unit is one folder under `Letter/Artist/`, together with its `CDn`
subfolders. When its files disagree on the album tag, the folder holds more
than one album - a single filed together with the album it came from - and
the engine marks it `needs a person` rather than plan it as one release.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from musiclib import files, mapping


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


def _album_value(track: files.Track) -> str | None:
    values = track.tags.get(mapping.PICARD["album"][track.family])
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _disagreement(tracks: list[files.Track]) -> tuple[str | None, str | None]:
    values: list[str] = []
    for track in tracks:
        value = _album_value(track)
        if value is not None and value not in values:
            values.append(value)
    if len(values) <= 1:
        return None, None
    return "needs a person", "files disagree on the album tag: " + ", ".join(values)


def _unit_at(album_path: Path, root: Path) -> Unit:
    tracks: list[files.Track] = []
    unreadable: list[tuple[str, str]] = []
    others: list[str] = []

    for path in sorted(p for p in album_path.rglob("*") if p.is_file()):
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
    found = []
    for letter_dir in root.iterdir():
        if not letter_dir.is_dir():
            continue
        for artist_dir in letter_dir.iterdir():
            if not artist_dir.is_dir():
                continue
            for album_dir in artist_dir.iterdir():
                if not album_dir.is_dir():
                    continue
                found.append(_unit_at(album_dir, root))
    found.sort(key=lambda u: u.rel)
    return found
