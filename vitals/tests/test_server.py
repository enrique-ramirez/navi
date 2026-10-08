"""The vitals server: the page, the sampler's JSON and the restart route on one port.

Each test starts its own server on a thread over temporary folders and speaks
to it with `http.client`, as the browser would. sudo is replaced by
`sudo_stub.py`, which records the command it was given in the file named by
`VITALS_STUB_LOG`, so a test can see what would have run as root.

Run from `vitals/`:
`../_tmp/venv/bin/python -m unittest tests.test_server`
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from server import Settings, make_server

STUB = Path(__file__).resolve().parent / "sudo_stub.py"
RESTARTABLE = {"foobar2000": "foobar2000.service", "agitha": "agitha.service"}

INDEX = b"<!doctype html><html><head><title>vitals</title></head><body></body></html>\n"
STYLE = b"body { color: black; }\n"
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>\n'
HOST = b'{"host": "hyrule-castle", "cpu_pct": 12.3}\n'
DAY = b'{"t": [1, 2], "cpu": [3, 4]}\n'
LOG_AGITHA = b'{"source": "journal", "lines": [], "writes": []}\n'
# Sits beside the page and data folders, never in them. No answer may carry these bytes.
SECRET = b"not for the browser\n"


def make_folders(root: Path) -> tuple[Path, Path]:
    page = root / "page"
    data = root / "data"
    (page / "img").mkdir(parents=True)
    (data / "history").mkdir(parents=True)
    (page / "index.html").write_bytes(INDEX)
    (page / "style.css").write_bytes(STYLE)
    (page / "img" / "logo.svg").write_bytes(LOGO)
    (data / "host.json").write_bytes(HOST)
    (data / "history" / "day.json").write_bytes(DAY)
    (data / "log-agitha.json").write_bytes(LOG_AGITHA)
    (root / "secret.txt").write_bytes(SECRET)
    return page, data


class Answer:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body)


class ServerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.page, self.data = make_folders(self.root)
        self.stub_log = self.root / "stub.log"
        self.saved_env = {name: os.environ.get(name) for name in ("VITALS_STUB_LOG", "VITALS_STUB_FAIL")}
        os.environ["VITALS_STUB_LOG"] = str(self.stub_log)
        os.environ.pop("VITALS_STUB_FAIL", None)
        self.server = None
        self.start()

    def tearDown(self) -> None:
        self.stop()
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.root)

    def start(self, cooldown_s: int = 60) -> None:
        self.stop()
        self.server = make_server(Settings(
            page=self.page, data=self.data, restartable=dict(RESTARTABLE), sudo=STUB,
            host="127.0.0.1", port=0, cooldown_s=cooldown_s,
        ))
        self.port = self.server.server_address[1]
        # A short poll lets shutdown() return quickly; each test starts its own server.
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(10)
            self.server = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def fetch(self, path: str, method: str = "GET", headers: dict[str, str] | None = None,
              body: bytes | None = None) -> Answer:
        # http.client sends the path as written, so `..` reaches the server unnormalised.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return Answer(response.status, response.headers, response.read())
        finally:
            connection.close()

    def restart(self, service: str, method: str = "POST", origin: str | None = "",
                content_type: str | None = "application/json") -> Answer:
        """Send the page's restart request, with any one part of it changed.

        `origin=""` means the page's own origin; `None` leaves the header out.
        """
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if origin is not None:
            headers["Origin"] = origin or self.origin
        if content_type is not None:
            headers["Content-Type"] = content_type
        return self.fetch(f"/api/restart/{service}", method, headers, b"{}")

    def stub_lines(self) -> list[str]:
        if not self.stub_log.exists():
            return []
        return self.stub_log.read_text(encoding="utf-8").splitlines()

    def assertRefused(self, answer: Answer, status: int) -> None:
        self.assertEqual(answer.status, status, answer.body)
        self.assertIn("application/json", answer.headers.get("Content-Type", ""))
        reason = answer.json().get("reason")
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip())

    def assertNoSecret(self, answer: Answer) -> None:
        self.assertNotIn(SECRET.strip(), answer.body)


class ServesFiles(ServerCase):
    def test_the_root_answers_the_pages_index_html(self) -> None:
        answer = self.fetch("/")
        self.assertEqual(answer.status, 200)
        self.assertTrue(answer.headers["Content-Type"].startswith("text/html"), answer.headers["Content-Type"])
        self.assertEqual(answer.body, INDEX)

    def test_a_file_in_the_page_folder_answers_its_own_bytes(self) -> None:
        for path, expected in (("/style.css", STYLE), ("/img/logo.svg", LOGO)):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 200)
                self.assertEqual(answer.body, expected)

    def test_the_samplers_json_comes_from_the_data_folder_and_is_never_cached(self) -> None:
        # A cached host.json would show a stale sample as fresh.
        for path, expected in (("/host.json", HOST), ("/history/day.json", DAY), ("/log-agitha.json", LOG_AGITHA)):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 200)
                self.assertEqual(answer.body, expected)
                self.assertIn("application/json", answer.headers["Content-Type"])
                self.assertEqual(answer.headers["Cache-Control"], "no-store")

    def test_head_answers_the_length_of_the_file_and_no_body(self) -> None:
        # Read off the socket: http.client drops a HEAD body unread, and a body
        # sent anyway would be taken as the start of the next answer on that connection.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as connection:
            connection.sendall(f"HEAD /host.json HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                               "Connection: close\r\n\r\n".encode())
            raw = b""
            while chunk := connection.recv(65536):
                raw += chunk
        head, _, rest = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(":") for line in lines[1:])}
        self.assertRegex(lines[0], r"^HTTP/1\.[01] 200 ")
        self.assertEqual(headers.get("content-length"), str(len(HOST)))
        self.assertEqual(rest, b"")


class RefusesWhatIsNotAFile(ServerCase):
    def test_a_missing_file_is_404(self) -> None:
        for path in ("/gone.css", "/history/year.json", "/log-nobody.json"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path).status, 404)

    def test_a_directory_is_404_and_never_a_listing(self) -> None:
        for path in ("/history/", "/history", "/img/", "/img"):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 404)
                self.assertNotIn(b"day.json", answer.body)
                self.assertNotIn(b"logo.svg", answer.body)

    def test_a_path_that_climbs_out_of_either_folder_is_404(self) -> None:
        for path in ("/../secret.txt", "/history/../../secret.txt", "/img/../../secret.txt", "/%2e%2e/secret.txt"):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 404)
                self.assertNoSecret(answer)


class RefusesOtherMethods(ServerCase):
    def test_a_method_other_than_get_or_head_is_405_with_allow(self) -> None:
        for method, path in (("PUT", "/host.json"), ("DELETE", "/"), ("POST", "/host.json"), ("POST", "/")):
            with self.subTest(method=method, path=path):
                answer = self.fetch(path, method, body=b"{}")
                self.assertEqual(answer.status, 405)
                self.assertIn("GET", answer.headers.get("Allow", ""))
                self.assertEqual(self.data.joinpath("host.json").read_bytes(), HOST)
                self.assertEqual(self.stub_lines(), [])


class RefusesARestart(ServerCase):
    # Each case fails one check and passes every other, so the status names that check,
    # apart from the last, which fails several to show which comes first.

    def test_a_get_on_the_restart_route_is_405_allowing_post(self) -> None:
        answer = self.restart("foobar2000", method="GET")
        self.assertRefused(answer, 405)
        self.assertEqual(answer.headers.get("Allow"), "POST")
        self.assertEqual(self.stub_lines(), [])

    def test_a_post_without_origin_is_403(self) -> None:
        self.assertRefused(self.restart("foobar2000", origin=None), 403)
        self.assertEqual(self.stub_lines(), [])

    def test_a_post_from_another_origin_is_403(self) -> None:
        for origin in ("http://evil.lan", f"http://127.0.0.1:{self.port + 1}"):
            with self.subTest(origin=origin):
                self.assertRefused(self.restart("foobar2000", origin=origin), 403)
        self.assertEqual(self.stub_lines(), [])

    def test_a_post_that_is_not_json_is_415(self) -> None:
        # A form or a plain-text fetch from another page needs no preflight; only JSON does.
        for content_type in ("text/plain", "application/x-www-form-urlencoded", None):
            with self.subTest(content_type=content_type):
                self.assertRefused(self.restart("foobar2000", content_type=content_type), 415)
        self.assertEqual(self.stub_lines(), [])

    def test_a_service_that_is_not_restartable_is_404(self) -> None:
        # xvfb and openbox are in the box's units but never restartable.
        for service in ("xvfb", "openbox", "nobody"):
            with self.subTest(service=service):
                self.assertRefused(self.restart(service), 404)
        self.assertEqual(self.stub_lines(), [])

    def test_the_checks_run_in_order_method_origin_type_service(self) -> None:
        # Several checks fail at once; the first in the contract's order decides.
        self.assertRefused(self.restart("xvfb", method="GET", origin=None, content_type="text/plain"), 405)
        self.assertRefused(self.restart("xvfb", origin="http://evil.lan", content_type="text/plain"), 403)
        self.assertRefused(self.restart("xvfb", content_type="text/plain"), 415)
        self.assertEqual(self.stub_lines(), [])


class Restarts(ServerCase):
    def test_a_restart_answers_202_runs_systemctl_through_sudo_and_logs_who_asked(self) -> None:
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            answer = self.restart("foobar2000")
            # The handler thread may still be writing after the answer arrives.
            deadline = time.monotonic() + 5
            while "restart foobar2000" not in captured.getvalue() and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(answer.status, 202, answer.body)
        self.assertEqual(answer.json(), {"service": "foobar2000", "unit": "foobar2000.service"})
        self.assertEqual(self.stub_lines(), ["-n /usr/bin/systemctl --no-block restart foobar2000.service"])
        # An access log line may sit beside it; the restart line is the one the journal is read for.
        restart_lines = [line for line in captured.getvalue().splitlines() if line.startswith("restart ")]
        self.assertEqual(restart_lines, ["restart foobar2000 from 127.0.0.1"])

    def test_a_json_content_type_with_a_charset_is_accepted(self) -> None:
        answer = self.restart("agitha", content_type="application/json; charset=utf-8")
        self.assertEqual(answer.status, 202, answer.body)
        self.assertEqual(self.stub_lines(), ["-n /usr/bin/systemctl --no-block restart agitha.service"])

    def test_a_failed_systemctl_answers_500_with_a_reason(self) -> None:
        os.environ["VITALS_STUB_FAIL"] = "1"
        self.assertRefused(self.restart("foobar2000"), 500)
        self.assertEqual(self.stub_lines(), ["-n /usr/bin/systemctl --no-block restart foobar2000.service"])


class LimitsRestartsPerService(ServerCase):
    def test_a_second_restart_of_the_same_service_inside_the_cooldown_is_429(self) -> None:
        self.assertEqual(self.restart("foobar2000").status, 202)
        answer = self.restart("foobar2000")
        self.assertRefused(answer, 429)
        self.assertRegex(answer.json()["reason"], r"\d+ seconds")
        self.assertEqual(len(self.stub_lines()), 1)

    def test_the_cooldown_is_per_service(self) -> None:
        self.assertEqual(self.restart("foobar2000").status, 202)
        self.assertEqual(self.restart("agitha").status, 202)
        self.assertEqual(self.stub_lines(), [
            "-n /usr/bin/systemctl --no-block restart foobar2000.service",
            "-n /usr/bin/systemctl --no-block restart agitha.service",
        ])

    def test_a_refused_request_inside_the_cooldown_answers_its_own_refusal(self) -> None:
        # The cooldown is the last check: a foreign page learns nothing about recent restarts.
        self.assertEqual(self.restart("foobar2000").status, 202)
        self.assertRefused(self.restart("foobar2000", origin="http://evil.lan"), 403)
        self.assertRefused(self.restart("foobar2000", content_type="text/plain"), 415)

    def test_the_cooldown_ends_after_cooldown_s(self) -> None:
        # With no cooldown the server's clock has always passed it, so this needs no sleep.
        self.start(cooldown_s=0)
        self.assertEqual(self.restart("foobar2000").status, 202)
        self.assertEqual(self.restart("foobar2000").status, 202)
        self.assertEqual(len(self.stub_lines()), 2)


if __name__ == "__main__":
    unittest.main()
