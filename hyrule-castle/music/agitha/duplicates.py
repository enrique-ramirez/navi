"""An album already in the library: finding it, comparing the copies, keeping the new one.

`find` and `compare` are read-only. `replace` is the moves of Keep the new
one; it renames with `os.rename` and never copies, so a failure leaves each
folder whole on one side or the other.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from musiclib import files, images, units
from musiclib.mapping import PICARD

from . import audio, drops

if TYPE_CHECKING:
    from .server import Config

RULES = (
    ("more audio files", "more-files", lambda copy: copy.files),
    ("lossless over lossy", "lossless", lambda copy: copy.lossless),
    ("higher bit depth", "bit-depth", lambda copy: copy.bit_depth or 0),
    ("higher sample rate", "sample-rate", lambda copy: copy.sample_rate),
    ("higher average bitrate", "bitrate", lambda copy: copy.bitrate),
)
TIE = "the copy in the library"

LENGTH_TOLERANCE_SECONDS = 2.0

COVER_NAMES = ("cover.jpg", "folder.jpg", "front.jpg")
_YEAR = re.compile(r"\(\d{4}\)\s+")
_TYPE = re.compile(r"\[(?:EP|Single|Mixtape|Live)\]\s+")
_EDITION = re.compile(r"\s+\[[^\]]*\]$")
_DISC = re.compile(r"CD\d+", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class CoverInfo:
    url: str
    width: int
    height: int


@dataclass(frozen=True)
class Copy:
    folder: str
    format: str
    lossless: bool
    bit_depth: int | None
    sample_rate: int
    bitrate: int
    files: int
    length: float
    size: int
    cover: CoverInfo | None
    release_id: str | None
    album: str | None
    album_artist: str | None
    date: str | None
    label: str | None
    catalog: str | None
    country: str | None
    media: str | None
    discs: int
    bitrate_min: int
    bitrate_max: int
    encoder: str | None
    tag_count: float


@dataclass(frozen=True)
class Tracks:
    paired: int
    length_differs: int
    only_new: int
    only_library: int
    max_length_diff: float


@dataclass(frozen=True)
class Comparison:
    new: Copy
    library: Copy
    recommended: str
    rule: str
    #: `rule` as a code the page translates; `library` where nothing differed.
    rule_code: str
    tracks: Tracks


@dataclass(frozen=True)
class _Track:
    facts: audio.Facts
    tags: dict[str, list[str]]
    encoder: str | None
    disc: int | str
    number: int | None

    @property
    def position(self) -> tuple[int | str, int] | None:
        return None if self.number is None else (self.disc, self.number)


def _bare(name: str) -> str:
    """`name` without its year, its type prefix and its trailing edition, for comparing two folders' names."""
    for pattern in (_YEAR, _TYPE):
        found = pattern.match(name)
        if found:
            name = name[found.end():]
    return _EDITION.sub("", name).casefold()


def _tracks(folder: Path) -> list[Path]:
    """The audio files of `folder`, in its disc folders too, in path order."""
    return [p for p in sorted(folder.rglob("*"))
            if p.suffix.lower() in files.AUDIO_EXTENSIONS and p.is_file() and not p.is_symlink()]


def _group_of(folder: Path) -> str | None:
    """The release group id the first audio file carrying one names, read with its own family's key."""
    for path in _tracks(folder):
        try:
            track = files.read(path)
        except files.Unreadable:
            continue
        key = PICARD["release group id"][track.family]
        value = track.tags.get(key) if key else None
        if value:
            return value[0].casefold()
    return None


def _planned_group(entry: dict[str, Any]) -> str | None:
    keys = {key.casefold() for key in PICARD["release group id"].values() if key}
    for planned in entry.get("files", []):
        for key, value in planned.get("after", {}).items():
            if key.casefold() in keys and value:
                return value[0].casefold()
    return None


def library_copy(config: Config, entry: dict[str, Any]) -> Path | None:
    """The folder under the planned artist folder that holds the entry's album already, or None.

    Where several do, the one at the planned destination comes first, since
    that is the one the new folder would land on; then the first by name.
    """
    destination = entry.get("destination")
    parts = PurePosixPath(destination).parts if destination else ()
    if len(parts) < 3:
        return None
    artist = config.library / parts[0] / parts[1]
    if not artist.is_dir():
        return None
    name, group = _bare(parts[2]), _planned_group(entry)

    def same_album(folder: Path) -> bool:
        theirs = _group_of(folder) if group is not None else None
        if theirs is not None:
            # Two release groups can share a title, as Weezer's coloured albums do.
            return theirs == group
        return _bare(folder.name) == name

    matches = [p for p in sorted(artist.iterdir()) if p.is_dir() and same_album(p)]
    matches.sort(key=lambda p: p.name != parts[2])
    return matches[0] if matches else None


def _number(tags: dict[str, list[str]], key: str | None) -> int | None:
    values = tags.get(key) if key else None
    found = _LEADING_NUMBER.search(values[0]) if values else None
    return int(found.group()) if found else None


def _disc(tags: dict[str, list[str]], family: str, rel: PurePosixPath) -> int | str:
    tagged = _number(tags, units.DISC_NUMBER_KEY.get(family))
    if tagged is not None:
        return tagged
    if len(rel.parts) < 2:
        return 1
    folder = units.DISC_FOLDER.match(rel.parts[0])
    return int(folder.group(1)) if folder else rel.parts[0]


def _read(path: Path, folder: Path) -> _Track | None:
    try:
        found = files.load(path)
        facts = audio.facts_of(found, path)
    except (files.Unreadable, OSError):
        # A file that went between listing and reading: apply moves an album's files while its view is read.
        return None
    if facts is None:
        return None
    tags = files.snapshot(found, facts.family)
    number = _number(tags, units.TRACK_NUMBER_KEY.get(facts.family))
    disc = _disc(tags, facts.family, PurePosixPath(path.relative_to(folder).as_posix()))
    return _Track(facts, tags, audio.encoder(found), disc, number)


def _first_tag(track: _Track | None, field: str) -> str | None:
    key = PICARD[field].get(track.facts.family) if track else None
    values = track.tags.get(key) if key else None
    return values[0] if values else None


def cover_file(folder: Path) -> Path | None:
    """The folder's `cover.jpg`, else `folder.jpg`, else `front.jpg`, whatever its case."""
    try:
        present = {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        # The folder went while it was read: apply and land move it.
        return None
    return next((present[name] for name in COVER_NAMES if name in present), None)


def _cover(folder: Path, url: str | None) -> CoverInfo | None:
    path = cover_file(folder)
    if path is None:
        return None
    try:
        width, height, _passes, _problem = images.cover_check(path.read_bytes())
    except OSError:
        return None
    return CoverInfo(url or str(path), width, height)


def copy_of(folder: Path, cover_url: str | None = None) -> Copy:
    """The facts of the album folder `folder`; `size` counts every file, the others audio only."""
    return _copy(folder, _read_all(folder), cover_url)


def _read_all(folder: Path) -> list[_Track]:
    return [t for t in (_read(p, folder) for p in _tracks(folder)) if t is not None]


def _copy(folder: Path, tracks: list[_Track], cover_url: str | None) -> Copy:
    found = [t.facts for t in tracks]
    formats = {f.format for f in found}
    depths = [f.bit_depth for f in found if f.bit_depth is not None]
    first = tracks[0] if tracks else None
    return Copy(
        folder=str(folder),
        format=formats.pop() if len(formats) == 1 else "mixed" if formats else "",
        lossless=bool(found) and all(f.lossless for f in found),
        bit_depth=min(depths) if depths else None,
        sample_rate=min((f.sample_rate for f in found), default=0),
        bitrate=round(sum(f.bitrate for f in found) / len(found)) if found else 0,
        files=len(found),
        length=sum(f.length for f in found),
        size=sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()),
        cover=_cover(folder, cover_url),
        release_id=_first_tag(first, "release id"),
        album=_first_tag(first, "album"),
        album_artist=_first_tag(first, "albumartist"),
        date=_first_tag(first, "date"),
        label=_first_tag(first, "label"),
        catalog=_first_tag(first, "catalognumber"),
        country=_first_tag(first, "releasecountry"),
        media=_first_tag(first, "media"),
        discs=len({t.disc for t in tracks}),
        bitrate_min=min((f.bitrate for f in found), default=0),
        bitrate_max=max((f.bitrate for f in found), default=0),
        encoder=next((t.encoder for t in tracks if t.encoder), None),
        tag_count=round(sum(len(t.tags) for t in tracks) / len(tracks), 1) if tracks else 0,
    )


def _pairs(new: list[_Track], library: list[_Track]) -> list[tuple[_Track, _Track]]:
    sides = []
    for tracks in (new, library):
        positions = [t.position for t in tracks]
        if None in positions or len(set(positions)) != len(positions):
            return list(zip(new, library))
        sides.append({t.position: t for t in tracks})
    ours, theirs = sides
    return [(ours[key], theirs[key]) for key in ours if key in theirs]


def _track_counts(new: list[_Track], library: list[_Track]) -> Tracks:
    pairs = _pairs(new, library)
    diffs = [abs(a.facts.length - b.facts.length) for a, b in pairs]
    return Tracks(paired=len(pairs), length_differs=sum(d > LENGTH_TOLERANCE_SECONDS for d in diffs),
                  only_new=len(new) - len(pairs), only_library=len(library) - len(pairs),
                  max_length_diff=max(diffs, default=0.0))


def compare(new_folder: Path, library_folder: Path,
            cover_url: Callable[[str], str] | None = None) -> Comparison:
    """`cover_url(side)` names where each copy's cover is served; without it a cover's url is its path."""
    ours, theirs = _read_all(new_folder), _read_all(library_folder)
    new = _copy(new_folder, ours, cover_url("new") if cover_url else None)
    library = _copy(library_folder, theirs, cover_url("library") if cover_url else None)
    tracks = _track_counts(ours, theirs)
    for rule, code, measure in RULES:
        mine, other = measure(new), measure(library)
        if mine != other:
            return Comparison(new, library, "new" if mine > other else "library", rule, code, tracks)
    return Comparison(new, library, "library", TIE, "library", tracks)


def find(config: Config, entry: dict[str, Any], new_folder: Path | None = None,
         cover_url: Callable[[str], str] | None = None) -> Comparison | None:
    """The comparison of the staged album with its copy in the library, or None where there is no copy.

    Without `new_folder` the staged folder is looked for by the entry's
    `source` under the inbox, as the entry carries no root.
    """
    found = library_copy(config, entry)
    if found is None:
        return None
    if new_folder is None:
        staged = sorted(config.inbox.glob(f"*/*/{entry['source']}"))
        if not staged:
            raise FileNotFoundError(f"the staged folder {entry['source']} is not in the inbox")
        new_folder = staged[0]
    return compare(new_folder, found, cover_url)


#: Each file of a folder by its path: its SHA-256 and, for audio, its length.
_Record = dict[str, tuple[str, float | None]]


class _Problem(Exception):
    def __init__(self, step: int, file: Path, reason: str) -> None:
        super().__init__(reason)
        self.step, self.file, self.reason = step, file, reason


def _length(path: Path) -> float | None:
    found = audio.facts(path) if path.suffix.lower() in files.AUDIO_EXTENSIONS else None
    return found.length if found else None


def _record(folder: Path) -> _Record:
    """Step 1: every file's SHA-256 by its path in `folder`, and an audio file's length as mutagen reads it now."""
    return {p.relative_to(folder).as_posix(): (drops.file_sha256(p), _length(p))
            for p in sorted(folder.rglob("*")) if p.is_file()}


def stranded(folder: Path) -> bool:
    """Whether the album folder `folder` holds a library copy set aside, which only Move may settle."""
    aside = folder / "replaced"
    return aside.is_dir() and any(p.is_file() for p in aside.rglob("*"))


def _saved(folder: Path) -> tuple[str, _Record] | None:
    """The library copy's path and the step 1 record an earlier run left in `replaced.json`, where it is stranded."""
    body = drops.read_json(folder / "replaced.json")
    if body is None or not stranded(folder):
        return None
    try:
        return body["copy"], {name: (digest, length) for name, (digest, length) in body["files"].items()}
    except (KeyError, TypeError, ValueError):
        return None


def _verify(folder: Path, recorded: _Record) -> None:
    """Step 4: the names, the hashes, and that each audio file opens with the length step 1 read, within 0.1 s.

    The plan holds no length per file, so the length compared is the finished
    folder's own, taken before it moved.
    """
    now = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    for name in sorted(set(recorded) - now):
        raise _Problem(4, folder / name, "the file is missing after the move")
    for name in sorted(now - set(recorded)):
        raise _Problem(4, folder / name, "the file was not in the finished folder")
    for name, (digest, length) in sorted(recorded.items()):
        path = folder / name
        try:
            if drops.file_sha256(path) != digest:
                raise _Problem(4, path, "its SHA-256 differs from the finished folder's")
        except OSError as exc:
            raise _Problem(4, path, f"could not be read: {exc.strerror or exc}") from exc
        if path.suffix.lower() in files.AUDIO_EXTENSIONS:
            found = _length(path)
            if found is None or length is None or abs(found - length) > 0.1:
                raise _Problem(4, path, "it does not open, or its length changed")


def _prune(start: Path, stop: Path) -> None:
    """Removes the empty folders from `start` up to, not including, `stop`."""
    for parent in (start, *start.parents):
        if parent == stop:
            return
        try:
            parent.rmdir()
        except OSError:
            return


def _fail(folder: Path, source: Path, problem: _Problem, outcome: str) -> dict[str, Any]:
    error = f"Step {problem.step} failed at {problem.file}: {problem.reason}. {outcome}"
    drops.write_album(folder, state="written, not moved", error=error, step=problem.step, file=str(problem.file))
    return {"state": "written, not moved", "path": str(source), "error": error,
            "step": problem.step, "file": str(problem.file)}


def _set_aside(library_folder: Path, aside: Path) -> None:
    """Step 2."""
    try:
        aside.parent.mkdir(parents=True, exist_ok=True)
        os.rename(library_folder, aside)
    except OSError as exc:
        raise _Problem(2, library_folder, f"could not be set aside: {exc.strerror or exc}") from exc


def _begin(folder: Path, source: Path, library_folder: Path, aside: Path, relative: str) -> _Record:
    """Steps 1 and 2: the record of the new folder, saved, and then the library's copy set aside."""
    try:
        recorded = _record(source)
        drops.replace_json(folder / "replaced.json", {"copy": relative, "files": recorded})
    except OSError as exc:
        raise _Problem(1, Path(exc.filename) if exc.filename else source,
                       f"could not be read or recorded: {exc.strerror or exc}") from exc
    _set_aside(library_folder, aside)
    return recorded


def _move_in(source: Path, target: Path) -> None:
    """Step 3."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        raise _Problem(3, target, f"could not be moved into the library: {exc.strerror or exc}") from exc


def _put_back(folder: Path, source: Path, aside: Path, library_folder: Path, problem: _Problem) -> dict[str, Any]:
    """The undo of step 2, and the answer for `problem`."""
    try:
        os.rename(aside, library_folder)
    except OSError as exc:
        return _fail(folder, source, problem,
                     f"The library's copy could not be put back and is at {aside}: {exc.strerror or exc}.")
    _prune(aside.parent, folder)
    (folder / "replaced.json").unlink(missing_ok=True)
    return _fail(folder, source, problem, "The library's copy is back where it was.")


def replace(config: Config, drop: str, n: str, entry: dict[str, Any],
            library_folder: Path | None) -> dict[str, Any] | None:
    """Swaps the library's copy `library_folder` for the finished folder of album `n`, in five steps.

    1 records the new folder's hashes and lengths in `replaced.json`, 2 sets
    the library's copy aside, 3 renames the new folder in, 4 verifies it, 5
    deletes the copy set aside. Where an earlier run left the copy set aside
    (`stranded`), this one resumes at step 3 against that record and
    `library_folder` is not used.

    None where the new folder is in the library and the old copy is deleted.
    Otherwise the answer of a `written, not moved` album, already written to
    its `album.json`, with the library's copy back where it was where it could
    be put back.
    """
    folder = config.inbox / drop / n
    source = folder / entry["destination"]
    target = config.library / entry["destination"]
    saved = _saved(folder)
    if saved is not None:
        relative, recorded = saved
        library_folder = config.library / relative
        aside = folder / "replaced" / relative
    else:
        assert library_folder is not None
        relative = library_folder.relative_to(config.library).as_posix()
        aside = folder / "replaced" / relative
        try:
            recorded = _begin(folder, source, library_folder, aside, relative)
        except _Problem as problem:
            _prune(aside.parent, folder)
            (folder / "replaced.json").unlink(missing_ok=True)
            return _fail(folder, source, problem, "Nothing was moved.")

    try:
        _move_in(source, target)
    except _Problem as problem:
        return _put_back(folder, source, aside, library_folder, problem)

    try:
        _verify(target, recorded)
    except _Problem as problem:
        try:
            os.rename(target, source)
        except OSError as exc:
            return _fail(folder, source, problem,
                         f"The new album could not be moved out of the library ({exc.strerror or exc}); "
                         f"the library's copy stays at {aside}.")
        return _put_back(folder, source, aside, library_folder, problem)

    shutil.rmtree(folder / "replaced", ignore_errors=True)
    (folder / "replaced.json").unlink(missing_ok=True)
    return None
