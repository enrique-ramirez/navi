"""Delete album: a library album folder removed for good, with its extras."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from . import drops, library, log, matches, swap
from .refusal import BEING_SAVED, OPEN_IN_REVIEW, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler


def _size(folder: Path) -> tuple[int, int]:
    count = total = 0
    for parent, _dirs, names in os.walk(folder):
        for name in names:
            count += 1
            total += os.lstat(Path(parent) / name).st_size
    return count, total


def delete(request: Handler, match: re.Match[str], config: Config) -> None:
    body = request.read_json()
    if not (isinstance(body, dict) and isinstance(body.get("path"), str)):
        raise Refusal(400, 'The body must be an object with the "path" of a library album.')
    path = body["path"]
    parts = path.split("/")
    if len(parts) != 3:
        raise Refusal(404, "No such folder.")
    folder = library.open_unlinked(config, *parts)
    root = library.library_root(config)
    with matches.starting:
        if request.server.queue.busy_library(path):
            raise Refusal(409, BEING_SAVED)
        if drops.open_match(config, path) is not None:
            raise Refusal(409, OPEN_IN_REVIEW)
        files, size = _size(folder)
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            log.failed("delete-album", path, exc.strerror or exc)
            raise Refusal(500, f"could not delete {path}: {exc.strerror or exc}") from None
    swap.prune(folder.parent, root)
    extras = config.extras / path
    note = None
    if extras.exists():
        try:
            shutil.rmtree(extras)
            swap.prune(extras.parent, config.extras)
        except OSError as exc:
            note = f"its extras could not be deleted: {exc.strerror or exc}"
    log.write("delete-album", path, files=files, bytes=size, note=note)
    request.send_json(200, {"deleted": path, "note": note})
