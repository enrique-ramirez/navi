"""Creating a drop and uploading its files.

The page `POST`s the whole list of what was dropped, paths and sizes, before
it sends a byte, so the server can refuse a loose audio file and a drop the
disk has no room for. Then it `PUT`s each file's bytes, and the server writes
them under `inbox/<drop>/raw/<item>/`.

Each test serves `agitha.server.make_server` on a thread over its own
temporary folders, with the free space and the clock faked through `Config`,
and talks to it over HTTP. What these tests read on disk is the layout the
plan fixes: `inbox/<drop>/drop.json` and `inbox/<drop>/raw/<item>/<path>`.

`POST /api/drops/<drop>/done` (and the `incomplete` state) belongs to
other tests. Here a drop is only ever `uploading`.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

STUB = Path(__file__).resolve().parent / "agitha_stub.py"

FREE = 10_000_000
AT = datetime(2026, 9, 29, 21, 30, 0)
AT_ID = "20260929-213000"

AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wma", ".wav", ".aiff", ".ape", ".wv", ".mpc")
REFUSAL = "drop the folder that holds it"

# Every byte value, and a CRLF, so a text-mode write or a decode shows.
PAYLOAD = bytes(range(256)) * 16 + b"\r\n\x00end"


class Clock:
    """`Config.now`: answers `at` however often it is asked, so two drops can share a second."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def folder(name: str, *files: tuple[str, int]) -> dict:
    return {"name": name, "kind": "folder", "files": [{"path": p, "size": s} for p, s in files]}


def archive(name: str, size: int) -> dict:
    return {"name": name, "kind": "archive", "files": [{"path": name, "size": size}]}


def loose(name: str, size: int) -> dict:
    return {"name": name, "kind": "file", "files": [{"path": name, "size": size}]}


def files_under(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


class ServedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Imported here so that, while the package is missing, each case
        # fails on its own rather than the module failing once.
        from agitha.server import Config, make_server

        self.root = Path(tempfile.mkdtemp(prefix="agitha-drops-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        folders = {name: self.root / name for name in ("inbox", "jobs", "library", "extras", "static")}
        for path in folders.values():
            path.mkdir()
        (folders["static"] / "index.html").write_text("<!doctype html><title>agitha</title>", encoding="utf-8")
        self.inbox = folders["inbox"]
        self.clock = Clock(AT)
        self.server = make_server(Config(
            inbox=self.inbox, jobs=folders["jobs"], library=folders["library"], extras=folders["extras"],
            musiclib=str(STUB), static=folders["static"], port=0, host="127.0.0.1",
            free_space=lambda _path: FREE, now=self.clock,
        ))
        # A short poll, or each test's shutdown waits half a second.
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, method: str, path: str, body: object = None, data: bytes | None = None) -> tuple[int, object]:
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        request = Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            with error:
                status, raw = error.code, error.read()
        return status, (json.loads(raw) if raw else None)

    def create(self, *items: dict) -> str:
        status, body = self.call("POST", "/api/drops", {"items": list(items)})
        self.assertEqual(status, 201, body)
        return body["drop"]

    def put(self, drop: str, item: str, path: str, data: bytes) -> tuple[int, object]:
        url = f"/api/drops/{quote(drop, safe='')}/files/{quote(item, safe='')}/{quote(path, safe='/')}"
        return self.call("PUT", url, data=data)


class CreatingADrop(ServedTestCase):
    def test_the_id_is_the_clock_as_year_month_day_dash_hours_minutes_seconds(self) -> None:
        # Single-digit fields, so a missing zero pad shows.
        self.clock.at = datetime(2026, 1, 2, 3, 4, 5)
        status, body = self.call("POST", "/api/drops", {"items": [archive("x.zip", 456)]})
        self.assertEqual((status, body), (201, {"drop": "20260102-030405"}))

    def test_a_second_and_a_third_drop_in_the_same_second_get_dash_2_and_dash_3(self) -> None:
        ids = [self.create(archive("x.zip", 456)) for _ in range(3)]
        self.assertEqual(ids, [AT_ID, f"{AT_ID}-2", f"{AT_ID}-3"])
        self.assertEqual({p.name for p in self.inbox.iterdir()}, set(ids))

    def test_an_id_is_taken_when_its_folder_exists_from_before_the_server_started(self) -> None:
        # A count kept in memory would hand out the bare id again after a restart.
        (self.inbox / AT_ID).mkdir()
        self.assertEqual(self.create(archive("x.zip", 456)), f"{AT_ID}-2")

    def test_the_drop_folder_holds_drop_json_with_the_items_as_sent_and_a_raw_folder(self) -> None:
        items = [
            folder("Sonata Arctica", ("2014 - Pariah's Child/01.mp3", 123), ("2014 - Pariah's Child/CD2/01.flac", 7)),
            archive("x.zip", 456),
            loose("notes.txt", 9),
        ]
        drop = self.create(*items)
        here = self.inbox / drop
        record = json.loads((here / "drop.json").read_text(encoding="utf-8"))
        self.assertEqual(record["items"], items)
        self.assertIs(record["done"], False)
        self.assertEqual(datetime.fromisoformat(record["started"]), AT)
        self.assertTrue((here / "raw").is_dir())

    def test_a_loose_audio_file_is_refused_with_drop_the_folder_that_holds_it(self) -> None:
        for extension in AUDIO:
            with self.subTest(extension=extension):
                # The audio file comes second, so a check of the first item alone passes it.
                items = [folder("Sonata Arctica", ("01.mp3", 1)), loose(f"01 - Track{extension}", 5)]
                status, body = self.call("POST", "/api/drops", {"items": items})
                self.assertEqual(status, 400, body)
                self.assertIn(REFUSAL, body["error"])
                self.assertEqual(list(self.inbox.iterdir()), [])

    def test_a_loose_file_that_is_not_audio_is_accepted_and_recorded(self) -> None:
        items = [folder("Sonata Arctica", ("01.mp3", 1)), loose("readme.txt", 3), loose("cover.jpg", 4)]
        drop = self.create(*items)
        record = json.loads((self.inbox / drop / "drop.json").read_text(encoding="utf-8"))
        self.assertEqual(record["items"], items)

    def test_a_folder_is_accepted_whatever_its_name_ends_in(self) -> None:
        # The refusal is for loose files; a folder named like an audio file is still a folder.
        self.create(folder("Live.flac", ("01.flac", 1)))

    def test_a_drop_with_no_items_is_refused(self) -> None:
        status, body = self.call("POST", "/api/drops", {"items": []})
        self.assertEqual(status, 400, body)
        self.assertTrue(body["error"])
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_a_drop_over_half_the_free_space_is_refused_naming_both_numbers(self) -> None:
        # Two items, so a total taken from the first item alone fits.
        items = [folder("A", ("01.mp3", 3_000_000)), archive("b.zip", 2_000_001)]
        status, body = self.call("POST", "/api/drops", {"items": items})
        self.assertEqual(status, 400, body)
        self.assertEqual((body["free"], body["needed"]), (10_000_000, 10_000_002))
        # Thousands separators are the server's choice; the digits are not.
        digits = re.sub(r"(?<=\d)[,._   ](?=\d{3})", "", body["error"])
        self.assertIn("10000000", digits)
        self.assertIn("10000002", digits)
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_a_drop_of_exactly_half_the_free_space_is_accepted(self) -> None:
        self.create(folder("A", ("01.mp3", 3_000_000)), archive("b.zip", 2_000_000))


class UploadingAFile(ServedTestCase):
    ITEM = "Café Tacvba"
    PATH = "1994 - Re/02 - El Ciclón.mp3"

    def make_drop(self, *more: dict) -> str:
        return self.create(folder(self.ITEM, (self.PATH, len(PAYLOAD)), ("1994 - Re/01.mp3", 1)), *more)

    def test_the_bytes_land_exactly_under_raw_item_path_with_204(self) -> None:
        drop = self.make_drop(archive("x y.zip", 5))
        self.assertEqual(self.put(drop, self.ITEM, self.PATH, PAYLOAD), (204, None))
        self.assertEqual(self.put(drop, "x y.zip", "x y.zip", b"PK\x03\x04\x00"), (204, None))
        raw = self.inbox / drop / "raw"
        self.assertEqual((raw / self.ITEM / self.PATH).read_bytes(), PAYLOAD)
        self.assertEqual((raw / "x y.zip" / "x y.zip").read_bytes(), b"PK\x03\x04\x00")

    def test_a_second_put_of_the_same_path_overwrites_the_first(self) -> None:
        # Shorter the second time, so a write that does not truncate leaves a tail.
        drop = self.make_drop()
        self.put(drop, self.ITEM, self.PATH, PAYLOAD)
        self.assertEqual(self.put(drop, self.ITEM, self.PATH, b"second"), (204, None))
        self.assertEqual((self.inbox / drop / "raw" / self.ITEM / self.PATH).read_bytes(), b"second")

    def test_a_path_with_dot_dot_or_an_absolute_path_is_refused_and_nothing_is_written(self) -> None:
        outside = self.root / "outside.mp3"
        # A path the page never lists would be refused as unlisted anyway, so
        # these are listed: the `..` refusal has to hold on its own. Whether
        # creating such a drop is refused first is left open; either way
        # nothing may be written.
        sneaky = {
            "dot dot": "../../../outside.mp3",
            "dot dot inside": "1994 - Re/../01.mp3",
            "absolute": str(outside),
        }
        for case, path in sneaky.items():
            with self.subTest(case=case):
                before = files_under(self.root)
                status, body = self.call("POST", "/api/drops", {"items": [folder(self.ITEM, ("01.mp3", 1), (path, 1))]})
                if status == 201:
                    drop = body["drop"]
                    before = files_under(self.root)
                    self.assertEqual(self.put(drop, self.ITEM, path, b"x")[0], 400)
                    # The same with every separator encoded, so a split before decoding does not help.
                    encoded = f"/api/drops/{drop}/files/{quote(self.ITEM, safe='')}/{quote(path, safe='')}"
                    self.assertEqual(self.call("PUT", encoded, data=b"x")[0], 400)
                else:
                    self.assertEqual(status, 400, body)
                self.assertEqual(files_under(self.root), before)
                self.assertFalse(outside.exists())

    def test_an_unknown_drop_is_404(self) -> None:
        self.make_drop()
        status, body = self.put("20990101-000000", self.ITEM, self.PATH, b"x")
        self.assertEqual(status, 404, body)
        self.assertTrue(body["error"])

    def test_an_item_not_in_the_drop_is_400_and_nothing_is_written(self) -> None:
        drop = self.make_drop()
        before = files_under(self.root)
        status, body = self.put(drop, "Somebody Else", self.PATH, b"x")
        self.assertEqual(status, 400, body)
        self.assertEqual(files_under(self.root), before)

    def test_a_path_listed_under_another_item_is_400_and_nothing_is_written(self) -> None:
        drop = self.make_drop(folder("Other", ("only-here.mp3", 1)))
        before = files_under(self.root)
        status, body = self.put(drop, self.ITEM, "only-here.mp3", b"x")
        self.assertEqual(status, 400, body)
        self.assertEqual(files_under(self.root), before)

    def test_a_drop_already_done_refuses_a_put_with_409(self) -> None:
        drop = self.make_drop()
        record_path = self.inbox / drop / "drop.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["done"] = True
        record_path.write_text(json.dumps(record), encoding="utf-8")
        status, body = self.put(drop, self.ITEM, self.PATH, b"x")
        self.assertEqual(status, 409, body)
        self.assertFalse((self.inbox / drop / "raw" / self.ITEM / self.PATH).exists())


class TheListWhileUploading(ServedTestCase):
    def test_a_drop_with_two_of_three_files_sent_is_uploading_and_counts_those_two(self) -> None:
        # Three sizes whose every partial sum differs, so the count names which two arrived.
        small, middle, large = b"a" * 10, b"b" * 200, b"c" * 3000
        items = [folder("Sonata Arctica", ("01.mp3", 10), ("02.mp3", 200)), archive("x.zip", 3000)]
        drop = self.create(*items)
        self.put(drop, "Sonata Arctica", "02.mp3", middle)
        self.put(drop, "x.zip", "x.zip", large)

        status, drops = self.call("GET", "/api/drops")
        self.assertEqual(status, 200, drops)
        [listed] = [d for d in drops if d["id"] == drop]
        self.assertEqual(listed["state"], "uploading")
        self.assertEqual(datetime.fromisoformat(listed["started"]), AT)
        self.assertEqual(listed["items"], items)
        self.assertEqual((listed["albums"], listed["ignored"], listed["refused"]), ([], [], []))
        self.assertEqual(listed["received"], {"files": 2, "bytes": 3200})
        self.assertEqual(sum(f["size"] for i in listed["items"] for f in i["files"]), len(small + middle + large))

        # Sending a file again replaces it; it is still one file.
        self.put(drop, "x.zip", "x.zip", large)
        [listed] = [d for d in self.call("GET", "/api/drops")[1] if d["id"] == drop]
        self.assertEqual(listed["received"], {"files": 2, "bytes": 3200})


if __name__ == "__main__":
    unittest.main()
