"""Which albums a batch applies without the owner, and the reasons every other one is held.

An album is auto-applied only when its status is `certain` or `auto`, its
plan passes validation, it has no destination collision and the memory has
not reopened it. Every other album is held, and its `holds` in `plan.json`
name every reason, not the first one found. The printed counts are checked
against the same `plan.json`.

One library holds one album per reason, planned in a single run that every
case reads. Each held album breaks exactly one condition, apart from the one
that breaks two. The hold kinds are `status`, `validation`, `collision`,
`reopened`. The fakes are `tests.test_batch_identify`'s.

`Suffixes` is a second library, of editions that would share an album
folder (criterion 64). Where one field of their releases tells them apart,
each is filed under its own value of it in brackets, and nothing is held.
The field is the first of the disambiguation comment, the country and the
medium format that every edition in the set has and no two share, compared
without case. `SuffixesTheSecondTime` applies two such pairs and plans a new
job over what apply wrote (criterion 28).
"""

from __future__ import annotations

import collections
import json
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from musiclib import check
from tests import builders
from tests.test_batch_apply import new_library
from tests.test_batch_identify import Services, album, no_throttle, release, run_identify

AUTO = "A/Auto Band/Clean [rip]"
REVIEW = "R/Review Band/Off [rip]"
UNIDENTIFIED = "U/Unknown Band/Nothing [rip]"
NO_GENRE = "G/Genreless Band/Bare [rip]"
PAIR = ("P/Pair Band/Twice [flac]", "P/Pair Band/Twice [rip]")
MOVING = "O/Occupied Band/Moved [rip]"
#: Where MOVING's release plans it to, already holding another album.
OCCUPANT = "O/Occupied Band/(2010) Moved"
REOPENED = "E/Reopened Band/Again [rip]"
TWO_REASONS = "T/Two Band/Both [rip]"


def kinds(entry: dict) -> set[str]:
    return {hold["kind"] for hold in entry["holds"]}


def details(entry: dict, kind: str) -> list[str]:
    return [hold["detail"] for hold in entry["holds"] if hold["kind"] == kind]


class Holds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        root = base / "library"
        job = base / ".musiclib" / "jobs" / "j1"
        job.mkdir(parents=True)
        memory = base / ".musiclib" / "memory.json"
        no_throttle(cls)

        catalogue = []

        def tagged(key, number, *, exact=True, genres=None, titles=("One", "Two")):
            found, group = release(number, key.split("/")[1], key.split("/")[2].split(" [")[0],
                                   list(titles), exact=exact, genres=genres)
            catalogue.append((found, group))
            album(root, key, list(titles), release_id=found["id"])

        tagged(AUTO, 1)
        tagged(REVIEW, 2, exact=False)
        album(root, UNIDENTIFIED, ["One", "Two"])
        # One track, so the plan has one "no genre" problem and the album one
        # validation hold, whichever way the printed count counts holds.
        tagged(NO_GENRE, 4, genres={}, titles=("One",))
        # Two rips of one release, planned to the same folder. Neither
        # collides with anything already on disk, so only comparing the
        # job's own destinations finds it.
        found, group = release(5, "Pair Band", "Twice", ["One", "Two"])
        catalogue.append((found, group))
        for key in PAIR:
            album(root, key, ["One", "Two"], release_id=found["id"])
        # The occupant has no release ID and a search finds nothing, so it
        # stays where it is and plans no destination of its own. Only the
        # write's own collision check sees the files in MOVING's way.
        tagged(MOVING, 6)
        occupant = album(root, OCCUPANT, ["One", "Two"])
        # Filed under the names MOVING's tracks are planned to take.
        for loose in sorted(occupant.glob("0*.flac")):
            number, title = loose.stem.split(" ", 1)
            loose.rename(occupant / f"{number}. {title.title()}.flac")
        tagged(REOPENED, 7)
        tagged(TWO_REASONS, 8, exact=False, genres={}, titles=("One",))
        memory.write_text(json.dumps({"edits": {}, "composers": {}, "reopened": [REOPENED]}))

        cls.code, cls.out, cls.err = run_identify(root, job, memory, Services(catalogue))
        cls.doc = json.loads((job / "plan.json").read_text(encoding="utf-8"))
        cls.albums = {entry["source"]: entry for entry in cls.doc["albums"]}

    def entry(self, key: str) -> dict:
        self.assertIn(key, self.albums, f"{key} is not in plan.json:\n{self.err}")
        return self.albums[key]

    def assertHeld(self, key: str, expected: set[str]) -> dict:
        entry = self.entry(key)
        self.assertEqual(entry["state"], "held", key)
        self.assertEqual(kinds(entry), expected, entry["holds"])
        return entry

    def test_a_certain_album_that_plans_a_change_is_auto_with_no_holds(self):
        # The control: every held album below differs from this one in the
        # condition it breaks. If this one is held too, the others prove nothing.
        entry = self.entry(AUTO)
        self.assertEqual(entry["status"], "certain")
        self.assertNotEqual(entry["changes"], [])
        self.assertEqual((entry["state"], entry["holds"]), ("auto", []))

    def test_an_album_identified_only_for_review_is_held_for_its_status(self):
        entry = self.assertHeld(REVIEW, {"status"})
        self.assertEqual(entry["status"], "review")
        self.assertEqual(len(details(entry, "status")), 1)
        self.assertTrue(details(entry, "status")[0].startswith("review"), entry["holds"])

    def test_an_unidentified_album_is_held_for_its_status_with_the_engines_reason(self):
        entry = self.assertHeld(UNIDENTIFIED, {"status"})
        self.assertEqual(entry["status"], "unidentified")
        # With no AcoustID the engine gives a reason, and the owner needs it
        # to know whether a key or a better tag would have found the album.
        (detail,) = details(entry, "status")
        self.assertRegex(detail, r"^unidentified: \S")

    def test_a_certain_album_whose_plan_fails_validation_is_held_naming_the_problem(self):
        entry = self.assertHeld(NO_GENRE, {"validation"})
        self.assertEqual(entry["status"], "certain")
        self.assertTrue(any("no genre" in detail for detail in details(entry, "validation")),
                        entry["holds"])

    def test_two_albums_planned_to_one_destination_are_both_held_and_each_names_the_other(self):
        first, second = (self.assertHeld(key, {"collision"}) for key in PAIR)
        self.assertEqual(first["destination"], second["destination"])
        self.assertTrue(any(PAIR[1] in detail for detail in details(first, "collision")), first["holds"])
        self.assertTrue(any(PAIR[0] in detail for detail in details(second, "collision")), second["holds"])

    def test_an_album_whose_destination_already_holds_another_albums_files_is_held_for_the_collision(self):
        entry = self.assertHeld(MOVING, {"collision"})
        self.assertEqual(entry["destination"], OCCUPANT)
        self.assertTrue(any(OCCUPANT in detail for detail in details(entry, "collision")), entry["holds"])

    def test_an_album_the_memory_reopened_is_held_though_it_is_certain_and_clean(self):
        entry = self.assertHeld(REOPENED, {"reopened"})
        self.assertEqual(entry["status"], "certain")
        self.assertEqual(details(entry, "reopened"), [""])

    def test_an_album_held_for_two_reasons_names_both(self):
        # The easy mistake is to stop at the first failed condition, which
        # leaves the owner fixing the status only to meet the second reason
        # on the next run.
        entry = self.assertHeld(TWO_REASONS, {"status", "validation"})
        self.assertTrue(any("no genre" in detail for detail in details(entry, "validation")),
                        entry["holds"])

    def test_the_printed_counts_match_plan_json_status_then_state_then_hold_each_sorted(self):
        entries = self.doc["albums"]
        # Every album here has at most one hold of each kind, so counting
        # albums per kind and counting hold items per kind agree, whichever
        # one the printed count actually means.
        per_album = collections.Counter(k for entry in entries for k in kinds(entry))
        per_item = collections.Counter(hold["kind"] for entry in entries for hold in entry["holds"])
        self.assertEqual(per_album, per_item, "the fixture has an album with two holds of one kind")

        expected = []
        for label, counts in (("status", collections.Counter(e["status"] for e in entries)),
                              ("state", collections.Counter(e["state"] for e in entries)),
                              ("hold", per_album)):
            expected += [f"{label} {name}: {n}" for name, n in sorted(counts.items())]
        # A count line of zero, if the command prints them, says nothing
        # either way and is left out.
        printed = [line for line in self.out.splitlines()
                   if re.fullmatch(r"(status|state|hold) .+: [1-9]\d*", line)]
        self.assertEqual(printed, expected)
        # Pinned as well, so a plan.json that is wrong in the same way as the
        # printout cannot pass on its own agreement.
        self.assertIn("state auto: 1", printed)
        self.assertIn("state held: 9", printed)
        self.assertIn("hold collision: 3", printed)



#: MusicBrainz gives `country` as a code and the name only on the release
#: event's area. The folder takes the name.
AREAS = {
    "JP": {"id": "2db42837-c832-3c27-b4a3-08198f75693c", "name": "Japan", "sort-name": "Japan",
           "iso-3166-1-codes": ["JP"]},
    "XE": {"id": "89a675c2-3e37-3518-b83c-418bad59a85a", "name": "Europe", "sort-name": "Europe",
           "iso-3166-1-codes": ["XE"]},
    "US": {"id": "489ce91b-6658-3307-9877-795b68554c98", "name": "United States",
           "sort-name": "United States", "iso-3166-1-codes": ["US"]},
    # MusicBrainz's own name for this area carries the brackets.
    "XW": {"id": "525d4e18-3d00-31b9-a58b-a146a916de8f", "name": "[Worldwide]", "sort-name": "[Worldwide]",
           "iso-3166-1-codes": ["XW"]},
}

UNIA = ("S/Sonata Arctica/Unia [jp]", "S/Sonata Arctica/Unia [eu]")
DEAR_SCIENCE = ("T/TV on the Radio/Dear Science [cd]", "T/TV on the Radio/Dear Science [lp]")
COMMENTED = ("C/Comment Band/Noted [a]", "C/Comment Band/Noted [b]")
ONE_COMMENT = ("H/Half Band/Half [a]", "H/Half Band/Half [b]")
CASED_COMMENT = ("C/Case Band/Cased [a]", "C/Case Band/Cased [b]")
THREE = ("F/Format Band/Thrice [a]", "F/Format Band/Thrice [b]", "F/Format Band/Thrice [c]")
SAME_RELEASE = ("D/Double Band/Twice [a]", "D/Double Band/Twice [b]")
EVENTS = ("E/Event Band/Events [a]", "E/Event Band/Events [b]")
WITH_VIDEO = ("V/Video Band/Vision [a]", "V/Video Band/Vision [b]")
LONE = "L/Lone Band/Alone [rip]"
LONG = ("W/Wordy Band/Long [a]", "W/Wordy Band/Long [b]")
GLOBE = ("G/Globe Band/Globe [a]", "G/Globe Band/Globe [b]")
BRACED = ("B/Brace Band/Braced [a]", "B/Brace Band/Braced [b]")

#: 59 six-letter words: 412 bytes, so `(2007) ` and the title are cut.
LONG_TITLE = " ".join(f"Part{n:02d}" for n in range(1, 60))


def edition(number: int, key: str, *, date: str, comment: str = "", country: str = "JP",
            fmt: str = "CD") -> tuple[dict, dict]:
    """The release `key` is an edition of: `tests.test_batch_identify.release` with its edition fields set.

    `comment` is the release's disambiguation, which MusicBrainz gives as
    `""` when there is none. `country` is a key of `AREAS`, set both as the
    code and as the one release event. `fmt` is every medium's format.
    """
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, ["One", "Two"])
    found["date"] = date
    group["first-release-date"] = found["release-group"]["first-release-date"] = date
    found["disambiguation"] = comment
    found["country"] = country
    found["release-events"] = [{"date": date, "area": AREAS[country]}]
    for medium in found["media"]:
        medium["format"] = fmt
    return found, group


class Suffixes(unittest.TestCase):
    """Editions that plan to one album folder in one job, and two albums that must keep it.

    Every release here is `certain` and plans a change, so an album held for
    anything is held for the suffix alone. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        root = base / "library"
        job = base / ".musiclib" / "jobs" / "j1"
        job.mkdir(parents=True)
        no_throttle(cls)

        catalogue = []
        numbers = iter(range(100, 200))

        def filed(key, **fields):
            found, group = edition(next(numbers), key, **fields)
            catalogue.append((found, group))
            album(root, key, ["One", "Two"], release_id=found["id"])

        # Two dates in one year: the folder takes the year, so the two
        # collide on it though their releases differ in date.
        filed(UNIA[0], date="2007-05-23", country="JP")
        filed(UNIA[1], date="2007-05-25", country="XE")
        filed(DEAR_SCIENCE[0], date="2008-09-23", country="US", fmt="CD")
        filed(DEAR_SCIENCE[1], date="2008-09-23", country="US", fmt="Vinyl")
        # Each field separates these, so the order of the fields decides.
        filed(COMMENTED[0], date="2007", comment="tour edition", country="JP", fmt="CD")
        filed(COMMENTED[1], date="2007", comment="club edition", country="XE", fmt="Vinyl")
        filed(ONE_COMMENT[0], date="2007", comment="digipak", country="JP")
        filed(ONE_COMMENT[1], date="2007", country="XE")
        filed(CASED_COMMENT[0], date="2007", comment="Remaster", country="JP")
        filed(CASED_COMMENT[1], date="2007", comment="remaster", country="XE")
        filed(THREE[0], date="2007", country="JP", fmt="CD")
        filed(THREE[1], date="2007", country="JP", fmt="Vinyl")
        filed(THREE[2], date="2007", country="XE", fmt="Cassette")
        # Released in the US first, but the release's country is Japan, and
        # its name is on the event whose area carries that code.
        filed(EVENTS[0], date="2007", country="JP")
        filed(EVENTS[1], date="2007", country="XE")
        # A DVD of one video holds no audio, so it is not counted, and the
        # format is the CD's alone.
        filed(WITH_VIDEO[0], date="2007", country="US", fmt="CD")
        filed(WITH_VIDEO[1], date="2007", country="US", fmt="Vinyl")
        filed(LONG[0], date="2007", country="JP")
        filed(LONG[1], date="2007", country="XE")
        filed(GLOBE[0], date="2007", country="XW")
        filed(GLOBE[1], date="2007", country="JP")
        filed(BRACED[0], date="2007", comment="live [bonus]", country="JP")
        filed(BRACED[1], date="2007", comment="studio", country="XE")
        # Every field is there to take, so an album given a suffix it did
        # not need has one to show.
        filed(LONE, date="2007", comment="tour edition", country="JP")
        found, group = edition(next(numbers), SAME_RELEASE[0], date="2007", comment="tour edition",
                               country="JP")
        catalogue.append((found, group))
        for key in SAME_RELEASE:
            album(root, key, ["One", "Two"], release_id=found["id"])
        for found, _group in catalogue:
            if found["title"] == "Events" and found["country"] == "JP":
                found["release-events"].insert(0, {"date": "2007", "area": AREAS["US"]})
            if found["title"] == "Vision" and found["media"][0]["format"] == "CD":
                dvd = builders.mb_medium(2, ["Video"], fmt="DVD-Video")
                dvd["tracks"][0]["recording"]["video"] = True
                found["media"].append(dvd)
        # The long pair's title is the release's, so the rips' folder names
        # stay short enough for the filesystem.
        for found, _group in catalogue:
            if found["title"] == "Long":
                found["title"] = found["release-group"]["title"] = _group["title"] = LONG_TITLE

        cls.code, cls.out, cls.err = run_identify(root, job, base / ".musiclib" / "memory.json",
                                                  Services(catalogue))
        cls.doc = json.loads((job / "plan.json").read_text(encoding="utf-8"))
        cls.albums = {entry["source"]: entry for entry in cls.doc["albums"]}

    def entry(self, key: str) -> dict:
        self.assertIn(key, self.albums, f"{key} is not in plan.json:\n{self.err}")
        return self.albums[key]

    def assertFiledUnder(self, expected: dict[str, str]) -> None:
        """Each album planned to its folder, every track inside it, and nothing held."""
        for key, destination in expected.items():
            with self.subTest(album=key):
                entry = self.entry(key)
                self.assertEqual(entry["destination"], destination)
                # The folder and the tracks are planned apart, and a write
                # goes by the tracks.
                self.assertEqual({str(PurePosixPath(f["destination"]).parent) for f in entry["files"]},
                                 {destination})
                # A suffixed folder the plan's own validation refuses would
                # hold the album anyway, for `validation` in place of
                # `collision`.
                self.assertEqual((entry["state"], entry["holds"]), ("auto", []))

    def test_two_editions_from_different_countries_are_filed_under_each_country_name(self):
        # Neither folder exists when the plan is judged. `check` takes a
        # suffix only beside the other edition's folder, so
        # a plan's own validation that asked the disk would hold both.
        self.assertFiledUnder({UNIA[0]: "S/Sonata Arctica/(2007) Unia [Japan]",
                               UNIA[1]: "S/Sonata Arctica/(2007) Unia [Europe]"})

    def test_two_editions_from_one_country_are_filed_under_each_medium_format(self):
        self.assertFiledUnder({DEAR_SCIENCE[0]: "T/TV on the Radio/(2008) Dear Science [CD]",
                               DEAR_SCIENCE[1]: "T/TV on the Radio/(2008) Dear Science [Vinyl]"})

    def test_the_disambiguation_comment_goes_first_when_every_edition_has_a_different_one(self):
        self.assertFiledUnder({COMMENTED[0]: "C/Comment Band/(2007) Noted [tour edition]",
                               COMMENTED[1]: "C/Comment Band/(2007) Noted [club edition]"})

    def test_a_comment_only_one_edition_has_is_passed_over_for_the_country_of_both(self):
        # Read as "each album's own first field", this files one under its
        # comment and the other under its country, and the two suffixes
        # say different kinds of thing.
        self.assertFiledUnder({ONE_COMMENT[0]: "H/Half Band/(2007) Half [Japan]",
                               ONE_COMMENT[1]: "H/Half Band/(2007) Half [Europe]"})

    def test_comments_that_differ_only_in_case_are_passed_over_for_the_country(self):
        # Folders that differ only in case are one folder on a disk that
        # ignores case, and the batch already compares destinations that way.
        self.assertFiledUnder({CASED_COMMENT[0]: "C/Case Band/(2007) Cased [Japan]",
                               CASED_COMMENT[1]: "C/Case Band/(2007) Cased [Europe]"})

    def test_three_editions_two_of_them_from_one_country_are_filed_under_each_format(self):
        # The countries differ across the set, but not between every two of
        # its albums, so the country cannot separate them.
        self.assertFiledUnder({THREE[0]: "F/Format Band/(2007) Thrice [CD]",
                               THREE[1]: "F/Format Band/(2007) Thrice [Vinyl]",
                               THREE[2]: "F/Format Band/(2007) Thrice [Cassette]"})

    def test_the_country_name_is_the_one_on_the_release_event_for_the_releases_country(self):
        self.assertFiledUnder({EVENTS[0]: "E/Event Band/(2007) Events [Japan]",
                               EVENTS[1]: "E/Event Band/(2007) Events [Europe]"})

    def test_the_format_leaves_out_a_medium_with_no_audio(self):
        # Criterion 14 counts only media that hold audio. `[CD + DVD-Video]`
        # names a disc that is not in the folder.
        self.assertFiledUnder({WITH_VIDEO[0]: "V/Video Band/(2007) Vision [CD]",
                               WITH_VIDEO[1]: "V/Video Band/(2007) Vision [Vinyl]"})

    def test_a_title_too_long_for_the_folder_is_cut_before_the_suffix_and_the_suffix_kept(self):
        # 255 bytes less `(2007) `, ` [...]` and ` [Japan]` leaves 234 for
        # the title: 33 words, 230 bytes. `[Europe]` is one byte longer and
        # leaves the same 33.
        kept = " ".join(LONG_TITLE.split(" ")[:33])
        self.assertFiledUnder({LONG[0]: f"W/Wordy Band/(2007) {kept} [...] [Japan]",
                               LONG[1]: f"W/Wordy Band/(2007) {kept} [...] [Europe]"})

    def test_a_country_whose_name_musicbrainz_wraps_in_brackets_is_filed_under_the_name_without_them(self):
        # `[[Worldwide]]` is a folder `check` refuses, so the album would be
        # held for `validation`, the plan's own run of `check`.
        self.assertFiledUnder({GLOBE[0]: "G/Globe Band/(2007) Globe [Worldwide]",
                               GLOBE[1]: "G/Globe Band/(2007) Globe [Japan]"})

    def test_brackets_inside_a_comment_become_parentheses_so_the_suffix_holds_one_pair_of_brackets(self):
        # Unheld means the plan's own run of `check` passed the folder.
        self.assertFiledUnder({BRACED[0]: "B/Brace Band/(2007) Braced [live (bonus)]",
                               BRACED[1]: "B/Brace Band/(2007) Braced [studio]"})

    def test_an_album_alone_in_its_folder_gets_no_suffix(self):
        entry = self.entry(LONE)
        self.assertEqual(entry["destination"], "L/Lone Band/(2007) Alone")
        self.assertEqual((entry["state"], entry["holds"]), ("auto", []))

    def test_two_rips_of_one_release_that_no_field_separates_keep_one_folder_and_stay_held(self):
        for key in SAME_RELEASE:
            with self.subTest(album=key):
                entry = self.entry(key)
                self.assertEqual(entry["destination"], "D/Double Band/(2007) Twice")
                self.assertEqual(kinds(entry), {"collision"}, entry["holds"])


class SuffixesTheSecondTime(unittest.TestCase):
    """Four pairs identified and applied in `j1`, then `j2` over what apply wrote.

    Unia and Dear Science, and two whose suffix MusicBrainz gives with
    brackets of its own: an area named `[Worldwide]`, and a comment with
    brackets inside it.

    Every pair is auto, so no decision is needed. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        for number, key, fields in ((201, UNIA[0], {"date": "2007-05-23", "country": "JP"}),
                                    (202, UNIA[1], {"date": "2007-05-25", "country": "XE"}),
                                    (203, DEAR_SCIENCE[0], {"date": "2008-09-23", "country": "US"}),
                                    (204, DEAR_SCIENCE[1], {"date": "2008-09-23", "country": "US",
                                                            "fmt": "Vinyl"}),
                                    (205, GLOBE[0], {"date": "2007", "country": "XW"}),
                                    (206, GLOBE[1], {"date": "2007", "country": "JP"}),
                                    (207, BRACED[0], {"date": "2007", "comment": "live [bonus]", "country": "JP"}),
                                    (208, BRACED[1], {"date": "2007", "comment": "studio", "country": "XE"})):
            found, group = edition(number, key, **fields)
            lib.catalogue.append((found, group))
            album(lib.root, key, ["One", "Two"], release_id=found["id"])
        lib.identify()
        cls.applied = lib.apply()
        cls.folders = sorted(str(path.relative_to(lib.root)) for path in lib.root.glob("*/*/*"))
        cls.violations = check.check(lib.root)

        cls.j2 = lib.base / ".musiclib" / "jobs" / "j2"
        cls.identified = run_identify(lib.root, cls.j2, lib.memory, Services(lib.catalogue))
        doc = json.loads((cls.j2 / "plan.json").read_text(encoding="utf-8"))
        cls.again = {entry["source"]: entry for entry in doc["albums"]}

    # Sorted as `glob` output is sorted here, by path.
    SUFFIXED = ["B/Brace Band/(2007) Braced [live (bonus)]", "B/Brace Band/(2007) Braced [studio]",
                "G/Globe Band/(2007) Globe [Japan]", "G/Globe Band/(2007) Globe [Worldwide]",
                "S/Sonata Arctica/(2007) Unia [Europe]", "S/Sonata Arctica/(2007) Unia [Japan]",
                "T/TV on the Radio/(2008) Dear Science [CD]", "T/TV on the Radio/(2008) Dear Science [Vinyl]"]

    def test_apply_writes_each_edition_into_its_suffixed_folder_and_leaves_no_rip_folder(self):
        # Apply rebuilds every plan before it writes, and refuses one that
        # comes out different, so a suffix identify added and the rebuild
        # does not gets no album written.
        self.assertEqual(self.folders, self.SUFFIXED, f"apply said: {self.applied}")
        for folder in self.SUFFIXED:
            with self.subTest(folder=folder):
                self.assertEqual(sorted(p.name for p in (self.lib.root / folder).glob("*.flac")),
                                 ["01. One.flac", "02. Two.flac"])

    def test_check_names_no_album_folder_violation_in_a_suffixed_folder(self):
        self.assertEqual(self.folders, self.SUFFIXED, f"apply said: {self.applied}")
        self.assertEqual([v for v in self.violations if v.rule == "album folder"], [])

    def test_a_new_job_over_the_suffixed_folders_proposes_no_change(self):
        # Each pair collides again on the folder without a suffix, and the
        # suffix it gets back must be the one it already has.
        self.assertEqual(self.folders, self.SUFFIXED, f"apply said: {self.applied}")
        for folder in self.SUFFIXED:
            with self.subTest(album=folder):
                self.assertIn(folder, self.again, f"not in j2; identify said: {self.identified}")
                entry = self.again[folder]
                self.assertEqual((entry["destination"], entry["changes"], entry["state"], entry["holds"]),
                                 (folder, [], "unchanged", []))


if __name__ == "__main__":
    unittest.main()
