"""Every drop and album the inbox holds, and what each offers, read from disk.

agitha keeps no database. `album.json` records what the queue last did, but
only the disk decides: a recorded `queued` or `identifying` counts only while
the live queue still holds the album, so one left by a dead process falls back
to what the folders show.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musiclib.batch.decisions import decisions_sha256
from musiclib.batch.job import Job

from . import drops, duplicates
from .paths import ALBUM_NUMBER, DROP_ID
from .refusal import Refusal

if TYPE_CHECKING:
    from .queue import Queue
    from .server import Config, Handler

BUSY_STATES = ("queued", "identifying", "applying")
#: The folders `musiclib.names.letter` makes.
LETTER_FOLDERS = re.compile(r"[A-Z#]")

ACTIONS = {
    "identify failed": ["retry", "discard"],
    "identify interrupted": ["retry", "discard"],
    "written, not moved": ["move", "discard"],
    "in the library": [],
}


def plan_entry(config: Config, drop: str, n: str) -> dict[str, Any] | None:
    """The first album of the job's `plan.json`, or None where there is no plan or it holds none."""
    plan = drops.read_json(config.jobs / f"agitha-{drop}-{n}" / "plan.json")
    albums = plan.get("albums") if plan else None
    return albums[0] if isinstance(albums, list) and albums and isinstance(albums[0], dict) else None


def staged_name(folder: Path) -> str | None:
    parent = folder / "drop" / "album"
    found = sorted(p.name for p in parent.iterdir() if p.is_dir()) if parent.is_dir() else []
    return found[0] if found else None


def _written(folder: Path) -> bool:
    """A finished album sits under a letter folder and `drop/` is gone."""
    if (folder / "drop").exists():
        return False
    return any(p.is_dir() and LETTER_FOLDERS.fullmatch(p.name) for p in folder.iterdir())


def _first(fields: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        if fields.get(key):
            return fields[key][0]
    return None


def _preview(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Title, artist, year and destination from the plan entry.

    They come from the neutral `fields` of the entry's first track: `album`,
    `albumartist` (else `artist`) and the year of `date`.
    """
    if entry is None:
        return {"title": None, "artist": None, "year": None, "destination": None}
    fields = next(iter(entry.get("fields", {}).values()), {})
    date = _first(fields, "date")
    return {"title": _first(fields, "album"), "artist": _first(fields, "albumartist", "artist"),
            "year": date[:4] if date else None, "destination": entry.get("destination")}


#: Holds that stop Approve; the other kinds only inform.
BLOCKING = ("decision", "error", "collision", "missing")


STALE = "the preview does not match the last decision; update the preview first"


def _decisions_changed(config: Config, drop: str, n: str) -> bool:
    """Whether `decisions.json` is no longer the file the plan was made from.

    A decision identify refuses is still written, and `batch apply` refuses an
    album whose decisions differ from the plan's `decisions_sha256`.
    """
    job = config.jobs / f"agitha-{drop}-{n}"
    plan = drops.read_json(job / "plan.json") or {}
    return decisions_sha256(Job(job)) != plan.get("decisions_sha256")


def approvable(config: Config, drop: str, n: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    """Whether the plan `entry` of album `n` may be approved: `ok`, and where not, a `reason` sentence, a `code` and the `hold`."""
    def no(reason: str, code: str, hold: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": False, "reason": reason, "code": code, "hold": hold}

    if entry is None:
        return no("no preview yet", "not-ready")
    if entry.get("decision") != "accept":
        return no("the preview has not been accepted yet", "not-accepted")
    if _decisions_changed(config, drop, n):
        return no(STALE, "not-accepted")
    # A missing track is named first: it is the one hold the owner cannot decide away.
    holds = entry.get("holds", [])
    for hold in sorted(holds, key=lambda h: h["kind"] != "missing"):
        if hold["kind"] in BLOCKING:
            detail = hold.get("detail")
            return no(f"held: {hold['kind']}: {detail}" if detail else f"held: {hold['kind']}", "held",
                      {"kind": hold["kind"], "detail": detail or ""})
    if not entry.get("destination"):
        return no("no destination", "not-ready")
    return {"ok": True, "reason": None, "code": None, "hold": None}


def _settle(recorded: str | None, busy: bool, written: bool, staged: bool, planned: bool) -> str:
    """The state of an album from what `album.json` recorded and what the disk shows; the disk wins."""
    if busy and recorded in BUSY_STATES:
        return recorded
    if recorded == "in the library":
        return recorded
    if written:
        return "written, not moved"
    if recorded == "apply failed":
        return recorded
    if not staged:
        return "incomplete"
    if planned:
        return "ready"
    if recorded == "identify failed":
        return recorded
    return "identify interrupted"


def album(config: Config, drop: str, n: str, queue: Queue | None = None) -> dict[str, Any] | None:
    """One `AlbumSummary` without `duplicate_of` (which needs its siblings), or None where `<n>/` is absent."""
    folder = config.inbox / drop / n
    if not folder.is_dir():
        return None
    record = drops.read_album(folder) or {}
    entry = plan_entry(config, drop, n)
    staged = staged_name(folder)
    busy = queue is not None and queue.busy(drop, n)
    state = _settle(record.get("state"), busy, _written(folder), staged is not None, entry is not None)
    if busy:
        actions: list[str] = []
    elif state == "ready":
        actions = (["approve"] if approvable(config, drop, n, entry)["ok"] else []) + ["reidentify", "discard"]
    elif state == "written, not moved" and duplicates.stranded(folder):
        actions = ["move"]
    else:
        actions = ACTIONS.get(state, ["discard"])
    return {
        "n": n,
        "name": record.get("name") or staged or n,
        "state": state,
        **_preview(entry),
        "duplicate_of": None,
        "stderr": record.get("stderr", ""),
        "error": record.get("error"),
        "busy": busy,
        "actions": list(actions),
    }


def known_album(config: Config, drop: str, n: str, queue: Queue) -> dict[str, Any]:
    """`album`, refusing with 404 where the drop or the album is unknown."""
    found = album(config, drop, n, queue) if drops.drop_dir(config, drop) is not None else None
    if found is None:
        raise Refusal(404, "No such album.")
    return found


def _mark_duplicates(albums: list[dict[str, Any]]) -> None:
    """Names, on each ready album, another ready one of the drop planning the same destination."""
    for one in albums:
        if one["state"] != "ready" or not one["destination"]:
            continue
        others = [a["n"] for a in albums
                  if a is not one and a["state"] == "ready" and a["destination"] == one["destination"]]
        one["duplicate_of"] = others[0] if others else None


def drop(config: Config, drop_id: str, queue: Queue | None = None,
         uploading: set[str] | frozenset[str] = frozenset(),
         extracting: set[str] | frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """One `Drop`, or None where the folder holds no `drop.json`."""
    found = drops.read_drop(config, drop_id)
    if found is None:
        return None
    folder = config.inbox / drop_id
    if not (drops.read_record(folder) or {}).get("done"):
        found["state"] = "uploading" if drop_id in uploading else "incomplete"
        return found
    if (folder / "raw").is_dir():
        # Only this process can be staging it; a `raw/` left by a dead one is a stopped drop.
        found["state"] = "extracting" if drop_id in extracting else "incomplete"
        if drop_id in extracting:
            found["actions"] = []
        return found
    numbers = sorted(p.name for p in folder.iterdir() if p.is_dir() and ALBUM_NUMBER.fullmatch(p.name))
    albums = [a for a in (album(config, drop_id, n, queue) for n in numbers) if a is not None]
    _mark_duplicates(albums)
    found["albums"] = albums
    if any(a["busy"] for a in albums):
        found["actions"] = []
    return found


def _order(drop_id: str) -> tuple[str, int]:
    return drop_id[:15], int(drop_id[16:] or 1)


def read(config: Config, queue: Queue | None = None,
         uploading: set[str] | frozenset[str] = frozenset(),
         extracting: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Every drop of the inbox, sorted by id.

    From disk alone, unless the live `queue` and the ids of drops this process
    is `uploading` or `extracting` are given; those are what disk cannot tell.
    """
    if not config.inbox.is_dir():
        return []
    ids = sorted((p.name for p in config.inbox.iterdir() if p.is_dir() and DROP_ID.fullmatch(p.name)),
                 key=_order)
    return [d for d in (drop(config, i, queue, uploading, extracting) for i in ids) if d is not None]


def listing(request: Handler, match: re.Match[str], config: Config) -> None:
    request.send_json(200, read(config, request.server.queue, request.server.uploading_now(),
                                   request.server.extracting))
