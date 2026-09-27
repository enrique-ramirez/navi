"""`musiclib batch identify`: an album whose collision check raises is held, and the run finishes.

The collision check is the last thing identify does before it writes
`plan.json`, and it is the one step that looks at the disk under every
album's planned destination. A name the filesystem refuses makes that look
raise, and before this was settled one such album stopped the whole run with
nothing written.

The album that fails is one whose planned artist folder is over 255 bytes,
which is what raised on the box. Python 3.13 there raises from
`Path.is_dir()` on such a name, but 3.14 answers `False` for any `OSError`,
so on a newer Python the real name alone would pass without ever testing
anything. `Path.is_dir` is patched to behave as 3.13 does, for over-long
names only. Every other path is looked up for real.

The fakes are `tests.test_batch_identify`'s.
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_batch_identify import Services, album, no_throttle, release, run_identify

FINE = "F/Fine Band/Short [rip]"
LONG = "W/Wordy Band/Pawn [rip]"
#: Planned after LONG, to a folder that already holds another album's files.
#: A fix that stops checking at the first album that raises misses this one.
LATER = "Y/Yonder Band/Moved [rip]"
#: Where LATER's release plans it to.
OCCUPANT = "Y/Yonder Band/(2010) Moved"

#: Over 255 bytes, so the artist folder `names` plans for it is one the
#: filesystem refuses to even look up. An artist folder is never cut to fit
#: (a long album title is), so this stays over the limit whatever `names`
#: does to titles. The rip on disk is filed under a short name, so only the
#: planned destination is too long.
LONG_ARTIST = "Wordy" + " Band" * 55


_real_is_dir = Path.is_dir


def _is_dir_as_on_the_box(path: Path) -> bool:
    """`Path.is_dir` as Python 3.13 answers it: a name over 255 bytes raises rather than answering `False`."""
    if any(len(part.encode()) > 255 for part in path.parts):
        raise OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), str(path))
    return _real_is_dir(path)


class CollisionCheckRaises(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        root = base / "library"
        cls.job = base / ".musiclib" / "jobs" / "j1"
        cls.job.mkdir(parents=True)
        memory = base / ".musiclib" / "memory.json"
        no_throttle(cls)
        patcher = mock.patch.object(Path, "is_dir", _is_dir_as_on_the_box)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        assert len(LONG_ARTIST.encode()) > 255
        catalogue = [release(1, "Fine Band", "Short", ["One", "Two"]),
                     release(2, LONG_ARTIST, "Pawn", ["One", "Two"]),
                     release(3, "Yonder Band", "Moved", ["One", "Two"])]
        for key, (found, _group) in zip((FINE, LONG, LATER), catalogue):
            album(root, key, ["One", "Two"], release_id=found["id"])
        # No release ID, and a search finds nothing, so it stays put, filed
        # under the names LATER's tracks are planned to take.
        occupant = album(root, OCCUPANT, ["One", "Two"])
        for loose in sorted(occupant.glob("0*.flac")):
            number, title = loose.stem.split(" ", 1)
            loose.rename(occupant / f"{number}. {title.title()}.flac")

        cls.code, cls.out, cls.err = run_identify(root, cls.job, memory, Services(catalogue))
        doc = json.loads((cls.job / "plan.json").read_text(encoding="utf-8"))
        cls.albums = {entry["source"]: entry for entry in doc["albums"]}

    def entry(self, key: str) -> dict:
        self.assertIn(key, self.albums, f"{key} is not in plan.json:\n{self.err}")
        return self.albums[key]

    def test_the_run_exits_0_and_writes_plan_json_and_review_html_with_every_album(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertTrue((self.job / "review.html").is_file(), "no review.html in the job")
        self.assertEqual(sorted(self.albums), sorted([FINE, LONG, LATER, OCCUPANT]))

    def test_the_album_whose_destination_the_filesystem_refuses_is_held_with_an_error_naming_it(self):
        held = self.entry(LONG)
        self.assertEqual(held["state"], "held")
        errors = [hold["detail"] for hold in held["holds"] if hold["kind"] == "error"]
        self.assertEqual(len(errors), 1, held["holds"])
        self.assertRegex(errors[0], r"^OSError: .*File name too long")

    def test_an_album_before_it_is_auto_as_if_the_failing_album_were_not_there(self):
        fine = self.entry(FINE)
        self.assertEqual((fine["state"], fine["holds"]), ("auto", []))

    def test_an_album_after_it_is_still_checked_and_held_for_its_own_collision(self):
        later = self.entry(LATER)
        self.assertEqual(later["state"], "held")
        self.assertEqual({hold["kind"] for hold in later["holds"]}, {"collision"}, later["holds"])


if __name__ == "__main__":
    unittest.main()
