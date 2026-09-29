"""Album units: what the engine finds under the root, and when it stops.

An album unit is one folder under `Letter/Artist/`. Audio directly in it, or
one level down in any subfolder, is a track; that subfolder is its disc
folder, whatever it is called (`CD1`, `Disc 1`, `CD2 - Live at Budokan`).
When its files disagree on the album tag, it holds more than one album, and
the engine marks it `needs a person` rather than planning it. The Moby
*Hotel* folder with a single in it is the case that started this.

Every case builds a small library in a temporary folder from the tagless
samples, and reads nothing back through the engine's own writer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import Frames

from musiclib import units
from musiclib.identify import identify
from tests import builders

NEEDS_A_PERSON = "needs a person"

# The album tag under each format's own name.
ALBUM_KEY = {"mp3": "TALB", "flac": "ALBUM", "ogg": "ALBUM", "m4a": "\xa9alb"}


def add(album: Path, rel: str, value: str | list[str] | None = None) -> Path:
    """Put a tagless sample at `album/rel`, with `value` as its album tag.

    `.mp4` gets the M4A sample, which is the same container. A list is
    written as that many values, in order.
    """
    path = album / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower().lstrip(".")
    shutil.copyfile(builders.FIXTURES / f"tone.{'m4a' if ext == 'mp4' else ext}", path)
    if value is not None:
        values = value if isinstance(value, list) else [value]
        tag = Frames["TALB"](encoding=3, text=values) if ext == "mp3" else values
        builders.write_tags(path, {ALBUM_KEY[ext]: tag})
    return path


def track_names(unit) -> list[str]:
    return [Path(t.path).relative_to(unit.path).as_posix() for t in unit.tracks]


class UnitsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def album(self, rel: str) -> Path:
        path = self.root / rel
        path.mkdir(parents=True)
        return path

    def only_unit(self):
        [unit] = units.units(self.root)
        return unit


class Finding(UnitsTestCase):
    def test_each_album_folder_under_letter_and_artist_is_one_unit_in_path_order(self) -> None:
        # Made in an order that is neither sorted nor reverse sorted, so only
        # sorting by path gives this list.
        for rel in ("N/Nine Inch Nails/(1999) The Fragile", "M/Moby/(2005) Hotel",
                    "N/Nine Inch Nails/(1994) The Downward Spiral", "P/Placebo/(2004) Once More with Feeling"):
            add(self.album(rel), "01. Track.flac", rel.rsplit(") ", 1)[1])
        found = units.units(self.root)
        self.assertEqual(
            [u.rel for u in found],
            [
                "M/Moby/(2005) Hotel",
                "N/Nine Inch Nails/(1994) The Downward Spiral",
                "N/Nine Inch Nails/(1999) The Fragile",
                "P/Placebo/(2004) Once More with Feeling",
            ],
        )
        for unit in found:
            with self.subTest(unit=unit.rel):
                self.assertEqual(Path(unit.path), self.root / unit.rel)
                self.assertTrue(Path(unit.path).is_absolute())

    def test_cd_folders_belong_to_their_album_and_tracks_come_in_path_order(self) -> None:
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        add(album, "CD2/01. Somewhat Damaged.flac", "The Fragile")
        add(album, "CD1/02. The Day the World Went Away.mp3", "The Fragile")
        add(album, "CD1/01. Somewhat Damaged.flac", "The Fragile")
        unit = self.only_unit()
        self.assertEqual(
            track_names(unit),
            ["CD1/01. Somewhat Damaged.flac", "CD1/02. The Day the World Went Away.mp3",
             "CD2/01. Somewhat Damaged.flac"],
        )

    def test_every_audio_format_counts_as_a_track(self) -> None:
        album = self.album("N/Nine Inch Nails/(1994) The Downward Spiral")
        names = ["01. A.mp3", "02. B.flac", "03. C.ogg", "04. D.m4a", "05. E.mp4"]
        for name in names:
            add(album, name)
        unit = self.only_unit()
        self.assertEqual(track_names(unit), names)
        self.assertEqual(unit.unreadable, [])
        self.assertEqual(unit.others, [])

    def test_everything_that_is_not_audio_is_listed_as_others_subfolders_included(self) -> None:
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        add(album, "CD1/01. Somewhat Damaged.flac", "The Fragile")
        for rel in ("cover.jpg", "rip.log", "Scans/booklet 01.jpg", "CD1/cue.cue"):
            (album / rel).parent.mkdir(parents=True, exist_ok=True)
            (album / rel).write_bytes(b"x")
        unit = self.only_unit()
        self.assertEqual(sorted(unit.others), ["CD1/cue.cue", "Scans/booklet 01.jpg", "cover.jpg", "rip.log"])
        self.assertEqual(track_names(unit), ["CD1/01. Somewhat Damaged.flac"])

    def test_a_macos_appledouble_file_is_not_audio(self) -> None:
        # Copying from a Mac to the share leaves `._name` beside each file.
        # It ends in .flac and holds no audio, so reading it as a track would
        # list every such album as unreadable.
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        add(album, "01. Somewhat Damaged.flac", "The Fragile")
        (album / "._01. Somewhat Damaged.flac").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        ")
        unit = self.only_unit()
        self.assertEqual(track_names(unit), ["01. Somewhat Damaged.flac"])
        self.assertEqual(unit.unreadable, [])
        self.assertEqual(unit.others, ["._01. Somewhat Damaged.flac"])

    def test_stray_files_above_the_album_folders_are_not_units(self) -> None:
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        add(album, "01. Somewhat Damaged.flac", "The Fragile")
        for rel in (".DS_Store", "N/.DS_Store", "N/Nine Inch Nails/folder.jpg"):
            (self.root / rel).write_bytes(b"x")
        self.assertEqual([u.rel for u in units.units(self.root)], ["N/Nine Inch Nails/(1999) The Fragile"])

    def test_an_audio_file_mutagen_cannot_read_is_listed_as_unreadable(self) -> None:
        # Planning refuses such a unit later. Here it is only reported, and
        # the readable tracks are still read.
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        add(album, "01. Somewhat Damaged.flac", "The Fragile")
        (album / "02. The Day the World Went Away.flac").write_bytes(b"not audio at all")
        unit = self.only_unit()
        self.assertEqual(track_names(unit), ["01. Somewhat Damaged.flac"])
        [(rel, error)] = unit.unreadable
        self.assertEqual(rel, "02. The Day the World Went Away.flac")
        self.assertTrue(str(error).strip())
        self.assertIsNone(unit.status)

    def lock(self, folder: Path) -> None:
        """Make `folder` unlistable until the case ends, or skip the case where that cannot be done."""
        folder.chmod(0)
        # Registered after the temporary directory, so it runs first.
        self.addCleanup(folder.chmod, 0o755)
        try:
            list(folder.iterdir())
        except PermissionError:
            return
        self.skipTest("chmod 000 does not stop this user listing a folder (root?)")

    def test_an_unreadable_folder_inside_an_album_is_listed_as_unreadable_and_holds_it(self) -> None:
        # Skipped silently, the album is planned and moved, and whatever the
        # folder holds is left behind in the old one. A disc folder, and a
        # folder two levels down, which only a walk at every depth reaches.
        for locked in ("CD2", "Scans", "Scans/extra"):
            with self.subTest(locked):
                self.root = Path(tempfile.mkdtemp(dir=self.root)).resolve()
                album = self.album("N/Nine Inch Nails/(1999) The Fragile")
                add(album, "CD1/01. Somewhat Damaged.flac", "The Fragile")
                add(album, "CD2/01. The Wretched.flac", "The Fragile")
                (album / "Scans/extra").mkdir(parents=True)
                (album / "Scans/extra/back.jpg").write_bytes(b"x")
                self.lock(album / locked)
                unit = self.only_unit()
                self.assertIn("CD1/01. Somewhat Damaged.flac", track_names(unit))
                self.assertEqual([rel for rel, _reason in unit.unreadable], [locked])
                self.assertTrue(str(unit.unreadable[0][1]).strip())
                # Identify holds a unit with anything unreadable before it
                # asks MusicBrainz, so no client is needed to see it held.
                held = identify(unit, None)
                self.assertEqual((held.status, held.reason), ("unidentified", "unreadable files"))

    def test_an_unreadable_letter_or_artist_folder_is_skipped_and_holds_nothing(self) -> None:
        # Nothing above the album folder belongs to an album, so there is
        # nothing to hold. The other albums are found as before.
        for locked in ("A", "N/A Perfect Circle"):
            with self.subTest(locked):
                self.root = Path(tempfile.mkdtemp(dir=self.root)).resolve()
                add(self.album("A/A Perfect Circle/(2000) Mer de Noms"), "01. The Hollow.flac", "Mer de Noms")
                add(self.album("N/A Perfect Circle/(2003) Thirteenth Step"), "01. The Package.flac", "Thirteenth Step")
                add(self.album("N/Nine Inch Nails/(1999) The Fragile"), "01. Somewhat Damaged.flac", "The Fragile")
                self.lock(self.root / locked)
                found = units.units(self.root)
                self.assertIn("N/Nine Inch Nails/(1999) The Fragile", [u.rel for u in found])
                self.assertFalse([u.rel for u in found if u.rel.startswith(locked + "/")])
                self.assertEqual([u.unreadable for u in found], [[]] * len(found))

    def test_a_root_that_cannot_be_listed_raises_rather_than_reading_as_an_empty_library(self) -> None:
        # An empty library and a misspelt path are not the same answer: the
        # first plans nothing, the second must stop the command.
        with self.assertRaises(FileNotFoundError):
            units.units(self.root / "libary")

    def test_finding_units_writes_nothing(self) -> None:
        # An MP3 with no ID3 tag is the likely victim: reading one gives it an
        # empty tag in memory, and a save would put it on disk.
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.mp3")
        add(album, "02. Raining Again.flac", "Hotel")
        add(album, "03. Beautiful.m4a", "Hotel Remixes")
        (album / "cover.jpg").write_bytes(b"x")
        past = 1_500_000_000
        for path in [*self.root.rglob("*"), self.root]:
            os.utime(path, (past, past))

        def state() -> dict[str, tuple[int, str | None]]:
            return {
                p.relative_to(self.root).as_posix(): (
                    p.stat().st_mtime_ns,
                    hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else None,
                )
                for p in [*self.root.rglob("*"), self.root]
            }

        before = state()
        units.units(self.root)
        after = state()
        changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
        self.assertEqual(changed, [])


class DiscFolders(UnitsTestCase):
    def test_audio_in_any_direct_subfolder_is_a_track_of_the_unit(self) -> None:
        # A descriptive disc folder is where a suggested disc subtitle comes
        # from, so its tracks must reach the plan at all.
        album = self.album("C/The Cure/(2010) Disintegration")
        add(album, "Disc 1/01. Plainsong.flac", "Disintegration")
        add(album, "CD2 - Live at Budokan/01. Prayers for Rain.mp3", "Disintegration")
        add(album, "CD3/01. Last Dance.ogg", "Disintegration")
        unit = self.only_unit()
        self.assertEqual(
            track_names(unit),
            ["CD2 - Live at Budokan/01. Prayers for Rain.mp3", "CD3/01. Last Dance.ogg",
             "Disc 1/01. Plainsong.flac"],
        )
        self.assertEqual(unit.others, [])

    def test_audio_two_levels_down_is_not_a_track(self) -> None:
        # Real, readable audio, so a walk that took every audio file at any
        # depth would count it as a track rather than list it as unreadable.
        album = self.album("C/The Cure/(2010) Disintegration")
        add(album, "01. Plainsong.flac", "Disintegration")
        add(album, "Scans/extra/x.flac", "Something Else")
        unit = self.only_unit()
        self.assertEqual(track_names(unit), ["01. Plainsong.flac"])
        self.assertEqual(unit.others, ["Scans/extra/x.flac"])
        self.assertEqual(unit.unreadable, [])
        # Its album tag is a different album. Counted, it would also mark the
        # unit as needing a person.
        self.assertIsNone(unit.status)


class Disagreement(UnitsTestCase):
    def test_two_album_tags_in_one_folder_need_a_person(self) -> None:
        # The Moby folder: the album and a single from it, filed together.
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", "Hotel")
        add(album, "02. Raining Again.flac", "Raining Again")
        add(album, "03. Beautiful.flac", "Hotel")
        unit = self.only_unit()
        self.assertEqual(unit.status, NEEDS_A_PERSON)
        # The person has to know what to split, so the reason names both.
        self.assertIn("Hotel", unit.reason)
        self.assertIn("Raining Again", unit.reason)

    def test_one_album_tag_needs_nobody(self) -> None:
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", "Hotel")
        add(album, "02. Raining Again.flac", "Hotel")
        self.assertIsNone(self.only_unit().status)

    def test_disagreement_is_found_in_every_format(self) -> None:
        for ext in ("mp3", "flac", "ogg", "m4a"):
            with self.subTest(ext=ext):
                album = self.album(f"N/Nine Inch Nails/(2004) Halo 14 {ext}")
                add(album, f"01. The Hand That Feeds.{ext}", "With Teeth")
                add(album, f"02. Home.{ext}", "Halo 14")
                [unit] = [u for u in units.units(self.root) if u.rel.endswith(ext)]
                self.assertEqual(unit.status, NEEDS_A_PERSON)

    def test_the_same_album_under_each_formats_own_tag_is_agreement(self) -> None:
        # A mixed-format folder names the album with TALB, ALBUM and ©alb.
        # Reading one of those and treating the rest as a different album
        # (or as none) gets this wrong in either direction.
        album = self.album("N/Nine Inch Nails/(1999) The Fragile")
        for number, ext in enumerate(("mp3", "flac", "ogg", "m4a"), start=1):
            add(album, f"0{number}. Track.{ext}", "The Fragile")
        self.assertIsNone(self.only_unit().status)
        add(album, "05. Track.mp3", "Still")
        self.assertEqual(self.only_unit().status, NEEDS_A_PERSON)

    def test_disagreement_across_cd_folders_counts(self) -> None:
        # NIN's Halo 14 and Halo 15 were filed as the two discs of one album.
        album = self.album("N/Nine Inch Nails/(2000) Things Falling Apart")
        add(album, "CD1/01. Starfuckers, Inc.flac", "Halo 14")
        add(album, "CD2/01. Slipping Away.flac", "Halo 15")
        self.assertEqual(self.only_unit().status, NEEDS_A_PERSON)

    def test_surrounding_whitespace_is_not_a_second_album(self) -> None:
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", "Hotel")
        add(album, "02. Raining Again.flac", " Hotel ")
        self.assertIsNone(self.only_unit().status)

    def test_a_difference_in_case_is_a_second_album(self) -> None:
        # Exact comparison. Folding case would hide two albums whose names
        # differ only in case, and the engine cannot tell those from a typo.
        album = self.album("P/Placebo/(2004) B-Sides")
        add(album, "01. Drag.flac", "B-Sides")
        add(album, "02. Leni.flac", "B-sides")
        self.assertEqual(self.only_unit().status, NEEDS_A_PERSON)

    def test_only_the_first_album_value_is_compared(self) -> None:
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", ["Hotel", "Hotel Remixes"])
        add(album, "02. Raining Again.flac", ["Hotel"])
        self.assertIsNone(self.only_unit().status)
        add(album, "03. Beautiful.flac", ["Hotel Remixes", "Hotel"])
        self.assertEqual(self.only_unit().status, NEEDS_A_PERSON)

    def test_a_track_with_no_album_tag_does_not_disagree(self) -> None:
        # Silence is not a second album. An untagged track is the ordinary
        # state of a fresh rip, and identifying it is the engine's job.
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", "Hotel")
        add(album, "02. Raining Again.mp3")
        add(album, "03. Beautiful.m4a")
        self.assertIsNone(self.only_unit().status)

    def test_an_unreadable_file_is_not_a_second_album(self) -> None:
        album = self.album("M/Moby/(2005) Hotel")
        add(album, "01. Hotel Intro.flac", "Hotel")
        (album / "02. Raining Again.flac").write_bytes(b"not audio at all")
        unit = self.only_unit()
        self.assertEqual(len(unit.unreadable), 1)
        self.assertIsNone(unit.status)


if __name__ == "__main__":
    unittest.main()
