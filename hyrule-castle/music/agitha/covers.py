"""A cover for a library album: `PUT /api/library/covers` keeps an upload, and a draft names it by its token.

An upload is judged here for the review's cover upload too (`decisions`), so
both refuse the same bytes in the same words. Uploads sit under
`config.jobs / "library-covers"`, one file per token, and are cleared when
agitha starts.
"""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musiclib import images

from . import drops
from .refusal import Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
NO_SUCH = "No such cover upload."
#: What `secrets.token_hex(16)` makes. A token is matched to this before it is joined to a path.
_TOKEN = re.compile(r"[0-9a-f]{32}")


def judge(data: bytes, content_type: str) -> tuple[str, dict[str, Any]]:
    """`(the extension for the type, {width, height, passes, problem})` of an upload, or a `Refusal`."""
    kind = content_type.split(";")[0].strip().lower()
    if kind not in EXTENSIONS:
        raise Refusal(415, "The cover must be a JPEG, PNG, WebP or GIF image.")
    return EXTENSIONS[kind], describe(data)


def describe(data: bytes) -> dict[str, Any]:
    try:
        width, height, passes, problem = images.cover_check(data)
    except images.NOT_AN_IMAGE:
        raise Refusal(400, "Those bytes are not an image.") from None
    return {"width": width, "height": height, "passes": passes, "problem": problem}


def _folder(config: Config) -> Path:
    return config.jobs / "library-covers"


def upload(request: Handler, match: re.Match[str], config: Config) -> None:
    # The body is read before any refusal, so a large upload is not cut off mid-send.
    data = request.read_body()
    _extension, answer = judge(data, request.headers.get("Content-Type", ""))
    token = secrets.token_hex(16)
    _folder(config).mkdir(parents=True, exist_ok=True)
    drops.replace_bytes(_folder(config) / token, data)
    request.send_json(200, {"cover": token, **answer})


def read(config: Config, token: Any) -> bytes:
    """The bytes uploaded as `token`; a `Refusal` for anything that is not a token this process handed out."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise Refusal(400, NO_SUCH)
    try:
        return (_folder(config) / token).read_bytes()
    except OSError:
        raise Refusal(400, NO_SUCH) from None


def discard(config: Config, token: str) -> None:
    (_folder(config) / token).unlink(missing_ok=True)


def clear(config: Config) -> None:
    shutil.rmtree(_folder(config), ignore_errors=True)
