"""Playing a staged track: the server answers byte ranges of the uploaded file.

A `Range` request gets `206 Partial Content` with the right
`Content-Range`, a request without one gets the whole file, and a range that
starts past the end gets `416`. The browser's audio element seeks with these,
so a wrong byte here is a skip or a track that never starts.

`GET /api/drops/<drop>/albums/<n>/audio/<path>` serves the file at
`inbox/<drop>/<n>/drop/album/<name>/<path>`, with `<path>` percent-decoded
UTF-8 and relative to the album folder. Nothing outside that folder is ever
served, and once the album is in the library the url is 404.

The folders are laid out by hand and the server runs on a thread, spoken to
over HTTP as the browser would. Every body is compared with the fixture's own
bytes.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

from agitha.server import Config, make_server

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUB = Path(__file__).resolve().parent / "agitha_stub.py"

DROP = "20260929-101500"
LANDED = "20260929-093000"
ALBUM = "An Album"

#: Each staged track, relative to the album folder, and the fixture it is a copy of.
TRACKS = {
    "01 one.mp3": "tone.mp3",
    "CD2/02 two.flac": "tone.flac",
    "03 café noir.m4a": "tone.m4a",
    "04 four.ogg": "tone.ogg",
    "05 five.wma": "tone.wma",
}

CONTENT_TYPES = {
    "01 one.mp3": "audio/mpeg",
    "CD2/02 two.flac": "audio/flac",
    "03 café noir.m4a": "audio/mp4",
    "04 four.ogg": "audio/ogg",
    "05 five.wma": "audio/x-ms-wma",
}

#: Sits outside every album folder. No answer may carry these bytes.
SECRET = b"agitha must never serve this\n" * 8


def audio_url(drop: str, n: str, rel: str) -> str:
    return f"/api/drops/{drop}/albums/{n}/audio/{urllib.parse.quote(rel)}"


def lay_out(root: Path) -> dict[str, Path]:
    folders = {name: root / name for name in ("inbox", "jobs", "library", "extras", "static")}
    for folder in folders.values():
        folder.mkdir()
    (folders["static"] / "index.html").write_bytes(b"<!doctype html><title>agitha</title>\n")

    drop = folders["inbox"] / DROP
    album = drop / "01" / "drop" / "album" / ALBUM
    album.mkdir(parents=True)
    (drop / "drop.json").write_text(json.dumps({
        "started": "2026-09-29T10:15:00",
        "items": [{"name": ALBUM, "kind": "folder",
                   "files": [{"path": rel, "size": (FIXTURES / src).stat().st_size} for rel, src in TRACKS.items()]}],
        "done": True,
    }), encoding="utf-8")
    (drop / "01" / "album.json").write_text(json.dumps({
        "n": "01", "name": ALBUM, "item": ALBUM, "state": "ready", "stderr": "", "error": None,
    }), encoding="utf-8")
    for rel, src in TRACKS.items():
        (album / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / src, album / rel)

    # Secrets one step out of the album folder and all the way out of the inbox.
    (drop / "01" / "drop" / "secret.mp3").write_bytes(SECRET)
    (root / "outside.mp3").write_bytes(SECRET)
    os.symlink(root / "outside.mp3", album / "link out.mp3")
    os.symlink(drop / "01" / "drop", album / "Up")

    # An album that has landed: the rename took `drop/` with it, and the
    # library holds the track under the same name the page last asked for.
    landed = folders["inbox"] / LANDED
    (landed / "01").mkdir(parents=True)
    (landed / "drop.json").write_text(json.dumps({
        "started": "2026-09-29T09:30:00",
        "items": [{"name": ALBUM, "kind": "folder", "files": [{"path": "01 one.mp3", "size": 1}]}],
        "done": True,
    }), encoding="utf-8")
    (landed / "01" / "album.json").write_text(json.dumps({
        "n": "01", "name": ALBUM, "item": ALBUM, "state": "in the library", "stderr": "", "error": None,
    }), encoding="utf-8")
    in_library = folders["library"] / "A" / "An Artist" / ALBUM
    in_library.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "tone.mp3", in_library / "01 one.mp3")
    return folders


class Answer:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body


class RangesCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        cls.folders = lay_out(cls.root)
        config = Config(
            inbox=cls.folders["inbox"], jobs=cls.folders["jobs"], library=cls.folders["library"],
            extras=cls.folders["extras"], musiclib=str(STUB), static=cls.folders["static"],
            port=0, host="127.0.0.1",
        )
        cls.server = make_server(config)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.mp3 = (FIXTURES / "tone.mp3").read_bytes()
        cls.size = len(cls.mp3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)
        shutil.rmtree(cls.root)

    def fetch(self, path: str, range_: str | None = None, method: str = "GET") -> Answer:
        # http.client sends the path as written, so `..` and `%2e` reach the
        # server untouched, and a 416 comes back as an answer, not a raise.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, headers={"Range": range_} if range_ else {})
            response = connection.getresponse()
            return Answer(response.status, response.headers, response.read())
        finally:
            connection.close()

    def assertPartial(self, answer: Answer, first: int, last: int, whole: bytes) -> None:
        self.assertEqual(answer.status, 206)
        self.assertEqual(answer.headers["Content-Range"], f"bytes {first}-{last}/{len(whole)}")
        self.assertEqual(answer.body, whole[first:last + 1])
        self.assertEqual(int(answer.headers["Content-Length"]), last + 1 - first)
        self.assertEqual(answer.headers["Accept-Ranges"], "bytes")


class AnswersARange(RangesCase):
    def test_bytes_0_1_is_206_with_the_first_two_bytes(self) -> None:
        # Safari asks for exactly this before it will play anything.
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=0-1")
        self.assertPartial(answer, 0, 1, self.mp3)
        self.assertEqual(answer.headers["Content-Type"].split(";")[0].strip(), "audio/mpeg")

    def test_a_closed_range_in_the_middle_is_exactly_those_bytes(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=200-299")
        self.assertPartial(answer, 200, 299, self.mp3)

    def test_an_open_range_is_the_rest_of_the_file(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=100-")
        self.assertPartial(answer, 100, self.size - 1, self.mp3)

    def test_bytes_0_open_is_206_with_the_whole_file(self) -> None:
        # Chrome and Firefox open a track with this.
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=0-")
        self.assertPartial(answer, 0, self.size - 1, self.mp3)

    def test_a_suffix_range_is_the_last_n_bytes(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=-10")
        self.assertPartial(answer, self.size - 10, self.size - 1, self.mp3)

    def test_the_last_byte_alone_is_satisfiable(self) -> None:
        # The boundary on the 416 side: a start one short of the size is a range.
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), f"bytes={self.size - 1}-")
        self.assertPartial(answer, self.size - 1, self.size - 1, self.mp3)

    def test_a_track_in_a_disc_folder_answers_its_own_bytes(self) -> None:
        flac = (FIXTURES / "tone.flac").read_bytes()
        answer = self.fetch(audio_url(DROP, "01", "CD2/02 two.flac"), "bytes=4-")
        self.assertPartial(answer, 4, len(flac) - 1, flac)
        self.assertEqual(answer.headers["Content-Type"].split(";")[0].strip(), "audio/flac")

    def test_a_name_with_a_space_and_an_accent_is_read_percent_decoded_as_utf8(self) -> None:
        m4a = (FIXTURES / "tone.m4a").read_bytes()
        path = f"/api/drops/{DROP}/albums/01/audio/03%20caf%C3%A9%20noir.m4a"
        answer = self.fetch(path, "bytes=0-1")
        self.assertPartial(answer, 0, 1, m4a)
        self.assertEqual(self.fetch(path).body, m4a)


class AnswersTheWholeFile(RangesCase):
    def test_no_range_is_200_with_the_whole_file_and_says_it_takes_ranges(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"))
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.body, self.mp3)
        self.assertEqual(int(answer.headers["Content-Length"]), self.size)
        self.assertEqual(answer.headers["Accept-Ranges"], "bytes")
        self.assertIsNone(answer.headers["Content-Range"])

    def test_each_format_answers_its_bytes_with_the_type_its_extension_names(self) -> None:
        for rel, content_type in CONTENT_TYPES.items():
            with self.subTest(rel=rel):
                answer = self.fetch(audio_url(DROP, "01", rel))
                self.assertEqual(answer.status, 200)
                self.assertEqual(answer.body, (FIXTURES / TRACKS[rel]).read_bytes())
                self.assertEqual(answer.headers["Content-Type"].split(";")[0].strip(), content_type)

    def test_head_answers_the_headers_and_no_body(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), method="HEAD")
        self.assertEqual(answer.status, 200)
        self.assertEqual(int(answer.headers["Content-Length"]), self.size)
        self.assertEqual(answer.headers["Accept-Ranges"], "bytes")
        self.assertEqual(answer.headers["Content-Type"].split(";")[0].strip(), "audio/mpeg")

        # http.client never reads a body after HEAD, so a server that sent one
        # would pass above. Read the raw socket to its end.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            target = audio_url(DROP, "01", "01 one.mp3").encode("ascii")
            raw.sendall(b"HEAD " + target + b" HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            received = b""
            while chunk := raw.recv(65536):
                received += chunk
        head, _, body = received.partition(b"\r\n\r\n")
        self.assertIn(b" 200 ", head.split(b"\r\n")[0])
        self.assertEqual(body, b"")

    def test_several_ranges_at_once_are_never_a_server_error(self) -> None:
        # A server may answer a multi-range request whole with 200; nothing
        # says more, so only a crash is wrong here.
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), "bytes=0-1,4-5")
        self.assertLess(answer.status, 500)


class RefusesARangePastTheEnd(RangesCase):
    def test_a_range_starting_at_the_size_is_416_naming_the_size(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), f"bytes={self.size}-")
        self.assertEqual(answer.status, 416)
        self.assertEqual(answer.headers["Content-Range"], f"bytes */{self.size}")
        self.assertNotIn(self.mp3[:64], answer.body)

    def test_a_range_wholly_past_the_end_is_416_naming_the_size(self) -> None:
        answer = self.fetch(audio_url(DROP, "01", "01 one.mp3"), f"bytes={self.size + 5}-{self.size + 9}")
        self.assertEqual(answer.status, 416)
        self.assertEqual(answer.headers["Content-Range"], f"bytes */{self.size}")
        self.assertNotIn(self.mp3[:64], answer.body)


class ServesNothingOutsideTheAlbum(RangesCase):
    def assertNotFound(self, path: str) -> None:
        answer = self.fetch(path)
        self.assertEqual(answer.status, 404, path)
        self.assertNotIn(SECRET[:40], answer.body)
        self.assertNotIn(self.mp3[:64], answer.body)

    def test_a_path_with_dot_dot_is_404(self) -> None:
        base = f"/api/drops/{DROP}/albums/01/audio"
        for path in (
            f"{base}/../../secret.mp3",
            f"{base}/%2e%2e/%2e%2e/secret.mp3",
            f"{base}/..%2f..%2fsecret.mp3",
            f"{base}/{'%2E%2E%2F' * 6}outside.mp3",
            # Resolves back inside the album, and is still refused: the
            # contract turns away any `..`, not only one that escapes.
            f"{base}/CD2/%2e%2e/01%20one.mp3",
        ):
            with self.subTest(path=path):
                self.assertNotFound(path)

    def test_an_absolute_path_is_404(self) -> None:
        outside = urllib.parse.quote(str(self.root / "outside.mp3"), safe="")
        base = f"/api/drops/{DROP}/albums/01/audio"
        doubled = urllib.parse.quote(str(self.root / "outside.mp3").lstrip("/"))
        for path in (f"{base}/{outside}", f"{base}//{doubled}"):
            with self.subTest(path=path):
                self.assertNotFound(path)

    def test_a_symlink_leading_out_of_the_album_is_404(self) -> None:
        for rel in ("link out.mp3", "Up/secret.mp3"):
            with self.subTest(rel=rel):
                self.assertNotFound(audio_url(DROP, "01", rel))

    def test_an_unknown_drop_or_album_is_404(self) -> None:
        for path in (
            audio_url("20260101-000000", "01", "01 one.mp3"),
            audio_url(DROP, "02", "01 one.mp3"),
            audio_url(DROP, "99", "01 one.mp3"),
        ):
            with self.subTest(path=path):
                self.assertNotFound(path)

    def test_a_missing_file_or_a_folder_is_404(self) -> None:
        for rel in ("06 six.mp3", "CD2/01 one.mp3", "CD2"):
            with self.subTest(rel=rel):
                self.assertNotFound(audio_url(DROP, "01", rel))

    def test_a_missing_file_is_404_with_a_range_too(self) -> None:
        # A server that checks the range before the file would say 416 here.
        answer = self.fetch(audio_url(DROP, "01", "06 six.mp3"), "bytes=999999-")
        self.assertEqual(answer.status, 404)

    def test_an_album_already_in_the_library_is_404(self) -> None:
        # The library holds the same track under the same name; the url
        # serves staged files only, never the library.
        self.assertNotFound(audio_url(LANDED, "01", "01 one.mp3"))


if __name__ == "__main__":
    unittest.main()
