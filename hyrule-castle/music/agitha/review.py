"""The album view: `GET /api/drops/<drop>/albums/<n>` and the cover it shows.

The plan is read again on every request, so an identify that finished a
second ago shows. Files are found under `inbox/<drop>/<n>/`, not under the
plan's own `root`, which names the box's inbox.
"""

from __future__ import annotations

import base64
import binascii
import copy
import dataclasses
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote, urlsplit

import mutagen
import mutagen.asf
import mutagen.id3
import mutagen.mp4
from musiclib import images
from musiclib.mapping import READABLE, readable_name

from . import audio, drops, duplicates, ranges, state
from .refusal import BUSY, Refusal

if TYPE_CHECKING:
    from .queue import Queue
    from .server import Config, Handler

FAMILIES = ("id3", "vorbis", "mp4", "asf")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def _names() -> dict[str, dict[str, str]]:
    return {family: {key: readable_name(family, key) for row in READABLE.values()
                     if (key := row.get(family)) is not None} for family in FAMILIES}


def _tail(path: str, base: str) -> str:
    return PurePosixPath(path).relative_to(base).as_posix()


def cover_file(config: Config, drop: str, n: str, entry: dict[str, Any] | None) -> Path | None:
    """The image shown as the album's cover: the owner's where the plan's inputs name it, else the album folder's file the plan's `cover.jpg` is.

    A cover the plan will fetch from the Cover Art Archive has no file yet, so it gives None.
    """
    job = config.jobs / f"agitha-{drop}-{n}"
    named = ((entry or {}).get("inputs") or {}).get("owner_cover")
    path = job / named["path"] if isinstance(named, dict) and isinstance(named.get("path"), str) else None
    # Only the file the plan names counts; the folder may hold covers sent since or before.
    if path is not None and path.parent == job / "owner" and path.is_file():
        return path
    planned = (entry or {}).get("images", {}).get("cover.jpg")
    folder = ranges.album_folder(config, drop, n)
    if not planned or folder is None:
        return None
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file() and not path.is_symlink() \
                and path.stat().st_size == planned["length"] and drops.file_sha256(path) == planned["sha256"]:
            return path
    return None


def _cover(config: Config, drop: str, n: str, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    path = cover_file(config, drop, n, entry)
    if path is None:
        return None
    try:
        width, height, passes, problem = images.cover_check(path.read_bytes())
    except OSError:
        return None
    return {"url": f"/api/drops/{drop}/albums/{n}/cover", "width": width, "height": height,
            "passes": passes, "problem": problem}


def _decision(config: Config, drop: str, n: str, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    doc = drops.read_json(config.jobs / f"agitha-{drop}-{n}" / "decisions.json")
    albums = doc.get("albums") if doc else None
    found = albums.get(entry["source"]) if entry and isinstance(albums, dict) else None
    return found if isinstance(found, dict) else None


def _file_facts(config: Config, drop: str, n: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for planned in entry.get("files", []):
        path_now = _tail(planned["source"], entry["source"])
        found = audio.facts(config.inbox / drop / n / entry["source"] / path_now)
        if found is None:
            continue
        result.append({
            "position": planned["position"], "path_now": path_now, "path_after": planned["destination"],
            "format": found.format, "family": found.family, "lossless": found.lossless,
            "bitrate": found.bitrate, "sample_rate": found.sample_rate, "bit_depth": found.bit_depth,
            "channels": found.channels, "length": found.length, "size": found.size,
            "audio_url": f"/api/drops/{drop}/albums/{n}/audio/{quote(path_now)}",
        })
    return result


#: ID3 frames the engine keeps as text or decodes; every other frame is recorded as a digest.
_ID3_READABLE = ("POPM", "UFID", "COMM", "USLT")


def _binary_sizes(path: Path) -> dict[str, list[str]]:
    """`{key: ["<kind> (<N> bytes)"]}` for the binary tags of the file at `path`, as `musiclib.files.snapshot` keys them.

    The snapshot holds a digest for these, which says nothing to the owner;
    the kind and size are read from the file. Ogg's picture is text in the
    snapshot and is sized from that text instead (`_sized`).
    """
    try:
        found = mutagen.File(path)
    except (OSError, mutagen.MutagenError):
        return {}
    tags = getattr(found, "tags", None)
    if tags is None:
        return {}
    sizes: dict[str, list[str]] = {}
    if isinstance(tags, mutagen.id3.ID3):
        for frame in tags.values():
            if frame.FrameID not in _ID3_READABLE and not hasattr(frame, "text") and hasattr(frame, "data"):
                sizes[frame.HashKey] = [f"{frame.FrameID} ({len(frame.data)} bytes)"]
    elif isinstance(found, mutagen.mp4.MP4):
        covers = images.embedded_pictures(path)
        if covers:
            sizes["covr"] = [f"covr ({len(covers[0][1])} bytes)"]
    elif isinstance(found, mutagen.asf.ASF):
        pictures = images.embedded_pictures(path)
        if pictures:
            sizes["WM/Picture"] = [f"WM/Picture ({len(data)} bytes)" for _kind, data in pictures]
    return sizes


def _sized(tags: dict[str, list[str]], sizes: dict[str, list[str]]) -> dict[str, list[str]]:
    """`tags` with each binary value replaced by its kind and size, the others as they are."""
    shown = {key: sizes.get(key, values) for key, values in tags.items()}
    block = shown.get("metadata_block_picture")
    if block is not None and "metadata_block_picture" not in sizes:
        try:
            shown["metadata_block_picture"] = [
                f"metadata_block_picture ({len(base64.b64decode(value, validate=True))} bytes)" for value in block]
        except (binascii.Error, ValueError):
            pass
    return shown


def _with_sizes(config: Config, drop: str, n: str, entry: dict[str, Any]) -> dict[str, Any]:
    """A copy of the plan `entry` whose files show binary tags as kind and size; the entry itself is not touched."""
    shown = copy.deepcopy(entry)
    for planned in shown.get("files", []):
        path = config.inbox / drop / n / entry["source"] / _tail(planned["source"], entry["source"])
        sizes = _binary_sizes(path)
        planned["before"] = _sized(planned.get("before", {}), sizes)
        planned["after"] = _sized(planned.get("after", {}), sizes)
    return shown


def _landing(entry: dict[str, Any]) -> list[str]:
    """The album folder as it will land: kept files that follow it, the tracks, and the images the plan writes."""
    destination = entry["destination"]
    kept = (_tail(path, entry["source"]) for path in entry.get("kept", []))
    tracks = (_tail(planned["destination"], destination) for planned in entry.get("files", []))
    return sorted({*tracks, *kept, *entry.get("images", {})})


def _landed(config: Config, drop: str, n: str) -> dict[str, Any] | None:
    """The view of an album that landed and whose `<n>/` is gone, built from its job; None where it did not land.

    The files are no longer in the inbox, so `files`, `tree` and `extras_to` are empty.
    """
    landed = drops.read_json(config.jobs / f"agitha-{drop}-{n}" / "landed.json")
    if landed is None or landed.get("state") != "in the library":
        return None
    entry = state.plan_entry(config, drop, n)
    destination = entry.get("destination") if entry else None
    return {
        "drop": drop, "n": n, "name": PurePosixPath(destination).name if destination else n,
        "state": "in the library", "stderr": "", "error": None, "step": None, "file": None, "busy": False,
        "preview": entry, "files": [], "names": _names(), "library_path": landed.get("path"),
        "tree": [], "extras_to": [], "decision": None, "cover": None, "duplicate": None,
        "approvable": {"ok": False, "reason": "in the library", "code": "in-library", "hold": None},
    }


def _cover_url(drop: str, n: str, side: str) -> str:
    return f"/api/drops/{drop}/albums/{n}/duplicate/cover?side={side}"


def _new_folder(config: Config, drop: str, n: str, entry: dict[str, Any] | None) -> Path | None:
    """The folder the album's files are in: the staged one, or the finished one once apply has written it."""
    staged = ranges.album_folder(config, drop, n)
    if staged is not None or not entry or not entry.get("destination"):
        return staged
    finished = config.inbox / drop / n / entry["destination"]
    return finished if finished.is_dir() else None


def _duplicate(config: Config, drop: str, n: str, entry: dict[str, Any] | None, busy: bool) -> dict[str, Any] | None:
    """The comparison of the album with its copy in the library; none while a musiclib process rewrites the folder."""
    staged = None if busy else _new_folder(config, drop, n, entry)
    found = duplicates.find(config, entry, staged, lambda side: _cover_url(drop, n, side)) \
        if entry and staged is not None else None
    return dataclasses.asdict(found) if found else None


def album(config: Config, drop: str, n: str, queue: Queue | None = None) -> dict[str, Any] | None:
    """One `AlbumView`, or None where the drop or album is unknown."""
    if drops.drop_dir(config, drop) is None:
        return None
    summary = state.album(config, drop, n, queue)
    if summary is None:
        return _landed(config, drop, n)
    folder = config.inbox / drop / n
    record = drops.read_album(folder) or {}
    entry = state.plan_entry(config, drop, n)
    destination = entry.get("destination") if entry else None
    offered = state.approvable(config, drop, n, entry)
    if summary["busy"]:
        offered = {"ok": False, "reason": BUSY, "code": "busy", "hold": None}
    return {
        "drop": drop, "n": n, "name": summary["name"], "state": summary["state"],
        "stderr": summary["stderr"], "error": summary["error"],
        "step": record.get("step"), "file": record.get("file"),
        "busy": summary["busy"],
        "preview": _with_sizes(config, drop, n, entry) if entry else None,
        "files": _file_facts(config, drop, n, entry) if entry else [],
        "names": _names(),
        "library_path": str(config.library / destination) if destination else None,
        "tree": _landing(entry) if destination else [],
        # `plan.relocated`'s rule: an extra follows the album's tail under the extras root.
        "extras_to": [{"source": path, "path": str(config.extras / destination / _tail(path, entry["source"]))}
                      for path in entry.get("extras", [])] if destination else [],
        "decision": _decision(config, drop, n, entry),
        "cover": _cover(config, drop, n, entry),
        "duplicate": _duplicate(config, drop, n, entry, summary["busy"]),
        "approvable": offered,
    }


def show(request: Handler, match: re.Match[str], config: Config) -> None:
    view = album(config, match.group(1), match.group(2), request.server.queue)
    if view is None:
        raise Refusal(404, "No such album.")
    request.send_json(200, view)


def duplicate_cover(request: Handler, match: re.Match[str], config: Config) -> None:
    """The cover file of one side of the duplicate comparison, `?side=new` or `?side=library`.

    Only the two folders are needed, so nothing is compared. While a musiclib
    process rewrites the staged folder there is no cover, as `_duplicate` has no comparison.
    """
    drop, n = match.group(1), match.group(2)
    side = parse_qs(urlsplit(request.path).query).get("side", [""])[0]
    entry = state.plan_entry(config, drop, n)
    staged = None if request.server.queue.busy(drop, n) else _new_folder(config, drop, n, entry)
    held = duplicates.library_copy(config, entry) if entry and staged is not None else None
    folder = {"new": staged, "library": held}.get(side) if held is not None else None
    path = duplicates.cover_file(folder) if folder is not None else None
    if path is None:
        raise Refusal(404, "No cover.")
    request.send_file(path)


def cover(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    folder = drops.drop_dir(config, drop)
    path = cover_file(config, drop, n, state.plan_entry(config, drop, n)) \
        if folder is not None and (folder / n).is_dir() else None
    if path is None:
        raise Refusal(404, "No cover.")
    request.send_file(path)
