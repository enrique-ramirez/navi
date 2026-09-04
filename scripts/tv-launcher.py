#!/usr/bin/env python3
"""Opens Jean on the living room TV, triggered from the landing page.

Samsung's remote-control API is a WebSocket, not REST. Both of the simpler
routes were tested against this set (QN65QN700CFXZX, 2023) and both are gone:

    GET  /api/v2/applications/org.tizen.browser   -> 404
    POST :8080/ws/apps/Browser  (DIAL)            -> 404

So the only way in is wss://TV:8002/api/v2/channels/samsung.remote.control,
which needs a real WebSocket client. That's python3-websocket from apt; deploy.sh
checks for it and refuses to install this service without it.

WHY THIS IS AN HTTP SERVICE AND NOT A TIMER

host-status.sh states the rule this breaks: "There is no endpoint, so there is no
code path anything on the LAN can make this box execute." That was true until
this file, and it was worth having, so the exception is drawn as narrowly as it
can be:

  - The endpoint takes NO parameters. Not the URL, not the TV's address, not the
    app id. Every one of those is read from .env at startup. The request body is
    read and discarded. There is nothing on the wire to inject into, so the whole
    class of "make navi fetch/execute X" bugs cannot exist here regardless of how
    sloppy the caller is.
  - It runs as navi-tv, a system user with no shell and no home, not as root.
    tv-launcher.service adds the sandboxing on top.
  - It binds 127.0.0.1. Caddy is the only thing that can reach it.

What's left is an unauthenticated LAN trigger that opens a browser on a TV. That
is a real thing anyone on the network can do to you, and it is also completely
uninteresting: the worst outcome is the TV changes what it's showing. Weigh that
against putting a password on the one control you want to press without thinking.

THE PAIRING PROMPT

TokenAuthSupport is true on this set. The first connection from a given client
name puts an "Allow navi to connect?" dialog on the TV and waits. Accept it and
the TV hands back a token in the ms.channel.connect frame; store that and every
later connection is silent. Ignore it and the TV sends ms.channel.timeOut and
hangs up, which is exactly what the first attempt from a laptop did.

If pairing was ever *denied*, the TV remembers that too, and every attempt fails
instantly with no prompt. Clear it on the TV at
Settings > General > External Device Manager > Device Connection Manager >
Device List, remove navi, and press the button again.
"""

import base64
import http.server
import json
import os
import ssl
import sys
import threading

import websocket  # python3-websocket

TV_HOST = os.environ.get("TV_HOST", "")
TV_URL = os.environ.get("TV_URL", "https://ocarina.lan")
CLIENT_NAME = os.environ.get("TV_CLIENT_NAME", "navi")
TOKEN_FILE = os.environ.get("TV_TOKEN_FILE", "/srv/data/tv/token")
LISTEN_PORT = int(os.environ.get("TV_LISTEN_PORT", "8090"))

# Generous, because the first call blocks on a human finding the remote. Later
# calls with a stored token return in well under a second.
PAIR_TIMEOUT = 45

# One TV, one WebSocket, one press at a time. Double-clicking the button should
# not open two connections and race for the token file.
_lock = threading.Lock()


def _read_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _write_token(token):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    tmp = TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(token))
    os.replace(tmp, TOKEN_FILE)  # atomic, so a crash mid-write can't leave a
                                 # truncated token that fails silently forever


def launch():
    """Connect, wait for the channel to come up, tell it to open the browser.

    Returns (ok, message). Never raises; the caller turns this straight into
    JSON for the page.
    """
    token = _read_token()
    url = "wss://%s:8002/api/v2/channels/samsung.remote.control?name=%s" % (
        TV_HOST, base64.b64encode(CLIENT_NAME.encode()).decode())
    if token:
        url += "&token=" + token

    # The TV presents a self-signed certificate for its own IP. There is no CA
    # to check it against and no way to install one, so verification is off.
    # This is a LAN control channel to a device we located by fixed IP; the
    # alternative isn't a verified connection, it's no connection.
    try:
        ws = websocket.create_connection(
            url, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=PAIR_TIMEOUT)
    except Exception as e:
        return False, "cannot reach the TV (%s). Is it on?" % type(e).__name__

    try:
        # Do NOT assume the first frame is the one you want. This set sends
        # ms.remote.touchDisable first, which is what makes the samsungtvws
        # library throw ConnectionFailure before it ever gets to the useful
        # frame. Read until something meaningful arrives.
        for _ in range(12):
            frame = json.loads(ws.recv())
            event = frame.get("event")

            if event == "ms.channel.connect":
                new_token = (frame.get("data") or {}).get("token")
                if new_token and str(new_token) != token:
                    _write_token(new_token)
                break

            if event == "ms.channel.timeOut":
                return False, ("the TV asked for permission and nobody "
                               "accepted it. Press the button again and "
                               "approve 'navi' on screen.")

            if event == "ms.channel.unauthorized":
                return False, ("the TV refused this box. Remove 'navi' under "
                               "Device Connection Manager on the TV and retry.")
        else:
            return False, "the TV never finished opening the channel"

        ws.send(json.dumps({
            "method": "ms.channel.emit",
            "params": {
                "event": "ed.apps.launch",
                "to": "host",
                "data": {
                    # NATIVE_LAUNCH is what carries metaTag through as the URL.
                    # DEEP_LINK is the library default and does not.
                    "action_type": "NATIVE_LAUNCH",
                    "appId": "org.tizen.browser",
                    "metaTag": TV_URL,
                },
            },
        }))
        # The TV acknowledges nothing useful here, so there is no success frame
        # to wait for. Sent is as much confirmation as the protocol offers, and
        # the real confirmation is that the TV is now showing Jean.
        return True, "sent"
    except Exception as e:
        return False, "the TV closed the connection (%s)" % type(e).__name__
    finally:
        try:
            ws.close()
        except Exception:
            pass


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") != "/api/tv/ocarina":
            return self._json(404, {"ok": False, "detail": "no such trigger"})

        # Drain and discard. Nothing in the request influences what happens
        # next, and that is the entire security design of this service.
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(min(length, 4096))

        if not _lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "detail": "already working on it"})
        try:
            ok, detail = launch()
        finally:
            _lock.release()
        return self._json(200 if ok else 502, {"ok": ok, "detail": detail})

    def do_GET(self):
        if self.path.rstrip("/") == "/api/tv/health":
            return self._json(200, {
                "ok": True, "tv": TV_HOST, "url": TV_URL,
                "paired": _read_token() is not None,
            })
        return self._json(404, {"ok": False, "detail": "no such trigger"})

    def log_message(self, fmt, *args):
        sys.stderr.write("tv-launcher: " + fmt % args + "\n")


if __name__ == "__main__":
    if not TV_HOST:
        sys.exit("TV_HOST is unset. Add it to /srv/navi/.env")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    sys.stderr.write("tv-launcher: 127.0.0.1:%d -> %s opens %s (paired: %s)\n"
                     % (LISTEN_PORT, TV_HOST, TV_URL, _read_token() is not None))
    server.serve_forever()
