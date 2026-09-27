"""The memory: what the owner decided once, carried into every later job, and the edits laid over a plan.

Every field edit in an applied decision is kept under its release MBID and
track position, and a later job over the same rips plans it again. A `video
game music` or `not game music` choice is kept
under the album's composer, a single album artist that is not Various
Artists, and reaches 001's engine next time. An album with no composer gets
its choice once, as that album's genre, and never as a composer.

An edit is laid over the plan the engine made. A field the path is built
from (title, album) moves the file or folder with it, because the library's
names follow its tags; any other field changes that tag and nothing else.

One library, planned once for the file, the real way: rips on disk, `batch
identify`, a `decisions.json` written by hand, identify again to fold it in,
`batch apply`, and then a second job, with its own cache, over an untouched
copy of the same rips and the same memory. The fakes and the job layout are
`tests.test_batch_identify`'s and `tests.test_batch_apply`'s. The cases only
read.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from musiclib import files, mapping, tagwrite
from tests.test_batch_apply import Library
from tests.test_batch_identify import Services, album, mbid, no_throttle, release, run_identify

VGM = "video game music"
NOT_GAME = "not game music"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
UNSETTLED = "review: unsettled soundtrack"

# Edited albums: ordinary releases, auto before anyone decides anything.
TITLED = "T/Tern/Shoreline [rip]"
RENAMED = "R/Rook/Old Name [rip]"
REGENRED = "G/Grebe/Marsh [rip]"

# Soundtrack-type albums, each held until someone says what it is.
GAME = "S/Sakura/Overworld [rip]"
FILM = "F/Fennel/Harbour [rip]"
VARIOUS = "V/Various Artists/Boss Battles [rip]"
DUO = "D/Dace & Eider/Two Hands [rip]"

TITLES = ["One", "Two"]
NEW_TITLE = "Second Wind"
NEW_ALBUM = "Renamed Record"
# Not a genre MusicBrainz gives the release group (that is `rock`), so the
# written genre can only have come from the edit.
NEW_GENRE = "jazz"

# The two artists of DUO. Nobody else in the library is either of them.
DACE, EIDER = mbid(3, 91), mbid(3, 92)


def credit(*artists: tuple[str, str]) -> list[dict]:
    """A ws/2 `artist-credit` for `artists`, each an (MBID, name) pair, joined with ` & `."""
    return [{"name": name, "joinphrase": " & " if i < len(artists) - 1 else "",
             "artist": {"id": ident, "name": name, "sort-name": name}}
            for i, (ident, name) in enumerate(artists)]


def soundtrack(number: int, key: str, album_credit: list[dict] | None = None) -> tuple[dict, dict]:
    """A Soundtrack-type release for the rip at `key`, with nothing else saying whether it is game music.

    No game tag on the group, no genre on the files, so 001 holds it as an
    unsettled soundtrack until the memory settles it. `album_credit`
    replaces the stock single-artist credit on the release and every track.
    """
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, TITLES)
    group["secondary-types"] = ["Soundtrack"]
    found["release-group"]["secondary-types"] = ["Soundtrack"]
    if album_credit is not None:
        found["artist-credit"] = album_credit
        for track in found["media"][0]["tracks"]:
            track["artist-credit"] = album_credit
    return found, group


def ordinary(number: int, key: str) -> tuple[dict, dict]:
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    return release(number, artist, title, TITLES)


CATALOGUE = {
    TITLED: ordinary(1, TITLED),
    RENAMED: ordinary(2, RENAMED),
    REGENRED: ordinary(3, REGENRED),
    GAME: soundtrack(4, GAME),
    FILM: soundtrack(5, FILM),
    VARIOUS: soundtrack(6, VARIOUS, credit((VARIOUS_ARTISTS, "Various Artists"))),
    DUO: soundtrack(7, DUO, credit((DACE, "Dace"), (EIDER, "Eider"))),
}


def release_of(key: str) -> str:
    return CATALOGUE[key][0]["id"]


def artist_of(key: str) -> str:
    return CATALOGUE[key][0]["artist-credit"][0]["artist"]["id"]


def entries(job: Path) -> dict[str, dict]:
    doc = json.loads((job / "plan.json").read_text(encoding="utf-8"))
    return {entry["source"]: entry for entry in doc["albums"]}


def at(entry: dict, position: str) -> dict:
    """The entry's planned file at `position`."""
    return next(f for f in entry["files"] if f["position"] == position)


def key_of(field: str) -> str:
    """`field`'s tag key in a FLAC file, which every rip here is."""
    return mapping.PICARD[field]["vorbis"]


def without_pictures(tags: dict) -> dict:
    """`tags` less the embedded cover, whose planned value is the old picture's digest (`tests.test_batch_apply`)."""
    return {k: v for k, v in tags.items() if not tagwrite.is_picture_key("vorbis", k)}


def accept(key: str, edits: dict, game: str | None = None) -> dict:
    return {"action": "accept", "release_id": release_of(key), "edits": edits, "game": game}


def every_position(field: str, value: str) -> dict:
    """An album-level field changed once on the page, which it exports into every position."""
    return {f"1-{n}": {field: [value]} for n in range(1, len(TITLES) + 1)}


class Memory(unittest.TestCase):
    """Job `j1` over `<tmp>/library`, decided and applied; then job `j2` over `<tmp>/fresh/library`.

    The rips are made once at `<tmp>/rips` and copied to both libraries, so
    the second job sees exactly what the first job saw before it wrote
    anything. Both jobs use `<tmp>/.musiclib/memory.json`.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = cls.base = Path(tmp.name)
        no_throttle(cls)
        catalogue = list(CATALOGUE.values())

        rips = base / "rips"
        for key in CATALOGUE:
            album(rips, key, TITLES, release_id=release_of(key))

        # `Library` is test_batch_apply's: its stub systemctl and refusing
        # transport are what apply gets here too.
        lib = cls.lib = Library(base)
        lib.root.rmdir()
        shutil.copytree(rips, lib.root)
        lib.catalogue = catalogue
        cls.memory = lib.memory

        lib.identify()
        cls.planned = lib.entries()
        # Each case below reads one of these as a precondition. A fixture
        # that planned otherwise would have the cases pass or fail for a
        # reason that has nothing to do with the memory.
        for key in (TITLED, RENAMED, REGENRED):
            if cls.planned[key]["state"] != "auto":
                raise AssertionError(f"{key} is not auto before any decision: {cls.planned[key]}")
        for key in (GAME, FILM, VARIOUS, DUO):
            entry = cls.planned[key]
            if (entry["state"], entry["holds"], entry["game_choice"]) != (
                    "held", [{"kind": "status", "detail": UNSETTLED}], True):
                raise AssertionError(f"{key} is not held only as an unsettled soundtrack: {entry}")
        if cls.memory.exists():
            raise AssertionError("memory.json exists before anything was applied")

        lib.decide({
            TITLED: accept(TITLED, {"1-2": {"title": [NEW_TITLE]}}),
            RENAMED: accept(RENAMED, every_position("album", NEW_ALBUM)),
            REGENRED: accept(REGENRED, every_position("genre", NEW_GENRE)),
            GAME: accept(GAME, {}, VGM),
            FILM: accept(FILM, {}, NOT_GAME),
            VARIOUS: accept(VARIOUS, {}, VGM),
            DUO: accept(DUO, {}, VGM),
        })
        cls.decided = lib.entries()
        cls.code, cls.out, cls.err = lib.apply()
        cls.remembered = json.loads(cls.memory.read_text(encoding="utf-8")) if cls.memory.exists() else None

        fresh = base / "fresh" / "library"
        shutil.copytree(rips, fresh)
        cls.fresh_job = base / ".musiclib" / "jobs" / "j2"
        cls.fresh_job.mkdir(parents=True)
        run_identify(fresh, cls.fresh_job, cls.memory, Services(catalogue))
        cls.again = entries(cls.fresh_job)

    def written(self, key: str) -> dict[str, dict[str, list[str]]]:
        """`key`'s tracks as apply left them in the first library: destination rel -> tags."""
        destination = self.decided[key]["destination"]
        folder = self.lib.root / destination
        self.assertTrue(folder.is_dir(), f"{key}: nothing at {destination}; apply said: {self.err}")
        return {f"{destination}/{p.name}": files.read(p).tags for p in sorted(folder.glob("*.flac"))}

    def assertRemembered(self) -> dict:
        self.assertIsNotNone(self.remembered, f"apply wrote no memory.json; it said: {self.out}{self.err}")
        return self.remembered

    # --- field edits -------------------------------------------------------

    def test_every_applied_field_edit_is_stored_under_its_release_mbid_and_track_position(self):
        memory = self.assertRemembered()
        # Keyed by release, not by album folder: the folder is exactly what
        # an applied title or album edit changes, and the import app meets
        # the release in a folder that was never in this job.
        expected = {
            TITLED: {"1-2": {"title": [NEW_TITLE]}},
            RENAMED: every_position("album", NEW_ALBUM),
            REGENRED: every_position("genre", NEW_GENRE),
        }
        for key, edits in expected.items():
            with self.subTest(album=key):
                self.assertEqual(memory.get("edits", {}).get(release_of(key)), edits)

    def test_a_later_job_over_untouched_rips_plans_every_remembered_edit_again(self):
        cases = [(TITLED, "1-2", "title", NEW_TITLE),
                 (RENAMED, "1-1", "album", NEW_ALBUM), (RENAMED, "1-2", "album", NEW_ALBUM),
                 (REGENRED, "1-1", "genre", NEW_GENRE), (REGENRED, "1-2", "genre", NEW_GENRE)]
        for key, position, field, value in cases:
            with self.subTest(album=key, position=position, field=field):
                entry = self.again[key]
                self.assertEqual(entry["fields"][position][field], [value])
                self.assertEqual(at(entry, position)["after"][key_of(field)], [value])

    def test_a_remembered_title_edit_stays_on_its_own_track_in_a_later_job(self):
        # An edit keyed by release alone, or read back onto every position,
        # would retitle track 1 as well.
        entry = self.again[TITLED]
        self.assertEqual(entry["fields"]["1-1"]["title"], ["One"])
        self.assertEqual(at(entry, "1-2")["destination"].rsplit("/", 1)[1], f"02. {NEW_TITLE}.flac")

    # --- edits laid over the plan ----------------------------------------------

    def test_an_applied_title_edit_renames_that_tracks_file_and_leaves_the_other_track_as_planned(self):
        tracks = self.written(TITLED)
        destination = self.decided[TITLED]["destination"]
        edited, untouched = f"{destination}/02. {NEW_TITLE}.flac", f"{destination}/01. One.flac"
        self.assertEqual(sorted(tracks), sorted([untouched, edited]))
        self.assertEqual(tracks[edited][key_of("title")], [NEW_TITLE])
        self.assertEqual(tracks[untouched][key_of("title")], ["One"])

    def test_an_applied_album_edit_renames_the_album_folder_and_nothing_is_left_at_the_old_one(self):
        before = self.planned[RENAMED]["destination"]
        # `(1989) Old Name` becomes `(1989) Renamed Record`: the year and the
        # artist folder are the engine's and do not move.
        parent, folder = before.rsplit("/", 1)
        expected = f"{parent}/{folder.replace('Old Name', NEW_ALBUM)}"
        self.assertNotEqual(expected, before, "the fixture's folder does not carry its album title")
        self.assertEqual(self.decided[RENAMED]["destination"], expected)
        tracks = self.written(RENAMED)
        self.assertEqual(len(tracks), len(TITLES))
        for rel, tags in tracks.items():
            self.assertEqual(tags[key_of("album")], [NEW_ALBUM], rel)
        self.assertFalse((self.lib.root / before).exists(), f"{before} is still in the library")

    def test_an_applied_genre_edit_changes_the_genre_tag_and_nothing_else(self):
        # What the engine planned before the edit, key for key and path for
        # path. The genre is the only thing that may differ.
        planned = self.planned[REGENRED]
        expected = {}
        for track in planned["files"]:
            tags = without_pictures(track["after"])
            tags[key_of("genre")] = [NEW_GENRE]
            expected[track["destination"]] = tags
        self.assertEqual(self.decided[REGENRED]["destination"], planned["destination"])
        written = {rel: without_pictures(tags) for rel, tags in self.written(REGENRED).items()}
        self.assertEqual(written, expected)

    # --- composer choices ----------------------------------------------------

    def test_a_game_choice_on_a_single_artist_album_is_written_to_that_album_in_the_same_apply(self):
        # Stored for next time is not enough: the album the owner decided
        # is written now, with the choice in its genre.
        for rel, tags in self.written(GAME).items():
            self.assertEqual(tags[key_of("genre")][0], VGM, rel)
        for rel, tags in self.written(FILM).items():
            self.assertNotIn(VGM, tags[key_of("genre")], rel)

    def test_a_remembered_video_game_music_composer_makes_the_next_job_plan_that_genre_first(self):
        entry = self.again[GAME]
        self.assertEqual((entry["state"], entry["holds"]), ("auto", []))
        for position in ("1-1", "1-2"):
            self.assertEqual(entry["fields"][position]["genre"][0], VGM, position)

    def test_a_remembered_not_game_music_composer_lets_a_soundtrack_album_auto_apply_next_time(self):
        # Held as an unsettled soundtrack in the first job (setUpClass checks
        # it). Nothing about the album changed since, only the memory.
        entry = self.again[FILM]
        self.assertEqual((entry["state"], entry["status"], entry["holds"]), ("auto", "certain", []))
        self.assertNotIn(VGM, entry["fields"]["1-1"]["genre"])

    def test_a_game_choice_on_a_various_artists_or_two_artist_album_is_written_to_that_album(self):
        for key in (VARIOUS, DUO):
            with self.subTest(album=key):
                tracks = self.written(key)
                self.assertEqual(len(tracks), len(TITLES))
                for rel, tags in tracks.items():
                    self.assertEqual(tags[key_of("genre")][0], VGM, rel)

    def test_game_choices_are_stored_under_a_single_album_artist_and_never_under_various_or_two_artists(self):
        # Various Artists is on hundreds of unrelated albums, and a
        # two-artist credit names nobody as the composer. Keeping either
        # would decide albums the owner never looked at. Only the two
        # single-artist choices may be here, each under its own artist.
        composers = self.assertRemembered().get("composers", {})
        self.assertEqual(composers, {artist_of(GAME): VGM, artist_of(FILM): NOT_GAME})
        for artist in (VARIOUS_ARTISTS, DACE, EIDER):
            self.assertNotIn(artist, composers)


if __name__ == "__main__":
    unittest.main()
