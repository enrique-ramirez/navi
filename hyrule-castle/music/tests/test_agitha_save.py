"""agitha's editor, saved: `POST /api/library/save` writes a draft into the library, as a job that says how it went.

The server runs on a thread over temporary folders and is spoken to over
HTTP. A save changes the library, so every case has its own folders and its
own server, over `builders.library`. A draft is built as the page builds one,
by `tests.test_agitha_editor`'s `draft` and `edit`.

A save is a job on the server's queue. A case posts the draft and polls the
job until it reads `done` or `failed`, then looks at the disk. The states in
between are checked only for their order: a save of three small files can be
over before the first poll.

The save runs in this process, so the failures are injected where
`tests.test_agitha_duplicates` injects them: `os.rename`, `os.replace` and
`shutil.rmtree` are replaced for the length of one save (`Swap`). A write
that does not verify, and a library file that changes during a save, come
through `musiclib.tagwrite.write`. An error the swap does not expect comes
through `agitha.drops.file_sha256`, which the verify hashes with.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote

from mutagen.flac import FLAC
from mutagen.id3 import ID3

from agitha import drops
from agitha.server import Config, make_server
from musiclib import files, tagwrite
from tests import builders
from tests import test_agitha_editor as editor_tests
from tests import test_agitha_library as shelf_tests

edit = editor_tests.edit
neighbour = shelf_tests.neighbour

SAVE = "/api/library/save"
CONTRACT = builders.FIXTURES / "agitha" / "library" / "job.json"

STALE = "the album changed since this page loaded"
BEING_SAVED = "the album is being saved"
RACED = "the library's copy changed while saving; save again"
#: What a draft naming a path that leaves its album is answered, with a 404.
NO_SUCH_FILE = "No such file."

#: The order a job's states come in. `failed` may follow any of the first three.
ORDER = ("waiting", "writing", "verifying", "done", "failed")
#: Seconds a job has to settle.
DEADLINE = 30

SONATA = "S/Sonata Arctica"
#: Where `ecliptica` lands once its album artist is `The Band`.
BANDED = "B/Band, The/(1999) Ecliptica"
#: On MusicBrainz's list, and on no track of the fixture.
NEW_GENRES = ["symphonic metal", "folk metal"]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def held(path: Path) -> dict[str, Any]:
    """What one track file holds: its tags, its embedded pictures and the hash of its audio.

    The audio hash is `musiclib.files.audio_fingerprint`, the one
    `tagwrite.write` compares before and after a write. Pictures are given
    by a digest, so a failure prints a line and not an image.
    """
    tags = {key: digest(value) if isinstance(value, bytes) else value
            for key, value in builders.read_tags(path).items()}
    if path.suffix == ".flac":
        # A Vorbis name has no case, and a rewritten one may come back in another.
        tags = {key.lower(): value for key, value in tags.items()}
        pictures = [(int(picture.type), picture.mime, digest(picture.data)) for picture in FLAC(path).pictures]
    else:
        pictures = [(int(frame.type), frame.mime, digest(frame.data)) for frame in ID3(path).getall("APIC")]
    return {"tags": tags, "pictures": pictures, "audio": files.audio_fingerprint(files.read(str(path)))}


@contextlib.contextmanager
def no_way_out() -> Iterator[list[str]]:
    """Every request to another machine raises while this runs. Yields what was asked for.

    Two doors are shut: `urllib.request.urlopen`, which `musiclib.mb`'s
    transport goes through, and the name lookup of any host but this one. The
    cases reach their own server on 127.0.0.1, which stays open.
    """
    def refuse(request: Any, *args: Any, **kwargs: Any) -> Any:
        asked.append(str(getattr(request, "full_url", request)))
        raise OSError("a test refused the request")

    with editor_tests.nobody_else_asked() as asked, mock.patch.object(urllib.request, "urlopen", refuse):
        yield asked


class Swap:
    """`os.rename`, `os.replace` and `shutil.rmtree` for the length of one save, broken at one step.

    The steps are the five of `agitha.duplicates.replace`, told apart by what
    is renamed to where and never by who calls:

    1. the record: `os.replace` onto a `replaced.json` under the jobs folder
    2. the set-aside: `os.rename` of the album's library folder
    3. the rename in: `os.rename` from under the jobs folder onto the album's new library folder
    4. the verify: one byte of `spoil` is flipped the moment step 3 has landed
    5. the delete: the first `shutil.rmtree` under the jobs folder after step 3 has landed

    A step from 1 to 5 fails as the disk would fail it: a `PermissionError`,
    once. `rmtree` asked to `ignore_errors` deletes nothing and says nothing,
    as the real one does when it cannot delete. `stops before 3`, `stops
    after 3` and `stops in 5` end the thread that runs the save with
    `SystemExit`, which no `except Exception` catches: the nearest a test
    comes to agitha dying there. `stops in 5` deletes one track of what step
    5 was asked to delete first, as a delete cut short would have. `watches`
    breaks nothing and says in `landed` when step 3 is over.

    A rename from one place under the jobs folder to another is none of the
    steps and goes through, so step 5 is still step 5 after one.
    """

    def __init__(self, case: SaveCase, old: str, step: int | str, *, new: str | None = None,
                 spoil: str | None = None) -> None:
        self.jobs = os.path.realpath(case.config.jobs)
        self.old = os.path.realpath(case.shelf / old)
        self.target = os.path.realpath(case.shelf / (new or old))
        self.step = step
        self.spoil = spoil
        #: What was broken, once it was.
        self.broke: list[str] = []
        #: Whether step 3 has put the new folder in the library.
        self.landed = False
        self.stopped = threading.Event()
        self.worker: threading.Thread | None = None
        self._rename, self._replace, self._rmtree = os.rename, os.replace, shutil.rmtree

    def _in_jobs(self, path: str) -> bool:
        return path.startswith(self.jobs + os.sep)

    def _deny(self, path: Any) -> PermissionError:
        self.broke.append(str(path))
        return PermissionError(13, "Permission denied (injected by the test)", str(path))

    def _stop(self, path: Any) -> SystemExit:
        self.broke.append(str(path))
        self.worker = threading.current_thread()
        self.stopped.set()
        return SystemExit("the test stopped the save here")

    def _move(self, real: Callable[..., Any], src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        source, target = os.path.realpath(src), os.path.realpath(dst)
        lands = self._in_jobs(source) and target == self.target and not self.landed
        if not self.broke:
            if self.step == 1 and self._in_jobs(target) and os.path.basename(target) == "replaced.json":
                raise self._deny(dst)
            if self.step == 2 and source == self.old:
                raise self._deny(src)
            if self.step == 3 and lands:
                raise self._deny(dst)
            if self.step == "stops before 3" and lands:
                raise self._stop(dst)
        result = real(src, dst, *args, **kwargs)
        if lands and not self.broke:
            self.landed = True
            if self.step == 4:
                victim = Path(dst) / (self.spoil or "")
                data = bytearray(victim.read_bytes())
                data[-1] ^= 0xFF
                victim.write_bytes(bytes(data))
                self.broke.append(str(victim))
            if self.step == "stops after 3":
                raise self._stop(dst)
        return result

    def rename(self, src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        return self._move(self._rename, src, dst, *args, **kwargs)

    def replace(self, src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        return self._move(self._replace, src, dst, *args, **kwargs)

    def rmtree(self, path: Any, ignore_errors: bool = False, *args: Any, **kwargs: Any) -> Any:
        fifth = self.landed and not self.broke and self._in_jobs(os.path.realpath(path))
        if self.step == 5 and fifth:
            error = self._deny(path)
            if ignore_errors:
                return None
            raise error
        if self.step == "stops in 5" and fifth:
            tracks = sorted(found for found in Path(path).rglob("*") if found.suffix in (".flac", ".mp3"))
            if tracks:
                tracks[0].unlink()
                raise self._stop(tracks[0])
        return self._rmtree(path, ignore_errors, *args, **kwargs)

    @contextlib.contextmanager
    def patched(self) -> Iterator[None]:
        with mock.patch("os.rename", self.rename), mock.patch("os.replace", self.replace), \
                mock.patch("shutil.rmtree", self.rmtree):
            yield


#: What a case says when its step was never reached, so nothing was broken and the case proved nothing.
NEVER = {
    1: "no `replaced.json` was written under the jobs folder with `os.replace`",
    2: "the library's folder was never set aside with `os.rename`",
    3: "no folder was renamed from the jobs folder into the library with `os.rename`",
    4: "no folder was renamed from the jobs folder into the library with `os.rename`",
    5: "nothing under the jobs folder was deleted with `shutil.rmtree` after the new folder landed",
}


class SaveCase(shelf_tests.LibraryCase):
    """A server per test over its own `builders.library`, at `<tmp>/shelf`, with the helpers to save a draft."""

    library: builders.Library
    config: Config

    # `LibraryCase` builds one server for a class. A save changes the library, so here each test builds its own.
    @classmethod
    def setUpClass(cls) -> None:
        pass

    @classmethod
    def tearDownClass(cls) -> None:
        pass

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.folders = neighbour.make_folders(self.root)
        # A decoy under the name the box uses. No save may touch it.
        (self.folders["library"] / "X" / "Decoy").mkdir(parents=True)
        self.shelf = self.root / "shelf"
        self.library = builders.library(self.shelf)
        self.config = Config(
            inbox=self.folders["inbox"], jobs=self.folders["jobs"], library=self.shelf,
            extras=self.folders["extras"], musiclib=str(neighbour.STUB), static=self.folders["static"],
            port=0, host="127.0.0.1",
        )
        self.start()
        self.addCleanup(self.stop)

    def start(self) -> None:
        self.server = make_server(self.config)
        self.port = self.server.server_address[1]
        # The default poll makes each stop wait half a second, twenty-odd times over.
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    def restart(self) -> None:
        """agitha stopped and started again over the same folders."""
        self.stop()
        self.start()

    draft = editor_tests.EditorCase.draft

    def path(self, name: str) -> str:
        return self.library.albums[name].path

    def tracks(self, name: str) -> tuple[str, ...]:
        return self.library.albums[name].tracks

    def holds(self, album: str, tracks: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        """`held` of each of `tracks` in the album folder at the library-relative `album`."""
        return {track: held(self.shelf / album / track) for track in tracks}

    def lay_extras(self, album: str) -> dict[str, bytes]:
        """Two files under `--extras` at the album's path, one of them in a folder. Returns them by their path there."""
        laid = {"scans/back.png": f"a scan of {album}\n".encode(), "ticket.txt": b"Tavastia, 1999\n"}
        for rel, data in laid.items():
            target = self.folders["extras"] / album / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return laid

    def lay_linked_track(self, album: str, name: str = "04. Elsewhere.flac", *,
                         relative: bool = False, to: Path | None = None) -> tuple[Path, Path]:
        """A track file outside the library and a link to it at `name` in the album at `album`. Returns link and file.

        The file is at `<tmp>/outside/`, which `on_disk` reads too. A
        `relative` link names it from the album's own place in the library
        and from nowhere else: read in a work folder, it names nothing.
        With `to`, the link names that file and none is laid outside.
        """
        outside = to or self.root / "outside" / "Elsewhere.flac"
        if to is None:
            outside.parent.mkdir(exist_ok=True)
            shutil.copyfile(self.shelf / self.path("winterheart") / self.tracks("winterheart")[0], outside)
        link = self.shelf / album / name
        link.symlink_to(os.path.relpath(outside, link.parent) if relative else outside)
        self.assertEqual(os.path.isabs(os.readlink(link)), not relative)
        self.assertEqual(link.read_bytes(), outside.read_bytes(), "the link does not name the file outside")
        return link, outside

    def on_disk(self) -> dict[str, bytes | None]:
        """Every file and folder the server was given but the jobs folder: the library, the extras, what is beside."""
        return {name: data for name, data in builders.tree(self.root).items()
                if name != "jobs" and not name.startswith("jobs/")}

    def differing(self, before: dict[str, bytes | None], after: dict[str, bytes | None]) -> list[str]:
        # Names only: the bytes of a library make a diff nobody reads.
        return sorted(name for name in before.keys() | after.keys() if before.get(name, 0) != after.get(name, 0))

    def assert_as_it_was(self, before: dict[str, bytes | None]) -> None:
        self.assertEqual(self.differing(before, self.on_disk()), [], "these are not as they were")

    def memory_files(self) -> dict[str, bytes | None]:
        """The bytes of each file an engine keeps its memory in, by its name; `None` where the file is not there.

        The stub engine keeps `agitha-memory.json` in the jobs folder and the
        real one `memory.json` beside it, as `tests.test_agitha_matches` reads them.
        """
        paths = (self.config.jobs / "agitha-memory.json", self.config.jobs.parent / "memory.json")
        return {path.name: path.read_bytes() if path.exists() else None for path in paths}

    def copies_in_jobs(self) -> list[str]:
        """The audio files under the jobs folder: what a save's work folder holds while it is there."""
        return sorted(path.relative_to(self.config.jobs).as_posix() for path in self.config.jobs.rglob("*")
                      if path.suffix in (".flac", ".mp3"))

    def post(self, route: str, draft: dict[str, Any]) -> neighbour.Answer:
        """The answer to `draft` posted to `route`. A handler that raised answers nothing, and that fails here."""
        try:
            return editor_tests.post(self.port, route, draft)
        except (http.client.HTTPException, OSError) as error:
            self.fail(f"POST {route} was not answered ({type(error).__name__}): the handler raised")

    def send(self, draft: dict[str, Any]) -> neighbour.Answer:
        return self.post(SAVE, draft)

    def accepted(self, draft: dict[str, Any]) -> str:
        """The job id of a draft the server took."""
        got = self.send(draft)
        self.assertEqual(got.status, 202, f"POST {SAVE} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(got.body)
        self.assertEqual(list(body), ["job"])
        self.assertIsInstance(body["job"], str)
        return body["job"]

    def settle(self, job: str) -> dict[str, Any]:
        """The job's one album once it reads `done` or `failed`, having checked each state on the way."""
        seen: list[str] = []
        deadline = time.monotonic() + DEADLINE
        while True:
            body = self.answer(f"/api/library/jobs/{quote(job, safe='')}")
            self.assertEqual(len(body["albums"]), 1, body)
            album = body["albums"][0]
            self.assertIn(album["state"], ORDER)
            if album["state"] != "failed":
                self.assertIsNone(album["error"], album)
            if seen[-1:] != [album["state"]]:
                seen.append(album["state"])
            if album["state"] in ("done", "failed"):
                break
            if time.monotonic() > deadline:
                self.fail(f"the job did not settle in {DEADLINE} s; it went through {seen}")
            time.sleep(0.02)
        # A state met twice, or one before an earlier one, is not in this order.
        self.assertEqual(seen, sorted(set(seen), key=ORDER.index), "the states came out of order")
        return album

    def land(self, draft: dict[str, Any], lands: str | None = None) -> dict[str, Any]:
        """Saves `draft` and waits for `done`. Checks what every save promises, and returns the job's album.

        Every save: the job names the album's path and where it landed, with
        no error. Nothing outside the album's old and new folders changed, in
        the library, the extras or beside them. The work folder is gone.
        """
        old = draft["tracks"][0]["album"]
        new = lands or old
        before = self.on_disk()
        copies = self.copies_in_jobs()
        job = self.accepted(draft)
        album = self.settle(job)
        self.assertEqual(album, {"path": old, "new_path": new, "state": "done", "error": None})

        own = tuple(f"{top}/{path}" for top in ("shelf", "extras") for path in (old, new))
        # A folder above the old or the new path may come or go with a move. The cases that move say which.
        above = {"/".join(path.split("/")[:depth]) for path in own for depth in range(2, path.count("/") + 1)}
        elsewhere = [name for name in self.differing(before, self.on_disk())
                     if name not in above and not any(name == path or name.startswith(path + "/") for path in own)]
        self.assertEqual(elsewhere, [], "the save changed these, outside its album")
        self.assertFalse((self.config.jobs / "library-edits" / job).exists(), "the work folder is still there")
        # Whether a failed save's work folder is cleared is not this check's: only what this save left counts.
        self.assertEqual([name for name in self.copies_in_jobs() if name not in copies], [],
                         "the jobs folder still holds this save's copy of the album")
        return album

    def clean_run(self, album: str, *edits: dict[str, Any], lands: str | None = None,
                  extras: bool = False) -> dict[str, bytes | None]:
        """`on_disk` of a twin of this case's folders, as laid, after a save of `edits` over `album` with no fault.

        `lands` is where the save moves the album, as `saved` takes it. With
        `extras` the twin has `lay_extras(album)` too, as this case must.
        """
        twin = SaveCase("setUp")
        twin.setUp()
        try:
            if extras:
                twin.lay_extras(album)
            self.assertEqual(self.differing(twin.on_disk(), self.on_disk()), [], "the twin is not laid as this case is")
            twin.saved(album, *edits, lands=lands)
            return twin.on_disk()
        finally:
            twin.doCleanups()

    @contextlib.contextmanager
    def held_mid_write(self, draft: dict[str, Any]) -> Iterator[str]:
        """Sends `draft` and holds its save inside its first `tagwrite.write`. Yields the job id; lets go on leaving."""
        real = tagwrite.write
        entered, release = threading.Event(), threading.Event()

        def write(track: files.Track, *args: Any, **kwargs: Any) -> files.Track:
            entered.set()
            release.wait(DEADLINE)
            return real(track, *args, **kwargs)

        with mock.patch.object(tagwrite, "write", write):
            job = self.accepted(draft)
            try:
                self.assertTrue(entered.wait(DEADLINE), "the save never wrote with `tagwrite.write`")
                yield job
            finally:
                release.set()

    def job_of(self, album: str) -> Any:
        """The `job` the album's page is answered with."""
        return self.answer(shelf_tests.address(album))["job"]

    def saved(self, album: str, *edits: dict[str, Any], lands: str | None = None) -> dict[str, Any]:
        """`land` of a draft of `edits` over `album`, built from what the album's page shows now."""
        return self.land(self.draft(album, *edits), lands)

    def failed(self, job: str) -> str:
        """The reason of a job that failed."""
        album = self.settle(job)
        self.assertEqual(album["state"], "failed", album)
        self.assertIsInstance(album["error"], str)
        self.assertNotEqual(album["error"].strip(), "", "a failed job gave no reason")
        return album["error"]

    def refused(self, draft: dict[str, Any]) -> str:
        """The sentence of a 409 to `draft`, having checked that nothing changed and no copy was taken."""
        before = self.on_disk()
        got = self.send(draft)
        self.assertEqual(got.status, 409, f"POST {SAVE} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(got.body)
        self.assertEqual(list(body), ["error"])
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])
        return body["error"]


class WritesWhatTheDraftNames(SaveCase):
    def test_a_save_changes_the_tags_the_draft_names_and_nothing_else_in_the_library(self) -> None:
        path = self.path("ecliptica")
        first, middle, last = self.tracks("ecliptica")
        before = self.holds(path, (first, middle, last))
        others = {name: data for name, data in builders.tree(self.shelf / path).items()
                  if name not in (first, middle, last)}
        # What the save must keep is there to be kept.
        self.assertEqual(before[first]["tags"]["rating"], ["4"])
        self.assertEqual(before[first]["tags"]["added"], ["2026-09-02T18:30"])
        self.assertEqual(len(before[first]["pictures"]), 1)
        self.assertEqual(before[middle]["tags"]["genre"], ["power metal", "heavy metal"])

        with no_way_out() as asked:
            self.saved(path, edit((first, last), set={"Genre": NEW_GENRES}),
                       edit((middle,), remove={"Genre": ["power metal"]}, add={"Composer": ["Tony Kakko"]}))

        expected = {track: {**was, "tags": dict(was["tags"])} for track, was in before.items()}
        expected[first]["tags"]["genre"] = NEW_GENRES
        expected[last]["tags"]["genre"] = NEW_GENRES
        expected[middle]["tags"]["genre"] = ["heavy metal"]
        expected[middle]["tags"]["composer"] = ["Tony Kakko"]
        after = self.holds(path, (first, middle, last))
        for track in (first, middle, last):
            with self.subTest(track=track):
                self.assertEqual(after[track], expected[track])
        # The cover, the booklet and the rest of the folder, and no file more or fewer.
        self.assertEqual({name: data for name, data in builders.tree(self.shelf / path).items()
                          if name not in (first, middle, last)}, others)
        self.assertEqual(asked, [])

    def test_a_track_the_draft_does_not_name_is_the_same_bytes_after_the_save(self) -> None:
        path = self.path("ecliptica")
        first, middle, last = self.tracks("ecliptica")
        before = {track: (self.shelf / path / track).read_bytes() for track in (first, last)}
        self.saved(path, edit((middle,), set={"Composer": ["Tony Kakko"]}))
        self.assertEqual(held(self.shelf / path / middle)["tags"]["composer"], ["Tony Kakko"])
        for track, data in before.items():
            self.assertEqual((self.shelf / path / track).read_bytes(), data, track)

    def test_one_readable_name_is_written_under_the_flacs_key_and_under_the_mp3s(self) -> None:
        path = self.path("discovery")
        flac, mp3, other = self.tracks("discovery")
        self.assertEqual(Path(mp3).suffix, ".mp3")
        before = self.holds(path, (flac, mp3, other))
        self.saved(path, edit(set={"Genre": NEW_GENRES, "Composer": ["Thomas Bangalter"]}))
        after = self.holds(path, (flac, mp3, other))
        for track, keys in ((flac, ("genre", "composer")), (mp3, ("TCON", "TCOM")), (other, ("genre", "composer"))):
            with self.subTest(track=track):
                expected = {**before[track], "tags": {**before[track]["tags"], keys[0]: NEW_GENRES,
                                                      keys[1]: ["Thomas Bangalter"]}}
                self.assertEqual(after[track], expected)

    def test_an_album_with_no_musicbrainz_ids_is_saved_and_no_other_machine_is_asked(self) -> None:
        path = self.path("fullmoon")
        rated, plain = self.tracks("fullmoon")
        before = self.holds(path, (rated, plain))
        # No id and no `ADDED` on either track, and a rating on the first.
        self.assertEqual([key for track in before.values() for key in track["tags"]
                          if "MusicBrainz" in key or "ADDED" in key or key.startswith("UFID")], [])
        self.assertIn("POPM:no@email", before[rated]["tags"])

        with no_way_out() as asked:
            self.saved(path, edit(set={"Composer": ["Tony Kakko"]}))

        after = self.holds(path, (rated, plain))
        for track in (rated, plain):
            with self.subTest(track=track):
                # The composer and nothing more: no id was looked up and no `ADDED` was stamped.
                self.assertEqual(after[track], {**before[track],
                                                "tags": {**before[track]["tags"], "TCOM": ["Tony Kakko"]}})
        self.assertEqual(asked, [])

    def test_memory_json_is_the_same_bytes_after_a_save_with_a_release_id_and_one_without(self) -> None:
        # Both files an engine remembers in: the stub's, in the jobs folder, and the real one's, beside it.
        nothing = {"agitha-memory.json": None, "memory.json": None}
        self.assertEqual(self.memory_files(), nothing)
        self.saved(self.path("silence"), edit(set={"Genre": NEW_GENRES}))
        self.assertEqual(self.memory_files(), nothing, "a save made a memory file where there was none")

        # Each file in its engine's own shape, with something remembered for the release `ecliptica` carries.
        release = self.library.albums["ecliptica"].release_id
        self.assertIsNotNone(release)
        self.assertIsNone(self.library.albums["fullmoon"].release_id)
        (self.config.jobs / "agitha-memory.json").write_text(
            json.dumps({"edits": {release: {"1-2": {"title": ["My Land (remembered)"]}}}}), encoding="utf-8")
        (self.config.jobs.parent / "memory.json").write_text(
            json.dumps({"version": 1, "releases": {release: {"edits": []}}}) + "\n", encoding="utf-8")
        remembered = self.memory_files()
        self.assertNotIn(None, remembered.values())
        for name in ("ecliptica", "fullmoon"):
            with self.subTest(album=name):
                self.saved(self.path(name), edit(set={"Composer": ["Tony Kakko"]}))
                self.assertEqual(self.memory_files(), remembered)

    def test_a_track_that_is_a_link_out_of_the_library_is_still_that_link_after_a_save(self) -> None:
        # The album's page does not show such a file. A copy that followed the link put the file itself in the library.
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        outside = self.root / "outside" / "Elsewhere.flac"
        outside.parent.mkdir()
        shutil.copyfile(self.shelf / self.path("winterheart") / self.tracks("winterheart")[0], outside)
        link = self.shelf / path / "04. Elsewhere.flac"
        link.symlink_to(outside)
        self.assertEqual([track["path"] for track in self.answer(shelf_tests.address(path))["tracks"]], list(tracks))
        was = outside.read_bytes()

        self.saved(path, edit(set={"Genre": NEW_GENRES}))

        self.assertEqual([held(self.shelf / path / track)["tags"]["genre"] for track in tracks], [NEW_GENRES] * 3)
        self.assertTrue(link.is_symlink(), "a file took the place of the link in the library")
        self.assertEqual(os.readlink(link), str(outside))
        self.assertEqual(outside.read_bytes(), was, "the save wrote through the link")

    def test_a_track_that_is_a_relative_link_out_of_the_library_is_still_that_link_after_a_save(self) -> None:
        # The link above is absolute and names its file from any folder. This one names it from the album's
        # place in the library alone. A save that reads the album through the link sees one more file in the
        # library than in its work folder, and takes the album for changed or the new folder for wrong.
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        link, outside = self.lay_linked_track(path, relative=True)
        named = os.readlink(link)
        self.assertEqual([track["path"] for track in self.answer(shelf_tests.address(path))["tracks"]], list(tracks))
        was = outside.read_bytes()

        self.saved(path, edit(set={"Genre": NEW_GENRES}))

        self.assertEqual([held(self.shelf / path / track)["tags"]["genre"] for track in tracks], [NEW_GENRES] * 3)
        self.assertTrue(link.is_symlink(), "a file took the place of the link in the library")
        self.assertEqual(os.readlink(link), named)
        self.assertEqual(outside.read_bytes(), was, "the save wrote through the link")

    def test_a_draft_that_names_a_link_to_another_albums_track_is_refused_as_no_file_of_the_album_and_writes_nothing(
            self) -> None:
        # A file that is a link is no track of the album, so no page drafts over it. This draft is made by
        # hand: it lists the link and edits it, beside a track the album does hold. The link leads out of
        # the album's folder, and a draft that names such a path is answered as one that names no file.
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        link, theirs = self.lay_linked_track(path, "04. Weballergy.mp3",
                                             to=self.shelf / self.path("silence") / self.tracks("silence")[0])
        page = self.answer(shelf_tests.address(path))
        self.assertEqual([track["path"] for track in page["tracks"]], list(tracks))
        self.assertNotIn(link.name, page["unreadable"])
        draft = self.draft(path, edit((tracks[0],), set={"Composer": ["Tony Kakko"]}))
        # Without the link it is a draft the server plans, so the refusal below is the link's.
        planned = self.post(editor_tests.PREVIEW, draft)
        self.assertEqual(planned.status, 200, planned.body[:300])
        stat = theirs.stat()
        draft["tracks"].append({"album": path, "path": link.name, "seen": {"Composer": None},
                                "loaded": {"size": stat.st_size, "mtime": stat.st_mtime}})
        draft["edits"][0]["tracks"].append({"album": path, "path": link.name})
        before = self.on_disk()

        for route in (editor_tests.PREVIEW, SAVE):
            with self.subTest(route=route):
                got = self.post(route, draft)
                if got.status == 202:
                    # Taken, which is the failure. The save ends before the next look at the disk.
                    self.settle(json.loads(got.body)["job"])
                self.assertEqual((got.status, json.loads(got.body)), (404, {"error": NO_SUCH_FILE}))
        # The other album's file, the link, and every file of the album that holds it.
        self.assert_as_it_was(before)
        self.assertTrue(link.is_symlink(), "a file took the place of the link in the library")
        self.assertEqual(self.copies_in_jobs(), [])
        self.assertIsNone(self.job_of(path), "the album is left busy")

    def test_an_album_that_holds_a_file_no_reader_opens_is_saved_and_that_file_stays_the_same_bytes(self) -> None:
        # `images` holds two tracks and a `.flac` that is not audio. The file has no length before the swap
        # and none after it, which is not a length that changed.
        entry = self.library.albums["images"]
        path, (first, second), (broken,) = entry.path, entry.tracks, entry.unreadable
        self.assertEqual(self.answer(shelf_tests.address(path))["unreadable"], [broken])
        before = self.holds(path, (first, second))
        others = {name: data for name, data in builders.tree(self.shelf / path).items() if name != first}
        self.assertIn(broken, others)

        self.saved(path, edit((first,), set={"Genre": NEW_GENRES}))

        after = self.holds(path, (first, second))
        self.assertEqual(after[first], {**before[first], "tags": {**before[first]["tags"], "genre": NEW_GENRES}})
        self.assertEqual(after[second], before[second])
        # The file nobody reads, the track the draft does not name and the pictures, and no file more or fewer.
        self.assertEqual({name: data for name, data in builders.tree(self.shelf / path).items() if name != first},
                         others)

    def test_the_job_answer_has_the_keys_of_job_json(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        job = self.accepted(self.draft(self.path("ecliptica"), edit(set={"Genre": NEW_GENRES})))
        self.settle(job)
        body = self.answer(f"/api/library/jobs/{quote(job, safe='')}")
        self.assertEqual(sorted(body), sorted(contract))
        self.assertEqual(sorted(body["albums"][0]), sorted(contract["albums"][0]))

    def test_a_job_id_nobody_was_given_is_404(self) -> None:
        got = self.fetch("/api/library/jobs/0123456789abcdef")
        self.assertEqual(got.status, 404, got.body[:300])
        self.assertEqual(list(json.loads(got.body)), ["error"])


class SaysAnAlbumIsBeingSaved(SaveCase):
    def test_the_albums_page_carries_the_job_while_its_save_waits_or_runs_and_none_once_it_is_over(self) -> None:
        running, waiting = self.path("ecliptica"), self.path("silence")
        self.assertIsNone(self.job_of(running))
        behind = self.draft(waiting, edit(set={"Genre": NEW_GENRES}))
        with self.held_mid_write(self.draft(running, edit(set={"Genre": NEW_GENRES}))) as job:
            self.assertEqual(self.job_of(running), {"id": job, "state": "writing"})
            # One worker: a save of another album sent now waits behind the held one.
            queued = self.accepted(behind)
            self.assertEqual(self.job_of(waiting), {"id": queued, "state": "waiting"})
            # An album no save names has none.
            self.assertIsNone(self.job_of(self.path("stones")))
        self.assertEqual(self.settle(job)["state"], "done")
        self.assertIsNone(self.job_of(running))
        self.assertEqual(self.settle(queued)["state"], "done")
        self.assertIsNone(self.job_of(waiting))

    def test_the_job_and_the_albums_page_read_verifying_while_the_new_folder_is_checked_in_the_library(self) -> None:
        # `settle` checks the order of the states it happens to meet. This holds the save at the
        # check of the folder it renamed in (step 4), so the state is met every time.
        path = self.path("ecliptica")
        swap = Swap(self, path, "watches")
        real = drops.file_sha256
        entered, release = threading.Event(), threading.Event()

        def sha256(file: Path, *args: Any, **kwargs: Any) -> str:
            if swap.landed and os.path.realpath(file).startswith(swap.target + os.sep):
                entered.set()
                release.wait(DEADLINE)
            return real(file, *args, **kwargs)

        with swap.patched(), mock.patch.object(drops, "file_sha256", sha256):
            job = self.accepted(self.draft(path, edit(set={"Genre": NEW_GENRES})))
            try:
                self.assertTrue(entered.wait(DEADLINE), "no file of the new folder was hashed with "
                                                        "`agitha.drops.file_sha256` after it was renamed in")
                body = self.answer(f"/api/library/jobs/{quote(job, safe='')}")
                self.assertEqual(body["albums"], [{"path": path, "new_path": path, "state": "verifying",
                                                   "error": None}])
                self.assertEqual(self.job_of(path), {"id": job, "state": "verifying"})
            finally:
                release.set()
            self.assertEqual(self.settle(job)["state"], "done")
        self.assertIsNone(self.job_of(path))

    def test_a_second_save_over_an_album_being_saved_is_refused_and_queues_nothing(self) -> None:
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        with self.held_mid_write(self.draft(path, edit(set={"Genre": NEW_GENRES}))) as job:
            got = self.send(self.draft(path, edit(set={"Composer": ["Tony Kakko"]})))
            self.assertEqual(got.status, 409, got.body[:300])
            self.assertEqual(json.loads(got.body), {"error": BEING_SAVED})
        self.assertEqual(self.settle(job)["state"], "done")
        # A save queued behind the first would be this album's job now, waiting or running.
        self.assertIsNone(self.job_of(path))
        after = self.holds(path, tracks)
        self.assertEqual([after[track]["tags"]["genre"] for track in tracks], [NEW_GENRES] * 3)
        self.assertEqual([track for track in tracks if "composer" in after[track]["tags"]], [])


class LandsAMove(SaveCase):
    def test_a_changed_title_renames_that_file_in_the_library(self) -> None:
        path = self.path("ecliptica")
        first, middle, last = self.tracks("ecliptica")
        names = sorted(builders.tree(self.shelf / path))
        before = held(self.shelf / path / middle)
        self.saved(path, edit((middle,), set={"Title": ["Replica"]}))
        renamed = "02. Replica.flac"
        self.assertEqual(sorted(builders.tree(self.shelf / path)),
                         sorted(renamed if name == middle else name for name in names))
        self.assertEqual(held(self.shelf / path / renamed),
                         {**before, "tags": {**before["tags"], "title": ["Replica"]}})

    def test_a_changed_album_artist_lands_the_album_and_its_extras_under_the_new_artist(self) -> None:
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        before = self.holds(path, tracks)
        folder = builders.tree(self.shelf / path)
        extras = self.lay_extras(path)
        # Another album's extras, which stay where they are: `land` checks that.
        self.lay_extras(self.path("silence"))
        siblings = sorted(entry.path for entry in self.library.under(SONATA) if entry.path != path)
        self.assertEqual(len(siblings), 4)

        self.saved(path, edit(set={"Album artist": ["The Band"]}), lands=BANDED)

        self.assertFalse((self.shelf / path).exists(), "the album is still at its old path")
        # The artist folder still holds four albums, so it stays, with those four and nothing else.
        self.assertEqual(sorted(f"{SONATA}/{child.name}" for child in (self.shelf / SONATA).iterdir()), siblings)
        after = self.holds(BANDED, tracks)
        for track in tracks:
            with self.subTest(track=track):
                self.assertEqual(after[track], {**before[track],
                                                "tags": {**before[track]["tags"], "albumartist": ["The Band"]}})
        self.assertEqual({name: data for name, data in builders.tree(self.shelf / BANDED).items()
                          if name not in tracks},
                         {name: data for name, data in folder.items() if name not in tracks})
        self.assertFalse((self.folders["extras"] / path).exists(), "the extras are still at the old path")
        self.assertEqual({name: data for name, data in builders.tree(self.folders["extras"] / BANDED).items()
                          if data is not None}, extras)

    def test_a_move_that_empties_the_artist_folder_and_the_letter_removes_both(self) -> None:
        path = self.path("lulu")
        self.assertEqual(path, "L/Lou Reed & Metallica/(2011) Lulu")
        self.assertEqual([child.name for child in (self.shelf / "L").iterdir()], ["Lou Reed & Metallica"])
        extras = builders.tree(self.folders["extras"])

        self.saved(path, edit(set={"Album artist": ["Sonata Arctica"]}), lands=f"{SONATA}/(2011) Lulu")

        self.assertTrue((self.shelf / SONATA / "(2011) Lulu" / "01. Brandenburg Gate.flac").is_file())
        self.assertFalse((self.shelf / "L" / "Lou Reed & Metallica").exists(), "the emptied artist folder stays")
        self.assertFalse((self.shelf / "L").exists(), "the emptied letter folder stays")
        # The album had no extras, so the move makes no folder for them.
        self.assertEqual(builders.tree(self.folders["extras"]), extras)


class LogsEachSave(SaveCase):
    def saves(self, logged: Any) -> list[str]:
        return [line for line in logged.output if ":write save " in line or ":write restore " in line]

    def test_a_save_logs_the_album_how_many_tracks_changed_and_the_names_of_the_tags_and_no_value(self) -> None:
        path = self.path("ecliptica")
        first, middle, last = self.tracks("ecliptica")
        with self.assertLogs("agitha.writes") as logged:
            self.saved(path, edit((first, last), set={"Genre": NEW_GENRES}),
                       edit((middle,), add={"Composer": ["Tony Kakko"]}))
        self.assertEqual(self.saves(logged),
                         [f"INFO:agitha.writes:write save {path} tracks=3 tags=Composer,Genre cover=kept"])

    def test_a_save_that_moves_the_album_logs_where_it_landed(self) -> None:
        path = self.path("ecliptica")
        with self.assertLogs("agitha.writes") as logged:
            self.saved(path, edit(set={"Album artist": ["The Band"]}), lands=BANDED)
        self.assertEqual(self.saves(logged),
                         [f"INFO:agitha.writes:write save {path} to={BANDED} tracks=3 tags=Album artist cover=kept"])

    def test_a_save_that_fails_logs_the_album_and_the_reason_the_job_gives(self) -> None:
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        with self.assertLogs("agitha.writes") as logged, Swap(self, path, 3).patched():
            reason = self.failed(self.accepted(draft))
        self.assertEqual(self.saves(logged), [f"WARNING:agitha.writes:write save {path} failed: {reason}"])

    def test_a_start_that_puts_an_album_back_logs_its_path(self) -> None:
        path = self.path("ecliptica")
        swap = Swap(self, path, "stops before 3")
        with swap.patched():
            self.accepted(self.draft(path, edit(set={"Genre": NEW_GENRES})))
            self.assertTrue(swap.stopped.wait(DEADLINE), NEVER[3])
            assert swap.worker is not None
            swap.worker.join(10)
        with self.assertLogs("agitha.writes") as logged:
            self.restart()
        self.assertEqual(self.saves(logged), [f"INFO:agitha.writes:write restore {path}"])


class RefusesADraftItCannotLand(SaveCase):
    def test_a_draft_over_a_track_that_is_gone_is_refused_as_changed_since_the_page_loaded(self) -> None:
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        (self.shelf / path / self.tracks("ecliptica")[1]).unlink()
        self.assertEqual(self.refused(draft), STALE)

    def listing_a_track_no_edit_names(self) -> dict[str, Any]:
        """A draft of new genres on the first track of `ecliptica` that lists the second too, whose file then goes."""
        path = self.path("ecliptica")
        first, middle, _last = self.tracks("ecliptica")
        shown = next(track for track in self.answer(shelf_tests.address(path))["tracks"] if track["path"] == middle)
        draft = self.draft(path, edit((first,), set={"Genre": NEW_GENRES}))
        draft["tracks"].append({"album": path, "path": middle, "loaded": shown["loaded"], "seen": {}})
        (self.shelf / path / middle).unlink()
        return draft

    def test_a_draft_listing_a_track_that_is_gone_and_no_edit_names_is_refused_as_changed(self) -> None:
        self.assertEqual(self.refused(self.listing_a_track_no_edit_names()), STALE)

    def test_a_preview_of_a_draft_listing_a_track_that_is_gone_is_refused_and_writes_nothing(self) -> None:
        draft = self.listing_a_track_no_edit_names()
        before = self.on_disk()
        got = self.post(editor_tests.PREVIEW, draft)
        # Which refusal a preview gives here is open. That it is one, and the client's to act on, is not.
        self.assertTrue(400 <= got.status < 500, f"the preview answered {got.status}: {got.body[:300]!r}")
        self.assert_as_it_was(before)

    def test_a_draft_over_a_tag_that_changed_since_the_page_loaded_is_refused(self) -> None:
        path = self.path("ecliptica")
        middle = self.tracks("ecliptica")[1]
        draft = self.draft(path, edit((middle,), set={"Title": ["Replica"]}))
        self.assertEqual(draft["tracks"][0]["seen"], {"Title": ["My Land"]})
        builders.write_tags(self.shelf / path / middle, {"TITLE": "Another Land"})
        self.assertEqual(self.refused(draft), STALE)

    def test_a_rating_and_a_tag_the_draft_leaves_alone_written_since_the_page_loaded_are_kept(self) -> None:
        path = self.path("ecliptica")
        first, middle, last = self.tracks("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        loaded = {track["path"]: track["loaded"] for track in draft["tracks"]}
        # A player stores a rating in one file and somebody's tagger a composer in another, after the page loaded.
        builders.write_tags(self.shelf / path / middle, {"RATING": "5"})
        builders.write_tags(self.shelf / path / last, {"COMPOSER": "Tony Kakko"})
        for track in (middle, last):
            stat = (self.shelf / path / track).stat()
            self.assertNotEqual({"size": stat.st_size, "mtime": stat.st_mtime}, loaded[track],
                                "the file reads as it did when the page loaded, so nothing is being tested")
        before = self.holds(path, (first, middle, last))

        self.land(draft)

        after = self.holds(path, (first, middle, last))
        self.assertEqual(after[middle]["tags"]["rating"], ["5"])
        self.assertEqual(after[last]["tags"]["composer"], ["Tony Kakko"])
        for track in (first, middle, last):
            with self.subTest(track=track):
                self.assertEqual(after[track], {**before[track], "tags": {**before[track]["tags"],
                                                                          "genre": NEW_GENRES}})

    def test_a_draft_that_would_land_on_another_album_is_refused_naming_its_path(self) -> None:
        draft = self.draft(self.path("ecliptica"), edit(set={"Date": ["2001-06-21"], "Album": ["Silence"]}))
        self.assertEqual(self.refused(draft), f"already in the library: {self.path('silence')}")

    def test_a_draft_that_takes_a_tracks_only_genres_is_refused_naming_the_rule(self) -> None:
        middle = self.tracks("ecliptica")[1]
        draft = self.draft(self.path("ecliptica"), edit((middle,), set={"Genre": None}))
        # The preview calls this rule `no genre` (`tests.test_agitha_editor`). The rest of the sentence is open.
        self.assertIn("no genre", self.refused(draft))


    def test_a_key_with_no_readable_name_over_an_mp3_and_a_flac_is_written_into_neither(self) -> None:
        # `TXXX:MOOD` is an MP3's key. Written into the two FLACs of `discovery` it would become
        # `txxx:mood`. The preview's sentence for it is `tests.test_agitha_editor`'s.
        for key in ("mood", "TXXX:MOOD"):
            with self.subTest(key=key):
                before = self.on_disk()
                got = self.send(self.draft(self.path("discovery"), edit(set={key: ["calm"]})))
                if got.status == 202:
                    # Taken, which is the failure. The save ends before the next look at the disk.
                    self.settle(json.loads(got.body)["job"])
                self.assertEqual(got.status, 409, f"POST {SAVE} answered {got.status}: {got.body[:300]!r}")
                self.assertEqual(list(json.loads(got.body)), ["error"])
                self.assert_as_it_was(before)

    def test_a_draft_that_lists_no_track_is_turned_down_and_the_handler_does_not_die(self) -> None:
        before = self.on_disk()
        for route in (editor_tests.PREVIEW, SAVE):
            for batch in (False, True):
                with self.subTest(route=route, batch=batch):
                    got = self.post(route, {"tracks": [], "edits": [], "swaps": [], "cover": None, "batch": batch})
                    # Malformed from either page: a batch of no tracks has no album to skip or to save.
                    self.assertEqual(got.status, 400, got.body[:300])
                    self.assertEqual(list(json.loads(got.body)), ["error"])
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])


class PutsTheLibraryBackWhenASaveFails(SaveCase):
    def breaks_at(self, step: int) -> None:
        """A save of new genres over `ecliptica`, broken at `step`: the job fails with a reason and nothing moved."""
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        before = self.on_disk()
        swap = Swap(self, path, step, spoil=self.tracks("ecliptica")[0])
        with swap.patched():
            reason = self.failed(self.accepted(draft))
        self.assertNotEqual(swap.broke, [], NEVER[step])
        self.assertNotEqual(reason, RACED)
        self.assert_as_it_was(before)
        # A failed save leaves nothing a later start would mistake for a copy to put back.
        self.restart()
        self.assert_as_it_was(before)

    def test_a_record_that_cannot_be_written_fails_the_save_and_moves_nothing(self) -> None:
        self.breaks_at(1)

    def test_a_library_folder_that_cannot_be_set_aside_fails_the_save_and_stays(self) -> None:
        self.breaks_at(2)

    def test_a_copy_that_cannot_be_renamed_in_fails_the_save_and_the_old_folder_is_put_back(self) -> None:
        self.breaks_at(3)

    def test_a_copy_that_does_not_verify_once_renamed_in_fails_the_save_and_the_old_folder_is_put_back(self) -> None:
        self.breaks_at(4)

    def test_a_set_aside_folder_that_cannot_be_deleted_fails_the_save_and_is_put_back(self) -> None:
        # Left under the jobs folder, the old copy would be put back at the next start over a save that read `done`.
        self.breaks_at(5)

    def test_an_error_the_swap_does_not_expect_with_the_album_set_aside_fails_the_save_and_puts_it_back(self) -> None:
        # Not one of the five steps failing as a disk fails: the hash of the verify raises something nobody catches by
        # name. The library's only copy of the album is in the work folder then, and must not go with it.
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        before = self.on_disk()
        swap = Swap(self, path, "watches")
        real = drops.file_sha256
        raised: list[str] = []

        def sha256(file: Path, *args: Any, **kwargs: Any) -> str:
            if swap.landed and not raised and os.path.realpath(file).startswith(swap.target + os.sep):
                raised.append(str(file))
                raise RuntimeError("the hash broke (injected by the test)")
            return real(file, *args, **kwargs)

        with swap.patched(), mock.patch.object(drops, "file_sha256", sha256):
            self.failed(self.accepted(draft))
        self.assertNotEqual(raised, [], "no file of the new folder was hashed with `agitha.drops.file_sha256` "
                                        "after it was renamed into the library")
        self.assert_as_it_was(before)
        self.restart()
        self.assert_as_it_was(before)

    def test_a_move_that_does_not_verify_leaves_no_folder_at_the_new_path_and_the_extras_where_they_were(self) -> None:
        path = self.path("ecliptica")
        self.lay_extras(path)
        draft = self.draft(path, edit(set={"Album artist": ["The Band"]}))
        before = self.on_disk()
        self.assertNotIn("shelf/B/Band, The", before)
        swap = Swap(self, path, 4, new=BANDED, spoil=self.tracks("ecliptica")[0])
        with swap.patched():
            self.failed(self.accepted(draft))
        self.assertNotEqual(swap.broke, [], NEVER[4])
        # `B` held albums before and still does. `B/Band, The` was made for this album and goes with it.
        self.assert_as_it_was(before)

    def test_a_write_that_does_not_verify_fails_the_save_and_the_same_draft_saves_afterwards(self) -> None:
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        before = self.on_disk()
        real = tagwrite.write
        written: list[str] = []

        def write(track: files.Track, *args: Any, **kwargs: Any) -> files.Track:
            written.append(Path(track.path).name)
            if len(written) == 2:
                raise tagwrite.VerifyError(f"{track.path}: write did not verify (injected by the test)")
            return real(track, *args, **kwargs)

        with mock.patch.object(tagwrite, "write", write):
            self.failed(self.accepted(draft))
        self.assertEqual(len(written), 2, "the save did not stop at the write that failed")
        self.assert_as_it_was(before)
        self.assertIsNone(self.job_of(path), "the album's page still carries the failed job")

        # The draft is still on the page, and the album is not left busy: Save again, and it lands.
        self.land(draft)
        self.assertEqual([held(self.shelf / path / track)["tags"]["genre"] for track in tracks], [NEW_GENRES] * 3)

    def test_a_library_file_changed_while_the_copy_is_written_fails_the_save_and_is_left_as_changed(self) -> None:
        path = self.path("ecliptica")
        first, middle, _last = self.tracks("ecliptica")
        draft = self.draft(path, edit((first,), set={"Genre": NEW_GENRES}))
        real = tagwrite.write
        written: list[str] = []
        changed: dict[str, bytes | None] = {}

        def write(track: files.Track, *args: Any, **kwargs: Any) -> files.Track:
            written.append(os.path.realpath(track.path))
            if len(written) == 1:
                # A player stores a rating in the library's file, on a track the draft does not name.
                builders.write_tags(self.shelf / path / middle, {"RATING": "5"})
                changed.update(self.on_disk())
            return real(track, *args, **kwargs)

        with mock.patch.object(tagwrite, "write", write):
            reason = self.failed(self.accepted(draft))
        self.assertNotEqual(written, [], "nothing was written with `tagwrite.write`, so nothing changed meanwhile")
        library = os.path.realpath(self.shelf) + os.sep
        self.assertEqual([name for name in written if name.startswith(library)], [],
                         "the save wrote into the library's own files, not into a copy")
        self.assertEqual(reason, RACED)
        self.assert_as_it_was(changed)
        self.assertEqual(held(self.shelf / path / middle)["tags"]["rating"], ["5"])

    def rated_past_the_saves_own_check(self, moment: str) -> None:
        """A save over the first track of `ecliptica`, with a rating stored in its second track at `moment`.

        `hashing`: as the swap hashes the first file of the new copy for its
        record (step 1), which is after the save compared the library's files
        with what it copied. `setting aside`: as the swap asks `os.rename` to
        set the library's folder aside (step 2), with the folder still in
        place. The job fails as `RACED` both times, and the library holds the
        album with the rating, as it was once the rating was written.
        """
        path = self.path("ecliptica")
        first, middle, _last = self.tracks("ecliptica")
        draft = self.draft(path, edit((first,), set={"Genre": NEW_GENRES}))
        jobs = os.path.realpath(self.config.jobs) + os.sep
        album = os.path.realpath(self.shelf / path)
        hash_file, rename = drops.file_sha256, os.rename
        changed: dict[str, bytes | None] = {}

        def rate() -> None:
            # A player stores a rating in the library's file, on a track the draft does not name.
            builders.write_tags(self.shelf / path / middle, {"RATING": "5"})
            changed.update(self.on_disk())

        def sha256(file: Path, *args: Any, **kwargs: Any) -> str:
            # Only with the album still in the library: hashed after step 2, there is no file there to rate.
            if (moment == "hashing" and not changed and os.path.realpath(file).startswith(jobs)
                    and (self.shelf / path / middle).is_file()):
                rate()
            return hash_file(file, *args, **kwargs)

        def set_aside(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            if moment == "setting aside" and not changed and os.path.realpath(src) == album:
                rate()
            return rename(src, dst, *args, **kwargs)

        with mock.patch.object(drops, "file_sha256", sha256), mock.patch("os.rename", set_aside):
            job = self.accepted(draft)
            found = self.settle(job)
        self.assertNotEqual(changed, {}, {
            "hashing": "no file under the jobs folder was hashed with `agitha.drops.file_sha256` while the album "
                       "was in the library",
            "setting aside": NEVER[2],
        }[moment])
        self.assertEqual((found["state"], found["error"]), ("failed", RACED))
        self.assert_as_it_was(changed)
        self.assertEqual(held(self.shelf / path / middle)["tags"]["rating"], ["5"])
        # Nothing is left that a later start would put back over the rated file.
        self.restart()
        self.assert_as_it_was(changed)

    def test_a_library_file_changed_while_the_swap_records_the_new_copy_fails_the_save_and_is_left_as_changed(
            self) -> None:
        self.rated_past_the_saves_own_check("hashing")

    def test_a_library_file_changed_as_the_folder_is_set_aside_fails_the_save_and_is_left_as_changed(self) -> None:
        # The last moment a file can change at its library path: once the folder is set aside there is none.
        self.rated_past_the_saves_own_check("setting aside")


class PutsTheLibraryBackWhenAgithaStarts(SaveCase):
    def stopped(self, draft: dict[str, Any], swap: Swap, never: str = NEVER[3]) -> str:
        """Sends `draft` and waits for `swap` to end the save's thread part-way. Returns the job id."""
        with swap.patched():
            job = self.accepted(draft)
            self.assertTrue(swap.stopped.wait(DEADLINE), never)
            assert swap.worker is not None
            swap.worker.join(10)
        return job

    def test_a_save_that_stopped_with_the_album_set_aside_is_put_back_at_the_next_start(self) -> None:
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": NEW_GENRES}))
        before = self.on_disk()
        self.stopped(draft, Swap(self, path, "stops before 3"))
        self.assertFalse((self.shelf / path).exists(),
                         "the save did not stop with the album set aside, so a start has nothing to put back")

        self.restart()

        self.assert_as_it_was(before)
        # The album is the owner's again: its page answers, and it can be saved.
        self.saved(path, edit(set={"Genre": NEW_GENRES}))

    def test_a_move_that_stopped_after_the_new_folder_landed_is_undone_at_the_next_start(self) -> None:
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Album artist": ["The Band"]}))
        before = self.on_disk()
        self.stopped(draft, Swap(self, path, "stops after 3", new=BANDED))
        self.assertTrue((self.shelf / BANDED).is_dir(),
                        "the save did not stop with the new folder in the library, so a start has nothing to undo")
        self.assertFalse((self.shelf / path).exists())

        self.restart()

        # The old folder is back, the new one is gone, and so is the artist folder made for it.
        self.assert_as_it_was(before)

    def test_a_save_that_stopped_while_deleting_the_set_aside_copy_leaves_a_whole_album_at_the_next_start(self) -> None:
        # The new folder has verified and the old copy has lost a track. Put back, the old copy is not the album.
        path = self.path("ecliptica")
        change = edit(set={"Genre": NEW_GENRES})
        clean = self.clean_run(path, change)
        draft = self.draft(path, change)
        before = self.on_disk()
        self.assertNotEqual(self.differing(before, clean), [], "the save changes nothing, so either end looks the same")
        swap = Swap(self, path, "stops in 5")
        job = self.stopped(draft, swap, NEVER[5])
        self.assertEqual(len(swap.broke), 1)

        self.restart()

        after = self.on_disk()
        as_before, as_saved = self.differing(before, after), self.differing(clean, after)
        self.assertTrue(as_before == [] or as_saved == [],
                        f"the library is neither as it was (it differs in {as_before}) "
                        f"nor as a clean run of the save leaves it (it differs in {as_saved})")
        self.assertFalse((self.config.jobs / "library-edits" / job).exists(), "the work folder is still there")
        self.assertEqual(self.copies_in_jobs(), [], "the jobs folder still holds tracks of the album")
        self.saved(path, edit(set={"Composer": ["Tony Kakko"]}))

    def test_a_move_that_stopped_while_deleting_the_set_aside_copy_is_finished_at_the_next_start(self) -> None:
        # The case above keeps the album at its path. This save moves it, and the album was alone under its
        # artist and its letter: once the new folder is kept, the emptied folders go and the extras follow,
        # as they do after a save nothing stopped.
        path, new = self.path("lulu"), f"{SONATA}/(2011) Lulu"
        self.assertEqual([child.name for child in (self.shelf / "L").iterdir()], ["Lou Reed & Metallica"])
        change = edit(set={"Album artist": ["Sonata Arctica"]})
        self.lay_extras(path)
        clean = self.clean_run(path, change, lands=new, extras=True)
        self.assertNotIn("shelf/L", clean)
        self.assertIn(f"extras/{new}/ticket.txt", clean)
        draft = self.draft(path, change)
        swap = Swap(self, path, "stops in 5", new=new)
        job = self.stopped(draft, swap, NEVER[5])
        self.assertEqual(len(swap.broke), 1)

        self.restart()

        self.assertEqual(self.differing(clean, self.on_disk()), [],
                         "these are not as a save of the same draft that nothing stopped leaves them")
        self.assertFalse((self.config.jobs / "library-edits" / job).exists(), "the work folder is still there")
        self.assertEqual(self.copies_in_jobs(), [], "the jobs folder still holds tracks of the album")
        self.saved(new, edit(set={"Composer": ["Lou Reed"]}))

    def test_a_start_that_cannot_delete_the_old_copy_of_a_finished_move_leaves_the_next_start_to_finish_it(
            self) -> None:
        # The case above, with a first start whose every delete under the jobs folder is refused. What says
        # where the album came from must outlast that start: the next one has the emptied folders and the
        # extras to see to, and nothing else on disk names the old path.
        path, new = self.path("lulu"), f"{SONATA}/(2011) Lulu"
        change = edit(set={"Album artist": ["Sonata Arctica"]})
        self.lay_extras(path)
        clean = self.clean_run(path, change, lands=new, extras=True)
        self.assertNotIn("shelf/L", clean)
        self.assertIn(f"extras/{new}/ticket.txt", clean)
        jobs_before = builders.tree(self.config.jobs)
        swap = Swap(self, path, "stops in 5", new=new)
        job = self.stopped(self.draft(path, change), swap, NEVER[5])
        self.assertEqual(len(swap.broke), 1)

        jobs = os.path.realpath(self.config.jobs) + os.sep
        real = shutil.rmtree
        refused: list[str] = []

        def rmtree(target: Any, ignore_errors: bool = False, *args: Any, **kwargs: Any) -> Any:
            # As `Swap` fails step 5: asked to `ignore_errors`, it deletes nothing and says nothing.
            if (os.path.realpath(target) + os.sep).startswith(jobs):
                refused.append(str(target))
                if ignore_errors:
                    return None
                raise PermissionError(13, "Permission denied (injected by the test)", str(target))
            return real(target, ignore_errors, *args, **kwargs)

        self.stop()
        with mock.patch("shutil.rmtree", rmtree):
            self.start()
        self.assertNotEqual(refused, [], "the first start deleted nothing under the jobs folder with "
                                         "`shutil.rmtree`, so nothing was refused")
        self.assertNotEqual(self.copies_in_jobs(), [], "the old copy is gone though its delete was refused")

        self.restart()

        self.assertEqual(self.differing(clean, self.on_disk()), [],
                         "these are not as a save of the same draft that nothing stopped leaves them")
        self.assertFalse((self.config.jobs / "library-edits" / job).exists(), "the work folder is still there")
        self.assertEqual(sorted(name for name, data in builders.tree(self.config.jobs).items()
                                if data is not None and name not in jobs_before), [],
                         "these files are left under the jobs folder")
