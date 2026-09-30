"""agitha's HTTP server: the built page, its assets and the JSON API on one port.

Routes are rows in `ROUTES`, `Route(method, pattern, handler)`; a handler is
`handler(request, match, config)` and answers through the request's `send_json`,
`send_file` and `fail`, or raises `Refusal`. HEAD is answered by the GET row, without the body.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Callable, NamedTuple
from urllib.parse import unquote, urlsplit

from . import approve, decisions, drops, queue, ranges, review, state
from .paths import climbs, names_nothing_real
from .refusal import Refusal


def _free_space(path: Path) -> int:
    return shutil.disk_usage(path).free


@dataclass(frozen=True)
class Config:
    inbox: Path
    jobs: Path
    library: Path
    extras: Path
    musiclib: str
    static: Path
    port: int = 8882
    host: str = ""
    free_space: Callable[[Path], int] = field(default=_free_space)
    #: Seconds without a PUT after which an unfinished drop stops reading `uploading`.
    upload_idle: float = 60.0
    now: Callable[[], datetime] = field(default=datetime.now)


CHUNK = 1 << 20
JSON = "application/json; charset=utf-8"
HTML = "text/html; charset=utf-8"


class Route(NamedTuple):
    method: str
    pattern: re.Pattern[str]
    handler: Callable[[Handler, re.Match[str], Config], None]


ROUTES: list[Route] = [
    Route("GET", re.compile(r"/api/drops"), state.listing),
    Route("POST", re.compile(r"/api/drops"), drops.create),
    Route("PUT", re.compile(r"/api/drops/([^/]+)/files/([^/]+)/(.+)"), drops.upload),
    Route("POST", re.compile(r"/api/drops/([^/]+)/done"), queue.done),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)"), review.show),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/cover"), review.cover),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/cover/now"), review.cover_now),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/duplicate/cover"), review.duplicate_cover),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/audio/(.+)"), ranges.audio),
    Route("GET", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/strays/(.+)"), ranges.stray),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/retry"), queue.retry),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/reidentify"), queue.reidentify),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/decision"), decisions.decide),
    Route("PUT", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/cover"), decisions.upload_cover),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/approve"), approve.approve),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/move"), approve.move),
    Route("POST", re.compile(r"/api/drops/([^/]+)/albums/([^/]+)/discard"), approve.discard_album),
    Route("POST", re.compile(r"/api/drops/([^/]+)/discard"), approve.discard_drop),
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: AgithaServer
    # A keep-alive connection reuses this instance, so _dispatch resets both.
    _consumed = False
    body_length = 0

    def do_GET(self) -> None:
        self._dispatch()

    do_HEAD = do_POST = do_PUT = do_GET

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def _dispatch(self) -> None:
        self._consumed = False
        declared = self._declared_length()
        if declared is None:
            self.body_length = 0
            self.close_connection = True
            self.fail(400, "Content-Length is not a number.")
            return
        self.body_length = declared
        path = unquote(urlsplit(self.path).path)
        # A NUL makes `Path.resolve` raise.
        if "\0" in path or climbs(path):
            self.fail(404, "Not found.")
            return
        if names_nothing_real(path):
            self.fail(404, "No such drop or album.")
            return
        method = "GET" if self.command == "HEAD" else self.command
        for route in ROUTES:
            found = route.pattern.fullmatch(path)
            if route.method == method and found:
                try:
                    route.handler(self, found, self.server.config)
                except Refusal as refusal:
                    self.fail(refusal.status, refusal.sentence)
                return
        if path == "/api" or path.startswith("/api/"):
            self.fail(404, "No such API path.")
        elif method == "GET":
            self._static(path)
        else:
            self.fail(404, "Not found.")

    def _static(self, path: str) -> None:
        root = self.server.config.static.resolve()
        target = (root / path.lstrip("/")).resolve()
        if not target.is_relative_to(root):
            self.fail(404, "Not found.")
        elif target.is_file():
            self.send_file(target)
        elif path.startswith("/assets/"):
            # A script that got the page would fail on its MIME type and hide the stale build.
            self.fail(404, "Not found.")
        else:
            index = root / "index.html"
            if index.is_file():
                self.send_bytes(200, HTML, index.read_bytes())
            else:
                self.fail(404, "The page has not been built.")

    def send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if self._body_unread():
            self.close_connection = True
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        self.send_bytes(200, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.read_bytes())

    def _declared_length(self) -> int | None:
        """The Content-Length header as a count of bytes, 0 where absent, None where it is not a number."""
        header = (self.headers.get("Content-Length") or "0").strip()
        return int(header) if header.isascii() and header.isdigit() else None

    def _body_unread(self) -> bool:
        return self.command in ("POST", "PUT") and not self._consumed and self.body_length > 0

    def send_json(self, status: int, body: Any) -> None:
        self.send_bytes(status, JSON, json.dumps(body).encode("utf-8"))

    def fail(self, status: int, sentence: str) -> None:
        self.send_json(status, {"error": sentence})

    def send_empty(self, status: int) -> None:
        self.send_bytes(status, "application/octet-stream", b"")

    def read_body(self) -> bytes:
        self._consumed = True
        return self.rfile.read(self.body_length)

    def copy_body(self, out: BinaryIO, on_chunk: Callable[[], None] | None = None) -> bool:
        """Streams the body into `out`, calling `on_chunk` after each piece; False, with the connection closed, where it ended short."""
        self._consumed = True
        left = self.body_length
        while left:
            # `read1` returns what has arrived, so a slow sender is seen piece by piece.
            chunk = self.rfile.read1(min(CHUNK, left))
            if not chunk:
                self.close_connection = True
                return False
            out.write(chunk)
            left -= len(chunk)
            if on_chunk:
                on_chunk()
        return True


class AgithaServer(ThreadingHTTPServer):
    daemon_threads = True
    config: Config
    queue: queue.Queue
    #: Ids of the drops this process has created and not yet finished; a restart forgets them.
    uploading: set[str]
    #: Ids of the drops this process is extracting and staging; a finished drop with `raw/` left and not here stopped.
    extracting: set[str]
    #: When each drop in `uploading` last received a byte or was created, by `Config.now`.
    touched: dict[str, datetime]
    #: Held while a `done` call checks a drop and marks it finished, so two calls cannot both win.
    finishing: threading.Lock

    def touch(self, drop: str) -> None:
        self.uploading.add(drop)
        self.touched[drop] = self.config.now()

    def uploading_now(self) -> set[str]:
        """The drops of `uploading` that have heard from the page within `upload_idle` seconds."""
        now = self.config.now()
        return {d for d in self.uploading
                if (now - self.touched[d]).total_seconds() <= self.config.upload_idle}


def make_server(config: Config) -> AgithaServer:
    server = AgithaServer((config.host, config.port), Handler)
    server.config = config
    server.queue = queue.Queue(config)
    server.uploading = set()
    server.extracting = set()
    server.touched = {}
    server.finishing = threading.Lock()
    return server
