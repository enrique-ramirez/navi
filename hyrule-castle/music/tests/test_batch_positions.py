"""The position `batch identify` gives each planned file, and where an owner edit at that position lands.

A position is `"<medium>-<track>"`, the key the pairing (`units.pair`)
gives the file: the index of its medium in the release's `media`, and its
track's index on that medium. A pregap is track 0. A DVD listed before the
CD leaves the CD's tracks at medium 2. A video track keeps its index, so the
audio track after it is `1-3` while it is numbered 2. The same key names an
edit on the page, in `decisions.json`, in `memory.json`, in the plan and in
identify's fit check, so an edit made at a position lands on the file that
position was shown for.

The planned file name follows the audio numbering and the disc folder
follows the counted media, whatever the key says: a file renamed after an
edit keeps both.

The library is built the way `tests.test_batch_apply` builds one: rips on
disk, `tests.test_batch_identify`'s fake MusicBrainz, and a `memory.json`
written by hand where an album needs a remembered edit. The cases only read.
"""

from __future__ import annotations

import copy
import json
import shutil
import unicodedata
import unittest
from pathlib import Path

from PIL import Image

from musiclib import mapping
from tests import builders
from tests.test_batch_apply import new_library
from tests.test_batch_identify import TONE_MS, Services, mbid, release, run_identify

# --- releases and rips ---------------------------------------------------------


def media_release(number: int, key: str, media: list[list[str]], *, dvd_first: bool = False,
                  video_tracks: tuple[tuple[int, int], ...] = (), pregap: str | None = None) -> tuple[dict, dict]:
    """A release for the rip at `key`, one list of audio titles per CD, and its release group.

    `dvd_first` lists a DVD of two video tracks ahead of the CDs, so the
    first CD is medium 2. `video_tracks` marks `(medium, track)` as video
    inside a medium. `pregap` puts a hidden track ahead of medium 1's first
    track, which MusicBrainz counts in `track-count` and not in `tracks`.
    Every length matches `tone.flac`, so a tagged rip is `certain`.
    """
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, media[0])
    credit = found["artist-credit"]
    specs = ([(["Clip A", "Clip B"], True)] if dvd_first else []) + [(titles, False) for titles in media]
    found["media"] = []
    for position, (titles, is_video) in enumerate(specs, start=1):
        medium = builders.mb_medium(position, titles, credit=credit, fmt="DVD-Video" if is_video else "CD")
        for track in medium["tracks"]:
            track["length"] = track["recording"]["length"] = TONE_MS
            if is_video or (position, track["position"]) in video_tracks:
                track["recording"]["video"] = True
        found["media"].append(medium)
    if pregap is not None:
        first = found["media"][0]
        hidden = copy.deepcopy(first["tracks"][0])
        hidden.update(id=mbid(9, number), position=0, number="0", title=pregap)
        hidden["recording"] = dict(hidden["recording"], id=mbid(8, number), title=pregap)
        first["pregap"] = hidden
        first["track-count"] += 1
    return found, group


def rip(root: Path, key: str, discs: list[list[str]], release_id: str, *, pregap: str | None = None) -> Path:
    """The rip at `root/key`: one folder, lower-case titles, track and disc numbers, tagged with `release_id`.

    A file is `NN title.flac` on one disc and `D-NN title.flac` on several.
    `pregap` is a file numbered 0 ahead of disc 1's first track.
    """
    base = root / key
    base.mkdir(parents=True)
    artist, album_title = key.split("/")[1], key.split("/")[2]
    for disc, titles in enumerate(discs, start=1):
        numbered = list(enumerate(titles, start=1))
        if pregap is not None and disc == 1:
            numbered.insert(0, (0, pregap))
        for number, title in numbered:
            stem = f"{number:02d} {title.lower()}" if len(discs) == 1 else f"{disc}-{number:02d} {title.lower()}"
            path = base / f"{stem}.flac"
            shutil.copyfile(builders.FIXTURES / "tone.flac", path)
            fields = {"title": [title.lower()], "artist": [artist], "album": [album_title], "date": ["1989"],
                      "release id": [release_id]}
            builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(titles)),
                                                           disc=(disc, len(discs))), v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


def nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def key_of(field: str) -> str:
    """`field`'s tag key in a FLAC file, which every rip here is."""
    return mapping.PICARD[field]["vorbis"]


def by_file(entry: dict) -> dict[str, dict]:
    """The entry's planned files by source file name."""
    return {f["source"].rsplit("/", 1)[1]: f for f in entry["files"]}


def names_under(entry: dict) -> dict[str, str]:
    """Source file name to planned destination below the album folder, for every planned file."""
    return {name: f["destination"].removeprefix(entry["destination"] + "/") for name, f in by_file(entry).items()}


# --- the library ---------------------------------------------------------------

# Albums with no edit: the positions alone.
PREGAP = "P/Pike/Hidden [rip]"
DVD_CD = "D/Dace/Both Sides [rip]"
MIXED = "M/Moth/Interlude [rip]"
DVD_TWO_CD = "T/Tern/Three Discs [rip]"

# The same shapes, each with a remembered title edit at a named position.
PREGAP_TITLED = "P/Plover/Hidden Again [rip]"
DVD_CD_TITLED = "D/Dunlin/Both Again [rip]"
MIXED_TITLED = "M/Merlin/Interlude Again [rip]"
DVD_TWO_CD_TITLED = "T/Teal/Three Again [rip]"

# A remembered album edit, which moves the album.
PREGAP_MOVED = "P/Pipit/Hidden Moved [rip]"
COVER_MOVED = "C/Cobalt/Picture [rip]"
COVER_STILL = "C/Coot/Picture Still [rip]"

# A file whose title disagrees with MusicBrainz, with and without an edit that says so.
REFITTED = "F/Fennel/Retitled [rip]"
UNFITTED = "F/Finch/Not Retitled [rip]"

# Every field edited with decomposed text.
ACCENTED = "N/Nettle/Accents [rip]"

MOVED_ALBUM = "Moved Record"
FOLDER_PNG = "Folder.PNG"
# Written decomposed (NFD). The engine's own text is NFC, so NFD in a
# planned tag can only have come from the edit.
ACCENTED_EDIT = {"title": "Café Añejo", "genre": "música", "discsubtitle": "Première Partie", "label": "Éditions Öl"}


def _library_albums() -> dict[str, tuple[tuple[dict, dict], list[list[str]], str | None, list[list[str]] | None]]:
    """Album key to (release and group, disc titles on MusicBrainz, pregap, disc titles on the files)."""
    one_two = [["One", "Two"]]
    return {
        PREGAP: (media_release(1, PREGAP, [["One", "Two", "Three"]], pregap="Secret"),
                 [["One", "Two", "Three"]], "Secret", None),
        DVD_CD: (media_release(2, DVD_CD, one_two, dvd_first=True), one_two, None, None),
        MIXED: (media_release(3, MIXED, [["One", "Film", "Two"]], video_tracks=((1, 2),)),
                one_two, None, None),
        DVD_TWO_CD: (media_release(4, DVD_TWO_CD, [["One", "Two"], ["Three"]], dvd_first=True),
                     [["One", "Two"], ["Three"]], None, None),
        PREGAP_TITLED: (media_release(5, PREGAP_TITLED, [["One", "Two", "Three"]], pregap="Secret"),
                        [["One", "Two", "Three"]], "Secret", None),
        DVD_CD_TITLED: (media_release(6, DVD_CD_TITLED, one_two, dvd_first=True), one_two, None, None),
        MIXED_TITLED: (media_release(7, MIXED_TITLED, [["One", "Film", "Two"]], video_tracks=((1, 2),)),
                       one_two, None, None),
        DVD_TWO_CD_TITLED: (media_release(8, DVD_TWO_CD_TITLED, [["One", "Two"], ["Three"]], dvd_first=True),
                            [["One", "Two"], ["Three"]], None, None),
        PREGAP_MOVED: (media_release(9, PREGAP_MOVED, [["One", "Two", "Three"]], pregap="Secret"),
                       [["One", "Two", "Three"]], "Secret", None),
        COVER_MOVED: (media_release(10, COVER_MOVED, one_two), one_two, None, None),
        COVER_STILL: (media_release(11, COVER_STILL, one_two), one_two, None, None),
        REFITTED: (media_release(12, REFITTED, one_two, dvd_first=True), one_two, None, [["One", "Zephyr"]]),
        UNFITTED: (media_release(13, UNFITTED, one_two, dvd_first=True), one_two, None, [["One", "Zephyr"]]),
        ACCENTED: (media_release(14, ACCENTED, one_two), one_two, None, None),
    }


ALBUMS = _library_albums()


def release_of(key: str) -> str:
    return ALBUMS[key][0][0]["id"]


def every(keys: list[str], field: str, value: str) -> dict:
    return {position: {field: [value]} for position in keys}


#: `memory.json` as a previous job would have left it. Each edit is keyed
#: by the pairing's position, which is the only key the page ever showed.
MEMORY_EDITS = {
    PREGAP_TITLED: {"1-0": {"title": ["Prelude"]}, "1-2": {"title": ["Deux"]}},
    DVD_CD_TITLED: {"2-2": {"title": ["Deux"]}},
    MIXED_TITLED: {"1-3": {"title": ["Deux"]}},
    DVD_TWO_CD_TITLED: {"3-1": {"title": ["Trois"]}},
    PREGAP_MOVED: every(["1-0", "1-1", "1-2", "1-3"], "album", MOVED_ALBUM),
    COVER_MOVED: every(["1-1", "1-2"], "album", MOVED_ALBUM),
    REFITTED: {"2-2": {"title": ["Zephyr"]}},
    ACCENTED: {"1-1": {field: [nfd(value)] for field, value in ACCENTED_EDIT.items()}},
}


def build(lib, keys: list[str]) -> None:
    """Rip every album of `keys` into `lib`, with `Folder.PNG` in place of `cover.jpg` for the cover albums."""
    for key in keys:
        (found, group), release_discs, pregap, file_discs = ALBUMS[key]
        base = rip(lib.root, key, file_discs or release_discs, found["id"], pregap=pregap)
        if key in (COVER_MOVED, COVER_STILL):
            Image.open(base / "cover.jpg").convert("RGBA").save(base / FOLDER_PNG)
            (base / "cover.jpg").unlink()
        lib.catalogue.append((found, group))


class Positions(unittest.TestCase):
    """Every album above in one library, planned once with the remembered edits, then once with a decision."""

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        build(lib, list(ALBUMS))
        # The edit for an album the library does not have: it must not reach
        # any entry, since no plan here reads it.
        edits = {release_of(key): edits for key, edits in MEMORY_EDITS.items()}
        edits[mbid(1, 999)] = {"1-1": {"title": ["Elsewhere"]}}
        lib.memory.parent.mkdir(parents=True, exist_ok=True)
        lib.memory.write_text(json.dumps({"edits": edits, "composers": {}, "reopened": []}), encoding="utf-8")
        cls.said = run_identify(lib.root, lib.job, lib.memory, Services(lib.catalogue))
        cls.entries = lib.entries()

        # The page's own round: an accept of DVD_CD with an edit at the
        # position the page showed for its second file.
        decisions = {"job": "j1", "albums": {DVD_CD: {
            "action": "accept", "release_id": release_of(DVD_CD), "edits": {"2-2": {"title": ["Deux"]}},
            "game": None}}}
        (lib.job / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
        cls.decided_said = run_identify(lib.root, lib.job, lib.memory, Services(lib.catalogue))
        cls.decided = lib.entries()

    def entry(self, key: str) -> dict:
        entry = self.entries.get(key)
        self.assertIsNotNone(entry, f"{key} is not in plan.json; identify said {self.said}")
        return entry

    # --- criteria 12 and 14: one position per planned file, the pairing's ------

    def test_each_planned_file_is_at_its_pairing_position_in_plan_order(self):
        # The pregap is 1-0, the CD after a DVD is medium 2, and the track
        # after a video keeps its index 3. Counting the release's tracks raw
        # gives 1-1.. for all of them and drops the last file of the pregap
        # album, whose page then shows every title one row off.
        expected = {
            PREGAP: [("00 secret.flac", "1-0"), ("01 one.flac", "1-1"), ("02 two.flac", "1-2"),
                     ("03 three.flac", "1-3")],
            DVD_CD: [("01 one.flac", "2-1"), ("02 two.flac", "2-2")],
            MIXED: [("01 one.flac", "1-1"), ("02 two.flac", "1-3")],
            DVD_TWO_CD: [("1-01 one.flac", "2-1"), ("1-02 two.flac", "2-2"), ("2-01 three.flac", "3-1")],
        }
        for key, pairs in expected.items():
            with self.subTest(album=key):
                entry = self.entry(key)
                self.assertEqual([(f["source"].rsplit("/", 1)[1], f["position"]) for f in entry["files"]], pairs)

    def test_the_page_fields_are_keyed_by_the_same_positions_and_carry_that_files_title(self):
        expected = {
            PREGAP: {"1-0": "Secret", "1-1": "One", "1-2": "Two", "1-3": "Three"},
            DVD_CD: {"2-1": "One", "2-2": "Two"},
            MIXED: {"1-1": "One", "1-3": "Two"},
            DVD_TWO_CD: {"2-1": "One", "2-2": "Two", "3-1": "Three"},
        }
        for key, titles in expected.items():
            with self.subTest(album=key):
                fields = self.entry(key)["fields"]
                self.assertEqual({position: values.get("title") for position, values in fields.items()},
                                 {position: [title] for position, title in titles.items()})

    # --- an edit lands on the file its position names -------------------------

    def test_a_remembered_title_edit_lands_on_the_file_at_its_position_and_nowhere_else(self):
        expected = {
            PREGAP_TITLED: {"00 secret.flac": "Prelude", "01 one.flac": "One", "02 two.flac": "Deux",
                            "03 three.flac": "Three"},
            DVD_CD_TITLED: {"01 one.flac": "One", "02 two.flac": "Deux"},
            MIXED_TITLED: {"01 one.flac": "One", "02 two.flac": "Deux"},
            DVD_TWO_CD_TITLED: {"1-01 one.flac": "One", "1-02 two.flac": "Two", "2-01 three.flac": "Trois"},
        }
        for key, titles in expected.items():
            with self.subTest(album=key):
                planned = {name: f["after"].get(key_of("title")) for name, f in by_file(self.entry(key)).items()}
                self.assertEqual(planned, {name: [title] for name, title in titles.items()})

    def test_a_file_renamed_by_a_title_edit_keeps_its_planned_number_and_disc_folder(self):
        # The number is the audio numbering, not the position: the pregap
        # stays 00 and the track after a video stays 02. The disc folder is
        # the counted disc, so the CDs after a DVD are CD1 and CD2.
        expected = {
            PREGAP_TITLED: {"00 secret.flac": "00. Prelude.flac", "01 one.flac": "01. One.flac",
                            "02 two.flac": "02. Deux.flac", "03 three.flac": "03. Three.flac"},
            DVD_CD_TITLED: {"01 one.flac": "01. One.flac", "02 two.flac": "02. Deux.flac"},
            MIXED_TITLED: {"01 one.flac": "01. One.flac", "02 two.flac": "02. Deux.flac"},
            DVD_TWO_CD_TITLED: {"1-01 one.flac": "CD1/01. One.flac", "1-02 two.flac": "CD1/02. Two.flac",
                                "2-01 three.flac": "CD2/01. Trois.flac"},
        }
        for key, names in expected.items():
            with self.subTest(album=key):
                self.assertEqual(names_under(self.entry(key)), names)

    def test_an_accepted_edit_at_a_pairing_position_is_taken_and_laid_on_that_file(self):
        # decisions.json is refused whole when an edit names a position the
        # album does not have, so an accept keyed the way the page shows it
        # must be one it has.
        code, _out, err = self.decided_said
        self.assertEqual(code, 0, err)
        entry = self.decided[DVD_CD]
        self.assertEqual(entry["decision"], "accept")
        self.assertEqual({name: f["after"].get(key_of("title")) for name, f in by_file(entry).items()},
                         {"01 one.flac": ["One"], "02 two.flac": ["Deux"]})
        self.assertEqual(names_under(entry), {"01 one.flac": "01. One.flac", "02 two.flac": "02. Deux.flac"})

    # --- an edit that moves the album -----------------------------------------

    def test_an_album_edit_moves_the_album_and_every_file_keeps_its_planned_name(self):
        entry = self.entry(PREGAP_MOVED)
        self.assertEqual(entry["destination"], f"P/Pipit/(2010) {MOVED_ALBUM}")
        self.assertEqual(names_under(entry), {"00 secret.flac": "00. Secret.flac", "01 one.flac": "01. One.flac",
                                              "02 two.flac": "02. Two.flac", "03 three.flac": "03. Three.flac"})
        for name, planned in by_file(entry).items():
            self.assertEqual(planned["after"].get(key_of("album")), [MOVED_ALBUM], name)

    def test_an_album_edit_still_deletes_a_folder_png_that_became_cover_jpg(self):
        # Unedited, the rip's Folder.PNG is the cover the plan converts to
        # cover.jpg, and so a deletion. The album edit re-sorts the other
        # files for the new destination, and has to keep that.
        still = self.entry(COVER_STILL)
        self.assertIn(f"{COVER_STILL}/{FOLDER_PNG}", still["deletions"], "the fixture's Folder.PNG is not the cover")
        moved = self.entry(COVER_MOVED)
        self.assertEqual(moved["destination"], f"C/Cobalt/(2010) {MOVED_ALBUM}")
        self.assertIn(f"{COVER_MOVED}/{FOLDER_PNG}", moved["deletions"])
        self.assertNotIn(f"{COVER_MOVED}/{FOLDER_PNG}", moved["extras"] + moved["kept"])

    # --- the fit check reads the edit under the same key ------------------------

    def test_a_remembered_title_edit_makes_its_file_fit_and_lands_on_that_file(self):
        # "zephyr" against MusicBrainz's "Two" fails criterion 1 without the
        # edit (UNFITTED). With it, the pair fits and the album is certain,
        # and the title the fit check read is the one planned for that file.
        self.assertEqual(self.entry(UNFITTED)["status"], "review", "the fixture's file fits without an edit")
        entry = self.entry(REFITTED)
        self.assertEqual((entry["status"], entry["holds"]), ("certain", []))
        self.assertEqual(by_file(entry)["02 zephyr.flac"]["position"], "2-2")
        self.assertEqual(by_file(entry)["02 zephyr.flac"]["after"].get(key_of("title")), ["Zephyr"])
        self.assertEqual(names_under(entry), {"01 one.flac": "01. One.flac", "02 zephyr.flac": "02. Zephyr.flac"})

    # --- criterion 23: an edit is written NFC -----------------------------------

    def test_an_owner_edit_to_any_field_is_planned_nfc(self):
        after = by_file(self.entry(ACCENTED))["01 one.flac"]["after"]
        for field, value in ACCENTED_EDIT.items():
            with self.subTest(field=field):
                self.assertNotEqual(nfd(value), value, "the fixture's text has nothing to compose")
                self.assertEqual(after.get(key_of(field)), [unicodedata.normalize("NFC", value)])

    # --- what an entry stores -----------------------------------------------

    def test_an_entrys_owner_input_holds_the_composers_and_not_the_edit_memory(self):
        # Every entry carried the whole memory's edits, one copy per album:
        # hundreds of megabytes of plan.json on the real library. The plan
        # reads only the composers; the edits it lays are `inputs.edits`.
        planned = [entry for entry in self.entries.values() if entry["inputs"] is not None]
        # An album the engine crashed on has no inputs at all, so the loop
        # below must not come up empty.
        self.assertIn(ACCENTED, [entry["source"] for entry in planned])
        for entry in planned:
            with self.subTest(album=entry["source"]):
                self.assertEqual(entry["inputs"]["owner_input"], {"composers": {}})


# --- criterion 28: the next job proposes nothing --------------------------------

APPLIED = [PREGAP, DVD_TWO_CD, MIXED]
APPLIED_EDITS = {
    PREGAP: {"1-0": {"title": ["Prelude"]}},
    DVD_TWO_CD: {"3-1": {"title": ["Trois"]}},
    MIXED: {"1-3": {"title": ["Deux"]}},
}


class AppliedEdits(unittest.TestCase):
    """Three albums identified, accepted with an edit each, applied, and then a new job over the result."""

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        build(lib, APPLIED)
        lib.identify()
        lib.decide({key: {"action": "accept", "release_id": release_of(key), "edits": edits, "game": None}
                    for key, edits in APPLIED_EDITS.items()})
        cls.decided = lib.entries()
        cls.code, cls.out, cls.err = lib.apply()
        cls.log = lib.log()
        cls.tree = sorted(p.relative_to(lib.root).as_posix() for p in lib.root.rglob("*.flac"))
        job = lib.base / ".musiclib" / "jobs" / "j2"
        cls.again_said = run_identify(lib.root, job, lib.memory, Services(lib.catalogue))
        cls.again = ({e["source"]: e for e in json.loads((job / "plan.json").read_text(encoding="utf-8"))["albums"]}
                     if (job / "plan.json").exists() else {})

    def test_each_edited_album_is_applied_with_the_edited_file_at_its_planned_name(self):
        self.assertEqual(sorted(line["source"] for line in self.log if line["outcome"] == "applied"), sorted(APPLIED),
                         f"apply said: {self.out}{self.err}")
        self.assertEqual(self.tree, sorted([
            "M/Moth/(2010) Interlude/01. One.flac", "M/Moth/(2010) Interlude/02. Deux.flac",
            "P/Pike/(2010) Hidden/00. Prelude.flac", "P/Pike/(2010) Hidden/01. One.flac",
            "P/Pike/(2010) Hidden/02. Two.flac", "P/Pike/(2010) Hidden/03. Three.flac",
            "T/Tern/(2010) Three Discs/CD1/01. One.flac", "T/Tern/(2010) Three Discs/CD1/02. Two.flac",
            "T/Tern/(2010) Three Discs/CD2/01. Trois.flac",
        ]))

    def test_a_new_job_over_the_applied_library_proposes_no_change(self):
        # The memory now holds each edit under its position, and the new job
        # lays it again over the files apply wrote. Laid on another file, it
        # would retitle and rename that one.
        self.assertEqual(len(self.again), len(APPLIED), f"identify said {self.again_said}")
        for key, entry in self.again.items():
            with self.subTest(album=key):
                self.assertEqual((entry["state"], entry["holds"], entry["changes"]), ("unchanged", [], []))


if __name__ == "__main__":
    unittest.main()
