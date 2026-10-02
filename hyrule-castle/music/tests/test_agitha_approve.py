"""Approve, Move and Discard: how an album gets from the inbox into the library, or out of the inbox.

Approve is refused unless the preview comes from an accept agitha wrote, has
a destination, and holds on nothing of kind `decision`, `error` or
`collision`; an `auto` or `certain` album waits like any other. An approve
runs `batch apply` and renames the finished folder into the library, making
the letter and artist folders. A rename that fails leaves the album `written,
not moved`, and Move retries the rename alone. An existing destination stops
approve before apply. A failing apply moves nothing. A landed album leaves
the inbox and keeps its job. Discard works per album and per drop, and is
refused while a musiclib process runs.

Each test lays out an inbox the way staging and identify leave it: the album
under `inbox/<drop>/<n>/drop/album/<name>/`, the server's `album.json` saying
`ready`, and a job made by running `tests/agitha_stub.py`'s identify. Where
the test wants an accept, it writes `decisions.json` and identifies again. The
server runs on a thread over those folders and is driven over HTTP. Its
`musiclib` is a wrapper written per test: it records each call's words in
`calls.jsonl`, waits while the file `hold` exists, then runs the stub. So a
test counts what the server ran and can keep an apply running while it looks.
"""

from __future__ import annotations

import errno
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
from pathlib import Path
from unittest import mock

from mutagen.id3 import ID3

from agitha.server import Config, make_server
from tests import builders
from tests.test_batch_identify import release

STUB = Path(__file__).resolve().parent / "agitha_stub.py"
# Not resolved: the venv's python is a symlink, and following it loses the venv's mutagen.
PYTHON = os.path.abspath(sys.executable)

DROP = "20260929-210000"
OTHER_DROP = "20260929-220000"
TITLES = ["One", "Two"]
CLEAN = release(81, "Clean Band", "Clean Album", TITLES)
OTHER = release(82, "Other Band", "Other Album", TITLES)
# A release group with no genre: an accept of it plans with a validation
# problem, and identify holds the album on `decision` (the decision-hold fixture's shape).
BARE = release(83, "Genreless Band", "Bare Album", TITLES, genres={})

# The stub prints a first line and 24 numbered ones; the server keeps the last 20.
STUB_FAILURE = [f"agitha stub: line {n}" for n in range(5, 25)]

WRAPPER = """\
#!{python}
# musiclib for one test: records the call, waits while `hold` exists, runs the stub.
import json, os, subprocess, sys, time
from pathlib import Path

control = Path({control!r})
with open(control / "calls.jsonl", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
deadline = time.time() + 30
while (control / "hold").exists():
    if time.time() > deadline:
        print("agitha test: nobody lifted the hold", file=sys.stderr)
        sys.exit(3)
    time.sleep(0.01)
env = dict(os.environ, AGITHA_STUB_CATALOGUE=str(control / "catalogue.json"))
env.pop("AGITHA_STUB_FAIL", None)
if (control / "fail").exists():
    env["AGITHA_STUB_FAIL"] = (control / "fail").read_text()
sys.exit(subprocess.run([{python!r}, {stub!r}, *sys.argv[1:]], env=env).returncode)
"""


class ApproveCase(unittest.TestCase):
    def setUp(self) -> None:
        # Resolved, so the paths the server builds compare equal to these.
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in ("inbox", "jobs", "library", "extras", "static", "control", "sources"):
            (self.root / name).mkdir()
        self.inbox, self.jobs, self.library = self.root / "inbox", self.root / "jobs", self.root / "library"
        self.extras, self.control, self.sources = self.root / "extras", self.root / "control", self.root / "sources"
        (self.root / "static" / "index.html").write_text("<!doctype html><title>agitha</title>\n")
        (self.control / "catalogue.json").write_text(json.dumps([list(CLEAN), list(OTHER), list(BARE)]))
        wrapper = self.control / "musiclib"
        wrapper.write_text(WRAPPER.format(python=PYTHON, control=str(self.control), stub=str(STUB)))
        wrapper.chmod(0o755)

        config = Config(inbox=self.inbox, jobs=self.jobs, library=self.library, extras=self.extras,
                        musiclib=str(wrapper), static=self.root / "static", port=0, host="127.0.0.1")
        self.server = make_server(config)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        # Runs first: no apply is left on the hold, and none writes while the folders go.
        self.addCleanup(self._settle)
        self.seen: dict[tuple[str, str], list[str | None]] = {}

    def _settle(self) -> None:
        (self.control / "hold").unlink(missing_ok=True)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, drops = self.request("GET", "/api/drops")
            if status != 200 or not any(album.get("busy") for drop in drops for album in drop.get("albums", [])):
                return
            time.sleep(0.05)

    def stage(self, n: str, folder: str, pair: tuple[dict, dict], accept: bool, drop: str = DROP) -> dict:
        """One album of `drop`, identified once; returns its preview (the plan's entry)."""
        found = pair[0]
        base = self.inbox / drop / n / "drop" / "album" / folder
        base.mkdir(parents=True)
        artist = found["artist-credit"][0]["name"]
        for k, title in enumerate(TITLES, start=1):
            path = base / f"{k:02d} {title.lower()}.mp3"
            shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
            fields = {"title": [title.lower()], "artist": [artist], "album": [folder], "date": ["1989"],
                      "release id": [found["id"]]}
            builders.write_tags(path, builders.picard_tags("mp3", fields, track=(k, len(TITLES)), disc=(1, 1)),
                                v2_version=4)
        shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")

        drop_json = self.inbox / drop / "drop.json"
        record = json.loads(drop_json.read_text()) if drop_json.exists() else {
            "started": "2026-09-29T21:00:00", "items": [], "done": True}
        record["items"].append({"name": folder, "kind": "folder", "files": [
            {"path": p.name, "size": p.stat().st_size} for p in sorted(base.iterdir())]})
        drop_json.write_text(json.dumps(record))
        (self.inbox / drop / n / "album.json").write_text(json.dumps(
            {"n": n, "name": folder, "item": folder, "state": "ready", "stderr": "", "error": None}))

        job = self.job(n, drop)
        job.mkdir()
        source = f"drop/album/{folder}"
        self.identify(job, self.inbox / drop / n)
        if accept:
            # identify takes an accept only for an album its plan already has, as the decision endpoint finds it.
            (job / "decisions.json").write_text(json.dumps({"job": job.name, "albums": {
                source: {"action": "accept", "release_id": found["id"]}}}))
            self.identify(job, self.inbox / drop / n)
        entry = json.loads((job / "plan.json").read_text())["albums"][0]
        self.assertEqual(entry["source"], source)
        return entry

    def identify(self, job: Path, root: Path) -> None:
        env = dict(os.environ, AGITHA_STUB_CATALOGUE=str(self.control / "catalogue.json"))
        env.pop("AGITHA_STUB_FAIL", None)
        env.pop("AGITHA_STUB_SLEEP", None)
        done = subprocess.run([PYTHON, str(STUB), "batch", "identify", str(root), "--job", str(job)],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def job(self, n: str, drop: str = DROP) -> Path:
        return self.jobs / f"agitha-{drop}-{n}"

    def files_under(self, folder: Path) -> dict[str, bytes]:
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

    def request(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode()
            headers = {} if body is None else {"Content-Type": "application/json"}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            connection.close()

    def approvable(self, n: str, drop: str = DROP) -> dict:
        """The album view's `approvable`, which the page turns into Approve's label."""
        status, view = self.request("GET", f"/api/drops/{drop}/albums/{n}")
        self.assertEqual(status, 200, view)
        return view["approvable"]

    def approve(self, n: str, drop: str = DROP) -> tuple[int, dict]:
        return self.request("POST", f"/api/drops/{drop}/albums/{n}/approve", {})

    def list_drops(self) -> dict[str, dict]:
        status, body = self.request("GET", "/api/drops")
        self.assertEqual(status, 200, body)
        return {drop["id"]: drop for drop in body}

    def album(self, n: str, drop: str = DROP) -> dict | None:
        found = [a for a in self.list_drops().get(drop, {}).get("albums", []) if a["n"] == n]
        return found[0] if found else None

    def watch(self, key: tuple[str, str], until, seconds: float = 15) -> dict | None:
        """Polls `GET /api/drops` until `until(album)`; `album` is None once the list lacks it.

        Every state the album showed is recorded in `self.seen[key]`, with None for gone.
        """
        deadline = time.monotonic() + seconds
        seen = self.seen.setdefault(key, [])
        while True:
            album = self.album(key[1], key[0])
            state = album["state"] if album else None
            if not seen or seen[-1] != state:
                seen.append(state)
            if until(album):
                return album
            if time.monotonic() > deadline:
                self.fail(f"gave up waiting on {key}; states seen: {seen}")
            time.sleep(0.03)

    def calls(self) -> list[list[str]]:
        log = self.control / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def wait_for_calls(self, count: int) -> None:
        deadline = time.monotonic() + 15
        while len(self.calls()) < count:
            if time.monotonic() > deadline:
                self.fail(f"musiclib was called {len(self.calls())} times, waited for {count}")
            time.sleep(0.02)

    def assert_one_apply(self, n: str, drop: str = DROP) -> None:
        """The only musiclib call was `batch apply` for this album's job, into these extras and library."""
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        argv = calls[0]
        self.assertEqual(argv[:2], ["batch", "apply"], argv)
        flags = dict(zip(argv[2::2], argv[3::2]))
        self.assertEqual(flags, {"--job": str(self.job(n, drop)), "--extras": str(self.extras),
                                 "--live-root": str(self.library)})

    def assert_library_empty(self) -> None:
        self.assertEqual(self.files_under(self.library), {})


class NotApprovable(ApproveCase):
    def test_an_auto_album_with_no_accept_is_refused_and_nothing_runs(self) -> None:
        # Certain and auto included, nothing lands without an accept and an Approve.
        entry = self.stage("01", "Clean Album", CLEAN, accept=False)
        self.assertEqual((entry["status"], entry["state"], entry["decision"], entry["holds"]),
                         ("certain", "auto", None, []))
        before = self.files_under(self.inbox / DROP / "01")
        offered = self.approvable("01")
        self.assertEqual((offered["ok"], offered["code"], offered["hold"]), (False, "not-accepted", None))

        status, body = self.approve("01")
        self.assertEqual(status, 409, body)
        self.assertIn("the preview has not been accepted yet", body["error"])

        self.assertEqual(self.calls(), [])
        self.assert_library_empty()
        self.assertEqual(self.files_under(self.inbox / DROP / "01"), before)
        self.assertEqual(self.album("01")["state"], "ready")

    def test_an_accept_held_on_decision_is_refused_with_the_hold_named(self) -> None:
        entry = self.stage("01", "Bare Album", BARE, accept=True)
        # Without these the refusal could be for the missing accept instead.
        self.assertEqual(entry["decision"], "accept")
        self.assertIsNotNone(entry["destination"])
        self.assertIn("decision", [hold["kind"] for hold in entry["holds"]])
        offered = self.approvable("01")
        self.assertEqual((offered["ok"], offered["code"]), (False, "held"))
        # The fixture's validation holds come first; the one that blocks is named.
        self.assertEqual(offered["hold"]["kind"], "decision")
        # The blocking hold names the validation problem itself, not just that there is one.
        problems = [hold["detail"] for hold in entry["holds"] if hold["kind"] == "validation"]
        self.assertTrue(problems)
        for problem in problems:
            self.assertIn(problem, offered["hold"]["detail"])

        status, body = self.approve("01")
        self.assertEqual(status, 409, body)
        self.assertIn("decision", body["error"])
        self.assertNotIn("not been accepted", body["error"])
        self.assertEqual(self.calls(), [])
        self.assert_library_empty()

    def test_an_accept_held_on_error_or_collision_or_with_no_destination_is_refused(self) -> None:
        # The stub cannot make an engine crash or a collision, so the accepted
        # preview is edited to carry each; approve refuses before apply reads it.
        self.stage("01", "Clean Album", CLEAN, accept=True)
        plan_path = self.job("01") / "plan.json"
        plan = json.loads(plan_path.read_text())
        cases = {
            "error": {"holds": [{"kind": "error", "detail": "the engine stopped on this album"}]},
            "collision": {"holds": [{"kind": "collision", "detail": "another album plans this folder"}]},
            "destination": {"destination": None},
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                edited = json.loads(json.dumps(plan))
                edited["albums"][0].update(change)
                plan_path.write_text(json.dumps(edited))
                status, body = self.approve("01")
                self.assertEqual(status, 409, body)
                if name != "destination":
                    self.assertIn(name, body["error"])
                # With no destination, `library / ""` is the library itself, which exists.
                self.assertNotIn("already in the library", body["error"])
        self.assertEqual(self.calls(), [])
        self.assert_library_empty()

    def test_an_album_the_drop_does_not_have_answers_404(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        for path in (f"/api/drops/{DROP}/albums/02/approve", f"/api/drops/{OTHER_DROP}/albums/01/approve"):
            with self.subTest(path=path):
                status, body = self.request("POST", path, {})
                self.assertEqual(status, 404, body)
        self.assertEqual(self.calls(), [])

    def test_an_existing_destination_stops_approve_before_apply_and_moves_nothing(self) -> None:
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        existing = self.library / entry["destination"]
        existing.mkdir(parents=True)
        (existing / "01. One.mp3").write_bytes(b"the copy already in the library")
        library_before = self.files_under(self.library)
        inbox_before = self.files_under(self.inbox / DROP / "01")

        status, body = self.approve("01")
        self.assertEqual(status, 409, body)
        self.assertIn("already in the library", body["error"])
        self.assertIn(entry["destination"], body["error"])

        self.assertEqual(self.calls(), [])
        self.assertEqual(self.files_under(self.library), library_before)
        self.assertEqual(self.files_under(self.inbox / DROP / "01"), inbox_before)

    def test_move_is_refused_for_an_album_that_is_not_written_not_moved(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        status, body = self.request("POST", f"/api/drops/{DROP}/albums/01/move", {})
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertEqual(self.calls(), [])
        self.assert_library_empty()


class Approving(ApproveCase):
    def test_approve_applies_then_renames_into_the_library_and_the_drop_leaves_the_list(self) -> None:
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        destination = entry["destination"]
        self.assertTrue(destination.startswith("C/Clean Band/"), destination)
        offered = self.approvable("01")
        self.assertEqual((offered["ok"], offered["code"], offered["hold"], offered["reason"]), (True, None, None, None))
        (self.control / "hold").touch()

        status, body = self.approve("01")
        self.assertEqual(status, 202, body)
        self.assertEqual(body["state"], "applying")
        self.wait_for_calls(1)
        held = self.watch((DROP, "01"), lambda album: album is not None and album["state"] == "applying")
        self.assertTrue(held["busy"])
        self.assertNotIn("approve", held["actions"])
        status, body = self.approve("01")
        self.assertEqual(status, 409, body)

        (self.control / "hold").unlink()
        self.watch((DROP, "01"), lambda album: album is None)
        # The album may leave the list before a poll catches `in the library`.
        self.assertIn(self.seen[(DROP, "01")], (["applying", None], ["applying", "in the library", None]))

        landed = self.library / destination
        self.assertEqual(sorted(self.files_under(landed)), ["01. One.mp3", "02. Two.mp3", "cover.jpg"])
        # Dropped as `one`: the title from MusicBrainz shows apply ran before the rename.
        self.assertEqual(ID3(landed / "01. One.mp3")["TIT2"].text, ["One"])
        self.assert_one_apply("01")

        self.assertFalse((self.inbox / DROP / "01").exists())
        self.assertFalse((self.inbox / DROP).exists())
        self.assertNotIn(DROP, self.list_drops())
        self.assertTrue((self.job("01") / "plan.json").is_file())

    def test_a_landed_album_still_opens_at_its_address_showing_where_it_went(self) -> None:
        # Landing deletes `<n>/` and, here, the whole drop; the album's
        # page must still say `in the library` and where, so a reload finds it.
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)
        target = self.library / entry["destination"]

        status, body = self.approve("01")
        self.assertEqual(status, 202, body)
        self.watch((DROP, "01"), lambda album: album is None)
        self.assert_landed_view("01", target, entry)

        # The drop's last album goes and the drop folder with it; the job stays.
        status, body = self.request("POST", f"/api/drops/{DROP}/albums/02/discard", {})
        self.assertEqual(status, 200, body)
        self.assertFalse((self.inbox / DROP).exists())
        self.assert_landed_view("01", target, entry)

    def assert_landed_view(self, n: str, target: Path, entry: dict) -> None:
        status, view = self.request("GET", f"/api/drops/{DROP}/albums/{n}")
        self.assertEqual(status, 200, view)
        self.assertEqual(view["state"], "in the library")
        self.assertEqual(view["library_path"], str(target))
        self.assertIs(view["busy"], False)
        self.assertEqual(view["preview"], entry)
        self.assertEqual((view["approvable"]["ok"], view["approvable"]["code"]), (False, "in-library"))

    def test_with_two_albums_approving_one_leaves_the_drop_listing_the_other(self) -> None:
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)

        status, body = self.approve("01")
        self.assertEqual(status, 202, body)
        self.watch((DROP, "01"), lambda album: album is None)

        self.assertTrue((self.library / entry["destination"] / "01. One.mp3").is_file())
        self.assertFalse((self.inbox / DROP / "01").exists())
        drop = self.list_drops()[DROP]
        self.assertEqual([(a["n"], a["state"]) for a in drop["albums"]], [("02", "ready")])
        self.assertTrue((self.inbox / DROP / "02" / "drop" / "album" / "Other Album" / "01 one.mp3").is_file())
        self.assertTrue((self.job("01") / "plan.json").is_file())
        self.assertTrue((self.job("02") / "plan.json").is_file())

    def test_a_failing_apply_moves_nothing_and_shows_its_stderr_with_only_discard(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        (self.control / "fail").write_text("apply")

        status, body = self.approve("01")
        self.assertEqual(status, 202, body)
        album = self.watch((DROP, "01"), lambda album: album is None or album["state"] not in ("queued", "applying"))

        self.assertIsNotNone(album, self.seen)
        self.assertEqual(album["state"], "apply failed")
        self.assertEqual(album["stderr"].splitlines(), STUB_FAILURE)
        self.assertEqual(album["actions"], ["discard"])
        self.assertFalse(album["busy"])
        self.assert_one_apply("01")
        self.assert_library_empty()
        self.assertTrue((self.inbox / DROP / "01" / "drop" / "album" / "Clean Album" / "01 one.mp3").is_file())

    def test_a_rename_refused_across_filesystems_leaves_it_written_not_moved_and_move_retries_only_the_rename(
            self) -> None:
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        destination = entry["destination"]
        finished = self.inbox / DROP / "01" / destination
        target = self.library / destination
        real_rename = os.rename
        refused: list[str] = []

        def rename(src, dst, *args, **kwargs):
            # Only a rename into the library fails, as it would with the library on another disk.
            if os.fspath(dst).startswith(str(self.library)):
                refused.append(os.fspath(dst))
                raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), os.fspath(src), None, os.fspath(dst))
            return real_rename(src, dst, *args, **kwargs)

        # `os.rename` itself, so `Path.rename` and a `from os import rename` taken after this both get it.
        with mock.patch("os.rename", new=rename):
            status, body = self.approve("01")
            self.assertEqual(status, 202, body)
            album = self.watch((DROP, "01"),
                               lambda album: album is None or album["state"] not in ("queued", "applying"))

        self.assertIsNotNone(album, self.seen)
        self.assertEqual(album["state"], "written, not moved")
        self.assertIn(str(finished), album["error"])
        self.assertIn(str(target), album["error"])
        self.assertEqual(album["actions"], ["move", "discard"])
        self.assertTrue(refused, "the server never tried to rename into the library")
        # No copy in place of the rename.
        self.assert_library_empty()
        self.assertEqual(sorted(self.files_under(finished)), ["01. One.mp3", "02. Two.mp3", "cover.jpg"])

        status, body = self.request("POST", f"/api/drops/{DROP}/albums/01/move", {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"state": "in the library", "path": str(target), "error": None,
                                "step": None, "file": None})
        self.assertEqual(sorted(self.files_under(target)), ["01. One.mp3", "02. Two.mp3", "cover.jpg"])
        self.assertEqual(ID3(target / "01. One.mp3")["TIT2"].text, ["One"])
        # Move ran neither apply nor identify again.
        self.assert_one_apply("01")
        self.assertFalse((self.inbox / DROP / "01").exists())
        self.assertNotIn(DROP, self.list_drops())
        self.assertTrue((self.job("01") / "plan.json").is_file())


class LogsWhatLands(ApproveCase):
    def test_an_approved_album_logs_the_apply_queued_and_then_its_path_in_the_library(self) -> None:
        entry = self.stage("01", "Clean Album", CLEAN, accept=True)
        with self.assertLogs("agitha.writes") as logged:
            self.assertEqual(self.approve("01")[0], 202)
            self.watch((DROP, "01"), lambda album: album is None)
        self.assertEqual(logged.output[:2], [
            f"INFO:agitha.writes:write queue-apply {DROP}/01",
            f"INFO:agitha.writes:write land {DROP}/01 path={entry['destination']}",
        ])

    def test_an_apply_that_fails_logs_the_album_and_its_exit_status(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        (self.control / "fail").write_text("apply")
        with self.assertLogs("agitha.writes") as logged:
            self.approve("01")
            self.watch((DROP, "01"), lambda album: album is None or album["state"] not in ("queued", "applying"))
        self.assertEqual(logged.output, [
            f"INFO:agitha.writes:write queue-apply {DROP}/01",
            f"WARNING:agitha.writes:write apply {DROP}/01 failed: apply exited with status 1",
        ])

    def test_a_discarded_album_and_the_drop_it_was_the_last_of_are_a_line_each(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        with self.assertLogs("agitha.writes") as logged:
            self.request("POST", f"/api/drops/{DROP}/albums/01/discard", {})
        self.assertEqual(logged.output, [f"INFO:agitha.writes:write discard-album {DROP}/01",
                                         f"INFO:agitha.writes:write clear-drop {DROP}"])

    def test_a_discarded_drop_logs_each_album_and_then_the_drop(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)
        with self.assertLogs("agitha.writes") as logged:
            self.request("POST", f"/api/drops/{DROP}/discard", {})
        self.assertEqual(sorted(logged.output[:2]), [f"INFO:agitha.writes:write discard-album {DROP}/01",
                                                     f"INFO:agitha.writes:write discard-album {DROP}/02"])
        self.assertEqual(logged.output[2:], [f"INFO:agitha.writes:write discard-drop {DROP} albums=2"])


class Discarding(ApproveCase):
    def test_discard_of_the_album_and_of_its_drop_is_refused_while_its_apply_runs(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)
        (self.control / "hold").touch()
        status, body = self.approve("01")
        self.assertEqual(status, 202, body)
        self.wait_for_calls(1)
        held = self.watch((DROP, "01"), lambda album: album is not None and album["state"] == "applying")
        self.assertTrue(held["busy"])
        self.assertNotIn("discard", held["actions"])
        self.assertEqual(self.list_drops()[DROP]["actions"], [])

        for path in (f"/api/drops/{DROP}/albums/01/discard", f"/api/drops/{DROP}/discard"):
            with self.subTest(path=path):
                status, body = self.request("POST", path, {})
                self.assertEqual(status, 409, body)
                self.assertIsInstance(body.get("error"), str)
        for n in ("01", "02"):
            self.assertTrue((self.inbox / DROP / n).is_dir(), n)
            self.assertTrue(self.job(n).is_dir(), n)

        # The refusals stopped nothing: the apply goes on and lands.
        (self.control / "hold").unlink()
        self.watch((DROP, "01"), lambda album: album is None)
        self.assertTrue(any(self.library.rglob("01. One.mp3")))

    def test_discarding_an_album_deletes_its_folder_and_job_and_the_last_one_takes_the_drop(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)

        status, body = self.request("POST", f"/api/drops/{DROP}/albums/01/discard", {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"state": "discarded"})
        self.assertFalse((self.inbox / DROP / "01").exists())
        self.assertFalse(self.job("01").exists())
        self.assertTrue((self.inbox / DROP / "02" / "drop" / "album" / "Other Album").is_dir())
        self.assertTrue((self.job("02") / "plan.json").is_file())
        self.assertEqual([a["n"] for a in self.list_drops()[DROP]["albums"]], ["02"])

        status, body = self.request("POST", f"/api/drops/{DROP}/albums/02/discard", {})
        self.assertEqual(status, 200, body)
        self.assertFalse(self.job("02").exists())
        self.assertFalse((self.inbox / DROP).exists())
        self.assertNotIn(DROP, self.list_drops())
        self.assertEqual(self.calls(), [])
        self.assert_library_empty()

    def test_discarding_a_drop_deletes_every_album_and_job_and_leaves_other_drops(self) -> None:
        self.stage("01", "Clean Album", CLEAN, accept=True)
        self.stage("02", "Other Album", OTHER, accept=False)
        self.stage("01", "Bare Album", BARE, accept=False, drop=OTHER_DROP)

        status, body = self.request("POST", f"/api/drops/{DROP}/discard", {})
        self.assertEqual(status, 200, body)
        self.assertFalse((self.inbox / DROP).exists())
        self.assertFalse(self.job("01").exists())
        self.assertFalse(self.job("02").exists())

        self.assertEqual(sorted(self.list_drops()), [OTHER_DROP])
        self.assertTrue((self.inbox / OTHER_DROP / "01" / "drop" / "album" / "Bare Album").is_dir())
        self.assertTrue((self.job("01", OTHER_DROP) / "plan.json").is_file())
        self.assertEqual(self.calls(), [])
        self.assert_library_empty()


if __name__ == "__main__":
    unittest.main()
