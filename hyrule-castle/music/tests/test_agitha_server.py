"""agitha's server: the built page, its assets and the API on one port.

The server answers the page and its API on the port it is given. An album's
address opens the page, so a reload or a second tab lands on the same album,
which means any path outside `/api` and `/assets` that is not a file under
`static` answers `static/index.html`.

The server runs on a thread over temporary folders and is spoken to over
HTTP, as the browser would. `python -m agitha` prints
`listening on http://<host>:<port>` as its first line of stdout, flushed, so
a caller that asked for port 0 can find the one it got.
"""

from __future__ import annotations

import http.client
import json
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from agitha.server import Config, make_server

MUSIC = Path(__file__).resolve().parent.parent
STUB = Path(__file__).resolve().parent / "agitha_stub.py"

INDEX = b"<!doctype html><html><head><title>agitha</title></head><body><div id=root></div></body></html>\n"
APP_JS = b"console.log('agitha');\n"
FAVICON = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>\n'
# Sits beside `static`, never in it. No answer may carry these bytes.
SECRET = b"not for the browser\n"


def make_folders(root: Path) -> dict[str, Path]:
    folders = {name: root / name for name in ("inbox", "jobs", "library", "extras", "static")}
    for folder in folders.values():
        folder.mkdir()
    (folders["static"] / "assets").mkdir()
    (folders["static"] / "index.html").write_bytes(INDEX)
    (folders["static"] / "assets" / "app.js").write_bytes(APP_JS)
    (folders["static"] / "favicon.svg").write_bytes(FAVICON)
    (root / "secret.txt").write_bytes(SECRET)
    return folders


class Answer:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        cls.folders = make_folders(cls.root)
        config = Config(
            inbox=cls.folders["inbox"], jobs=cls.folders["jobs"], library=cls.folders["library"],
            extras=cls.folders["extras"], musiclib=str(STUB), static=cls.folders["static"],
            port=0, host="127.0.0.1",
        )
        cls.server = make_server(config)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)
        shutil.rmtree(cls.root)

    def fetch(self, path: str, method: str = "GET") -> Answer:
        # http.client sends the path as written; urllib would do the same
        # today, but this leaves no doubt that `..` reaches the server.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return Answer(response.status, response.headers, response.read())
        finally:
            connection.close()


class ServesThePage(ServerCase):
    def test_the_root_answers_index_html(self) -> None:
        answer = self.fetch("/")
        self.assertEqual(answer.status, 200)
        self.assertTrue(answer.headers["Content-Type"].startswith("text/html"), answer.headers["Content-Type"])
        self.assertEqual(answer.body, INDEX)

    def test_an_albums_address_answers_index_html_so_a_reload_lands_on_it(self) -> None:
        # The page's router reads the address, the server only
        # has to hand it the page.
        for path in ("/drops/x/albums/01", "/drops/20260929-101500-2/albums/12", "/drops/x/"):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 200)
                self.assertTrue(answer.headers["Content-Type"].startswith("text/html"), answer.headers["Content-Type"])
                self.assertEqual(answer.body, INDEX)

    def test_an_asset_answers_its_own_bytes_as_javascript(self) -> None:
        answer = self.fetch("/assets/app.js")
        self.assertEqual(answer.status, 200)
        self.assertIn("javascript", answer.headers["Content-Type"])
        self.assertEqual(answer.body, APP_JS)

    def test_a_file_at_the_top_of_static_answers_its_own_bytes(self) -> None:
        # Vite copies `public/` to the top of the build: the favicon and the
        # logo live there, beside index.html.
        answer = self.fetch("/favicon.svg")
        self.assertEqual(answer.status, 200)
        self.assertTrue(answer.headers["Content-Type"].startswith("image/svg+xml"), answer.headers["Content-Type"])
        self.assertEqual(answer.body, FAVICON)

    def test_a_missing_asset_is_404_rather_than_the_page(self) -> None:
        # A browser that asked for a script and got HTML reports a MIME
        # error and a blank page, which hides the stale build behind it.
        answer = self.fetch("/assets/gone.js")
        self.assertEqual(answer.status, 404)
        self.assertNotEqual(answer.body, INDEX)

    def test_a_path_climbing_out_of_static_reads_nothing_outside_it(self) -> None:
        for path in (
            "/assets/../../secret.txt",
            "/assets/%2e%2e/%2e%2e/secret.txt",
            "/assets/..%2f..%2fsecret.txt",
        ):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 404)
                self.assertNotIn(SECRET.strip(), answer.body)

    def test_a_climb_outside_assets_never_reads_the_file_either(self) -> None:
        # It may be 404 or the page. Either is safe; the file's bytes are not.
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/drops/../../secret.txt"):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertNotIn(SECRET.strip(), answer.body)

    def test_head_on_the_root_answers_the_headers_and_no_body(self) -> None:
        answer = self.fetch("/", method="HEAD")
        self.assertEqual(answer.status, 200)
        self.assertTrue(answer.headers["Content-Type"].startswith("text/html"), answer.headers["Content-Type"])
        self.assertEqual(int(answer.headers["Content-Length"]), len(INDEX))

        # http.client never reads a body after HEAD, so a server that sends
        # one anyway would pass above. Read the raw socket to its end.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            raw.sendall(b"HEAD / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            received = b""
            while chunk := raw.recv(65536):
                received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        self.assertIn(b" 200 ", head.split(b"\r\n")[0])
        self.assertEqual(body, b"")


class AnswersTheApi(ServerCase):
    def test_drops_over_an_empty_inbox_is_an_empty_json_list(self) -> None:
        answer = self.fetch("/api/drops")
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(answer.body), [])

    def test_an_unknown_api_path_is_404_json_with_an_error(self) -> None:
        # Never the page: the page's fetch would parse HTML as JSON.
        for path in ("/api/nothing", "/api/", "/api/drops/x/nothing/here"):
            with self.subTest(path=path):
                answer = self.fetch(path)
                self.assertEqual(answer.status, 404)
                self.assertEqual(answer.headers["Content-Type"], "application/json; charset=utf-8")
                body = json.loads(answer.body)
                self.assertIsInstance(body, dict)
                self.assertIsInstance(body.get("error"), str)
                self.assertNotEqual(body["error"].strip(), "")


class RunsFromTheCommandLine(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.folders = make_folders(self.root)

    def test_python_m_agitha_prints_where_it_listens_and_serves_there(self) -> None:
        f = self.folders
        process = subprocess.Popen(
            [
                sys.executable, "-m", "agitha", "--port", "0", "--host", "127.0.0.1",
                "--inbox", str(f["inbox"]), "--jobs", str(f["jobs"]), "--library", str(f["library"]),
                "--extras", str(f["extras"]), "--musiclib", str(STUB), "--static", str(f["static"]),
            ],
            cwd=MUSIC, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        def stop() -> None:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

        self.addCleanup(stop)

        # A reader thread, so a server that never prints, or prints into a
        # buffer it never flushes, fails here instead of hanging the suite.
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            first = lines.get(timeout=15)
        except queue.Empty:
            self.fail("nothing on stdout within 15 s; is the line flushed?")
        if not first:
            process.wait(10)
            self.fail(f"exited {process.returncode} before printing:\n{process.stderr.read()}")

        found = re.fullmatch(r"listening on http://127\.0\.0\.1:(\d+)\n", first)
        self.assertIsNotNone(found, repr(first))
        port = int(found.group(1))
        self.assertNotEqual(port, 0)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/drops", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), [])
        # `--static` reaches the server: the page is the one in that folder.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/drops/x/albums/01", timeout=10) as response:
            self.assertEqual(response.read(), INDEX)


if __name__ == "__main__":
    unittest.main()
