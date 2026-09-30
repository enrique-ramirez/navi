"""agitha's queue: one musiclib process at a time, and what each album shows while it waits.

Once a drop is done, each album is identified with
`musiclib batch identify <inbox>/<drop>/<n> --job <jobs>/agitha-<drop>-<n>`,
one process at a time across every drop, and shows `queued`, `identifying`,
then `ready`. An album whose identify fails shows the last 20 lines of its
stderr and offers Retry and Discard, and its siblings go on. Two albums of
one drop planning one destination name each other. The queue also owns one
part of Discard: it is refused while a musiclib process is queued or running
for the album.

The server runs on a thread over temporary folders and is driven over HTTP
the way the page drives it. Its `musiclib` is a wrapper written per test:
it records each call's words and times, waits for the test to let it go
(`go-<k>` for the k-th call, or `open` for all of them), and then runs
`tests/agitha_stub.py`, which runs the real engine over a fake MusicBrainz.
Holding a call is what makes `queued` and `identifying` observable without
sleeping: an album stays `identifying` for as long as the test holds it.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from agitha.server import Config, make_server
from tests import builders
from tests.test_batch_identify import release

STUB = Path(__file__).resolve().parent / "agitha_stub.py"
# Not resolved: the venv's python is a symlink, and following it loses the venv's mutagen.
PYTHON = os.path.abspath(sys.executable)

TITLES = ["One", "Two"]
CLEAN = release(71, "Clean Band", "Clean Album", TITLES)
OTHER = release(72, "Other Band", "Other Album", TITLES)
THIRD = release(73, "Third Band", "Third Album", TITLES)

STUB_FAILURE = [f"agitha stub: line {n}" for n in range(5, 25)]
NOTHING_PLANNED = ["agitha test: looked everywhere", "agitha test: planned nothing"]

WRAPPER = """\
#!{python}
# musiclib for one test: records the call, waits to be let go, runs the stub.
import json, os, subprocess, sys, time
from pathlib import Path

control = Path({control!r})
k = 1
while True:
    try:
        os.close(os.open(control / f"call-{{k}}.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        break
    except FileExistsError:
        k += 1
record = {{"argv": sys.argv[1:], "start": time.time(), "end": None}}
(control / f"call-{{k}}.json").write_text(json.dumps(record))
deadline = time.time() + 30
while not (control / "open").exists() and not (control / f"go-{{k}}").exists():
    if time.time() > deadline:
        print("agitha test: nobody let call", k, "go", file=sys.stderr)
        sys.exit(3)
    time.sleep(0.01)
mode = (control / f"mode-{{k}}").read_text() if (control / f"mode-{{k}}").exists() else ""
env = dict(os.environ, AGITHA_STUB_CATALOGUE=str(control / "catalogue.json"))
env.pop("AGITHA_STUB_FAIL", None)
if mode == "fail":
    env["AGITHA_STUB_FAIL"] = "identify"
if mode == "empty":
    # Exits 0 with a plan that has no album in it.
    job = Path(sys.argv[sys.argv.index("--job") + 1])
    job.mkdir(parents=True, exist_ok=True)
    (job / "plan.json").write_text(json.dumps({{"albums": [], "job": job.name, "root": sys.argv[3]}}))
    print({nothing!r}, file=sys.stderr)
    code = 0
else:
    code = subprocess.run([{python!r}, {stub!r}, *sys.argv[1:]], env=env).returncode
record["end"] = time.time()
(control / f"call-{{k}}.json").write_text(json.dumps(record))
sys.exit(code)
"""


class QueueCase(unittest.TestCase):
    def setUp(self) -> None:
        # Resolved, so the paths the server passes on compare equal to these.
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        folders = {name: self.root / name for name in ("inbox", "jobs", "library", "extras", "static", "control",
                                                        "sources")}
        for folder in folders.values():
            folder.mkdir()
        (folders["static"] / "index.html").write_text("<!doctype html><title>agitha</title>\n")
        self.inbox, self.jobs, self.control, self.sources = (
            folders["inbox"], folders["jobs"], folders["control"], folders["sources"])
        (self.control / "catalogue.json").write_text(json.dumps([list(CLEAN), list(OTHER), list(THIRD)]))
        wrapper = self.control / "musiclib"
        wrapper.write_text(WRAPPER.format(python=PYTHON, control=str(self.control), stub=str(STUB),
                                          nothing="\n".join(NOTHING_PLANNED)))
        wrapper.chmod(0o755)

        config = Config(inbox=self.inbox, jobs=self.jobs, library=folders["library"], extras=folders["extras"],
                        musiclib=str(wrapper), static=folders["static"], port=0, host="127.0.0.1")
        self.server = make_server(config)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        # Runs first: nothing is left waiting on a gate, and no process writes
        # into the folders while they are removed.
        self.addCleanup(self._settle)
        self.seen: dict[tuple[str, str], list[str]] = {}

    def _settle(self) -> None:
        (self.control / "open").touch()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not any(album["busy"] for drop in self.list_drops() for album in drop["albums"]):
                return
            time.sleep(0.05)

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            connection.close()

    def list_drops(self) -> list[dict]:
        status, body = self.request("GET", "/api/drops")
        self.assertEqual(status, 200)
        return body

    def make_drop(self, albums: list[tuple[str, tuple[dict, dict]]]) -> str:
        """Creates a drop of one folder per album and uploads it; returns the drop's id, not yet done."""
        items = []
        for folder, (found, _group) in albums:
            base = self.sources / folder
            if not base.exists():
                build_album(base, folder, found)
            files = sorted(p.relative_to(base).as_posix() for p in base.iterdir())
            items.append({"name": folder, "kind": "folder",
                          "files": [{"path": name, "size": (base / name).stat().st_size} for name in files]})
        status, body = self.request("POST", "/api/drops", json.dumps({"items": items}).encode())
        self.assertIn(status, (200, 201), body)
        drop = body["drop"]
        for item in items:
            for file in item["files"]:
                path = urllib.parse.quote(f"/api/drops/{drop}/files/{item['name']}/{file['path']}")
                status, answer = self.request("PUT", path, (self.sources / item["name"] / file["path"]).read_bytes())
                self.assertLess(status, 300, answer)
        return drop

    def done(self, drop: str) -> dict:
        status, body = self.request("POST", f"/api/drops/{drop}/done")
        self.assertEqual(status, 202, body)
        return body

    def calls(self) -> list[dict]:
        found = []
        k = 1
        while (self.control / f"call-{k}.json").exists():
            text = (self.control / f"call-{k}.json").read_text()
            found.append(json.loads(text) if text else {"argv": None, "start": None, "end": None})
            k += 1
        return found

    def wait_for_call(self, k: int) -> None:
        deadline = time.monotonic() + 15
        while len(self.calls()) < k:
            if time.monotonic() > deadline:
                self.fail(f"musiclib was called {len(self.calls())} times, waited for call {k}")
            time.sleep(0.02)

    def go(self, k: int) -> None:
        (self.control / f"go-{k}").touch()

    def identify(self, drop: str, n: str) -> list[str]:
        # `started` is the server's local time, naive: its first 16 characters are the minute.
        started = json.loads((self.inbox / drop / "drop.json").read_text(encoding="utf-8"))["started"]
        return ["batch", "identify", str(self.inbox / drop / n), "--job", str(self.jobs / f"agitha-{drop}-{n}"),
                "--added", started[:16]]

    def watch(self, until, check=None, seconds: float = 15) -> dict[tuple[str, str], dict]:
        """Polls `GET /api/drops` until `until(albums)`; records every state each album showed.

        `albums` maps `(drop, n)` to the album's JSON. `check(albums)` runs on every poll.
        """
        deadline = time.monotonic() + seconds
        while True:
            albums = {(drop["id"], album["n"]): album for drop in self.list_drops() for album in drop["albums"]}
            for key, album in albums.items():
                states = self.seen.setdefault(key, [])
                if not states or states[-1] != album["state"]:
                    states.append(album["state"])
            if check:
                check(albums)
            if until(albums):
                return albums
            if time.monotonic() > deadline:
                self.fail(f"gave up waiting; states seen: {self.seen}")
            time.sleep(0.03)


def build_album(base: Path, folder: str, found: dict) -> None:
    """Two tagged MP3s and a cover, tagged with `found`'s id, as `make_fixtures.py` builds one."""
    base.mkdir(parents=True)
    artist = found["artist-credit"][0]["name"]
    for n, title in enumerate(TITLES, start=1):
        path = base / f"{n:02d} {title.lower()}.mp3"
        shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
        fields = {"title": [title.lower()], "artist": [artist], "album": [folder], "date": ["1989"],
                  "release id": [found["id"]]}
        builders.write_tags(path, builders.picard_tags("mp3", fields, track=(n, len(TITLES)), disc=(1, 1)),
                            v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")


def states(albums: dict, *keys: tuple[str, str]) -> list[str | None]:
    return [albums[key]["state"] if key in albums else None for key in keys]


class Identifying(QueueCase):
    def test_albums_of_two_drops_are_identified_one_process_at_a_time_in_the_order_they_were_queued(self) -> None:
        first = self.make_drop([("First Album", CLEAN)])
        answered = self.done(first)
        # The worker may already have taken it by the time the answer is built.
        self.assertIn(answered["albums"][0]["state"], ("queued", "identifying"))
        self.wait_for_call(1)
        x = (first, "01")
        self.watch(lambda albums: states(albums, x) == ["identifying"])

        second = self.make_drop([("Second Album", OTHER), ("Third Album", THIRD)])
        self.assertNotEqual(second, first)
        y1, y2 = (second, "01"), (second, "02")
        answered = self.done(second)
        # First's album holds the only process, so both of these wait.
        self.assertEqual([album["state"] for album in answered["albums"]], ["queued", "queued"])

        def one_at_a_time(albums: dict) -> None:
            running = [key for key, album in albums.items() if album["state"] == "identifying"]
            self.assertLessEqual(len(running), 1, running)

        self.watch(lambda albums: states(albums, x, y1, y2) == ["identifying", "queued", "queued"], one_at_a_time)
        self.assertEqual(len(self.calls()), 1)

        self.go(1)
        self.wait_for_call(2)
        # Queued first, started first: 01 before 02, though a sort by name or
        # destination would pick either.
        self.watch(lambda albums: states(albums, x, y1, y2) == ["ready", "identifying", "queued"], one_at_a_time)
        self.go(2)
        self.wait_for_call(3)
        self.watch(lambda albums: states(albums, x, y1, y2) == ["ready", "ready", "identifying"], one_at_a_time)
        self.go(3)
        self.watch(lambda albums: states(albums, x, y1, y2) == ["ready", "ready", "ready"], one_at_a_time)

        calls = self.calls()
        self.assertEqual([call["argv"] for call in calls],
                         [self.identify(first, "01"), self.identify(second, "01"), self.identify(second, "02")])
        for before, after in zip(calls, calls[1:]):
            self.assertLessEqual(before["end"], after["start"], "two musiclib processes overlapped")

        # The first album's `queued` lasts only until the idle worker takes it,
        # which no poll is sure to catch.
        self.assertIn(self.seen[x], (["queued", "identifying", "ready"], ["identifying", "ready"]))
        self.assertEqual(self.seen[y1], ["queued", "identifying", "ready"])
        self.assertEqual(self.seen[y2], ["queued", "identifying", "ready"])


class AddedStamp(unittest.TestCase):
    """`ADDED` is the drop's upload start, in the box's local time, to the minute."""

    def setUp(self) -> None:
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Mexico_City"
        time.tzset()

        def restore() -> None:
            if zone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = zone
            time.tzset()

        self.addCleanup(restore)

    def test_a_naive_start_is_already_local_and_is_cut_to_the_minute(self) -> None:
        from agitha.queue import added_stamp

        self.assertEqual(added_stamp({"started": "2026-09-30T11:02:59.912345"}), "2026-09-30T11:02")

    def test_a_start_with_an_offset_is_turned_into_local_time(self) -> None:
        from agitha.queue import added_stamp

        self.assertEqual(added_stamp({"started": "2026-09-30T17:02:10+00:00"}), "2026-09-30T11:02")

    def test_a_record_without_a_start_that_reads_gives_none(self) -> None:
        from agitha.queue import added_stamp

        for record in (None, {}, {"started": "yesterday"}):
            with self.subTest(record=record):
                self.assertIsNone(added_stamp(record))


class Failing(QueueCase):
    def test_a_failed_identify_shows_its_last_20_stderr_lines_and_retry_runs_it_again_while_its_sibling_finishes(
            self) -> None:
        (self.control / "mode-1").write_text("fail")
        drop = self.make_drop([("Failing Album", CLEAN), ("Sibling Album", OTHER)])
        a1, a2 = (drop, "01"), (drop, "02")
        self.done(drop)
        self.go(1)
        self.go(2)
        # Settled: a state can change a moment before `busy` does.
        albums = self.watch(lambda albums: states(albums, a1, a2) == ["identify failed", "ready"]
                            and not albums[a1]["busy"])

        failed = albums[a1]
        # The stub printed 25 lines; the first five are gone.
        self.assertEqual(failed["stderr"].splitlines(), STUB_FAILURE)
        self.assertIn("retry", failed["actions"])
        self.assertIn("discard", failed["actions"])
        self.assertFalse(failed["busy"])
        self.assertEqual(albums[a2]["stderr"], "")

        status, body = self.request("POST", f"/api/drops/{drop}/albums/02/retry")
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)

        status, body = self.request("POST", f"/api/drops/{drop}/albums/01/retry")
        self.assertLess(status, 300, body)
        self.wait_for_call(3)
        albums = self.watch(lambda albums: states(albums, a1) == ["identifying"])
        self.assertTrue(albums[a1]["busy"])
        self.assertNotIn("retry", albums[a1]["actions"])
        self.go(3)
        self.watch(lambda albums: states(albums, a1, a2) == ["ready", "ready"])

        # 02's refused retry ran nothing; 01's ran the same command again.
        self.assertEqual([call["argv"] for call in self.calls()],
                         [self.identify(drop, "01"), self.identify(drop, "02"), self.identify(drop, "01")])

    def test_identify_again_runs_a_ready_album_again_and_refuses_a_failed_one(self) -> None:
        (self.control / "mode-1").write_text("fail")
        drop = self.make_drop([("Failing Album", CLEAN), ("Ready Album", OTHER)])
        a1, a2 = (drop, "01"), (drop, "02")
        self.done(drop)
        self.go(1)
        self.go(2)
        albums = self.watch(lambda albums: states(albums, a1, a2) == ["identify failed", "ready"]
                            and not albums[a2]["busy"])
        self.assertIn("reidentify", albums[a2]["actions"])
        self.assertNotIn("reidentify", albums[a1]["actions"])

        status, body = self.request("POST", f"/api/drops/{drop}/albums/01/reidentify")
        self.assertEqual(status, 409, body)

        status, body = self.request("POST", f"/api/drops/{drop}/albums/02/reidentify")
        self.assertLess(status, 300, body)
        self.wait_for_call(3)
        self.go(3)
        self.watch(lambda albums: states(albums, a2) == ["ready"] and not albums[a2]["busy"])
        self.assertEqual([call["argv"] for call in self.calls()],
                         [self.identify(drop, "01"), self.identify(drop, "02"), self.identify(drop, "02")])

    def test_an_identify_that_exits_0_with_no_album_in_its_plan_counts_as_failed(self) -> None:
        (self.control / "mode-1").write_text("empty")
        (self.control / "open").touch()
        drop = self.make_drop([("Unplanned Album", CLEAN)])
        self.done(drop)
        albums = self.watch(lambda albums: states(albums, (drop, "01"))[0] not in (None, "queued", "identifying")
                            and not albums[(drop, "01")]["busy"])

        album = albums[(drop, "01")]
        self.assertEqual(album["state"], "identify failed")
        self.assertEqual(album["stderr"].splitlines(), NOTHING_PLANNED)
        self.assertIn("retry", album["actions"])


class SameDestination(QueueCase):
    def test_two_albums_of_one_drop_planning_one_destination_name_each_other(self) -> None:
        (self.control / "open").touch()
        drop = self.make_drop([("La la Love You", CLEAN), ("La la Love You Bonus", CLEAN), ("Something Else", OTHER)])
        self.done(drop)
        # Another drop with the same release: the naming is within a drop,
        # so this one names nobody and the pair above keeps naming each other.
        later = self.make_drop([("La la Love You Again", CLEAN)])
        self.done(later)
        keys = [(drop, "01"), (drop, "02"), (drop, "03"), (later, "01")]
        albums = self.watch(lambda albums: states(albums, *keys) == ["ready"] * 4)

        pair, other, elsewhere = albums[keys[0]], albums[keys[2]], albums[keys[3]]
        # Without one shared destination the rest proves nothing.
        self.assertIsNotNone(pair["destination"])
        self.assertEqual(albums[keys[1]]["destination"], pair["destination"])
        self.assertNotEqual(other["destination"], pair["destination"])
        self.assertEqual(elsewhere["destination"], pair["destination"])

        self.assertEqual(albums[keys[0]]["duplicate_of"], "02")
        self.assertEqual(albums[keys[1]]["duplicate_of"], "01")
        self.assertIsNone(other["duplicate_of"])
        self.assertIsNone(elsewhere["duplicate_of"])


class NoDiscardWhileBusy(QueueCase):
    def test_discard_is_neither_offered_nor_accepted_while_an_album_is_queued_or_identifying(self) -> None:
        drop = self.make_drop([("Running Album", CLEAN), ("Waiting Album", OTHER)])
        a1, a2 = (drop, "01"), (drop, "02")
        self.done(drop)
        self.wait_for_call(1)
        albums = self.watch(lambda albums: states(albums, a1, a2) == ["identifying", "queued"])

        for key in (a1, a2):
            with self.subTest(state=albums[key]["state"]):
                self.assertTrue(albums[key]["busy"])
                self.assertNotIn("discard", albums[key]["actions"])
                status, body = self.request("POST", f"/api/drops/{drop}/albums/{key[1]}/discard")
                self.assertEqual(status, 409, body)
                self.assertIsInstance(body.get("error"), str)
        listed = {drop_["id"]: drop_ for drop_ in self.list_drops()}
        self.assertEqual(listed[drop]["actions"], [])

        # Still there, and still going: the refusal cancelled nothing.
        self.assertTrue((self.inbox / drop / "01" / "drop" / "album" / "Running Album").is_dir())
        self.assertTrue((self.inbox / drop / "02" / "drop" / "album" / "Waiting Album").is_dir())
        self.go(1)
        self.go(2)
        self.watch(lambda albums: states(albums, a1, a2) == ["ready", "ready"])
        self.assertEqual(len(self.calls()), 2)

    def test_an_album_whose_run_raises_ends_failed_and_the_albums_behind_it_still_run(self) -> None:
        # The contract runs musiclib with `subprocess.run`, which raises
        # ValueError for an argument holding a null byte. The worker must
        # survive it: a dead worker leaves every later album queued and
        # busy, with no Discard, until agitha restarts.
        real = subprocess.run
        raised = []

        def run(args, *rest, **options):
            if not raised and args[1:3] == ["batch", "identify"] and args[3].endswith("/01"):
                raised.append(args)
                raise ValueError("embedded null byte")
            return real(args, *rest, **options)

        patcher = mock.patch("subprocess.run", run)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.control / "open").touch()
        drop = self.make_drop([("Raising Album", CLEAN), ("Behind Album", OTHER)])
        a1, a2 = (drop, "01"), (drop, "02")
        self.done(drop)
        albums = self.watch(lambda albums: states(albums, a1, a2) == ["identify failed", "ready"]
                            and not albums[a1]["busy"], seconds=10)

        self.assertEqual(len(raised), 1)
        failed = albums[a1]
        self.assertIn("embedded null byte", failed["stderr"] + (failed["error"] or ""))
        self.assertIn("retry", failed["actions"])
        self.assertIn("discard", failed["actions"])
        listed = {drop_["id"]: drop_ for drop_ in self.list_drops()}
        self.assertEqual(listed[drop]["actions"], ["discard"])


class AlbumNumbers(QueueCase):
    def test_every_album_route_answers_404_for_an_n_that_is_not_an_album_folder(self) -> None:
        # `.` once reached discard as the album and deleted the whole drop,
        # queued albums' jobs included. An album is two digits or more,
        # `01` onwards, so `1` is not album 01 either.
        (self.control / "open").touch()
        drop = self.make_drop([("Kept Album", CLEAN), ("Kept Too", OTHER)])
        self.done(drop)
        self.watch(lambda albums: states(albums, (drop, "01"), (drop, "02")) == ["ready", "ready"]
                   and not any(album["busy"] for album in albums.values()))
        before = (builders.tree(self.inbox), builders.tree(self.jobs))

        # Discard last: once a request deletes the drop, every later 404
        # would be true of a missing drop and would prove nothing.
        routes = [("POST", "retry", b""), ("POST", "approve", b"{}"), ("POST", "move", b""),
                  ("POST", "decision", b"{}"), ("PUT", "cover", builders.jpeg(500, 500)), ("GET", "", None),
                  ("GET", "audio/01%20one.mp3", None), ("POST", "discard", b"")]
        for method, tail, body in routes:
            for n in ("%2E", "%2E%2E", "x", "1"):
                path = f"/api/drops/{drop}/albums/{n}" + (f"/{tail}" if tail else "")
                with self.subTest(method=method, path=path):
                    status, _answer = self.request(method, path, body)
                    self.assertEqual(status, 404)
                # Outside the subtest, so the first request that changes the drop stops the test.
                self.assertEqual((builders.tree(self.inbox), builders.tree(self.jobs)), before, f"{method} {path}")


if __name__ == "__main__":
    unittest.main()
