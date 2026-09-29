"""A whole 2b round, and a second job after it: decisions and edits that meet an album apply already moved.

The owner decides on the page the first identify wrote, while apply has
already moved the auto set. A decision keyed by an album's old path still
reaches that album, found through its `applied` line in `applied.jsonl`. A
key the job never had is still refused whole, and a decision whose album
cannot be found either way stops identify rather than vanishing.

An edit that moves an album folder moves everything in it. The cover and a
booklet go with the tracks, a video goes to extras, and no folder is left
behind. A second job over what the edit wrote proposes nothing, and taking
it at its word deletes nothing.

Every job is built the real way, with `tests.test_batch_apply`'s `Library`:
rips on disk, identify through the fake MusicBrainz, `decisions.json` by
hand, identify again, and apply against a transport that refuses. A second
job is `Library.job` pointed at another directory beside the first.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from pathlib import Path

from musiclib import files, mapping
from tests import builders
from tests.test_batch_apply import new_library
from tests.test_batch_identify import Services, album, release, run_identify

MOVED = "A/Alpha/First [rip]"
HELD = "H/Held/Third [rip]"
RENAMED = "R/Rook/Old Name [rip]"

NEW_TITLE = "Uno"
NEW_ALBUM = "Renamed Record"

VARIOUS = "V/Various Artists/Boss Battles [rip]"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
VGM = "video game music"
NEITHER = "neither"

#: A key no job here ever had: not in any `plan.json`, not in any `applied.jsonl`.
STRANGER = "Z/Nobody/Nothing [rip]"


def tag(field: str) -> str:
    """`field`'s key in a FLAC file, which every rip here is."""
    return mapping.PICARD[field]["vorbis"]


def every_position(field: str, value: str) -> dict:
    """An album-level field changed once on the page, exported into both positions."""
    return {"1-1": {field: [value]}, "1-2": {field: [value]}}


def write_decisions(lib, albums: dict) -> None:
    """`decisions.json` in `lib.job`, as the page exports it for that job."""
    (lib.job / "decisions.json").write_text(
        json.dumps({"job": lib.job.name, "albums": albums}), encoding="utf-8")


def identify(lib, reopen: tuple[str, ...] = ()) -> tuple[int, str, str]:
    return run_identify(lib.root, lib.job, lib.memory, Services(lib.catalogue), reopen)


def add_various_soundtrack(lib) -> str:
    """A Various Artists Soundtrack-type album at VARIOUS, held for the owner's game choice."""
    found, group = release(6, "Various Artists", "Boss Battles", ["One", "Two"])
    group["secondary-types"] = ["Soundtrack"]
    found["release-group"]["secondary-types"] = ["Soundtrack"]
    various = [{"name": "Various Artists", "joinphrase": "",
                "artist": {"id": VARIOUS_ARTISTS, "name": "Various Artists", "sort-name": "Various Artists"}}]
    found["artist-credit"] = various
    for track in found["media"][0]["tracks"]:
        track["artist-credit"] = various
    lib.catalogue.append((found, group))
    album(lib.root, VARIOUS, ["One", "Two"], release_id=found["id"])
    return found["id"]


def accept(release_id: str, edits=None, game: str | None = None) -> dict:
    return {"action": "accept", "release_id": release_id, "edits": {} if edits is None else edits, "game": game}


def second_job(lib) -> Path:
    """Point `lib` at a new job `j2` beside the first, sharing its library and memory."""
    lib.job = lib.base / ".musiclib" / "jobs" / "j2"
    lib.job.mkdir(parents=True)
    return lib.job


def job_files(job: Path) -> dict[str, bytes]:
    """Every file the batch writes in `job`, and its bytes. The engine's cache is left out."""
    return {name: (job / name).read_bytes()
            for name in ("plan.json", "review.html", "applied.jsonl") if (job / name).is_file()}


def snapshot(root: Path) -> dict[str, str | None]:
    """Every path under `root`, with a digest of its bytes (`None` for a folder).

    `builders.tree` with the bytes hashed, so a failure names the paths that
    differ rather than printing every file in the library.
    """
    return {rel: None if data is None else hashlib.sha256(data).hexdigest()[:12]
            for rel, data in builders.tree(root).items()}


def tracks_in(folder: Path) -> dict[str, dict]:
    """Every track in `folder` by file name, with its tags."""
    return {p.name: files.read(p).tags for p in sorted(folder.glob("*.flac"))}


class Round(unittest.TestCase):
    """`plan.md`'s round, once: identify, apply the auto set, decide on the first page, identify, apply.

    MOVED is auto and the first apply moves it. The owner, still reading the
    page from before that apply, retitles its first track, keyed by the path
    the page showed. HELD is `review`, and the owner accepts it as planned.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        lib.add(MOVED, 1)
        lib.add(HELD, 2, exact=False)
        lib.identify()
        page = cls.page = lib.entries()
        if lib.states() != {MOVED: "auto", HELD: "held"}:
            raise AssertionError(f"the fixture did not plan as these cases assume: {lib.states()}")

        code, _out, err = lib.apply()
        cls.moved_to = page[MOVED]["destination"]
        if code != 0 or not (lib.root / cls.moved_to).is_dir() or (lib.root / MOVED).exists():
            raise AssertionError(f"the auto set was not applied as these cases assume: {code} {err}")

        write_decisions(lib, {
            MOVED: {"action": "accept", "release_id": page[MOVED]["release_id"],
                    "edits": {"1-1": {"title": [NEW_TITLE]}}, "game": None},
            HELD: {"action": "accept", "release_id": page[HELD]["release_id"], "edits": {}, "game": None},
        })
        cls.fold = identify(lib)
        cls.applied = lib.apply()

    def test_an_edit_to_an_album_apply_already_moved_is_written_to_where_that_album_now_is(self):
        code, _out, err = self.fold
        self.assertEqual(code, 0, f"identify, folding the decisions in: {err}")
        code, _out, err = self.applied
        self.assertEqual(code, 0, f"apply of the decisions: {err}")
        tracks = tracks_in(self.lib.root / self.moved_to)
        self.assertEqual(sorted(tracks), [f"01. {NEW_TITLE}.flac", "02. Two.flac"])
        self.assertEqual(tracks[f"01. {NEW_TITLE}.flac"][tag("title")], [NEW_TITLE])

    def test_a_held_album_accepted_alongside_that_edit_is_applied(self):
        # The same decisions.json carries both. A file refused over the moved
        # album's key would leave this one unwritten too.
        destination = self.page[HELD]["destination"]
        self.assertNotEqual(destination, HELD, "the fixture plans no move for the held album")
        self.assertEqual(sorted(tracks_in(self.lib.root / destination)), ["01. One.flac", "02. Two.flac"])
        self.assertFalse((self.lib.root / HELD).exists(), f"{HELD} is still in the library")
        self.assertIn((HELD, "applied"), [(line["source"], line["outcome"]) for line in self.lib.log()])


class DecisionsNobodyCanPlace(unittest.TestCase):
    def test_a_key_in_neither_plan_json_nor_applied_jsonl_is_rejected_and_nothing_is_written(self):
        # Following an applied album from its old path widens what a job
        # "has". It must not widen it to anything at all. This case passes
        # before the fix too: it guards the fix from going too far.
        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.add(HELD, 2, exact=False)
        lib.identify()
        page = lib.entries()
        lib.apply()
        write_decisions(lib, {
            MOVED: {"action": "accept", "release_id": page[MOVED]["release_id"], "edits": {}, "game": None},
            HELD: {"action": "accept", "release_id": page[HELD]["release_id"], "edits": {}, "game": None},
            STRANGER: {"action": "skip"},
        })
        library, job = snapshot(lib.root), job_files(lib.job)

        # Refused as a file, not only found missing later: identify would
        # also stop on a key it cannot place, and that alone would let a
        # reader that accepts any key at all pass the lines after this.
        from musiclib.batch import decisions
        from musiclib.batch.job import Job
        with self.assertRaises(decisions.DecisionsRejected) as refused:
            decisions.read(Job(lib.job))
        self.assertIn(STRANGER, str(refused.exception))

        code, _out, err = identify(lib)
        self.assertEqual(code, 1)
        self.assertIn(STRANGER, err)
        self.assertEqual(job_files(lib.job), job)

        code, _out, err = lib.apply()
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(lib.root), library)
        self.assertEqual(job_files(lib.job), job)

    def test_a_decision_whose_album_is_neither_where_the_page_saw_it_nor_in_applied_jsonl_stops_identify(self):
        # The owner renamed the folder by hand after the page was made. The
        # key is in plan.json, so the file reads fine, but no album is there
        # and apply never moved it. Planning on without the decision would
        # drop the owner's answer and say nothing.
        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.add(HELD, 2, exact=False)
        lib.identify()
        page = lib.entries()
        shutil.move(lib.root / HELD, lib.root / "H/Held/Renamed by hand")
        write_decisions(lib, {
            HELD: {"action": "accept", "release_id": page[HELD]["release_id"], "edits": {}, "game": None},
        })
        job = job_files(lib.job)

        code, _out, err = identify(lib)

        self.assertEqual(code, 1, "identify carried on without the owner's decision")
        self.assertIn(HELD, err)
        self.assertEqual(job_files(lib.job), job)


    def test_two_keys_for_the_same_album_are_rejected_naming_both_and_nothing_is_written(self):
        # MOVED's old key reaches the album through applied.jsonl, and its new
        # key names it directly. Taking either one would silently discard the
        # other answer; the owner has to say which.
        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.identify()
        page = lib.entries()
        lib.apply()
        lib.identify()
        moved_to = page[MOVED]["destination"]
        if moved_to not in lib.entries():
            raise AssertionError(f"the second identify does not plan {moved_to}: {sorted(lib.entries())}")
        write_decisions(lib, {MOVED: accept(page[MOVED]["release_id"]), moved_to: {"action": "skip"}})
        library, job = snapshot(lib.root), job_files(lib.job)

        from musiclib.batch import decisions
        from musiclib.batch.job import Job
        with self.assertRaises(decisions.DecisionsRejected) as refused:
            decisions.read(Job(lib.job))
        for key in (MOVED, moved_to):
            self.assertIn(key, str(refused.exception))

        code, _out, err = identify(lib)
        self.assertEqual(code, 1)
        self.assertEqual(job_files(lib.job), job)
        code, _out, err = lib.apply()
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(lib.root), library)
        self.assertEqual(job_files(lib.job), job)

    def test_an_accept_whose_edits_are_not_positions_of_fields_of_lists_is_rejected_not_raised(self):
        # A hand-edited or truncated file. A crash with a Python traceback
        # tells the owner nothing about which album to fix.
        from musiclib.batch import decisions
        from musiclib.batch.job import Job

        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.identify()
        release_id = lib.entries()[MOVED]["release_id"]
        job = job_files(lib.job)
        for label, edits in (("edits is a list", [{"title": ["Uno"]}]),
                             ("a position maps to a string", {"1-1": "Uno"})):
            with self.subTest(label):
                write_decisions(lib, {MOVED: accept(release_id, edits)})
                with self.assertRaises(decisions.DecisionsRejected) as refused:
                    decisions.read(Job(lib.job))
                self.assertIn(MOVED, str(refused.exception))
                code, _out, _err = identify(lib)
                self.assertEqual(code, 1)
                self.assertEqual(job_files(lib.job), job)

    def test_a_decision_that_cannot_be_placed_stops_identify_before_the_cache_is_made(self):
        # Placing decisions is a walk of the folders, and needs no request.
        # Finding out only after identifying every album costs a full run
        # against MusicBrainz, at one request a second, for an exit 1.
        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.add(HELD, 2, exact=False)
        lib.identify()
        page = lib.entries()
        shutil.rmtree(lib.job / "cache")
        shutil.move(lib.root / HELD, lib.root / "H/Held/Renamed by hand")
        write_decisions(lib, {HELD: accept(page[HELD]["release_id"])})
        services = Services(lib.catalogue)

        code, _out, err = run_identify(lib.root, lib.job, lib.memory, services)

        self.assertEqual(code, 1, err)
        self.assertIn(HELD, err)
        self.assertEqual(services.answered, [], "identify asked MusicBrainz before refusing")
        self.assertFalse((lib.job / "cache").exists(), "identify made the cache before refusing")


class GameChoiceChangedAfterAFold(unittest.TestCase):
    """A Various Artists soundtrack accepted as `video game music`, folded, then re-exported as `neither`.

    The page re-exports an accept with the entry's `owner_edits` as its
    edits. The genre the game choice gives is the batch's own doing, so it
    must not be among them, or flipping the radio changes nothing that
    identify writes.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        release_id = add_various_soundtrack(lib)
        lib.identify()
        if lib.entries()[VARIOUS]["game_choice"] is not True:
            raise AssertionError(f"the fixture offers no game choice: {lib.entries()[VARIOUS]}")
        lib.decide({VARIOUS: accept(release_id, {}, VGM)})
        cls.first = lib.entries()[VARIOUS]
        # What the page exports from this entry.
        carried = cls.first.get("owner_edits", cls.first["inputs"]["edits"])
        lib.decide({VARIOUS: accept(release_id, carried, NEITHER)})
        cls.flipped = lib.entries()[VARIOUS]

    def test_the_owner_edits_leave_out_the_genre_the_game_choice_gave(self):
        # Precondition: the first fold did plan the genre.
        for position in ("1-1", "1-2"):
            self.assertEqual(self.first["fields"][position]["genre"][0], VGM, position)
        self.assertIn("owner_edits", self.first)
        self.assertEqual(self.first["owner_edits"], {})

    def test_re_exporting_with_neither_plans_the_album_with_only_musicbrainzs_genres(self):
        # `rock` is the release group's one genre (`tests.test_batch_identify`).
        for position in ("1-1", "1-2"):
            self.assertEqual(self.flipped["fields"][position]["genre"], ["rock"], position)


class CanaryWithAnAcceptLeftForLater(unittest.TestCase):
    def test_limit_1_before_an_accepted_album_exits_0_and_a_later_apply_writes_the_accept(self):
        # `--limit` is the canary in `plan.md`'s round. An accept it did not
        # reach is waiting, not failed, and exit 1 would stop a script that
        # runs the canary and then the rest.
        lib = new_library(self)
        lib.add(MOVED, 1)
        lib.add(HELD, 2, exact=False)
        lib.identify()
        lib.decide({HELD: lib.accept(HELD)})

        code, _out, err = lib.apply(limit=1)

        self.assertEqual(code, 0, err)
        self.assertNotIn(HELD, err)
        self.assertEqual([line["source"] for line in lib.log()], [MOVED])

        code, _out, err = lib.apply()

        self.assertEqual(code, 0, err)
        self.assertEqual([(line["source"], line["outcome"]) for line in lib.log()],
                         [(MOVED, "applied"), (HELD, "applied")])


class AlbumEditThenANewJob(unittest.TestCase):
    """RENAMED, with a cover, a booklet and a video, accepted with an album-title edit and applied.

    Then job `j2` over the library that apply wrote, with the memory that
    apply wrote, planned and applied with no decisions at all.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        source = lib.add(RENAMED, 1)
        (source / "booklet.pdf").write_bytes(b"%PDF-1.4 not really a booklet\n")
        (source / "video.mkv").write_bytes(b"not really a video")
        lib.identify()
        release_id = lib.entries()[RENAMED]["release_id"]
        lib.decide({RENAMED: {"action": "accept", "release_id": release_id,
                              "edits": every_position("album", NEW_ALBUM), "game": None}})
        cls.decided = lib.entries()[RENAMED]
        cls.first = lib.apply()
        cls.written = snapshot(lib.root)
        cls.written_extras = snapshot(lib.extras)

        second_job(lib)
        cls.second_identify = identify(lib)
        cls.again = lib.entries()
        cls.second_apply = lib.apply()
        cls.after = snapshot(lib.root)

    def test_the_cover_booklet_and_video_go_with_the_album_to_its_edited_folder(self):
        code, _out, err = self.first
        self.assertEqual(code, 0, err)
        # Read off the snapshot taken as this apply returned: the second
        # job's apply has run on the same library since.
        destination = self.decided["destination"]
        self.assertTrue(destination.endswith(f") {NEW_ALBUM}"), destination)
        self.assertEqual(sorted(rel.rsplit("/", 1)[1] for rel in self.written
                                if rel.startswith(destination + "/")),
                         ["01. One.flac", "02. Two.flac", "booklet.pdf", "cover.jpg"])
        self.assertIn(f"{destination}/video.mkv", self.written_extras)
        self.assertFalse(any(rel == RENAMED or rel.startswith(RENAMED + "/") for rel in self.written),
                         f"{RENAMED} is still in the library")

    def test_a_new_job_over_what_the_edit_wrote_proposes_no_change(self):
        # The engine alone would plan the MusicBrainz title, and so a move
        # and the cover deleted from the folder it leaves. The remembered
        # edit brings the plan back to this very folder, so nothing moves
        # and nothing may be deleted.
        destination = self.decided["destination"]
        entry = self.again.get(destination)
        self.assertIsNotNone(entry, f"{destination} is not in the new job: {sorted(self.again)}")
        self.assertEqual((entry["state"], entry["changes"], entry["deletions"]), ("unchanged", [], []))

    def test_applying_that_new_job_leaves_the_album_and_its_cover_byte_identical(self):
        code, _out, err = self.second_apply
        self.assertEqual(code, 0, err)
        cover = f"{self.decided['destination']}/cover.jpg"
        self.assertIn(cover, self.after, "the cover is gone")
        self.assertEqual(self.after, self.written)


class ReopenedAlbumRenamedInPlace(unittest.TestCase):
    """RENAMED, applied as auto. Then job `j2` reopens it where it now is, and the owner renames the album.

    A video lands in the applied folder between the two jobs, so the second
    job has an extra to move as well as a booklet to keep.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        source = lib.add(RENAMED, 1)
        (source / "booklet.pdf").write_bytes(b"%PDF-1.4 not really a booklet\n")
        lib.identify()
        cls.applied_at = lib.entries()[RENAMED]["destination"]
        code, _out, err = lib.apply()
        if code != 0 or not (lib.root / cls.applied_at / "cover.jpg").is_file():
            raise AssertionError(f"the first apply did not write the album as assumed: {code} {err}")
        (lib.root / cls.applied_at / "video.mkv").write_bytes(b"not really a video")

        second_job(lib)
        identify(lib, reopen=(cls.applied_at,))
        entry = lib.entries()[cls.applied_at]
        if (entry["state"], entry["holds"]) != ("held", [{"kind": "reopened", "detail": ""}]):
            raise AssertionError(f"the reopened album is not held only as reopened: {entry}")
        write_decisions(lib, {cls.applied_at: {"action": "accept", "release_id": entry["release_id"],
                                               "edits": every_position("album", NEW_ALBUM), "game": None}})
        cls.fold = identify(lib)
        cls.decided = lib.entries()[cls.applied_at]
        cls.second = lib.apply()

    def test_no_folder_is_left_where_the_album_was(self):
        # The album starts at its planned folder, so the engine sorted the
        # old cover as one to keep in place. Once the edit moves the album,
        # that cover is left alone in a folder nothing else is in.
        code, _out, err = self.second
        self.assertEqual(code, 0, err)
        old = self.lib.root / self.applied_at
        left = sorted(p.name for p in old.iterdir()) if old.is_dir() else []
        self.assertFalse(old.exists(), f"left behind: {left}")

    def test_the_tracks_cover_and_booklet_are_in_the_renamed_folder_and_the_video_is_in_extras(self):
        destination = self.decided["destination"]
        self.assertEqual(destination, self.applied_at.replace("Old Name", NEW_ALBUM))
        folder = self.lib.root / destination
        self.assertEqual(sorted(p.name for p in folder.iterdir()) if folder.is_dir() else [],
                         ["01. One.flac", "02. Two.flac", "booklet.pdf", "cover.jpg"])
        for name, tags in tracks_in(folder).items():
            self.assertEqual(tags[tag("album")], [NEW_ALBUM], name)
        self.assertTrue((self.lib.extras / destination / "video.mkv").is_file(),
                        f"video.mkv is not under extras at {destination}")


if __name__ == "__main__":
    unittest.main()
