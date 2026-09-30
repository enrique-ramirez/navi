"""Playing a staged track: `GET /api/drops/<drop>/albums/<n>/audio/<path>` with byte ranges.

Only a file under `inbox/<drop>/<n>/drop/album/<name>/` is served. Once the
album has moved into the library that folder is gone, and the url is 404.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING

from . import drops, state

if TYPE_CHECKING:
    from .server import Config, Handler

CHUNK = 64 * 1024
CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wma": "audio/x-ms-wma",
}
RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def album_folder(config: Config, drop: str, n: str) -> Path | None:
    """The staged album folder, or None where the drop or album is unknown or has left `drop/`."""
    folder = drops.drop_dir(config, drop)
    if folder is None or not (folder / n).is_dir():
        return None
    name = state.staged_name(folder / n)
    return folder / n / "drop" / "album" / name if name else None


class Unsatisfiable(Exception):
    """The range starts beyond the end of the file."""


def _span(header: str | None, size: int) -> tuple[int, int] | None:
    """The inclusive byte span asked for, or None to answer the whole file; raises `Unsatisfiable`."""
    found = RANGE.fullmatch(header.strip()) if header else None
    if found is None or found.group(1) == found.group(2) == "":
        # RFC 9110 lets a server answer whole a Range it does not serve as one.
        return None
    first, last = found.groups()
    if first == "":
        wanted = int(last)
        if not wanted or not size:
            raise Unsatisfiable
        return max(size - wanted, 0), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return None
    if start >= size:
        raise Unsatisfiable
    return start, min(end, size - 1)


def audio(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n, rel = match.group(1), match.group(2), match.group(3)
    folder = album_folder(config, drop, n)
    if folder is None:
        request.fail(404, "No such album.")
        return
    root = folder.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        request.fail(404, "No such file.")
        return
    size = target.stat().st_size
    try:
        span = _span(request.headers.get("Range"), size)
    except Unsatisfiable:
        request.send_response(416)
        request.send_header("Content-Range", f"bytes */{size}")
        request.send_header("Content-Length", "0")
        request.end_headers()
        return
    content_type = CONTENT_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] \
        or "application/octet-stream"
    first, last = span if span else (0, size - 1)
    request.send_response(206 if span else 200)
    request.send_header("Content-Type", content_type)
    request.send_header("Accept-Ranges", "bytes")
    if span:
        request.send_header("Content-Range", f"bytes {first}-{last}/{size}")
    left = last + 1 - first
    request.send_header("Content-Length", str(left))
    request.end_headers()
    if request.command == "HEAD":
        return
    try:
        with target.open("rb") as handle:
            handle.seek(first)
            while left > 0 and (chunk := handle.read(min(CHUNK, left))):
                request.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        request.close_connection = True
