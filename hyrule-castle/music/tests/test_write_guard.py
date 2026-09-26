"""The write path leaves the live library alone while foobar2000 is running.

The live library is `/srv/music/library` on hyrule-castle.
These tests pass a stand-in for it under a temporary folder, and a stub
`systemctl` that answers `active` or `inactive` and notes every call, so
nothing here depends on the machine the tests run on.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from musiclib import files, write
from tests import builders

ALBUM = "N/Nine Inch Nails/(1999) The Fragile"
DESTINATION = "N/Nine Inch Nails/(1999) The Fragile (Deluxe)"


class _Library(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.live = self.tmp / "srv" / "music" / "library"
        self.extras = self.tmp / "srv" / "music" / "extras"
        (self.tmp / "bin").mkdir()

    def systemctl(self, answer: str) -> tuple[Path, Path]:
        """A stub `systemctl` that prints `answer`, and the file its calls land in."""
        script = self.tmp / "bin" / "systemctl"
        calls = self.tmp / "bin" / "calls"
        # `systemctl is-active` exits 3 for a unit that is not running.
        script.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\necho {answer}\nexit {0 if answer == "active" else 3}\n')
        script.chmod(0o755)
        return script, calls

    def plan(self, root: Path):
        """An album under `root`, and a plan that touches it every way a write can.

        Every track is moved and retitled, a new cover is written, a rip list
        is deleted and the other files are carried along, so "nothing written"
        is checked against every kind of write, not only tags.
        """
        album = builders.library_album(root)
        (album / "album.cue").write_text('FILE "01. Somewhat Damaged.flac" WAVE\n')
        return builders.album_plan(
            root, ALBUM, DESTINATION, builders.retitled_tracks(root, album, DESTINATION),
            images={"cover.jpg": builders.jpeg(700, 700)},
            deletions=[f"{ALBUM}/album.cue", f"{ALBUM}/cover.jpg"],
            kept=[f"{ALBUM}/{name}" for name in ("back.jpg", "booklet.pdf", "rip.log",
                                                  "notes.txt", "lyrics.lrc")])

    def assert_written(self, plan):
        for track in plan.files:
            self.assertTrue((plan.root / track.destination).exists(), track.destination)
            self.assertEqual(files.read(plan.root / track.destination).tags["title"],
                             track.target["title"])


class WhileFoobarRuns(_Library):
    def test_a_root_at_or_under_the_live_library_is_refused_with_the_command_to_stop_it(self):
        # A root inside the live library is as live as the library itself: a
        # guard that compared the two paths for equality would let it through.
        for root in (self.live, self.live / "N"):
            with self.subTest(root=root.relative_to(self.tmp).as_posix()):
                shutil.rmtree(self.live, ignore_errors=True)
                plan = self.plan(root)
                systemctl, calls = self.systemctl("active")
                calls.unlink(missing_ok=True)
                before = builders.tree(self.tmp / "srv")

                with self.assertRaises(write.FoobarRunning) as caught:
                    write.write_album(plan, self.extras, live_root=self.live, systemctl=str(systemctl))

                self.assertIn("sudo systemctl stop foobar2000", str(caught.exception))
                self.assertEqual(builders.tree(self.tmp / "srv"), before)
                self.assertIn("is-active foobar2000", calls.read_text())

    def test_an_inactive_foobar2000_lets_a_write_to_the_live_library_through(self):
        plan = self.plan(self.live)
        systemctl, _ = self.systemctl("inactive")

        write.write_album(plan, self.extras, live_root=self.live, systemctl=str(systemctl))

        self.assert_written(plan)


class OutsideTheLiveLibrary(_Library):
    def test_a_root_elsewhere_is_written_without_asking_systemctl(self):
        # The stub says foobar2000 is running, so a write that goes ahead
        # proves the guard did not apply. `library-old` shares the live root's
        # name as a string prefix but is not inside it.
        for root in (self.tmp / "inbox", self.tmp / "srv" / "music" / "library-old"):
            with self.subTest(root=root.relative_to(self.tmp).as_posix()):
                plan = self.plan(root)
                systemctl, calls = self.systemctl("active")
                calls.unlink(missing_ok=True)

                write.write_album(plan, self.extras, live_root=self.live, systemctl=str(systemctl))

                self.assert_written(plan)
                self.assertFalse(calls.exists(), "systemctl was asked about a root outside the library")


class ThroughASymlink(_Library):
    def test_a_root_and_a_live_library_that_are_one_folder_by_two_paths_are_refused(self):
        # The deploy links /srv/fb2k/Musica to /srv/music/library, so the
        # same albums have two paths. A guard that compares the text of the
        # paths lets a plan rooted at the link write under a running
        # foobar2000. Both directions, since either side can be the link.
        link = self.tmp / "srv" / "fb2k" / "Musica"
        cases = {
            "the plan's root is the link": (link, self.live),
            "the live root given is the link": (self.live, link),
        }
        for case, (root, live_root) in cases.items():
            with self.subTest(case):
                shutil.rmtree(self.tmp / "srv", ignore_errors=True)
                self.live.mkdir(parents=True)
                link.parent.mkdir(parents=True)
                link.symlink_to(self.live, target_is_directory=True)
                plan = self.plan(root)
                systemctl, calls = self.systemctl("active")
                calls.unlink(missing_ok=True)
                before = builders.tree(self.live)

                with self.assertRaises(write.FoobarRunning) as caught:
                    write.write_album(plan, self.extras, live_root=live_root, systemctl=str(systemctl))

                self.assertIn("sudo systemctl stop foobar2000", str(caught.exception))
                self.assertEqual(builders.tree(self.live), before)
                self.assertIn("is-active foobar2000", calls.read_text())


if __name__ == "__main__":
    unittest.main()
