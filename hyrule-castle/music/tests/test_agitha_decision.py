"""The owner's decision on an album: written as the engine reads it, then identified again.

`POST /api/drops/<drop>/albums/<n>/decision` takes a
`Decision` (`agitha/ui/src/shared/api/types.ts`), writes the job's
`decisions.json` keyed by the preview's `source`, and queues identify. The new
preview shows the owner's edits, repoint or soundtrack choice. When identify
refuses the file, the album goes back to `ready` with identify's message and
its earlier preview. The view derives whether Approve is on: it is for an
accept the engine planned clean, and off naming why otherwise. The plan must
also be the one made from the current `decisions.json`, so a refused decision
leaves Approve off and the server refuses an approve. An accept's `strays`,
the owner's name or deletion for each file outside the album's rules, is
refused with a sentence naming the path and the reason where a name breaks
the library's naming rules or is taken, or the path is not one of the album's strays.

Each case has one album staged the way agitha stages it and identified once
by `tests/agitha_stub.py` (the real engine over a fake MusicBrainz), so the
preview the server starts from is one the engine wrote. The server's
`musiclib` is a wrapper that records each call and waits while the test holds
it, so `identifying` and `busy` can be seen without sleeping.
"""

from __future__ import annotations

import hashlib
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
from pathlib import Path, PurePosixPath

from mutagen.id3 import ID3, TXXX

from agitha.server import Config, make_server
from musiclib import strays
from musiclib.batch import decisions as engine_decisions
from musiclib.batch.job import Job
from tests import builders

TESTS = Path(__file__).resolve().parent
STUB = TESTS / "agitha_stub.py"
CATALOGUE = json.loads((TESTS / "fixtures" / "agitha" / "catalogue.json").read_text(encoding="utf-8"))
# Not resolved: the venv's python is a symlink, and following it loses the venv's mutagen.
PYTHON = os.path.abspath(sys.executable)

#: Two releases of the stub's catalogue: the one the files are tagged with, and another to repoint to.
CLEAN_ID = CATALOGUE[0][0]["id"]
BARE_ID = CATALOGUE[1][0]["id"]
ARTIST = CATALOGUE[0][0]["artist-credit"][0]["name"]
ALBUM = CATALOGUE[0][0]["title"]
TITLES = ["One", "Two", "Three"]

DROP = "20260929-210000"
JOB = f"agitha-{DROP}-01"
BUSY_STATES = ("queued", "identifying")
SECONDS = 15

WRAPPER = """\
#!{python}
# musiclib for one test: records the call, waits while `hold` exists, runs the stub.
import json, subprocess, sys, time
from pathlib import Path

control = Path({control!r})
with open(control / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
deadline = time.monotonic() + 30
while (control / "hold").exists():
    if time.monotonic() > deadline:
        print("agitha test: held for 30 s", file=sys.stderr)
        sys.exit(3)
    time.sleep(0.01)
sys.exit(subprocess.run([{python!r}, {stub!r}, *sys.argv[1:]]).returncode)
"""


def stage_album(inbox: Path, n: str, name: str, state: str) -> Path:
    """`inbox/<DROP>/<n>/drop/album/<name>/` and its `album.json`, as agitha leaves an album after staging."""
    drop = inbox / DROP
    drop.mkdir(exist_ok=True)
    (drop / "drop.json").write_text(json.dumps({
        "started": "2026-09-29T21:00:00", "done": True,
        "items": [{"name": name, "kind": "folder", "files": []}],
    }), encoding="utf-8")
    folder = drop / n / "drop" / "album" / name
    folder.mkdir(parents=True)
    (drop / n / "album.json").write_text(json.dumps(
        {"n": n, "name": name, "item": name, "state": state, "stderr": "", "error": None}), encoding="utf-8")
    return folder


def build_tracks(folder: Path) -> None:
    """Three MP3s tagged with the clean release's id, the second with a `TXXX:MOOD` for the owner to remove."""
    for n, title in enumerate(TITLES, start=1):
        path = folder / f"{n:02d} {title.lower()}.mp3"
        shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
        fields = {"title": [title.lower()], "artist": [ARTIST], "album": [ALBUM], "date": ["1989"],
                  "release id": [CLEAN_ID]}
        builders.write_tags(path, builders.picard_tags("mp3", fields, track=(n, len(TITLES)), disc=(1, 1)),
                            v2_version=4)
        if n == 2:
            tags = ID3(path)
            tags.add(TXXX(encoding=3, desc="MOOD", text=["calm"]))
            tags.save(path)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", folder / "cover.jpg")


class AlbumCase(unittest.TestCase):
    """One identified album `01` of drop `DROP`, served over HTTP."""

    #: Files beside the tracks and `cover.jpg`, by path under the album folder, laid before the first identify.
    files: dict[str, bytes] = {}

    def setUp(self) -> None:
        # Resolved, so the paths the server passes on compare equal to these.
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        folders = {name: self.root / name for name in ("inbox", "jobs", "library", "extras", "static", "control")}
        for folder in folders.values():
            folder.mkdir()
        (folders["static"] / "index.html").write_text("<!doctype html><title>agitha</title>\n")
        self.inbox, self.jobs, self.control = folders["inbox"], folders["jobs"], folders["control"]

        self.album_folder = stage_album(self.inbox, "01", ALBUM, "ready")
        build_tracks(self.album_folder)
        for rel, data in self.files.items():
            (self.album_folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.album_folder / rel).write_bytes(data)
        self.job = self.jobs / JOB
        first = subprocess.run([PYTHON, str(STUB), "batch", "identify", str(self.inbox / DROP / "01"),
                                "--job", str(self.job)], capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, f"the stub's first identify failed:\n{first.stderr}")
        self.plan_bytes = (self.job / "plan.json").read_bytes()
        self.entry = json.loads(self.plan_bytes)["albums"][0]
        self.source = self.entry["source"]

        wrapper = self.control / "musiclib"
        wrapper.write_text(WRAPPER.format(python=PYTHON, control=str(self.control), stub=str(STUB)))
        wrapper.chmod(0o755)
        config = Config(inbox=self.inbox, jobs=self.jobs, library=folders["library"], extras=folders["extras"],
                        musiclib=str(wrapper), static=folders["static"], port=0, host="127.0.0.1")
        self.server = make_server(config)
        self.port = self.server.server_address[1]
        # A short poll, so shutdown does not wait half a second per case.
        thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        # Runs first: no process is left held, or writing into the folders while they go.
        self.addCleanup(self._settle)
        self.seen: list[str] = []

    def _settle(self) -> None:
        self.release()
        deadline = time.monotonic() + SECONDS
        while time.monotonic() < deadline:
            status, _type, raw = self.request("GET", "/api/drops")
            if status != 200 or not any(a["busy"] for d in json.loads(raw) for a in d["albums"]):
                return
            time.sleep(0.05)

    def hold(self) -> None:
        (self.control / "hold").touch()

    def release(self) -> None:
        (self.control / "hold").unlink(missing_ok=True)

    def calls(self) -> list[list[str]]:
        log = self.control / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def identify_argv(self, n: str = "01") -> list[str]:
        # `stage_album` writes the drop as started at 2026-09-29T21:00:00, local.
        return ["batch", "identify", str(self.inbox / DROP / n), "--job", str(self.jobs / f"agitha-{DROP}-{n}"),
                "--drop-unreadable", "--added", "2026-09-29T21:00"]

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, str, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.headers.get("Content-Type", ""), response.read()
        finally:
            connection.close()

    def post_decision(self, decision, n: str = "01") -> tuple[int, dict]:
        body = decision if isinstance(decision, bytes) else json.dumps(decision).encode()
        status, _type, raw = self.request("POST", f"/api/drops/{DROP}/albums/{n}/decision", body,
                                          {"Content-Type": "application/json"})
        return status, (json.loads(raw) if raw else {})

    def view(self, n: str = "01") -> dict:
        status, _type, raw = self.request("GET", f"/api/drops/{DROP}/albums/{n}")
        self.assertEqual(status, 200, raw[:300])
        return json.loads(raw)

    def summary(self, n: str = "01") -> dict:
        status, _type, raw = self.request("GET", "/api/drops")
        self.assertEqual(status, 200, raw[:300])
        found = [a for d in json.loads(raw) if d["id"] == DROP for a in d["albums"] if a["n"] == n]
        self.assertEqual(len(found), 1, found)
        return found[0]

    def watch(self, until) -> dict:
        """Polls `GET /api/drops` until `until(album)`, recording in `seen` each state album 01 showed."""
        deadline = time.monotonic() + SECONDS
        while True:
            album = self.summary()
            if not self.seen or self.seen[-1] != album["state"]:
                self.seen.append(album["state"])
            if until(album):
                return album
            if time.monotonic() > deadline:
                self.fail(f"gave up waiting; states seen: {self.seen}")
            time.sleep(0.03)

    def finish(self) -> dict:
        """Waits for the identify a decision queued to end; answers the album's view."""
        self.release()
        self.watch(lambda album: album["state"] not in BUSY_STATES and not album["busy"])
        return self.view()

    def written(self) -> dict | None:
        path = self.job / "decisions.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def after(self, preview: dict, position: str) -> dict[str, list[str]]:
        return next(f["after"] for f in preview["files"] if f["position"] == position)

    def before(self, preview: dict, position: str) -> dict[str, list[str]]:
        return next(f["before"] for f in preview["files"] if f["position"] == position)


#: A neutral edit on one track, a raw frame with two values, and a `null` that removes a frame the file has.
EDITS = {
    "1-1": {"title": ["Uno"]},
    "1-2": {"TCOM": ["Ann Composer", "Bob Composer"], "TXXX:MOOD": None},
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def accept(release_id: str = CLEAN_ID, edits: dict | None = None, game: str | None = "neither", **more) -> dict:
    return {"action": "accept", "release_id": release_id, "edits": EDITS if edits is None else edits, "game": game,
            **more}


class Accepting(AlbumCase):
    """An accept with edits and the soundtrack choice reaches the engine and comes back."""

    def test_an_accept_is_written_keyed_by_the_previews_source_and_identify_runs_again(self) -> None:
        self.assertEqual(self.entry["release_id"], CLEAN_ID)
        decision = accept()
        self.hold()
        status, body = self.post_decision(decision)
        self.assertEqual(status, 202, body)
        self.assertEqual(body, {"state": "queued"})
        self.assertEqual(self.written(), {"job": JOB, "albums": {self.source: decision}})

        # The worker may take it before the first poll, but the gate keeps it
        # identifying until released.
        album = self.watch(lambda album: album["state"] == "identifying")
        self.assertTrue(album["busy"])
        self.release()
        self.watch(lambda album: album["state"] == "ready" and not album["busy"])
        self.assertIn(self.seen, (["queued", "identifying", "ready"], ["identifying", "ready"]))
        self.assertEqual(self.calls(), [self.identify_argv()])

    def test_the_new_preview_carries_every_edit_and_the_choice_and_approve_is_on(self) -> None:
        # Without these the removal and the edits below would prove nothing.
        self.assertEqual(self.before(self.entry, "1-2").get("TXXX:MOOD"), ["calm"])
        self.assertEqual(self.after(self.entry, "1-2").get("TXXX:MOOD"), ["calm"])
        self.assertEqual(self.after(self.entry, "1-1")["TIT2"], ["One"])
        self.assertNotIn("TCOM", self.after(self.entry, "1-2"))

        decision = accept()
        status, body = self.post_decision(decision)
        self.assertEqual(status, 202, body)
        view = self.finish()

        self.assertEqual(view["state"], "ready")
        self.assertIsNone(view["error"])
        self.assertEqual(view["decision"], decision)
        preview = view["preview"]
        self.assertEqual(preview["decision"], "accept")
        self.assertEqual(preview["owner_edits"], EDITS)
        self.assertEqual(preview["game"], "neither")
        self.assertEqual(self.after(preview, "1-1")["TIT2"], ["Uno"])
        self.assertEqual(self.after(preview, "1-2")["TCOM"], ["Ann Composer", "Bob Composer"])
        self.assertNotIn("TXXX:MOOD", self.after(preview, "1-2"))
        # The title edit was for one track.
        self.assertEqual(self.after(preview, "1-2")["TIT2"], ["Two"])
        self.assertEqual(self.after(preview, "1-3")["TIT2"], ["Three"])
        self.assertEqual(view["approvable"], {"ok": True, "reason": None, "code": None, "hold": None})

    def test_an_accept_the_engine_holds_on_decision_leaves_approve_off_naming_the_hold(self) -> None:
        # The other release has no genre, so the plan has a problem the
        # owner's accept cannot clear, and the engine holds it on `decision`.
        # `game: null` means no choice was made and must be taken.
        status, body = self.post_decision(accept(BARE_ID, edits={}, game=None))
        self.assertEqual(status, 202, body)
        view = self.finish()

        self.assertEqual(view["preview"]["release_id"], BARE_ID)
        self.assertIn("decision", [hold["kind"] for hold in view["preview"]["holds"]])
        approvable = view["approvable"]
        self.assertIs(approvable["ok"], False)
        self.assertEqual(approvable["code"], "held")
        self.assertEqual(approvable["hold"]["kind"], "decision")
        self.assertTrue(approvable["reason"].startswith("held: decision"), approvable)


class Repointing(AlbumCase):
    """A pasted release is written as a repoint and the new preview is of it."""

    def test_a_repoint_is_written_and_the_new_preview_is_of_the_pasted_release(self) -> None:
        decision = {"action": "repoint", "release": f"https://musicbrainz.org/release/{BARE_ID}"}
        status, body = self.post_decision(decision)
        self.assertEqual(status, 202, body)
        self.assertEqual(self.written(), {"job": JOB, "albums": {self.source: decision}})
        view = self.finish()

        self.assertEqual(view["state"], "ready")
        self.assertEqual(view["decision"], decision)
        self.assertEqual(view["preview"]["decision"], "repoint")
        self.assertEqual(view["preview"]["release_id"], BARE_ID)
        # A repoint is not an accept, whatever its holds.
        self.assertEqual(view["approvable"], {"ok": False, "reason": "the preview has not been accepted yet",
                                              "code": "not-accepted", "hold": None})
        self.assertEqual(self.calls(), [self.identify_argv()])


STALE = "the preview does not match the last decision; update the preview first"


class Refused(AlbumCase):
    """A decision identify refuses shows identify's message over the earlier preview."""

    def test_a_decision_the_engine_refuses_returns_the_album_to_ready_with_its_message_and_the_earlier_preview(
            self) -> None:
        # The shape is right, so the server passes it on; the engine refuses
        # the key by name.
        decision = accept(edits={"1-2": {"XYZZ": ["x"]}})
        status, body = self.post_decision(decision)
        self.assertEqual(status, 202, body)
        view = self.finish()

        self.assertEqual(self.calls(), [self.identify_argv()])
        # The engine's own words for this file, whatever wording it uses.
        with self.assertRaises(engine_decisions.DecisionsRejected) as refused:
            engine_decisions.read(Job(self.job))
        self.assertIn("XYZZ", str(refused.exception))

        self.assertEqual(view["state"], "ready")
        self.assertIsInstance(view["error"], str)
        self.assertIn(str(refused.exception), view["error"])
        self.assertEqual(self.summary()["error"], view["error"])
        self.assertEqual(view["preview"], self.entry)
        self.assertEqual((self.job / "plan.json").read_bytes(), self.plan_bytes)

    def test_a_refused_decision_after_an_accept_keeps_the_accepted_preview_and_turns_approve_off(self) -> None:
        status, body = self.post_decision(accept(edits={}, game=None))
        self.assertEqual(status, 202, body)
        accepted = self.finish()
        # Only the accepted preview may be approved; the rest is about losing that.
        self.assertIs(accepted["approvable"]["ok"], True, accepted["approvable"])
        plan_bytes = (self.job / "plan.json").read_bytes()

        status, body = self.post_decision(accept(edits={"1-2": {"XYZZ": ["x"]}}))
        self.assertEqual(status, 202, body)
        view = self.finish()
        self.assertEqual(self.calls(), [self.identify_argv(), self.identify_argv()])
        self.assertEqual(view["state"], "ready")
        self.assertIn("XYZZ", view["error"])
        self.assertEqual(view["preview"], accepted["preview"])
        self.assertEqual((self.job / "plan.json").read_bytes(), plan_bytes)

        # The plan was made from the accept and `decisions.json` now holds the
        # refused decision, so apply would refuse the album as changed.
        self.assertEqual(view["approvable"], {"ok": False, "reason": STALE, "code": "not-accepted", "hold": None})
        status, _type, raw = self.request("POST", f"/api/drops/{DROP}/albums/01/approve", b"{}",
                                          {"Content-Type": "application/json"})
        self.assertEqual(status, 409, raw[:300])
        self.assertIsInstance(json.loads(raw).get("error"), str)
        album = self.summary()
        self.assertEqual((album["state"], album["busy"]), ("ready", False))
        self.assertEqual([argv[1] for argv in self.calls()], ["identify", "identify"])


class BadShape(AlbumCase):
    """A decision of the wrong shape is refused before anything is written or run."""

    def test_a_decision_of_the_wrong_shape_is_400_naming_the_field_and_writes_and_runs_nothing(self) -> None:
        # `plan.json` is in the job, so a cover check that only asks whether
        # the file exists lets it through.
        cases = [
            ("skip is not offered", {"action": "skip"}, "action"),
            ("no action", {"release_id": CLEAN_ID, "edits": {}, "game": None}, "action"),
            ("accept without release_id", {"action": "accept", "edits": {}, "game": None}, "release_id"),
            ("unknown game choice", accept(edits={}, game="maybe"), "game"),
            ("cover not uploaded", accept(edits={}, cover="owner/cover.png"), "cover"),
            ("cover outside owner/", accept(edits={}, cover="plan.json"), "cover"),
            ("position the preview lacks", accept(edits={"9-9": {"title": ["x"]}}), "edits"),
            ("edits not an object", accept(edits=["title"]), "edits"),
            ("repoint without release", {"action": "repoint"}, "release"),
        ]
        cases += [(name, raw, None) for name, raw in (("not JSON", b"{accept"), ("not an object", b"[]"))]
        for name, decision, field in cases:
            with self.subTest(name):
                try:
                    status, body = self.post_decision(decision)
                    self.assertEqual(status, 400, body)
                    self.assertIsInstance(body.get("error"), str)
                    if field is not None:
                        self.assertIn(field, body["error"])
                    self.assertIsNone(self.written())
                    self.assertEqual(self.calls(), [])
                finally:
                    # A case let through must not leave the album busy for the next one.
                    self.finish()
                    (self.job / "decisions.json").unlink(missing_ok=True)
                    (self.control / "calls.jsonl").unlink(missing_ok=True)

        album = self.summary()
        self.assertEqual(album["state"], "ready")
        self.assertIs(album["busy"], False)


class Conflicts(AlbumCase):
    """409 while busy or before there is a preview, 404 for an album that is not there."""

    def test_a_second_decision_while_the_first_is_identified_is_409_and_the_first_stands(self) -> None:
        first = accept(edits={}, game=None)
        self.hold()
        status, body = self.post_decision(first)
        self.assertEqual(status, 202, body)
        status, body = self.post_decision({"action": "repoint", "release": BARE_ID})
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertEqual(self.written(), {"job": JOB, "albums": {self.source: first}})

        view = self.finish()
        self.assertEqual(view["preview"]["release_id"], CLEAN_ID)
        self.assertEqual(self.calls(), [self.identify_argv()])

    def test_a_decision_for_an_album_with_no_preview_is_409(self) -> None:
        folder = stage_album(self.inbox, "02", "Unplanned Album", "identify failed")
        shutil.copyfile(builders.FIXTURES / "tone.mp3", folder / "01 x.mp3")
        status, body = self.post_decision(accept(edits={}), n="02")
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertFalse((self.jobs / f"agitha-{DROP}-02" / "decisions.json").exists())
        self.assertEqual(self.calls(), [])

    def test_a_decision_for_an_unknown_album_or_drop_is_404(self) -> None:
        # The same body goes to the album that exists, so a 404 here is about
        # the album and not a missing route.
        skip = json.dumps({"action": "skip"}).encode()
        for path, want in ((f"/api/drops/{DROP}/albums/01/decision", 400),
                           (f"/api/drops/{DROP}/albums/09/decision", 404),
                           ("/api/drops/20000101-000000/albums/01/decision", 404)):
            with self.subTest(path=path):
                status, content_type, raw = self.request("POST", path, skip, {"Content-Type": "application/json"})
                self.assertEqual(status, want, raw[:300])
                self.assertEqual(content_type, "application/json; charset=utf-8")
                self.assertIsInstance(json.loads(raw).get("error"), str)
        self.assertEqual(self.calls(), [])


#: Strays under `COVERS/`: two images with no guess, a PDF and a text file agitha keeps under their own
#: names. Beside them at the root, a `back.jpg` and a `notes.txt` that are not strays and that the plan keeps.
STRAY_FILES = {
    "COVERS/Bowie00001.jpg": builders.jpeg(600, 600),
    "COVERS/Bowie00002.jpg": builders.jpeg(500, 500),
    "COVERS/liner notes.pdf": b"%PDF-1.4 liner notes\n",
    "COVERS/notes.txt": b"the rip's notes, in COVERS\n",
    "back.jpg": builders.jpeg(300, 300),
    "notes.txt": b"the rip's notes, at the root\n",
}


class StrayNames(AlbumCase):
    """The owner's names for strays: a 400 naming the path and the reason for each offence, a 202 otherwise."""

    files = STRAY_FILES

    def refused(self, strays: dict) -> str:
        """Posts an accept carrying `strays`; asserts it was refused before anything was written or run."""
        try:
            status, body = self.post_decision(accept(edits={}, game=None, strays=strays))
            self.assertEqual(status, 400, body)
            self.assertIsInstance(body.get("error"), str)
            self.assertIsNone(self.written())
            self.assertEqual(self.calls(), [])
            return body["error"]
        finally:
            # A case let through must not leave the album busy, or its decision behind, for the next one.
            self.finish()
            (self.job / "decisions.json").unlink(missing_ok=True)
            (self.control / "calls.jsonl").unlink(missing_ok=True)

    def test_a_path_that_is_not_a_stray_of_the_album_is_400_naming_the_path(self) -> None:
        cases = [
            ("a track", "01 one.mp3"),
            ("the root cover", "cover.jpg"),
            # A library name at the root is kept where it is, and is not a stray.
            ("a root file the plan keeps", "back.jpg"),
            ("no such file", "COVERS/Bowie00009.jpg"),
            # Reaches a real file that is not a stray.
            ("a path that climbs", "COVERS/../back.jpg"),
        ]
        for name, path in cases:
            with self.subTest(name):
                self.assertIn(path, self.refused({path: None}))

    def test_a_name_strays_name_offence_refuses_is_400_with_its_sentence(self) -> None:
        cases = [
            ("an image name outside the library's", "COVERS/Bowie00001.jpg", "Bowie.jpg"),
            ("an image with another extension", "COVERS/Bowie00001.jpg", "front.png"),
            ("an image named cover", "COVERS/Bowie00001.jpg", "cover.jpg"),
            ("a PDF named cover", "COVERS/liner notes.pdf", "cover.pdf"),
            ("a PDF with another extension", "COVERS/liner notes.pdf", "liner notes.txt"),
            ("a name holding a /", "COVERS/liner notes.pdf", "Scans/liner notes.pdf"),
            ("a name sanitize would change", "COVERS/liner notes.pdf", "liner: notes.pdf"),
        ]
        for name, path, wanted in cases:
            with self.subTest(name):
                offence = strays.name_offence(path, wanted)
                # Without this the case would test nothing about the module's rule.
                self.assertIsNotNone(offence)
                error = self.refused({path: wanted})
                self.assertIn(path, error)
                self.assertIn(offence, error)

    def test_a_name_two_strays_of_the_accept_both_take_is_400_naming_the_name(self) -> None:
        error = self.refused({"COVERS/Bowie00001.jpg": "back-1.jpg", "COVERS/Bowie00002.jpg": "back-1.jpg"})
        self.assertIn("back-1.jpg", error)
        # Which of the two the sentence blames is not decided; it names one of them.
        self.assertTrue("COVERS/Bowie00001.jpg" in error or "COVERS/Bowie00002.jpg" in error, error)

    def test_a_name_a_file_the_plan_keeps_already_has_is_400_naming_the_path_and_the_name(self) -> None:
        cases = [
            ("an image under a kept root image's name", "COVERS/Bowie00001.jpg", "back.jpg"),
            ("a text file under a kept root file's name", "COVERS/notes.txt", "notes.txt"),
        ]
        # Without these the root files could be strays, or not kept, and the case would test the wrong rule.
        kept = {PurePosixPath(rel).relative_to(self.source).as_posix() for rel in self.entry["kept"]}
        self.assertLessEqual({"back.jpg", "notes.txt"}, kept)
        for name, path, wanted in cases:
            with self.subTest(name):
                self.assertIsNone(strays.name_offence(path, wanted))
                error = self.refused({path: wanted})
                self.assertIn(path, error)
                self.assertIn(wanted, error)

    def test_strays_that_are_not_a_map_of_names_are_400_naming_strays(self) -> None:
        for name, given in (("a list", ["COVERS/Bowie00001.jpg"]), ("a number for a name", {"COVERS/Bowie00001.jpg": 1})):
            with self.subTest(name):
                self.assertIn("strays", self.refused(given))

    def assert_taken(self, given: dict) -> None:
        """An accept carrying `given` is answered 202, written as sent, and identified once."""
        decision = accept(edits={}, game=None, strays=given)
        try:
            status, body = self.post_decision(decision)
            self.assertEqual(status, 202, body)
            self.assertEqual(self.written(), {"job": JOB, "albums": {self.source: decision}})
            self.finish()
            self.assertEqual(self.calls(), [self.identify_argv()])
        finally:
            self.finish()
            (self.job / "decisions.json").unlink(missing_ok=True)
            (self.control / "calls.jsonl").unlink(missing_ok=True)

    def test_a_valid_map_of_names_and_deletions_is_202_written_as_sent_and_identify_runs(self) -> None:
        cases = [
            ("names and a deletion", {"COVERS/Bowie00001.jpg": "booklet-01.jpg", "COVERS/Bowie00002.jpg": None,
                                      "COVERS/liner notes.pdf": "Liner Notes (2014).pdf"}),
            ("only deletions", {path: None for path in STRAY_FILES if path.startswith("COVERS/")}),
        ]
        for name, given in cases:
            with self.subTest(name):
                self.assert_taken(given)

    def test_a_stray_given_the_name_agitha_already_keeps_it_under_is_202(self) -> None:
        # Its own name is taken by no other file. A case of its own: any accept before it replans the PDF.
        self.assertIn({"path": "COVERS/liner notes.pdf", "answer": {"keep": "liner notes.pdf"}},
                      [{"path": row["path"], "answer": row["answer"]} for row in self.entry["strays"]])
        self.assert_taken({"COVERS/liner notes.pdf": "liner notes.pdf"})


if __name__ == "__main__":
    unittest.main()
