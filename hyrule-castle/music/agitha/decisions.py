"""The owner's decision on an album and the owner's cover.

`POST .../decision` validates a `Decision` (`ui/src/shared/api/types.ts`),
writes the job's `decisions.json` keyed by the preview's `source`, and queues
identify. `PUT .../cover` keeps an image in the job's `owner/` and answers the
library's cover test. What only the engine can judge (a raw key it cannot
write, a release it cannot read) is left to identify, whose message the album
then shows.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musiclib import images, strays
from musiclib.genres import NEITHER, SOUNDTRACK, VIDEO_GAME_MUSIC

from . import drops, state
from .refusal import BUSY, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

GAMES = (VIDEO_GAME_MUSIC, SOUNDTRACK, NEITHER)
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
OWNER_COVER = re.compile(r"owner/[^/\\]+")


def _invalid(body: Any, entry: dict[str, Any], job: Path) -> str | None:
    """The sentence for the first thing wrong with a decision, or None."""
    if not isinstance(body, dict):
        return "The request is not a JSON object."
    if body.get("action") not in ("accept", "repoint"):
        return "action must be accept or repoint."
    if body["action"] == "repoint":
        release = body.get("release")
        return None if isinstance(release, str) and release.strip() else "A repoint needs a release."
    if not isinstance(body.get("release_id"), str) or not body["release_id"]:
        return "An accept needs a release_id."
    if body.get("game") is not None and body["game"] not in GAMES:
        return f"game must be one of {', '.join(GAMES)}, or null."
    edits = body.get("edits", {})
    if not isinstance(edits, dict):
        return "edits must be an object of positions."
    for position, fields in edits.items():
        if position not in entry.get("fields", {}):
            return f"edits names position {position!r}, which the preview does not have."
        if not isinstance(fields, dict) or not all(
                values is None or isinstance(values, list) and all(isinstance(v, str) for v in values)
                for values in fields.values()):
            return f"edits at {position!r} must map each tag to a list of strings, or null."
    if body.get("strays") is not None:
        if offences := strays.answer_offences(entry, body["strays"]):
            return "; ".join(offences)
    cover = body.get("cover")
    if cover is not None and not (isinstance(cover, str) and OWNER_COVER.fullmatch(cover)
                                  and (job / cover).is_file()):
        return "cover must name an image uploaded to owner/, as owner/<file>."
    return None


def _ready(request: Handler, config: Config, drop: str, n: str) -> dict[str, Any]:
    """The album's plan entry where a decision or a cover may be taken now; otherwise a `Refusal`."""
    found = state.known_album(config, drop, n, request.server.queue)
    if found["busy"]:
        raise Refusal(409, BUSY)
    entry = state.plan_entry(config, drop, n) if found["state"] == "ready" else None
    if entry is None:
        raise Refusal(409, f"An album that is {found['state']} has no preview to change.")
    return entry


def decide(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    raw = request.read_body()
    entry = _ready(request, config, drop, n)
    try:
        body = json.loads(raw)
    except ValueError:
        request.fail(400, "The request is not JSON.")
        return
    job = config.jobs / f"agitha-{drop}-{n}"
    problem = _invalid(body, entry, job)
    if problem:
        request.fail(400, problem)
        return
    drops.replace_json(job / "decisions.json", {"job": job.name, "albums": {entry["source"]: body}})
    drops.write_album(config.inbox / drop / n, state="queued", stderr="", error=None)
    request.server.queue.enqueue(drop, n, "identify")
    request.send_json(202, {"state": "queued"})


def upload_cover(request: Handler, match: re.Match[str], config: Config) -> None:
    drop, n = match.group(1), match.group(2)
    data = request.read_body()
    _ready(request, config, drop, n)
    content_type = request.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if content_type not in EXTENSIONS:
        request.fail(415, "The cover must be a JPEG, PNG, WebP or GIF image.")
        return
    try:
        width, height, passes, problem = images.cover_check(data)
    except (OSError, ValueError, SyntaxError):
        request.fail(400, "Those bytes are not an image.")
        return
    owner = config.jobs / f"agitha-{drop}-{n}" / "owner"
    owner.mkdir(parents=True, exist_ok=True)
    # A name of its own per image, so a second upload is a new path the draft must send and never a
    # changed file under a path an accepted plan already names.
    name = f"cover-{hashlib.sha256(data).hexdigest()[:8]}.{EXTENSIONS[content_type]}"
    drops.replace_bytes(owner / name, data)
    request.send_json(200, {"width": width, "height": height, "passes": passes, "problem": problem,
                            "path": f"owner/{name}"})
