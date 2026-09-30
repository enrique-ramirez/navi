"""What agitha lists after a start, read from the inbox and the jobs alone.

agitha keeps no database, so every drop and album state must come back from
the folders a previous process left behind. Each test lays those folders
out by hand, as the upload, the staging, the queue and `batch apply` would
have left them, and reads them with `agitha.state.read`. One test starts the
real server over the same folders and checks that `GET /api/drops` answers
the same list.

`actions` names the buttons the page offers for a drop or an album.
"""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from agitha import state

TESTS = Path(__file__).resolve().parent
PLAN = TESTS / "fixtures" / "agitha" / "auto-clean" / "plan.json"
STUB = TESTS / "agitha_stub.py"

#: The drop and album the auto-clean plan was made for, so its `source` and `job` match.
DROP = "20260929-210000"
NAME = "Clean Album"
DESTINATION = "C/Clean Band/(2010) Clean Album"

ITEMS = [{"name": NAME, "kind": "folder", "files": [
    {"path": "01 one.mp3", "size": 3},
    {"path": "02 two.mp3", "size": 3},
]}]

DROP_FIELDS = {"id", "state", "started", "items", "ignored", "refused", "albums", "received", "actions"}
ALBUM_FIELDS = {"n", "name", "state", "title", "artist", "year", "destination",
                "duplicate_of", "stderr", "error", "busy", "actions"}


class Disk:
    """A temporary `/srv/music` with helpers that leave what each step of agitha leaves."""

    def __init__(self, test: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.inbox = root / "inbox"
        self.jobs = root / ".musiclib" / "jobs"
        self.library = root / "library"
        self.extras = root / "extras"
        self.static = root / "static"
        for folder in (self.inbox, self.jobs, self.library, self.extras, self.static):
            folder.mkdir(parents=True)
        (self.static / "index.html").write_text("<!doctype html><title>agitha</title>", encoding="utf-8")

    def config(self, **more):
        from agitha.server import Config

        return Config(inbox=self.inbox, jobs=self.jobs, library=self.library, extras=self.extras,
                      musiclib=str(STUB), static=self.static, port=0, host="127.0.0.1", **more)

    def drop(self, drop: str = DROP, done: bool = True, items: list | None = None,
             arrived: list[str] | None = None) -> Path:
        """`drop.json`, and under `raw/` the files of `arrived` (`item/path`) when given."""
        folder = self.inbox / drop
        folder.mkdir()
        record = {"started": "2026-09-29T21:00:00", "items": ITEMS if items is None else items, "done": done}
        (folder / "drop.json").write_text(json.dumps(record), encoding="utf-8")
        for rel in arrived or []:
            path = folder / "raw" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"ID3")
        return folder

    def staged(self, n: str, name: str = NAME, drop: str = DROP) -> Path:
        album = self.inbox / drop / n / "drop" / "album" / name
        album.mkdir(parents=True)
        for file in ("01 one.mp3", "02 two.mp3"):
            (album / file).write_bytes(b"ID3")
        return album

    def written(self, n: str, destination: str = DESTINATION, drop: str = DROP) -> Path:
        """A finished album as `batch apply` leaves it: under a letter folder, `drop/` gone."""
        album = self.inbox / drop / n / destination
        album.mkdir(parents=True)
        for file in ("01 - One.mp3", "02 - Two.mp3"):
            (album / file).write_bytes(b"ID3")
        return album

    def record(self, n: str, drop: str = DROP, **fields) -> None:
        """The server's own `album.json`, as the queue writes it."""
        body = {"n": n, "name": NAME, "item": NAME, "state": "queued", "stderr": "", "error": None}
        body.update(fields)
        folder = self.inbox / drop / n
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "album.json").write_text(json.dumps(body), encoding="utf-8")

    def job(self, n: str, drop: str = DROP, plan: bool = True) -> Path:
        job = self.jobs / f"agitha-{drop}-{n}"
        job.mkdir(parents=True)
        if plan:
            shutil.copyfile(PLAN, job / "plan.json")
        return job

    def read(self) -> list[dict]:
        return state.read(self.config())


def by_id(drops: list[dict]) -> dict[str, dict]:
    return {drop["id"]: drop for drop in drops}


def album(drops: list[dict], n: str, drop: str = DROP) -> dict:
    found = [a for a in by_id(drops)[drop]["albums"] if a["n"] == n]
    if len(found) != 1:
        raise AssertionError(f"{drop}/{n}: {len(found)} albums in {by_id(drops)[drop]['albums']!r}")
    return found[0]


class IncompleteDrops(unittest.TestCase):
    """A drop that stopped before its last file stays, offering only Discard."""

    def test_a_drop_missing_files_under_raw_is_incomplete_with_no_albums_and_only_discard(self) -> None:
        disk = Disk(self)
        disk.drop(done=False, arrived=[f"{NAME}/01 one.mp3"])
        # The tab closed before the first file: no `raw/` at all.
        disk.drop("20260929-220000", done=False)
        drops = by_id(disk.read())
        self.assertEqual(sorted(drops), [DROP, "20260929-220000"])
        for drop in drops.values():
            self.assertEqual(drop["state"], "incomplete", drop["id"])
            self.assertEqual(drop["actions"], ["discard"], drop["id"])
            # `raw/` is the upload, never an album.
            self.assertEqual(drop["albums"], [], drop["id"])

    def test_a_drop_with_every_file_but_no_done_call_is_still_incomplete(self) -> None:
        # Guards against counting files: the page's `done` call never came,
        # so nothing was extracted or staged and nothing will be.
        disk = Disk(self)
        disk.drop(done=False, arrived=[f"{NAME}/01 one.mp3", f"{NAME}/02 two.mp3"])
        [drop] = disk.read()
        self.assertEqual(drop["state"], "incomplete")
        self.assertEqual(drop["actions"], ["discard"])
        self.assertEqual(drop["albums"], [])


class AlbumStates(unittest.TestCase):
    """Each album's state and offered actions, from what is on disk."""

    def test_a_staged_album_whose_job_has_no_plan_is_identify_interrupted_with_retry(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.staged("01")
        disk.staged("02")
        disk.job("02", plan=False)  # identify had started and written nothing yet
        drops = disk.read()
        for n in ("01", "02"):
            got = album(drops, n)
            self.assertEqual(got["state"], "identify interrupted", n)
            self.assertEqual(got["actions"], ["retry", "discard"], n)
            self.assertEqual(got["name"], NAME, n)
            self.assertIsNone(got["destination"], n)

    def test_a_staged_album_whose_job_has_a_plan_is_ready_and_offers_discard(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.staged("01")
        disk.job("01")
        got = album(disk.read(), "01")
        self.assertEqual(got["state"], "ready")
        self.assertIn("discard", got["actions"])
        self.assertNotIn("retry", got["actions"])
        self.assertNotIn("move", got["actions"])
        self.assertEqual(got["destination"], DESTINATION)

    def test_identify_failed_in_album_json_survives_with_its_stderr_and_retry(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.staged("01")
        disk.job("01", plan=False)
        stderr = "musiclib: MusicBrainz answered 503\nmusiclib: giving up"
        disk.record("01", state="identify failed", stderr=stderr, error="identify exited with status 1")
        got = album(disk.read(), "01")
        self.assertEqual(got["state"], "identify failed")
        self.assertEqual(got["actions"], ["retry", "discard"])
        self.assertEqual(got["stderr"], stderr)
        self.assertEqual(got["error"], "identify exited with status 1")

    def test_a_finished_album_under_a_letter_folder_with_no_drop_folder_is_written_not_moved(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.written("01")
        # `#` is the letter of an artist that starts with no A to Z.
        disk.written("02", "#/2 Many DJs/(2002) As Heard on Radio Soulwax")
        # apply leaves the job's plan behind; the letter folder wins over it,
        # so the album is moved and never identified or applied again.
        disk.job("01")
        disk.job("02")
        # apply stopped part way: files under the letter folder, `drop/` still there.
        disk.staged("03")
        disk.written("03")
        disk.job("03")
        drops = disk.read()
        for n in ("01", "02"):
            got = album(drops, n)
            self.assertEqual(got["state"], "written, not moved", n)
            self.assertEqual(got["actions"], ["move", "discard"], n)
        # Nothing says what an album with no `drop/` folder is.
        self.assertNotEqual(album(drops, "03")["state"], "written, not moved")
        self.assertNotIn("move", album(drops, "03")["actions"])

    def test_an_album_json_saying_in_the_library_offers_nothing(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.record("01", state="in the library", path=f"/srv/music/library/{DESTINATION}")
        disk.job("01")
        got = album(disk.read(), "01")
        self.assertEqual(got["state"], "in the library")
        self.assertEqual(got["actions"], [])

    def test_an_album_folder_with_neither_drop_nor_a_letter_folder_is_incomplete(self) -> None:
        disk = Disk(self)
        disk.drop()
        # Three levels deep, as a finished album is, under a folder that is no single letter.
        stray = disk.inbox / DROP / "01" / "CB" / "Clean Band" / "(2010) Clean Album"
        stray.mkdir(parents=True)
        (stray / "01 - One.mp3").write_bytes(b"ID3")
        (disk.inbox / DROP / "02").mkdir()
        drops = disk.read()
        for n in ("01", "02"):
            got = album(drops, n)
            self.assertEqual(got["state"], "incomplete", n)
            self.assertEqual(got["actions"], ["discard"], n)


class Listing(unittest.TestCase):
    def test_only_folders_named_like_a_drop_id_are_listed(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.drop(f"{DROP}-2")
        (disk.inbox / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
        (disk.inbox / "notes.txt").write_text("drop.json", encoding="utf-8")
        (disk.inbox / "lost+found").mkdir()
        # Near misses, each with a `drop.json` so only the name keeps them out.
        disk.drop("20260929-21000")
        disk.drop(f"{DROP}-a")
        disk.drop(f"x{DROP}")
        self.assertEqual(sorted(d["id"] for d in disk.read()), [DROP, f"{DROP}-2"])

    def test_drops_come_back_sorted_by_id_and_albums_by_n(self) -> None:
        disk = Disk(self)
        # Made out of order; this filesystem lists them out of order too.
        for drop in (f"{DROP}-2", "20260101-090000", DROP):
            disk.drop(drop)
        for n in ("03", "01", "02"):
            disk.staged(n)
        drops = disk.read()
        self.assertEqual([d["id"] for d in drops], ["20260101-090000", DROP, f"{DROP}-2"])
        self.assertEqual([a["n"] for a in by_id(drops)[DROP]["albums"]], ["01", "02", "03"])

    def test_every_drop_and_album_carries_the_fields_the_page_reads(self) -> None:
        disk = Disk(self)
        disk.drop()
        disk.staged("01")
        disk.job("01")
        disk.staged("02")
        disk.drop("20260929-220000", done=False, arrived=[f"{NAME}/01 one.mp3"])
        drops = disk.read()
        self.assertEqual(len(drops), 2)
        for drop in drops:
            self.assertLessEqual(DROP_FIELDS, set(drop), drop["id"])
            # What the page sent, from `drop.json`.
            self.assertEqual(drop["started"], "2026-09-29T21:00:00")
            self.assertEqual(drop["items"], ITEMS)
            for got in drop["albums"]:
                self.assertLessEqual(ALBUM_FIELDS, set(got), got["n"])
        self.assertEqual(len(by_id(drops)[DROP]["albums"]), 2)


class Restart(unittest.TestCase):
    def test_a_state_recorded_by_a_process_that_died_comes_back_from_disk(self) -> None:
        # The queue wrote `queued` or `identifying` and the process died, so
        # nothing is running now: no plan means Retry, a plan means ready.
        disk = Disk(self)
        disk.drop()
        disk.staged("01")
        disk.record("01", state="queued")
        disk.staged("02")
        disk.record("02", state="identifying")
        disk.job("02", plan=False)
        disk.staged("03")
        disk.record("03", state="identifying")
        disk.job("03")
        first = disk.read()
        expected = {"01": ("identify interrupted", ["retry", "discard"]),
                    "02": ("identify interrupted", ["retry", "discard"])}
        for n, (want, actions) in expected.items():
            got = album(first, n)
            self.assertEqual(got["state"], want, n)
            self.assertEqual(got["actions"], actions, n)
        self.assertEqual(album(first, "03")["state"], "ready")
        for n in ("01", "02", "03"):
            self.assertIs(album(first, n)["busy"], False, n)
        # A second read, as a second start would make, loses nothing.
        self.assertEqual(disk.read(), first)


class Served:
    """A running server over `disk`, with plain HTTP calls."""

    def __init__(self, test: unittest.TestCase, config) -> None:
        from agitha.server import make_server

        self.server = make_server(config)
        test.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        test.addCleanup(thread.join, 5)
        test.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, method: str, path: str, data: bytes | None = None, body: object = None):
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                raw = answer.read()
                return answer.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as refusal:
            raw = refusal.read()
            return refusal.code, json.loads(raw) if raw else None

    def create(self, items: list) -> str:
        status, body = self.call("POST", "/api/drops", body={"items": items})
        if status != 201:
            raise AssertionError(f"create answered {status}: {body!r}")
        return body["drop"]

    def put(self, drop: str, item: str, path: str, data: bytes = b"ID3") -> int:
        url = f"/api/drops/{quote(drop, safe='')}/files/{quote(item, safe='')}/{quote(path, safe='/')}"
        return self.call("PUT", url, data=data)[0]

    def listed(self, drop: str) -> dict:
        status, body = self.call("GET", "/api/drops")
        if status != 200:
            raise AssertionError(f"GET /api/drops answered {status}: {body!r}")
        return by_id(body)[drop]


class Clock:
    """`Config.now`, moved by hand, remembering what it told the server's threads."""

    def __init__(self) -> None:
        self.at = datetime(2026, 9, 29, 21, 0, 0)
        self.main = threading.current_thread()
        self.told: list[datetime] = []

    def __call__(self) -> datetime:
        if threading.current_thread() is not self.main:
            self.told.append(self.at)
        return self.at

    def wait_for_a_reading(self, since: datetime, seconds: float = 2.0) -> None:
        """Until a server thread has read the clock at `since` or later, or `seconds` pass."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not any(at >= since for at in self.told):
            time.sleep(0.005)

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


class AnUploadThatStops(unittest.TestCase):
    """Criterion 15 while the server keeps running: a drop nobody sends to stops being `uploading`."""

    def test_a_drop_with_no_put_for_upload_idle_seconds_reads_incomplete_and_a_later_put_resumes_it(self) -> None:
        # Decided for T35: the time of the last PUT comes from `Config.now`,
        # the clock the drop's `started` already comes from.
        disk = Disk(self)
        clock = Clock()
        served = Served(self, disk.config(now=clock, upload_idle=60.0, free_space=lambda _path: 10**12))
        drop = served.create(ITEMS)

        # Idle is counted from the last PUT, never from the drop's start.
        clock.advance(50)
        self.assertEqual(served.put(drop, NAME, "01 one.mp3"), 204)
        clock.advance(50)
        self.assertEqual(served.listed(drop)["state"], "uploading")

        clock.advance(11)
        stopped = served.listed(drop)
        self.assertEqual(stopped["state"], "incomplete")
        self.assertEqual(stopped["actions"], ["discard"])
        self.assertEqual(stopped["albums"], [])

        # The tab was only slow: `done` never came, so the file is taken and the drop goes on.
        self.assertEqual(served.put(drop, NAME, "02 two.mp3"), 204)
        self.assertEqual(served.listed(drop)["state"], "uploading")


    def test_a_file_still_arriving_keeps_its_drop_uploading_past_upload_idle(self) -> None:
        # Idle is counted from the last byte in, so one long file does not
        # read `incomplete` halfway and stop the page polling.
        disk = Disk(self)
        clock = Clock()
        piece = 4096
        items = [{"name": NAME, "kind": "folder", "files": [{"path": "01 one.flac", "size": 3 * piece}]}]
        served = Served(self, disk.config(now=clock, upload_idle=0.2, free_space=lambda _path: 10**12))
        drop = served.create(items)
        start = clock.at
        # Forget `create`'s reading, so the first wait below waits for the PUT's.
        clock.told.clear()

        sender = socket.create_connection(("127.0.0.1", served.server.server_address[1]), timeout=10)
        self.addCleanup(sender.close)
        path = f"/api/drops/{drop}/files/{quote(NAME, safe='')}/{quote('01 one.flac', safe='/')}"
        sender.sendall((f"PUT {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/octet-stream\r\n"
                        f"Content-Length: {3 * piece}\r\nConnection: close\r\n\r\n").encode("ascii"))
        sender.sendall(b"a" * piece)
        clock.wait_for_a_reading(start)
        clock.advance(0.15)
        sender.sendall(b"b" * piece)
        clock.wait_for_a_reading(clock.at)
        clock.advance(0.15)
        # 0.3 s since the PUT began, 0.15 s since its last byte.
        self.assertEqual(served.listed(drop)["state"], "uploading")

        sender.sendall(b"c" * piece)
        answer = b""
        while chunk := sender.recv(4096):
            answer += chunk
        self.assertTrue(answer.startswith(b"HTTP/1.") and answer.split(b" ", 2)[1] == b"204", answer[:200])
        self.assertEqual(served.listed(drop)["received"]["files"], 1)


class AStagingThatStops(unittest.TestCase):
    """Criterion 19: a drop whose `done` came and whose staging never finished."""

    def lay(self, disk: Disk) -> None:
        disk.drop(arrived=[f"{NAME}/01 one.mp3", f"{NAME}/02 two.mp3"])  # done: true, `raw/` left

    def test_a_finished_drop_with_raw_left_and_no_album_folders_reads_incomplete_from_disk(self) -> None:
        disk = Disk(self)
        self.lay(disk)
        [got] = disk.read()
        self.assertEqual(got["state"], "incomplete")
        self.assertEqual(got["actions"], ["discard"])
        self.assertEqual(got["albums"], [])

    def test_a_fresh_server_over_a_drop_left_mid_staging_lists_it_incomplete(self) -> None:
        disk = Disk(self)
        self.lay(disk)
        got = Served(self, disk.config()).listed(DROP)
        self.assertEqual(got["state"], "incomplete")
        self.assertEqual(got["actions"], ["discard"])

    def test_a_staging_that_raises_leaves_the_drop_incomplete_with_the_error_not_extracting(self) -> None:
        disk = Disk(self)
        served = Served(self, disk.config(free_space=lambda _path: 10**12))
        drop = served.create(ITEMS)
        for file in ITEMS[0]["files"]:
            self.assertEqual(served.put(drop, NAME, file["path"]), 204)

        go = threading.Event()

        def stage(_folder):
            go.wait(10)
            raise OSError("No space left on device: 'Clean Album'")

        seen: list[str] = []
        with mock.patch("agitha.albums.stage", side_effect=stage):
            finishing = threading.Thread(target=served.call, args=("POST", f"/api/drops/{drop}/done"), daemon=True)
            finishing.start()
            # While this process stages it, the drop is `extracting`.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and "extracting" not in seen:
                seen.append(served.listed(drop)["state"])
            go.set()
            finishing.join(10)
        self.assertFalse(finishing.is_alive(), "POST .../done never answered")
        self.assertIn("extracting", seen)

        got = served.listed(drop)
        self.assertEqual(got["state"], "incomplete")
        self.assertEqual(got["actions"], ["discard"])
        self.assertIn("No space left on device: 'Clean Album'", got["error"] or "")


class Server(unittest.TestCase):
    def test_get_api_drops_on_a_fresh_server_answers_what_read_finds(self) -> None:
        from agitha.server import make_server

        disk = Disk(self)
        disk.drop()
        (disk.inbox / DROP / "01").mkdir()
        disk.staged("02")
        disk.staged("03")
        disk.job("03")
        disk.written("04")
        disk.job("04")
        disk.drop("20260929-220000", done=False, arrived=[f"{NAME}/01 one.mp3"])
        (disk.inbox / "lost+found").mkdir()

        config = disk.config()
        server = make_server(config)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/drops", timeout=5) as answer:
            self.assertEqual(answer.status, 200)
            self.assertEqual(answer.headers["Content-Type"], "application/json; charset=utf-8")
            body = json.loads(answer.read().decode("utf-8"))

        self.assertEqual(body, state.read(config))
        self.assertEqual([d["id"] for d in body], [DROP, "20260929-220000"])
        self.assertEqual(by_id(body)["20260929-220000"]["state"], "incomplete")
        states = {a["n"]: (a["state"], a["actions"]) for a in by_id(body)[DROP]["albums"]}
        self.assertEqual(states["01"], ("incomplete", ["discard"]))
        self.assertEqual(states["02"], ("identify interrupted", ["retry", "discard"]))
        self.assertEqual(states["03"][0], "ready")
        self.assertEqual(states["04"], ("written, not moved", ["move", "discard"]))
        self.assertEqual(sorted(states), ["01", "02", "03", "04"])



#: A hold `batch identify --drop-unreadable` writes for a track whose file cannot be read.
#: It does not hold the word `missing`, so a refusal naming the kind is told from one quoting the detail.
MISSING = {"kind": "missing",
           "detail": 'track 2, "Two": 02 two.mp3 could be it, but it cannot be read'}

#: Holds that inform and do not stop Approve on their own, in the words `batch identify` writes them.
INFORMING = [{"kind": "validation", "detail": "file counts do not match"},
             {"kind": "status", "detail": "review: 2 of 3 files"},
             {"kind": "repointed", "detail": "6f1a2b3c-0000-4000-8000-000100000009"},
             {"kind": "reopened", "detail": ""}]

#: Holds that stop Approve on their own.
STOPPING = [{"kind": "error", "detail": "owner/cover.png: not an image"},
            {"kind": "decision", "detail": "accepted with problems"},
            {"kind": "collision", "detail": "C/Clean Band/(2010) Clean Album is already in the library"}]

#: The album `identified_with_a_truncated_track` stages: three tracks, the second cut off.
TRUNCATED_NAME = "Short Album"
TRUNCATED_TITLES = ["One", "Two", "Three"]
TRUNCATED_FILE = "02 two.mp3"


def identified_with_a_truncated_track(disk: Disk, n: str = "01", accept: bool = False) -> dict:
    """Album `n` of `DROP` staged with its second MP3 cut off and identified as agitha asks, with `--drop-unreadable`.

    The engine runs in the process over the fake MusicBrainz of
    `tests.test_batch_identify`, whose search lists every release it holds:
    a rip one file short does not match its own release ID's counts, so
    identify searches. `accept` writes the owner's accept of that release
    first, so the plan is made from it. Returns the release.
    """
    import io

    from musiclib import mb
    from musiclib.batch.identify import run
    from musiclib.batch.job import Job
    from tests import builders
    from tests.test_batch_identify import TRUNCATED, Unreadable, release

    found, group = release(81, "Short Band", TRUNCATED_NAME, TRUNCATED_TITLES)
    if not (disk.inbox / DROP).exists():
        disk.drop(items=[{"name": TRUNCATED_NAME, "kind": "folder", "files": []}])
    album = disk.inbox / DROP / n / "drop" / "album" / TRUNCATED_NAME
    album.mkdir(parents=True)
    for number, title in enumerate(TRUNCATED_TITLES, start=1):
        path = album / f"{number:02d} {title.lower()}.mp3"
        if path.name == TRUNCATED_FILE:
            path.write_bytes(TRUNCATED)
            continue
        shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
        fields = {"title": [title.lower()], "artist": ["Short Band"], "album": [TRUNCATED_NAME], "date": ["1989"],
                  "release id": [found["id"]]}
        builders.write_tags(path, builders.picard_tags("mp3", fields, track=(number, len(TRUNCATED_TITLES)),
                                                       disc=(1, 1)), v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", album / "cover.jpg")

    job = disk.jobs / f"agitha-{DROP}-{n}"

    def identify() -> None:
        err = io.StringIO()
        with mock.patch.object(mb, "_MIN_INTERVAL", 0.0):
            code = run(disk.inbox / DROP / n, Job(job), disk.jobs / "agitha-memory.json",
                       transport=Unreadable.Searching([(found, group)]), env={}, which=lambda _name: None,
                       out=io.StringIO(), err=err, drop_unreadable=True)
        if code:
            raise AssertionError(f"identify exited {code}: {err.getvalue()}")

    identify()
    if accept:
        # A decision names an album the job has already planned, so it comes second, as the page's Accept does.
        decisions = {"job": job.name, "albums": {f"drop/album/{TRUNCATED_NAME}": {
            "action": "accept", "release_id": found["id"], "edits": {}}}}
        (job / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
        identify()
    return found


class MissingBlocksApprove(unittest.TestCase):
    """An album with a `missing` hold is never approvable, whatever else it holds."""

    def setUp(self) -> None:
        self.config = Disk(self).config()

    def approvable(self, *holds: dict) -> dict:
        # Accepted, with a destination and a plan made from that decision:
        # nothing but the holds stands between it and Approve.
        entry = {"decision": "accept", "release_id": "6f1a2b3c-0000-4000-8000-000100000001",
                 "destination": DESTINATION, "holds": list(holds)}
        return state.approvable(self.config, DROP, "01", entry)

    def assertRefusedFor(self, offered: dict, hold: dict) -> None:
        self.assertIs(offered["ok"], False, offered)
        self.assertEqual(offered["code"], "held", offered)
        self.assertEqual(offered["hold"], hold, offered)
        # The review bar shows this sentence: it names the hold and says which track.
        self.assertIn(hold["kind"], offered["reason"])
        self.assertIn(hold["detail"], offered["reason"])

    def test_a_missing_hold_alone_refuses_approve_and_the_refusal_names_it(self) -> None:
        self.assertRefusedFor(self.approvable(MISSING), MISSING)

    def test_a_missing_hold_refuses_approve_after_holds_that_only_inform(self) -> None:
        # Listed first, each of these would be skipped by a refusal that only
        # looks at the first hold, or at a fixed list of kinds it knew of before.
        for informing in INFORMING:
            with self.subTest(before=informing["kind"]):
                self.assertRefusedFor(self.approvable(informing, MISSING), MISSING)
        self.assertRefusedFor(self.approvable(*INFORMING, MISSING), MISSING)

    def test_the_refusal_names_the_missing_hold_over_another_blocking_hold_listed_before_it(self) -> None:
        # "Refused with that hold, whatever else the album holds": the page puts
        # `missing` above every other hold, and the refusal agrees with it.
        # `batch identify` writes an `error` hold before the `missing` ones.
        for stopping in STOPPING:
            with self.subTest(before=stopping["kind"]):
                self.assertRefusedFor(self.approvable(stopping, MISSING), MISSING)

    def test_an_accepted_album_identified_with_a_truncated_track_is_refused_on_its_missing_hold(self) -> None:
        # The plan `batch identify --drop-unreadable` writes, not one made by
        # hand: the album is accepted and planned, and only the hold stops it.
        disk = Disk(self)
        found = identified_with_a_truncated_track(disk, accept=True)
        entry = state.plan_entry(disk.config(), DROP, "01")
        self.assertEqual((entry["decision"], entry["release_id"]), ("accept", found["id"]))
        self.assertTrue(entry["destination"], entry)
        held = [hold for hold in entry["holds"] if hold["kind"] == "missing"]
        self.assertEqual(len(held), 1, entry["holds"])

        self.assertRefusedFor(state.approvable(disk.config(), DROP, "01", entry), held[0])
        listed = album(disk.read(), "01")
        self.assertNotIn("approve", listed["actions"])


if __name__ == "__main__":
    unittest.main()
