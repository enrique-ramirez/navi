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
"""

from __future__ import annotations

import collections
import json
import re
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
