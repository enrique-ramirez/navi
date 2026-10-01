"""Planning an album against a release: what refuses a plan before any file is touched.

`test_check` covers a plan that breaks one of the library's rules. Most of
these are the cases where the release, the names it gives or the Cover Art
Archive cannot be planned at all: each has to come back as a plan problem
the owner can read, never as a crash and never as a plan that writes
something wrong. The rest are names that look as if they should fail and
must not: a title too long for a folder, and a title in typographic
punctuation.

The rip, the release and the MusicBrainz half of the fake services are
`test_check`'s. `Archive` adds what the Cover Art Archive half of those
lacks: a back image, a release group with images of its own, and an archive
that answers with an error.

An archive error is no reason to stop planning. The album is planned with
what the archive did give, the cover falls back to the files' embedded
front and then to a folder cover, and one hold names what failed.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from PIL import Image

from musiclib import caa, mb
from musiclib.cache import Cache
from tests import builders
from tests.test_check import (FRONT, FRONT_URL, _names, _Planning, _plan_album, _release, _release_group, _rip,
                              _Services, _snapshot)
from tests.test_names import FIONA, FIONA_FOLDER

BACK = builders.jpeg(640, 480)
BACK_URL = f"https://coverartarchive.org/release/{builders.RELEASE_ID}/2.jpg"


LISTING_URL = f"https://coverartarchive.org/release/{builders.RELEASE_ID}"
GROUP_LISTING_URL = f"https://coverartarchive.org/release-group/{builders.RELEASE_GROUP_ID}"
GROUP_FRONT_URL = f"https://coverartarchive.org/release-group/{builders.RELEASE_GROUP_ID}/9.jpg"


class Archive:
    """MusicBrainz as `test_check._Services` answers it, and a Cover Art Archive this test sets up.

    `images` is `(type, url, bytes)` for each image the archive lists, in
    order. `listing` and `download` are the status the archive gives for the
    release's list and for every image in it: anything but 200 is an error
    the archive answered with, which `caa` raises as `CoverArtError`.
    `statuses` gives one image's URL a status of its own, over `download`.
    `group_images` is the release group's list in the same form, a 404 when
    empty. `requested` is every archive URL asked, in order. Any field may
    change between two plans.
    """

    def __init__(self, release: dict, release_group: dict | None = None, *,
                 images=(("Front", FRONT_URL, FRONT),), listing: int = 200, download: int = 200,
                 statuses: dict[str, int] | None = None, group_images=()):
        self.release_id = release["id"]
        self.musicbrainz = _Services(release, release_group or _release_group(), front=False)
        self.images = list(images)
        self.listing = listing
        self.download = download
        self.statuses = dict(statuses or {})
        self.group_images = list(group_images)
        self.requested: list[str] = []

    @staticmethod
    def _listing(images) -> bytes:
        return json.dumps({"images": [
            {"id": n, "types": [kind], "front": kind == "Front", "back": kind == "Back",
             "image": image_url, "thumbnails": {}}
            for n, (kind, image_url, _data) in enumerate(images, start=1)]}).encode()

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc != "coverartarchive.org":
            return self.musicbrainz(url, headers)
        self.requested.append(url)
        if parts.path.rstrip("/") == f"/release/{self.release_id}":
            if self.listing != 200:
                return self.listing, b"Internal Server Error"
            if not self.images:
                return 404, b"Not Found"
            return 200, self._listing(self.images)
        if parts.path.rstrip("/") == f"/release-group/{builders.RELEASE_GROUP_ID}":
            return (200, self._listing(self.group_images)) if self.group_images else (404, b"Not Found")
        for _kind, image_url, data in [*self.images, *self.group_images]:
            if url == image_url:
                status = self.statuses.get(url, self.download)
                return (200, data) if status == 200 else (status, b"Bad Gateway")
        return 404, b"Not Found"


def plan_with(tmp: Path, unit, release: dict, services, *, cache: Cache | None = None, **kwargs):
    """`plan_album` against `services`, through `cache`, else a cache of its own under `tmp`."""
    cache = cache or Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=tmp)))
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

    def test_a_title_over_255_bytes_is_planned_with_a_cut_name_and_one_of_exactly_255_is_not_cut(self):
        # ext4 on the box takes 255 bytes a name, whatever the characters.
        # The titles are three-byte characters, so every one of these names
        # is well under 255 characters: a cut that counts characters leaves
        # them all whole. They have no spaces, so the cut is by character.
        wide = "交"  # three bytes in UTF-8
        exactly = wide * 82  # "01. " + 246 bytes + ".flac" is 255 bytes
        over = wide * 83  # 258 bytes as a file name, 256 as "(2010) " and the title
        self.assertEqual(len(f"01. {exactly}.flac".encode()), 255)
        album_dir = "C/Cure, The/(2010) Disintegration"
        cases = {
            # 80 characters are 240 bytes, and "01. ", " [...]" and ".flac" make 255.
            "a track title": ("track", over, f"{album_dir}/01. {wide * 80} [...].flac"),
            # "(2010) " and " [...]" leave 242 bytes, and 80 characters take 240.
            "an album title": ("album", over, f"C/Cure, The/(2010) {wide * 80} [...]/01. Plainsong.flac"),
            "a track name of exactly 255 bytes": ("track", exactly, f"{album_dir}/01. {exactly}.flac"),
        }
        for case, (where, title, first_destination) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"])
                if where == "track":
                    release = _release([title, "Pictures of You"])
                else:
                    release = _release(["Plainsong", "Pictures of You"], title=title)

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

                self.assertEqual(list(plan.problems), [])
                first = next(f for f in plan.files if PurePosixPath(str(f.source)).name == "01 plainsong.flac")
                self.assertEqual(str(first.destination), first_destination)
                key = "title" if where == "track" else "album"
                self.assertEqual(first.target[key], [title])

    def test_an_artist_folder_over_255_bytes_is_still_refused(self):
        artist = "交" * 86  # 258 bytes
        credit = builders.mb_credit("1a0b0c0d-0000-4000-8000-0000000000b1", artist, artist)
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        release = _release(["Plainsong", "Pictures of You"], credit=credit)
        before = _snapshot(root)

        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

        said = [p for p in plan.problems if "too long for a file name" in p]
        self.assertTrue(said, f"no problem says the artist folder is too long: {plan.problems}")
        self.assertRefused(plan, said[0], root, before)


#: Fiona Apple's 1999 album as MusicBrainz gives it. Every apostrophe in the
#: title is a right single quotation mark there, so this is `FIONA` with
#: each one put back.
FIONA_AS_MUSICBRAINZ = FIONA.replace("'", "\u2019")
FIONA_CREDIT = builders.mb_credit("1a0b0c0d-0000-4000-8000-0000000000b2", "Fiona Apple", "Apple, Fiona")


class ALongTitle(_Planning):
    def test_fiona_apples_when_the_pawn_is_planned_to_criterion_46s_folder_with_its_full_title_in_the_tag(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        release = _release(["Plainsong", "Pictures of You"], title=FIONA_AS_MUSICBRAINZ,
                           credit=FIONA_CREDIT, date="1999-11-09")

        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), f"F/Fiona Apple/{FIONA_FOLDER}")
        for file_plan in plan.files:
            self.assertEqual(file_plan.target["album"], [FIONA])


class NamesFromConvertedText(_Planning):
    """Folders are built from the same converted text as the tag, so each agrees with the other.

    A folder built from MusicBrainz's raw text keeps a curly quote the tag
    beside it has lost, and `check` then reads the two as disagreeing.
    """

    def plan_release(self, **changes):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        release = _release(["Plainsong", "Pictures of You"], **changes)
        return plan_with(self.tmp, self.unit(root, album), release, Archive(release), status="auto")

    def test_the_cures_hell_win_lands_in_a_folder_with_a_straight_apostrophe(self):
        plan = self.plan_release(title="He\u2019ll Win")
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), "C/Cure, The/(2010) He'll Win")

    def test_every_converted_character_in_the_album_title_reaches_the_folder_converted(self):
        cases = {
            "\u2018": "A'B", "\u2019": "A'B", "\u201c": "A''B", "\u201d": "A''B", "\u2026": "A...B",
            "\u2010": "A-B", "\u2013": "A-B", "\u2014": "A-B",
        }
        for char, folder_title in cases.items():
            with self.subTest(f"U+{ord(char):04X}"):
                plan = self.plan_release(title=f"A{char}B")
                self.assertEqual(list(plan.problems), [])
                self.assertEqual(str(plan.destination), f"C/Cure, The/(2010) {folder_title}")

    def test_a_title_ending_in_an_ellipsis_gets_a_folder_with_no_trailing_dots(self):
        # The tag ends `...`, and the character table drops trailing full
        # stops. The raw `\u2026` is no full stop, so a folder built from it
        # keeps it and disagrees with its tag.
        plan = self.plan_release(title="Wait\u2026")
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), "C/Cure, The/(2010) Wait")
        self.assertEqual(plan.files[0].target["album"], ["Wait..."])

    def test_guns_n_roses_gets_an_artist_folder_with_a_straight_apostrophe(self):
        credit = builders.mb_credit("1a0b0c0d-0000-4000-8000-0000000000b3",
                                    "Guns N\u2019 Roses", "Guns N\u2019 Roses")
        plan = self.plan_release(credit=credit)
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), "G/Guns N' Roses/(2010) Disintegration")

    def test_the_artist_folder_takes_the_converted_name_and_the_converted_sort_name(self):
        # Converting the name and not the sort name (or the other way round)
        # would make them differ, and the folder would fall back to `The A'B`.
        cases = {
            "\u2018": "A'B", "\u2019": "A'B", "\u201c": "A''B", "\u201d": "A''B", "\u2026": "A...B",
            "\u2010": "A-B", "\u2013": "A-B", "\u2014": "A-B",
        }
        for char, folder_name in cases.items():
            with self.subTest(f"U+{ord(char):04X}"):
                credit = builders.mb_credit("1a0b0c0d-0000-4000-8000-0000000000b4",
                                            f"The A{char}B", f"A{char}B, The")
                plan = self.plan_release(credit=credit)
                self.assertEqual(list(plan.problems), [])
                self.assertEqual(str(plan.destination), f"A/{folder_name}, The/(2010) Disintegration")


UNAVAILABLE = "cover art archive unavailable:"
NO_COVER_ARCHIVE_FAILED = ("no cover: the cover art archive is unavailable and the files carry none; "
                           "upload a cover or identify again")
NO_COVER_NO_FRONT = "no cover: the cover art archive has no front and the files carry none; upload a cover"

#: Every picture below is square and at least 500 px unless its name says
#: otherwise, so it passes the cover test and no `cover: neither passes`
#: hold joins the one under test. Each has a colour of its own, so a plan
#: that takes the wrong one shows.
ARCHIVE_FRONT = builders.picture(1200, 1200, (200, 30, 30))
EMBEDDED = builders.picture(500, 500, (30, 200, 30))
FOLDER = builders.picture(600, 600, (30, 30, 200))
OWNER = builders.picture(700, 700, (200, 200, 30))
GROUP_FRONT = builders.picture(800, 800, (30, 200, 200))
ARCHIVE_IMAGES = (("Front", FRONT_URL, ARCHIVE_FRONT), ("Back", BACK_URL, BACK))
TITLES = ["Plainsong", "Pictures of You"]
#: Which picture is which, for a failure message a person can read.
_KNOWN = {ARCHIVE_FRONT: "ARCHIVE_FRONT", EMBEDDED: "EMBEDDED", FOLDER: "FOLDER", OWNER: "OWNER",
          GROUP_FRONT: "GROUP_FRONT", BACK: "BACK"}


def _shown(images: dict[str, bytes]) -> dict[str, str]:
    """`images` with each picture named as `_KNOWN` names it, else by its digest."""
    return {name: _KNOWN.get(data, f"sha256 {hashlib.sha256(data).hexdigest()[:16]}") for name, data in images.items()}


class Failure:
    """One way the archive fails, the rip it fails on, and what the plan makes of it."""

    def __init__(self, archive: dict, failed: dict[str, str], cover: str, images: dict[str, bytes], *,
                 embedded: bytes | None = None, folder: tuple[str, bytes] | None = None):
        self.archive = archive
        self.failed = failed
        self.cover = cover
        self.images = images
        self.embedded = embedded
        self.folder = folder


#: Each way the archive fails, and the cover the plan falls back to.
FAILURES = {
    # The embedded front beats `folder.jpg` here, as it does when the archive answers.
    "the release's list answers 500": Failure(
        dict(listing=500), {LISTING_URL: "500"}, "the files' embedded front", {"cover.jpg": EMBEDDED},
        embedded=EMBEDDED, folder=("folder.jpg", FOLDER)),
    "the front answers 502": Failure(
        dict(statuses={FRONT_URL: 502}), {FRONT_URL: "502"}, "the folder's folder.jpg",
        {"cover.jpg": FOLDER, "back.jpg": BACK}, folder=("folder.jpg", FOLDER)),
    "the back answers 500": Failure(
        dict(statuses={BACK_URL: 500}), {BACK_URL: "500"}, "the archive's front", {"cover.jpg": ARCHIVE_FRONT}),
    # Two failures in one plan: a hold built from the first alone shows here.
    "the front answers 502 and the back 500": Failure(
        dict(statuses={FRONT_URL: 502, BACK_URL: 500}), {FRONT_URL: "502", BACK_URL: "500"},
        "the folder's folder.jpg", {"cover.jpg": FOLDER}, folder=("folder.jpg", FOLDER)),
}


def _rip_with(root: Path, titles=TITLES, *, embedded: bytes | None = None,
              folder: tuple[str, bytes] | None = None) -> Path:
    """`_rip` with no `cover.jpg`, `embedded` as the front of every track and `folder` as `(name, bytes)`."""
    album = _rip(root, titles, cover=False)
    if embedded is not None:
        for track in sorted(album.glob("*.flac")):
            builders.embed_picture(track, embedded)
    if folder is not None:
        (album / folder[0]).write_bytes(folder[1])
    return album


def _naming(url: str, status: str) -> re.Pattern:
    """`url` followed by `status`, whatever punctuation joins them.

    The release's list is a prefix of each image's URL; the status must come
    straight after the URL, so the list is not taken as named by an image's
    failure.
    """
    return re.compile(re.escape(url) + r"\W{1,6}" + re.escape(status) + r"\b")


class _Fallback(_Planning):
    def the_archive_hold(self, plan) -> str:
        """The one hold that says the archive is unavailable; fails when there is none or more than one."""
        said = [hold for hold in plan.holds if hold.startswith(UNAVAILABLE)]
        self.assertEqual(len(said), 1, f"not one {UNAVAILABLE!r} hold: holds {plan.holds}, problems {plan.problems}")
        return said[0]

    def assertNoArchiveHold(self, plan):
        self.assertEqual([h for h in [*plan.holds, *plan.problems] if UNAVAILABLE in h], [])

    def plan_failure(self, failure: Failure, archive: dict | None = None, **kwargs):
        root = self.library()
        album = _rip_with(root, embedded=failure.embedded, folder=failure.folder)
        release = _release(TITLES)
        services = Archive(release, images=ARCHIVE_IMAGES, **(failure.archive if archive is None else archive))
        return plan_with(self.tmp, self.unit(root, album), release, services, status="auto", **kwargs)


class AnArchiveThatFails(_Fallback):
    def test_still_plans_every_tag_move_and_fetched_image_as_on_a_day_it_answers(self):
        # A plan that dropped the whole image plan, or refused the album, would show as a
        # problem or as missing files.
        for case, failure in FAILURES.items():
            with self.subTest(case):
                plan = self.plan_failure(failure)
                answering = self.plan_failure(failure, archive={})

                self.assertEqual(list(plan.problems), [])
                self.assertTrue(plan.files)
                self.assertEqual([(f.source, f.destination, f.target) for f in plan.files],
                                 [(f.source, f.destination, f.target) for f in answering.files])
                self.assertEqual(plan.destination, answering.destination)
                self.assertEqual(_shown(plan.images), _shown(failure.images))

    def test_one_hold_names_each_failed_request_with_its_status_and_says_what_the_cover_is(self):
        for case, failure in FAILURES.items():
            with self.subTest(case):
                hold = self.the_archive_hold(self.plan_failure(failure))

                for url, status in failure.failed.items():
                    self.assertRegex(hold, _naming(url, status))
                self.assertIn(failure.cover, hold)
                # Only what failed is named: the image that answered is not.
                for url in {FRONT_URL, BACK_URL} - set(failure.failed):
                    self.assertNotIn(url, hold)

    def test_a_plan_asked_for_as_auto_is_review_and_the_archive_hold_blocks_nothing(self):
        # Each case's only hold is the archive's, so it
        # alone turns `auto` to `review`. A hold is a `validation` hold to
        # agitha and does not stop an accepted album; a problem would.
        for case, failure in FAILURES.items():
            with self.subTest(case):
                plan = self.plan_failure(failure)

                self.assertEqual(plan.holds, [self.the_archive_hold(plan)])
                self.assertEqual(list(plan.problems), [])
                self.assertEqual(plan.status, "review")

    def test_a_release_list_answering_500_plans_no_archive_image_and_never_asks_the_release_group(self):
        # The group has a front of its own, so a plan that
        # asks it in the release's place takes that front as the cover.
        cases = {
            "the release's list answers 500": (500, {"cover.jpg": EMBEDDED}),
            # The fake's group is real: with the release's list a 404, it is asked and its front is the cover.
            "the release's list answers 404": (404, {"cover.jpg": GROUP_FRONT}),
        }
        for case, (listing, images) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip_with(root, embedded=EMBEDDED)
                release = _release(TITLES)
                group = (("Front", GROUP_FRONT_URL, GROUP_FRONT),)
                services = Archive(release, images=() if listing == 404 else ARCHIVE_IMAGES,
                                   listing=200 if listing == 404 else listing, group_images=group)

                plan = plan_with(self.tmp, self.unit(root, album), release, services, status="auto")

                self.assertEqual(_shown(plan.images), _shown(images))
                if listing == 500:
                    self.assertEqual([url for url in services.requested if url != LISTING_URL], [])
                else:
                    self.assertIn(GROUP_LISTING_URL, services.requested)

    def test_with_no_cover_anywhere_the_problem_says_whether_the_archive_failed_or_has_no_front(self):
        cases = {
            "the release's list answers 500": (dict(listing=500), NO_COVER_ARCHIVE_FAILED),
            "the front answers 500": (dict(statuses={FRONT_URL: 500}), NO_COVER_ARCHIVE_FAILED),
            "the release and its group have no images": (dict(images=()), NO_COVER_NO_FRONT),
            "the release has only a back": (dict(images=(("Back", BACK_URL, BACK),)), NO_COVER_NO_FRONT),
        }
        for case, (archive, sentence) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip_with(root)
                release = _release(TITLES)
                before = _snapshot(root)
                services = Archive(release, **{"images": ARCHIVE_IMAGES, **archive})

                plan = plan_with(self.tmp, self.unit(root, album), release, services, status="auto")

                self.assertIn(sentence, plan.problems)
                self.assertNotIn("cover.jpg", plan.images)
                self.assertEqual([p for p in plan.problems if p.startswith("no front cover")], [])
                if sentence == NO_COVER_NO_FRONT:
                    self.assertNoArchiveHold(plan)
                self.assertRefused(plan, sentence, root, before)


class TheFilesEmbeddedFront(_Fallback):
    def test_with_no_archive_front_the_embedded_front_is_the_cover_and_a_folder_cover_stays_where_it_is(self):
        for name in ("folder.jpg", "album.jpg", "art.jpg"):
            with self.subTest(name):
                root = self.library()
                album = _rip_with(root, embedded=EMBEDDED, folder=(name, FOLDER))
                release = _release(TITLES)

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()),
                                 status="auto")

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(_shown(plan.images), _shown({"cover.jpg": EMBEDDED}))
                self.assertIsNone(plan.consumed)
                self.assertNotIn(name, _names(plan.deletions))
                self.assertIn(name, _names(plan.kept))

    def test_with_no_archive_front_the_embedded_front_replaces_a_folder_cover_jpg(self):
        root = self.library()
        album = _rip_with(root, embedded=EMBEDDED, folder=("cover.jpg", FOLDER))
        release = _release(TITLES)

        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()), status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(_shown(plan.images), _shown({"cover.jpg": EMBEDDED}))

    def test_the_embedded_front_is_the_first_front_picture_of_the_first_track_in_plan_order_that_has_a_picture(self):
        # Track 1 has no picture. The files are named so their
        # name order (track 3, 1, 2) is not the plan's (1, 2, 3): a plan that
        # reads the folder in name order takes track 3's front.
        front_2, front_3 = builders.picture(500, 500, (90, 10, 10)), builders.picture(500, 500, (10, 90, 10))
        other, another = builders.picture(500, 500, (10, 10, 90)), builders.picture(500, 500, (90, 90, 10))
        cases = {
            # The front comes second in its track, so a plan taking the first picture shows.
            "track 2 carries a back and then a front": ([(4, other), (3, front_2)], front_2),
            "track 2 carries no front": ([(4, other), (5, another)], other),
        }
        for case, (track_2, expected) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You", "Closedown"], cover=False)
                renamed = {}
                for old, new in (("01 plainsong.flac", "m plainsong.flac"),
                                 ("02 pictures of you.flac", "s pictures of you.flac"),
                                 ("03 closedown.flac", "a closedown.flac")):
                    renamed[old] = (album / old).rename(album / new)
                for kind, data in track_2:
                    builders.embed_picture(renamed["02 pictures of you.flac"], data, picture_type=kind)
                builders.embed_picture(renamed["03 closedown.flac"], front_3)
                release = _release(["Plainsong", "Pictures of You", "Closedown"])

                plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()),
                                 status="auto")

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(_shown(plan.images), _shown({"cover.jpg": expected}))

    def test_an_embedded_png_becomes_a_jpeg_cover_of_the_same_picture(self):
        colour = (180, 60, 20)
        root = self.library()
        album = _rip_with(root)
        for track in sorted(album.glob("*.flac")):
            builders.embed_picture(track, builders.picture(600, 600, colour, "PNG"), mime="image/png")
        release = _release(TITLES)

        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()), status="auto")

        self.assertEqual(list(plan.problems), [])
        cover = plan.images.get("cover.jpg")
        self.assertIsNotNone(cover, "no cover.jpg planned")
        with Image.open(io.BytesIO(cover)) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (600, 600)))
            pixel = image.convert("RGB").getpixel((300, 300))
        self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(pixel, colour)), pixel)

    def test_waking_up_whose_front_answers_500_plans_the_500_px_front_every_flac_carries(self):
        failure = Failure(dict(statuses={FRONT_URL: 500}), {FRONT_URL: "500"}, "the files' embedded front",
                          {"cover.jpg": EMBEDDED, "back.jpg": BACK}, embedded=EMBEDDED)

        plan = self.plan_failure(failure)

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(_shown(plan.images), _shown(failure.images))
        self.assertEqual(plan.embedded, EMBEDDED)
        self.assertIn("the files' embedded front", self.the_archive_hold(plan))

    def test_a_300_px_embedded_front_is_the_cover_with_no_hold_of_its_own(self):
        small = builders.picture(300, 300, (120, 20, 120))
        root = self.library()
        album = _rip_with(root, embedded=small)
        release = _release(TITLES)

        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()), status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(plan.holds, [])
        self.assertEqual(_shown(plan.images), _shown({"cover.jpg": small}))

    def test_given_the_original_folders_covers_the_embedded_front_is_never_the_cover(self):
        # The re-judge path: `local` stands in for the folder's covers, and the
        # files' pictures are not a candidate. This seam sees only the outcome,
        # not whether the pictures were read.
        cases = {
            "the archive has no front": dict(images=()),
            "the release's list answers 500": dict(listing=500),
        }
        for case, archive in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip_with(root, embedded=EMBEDDED)
                release = _release(TITLES)

                plan = plan_with(self.tmp, self.unit(root, album), release,
                                 Archive(release, **{"images": ARCHIVE_IMAGES, **archive}),
                                 status="auto", local=[("cover.jpg", FOLDER)])

                self.assertEqual(_shown(plan.images).get("cover.jpg"), "FOLDER")


class TheArchiveAnsweringAgain(_Fallback):
    def test_identify_again_takes_the_archives_front_and_drops_the_hold_but_never_replaces_the_owners(self):
        # One cache for both plans, as on the box: the failed
        # front was never cached, so the second plan asks it again.
        cases = {
            "the embedded front stood in": (None, EMBEDDED, "the files' embedded front", ARCHIVE_FRONT),
            "the owner's cover": (OWNER, OWNER, "the owner's", OWNER),
        }
        for case, (owner, first_cover, phrase, second_cover) in cases.items():
            with self.subTest(case):
                root = self.library()
                album = _rip_with(root, embedded=EMBEDDED)
                release = _release(TITLES)
                services = Archive(release, images=ARCHIVE_IMAGES, statuses={FRONT_URL: 500})
                cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
                unit = self.unit(root, album)

                failed = plan_with(self.tmp, unit, release, services, cache=cache, status="auto", owner_cover=owner)
                self.assertEqual(_shown(failed.images).get("cover.jpg"), _KNOWN[first_cover])
                self.assertIn(phrase, self.the_archive_hold(failed))

                services.statuses = {}
                answered = plan_with(self.tmp, unit, release, services, cache=cache, status="auto", owner_cover=owner)
                self.assertEqual(_shown(answered.images), _shown({"cover.jpg": second_cover, "back.jpg": BACK}))
                self.assertNoArchiveHold(answered)
                self.assertEqual(answered.holds, [])
                self.assertEqual(answered.status, "auto")


class TheFolderCoverJpgAsTheSamePicture(_Fallback):
    """With no fetched archive front, the folder's own `cover.jpg` stays the cover over the files' front.

    Only where it is the same picture and its shorter side is at least the
    embedded front's: an applied album embeds a 1200 px copy of the `cover.jpg`
    beside it, and replacing the full-size file with its own copy loses pixels.
    Any other folder cover, or a smaller `cover.jpg`, loses to the embedded
    front and stays where it is. Every picture here is the same
    two-tone one at different sizes, so a same-picture test passes each pair.
    """

    def plan_folder(self, folder: tuple[str, bytes], embedded: bytes):
        root = self.library()
        album = _rip_with(root, embedded=embedded, folder=folder)
        release = _release(TITLES)
        return plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=()), status="auto")

    def test_a_cover_jpg_at_least_as_large_as_its_embedded_copy_stays_the_cover_byte_for_byte(self):
        cases = {
            "3000 px beside a 1200 px copy": (builders.two_tone(3000, 3000), builders.two_tone(1200, 1200)),
            # The boundary. The copy is a PNG, so the plan's JPEG of it differs
            # from the folder's bytes and a plan that takes it shows.
            "1200 px beside a 1200 px copy": (builders.two_tone(1200, 1200), builders.two_tone(1200, 1200, "PNG")),
        }
        for case, (folder, embedded) in cases.items():
            with self.subTest(case):
                plan = self.plan_folder(("cover.jpg", folder), embedded)

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(_shown(plan.images), _shown({"cover.jpg": folder}))

    def test_a_smaller_cover_jpg_or_any_other_folder_cover_of_the_same_picture_loses_to_the_embedded_front(self):
        embedded = builders.two_tone(500, 500)
        cases = {
            # Smaller than the embedded front: the size rule decides it.
            "a 200 px Folder.jpg": ("Folder.jpg", builders.two_tone(200, 200)),
            "a 300 px cover.jpg": ("cover.jpg", builders.two_tone(300, 300)),
            # Larger than the embedded front: only the name decides it.
            "a 1000 px album.jpg": ("album.jpg", builders.two_tone(1000, 1000)),
        }
        for case, (name, data) in cases.items():
            with self.subTest(case):
                plan = self.plan_folder((name, data), embedded)

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(_shown(plan.images), _shown({"cover.jpg": embedded}))
                if name != "cover.jpg":
                    self.assertIsNone(plan.consumed)
                    self.assertIn(name, _names(plan.kept))


NOT_AN_IMAGE = b"<html><body>Service Temporarily Unavailable</body></html>"


class AFrontThatIsNotAnImage(_Fallback):
    """The archive's front answered 200 with bytes no image reader opens: a failed front, as a 500 is.

    The cover falls back as it does for a failed download, the hold names the front,
    and nothing blocks the album unless no cover is left.
    """

    def plan_front(self, *, embedded: bytes | None = None, folder: tuple[str, bytes] | None = None):
        root = self.library()
        album = _rip_with(root, embedded=embedded, folder=folder)
        release = _release(TITLES)
        before = _snapshot(root)
        images = (("Front", FRONT_URL, NOT_AN_IMAGE), ("Back", BACK_URL, BACK))
        plan = plan_with(self.tmp, self.unit(root, album), release, Archive(release, images=images), status="auto")
        return plan, root, before

    def test_the_embedded_front_is_the_cover_and_the_hold_names_the_front(self):
        # `folder.jpg` is there too: the embedded front comes before it.
        plan, _root, _before = self.plan_front(embedded=EMBEDDED, folder=("folder.jpg", FOLDER))

        self.assertEqual(_shown(plan.images), _shown({"cover.jpg": EMBEDDED, "back.jpg": BACK}))
        self.assertEqual(list(plan.problems), [])
        hold = self.the_archive_hold(plan)
        self.assertIn(FRONT_URL, hold)
        self.assertIn("the files' embedded front", hold)

    def test_with_no_embedded_front_a_folder_cover_is_the_cover(self):
        plan, _root, _before = self.plan_front(folder=("folder.jpg", FOLDER))

        self.assertEqual(_shown(plan.images), _shown({"cover.jpg": FOLDER, "back.jpg": BACK}))
        self.assertEqual(list(plan.problems), [])
        self.assertIn("the folder's folder.jpg", self.the_archive_hold(plan))

    def test_with_no_cover_anywhere_the_problem_is_the_archive_unavailable_sentence(self):
        plan, root, before = self.plan_front()

        self.assertIn(NO_COVER_ARCHIVE_FAILED, plan.problems)
        self.assertEqual([p for p in plan.problems if p.startswith("no cover") and p != NO_COVER_ARCHIVE_FAILED], [])
        self.assertIn(FRONT_URL, self.the_archive_hold(plan))
        self.assertRefused(plan, NO_COVER_ARCHIVE_FAILED, root, before)


if __name__ == "__main__":
    unittest.main()
