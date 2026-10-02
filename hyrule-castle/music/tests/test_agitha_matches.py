"""agitha's Match to MusicBrainz: a library album copied into the inbox, reviewed as an upload is, and landed over the folder it came from.

The server runs on a thread over temporary folders and is spoken to over
HTTP. A match changes the library, so every case has its own folders and
its own server, over `builders.library`, as `tests.test_agitha_save` has.

The engine is `tests/agitha_stub.py`: the real identify and apply over a fake
MusicBrainz that answers from a catalogue. The fake finds a release only by
the release id the files carry, so `catalogue` holds one release under the id
of each fixture album a case matches, and says there what the plan differs
in: a genre, the artist, the year. `fullmoon` carries no id and is found
nothing.

A match is identified and applied by a process and landed on the queue's
thread. A case posts and then polls the album's review until it settles. The
landing runs in this process, so the one failure injected is an `os.rename`
replaced for the length of one approve, as `tests.test_agitha_duplicates`
does.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any
from unittest import mock

from agitha import drops, duplicates
from tests import builders
from tests import test_agitha_decision as decision_tests
from tests import test_agitha_save as save_tests
from tests.test_agitha_library import address
from tests.test_batch_identify import mbid, release

edit = save_tests.edit

MATCH = "/api/library/match"
OPEN_IN_REVIEW = "the album is open in review"
BEING_SAVED = save_tests.BEING_SAVED
CHANGED = "the library's copy changed since this match began; start over"
TAKEN = "already in the library: "

DROP_ID = re.compile(r"\d{8}-\d{6}(-\d+)?")
BUSY = ("queued", "identifying", "applying")
SETTLED = ("in the library", "written, not moved", "apply failed")
#: Seconds an album has to be identified, or to land.
DEADLINE = 30

# Not resolved: the venv's python is a symlink, and following it loses the venv's mutagen.
PYTHON = os.path.abspath(sys.executable)

WRAPPER = """\
#!{python}
# musiclib for one test: the stub, answering from the test's own catalogue.
import os, subprocess, sys

env = dict(os.environ, AGITHA_STUB_CATALOGUE={catalogue!r})
env.pop("AGITHA_STUB_FAIL", None)
env.pop("AGITHA_STUB_SLEEP", None)
sys.exit(subprocess.run([{python!r}, {stub!r}, *sys.argv[1:]], env=env).returncode)
"""

#: A drop and an album number, as the match route answers them.
Ref = tuple[str, str]

#: What the fake MusicBrainz says of each fixture album a case matches. The
#: number makes its release group and artist ids. A genre here is on no track
#: of the fixture's album, so a landed track that carries it was written from
#: the plan.
RELEASES: dict[str, dict[str, Any]] = {
    # Planned where it is, and in the release group its files carry already: to the search an
    # upload's Approve makes, the folder in the library is this album.
    "ecliptica": dict(number=601, artist="Sonata Arctica", title="Ecliptica", date="1999-11-22",
                      genre="symphonic metal", same_group=True),
    # Another artist, in a letter the library does not have. `L/Lou Reed & Metallica` holds this album alone.
    "lulu": dict(number=602, artist="Metallica", title="Lulu", date="2011-10-31", genre="thrash metal"),
    # Another year, so another folder under the same artist, which holds four more albums.
    "winterheart": dict(number=603, artist="Sonata Arctica", title="Winterheart's Guild", date="2004-03-05",
                        genre="folk metal"),
}
#: Where the plans of `lulu` and `winterheart` land.
MOVED = "M/Metallica/(2011) Lulu"
REDATED = "S/Sonata Arctica/(2004) Winterheart's Guild"

#: The `ADDED` every track of the fixture's `ecliptica` carries.
ECLIPTICA_ADDED = "2026-09-02T18:30"


def catalogue(library: builders.Library) -> list[list[dict[str, Any]]]:
    """The `[release, release group]` pairs of `RELEASES`, each under its fixture album's release id and track titles."""
    pairs = []
    for name, row in RELEASES.items():
        entry = library.albums[name]
        titles = [PurePosixPath(track).stem.split(". ", 1)[1] for track in entry.tracks]
        found, group = release(row["number"], row["artist"], row["title"], titles, genres={row["genre"]: 3})
        found["id"] = entry.release_id
        found["date"] = group["first-release-date"] = found["release-group"]["first-release-date"] = row["date"]
        if row.get("same_group"):
            carried = save_tests.held(entry.folder / entry.tracks[0])["tags"]["musicbrainz_releasegroupid"][0]
            group["id"] = found["release-group"]["id"] = carried
        pairs.append([found, group])
    return pairs


def beside(snapshot: dict[str, bytes | None], *albums: str) -> dict[str, bytes | None]:
    """`snapshot` without the album folders `albums` and the letter and artist folders above them."""
    above = {"/".join(album.split("/")[:depth]) for album in albums for depth in (1, 2)}
    return {name: data for name, data in snapshot.items()
            if name not in above and not any(name == album or name.startswith(album + "/") for album in albums)}


def files_of(snapshot: dict[str, bytes | None]) -> dict[str, bytes]:
    return {name: data for name, data in snapshot.items() if data is not None}


class MatchCase(save_tests.SaveCase):
    """A server per test over its own `builders.library`, its engine answering from `catalogue`."""

    def start(self) -> None:
        # `SaveCase` names the stub itself, which runs under whatever `python3` the PATH has.
        # The wrapper runs it under this interpreter, with this case's catalogue.
        control = self.root / "control"
        if not control.exists():
            control.mkdir()
            (control / "catalogue.json").write_text(json.dumps(catalogue(self.library)), encoding="utf-8")
            wrapper = control / "musiclib"
            wrapper.write_text(WRAPPER.format(python=PYTHON, stub=str(save_tests.neighbour.STUB),
                                              catalogue=str(control / "catalogue.json")))
            wrapper.chmod(0o755)
            self.config = dataclasses.replace(self.config, musiclib=str(wrapper))
        super().start()

    def setUp(self) -> None:
        super().setUp()
        self.inbox = self.folders["inbox"]
        # Runs first: no engine process is left writing while the folders go.
        self.addCleanup(self.idle)

    def idle(self) -> None:
        deadline = time.monotonic() + DEADLINE
        while time.monotonic() < deadline:
            try:
                got = self.fetch("/api/drops")
            except (http.client.HTTPException, OSError):
                return
            if got.status != 200 or not any(album["busy"] for drop in json.loads(got.body)
                                            for album in drop["albums"]):
                return
            time.sleep(0.05)

    def shelved(self) -> dict[str, bytes | None]:
        return builders.tree(self.shelf)

    def assert_shelved(self, before: dict[str, bytes | None]) -> None:
        # Names only: the bytes of a library make a diff nobody reads.
        self.assertEqual(self.differing(before, self.shelved()), [], "these are not as they were in the library")

    def extras(self) -> dict[str, bytes | None]:
        return builders.tree(self.folders["extras"])

    def drops_on_disk(self) -> list[str]:
        return sorted(os.listdir(self.inbox))

    def ask(self, path: Any) -> save_tests.neighbour.Answer:
        return self.post(MATCH, {"path": path})

    def match(self, path: str) -> Ref:
        """The drop and album of a match the server began for the album at `path`."""
        got = self.ask(path)
        self.assertEqual(got.status, 201, f"POST {MATCH} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(got.body)
        self.assertEqual(sorted(body), ["drop", "n"], body)
        return body["drop"], body["n"]

    def review(self, ref: Ref, tail: str = "") -> str:
        return f"/api/drops/{ref[0]}/albums/{ref[1]}{tail}"

    def view(self, ref: Ref) -> dict[str, Any]:
        return self.answer(self.review(ref))

    def listed(self) -> dict[Ref, dict[str, Any]]:
        """Every album of `GET /api/drops`, by its drop and number."""
        return {(drop["id"], album["n"]): album for drop in self.answer("/api/drops") for album in drop["albums"]}

    def page(self, path: str) -> dict[str, Any]:
        """The library album's own page."""
        return self.answer(address(path))

    def until(self, ref: Ref, done: Any, what: str) -> dict[str, Any]:
        """The album's review once `done(view)`. A poll the server could not answer mid-move is asked again."""
        seen: list[str] = []
        last: dict[str, Any] = {}
        deadline = time.monotonic() + DEADLINE
        while True:
            try:
                got = self.fetch(self.review(ref))
                view = json.loads(got.body) if got.status == 200 else None
            except (http.client.HTTPException, OSError):
                view = None
            if view is not None:
                last = view
                if seen[-1:] != [view["state"]]:
                    seen.append(view["state"])
                if done(view):
                    return view
            if time.monotonic() > deadline:
                self.fail(f"the album was not {what} in {DEADLINE} s; it went through {seen}; "
                          f"error: {last.get('error')!r}; stderr: {last.get('stderr')!r}")
            time.sleep(0.03)

    def ready(self, ref: Ref) -> dict[str, Any]:
        """The review once identify is over, which must have left a plan."""
        view = self.until(ref, lambda view: not view["busy"] and view["state"] not in BUSY, "identified")
        self.assertEqual(view["state"], "ready", (view["error"], view["stderr"]))
        self.assertIsNotNone(view["preview"])
        return view

    def accept(self, ref: Ref, edits: dict[str, Any] | None = None) -> dict[str, Any]:
        """The review after the owner accepted the release the plan found, with `edits`."""
        found = self.ready(ref)["preview"]["release_id"]
        got = self.post(self.review(ref, "/decision"), {"action": "accept", "release_id": found, "edits": edits or {}})
        self.assertEqual(got.status, 202, got.body[:300])
        view = self.ready(ref)
        self.assertIsNone(view["error"], view["stderr"])
        self.assertEqual(view["preview"]["decision"], "accept")
        return view

    def matched(self, name: str, lands: str | None = None, edits: dict[str, Any] | None = None) -> Ref:
        """A match of the fixture album `name`, identified and accepted, whose plan lands at `lands` (its own path by default)."""
        ref = self.match(self.path(name))
        view = self.accept(ref, edits)
        # The catalogue decides this. A plan that lands elsewhere is another case than the one a test names.
        self.assertEqual(view["preview"]["destination"], lands or self.path(name))
        return ref

    def approve(self, ref: Ref, body: dict[str, Any] | None = None) -> save_tests.neighbour.Answer:
        return self.post(self.review(ref, "/approve"), body or {})

    def settled(self, ref: Ref) -> dict[str, Any]:
        return self.until(ref, lambda view: not view["busy"] and view["state"] in SETTLED, "settled")

    def landed(self, ref: Ref) -> dict[str, Any]:
        """Approves with an empty body and waits for the album to be in the library."""
        got = self.approve(ref)
        self.assertEqual(got.status, 202, f"Approve answered {got.status}: {got.body[:300]!r}")
        view = self.settled(ref)
        self.assertEqual(view["state"], "in the library", (view["error"], view["stderr"]))
        return view

    def turned_down(self, got: save_tests.neighbour.Answer, status: int = 409) -> str:
        """The sentence of a refusal."""
        self.assertEqual(got.status, status, got.body[:300])
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(got.body)
        self.assertEqual(list(body), ["error"], body)
        return body["error"]

    def discard(self, ref: Ref) -> None:
        got = self.post(self.review(ref, "/discard"), {})
        self.assertEqual(got.status, 200, got.body[:300])

    def remembered(self) -> dict[str, Any]:
        """What the engine's memory holds. The stub keeps it in the jobs folder, the real engine beside it."""
        for path in self.memories():
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def memories(self) -> tuple[Path, Path]:
        return self.config.jobs / "agitha-memory.json", self.config.jobs.parent / "memory.json"


class StartsAMatch(MatchCase):
    def test_a_match_copies_the_album_into_a_new_drop_of_one_album_and_leaves_the_library_as_it_was(self) -> None:
        path = self.path("ecliptica")
        before = self.shelved()
        held = builders.tree(self.shelf / path)
        self.assertEqual(self.drops_on_disk(), [])

        drop, n = self.match(path)

        self.assertRegex(drop, DROP_ID)
        self.assertEqual(n, "01")
        self.assertEqual(self.drops_on_disk(), [drop])
        # Where `albums.stage` puts an upload, so identify and the review find it as they find any album.
        copy = self.inbox / drop / n / "drop" / "album" / PurePosixPath(path).name
        self.assertEqual(builders.tree(copy), held)
        self.assertEqual([ref for ref in self.listed() if ref[0] == drop], [(drop, n)])

        # Identify was queued for it: it comes to rest with the plan of the release its files name.
        view = self.ready((drop, n))
        self.assertEqual(view["preview"]["release_id"], self.library.albums["ecliptica"].release_id)
        self.assertEqual(view["preview"]["destination"], path)
        self.assertIsNone(view["error"])
        # What any identified album offers before the owner accepts its preview.
        listed = self.listed()[(drop, n)]
        self.assertEqual((listed["state"], listed["busy"], listed["actions"]),
                         ("ready", False, ["reidentify", "discard"]))
        self.assert_shelved(before)

    def test_the_drops_list_the_review_and_the_library_each_say_which_folder_the_match_replaces(self) -> None:
        path, sibling = self.path("ecliptica"), self.path("silence")
        # An album that was dropped, in a drop of its own, laid as staging leaves one.
        decision_tests.stage_album(self.inbox, "01", "Some Upload", "identify interrupted")
        uploaded = (decision_tests.DROP, "01")
        self.assertIsNone(self.page(path)["match"])

        ref = self.match(path)
        self.ready(ref)

        listed = self.listed()
        self.assertEqual(listed[ref]["replaces"], path)
        self.assertIn("replaces", listed[uploaded])
        self.assertIsNone(listed[uploaded]["replaces"])
        self.assertEqual(self.view(ref)["replaces"], path)
        self.assertEqual(self.page(path)["match"], {"drop": ref[0], "n": ref[1]})
        self.assertIsNone(self.page(sibling)["match"])
        # The artist's page lists the same albums, so a batch can tell which one is open.
        artist = {album["path"]: album["match"] for album in self.answer(address(save_tests.SONATA))["albums"]}
        self.assertEqual(artist[path], {"drop": ref[0], "n": ref[1]})
        self.assertEqual({found for name, found in artist.items() if name != path}, {None})

    def test_a_match_of_an_album_that_holds_a_link_is_refused_saying_so_and_copies_nothing(self) -> None:
        # The album's page does not show a linked file. Copied as a link, it is in the inbox for apply to
        # write the plan's tags through, into the file it names. Copied as a file, Approve carries into the
        # library what was never in it. So the album is not matched while it holds one.
        linked, nested, covered = self.path("ecliptica"), self.path("fragile"), self.path("winterheart")
        link, outside = self.lay_linked_track(linked)
        # In a disc folder, and relative: a look at the album folder's own entries alone does not find it.
        self.lay_linked_track(nested, "CD2/03. Elsewhere.flac", relative=True)
        cover = self.shelf / covered / "cover.jpg"
        cover.unlink()
        cover.symlink_to(self.shelf / self.path("silence") / "cover.jpg")
        self.assertEqual([track["path"] for track in self.page(linked)["tracks"]], list(self.tracks("ecliptica")))
        before = self.on_disk()

        for what, path in (("a track", linked), ("a track in a disc folder", nested), ("cover.jpg", covered)):
            with self.subTest(link=what):
                self.assertRegex(self.turned_down(self.ask(path)), re.compile("link", re.IGNORECASE))
                self.assertEqual(self.drops_on_disk(), [])
                self.assertIsNone(self.page(path)["match"])
        self.assertEqual(self.answer("/api/drops"), [])
        # The library, the inbox and the file outside, and no copy of an album under the jobs folder.
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])
        self.assertTrue(link.is_symlink())

        # The link was all that was in the way: without it the album is matched as any other.
        link.unlink()
        self.ready(self.match(linked))

    def test_a_path_that_names_no_album_of_the_library_is_404_and_makes_no_drop(self) -> None:
        real = self.library.albums["ecliptica"]
        # A whole album outside the root, and a link to it from inside.
        outside = self.root / "outside" / "(2000) Outside"
        shutil.copytree(real.folder, outside)
        (self.shelf / "S" / "Sonata Arctica" / "(2000) Linked").symlink_to(outside, target_is_directory=True)
        before = self.shelved()

        for path in (
            "S/Sonata Arctica/(1999) Nothing",
            "S/Sonata Arctica",
            "S",
            "",
            str(real.folder),
            f"../shelf/{real.path}",
            "../outside/(2000) Outside",
            "S/Sonata Arctica/..",
            "S/Sonata Arctica/(2000) Linked",
        ):
            with self.subTest(path=path):
                self.turned_down(self.ask(path), 404)
                self.assertEqual(self.drops_on_disk(), [])
        self.assert_shelved(before)
        self.assertEqual(self.answer("/api/drops"), [])
        # The route is there, and takes the one path of these that is an album of the library.
        self.ready(self.match(real.path))


class KeepsOneMatchOpen(MatchCase):
    def test_a_second_match_of_an_album_answers_the_one_already_open_and_copies_nothing(self) -> None:
        path = self.path("ecliptica")
        first = self.match(path)

        # Once while the first may still be queued, once when it is ready.
        for moment in ("at once", "after identify"):
            with self.subTest(moment=moment):
                again = self.ask(path)
                self.assertEqual(again.status, 200, again.body[:300])
                self.assertEqual(json.loads(again.body), {"drop": first[0], "n": first[1]})
                self.assertEqual(self.drops_on_disk(), [first[0]])
                self.assertEqual(list(self.listed()), [first])
            self.ready(first)

        # Another album is another match.
        other = self.match(self.path("winterheart"))
        self.assertNotEqual(other[0], first[0])
        self.ready(other)

    def test_a_match_is_still_open_after_agitha_restarts(self) -> None:
        # What is open is on disk. A server that kept it in memory would copy the album a second time.
        path = self.path("ecliptica")
        first = self.match(path)
        self.ready(first)

        self.restart()

        self.assertEqual(self.page(path)["match"], {"drop": first[0], "n": first[1]})
        again = self.ask(path)
        self.assertEqual(again.status, 200, again.body[:300])
        self.assertEqual(json.loads(again.body), {"drop": first[0], "n": first[1]})
        self.assertEqual(self.drops_on_disk(), [first[0]])

    def test_a_save_over_an_album_with_a_match_open_is_refused_and_writes_nothing(self) -> None:
        path = self.path("ecliptica")
        draft = self.draft(path, edit(set={"Genre": save_tests.NEW_GENRES}))
        ref = self.match(path)
        self.ready(ref)
        before = self.on_disk()

        got = self.send(draft)

        self.assertEqual(self.turned_down(got), OPEN_IN_REVIEW)
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])
        self.assertIsNone(self.job_of(path))

    def test_a_match_of_an_album_being_saved_is_refused_and_makes_no_drop(self) -> None:
        path = self.path("ecliptica")
        with self.held_mid_write(self.draft(path, edit(set={"Genre": save_tests.NEW_GENRES}))) as job:
            got = self.ask(path)
            self.assertEqual(self.turned_down(got), BEING_SAVED)
            self.assertEqual(self.drops_on_disk(), [])
        self.assertEqual(self.settle(job)["state"], "done")
        self.assertIsNone(self.page(path)["match"])
        self.assertEqual(self.drops_on_disk(), [])


class ReviewsAMatch(MatchCase):
    def test_the_review_compares_no_copies_and_approve_asks_for_no_choice_between_them(self) -> None:
        # An upload planned onto a folder the library holds is shown the comparison, and Approve
        # then takes `keep`. A match is planned onto its own folder nearly every time.
        path = self.path("ecliptica")
        ref = self.matched("ecliptica")
        view = self.view(ref)
        searched = duplicates.library_copy(self.config, view["preview"])
        self.assertEqual(searched and os.path.realpath(searched), os.path.realpath(self.shelf / path),
                         "an upload planned like this would be shown no comparison, so the case proves nothing")

        self.assertIsNone(view["duplicate"])
        self.assertEqual(view["replaces"], path)
        self.assertEqual(view["approvable"], {"ok": True, "reason": None, "code": None, "hold": None})
        self.assertEqual(self.listed()[ref]["actions"], ["approve", "reidentify", "discard"])

        got = self.approve(ref, {})
        self.assertEqual(got.status, 202, got.body[:300])
        self.assertEqual(self.settled(ref)["state"], "in the library")

    def test_discard_removes_the_copy_and_its_job_and_leaves_the_library_as_it_was(self) -> None:
        path = self.path("ecliptica")
        before = self.shelved()
        extras = self.extras()
        ref = self.matched("ecliptica")
        job = self.config.jobs / f"agitha-{ref[0]}-{ref[1]}"
        self.assertTrue(job.is_dir(), "the match has no job to remove, so the case proves less than it says")

        self.discard(ref)

        self.assertEqual(self.drops_on_disk(), [])
        self.assertFalse(job.exists())
        self.assertEqual(self.listed(), {})
        self.assert_shelved(before)
        self.assertEqual(self.extras(), extras)
        self.assertIsNone(self.page(path)["match"])

    def test_once_its_match_is_discarded_an_album_can_be_saved_and_matched_again(self) -> None:
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        ref = self.match(path)
        self.ready(ref)
        self.discard(ref)

        self.saved(path, edit(set={"Genre": save_tests.NEW_GENRES}))
        after = self.holds(path, tracks)
        self.assertEqual([after[track]["tags"]["genre"] for track in tracks], [save_tests.NEW_GENRES] * 3)

        self.ready(self.match(path))


class LandsAMatch(MatchCase):
    def test_a_match_planned_onto_its_own_folder_puts_what_the_plan_wrote_there_and_touches_nothing_else(self) -> None:
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        row = RELEASES["ecliptica"]
        was = self.holds(path, tracks)
        self.assertNotIn(row["genre"], was[tracks[0]]["tags"]["genre"])
        before = self.shelved()
        extras = self.extras()
        ref = self.matched("ecliptica")

        view = self.landed(ref)

        self.assertEqual(os.path.realpath(view["library_path"]), os.path.realpath(self.shelf / path))
        now = self.holds(path, tracks)
        self.assertEqual([now[track]["tags"]["genre"] for track in tracks], [[row["genre"]]] * 3)
        self.assertEqual({track: now[track]["audio"] for track in tracks},
                         {track: was[track]["audio"] for track in tracks})
        self.assertEqual(beside(self.shelved(), path), beside(before, path))
        self.assertEqual(self.extras(), extras)
        # Landed: the copy is gone from the inbox and the album is the owner's to edit again.
        self.assertEqual(self.drops_on_disk(), [])
        self.assertIsNone(self.page(path)["match"])

    def test_a_match_planned_under_another_artist_lands_there_and_takes_the_old_folders_and_extras_with_it(self) -> None:
        old, tracks = self.path("lulu"), self.tracks("lulu")
        laid = self.lay_extras(old)
        was = self.holds(old, tracks)
        before = self.shelved()
        ref = self.matched("lulu", MOVED)

        view = self.landed(ref)

        self.assertEqual(os.path.realpath(view["library_path"]), os.path.realpath(self.shelf / MOVED))
        now = self.holds(MOVED, tracks)
        self.assertEqual([now[track]["tags"]["albumartist"] for track in tracks], [["Metallica"]] * 2)
        self.assertEqual({track: now[track]["audio"] for track in tracks},
                         {track: was[track]["audio"] for track in tracks})
        shelf = self.shelved()
        # The album was alone under its artist and its letter, so all three go.
        self.assertEqual([name for name in shelf if name == "L" or name.startswith("L/")], [])
        self.assertEqual(beside(shelf, old, MOVED), beside(before, old, MOVED))
        self.assertEqual(files_of(self.extras()), {f"{MOVED}/{rel}": data for rel, data in laid.items()})
        self.assertFalse((self.folders["extras"] / old).exists())
        self.assertEqual(self.fetch(address(old)).status, 404)
        self.assertIsNone(self.page(MOVED)["match"])

    def test_a_match_replaces_the_folder_it_was_started_from_and_no_other_edition_under_the_planned_artist(self) -> None:
        # An upload's Approve looks under the planned artist folder for the album it would
        # replace. A match was started from one folder, and that is the one that goes.
        old, tracks = self.path("winterheart"), self.tracks("winterheart")
        ref = self.matched("winterheart", REDATED)
        # Another edition, named so that it sorts first, carrying the release group the plan writes.
        demo = builders.library_album(self.shelf, letter="S", artist="Sonata Arctica", album="Winterheart's Guild",
                                      folder="(2002) Winterheart's Guild [Demo]", date="2002-01-01",
                                      discs=(("Gravenimage",),))
        builders.write_tags(demo / "01. Gravenimage.flac",
                            {"MUSICBRAINZ_RELEASEGROUPID": mbid(2, RELEASES["winterheart"]["number"])})
        searched = duplicates.library_copy(self.config, self.view(ref)["preview"])
        self.assertEqual(searched and os.path.realpath(searched), os.path.realpath(demo),
                         "the search would not take the other edition, so the case proves nothing")
        before = self.shelved()

        self.landed(ref)

        shelf = self.shelved()
        self.assertNotIn(old, shelf)
        self.assertEqual(sorted(name[len(REDATED) + 1:] for name in shelf
                                if name.startswith(REDATED + "/") and name.endswith(".flac")), sorted(tracks))
        self.assertEqual([self.holds(REDATED, tracks)[track]["tags"]["genre"] for track in tracks],
                         [[RELEASES["winterheart"]["genre"]]] * 2)
        # The artist folder keeps its other albums, the demo among them, as they were.
        self.assertIn(demo.relative_to(self.shelf).as_posix(), shelf)
        self.assertEqual(beside(shelf, old, REDATED), beside(before, old, REDATED))

    def test_approve_is_refused_where_the_planned_folder_is_another_album_and_nothing_changes(self) -> None:
        ref = self.matched("lulu", MOVED)
        self.lay_extras(self.path("lulu"))
        # An album at the planned path that an upload would be offered to replace: the same release group.
        taken = builders.library_album(self.shelf, letter="M", artist="Metallica", album="Lulu", date="2011-10-31",
                                       discs=(("Brandenburg Gate",),))
        builders.write_tags(taken / "01. Brandenburg Gate.flac",
                            {"MUSICBRAINZ_RELEASEGROUPID": mbid(2, RELEASES["lulu"]["number"])})
        self.assertEqual(taken.relative_to(self.shelf).as_posix(), MOVED)
        before = self.shelved()
        extras = self.extras()

        # `keep` is how an upload replaces a copy. A match replaces the folder it came from and no other.
        for body in ({}, {"keep": "new"}):
            with self.subTest(body=body):
                # The folder as the library names it, as the editor's refusal spells it.
                self.assertEqual(self.turned_down(self.approve(ref, body)), TAKEN + MOVED)
                view = self.view(ref)
                self.assertEqual((view["state"], view["busy"]), ("ready", False))
                self.assert_shelved(before)
                self.assertEqual(self.extras(), extras)

    def test_approve_is_refused_once_a_file_of_the_library_folder_changed_after_the_copy_was_taken(self) -> None:
        def rate(folder: Path) -> None:
            builders.write_tags(folder / "02. My Land.flac", {"RATING": "5"})

        def recover(folder: Path) -> None:
            (folder / "cover.jpg").write_bytes(builders.two_tone(900, 900))

        for name, lands, change in (("ecliptica", None, rate), ("winterheart", REDATED, recover)):
            with self.subTest(album=name, change=change.__name__):
                path = self.path(name)
                ref = self.matched(name, lands)
                change(self.shelf / path)
                before = self.shelved()

                self.assertEqual(self.turned_down(self.approve(ref)), CHANGED)

                view = self.view(ref)
                self.assertEqual((view["state"], view["busy"]), ("ready", False))
                self.assert_shelved(before)
                self.assertEqual(self.page(path)["match"], {"drop": ref[0], "n": ref[1]})

    def rated_past_approves_check(self, moment: str) -> None:
        """A match of `ecliptica` approved, with a rating stored in the library's second track at `moment`.

        Every moment is after Approve was taken. `applying`: as the engine's
        apply ends, before the landing has looked at the library's folder.
        The other two are after the landing compared that folder with the
        record of the copy. `hashing`: as the swap hashes the first track of
        the finished folder for its record (step 1). `setting aside`: as
        the swap asks `os.rename` to set the library's folder aside (step
        2), with the folder still in place.

        The album comes to rest unmoved with `CHANGED`, and the library
        keeps the rated file. The review carries that sentence and no step
        and no file of a swap, as no step went wrong. The album offers
        Discard alone: Move would meet the same changed copy.
        """
        path = self.path("ecliptica")
        rated = self.shelf / path / "02. My Land.flac"
        ref = self.matched("ecliptica")
        finished = os.path.realpath(self.inbox / ref[0] / ref[1] / path) + os.sep
        album = os.path.realpath(self.shelf / path)
        hash_file, rename, engine = drops.file_sha256, os.rename, subprocess.run
        changed: dict[str, bytes | None] = {}

        def rate() -> None:
            builders.write_tags(rated, {"RATING": "5"})
            changed.update(self.shelved())

        def run(command: Any, *args: Any, **kwargs: Any) -> Any:
            done = engine(command, *args, **kwargs)
            if moment == "applying" and not changed and "apply" in command:
                rate()
            return done

        def sha256(file: Path, *args: Any, **kwargs: Any) -> str:
            # A track, since the review hashes the pictures of the inbox to show a cover. And only with
            # the album still in the library: hashed after step 2, there is no file there to rate.
            if (moment == "hashing" and not changed and Path(file).suffix == ".flac"
                    and os.path.realpath(file).startswith(finished) and rated.is_file()):
                rate()
            return hash_file(file, *args, **kwargs)

        def set_aside(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            if moment == "setting aside" and not changed and os.path.realpath(src) == album:
                rate()
            return rename(src, dst, *args, **kwargs)

        with mock.patch.object(drops, "file_sha256", sha256), mock.patch("os.rename", set_aside), \
                mock.patch("subprocess.run", run):
            got = self.approve(ref)
            self.assertEqual(got.status, 202, got.body[:300])
            view = self.settled(ref)

        self.assertNotEqual(changed, {}, {
            "applying": "the engine was never run for `apply` with `subprocess.run`",
            "hashing": "no track of the finished folder was hashed with `agitha.drops.file_sha256` while the "
                       "album was in the library",
            "setting aside": "the library's folder was never set aside with `os.rename`",
        }[moment])
        self.assertEqual((view["state"], view["error"]), ("written, not moved", CHANGED))
        self.assert_shelved(changed)
        self.assertEqual(save_tests.held(rated)["tags"]["rating"], ["5"])
        with self.subTest("what the review says went wrong"):
            self.assertEqual((view["step"], view["file"]), (None, None))
        with self.subTest("what the album offers"):
            self.assertEqual(self.listed()[ref]["actions"], ["discard"])

    def test_a_rating_stored_while_the_engine_applies_stops_the_landing_and_is_kept(self) -> None:
        # Approve saw the library's folder as it was copied. The landing looks again once apply is over.
        self.rated_past_approves_check("applying")

    def test_a_rating_stored_while_the_swap_records_the_finished_folder_stops_the_landing_and_is_kept(self) -> None:
        self.rated_past_approves_check("hashing")

    def test_a_rating_stored_as_the_library_folder_is_set_aside_stops_the_landing_and_is_kept(self) -> None:
        # The last moment a file can change at its library path: once the folder is set aside there is none.
        self.rated_past_approves_check("setting aside")

    def test_a_match_under_another_artist_stopped_while_deleting_the_old_folder_is_finished_by_a_start_and_move(
            self) -> None:
        # The new folder has verified and the old copy has lost a track, so the new folder stays. What follows a
        # landing nothing stopped still has to happen: the emptied folders go and the extras move.
        old, tracks = self.path("lulu"), self.tracks("lulu")
        laid = self.lay_extras(old)
        was = self.holds(old, tracks)
        before = self.shelved()
        ref = self.stopped_while_deleting_the_old_folder()

        self.restart()
        # Move is what the album offers after such a stop. Where a start has finished the landing
        # itself, Move is refused and changes nothing, and the library is judged as the start left it.
        moved = self.post(self.review(ref, "/move"), {})
        self.assertLess(moved.status, 500, moved.body[:300])

        shelf = self.shelved()
        self.assertEqual([name for name in shelf if name == "L" or name.startswith("L/")], [],
                         "the folders the album left empty are still there")
        now = self.holds(MOVED, tracks)
        self.assertEqual([now[track]["tags"]["albumartist"] for track in tracks], [["Metallica"]] * 2)
        self.assertEqual({track: now[track]["audio"] for track in tracks},
                         {track: was[track]["audio"] for track in tracks})
        self.assertEqual(beside(shelf, old, MOVED), beside(before, old, MOVED))
        self.assertEqual(files_of(self.extras()), {f"{MOVED}/{rel}": data for rel, data in laid.items()})
        self.assertFalse((self.folders["extras"] / old).exists())
        self.assertEqual(sorted(found.relative_to(self.inbox).as_posix() for found in self.inbox.rglob("*.flac")), [],
                         "the inbox still holds tracks of the album")
        self.assertIsNone(self.page(MOVED)["match"])

    def stopped_while_deleting_the_old_folder(self) -> Ref:
        """A match of `lulu`, planned at `MOVED`, approved and stopped as its swap deletes the copy set aside.

        The new folder is in the library and has verified, the old copy has
        lost a track, and the thread that landed it is dead. Nothing that
        follows a landing has happened: the old artist and letter folders
        are there, and the extras are at the old path.
        """
        ref = self.matched("lulu", MOVED)
        staged = os.path.realpath(self.inbox / ref[0] / ref[1]) + os.sep
        real = shutil.rmtree
        stopped = threading.Event()
        cut: list[Path] = []
        workers: list[threading.Thread] = []

        def rmtree(path: Any, *args: Any, **kwargs: Any) -> Any:
            # The first delete under the album's inbox folder, with the new folder in the library, of a
            # folder that holds a track: the copy set aside. The thread ends as agitha would die there.
            inside = os.path.realpath(path).startswith(staged) and (self.shelf / MOVED).is_dir()
            held = sorted(Path(path).rglob("*.flac")) if inside and not cut else []
            if held:
                held[0].unlink()
                cut.append(held[0])
                workers.append(threading.current_thread())
                stopped.set()
                raise SystemExit("the test stopped the swap here")
            return real(path, *args, **kwargs)

        with mock.patch("shutil.rmtree", rmtree):
            got = self.approve(ref)
            self.assertEqual(got.status, 202, got.body[:300])
            self.assertTrue(stopped.wait(DEADLINE), "the copy set aside was never deleted with `shutil.rmtree`")
            workers[0].join(10)
        return ref

    def test_a_match_whose_new_folder_is_kept_and_whose_landing_is_unfinished_offers_move_alone_and_refuses_discard(
            self) -> None:
        # Discard deletes the album's inbox folder, and with it all that says a landing is unfinished: the old
        # artist folder would stay in the library for good, and the extras at a path no album has.
        self.lay_extras(self.path("lulu"))
        ref = self.stopped_while_deleting_the_old_folder()
        self.restart()

        with self.subTest("what the album offers"):
            self.assertEqual(self.listed()[ref]["actions"], ["move"])
        # The album's own Discard, and its drop's, which discards the one album the drop holds.
        for what, route in (("the album", self.review(ref, "/discard")), ("its drop", f"/api/drops/{ref[0]}/discard")):
            with self.subTest(discard=what):
                self.assertIn(ref, self.listed(), "the album is gone, so this Discard has nothing to refuse")
                everything = builders.tree(self.root)
                got = self.post(route, {})
                self.assertTrue(400 <= got.status < 500, f"Discard answered {got.status}: {got.body[:300]!r}")
                self.assertEqual(self.differing(everything, builders.tree(self.root)), [],
                                 "the refused Discard changed these")

    def test_a_new_folder_that_does_not_verify_is_taken_out_and_the_old_album_is_as_it_was(self) -> None:
        # The old folder goes only once the new one has verified. Here it does not: a byte of
        # one track changes the moment the folder is in the library.
        old = self.path("lulu")
        self.lay_extras(old)
        before = self.shelved()
        extras = self.extras()
        ref = self.matched("lulu", MOVED)
        target = os.path.realpath(self.shelf / MOVED)
        real = os.rename
        spoiled: list[str] = []

        def rename(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            result = real(src, dst, *args, **kwargs)
            if not spoiled and os.path.realpath(dst) == target:
                victim = sorted(Path(dst).glob("*.flac"))[0]
                data = bytearray(victim.read_bytes())
                data[-1] ^= 0xFF
                victim.write_bytes(bytes(data))
                spoiled.append(str(victim))
            return result

        with mock.patch("os.rename", rename):
            got = self.approve(ref)
            self.assertEqual(got.status, 202, got.body[:300])
            view = self.settled(ref)

        self.assertNotEqual(spoiled, [], "no folder was renamed to the planned path with `os.rename`, "
                                         "so nothing was broken")
        self.assertEqual(view["state"], "written, not moved", view["error"])
        self.assertIsInstance(view["error"], str)
        self.assertNotEqual(view["error"].strip(), "")
        # As it was, to the folder: the letter and artist folders made for the new album are gone too.
        self.assert_shelved(before)
        self.assertEqual(self.extras(), extras)


class KeepsTheAddedTime(MatchCase):
    def test_a_landed_match_keeps_each_tracks_added_time_and_writes_none_where_there_was_none(self) -> None:
        # An upload is stamped with its drop's time. A match is the same album as before.
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        builders.delete_tags(self.shelf / path / tracks[1], ["ADDED"])
        was = [self.holds(path, tracks)[track]["tags"].get("added") for track in tracks]
        self.assertEqual(was, [[ECLIPTICA_ADDED], None, [ECLIPTICA_ADDED]])

        self.landed(self.matched("ecliptica"))

        now = self.holds(path, tracks)
        # The genre shows these are the files the plan wrote, and not the ones nothing touched.
        self.assertEqual(now[tracks[1]]["tags"]["genre"], [RELEASES["ecliptica"]["genre"]])
        self.assertEqual([now[track]["tags"].get("added") for track in tracks], was)


class GoesThroughDecisionsAndMemory(MatchCase):
    def test_an_edit_accepted_on_a_matchs_review_lands_and_is_remembered_for_the_release(self) -> None:
        entry = self.library.albums["ecliptica"]
        edits = {"1-1": {"title": ["Blank File (owner's cut)"]}}
        self.assertEqual(self.remembered(), {})
        ref = self.matched("ecliptica", edits=edits)
        self.assertEqual(self.remembered(), {}, "an edit was remembered before Approve")

        self.landed(ref)

        self.assertEqual(self.remembered().get("edits", {}).get(entry.release_id), edits)
        first = [path for path in sorted((self.shelf / entry.path).glob("01. *.flac"))]
        self.assertEqual(len(first), 1, first)
        self.assertEqual(save_tests.held(first[0])["tags"]["title"], ["Blank File (owner's cut)"])

    def test_an_edit_an_earlier_review_remembered_for_the_release_is_laid_on_the_matchs_plan(self) -> None:
        entry = self.library.albums["ecliptica"]
        memory = {"edits": {entry.release_id: {"1-2": {"title": ["My Land (remembered)"]}}}}
        for path in self.memories():
            path.write_text(json.dumps(memory), encoding="utf-8")

        view = self.ready(self.match(entry.path))

        titles = {planned["position"]: planned["after"]["title"] for planned in view["preview"]["files"]}
        self.assertEqual(titles, {"1-1": ["Blank File"], "1-2": ["My Land (remembered)"],
                                  "1-3": ["8th Commandment"]})

    def test_a_match_that_finds_no_release_offers_discard_only_and_the_album_stays_editable_by_hand(self) -> None:
        # `fullmoon` carries no MusicBrainz id, and the fake's search finds nothing.
        path = self.path("fullmoon")
        before = self.shelved()
        ref = self.match(path)

        view = self.ready(ref)

        self.assertEqual(view["preview"]["status"], "unidentified")
        self.assertIs(view["approvable"]["ok"], False)
        self.assertEqual(self.listed()[ref]["actions"], ["discard"])
        for action in ("reidentify", "approve"):
            with self.subTest(action=action):
                got = self.post(self.review(ref, f"/{action}"), {})
                self.assertTrue(400 <= got.status < 500, f"{action} answered {got.status}: {got.body[:300]!r}")
                listed = self.listed()[ref]
                self.assertEqual((listed["state"], listed["busy"]), ("ready", False))
        self.assert_shelved(before)

        self.discard(ref)
        self.assertIsNone(self.page(path)["match"])
        self.saved(path, edit(set={"Genre": save_tests.NEW_GENRES}))


if __name__ == "__main__":
    import unittest

    unittest.main()
