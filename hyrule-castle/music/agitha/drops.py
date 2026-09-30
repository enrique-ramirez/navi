"""Creating a drop, uploading its files, and reading one back.

A drop is `inbox/<id>/`: `drop.json` holds what the page said it would send,
`raw/<item>/<path>` holds the bytes as they arrive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .paths import DROP_ID, climbs

if TYPE_CHECKING:
    from .server import Config, Handler

#: Wider than `musiclib.files.AUDIO_EXTENSIONS` on purpose: a loose file is refused for any of these,
#: including formats the library cannot tag.
LOOSE_AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wma", ".wav", ".aiff", ".ape", ".wv", ".mpc")
KINDS = ("folder", "archive", "file")


def _unsafe(path: str) -> bool:
    """A path that is empty, absolute, or climbs with a `..` segment."""
    return not path or path.startswith(("/", "\\")) or climbs(path)


def _invalid(body: Any) -> str | None:
    """The sentence for the first thing wrong with a create request, or None."""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        return "A drop needs at least one item."
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or item.get("kind") not in KINDS \
                or not isinstance(item.get("files"), list):
            return "Each item needs a name, a kind and a list of files."
        name = item["name"]
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            return f"“{name}” is not a name this server can keep."
        for entry in item["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) \
                    or type(entry.get("size")) is not int or entry["size"] < 0:
                return f"A file of “{name}” has no path or size."
            if _unsafe(entry["path"]):
                return f"“{entry['path']}” in “{name}” is not a path this server will write."
        if item["kind"] == "file" and name.lower().endswith(LOOSE_AUDIO):
            return f"“{name}” is a loose audio file: drop the folder that holds it."
    return None


def _room_problem(config: Config, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The refusal body where the disk cannot hold twice the drop, or None."""
    needed = 2 * sum(f["size"] for item in items for f in item["files"])
    free = config.free_space(config.inbox)
    if needed <= free:
        return None
    return {
        "error": f"The drop needs {needed} bytes of room, twice its size, and the disk has {free} free.",
        "free": free, "needed": needed,
    }


def _claim_folder(config: Config, stem: str) -> str:
    """Makes `inbox/<stem>` or, where it exists, `inbox/<stem>-2`, `-3` and so on; returns the id."""
    drop, number = stem, 1
    while True:
        try:
            (config.inbox / drop).mkdir()
            return drop
        except FileExistsError:
            number += 1
            drop = f"{stem}-{number}"


def create(request: Handler, match: re.Match[str], config: Config) -> None:
    try:
        body = json.loads(request.read_body())
    except ValueError:
        request.fail(400, "The request is not JSON.")
        return
    problem = _invalid(body)
    if problem:
        request.fail(400, problem)
        return
    no_room = _room_problem(config, body["items"])
    if no_room:
        request.send_json(400, no_room)
        return
    now = config.now()
    drop = _claim_folder(config, now.strftime("%Y%m%d-%H%M%S"))
    (config.inbox / drop / "raw").mkdir()
    write_record(config.inbox / drop, {"started": now.isoformat(), "items": body["items"], "done": False})
    request.server.touch(drop)
    request.send_json(201, {"drop": drop})


def replace_bytes(path: Path, data: bytes) -> None:
    """Writes beside `path` and renames, so a poll never reads half a file."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as out:
        partial = Path(out.name)
        out.write(data)
    try:
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    """The SHA-256 hex of the file at `path`, read in chunks."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            sha.update(chunk)
    return sha.hexdigest()


def replace_json(path: Path, body: dict[str, Any]) -> None:
    replace_bytes(path, json.dumps(body).encode("utf-8"))


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def read_record(drop_dir: Path) -> dict[str, Any] | None:
    """`drop.json` of a drop folder, or None where it is absent or unreadable."""
    return read_json(drop_dir / "drop.json")


def write_record(drop_dir: Path, record: dict[str, Any]) -> None:
    replace_json(drop_dir / "drop.json", record)


def read_album(album_dir: Path) -> dict[str, Any] | None:
    """The server's `album.json` of an album folder, or None."""
    return read_json(album_dir / "album.json")


def write_album(album_dir: Path, **fields: Any) -> None:
    """Merges `fields` into the album's `album.json`, creating it where there is none."""
    album_dir.mkdir(parents=True, exist_ok=True)
    replace_json(album_dir / "album.json", {**(read_album(album_dir) or {}), **fields})


def drop_dir(config: Config, drop: str) -> Path | None:
    """The folder of drop `drop`, or None where the id is not one the server makes."""
    return config.inbox / drop if DROP_ID.fullmatch(drop) else None


def upload(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, item, path = match.group(1), match.group(2), match.group(3)
    record = read_record(config.inbox / drop)
    if record is None:
        request.fail(404, "No such drop.")
        return
    if _unsafe(path):
        request.fail(400, "That path is not one this server will write.")
        return
    listed = next((i for i in record["items"] if i["name"] == item), None)
    if listed is None or path not in {f["path"] for f in listed["files"]}:
        request.fail(400, "That file was not listed when the drop began.")
        return
    if record.get("done"):
        request.fail(409, "The drop is finished; it takes no more files.")
        return
    target = config.inbox / drop / "raw" / item / path
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with partial.open("wb") as out:
            whole = request.copy_body(out, lambda: request.server.touch(drop))
        if whole:
            os.replace(partial, target)
        request.server.touch(drop)
    finally:
        partial.unlink(missing_ok=True)
    if whole:
        request.send_empty(204)


def read_drop(config: Config, drop: str) -> dict[str, Any] | None:
    """One drop as `types.ts` defines `Drop`, with no albums; `state.read` fills them and the state.

    None where the folder holds no `drop.json`.
    """
    record = read_record(config.inbox / drop)
    if record is None:
        return None
    raw = config.inbox / drop / "raw"
    files = size = 0
    for item in record["items"]:
        for path in {f["path"] for f in item["files"]}:
            target: Path = raw / item["name"] / path
            if target.is_file():
                files += 1
                size += target.stat().st_size
    return {
        "id": drop,
        "state": "ready" if record.get("done") else "incomplete",
        "started": record["started"],
        "items": record["items"],
        "ignored": record.get("ignored", []),
        "refused": record.get("refused", []),
        "error": record.get("error"),
        "albums": [],
        "actions": ["discard"],
        "received": {"files": files, "bytes": size},
    }
