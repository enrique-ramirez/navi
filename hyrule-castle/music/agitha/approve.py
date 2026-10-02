"""What Approve, Move and Discard do to an album.

The approve route refuses from `state.approvable`, the one place that says
whether an album may be approved. Approve queues `batch apply`; the queue calls
`land` after a good apply, and Move calls it again for an album whose rename
failed. Where the plan's album is already in the library, Approve takes `keep`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import drops, duplicates, log, matches, state, swap
from .paths import ALBUM_NUMBER
from .refusal import BUSY, TAKEN, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

STRANDED = "The library's copy is set aside in this album's replaced/ folder; Move it into the library first."
UNFINISHED = "The new folder is in the library and its landing is unfinished; Move the album to finish it."


def _album_answer(state_: str, path: str | None, error: str | None) -> dict[str, Any]:
    return {"state": state_, "path": path, "error": error, "step": None, "file": None}


def _keep(request: Handler) -> str | None:
    """`keep` of the request body; a `Refusal` where the body is not one approve takes."""
    raw = request.read_body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("keep") not in (None, "new", "library"):
        raise Refusal(400, 'The body must be an object whose "keep", where present, is "new" or "library".')
    return body.get("keep")


def approve(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    keep = _keep(request)
    queue = request.server.queue
    found = state.known_album(config, drop, n, queue)
    if found["busy"]:
        raise Refusal(409, BUSY)
    entry = state.plan_entry(config, drop, n)
    folder = config.inbox / drop / n
    # A match replaces the folder it was copied from, never one a search finds.
    replaces = _replaces(folder)
    held = duplicates.library_copy(config, entry) if entry and replaces is None else None
    # Discarding needs only the copy in the library, not an accepted preview.
    if keep == "library":
        if held is None:
            raise Refusal(409, "There is no copy in the library to keep.")
        _remove_album(config, drop, n)
        _clear_empty_drop(config, drop)
        request.send_json(200, _album_answer("discarded", None, None))
        return
    if found["state"] != "ready":
        raise Refusal(409, f"An album that is {found['state']} cannot be approved.")
    offered = state.approvable(config, drop, n, entry)
    if not offered["ok"] or entry is None:
        raise Refusal(409, offered["reason"] or "This album cannot be approved.")
    target = config.library / entry["destination"]
    if replaces is not None:
        if (sentence := matches.refusal(config, folder, entry, replaces)) is not None:
            raise Refusal(409, sentence)
    elif held is not None and keep is None:
        raise Refusal(409, f"{TAKEN}: {held}; keep the new one or the one in the library.")
    elif held is None and target.exists():
        raise Refusal(409, f"{TAKEN}: {target}")
    # Written before the queue takes it, so a poll never sees the album `ready` while it is busy.
    drops.write_album(config.inbox / drop / n, state="applying", stderr="", error=None, step=None, file=None,
                      keep="new" if held is not None else None)
    if not queue.enqueue(drop, n, "apply"):
        raise Refusal(409, BUSY)
    log.write("queue-apply", f"{drop}/{n}", keep="new" if held is not None else None)
    request.send_json(202, _album_answer("applying", None, None))


def _unsettled(album: Path) -> str:
    """The sentence Discard is refused with for an album `swap.unsettled`."""
    return STRANDED if swap.stranded(album) else UNFINISHED


def _replaces(folder: Path) -> str | None:
    """The library path the match at the album folder `folder` replaces, or `None` for an upload."""
    return drops.replaces_of(drops.read_album(folder))


def _keeps_new(folder: Path) -> bool:
    return (drops.read_album(folder) or {}).get("keep") == "new"


def _copy_in_the_way(config: Config, folder: Path, entry: dict[str, Any] | None) -> Path | None:
    """A library copy of the album the owner has not chosen to replace, which a move would land beside or on."""
    if not entry or not entry.get("destination") or _keeps_new(folder) or _replaces(folder):
        return None
    return duplicates.library_copy(config, entry)


def _rename_in(config: Config, folder: Path, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """Renames the finished folder into the library; the `written, not moved` answer where a copy is in the way or the rename fails."""
    destination = entry["destination"] if entry else None
    source = folder / destination if destination else None
    target = config.library / destination if destination else None
    held = _copy_in_the_way(config, folder, entry)
    if held is not None:
        return drops.write_not_moved(folder, str(source), f"{TAKEN}: {held}")
    try:
        if source is None or target is None:
            raise OSError("the plan has no destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        return drops.write_not_moved(folder, str(source) if source else None,
                                     f"could not move {source} to {target}: {exc.strerror or exc}")
    return None


def _put_in_library(config: Config, drop: str, n: str, entry: dict[str, Any] | None,
                    replaces: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """`(answer, None)` where the album did not land, as a `written, not moved` album answers; else `(None, extras)`.

    `extras` is the sentence of the extras that could not follow the landing, or `None` where all of it was done.
    """
    folder = config.inbox / drop / n
    if swap.is_committed(folder):
        # A stop after the landing left the new folder in the library and the old copy half deleted: only what follows a landing is left.
        destination = entry["destination"] if entry else None
        if replaces is not None and destination:
            return None, swap.after_landing(config.library, config.extras, replaces, destination)
        return None, None
    if replaces is not None and entry is not None:
        return matches.land(config, drop, n, entry, replaces)
    keeps = bool(entry and entry["destination"]) and _keeps_new(folder)
    old = duplicates.library_copy(config, entry) if keeps and entry else None
    if old is not None or (keeps and swap.stranded(folder)):
        failed = duplicates.replace(config, drop, n, entry, old)
        if failed is None:
            log.write("replace-duplicate", entry["destination"], drop=f"{drop}/{n}",
                      was=old.relative_to(config.library).as_posix() if old is not None else None)
        return failed, None
    return _rename_in(config, folder, entry), None


def land(config: Config, drop: str, n: str) -> dict[str, Any]:
    """Renames the finished folder of album `n` into the library and clears it from the inbox.

    One `os.rename` and never a copy: where the rename fails the album stays
    `written, not moved` with both paths in `error`, and Move calls this again.
    The job keeps `landed.json`, since `<n>/`, which holds `album.json`, goes.
    """
    folder = config.inbox / drop / n
    entry = state.plan_entry(config, drop, n)
    failed, note = _put_in_library(config, drop, n, entry, _replaces(folder))
    if failed is not None:
        log.failed("land", f"{drop}/{n}", failed["error"])
        return failed
    destination = entry["destination"] if entry else None
    target = config.library / destination if destination else None
    drops.replace_json(config.jobs / f"agitha-{drop}-{n}" / "landed.json",
                       {"state": "in the library", "path": str(target)})
    log.write("land", f"{drop}/{n}", path=destination, note=note)
    shutil.rmtree(folder)
    _clear_empty_drop(config, drop)
    return _album_answer("in the library", str(target), note)


def _clear_empty_drop(config: Config, drop: str) -> None:
    """Removes the drop folder once no album folder is left in it."""
    folder = config.inbox / drop
    if folder.is_dir() and not any(p.is_dir() and ALBUM_NUMBER.fullmatch(p.name) for p in folder.iterdir()):
        shutil.rmtree(folder)
        log.write("clear-drop", drop)


def move(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    request.read_body()
    found = state.known_album(config, drop, n, request.server.queue)
    if found["busy"] or found["state"] != "written, not moved":
        raise Refusal(409, f"An album that is {found['state']} cannot be moved.")
    # A copy that reached the library since apply is the owner's to choose about, so the album view offers it.
    held = _copy_in_the_way(config, config.inbox / drop / n, state.plan_entry(config, drop, n))
    if held is not None:
        raise Refusal(409, f"{TAKEN}: {held}")
    request.send_json(200, land(config, drop, n))


def _remove_album(config: Config, drop: str, n: str) -> None:
    shutil.rmtree(config.inbox / drop / n, ignore_errors=True)
    shutil.rmtree(config.jobs / f"agitha-{drop}-{n}", ignore_errors=True)
    log.write("discard-album", f"{drop}/{n}")


def discard_album(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    folder = drops.drop_dir(config, drop)
    if folder is None or not (folder / n).is_dir():
        raise Refusal(404, "No such album.")
    if request.server.queue.busy(drop, n):
        raise Refusal(409, BUSY)
    if swap.unsettled(folder / n):
        raise Refusal(409, _unsettled(folder / n))
    _remove_album(config, drop, n)
    _clear_empty_drop(config, drop)
    request.send_json(200, {"state": "discarded"})


def discard_drop(request: Handler, match: re.Match[str], config: Config) -> None:
    drop = match.group(1)
    folder = drops.drop_dir(config, drop)
    if folder is None or not folder.is_dir():
        raise Refusal(404, "No such drop.")
    if request.server.queue.busy_drop(drop):
        raise Refusal(409, BUSY)
    numbers = [p.name for p in folder.iterdir() if p.is_dir() and ALBUM_NUMBER.fullmatch(p.name)]
    for number in numbers:
        if swap.unsettled(folder / number):
            raise Refusal(409, _unsettled(folder / number))
    for album in numbers:
        _remove_album(config, drop, album)
    shutil.rmtree(folder, ignore_errors=True)
    log.write("discard-drop", drop, albums=len(numbers))
    request.send_json(200, {"state": "discarded"})
