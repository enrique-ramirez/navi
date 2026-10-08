"""The vitals server: the page, the sampler's JSON and the restart route on one port.

It runs on hyrule-castle as the user `vitals`, started by `host-page.service`.
GET and HEAD serve files from the page folder and the data folder, with no
directory listings and nothing outside either folder. The one thing it
executes is `sudo -n systemctl --no-block restart <unit>`, from
`POST /api/restart/<service>`, for the services the config lists as restartable.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import config

MIME = {
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "ico": "image/x-icon",
    "txt": "text/plain; charset=utf-8",
}
# The sampler's files; every other path is looked up in the page folder.
DATA_PATH = re.compile(r"/host\.json|/history/[^/]+\.json|/log-[^/]+\.json")
RESTART_PATH = re.compile(r"/api/restart/([^/]+)")
# A body larger than this is not read; the connection is closed instead.
MAX_DRAIN = 65536
SYSTEMCTL_TIMEOUT_S = 30


@dataclass
class Settings:
    page: Path
    data: Path
    restartable: dict[str, str]
    sudo: Path = Path("/usr/bin/sudo")
    host: str = "127.0.0.1"
    port: int = 0
    cooldown_s: int = 60


class VitalsServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings: Settings) -> None:
        super().__init__((settings.host, settings.port), Handler)
        self.settings = settings
        self.page_root = settings.page.resolve()
        self.data_root = settings.data.resolve()
        self.restart_lock = threading.Lock()
        self.last_restart: dict[str, float] = {}


def make_server(settings: Settings) -> ThreadingHTTPServer:
    return VitalsServer(settings)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: VitalsServer

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def do_GET(self) -> None:
        self._dispatch()

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

    def _dispatch(self) -> None:
        self._drain_body()
        path = unquote(urlsplit(self.path).path)
        restart = RESTART_PATH.fullmatch(path)
        if restart:
            self._restart(restart.group(1))
        elif self.command not in ("GET", "HEAD"):
            self._refuse(405, "Only GET and HEAD are allowed here.", allow="GET, HEAD")
        else:
            self._serve(path)

    def _drain_body(self) -> None:
        # An unread body would be taken as the start of the next request on a kept-alive connection.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_DRAIN:
            self.close_connection = True
        elif length:
            self.rfile.read(length)

    def _serve(self, path: str) -> None:
        if "\0" in path:
            self._refuse(404, "Not found.")
            return
        is_data = DATA_PATH.fullmatch(path) is not None
        if path == "/":
            root, relative = self.server.page_root, "index.html"
        elif is_data:
            root, relative = self.server.data_root, path.lstrip("/")
        else:
            root, relative = self.server.page_root, path.lstrip("/")
        target = (root / relative).resolve()
        try:
            if not target.is_relative_to(root) or not target.is_file():
                raise FileNotFoundError(path)
            body = target.read_bytes()
        except OSError:
            self._refuse(404, "Not found.")
            return
        content_type = MIME.get(target.suffix.lstrip(".").lower(), "application/octet-stream")
        self._send(200, content_type, body, no_store=is_data)

    def _restart(self, service: str) -> None:
        if self.command != "POST":
            self._refuse(405, "Restart with a POST.", allow="POST")
            return
        host = self.headers.get("Host")
        if host is None or self.headers.get("Origin") != f"http://{host}":
            self._refuse(403, "The request did not come from this page.")
            return
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._refuse(415, "The request must be JSON.")
            return
        unit = self.server.settings.restartable.get(service)
        if unit is None:
            self._refuse(404, f"{service} cannot be restarted from here.")
            return
        cooldown = self.server.settings.cooldown_s
        with self.server.restart_lock:
            last = self.server.last_restart.get(service)
            seconds_since = time.monotonic() - last if last is not None else None
            if seconds_since is not None and seconds_since < cooldown:
                ago = int(seconds_since)
                self._refuse(429, f"{service} was restarted {ago} seconds ago; wait a minute.")
                return
            command = [str(self.server.settings.sudo), "-n", "/usr/bin/systemctl", "--no-block", "restart", unit]
            try:
                done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                      timeout=SYSTEMCTL_TIMEOUT_S)
                ok = done.returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if ok:
                self.server.last_restart[service] = time.monotonic()
        if not ok:
            self._refuse(500, "systemctl failed")
            return
        sys.stderr.write(f"restart {service} from {self.client_address[0]}\n")
        self._send(202, "application/json", json.dumps({"service": service, "unit": unit}).encode())

    def _refuse(self, status: int, reason: str, allow: str | None = None) -> None:
        self._send(status, "application/json", json.dumps({"reason": reason}).encode(), allow=allow)

    def _send(self, status: int, content_type: str, body: bytes, allow: str | None = None,
              no_store: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if allow:
            self.send_header("Allow", allow)
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the vitals page and its restart route.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--defaults", type=Path, default=Path(__file__).resolve().parent / "defaults.conf")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--sudo", type=Path, default=Path("/usr/bin/sudo"))
    args = parser.parse_args()
    try:
        cfg = config.load(args.defaults, args.config)
    except config.ConfigError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    restartable = {name: cfg.service_unit[name] for name in cfg.restartable}
    server = make_server(Settings(page=args.page, data=args.data, restartable=restartable,
                                  sudo=args.sudo, host=args.host, port=args.port))
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    try:
        # The unit stops it with SIGTERM, so shutdown() is never called and the loop can block without polling.
        server.serve_forever(poll_interval=None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
