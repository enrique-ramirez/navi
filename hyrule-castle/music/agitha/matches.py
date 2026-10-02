"""Match to MusicBrainz: a library album copied into the inbox as a drop of one album, reviewed as an upload is.

The copy is staged where `albums.stage` puts an upload, so identify, the
decisions, apply and the review page treat it as any album. Its `album.json`
says which library folder it `replaces`, and what the files of that folder
were (`copied`) when the copy was taken. Whether a match is open is read from
`album.json` every time, so a restart forgets nothing.
"""

from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import drops, duplicates, library, log, planpaths, swap
from .refusal import BEING_SAVED, HOLDS_A_LINK, MATCH_CHANGED, TAKEN, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

#: A drop of one album, which is the first.
N = "01"

#: Held from the look for an open match to the album.json that makes the new one open.
_starting = threading.Lock()


def start(request: Handler, match: re.Match[str], config: Config) -> None:
    body = request.read_json()
    if not (isinstance(body, dict) and isinstance(body.get("path"), str)):
        raise Refusal(400, 'The body must be an object with the "path" of a library album.')
    path = body["path"]
    folder = library.open_album(config, path)
    with _starting:
        if request.server.queue.busy_library(path):
            raise Refusal(409, BEING_SAVED)
        found = drops.open_match(config, path)
        if found is not None:
            request.send_json(200, found)
            return
        if any(entry.is_symlink() for entry in folder.rglob("*")):
            raise Refusal(409, HOLDS_A_LINK)
        drop = _copy_into_a_drop(config, path, folder)
    log.write("start-match", path, drop=f"{drop}/{N}")
    request.server.queue.enqueue(drop, N, "identify")
    request.send_json(201, {"drop": drop, "n": N})


def _copy_into_a_drop(config: Config, path: str, folder: Path) -> str:
    """Copies `folder` into a new drop of one album and returns the drop's id; the library is only read.

    `album.json` is written first, so the match is open before the copy is
    whole and a save cannot begin over the album meanwhile. `drop.json` is
    written last, as nothing lists the drop before it is complete.
    """
    now = config.now()
    config.inbox.mkdir(parents=True, exist_ok=True)
    drop = drops.claim_drop(config, now)
    base, album = config.inbox / drop, config.inbox / drop / N
    try:
        drops.write_album(album, n=N, name=folder.name, item=folder.name, state="queued", stderr="", error=None,
                          replaces=path, copied=swap.stamps(folder))
        shutil.copytree(folder, album / "drop" / "album" / folder.name, symlinks=True)
        drops.write_record(base, {"started": now.isoformat(), "done": True, "ignored": [], "refused": [],
                                  "error": None, "items": [{"name": folder.name, "kind": "folder", "files": []}]})
    except BaseException as exc:
        shutil.rmtree(base, ignore_errors=True)
        log.failed("start-match", path, f"{type(exc).__name__}: {exc}")
        raise
    return drop


def _copied(album: Path) -> Any:
    """The stamps of the library folder as `album.json` recorded them when the copy was taken."""
    return (drops.read_album(album) or {}).get("copied")


def refusal(config: Config, album: Path, entry: dict[str, Any], replaces: str) -> str | None:
    """The sentence Approve is refused with for the match at `album`, which replaces `replaces`, or `None`.

    A taken path comes first, then a changed copy.
    """
    destination = entry["destination"]
    if destination != replaces and planpaths.is_taken(library.library_root(config), destination,
                                                      config.library / replaces):
        return f"{TAKEN}: {destination}"
    if swap.stamps(config.library / replaces) != _copied(album):
        return MATCH_CHANGED
    return None


def land(config: Config, drop: str, n: str, entry: dict[str, Any],
         replaces: str) -> tuple[dict[str, Any] | None, str | None]:
    """Swaps the folder the match replaces, `replaces`, for the finished one, which lands at the plan's destination.

    `(None, extras)` where the new folder is in the library and the old one
    is gone, with `extras` the sentence of extras that could not follow. The
    answer of a `written, not moved` album, already written to its `album.json`,
    where it did not, with the library as it was and no folder made for it.
    """
    folder = config.inbox / drop / n
    old, unchanged = None, None
    # Where an earlier run set the old folder aside, the swap resumes from its record.
    if not swap.stranded(folder):
        if (sentence := refusal(config, folder, entry, replaces)) is not None:
            return drops.write_not_moved(folder, str(folder / entry["destination"]), sentence), None
        old, unchanged = config.library / replaces, swap.Unchanged(_copied(folder), MATCH_CHANGED)
    failed = duplicates.replace(config, drop, n, entry, old, unchanged)
    if failed is not None:
        return failed, None
    log.write("land-match", replaces, to=entry["destination"], drop=f"{drop}/{n}")
    return None, swap.after_landing(config.library, config.extras, replaces, entry["destination"])
