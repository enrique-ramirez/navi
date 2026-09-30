"""Two paths that Wine would take for one file stop the write before it starts.

foobar2000 runs under Wine, which compares names without
regard to case, so `Foo.flac` and `foo.flac` are the same file to it even
on a Linux disk that happily holds both. On this MacBook the disk agrees
with Wine, and a second move onto a name differing only in case replaces
the first file outright, which is the loss the check is there to prevent.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musiclib import files, write
from tests import builders

ALBUM = "N/Nine Inch Nails/(1999) The Fragile"
DESTINATION = "N/Nine Inch Nails/(1999) The Fragile (Deluxe)"
TITLES = ("Somewhat Damaged", "The Day the World Went Away", "The Frail", "The Wretched")


class _Album(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "library"
        self.extras = Path(tmp.name) / "extras"
        self.album = builders.library_album(self.root, discs=(TITLES,))

    def track(self, number: int, name: str, title: str, folder: str = DESTINATION):
        """Track `number` of the album, moved to `folder/name` and retitled."""
        source = f"{ALBUM}/{number:02d}. {TITLES[number - 1]}.flac"
        return builders.file_plan(self.root, source, f"{folder}/{name}", title)

    def assert_refused_naming(self, plan, first: str, second: str):
        before = builders.tree(self.root)

        with self.assertRaises(write.Collision) as caught:
            write.write_album(plan, self.extras)

        self.assertIn(first, str(caught.exception))
        self.assertIn(second, str(caught.exception))
        self.assertEqual(builders.tree(self.root), before)
        self.assertFalse(self.extras.exists())


class Collisions(_Album):
    def test_two_destinations_differing_only_in_case_leave_the_album_untouched_and_name_both(self):
        # The colliding pair comes last, so a check made file by file as the
        # moves happen would already have moved and retagged tracks 1 and 2.
        plan = builders.album_plan(self.root, ALBUM, DESTINATION, [
            self.track(1, "01. Somewhat Damaged.flac", "Somewhat Damaged"),
            self.track(2, "02. The Day the World Went Away.flac", "The Day the World Went Away"),
            self.track(3, "03. Foo.flac", "Foo"),
            self.track(4, "03. foo.flac", "foo"),
        ])
        self.assert_refused_naming(plan, f"{DESTINATION}/03. Foo.flac", f"{DESTINATION}/03. foo.flac")

    def test_a_track_landing_on_a_file_already_in_the_destination_folder_is_refused(self):
        # A leftover from an earlier album in the folder the plan moves into.
        # The plan neither moves nor deletes it, so it stays, and the track
        # would land on it.
        leftover = f"{DESTINATION}/02. THE DAY THE WORLD WENT AWAY.flac"
        (self.root / DESTINATION).mkdir(parents=True)
        builders.copy_fixture(self.root / DESTINATION, "flac", "02. THE DAY THE WORLD WENT AWAY")
        plan = builders.album_plan(self.root, ALBUM, DESTINATION, [
            self.track(1, "01. Somewhat Damaged.flac", "Somewhat Damaged"),
            self.track(2, "02. The Day the World Went Away.flac", "The Day the World Went Away"),
        ])
        self.assert_refused_naming(plan, f"{DESTINATION}/02. The Day the World Went Away.flac", leftover)

    def test_a_kept_file_landing_on_a_file_already_in_the_destination_folder_is_refused(self):
        (self.root / DESTINATION).mkdir(parents=True)
        (self.root / DESTINATION / "NOTES.txt").write_text("somebody else's notes\n")
        plan = builders.album_plan(
            self.root, ALBUM, DESTINATION,
            [self.track(n, f"{n:02d}. {t}.flac", t) for n, t in enumerate(TITLES, start=1)],
            kept=[f"{ALBUM}/notes.txt", f"{ALBUM}/rip.log"])
        self.assert_refused_naming(plan, f"{DESTINATION}/notes.txt", f"{DESTINATION}/NOTES.txt")


class MovedStrayCollisions(_Album):
    """A stray's new name is a destination like any other."""

    def setUp(self):
        super().setUp()
        self.base = self.root.parent

    def arrange(self, case: str) -> None:
        """A fresh library for `case`, so a write one case lets through cannot spoil the next."""
        self.root = self.base / case / "library"
        self.extras = self.base / case / "extras"
        self.album = builders.library_album(self.root, discs=(TITLES,))
        for path in ("COVERS/tracklist.txt", "COVERS/Notes.txt", "COVERS/back side.jpg", "Scans/Back.jpg"):
            (self.album / path).parent.mkdir(parents=True, exist_ok=True)
            (self.album / path).write_bytes(f"the bytes of {path}".encode())

    def tracks(self, folder: str) -> list:
        return [self.track(n, f"{n:02d}. {t}.flac", t, folder=folder) for n, t in enumerate(TITLES, start=1)]

    def test_a_stray_named_like_a_track_or_a_kept_file_leaves_the_album_untouched_and_names_both(self):
        cases = {
            "a track, the album moving": (DESTINATION, [], {"COVERS/tracklist.txt": "01. SOMEWHAT DAMAGED.flac"},
                                         "01. SOMEWHAT DAMAGED.flac", "01. Somewhat Damaged.flac"),
            "a kept file, the album moving": (DESTINATION, ["notes.txt"], {"COVERS/Notes.txt": "NOTES.txt"},
                                              "NOTES.txt", "notes.txt"),
            "a kept file, the album staying": (ALBUM, ["notes.txt"], {"COVERS/Notes.txt": "NOTES.txt"},
                                               "NOTES.txt", "notes.txt"),
            "another stray": (DESTINATION, [], {"COVERS/back side.jpg": "back.jpg", "Scans/Back.jpg": "Back.jpg"},
                              "Back.jpg", "back.jpg"),
        }
        for case, (folder, kept, moved, first, second) in cases.items():
            with self.subTest(case):
                self.arrange(case)
                plan = builders.album_plan(
                    self.root, ALBUM, folder, self.tracks(folder),
                    kept=[f"{ALBUM}/{name}" for name in kept],
                    moved={f"{ALBUM}/{path}": name for path, name in moved.items()})
                self.assert_refused_naming(plan, f"{folder}/{first}", f"{folder}/{second}")


class NotCollisions(_Album):
    def test_a_case_only_rename_in_place_is_written(self):
        # The file's old name matches its new one without regard to case, but
        # the old name is leaving, so nothing stays there to collide with. A
        # check that counted the file against itself would refuse every
        # title whose capitalisation MusicBrainz corrects.
        plan = builders.album_plan(self.root, ALBUM, ALBUM, [
            self.track(3, "03. the frail.flac", "the frail", folder=ALBUM),
        ])

        write.write_album(plan, self.extras)

        names = {p.name for p in self.album.iterdir()}
        self.assertIn("03. the frail.flac", names)
        self.assertNotIn("03. The Frail.flac", names)
        self.assertEqual(files.read(self.album / "03. the frail.flac").tags["title"], ["the frail"])


if __name__ == "__main__":
    unittest.main()
