"""Planning an album against a release: what refuses a plan before any file is touched.

Criteria 6, 18, 25, 26 and 29. `test_check` covers a plan that breaks one of
the library's rules. These are the cases where the release, the names it
gives or the Cover Art Archive cannot be planned at all: each has to come
back as a plan problem the owner can read, never as a crash and never as a
plan that writes something wrong.

The rip, the release and the MusicBrainz half of the fake services are
`test_check`'s. `Archive` adds what the Cover Art Archive half of those
lacks: a back image, and an archive that answers with an error.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from musiclib import caa, mb
from musiclib.cache import Cache
from tests import builders
from tests.test_check import (FRONT, FRONT_URL, _Planning, _plan_album, _release, _release_group, _rip,
                              _Services, _snapshot)

BACK = builders.jpeg(640, 480)
BACK_URL = f"https://coverartarchive.org/release/{builders.RELEASE_ID}/2.jpg"


class Archive:
    """MusicBrainz as `test_check._Services` answers it, and a Cover Art Archive this test sets up.

    `images` is `(type, url, bytes)` for each image the archive lists, in
    order. `listing` and `download` are the status the archive gives for the
    release's list and for every image in it: anything but 200 is an error
    the archive answered with, which `caa` raises as `CoverArtError`.
    """

    def __init__(self, release: dict, release_group: dict | None = None, *,
                 images=(("Front", FRONT_URL, FRONT),), listing: int = 200, download: int = 200):
        self.release_id = release["id"]
        self.musicbrainz = _Services(release, release_group or _release_group(), front=False)
        self.images = list(images)
        self.listing = listing
        self.download = download

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc != "coverartarchive.org":
            return self.musicbrainz(url, headers)
        if parts.path.rstrip("/") == f"/release/{self.release_id}":
            if self.listing != 200:
                return self.listing, b"Internal Server Error"
            if not self.images:
                return 404, b"Not Found"
            listing = {"images": [
                {"id": n, "types": [kind], "front": kind == "Front", "back": kind == "Back",
                 "image": image_url, "thumbnails": {}}
                for n, (kind, image_url, _data) in enumerate(self.images, start=1)]}
            return 200, json.dumps(listing).encode()
        for _kind, image_url, data in self.images:
            if url == image_url:
                return (200, data) if self.download == 200 else (self.download, b"Bad Gateway")
        return 404, b"Not Found"


def plan_with(tmp: Path, unit, release: dict, services, **kwargs):
    """`plan_album` against `services`, through a cache of its own under `tmp`."""
    cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=tmp)))
    client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
    art = caa.CoverArt(cache, transport=services)
    return _plan_album(unit, release, client, art, **kwargs)


def _numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"(?<![\w.])\d+(?![\w.])", text)}


class TheExistingCover(_Planning):
    def test_a_cover_jpg_in_any_case_is_the_cover_kept_when_the_archive_has_no_front(self):
        # A rip from Windows often carries `Cover.jpg`. The box's disk tells
        # the cases apart, so a plan that looks only for `cover.jpg` finds no
        # cover there and fails an album that has one. This disk may not:
        # run it with TMPDIR on a case-sensitive volume to see it bite.
        for name in ("Cover.jpg", "COVER.JPG"):
            with self.subTest(name):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"], cover=False)
                own = builders.jpeg(500, 500)
                (album / name).write_bytes(own)
                release = _release(["Plainsong", "Pictures of You"])

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()),
                                 status="auto")

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(plan.images.get("cover.jpg"), own)


class AReleaseThatDoesNotFit(_Planning):
    def test_file_counts_that_differ_from_the_release_are_refused_naming_both_counts(self):
        # A release picked by URL is never checked against the files, so a
        # plan has to be. More files than tracks crashed the planner, and
        # fewer tagged every file as a track of a release it only partly is.
        # The last case has the same total on both sides, so a check of
        # totals alone lets it through.
        cases = {
            "4 files, 3 tracks": ([["A", "B", "C", "D"]], [["A", "B", "C"]]),
            "2 files, 5 tracks": ([["A", "B"]], [["A", "B", "C", "D", "E"]]),
            "3+1 files, 3+2 tracks": ([["A", "B", "C"], ["D"]], [["A", "B", "C"], ["D", "E"]]),
            "3 files on 1 medium, 2+1 tracks on 2": ([["A", "B", "C"]], [["A", "B"], ["C"]]),
        }
        for case, (on_disk, media) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip(root, *on_disk)
                release = _release(*media)
                before = _snapshot(root)

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

                counts = {len(titles) for titles in on_disk} | {len(titles) for titles in media}
                said = [p for p in plan.problems if counts <= _numbers(p)]
                self.assertTrue(said, f"no problem names the counts {sorted(counts)}: {plan.problems}")
                self.assertEqual(list(plan.files), [])
                self.assertRefused(plan, said[0], root, before)

    def test_a_destination_name_over_255_bytes_is_refused_and_one_of_exactly_255_is_not(self):
        # ext4 on the box takes 255 bytes a name, whatever the characters.
        # The titles are three-byte characters, so every one of these names
        # is well under 255 characters: a check that counts characters
        # passes them all.
        wide = "交"  # 交, three bytes in UTF-8
        exactly = wide * 82  # "01. " + 246 bytes + ".flac" is 255 bytes
        over = wide * 83  # 258 bytes as a file name, 256 as "(2010) " and the title
        cases = {
            "a track title": ("track", over, True),
            "an album title": ("album", over, True),
            "a track name of exactly 255 bytes": ("track", exactly, False),
        }
        for case, (where, title, refused) in cases.items():
            with self.subTest(case):
                self.assertEqual(len(f"01. {exactly}.flac".encode()), 255)
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"])
                if where == "track":
                    release = _release([title, "Pictures of You"])
                else:
                    release = _release(["Plainsong", "Pictures of You"], title=title)
                before = _snapshot(root)

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

                said = [p for p in plan.problems if "255" in p or "too long" in p.casefold()]
                if not refused:
                    self.assertEqual(said, [])
                    continue
                self.assertTrue(said, f"no problem says a name is too long: {plan.problems}")
                self.assertRefused(plan, said[0], root, before)


class ACoverArtArchiveError(_Planning):
    def test_becomes_a_plan_problem_and_the_write_is_refused(self):
        # A 500 from the archive is not "this release has no images": taking
        # it as that would keep the rip's cover and write the album as done.
        # A 404 is the archive saying it has none, and is not an error.
        cases = {
            "the release's list answers 500": dict(listing=500),
            "the front image answers 502": dict(download=502),
        }
        for case, archive in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"])
                release = _release(["Plainsong", "Pictures of You"])
                before = _snapshot(root)

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, **archive),
                                 status="auto")

                said = [p for p in plan.problems if "cover art archive unavailable" in p.casefold()]
                self.assertTrue(said, f"no problem says the archive is unavailable: {plan.problems}")
                self.assertRefused(plan, said[0], root, before)


if __name__ == "__main__":
    unittest.main()
