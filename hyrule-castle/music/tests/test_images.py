"""Album images and the embedded cover, from spec criteria 25, 26 and 27, and the front's fallbacks.

`tests/fixtures/caa/release.json` is written in the shape the Cover Art
Archive returns for a release. Its list order is chosen so that sorting by
id, counting a type before skipping, or looking only at the first type all
give the wrong names. The image bytes are generated here with Pillow.

Where the front comes from when the release has none, and what a download
that is not an image does, are judged through `plan_album` against a rip
from `tests.test_check`, so they hold whatever `plan_images` is handed.
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import struct
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from PIL import Image, ImageDraw

from musiclib import caa, check, images, mb
from musiclib.batch.identify import Clients, plan_entry, rebuild
from musiclib.cache import Cache
from musiclib.units import pair, position_key
from tests import builders
from tests.test_check import (_names, _Planning, _plan_album, _release, _release_group, _rip, _Services,
                              _write_album)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RELEASE = json.loads((FIXTURES / "caa" / "release.json").read_text())
CAA_IMAGES = RELEASE["images"]
RELEASE_MBID = "7b1d3a58-2c4e-4f6a-9b8d-0e1f2a3b4c5d"
COVER = (FIXTURES / "cover.jpg").read_bytes()  # 1600 x 900
FORMATS = ("mp3", "flac", "ogg", "m4a")


def by_id(image_id: int) -> dict:
    return next(i for i in CAA_IMAGES if i["id"] == image_id)


def png(width: int, height: int, colour: tuple[int, int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(out, "PNG")
    return out.getvalue()


def two_tone(width: int, height: int) -> bytes:
    """Red on the left half, blue on the right, so a resize can be told from a blank."""
    image = Image.new("RGB", (width, height), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, width // 2, height))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


def size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def is_jpeg(data: bytes) -> bool:
    return Image.open(io.BytesIO(data)).format == "JPEG"


# One distinct JPEG per image, so a name holding the wrong image shows. The
# spine is a PNG, which has to be converted.
BODIES = {i["image"]: builders.jpeg(100 + n, 50 + n) for n, i in enumerate(CAA_IMAGES)}
BODIES[by_id(1010)["image"]] = png(64, 32, (0, 128, 0, 255))


def download(url: str) -> bytes:
    return BODIES[url]


def pictures(path: Path) -> list[tuple[int, str, bytes]]:
    """Every embedded picture, read with mutagen rather than the code under test.

    M4A has no picture types; a `covr` is a front cover there, and its
    `mime` is `image/jpeg` when the atom says JPEG.
    """
    ext = path.suffix.lstrip(".")
    if ext == "mp3":
        return [(f.type, f.mime, f.data) for f in ID3(path).getall("APIC")]
    if ext == "m4a":
        return [
            (3, "image/jpeg" if c.imageformat == MP4Cover.FORMAT_JPEG else "other", bytes(c))
            for c in MP4(path).get("covr", [])
        ]
    audio = FLAC(path) if ext == "flac" else OggVorbis(path)
    found = [(p.type, p.mime, p.data) for p in getattr(audio, "pictures", [])]
    for block in (audio.tags or {}).get("metadata_block_picture", []):
        p = Picture(base64.b64decode(block))
        found.append((p.type, p.mime, p.data))
    return found


TITLE_KEY = {"mp3": "TIT2", "flac": "title", "ogg": "title", "m4a": "\xa9nam"}


class Transport:
    """Answers by URL path, records every request, and fails on anything unplanned."""

    def __init__(self, answers: dict[str, tuple[int, bytes]]) -> None:
        self.answers = answers
        self.requests: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        parts = urlsplit(url)
        key = f"{parts.netloc}{parts.path.rstrip('/')}"
        if key not in self.answers:
            raise AssertionError(f"unexpected request: {url}")
        return self.answers[key]


def offline(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    raise AssertionError(f"a warm cache made a request: {url}")


class CoverArtClient(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)

    def client(self, transport) -> caa.CoverArt:
        from musiclib.cache import Cache

        return caa.CoverArt(Cache(self.cache_dir), transport=transport)

    def test_lists_the_release_images_from_the_cover_art_archive(self) -> None:
        body = json.dumps(RELEASE).encode()
        transport = Transport({f"coverartarchive.org/release/{RELEASE_MBID}": (200, body)})
        self.assertEqual(self.client(transport).images(RELEASE_MBID), CAA_IMAGES)
        self.assertEqual(len(transport.requests), 1)

    def test_a_release_the_archive_does_not_have_has_no_images_even_offline(self) -> None:
        # A 404 is the archive's answer for "nothing here". Cached as an empty
        # list, a warm cache can plan the album without the network.
        transport = Transport({f"coverartarchive.org/release/{RELEASE_MBID}": (404, b"Not Found")})
        self.assertEqual(self.client(transport).images(RELEASE_MBID), [])
        self.assertEqual(self.client(offline).images(RELEASE_MBID), [])

    def test_a_download_is_kept_byte_for_byte_and_answers_offline(self) -> None:
        url = by_id(1001)["image"]
        path = urlsplit(url)
        transport = Transport({f"{path.netloc}{path.path}": (200, BODIES[url])})
        self.assertEqual(self.client(transport).download(url), BODIES[url])
        self.assertEqual(self.client(offline).download(url), BODIES[url])


class Naming(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = images.plan_images(CAA_IMAGES, download)

    def test_names_every_image_the_rules_keep(self) -> None:
        self.assertEqual(
            set(self.plan.files),
            {
                "cover.jpg",
                "back.jpg",
                "booklet-01.jpg",
                "booklet-02.jpg",
                "medium-1.jpg",
                "medium-2.jpg",
                "tray.jpg",
                "spine.jpg",
            },
        )
        self.assertFalse(self.plan.problems)

    def test_the_front_becomes_cover_jpg(self) -> None:
        self.assertEqual(self.plan.files["cover.jpg"], BODIES[by_id(1003)["image"]])

    def test_numbers_repeated_types_in_the_archives_order(self) -> None:
        # The second booklet and the second medium have the lower ids, so
        # numbering by id swaps each pair.
        for name, image_id in (
            ("booklet-01.jpg", 1009),
            ("booklet-02.jpg", 1002),
            ("medium-1.jpg", 1008),
            ("medium-2.jpg", 1004),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.plan.files[name], BODIES[by_id(image_id)["image"]])

    def test_skips_raw_unedited_and_watermark_wherever_they_are_in_the_types(self) -> None:
        # The watermarked image lists Back first, so checking only the first
        # type keeps it, as `back-2.jpg` or over the real `back.jpg`.
        self.assertEqual(self.plan.files["back.jpg"], BODIES[by_id(1001)["image"]])
        saved = list(self.plan.files.values())
        for image_id in (1006, 1007):
            with self.subTest(image_id=image_id):
                self.assertNotIn(BODIES[by_id(image_id)["image"]], saved)

    def test_converts_any_other_format_to_jpeg(self) -> None:
        spine = self.plan.files["spine.jpg"]
        self.assertTrue(is_jpeg(spine))
        self.assertEqual(size(spine), (64, 32))
        r, g, b = Image.open(io.BytesIO(spine)).convert("RGB").getpixel((32, 16))
        self.assertTrue(g > 100 and r < 40 and b < 40, (r, g, b))

    def test_a_single_medium_is_not_numbered_and_a_single_booklet_is(self) -> None:
        plan = images.plan_images([by_id(1003), by_id(1008), by_id(1009)], download)
        self.assertEqual(set(plan.files), {"cover.jpg", "medium.jpg", "booklet-01.jpg"})


class WhichImageIsTheFront(unittest.TestCase):
    def image(self, image_id: int, types: list[str], front: bool) -> dict:
        return {**by_id(image_id), "types": types, "front": front}

    def test_the_image_marked_front_wins_over_an_earlier_front_typed_one(self) -> None:
        caa_images = [self.image(1001, ["Front"], False), self.image(1002, ["Front"], True)]
        plan = images.plan_images(caa_images, download)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])

    def test_without_a_marked_front_the_first_front_typed_image_is_the_cover(self) -> None:
        caa_images = [self.image(1001, ["Back"], False), self.image(1002, ["Front"], False)]
        plan = images.plan_images(caa_images, download)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])

    def test_a_raw_unedited_front_is_never_the_cover(self) -> None:
        caa_images = [self.image(1006, ["Raw/Unedited", "Front"], True), self.image(1002, ["Front"], False)]
        plan = images.plan_images(caa_images, download)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])


NO_FRONT = ("no front cover: not in the Cover Art Archive for the release or its release group, "
            "and no cover image in the folder")
#: What `plan_album` says instead, where the archive answered and neither the files nor the folder
#: carry a cover. `plan_images` called on its own still says `NO_FRONT`.
NO_COVER = "no cover: the cover art archive has no front and the files carry none; upload a cover"


class NoFrontInTheArchive(unittest.TestCase):
    def test_an_archive_front_that_passes_replaces_the_folders_cover(self) -> None:
        # The fixture's own front is 100 by 50 and fails the cover bar,
        # so the front here is swapped for a square one that passes.
        front = builders.jpeg(800, 800)
        plan = images.plan_images(CAA_IMAGES, {**BODIES, by_id(1003)["image"]: front}.__getitem__,
                                  local=[("cover.jpg", builders.jpeg(10, 10))])
        self.assertEqual(plan.files["cover.jpg"], front)

    def test_the_folders_cover_is_kept(self) -> None:
        existing = builders.jpeg(10, 10)
        plan = images.plan_images([by_id(1001)], download, local=[("cover.jpg", existing)])
        self.assertEqual(plan.files["cover.jpg"], existing)
        self.assertEqual(plan.files["back.jpg"], BODIES[by_id(1001)["image"]])
        self.assertFalse(plan.problems)

    def test_with_no_cover_in_the_folder_either_the_plan_says_where_it_looked(self) -> None:
        for caa_images in ([], [by_id(1001)], [by_id(1006)]):
            with self.subTest(ids=[i["id"] for i in caa_images]):
                plan = images.plan_images(caa_images, download)
                self.assertNotIn("cover.jpg", plan.files)
                self.assertIn(NO_FRONT, plan.problems)


class EmbeddedFront(unittest.TestCase):
    def test_a_cover_over_1200_px_is_resized_to_1200_on_its_long_side(self) -> None:
        for source, expected in ((COVER, (1200, 675)), (builders.jpeg(900, 1600), (675, 1200))):
            with self.subTest(source=size(source)):
                out = images.embedded_front(source)
                self.assertTrue(is_jpeg(out))
                self.assertEqual(size(out), expected)

    def test_a_resized_cover_is_the_same_picture(self) -> None:
        out = Image.open(io.BytesIO(images.embedded_front(two_tone(2000, 1000)))).convert("RGB")
        left, right = out.getpixel((150, 300)), out.getpixel((1050, 300))
        self.assertTrue(left[0] > 200 and left[2] < 60, left)
        self.assertTrue(right[2] > 200 and right[0] < 60, right)

    def test_a_cover_that_fits_is_used_byte_for_byte(self) -> None:
        for width, height in ((800, 800), (1200, 500)):
            with self.subTest(size=(width, height)):
                source = builders.jpeg(width, height)
                self.assertEqual(images.embedded_front(source), source)


class Embed(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.front = builders.jpeg(300, 300)

    def seeded(self, ext: str) -> Path:
        """A track with a title and two pictures already in it, a front and a back."""
        path = builders.copy_fixture(self.tmp, ext)
        builders.write_tags(path, {TITLE_KEY[ext]: "Hier kommt Alex"})
        if ext == "mp3":
            builders.add_id3v1(path)
        builders.embed_picture(path, builders.jpeg(20, 20), picture_type=3)
        builders.embed_picture(path, builders.jpeg(30, 20), picture_type=4)
        return path

    def test_leaves_exactly_one_front_cover_with_the_given_bytes(self) -> None:
        for ext in FORMATS:
            with self.subTest(ext=ext):
                path = self.seeded(ext)
                images.embed(path, self.front)
                self.assertEqual(pictures(path), [(3, "image/jpeg", self.front)])

    def test_adds_the_cover_to_a_track_that_has_none(self) -> None:
        for ext in FORMATS:
            with self.subTest(ext=ext):
                path = builders.copy_fixture(self.tmp, ext, "bare")
                images.embed(path, self.front)
                self.assertEqual(pictures(path), [(3, "image/jpeg", self.front)])

    def test_keeps_the_other_tags(self) -> None:
        for ext in FORMATS:
            with self.subTest(ext=ext):
                path = self.seeded(ext)
                images.embed(path, self.front)
                title = builders.read_tags(path)[TITLE_KEY[ext]]
                self.assertEqual([str(v) for v in title], ["Hier kommt Alex"])

    def test_saves_an_mp3_as_id3v24_with_no_id3v1(self) -> None:
        path = self.seeded("mp3")
        images.embed(path, self.front)
        self.assertEqual(ID3(path).version[:2], (2, 4))
        self.assertNotEqual(path.read_bytes()[-128:-125], b"TAG")

    def test_embedded_pictures_reads_every_picture_with_its_type(self) -> None:
        for ext in FORMATS:
            with self.subTest(ext=ext):
                path = self.seeded(ext)
                found = images.embedded_pictures(path)
                # M4A keeps no picture type, so only the bytes are compared there.
                expected = [builders.jpeg(20, 20), builders.jpeg(30, 20)]
                if ext == "m4a":
                    self.assertEqual([data for _type, data in found], expected)
                else:
                    self.assertEqual(found, [(3, expected[0]), (4, expected[1])])


class EmbedInMp4AndWma(unittest.TestCase):
    """The two kinds `Embed` does not cover: `.mp4` audio, embedded like M4A, and WMA's `WM/Picture`."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.front = builders.jpeg(300, 300)

    def seeded(self, ext: str) -> Path:
        """A track with a title and two pictures in it already, a front and a back."""
        path = builders.copy_fixture(self.tmp, ext)
        builders.write_tags(path, {"mp4": {"\xa9nam": "Hier kommt Alex"},
                                   "wma": {"Title": "Hier kommt Alex"}}[ext])
        builders.embed_picture(path, builders.jpeg(20, 20), picture_type=3)
        builders.embed_picture(path, builders.jpeg(30, 20), picture_type=4)
        return path

    @staticmethod
    def pictures(path: Path) -> list[tuple[int, str, bytes]]:
        if path.suffix == ".wma":
            return builders.asf_pictures(path)
        return [(3, "image/jpeg" if c.imageformat == MP4Cover.FORMAT_JPEG else "other", bytes(c))
                for c in MP4(path).get("covr", [])]

    def test_leaves_exactly_one_front_cover_with_the_given_bytes_and_keeps_the_title(self) -> None:
        # Seeded with two pictures, so an embed that adds without clearing
        # leaves three.
        for ext in ("mp4", "wma"):
            with self.subTest(ext=ext):
                path = self.seeded(ext)
                images.embed(path, self.front)
                self.assertEqual(self.pictures(path), [(3, "image/jpeg", self.front)])
                title = builders.read_tags(path)["\xa9nam" if ext == "mp4" else "Title"]
                self.assertEqual([str(v) for v in title], ["Hier kommt Alex"])

    def test_embedded_pictures_reads_every_picture(self) -> None:
        # Comparing a written album against its plan reads these, and a
        # format it cannot read makes every re-plan of that album raise.
        expected = [builders.jpeg(20, 20), builders.jpeg(30, 20)]
        for ext in ("mp4", "wma"):
            with self.subTest(ext=ext):
                found = images.embedded_pictures(self.seeded(ext))
                if ext == "mp4":
                    self.assertEqual([data for _type, data in found], expected)
                else:
                    self.assertEqual(found, [(3, expected[0]), (4, expected[1])])


class CoverAndEmbeddedTogether(unittest.TestCase):
    def test_cover_jpg_stays_full_size_and_every_track_carries_it_at_1200(self) -> None:
        front = {**by_id(1003), "image": "http://coverartarchive.org/release/x/1.jpg"}
        plan = images.plan_images([front], lambda url: COVER)
        self.assertEqual(plan.files["cover.jpg"], COVER)

        embedded = images.embedded_front(plan.files["cover.jpg"])
        with tempfile.TemporaryDirectory() as tmp:
            for ext in FORMATS:
                with self.subTest(ext=ext):
                    path = builders.copy_fixture(tmp, ext)
                    images.embed(path, embedded)
                    [(kind, mime, data)] = pictures(path)
                    self.assertEqual((kind, mime), (3, "image/jpeg"))
                    self.assertEqual(data, embedded)
                    self.assertEqual(max(size(data)), 1200)


RELEASE_GROUP_MBID = "4d5e6f70-8192-4a3b-8c4d-5e6f70819203"


class ReleaseGroupImages(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)

    def client(self, transport) -> caa.CoverArt:
        from musiclib.cache import Cache

        return caa.CoverArt(Cache(self.cache_dir), transport=transport)

    def test_lists_the_release_groups_images_and_answers_them_offline(self) -> None:
        body = json.dumps(RELEASE).encode()
        transport = Transport({f"coverartarchive.org/release-group/{RELEASE_GROUP_MBID}": (200, body)})
        self.assertEqual(self.client(transport).release_group_images(RELEASE_GROUP_MBID), CAA_IMAGES)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(self.client(offline).release_group_images(RELEASE_GROUP_MBID), CAA_IMAGES)

    def test_a_release_group_the_archive_does_not_have_has_no_images_even_offline(self) -> None:
        transport = Transport({f"coverartarchive.org/release-group/{RELEASE_GROUP_MBID}": (404, b"Not Found")})
        self.assertEqual(self.client(transport).release_group_images(RELEASE_GROUP_MBID), [])
        self.assertEqual(self.client(offline).release_group_images(RELEASE_GROUP_MBID), [])

    def test_a_release_group_listing_that_answers_500_raises_rather_than_reading_as_none(self) -> None:
        transport = Transport({f"coverartarchive.org/release-group/{RELEASE_GROUP_MBID}": (500, b"oops")})
        with self.assertRaises(caa.CoverArtError):
            self.client(transport).release_group_images(RELEASE_GROUP_MBID)


def webp(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (0, 0, 200)).save(out, "WEBP")
    return out.getvalue()


# Both fronts pass the cover bar (square, 500 px or more), so a front
# that beats a folder image here beats it by rank, not by the bar.
RELEASE_FRONT = ("Front", f"https://coverartarchive.org/release/{builders.RELEASE_ID}/1.jpg", builders.jpeg(601, 601))
RELEASE_BACK = ("Back", f"https://coverartarchive.org/release/{builders.RELEASE_ID}/2.jpg", builders.jpeg(302, 302))
# The release-group endpoint lists another release's images, so its URLs
# name that release, not the one being planned.
OTHER_RELEASE = "1a0b0c0d-0000-4000-8000-0000000000b9"
GROUP_FRONT = ("Front", f"https://coverartarchive.org/release/{OTHER_RELEASE}/7.jpg", builders.jpeg(701, 701))
GROUP_BACK = ("Back", f"https://coverartarchive.org/release/{OTHER_RELEASE}/8.jpg", builders.jpeg(402, 402))
GROUP_BOOKLET = ("Booklet", f"https://coverartarchive.org/release/{OTHER_RELEASE}/9.jpg", builders.jpeg(403, 403))
NOT_AN_IMAGE = b"<!DOCTYPE html><html><title>Service Temporarily Unavailable</title></html>"


class Archives:
    """MusicBrainz as `test_check._Services` answers it, and both Cover Art Archive listings.

    `release_images` and `group_images` are `(type, url, bytes)` for each
    image the release's and the release group's listing hold, in order; a
    tuple of types in place of one gives the image all of them. An empty
    listing is the archive's 404; so is any URL neither names.
    """

    def __init__(self, release: dict, *, release_images=(), group_images=()) -> None:
        self.release_id = release["id"]
        self.group_id = release["release-group"]["id"]
        self.musicbrainz = _Services(release, _release_group(), front=False)
        self.listings = {f"/release/{self.release_id}": list(release_images),
                         f"/release-group/{self.group_id}": list(group_images)}
        self.asked: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc != "coverartarchive.org":
            return self.musicbrainz(url, headers)
        self.asked.append(url)
        listing = self.listings.get(parts.path.rstrip("/"))
        if listing is not None:
            if not listing:
                return 404, b"Not Found"
            return 200, json.dumps({"images": [
                {"id": n, "types": types, "front": "Front" in types, "back": "Back" in types,
                 "image": image_url, "thumbnails": {}}
                for n, (types, image_url) in enumerate(
                    ((list(kind) if isinstance(kind, tuple) else [kind], image_url)
                     for kind, image_url, _data in listing), start=1)]}).encode()
        for listing in self.listings.values():
            for _kind, image_url, data in listing:
                if url == image_url:
                    return 200, data
        return 404, b"Not Found"


#: Over the 64 MiB a plan reads of a folder file to compare its bytes.
LARGE = 65 * 1024 * 1024


class _FrontPlanning(_Planning):
    TITLES = ["Plainsong", "Pictures of You"]

    def plan_rip(self, local: dict[str, bytes], *, large: dict[str, bytes] | None = None, **archive):
        """A rip with no cover of its own but `local`'s files, planned against `archive`.

        Each of `large` is its bytes followed by a sparse tail to `LARGE`.
        """
        root = self.library()
        album = _rip(root, self.TITLES, cover=False)
        for name, data in local.items():
            (album / name).parent.mkdir(parents=True, exist_ok=True)
            (album / name).write_bytes(data)
        for name, head in (large or {}).items():
            with open(album / name, "wb") as handle:
                handle.write(head)
                handle.truncate(LARGE)
        release = _release(self.TITLES)
        services = self.archives = Archives(release, **archive)
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        # Kept for a case that plans the same rip again through the batch.
        self.root, self.unit_, self.release, self.client, self.art = root, self.unit(root, album), release, client, art
        return _plan_album(self.unit_, release, client, art, status="auto")


class TheFrontFallsBack(_FrontPlanning):
    def test_with_no_front_on_the_release_the_release_groups_front_is_the_cover(self) -> None:
        plan = self.plan_rip({}, release_images=[RELEASE_BACK], group_images=[GROUP_BACK, GROUP_FRONT])
        self.assertEqual(plan.images.get("cover.jpg"), GROUP_FRONT[2])
        self.assertEqual(plan.images["back.jpg"], RELEASE_BACK[2])
        self.assertEqual(list(plan.problems), [])

    def test_only_the_front_comes_from_the_release_group(self) -> None:
        # The group's back and booklet belong to some other release of the
        # album; only its front stands in for this one's.
        plan = self.plan_rip({}, release_images=[], group_images=[GROUP_BACK, GROUP_FRONT, GROUP_BOOKLET])
        self.assertEqual(plan.images, {"cover.jpg": GROUP_FRONT[2]})

    def test_the_releases_own_front_beats_the_groups_and_the_folders(self) -> None:
        plan = self.plan_rip({"cover.jpg": builders.jpeg(501, 501)},
                             release_images=[RELEASE_FRONT], group_images=[GROUP_FRONT])
        self.assertEqual(plan.images.get("cover.jpg"), RELEASE_FRONT[2])

    def test_the_release_groups_front_beats_a_cover_jpg_already_in_the_folder(self) -> None:
        plan = self.plan_rip({"cover.jpg": builders.jpeg(501, 501)},
                             release_images=[RELEASE_BACK], group_images=[GROUP_FRONT])
        self.assertEqual(plan.images.get("cover.jpg"), GROUP_FRONT[2])
        self.assertEqual(list(plan.problems), [])

    def test_with_no_front_in_either_archive_folder_png_becomes_cover_jpg_and_is_removed(self) -> None:
        plan = self.plan_rip({"Folder.PNG": png(64, 32, (0, 128, 0, 255))})
        cover = plan.images.get("cover.jpg")
        self.assertIsNotNone(cover, plan.problems)
        self.assertTrue(is_jpeg(cover))
        self.assertEqual(size(cover), (64, 32))
        r, g, b = Image.open(io.BytesIO(cover)).convert("RGB").getpixel((32, 16))
        self.assertTrue(g > 100 and r < 40 and b < 40, (r, g, b))
        self.assertIn("Folder.PNG", _names(plan.deletions))
        self.assertNotIn("Folder.PNG", _names(plan.kept) | _names(plan.extras))
        self.assertEqual(list(plan.problems), [])

    def test_every_listed_name_and_extension_in_any_case_is_taken_from_the_folder(self) -> None:
        # A JPEG is kept byte for byte; anything else is converted.
        cases = {
            "COVER.png": png(71, 31, (0, 128, 0, 255)),
            "Front.JPEG": builders.jpeg(72, 32),
            "folder.jpg": builders.jpeg(73, 33),
            "Album.WebP": webp(74, 34),
            "ART.JPG": builders.jpeg(75, 35),
        }
        for name, data in cases.items():
            with self.subTest(name):
                plan = self.plan_rip({name: data})
                cover = plan.images.get("cover.jpg")
                self.assertIsNotNone(cover, plan.problems)
                self.assertTrue(is_jpeg(cover))
                self.assertEqual(size(cover), size(data))
                if is_jpeg(data):
                    self.assertEqual(cover, data)
                self.assertEqual(list(plan.problems), [])

    def test_of_several_in_the_folder_the_earliest_name_in_the_list_wins_then_the_file_name(self) -> None:
        # Alphabetical order picks `album` or `art` in each of these; the
        # list's order is cover, front, folder, album, art.
        cases = {
            "front": ({"album.jpg": builders.jpeg(81, 41), "art.png": png(82, 42, (0, 0, 0, 255)),
                       "Folder.jpg": builders.jpeg(83, 43), "front.webp": webp(84, 44)}, (84, 44)),
            "cover": ({"album.jpg": builders.jpeg(81, 41), "cover.png": png(85, 45, (0, 0, 0, 255))}, (85, 45)),
            "one name, two extensions": ({"front.png": png(86, 46, (0, 0, 0, 255)),
                                          "front.jpeg": builders.jpeg(87, 47)}, (87, 47)),
        }
        for case, (local, expected) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip(local)
                self.assertIn("cover.jpg", plan.images, plan.problems)
                self.assertEqual(size(plan.images["cover.jpg"]), expected)

    def test_a_folder_image_passed_over_for_an_archive_front_stays_where_it_is(self) -> None:
        # Only a folder image that became `cover.jpg` is removed; one the
        # archive's front beat is left alone, so a plan that deletes every
        # cover-named image it looked at loses the owner's file.
        mine = builders.jpeg(501, 501)
        cases = {
            "the release's front": (dict(release_images=[RELEASE_FRONT]), RELEASE_FRONT[2]),
            "the release group's front": (dict(release_images=[RELEASE_BACK], group_images=[GROUP_FRONT]),
                                          GROUP_FRONT[2]),
        }
        for case, (archive, front) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip({"folder.jpg": mine}, **archive)
                self.assertEqual(plan.images.get("cover.jpg"), front)
                self.assertNotIn("folder.jpg", _names(plan.deletions))
                self.assertIn("folder.jpg", _names(plan.kept))
                self.assertEqual(list(plan.problems), [])

    def test_a_name_or_extension_off_the_list_or_a_file_in_a_subfolder_is_not_a_cover(self) -> None:
        # A name with a front word in it becomes `front.*` and then a cover
        # (the case below), so the extra-word and subfolder cases here carry no
        # front word: `Cover 1` is one of several covers, `covers` is plural.
        for name in ("cover.gif", "cover.bmp", "covers.jpg", "cover 1.jpg", "back.jpg", "scans/covers.jpg"):
            with self.subTest(name):
                plan = self.plan_rip({name: builders.jpeg(90, 90)})
                # A plan refused before tagging (a unit `units` blocks) holds
                # no images either, so the tracks show it was really planned.
                self.assertTrue(plan.files, plan.problems)
                self.assertNotIn("cover.jpg", plan.images)
                self.assertIn(NO_COVER, plan.problems)

    def test_a_stray_whose_name_guesses_the_front_is_the_cover_and_stays_as_front_jpg(self) -> None:
        # The one at the root and the one in a subfolder both land as
        # `front.jpg`, copied to `cover.jpg`, never moved.
        for name in ("front cover.jpg", "scans/cover.jpg"):
            with self.subTest(name):
                data = builders.jpeg(90, 90)
                plan = self.plan_rip({name: data})
                self.assertEqual(plan.images.get("cover.jpg"), data, plan.problems)
                self.assertEqual([p for p in plan.problems if p.startswith(("no cover", "no front cover"))], [])
                self.assertEqual(list(plan.moved.values()), ["front.jpg"])
                self.assertNotIn(PurePosixPath(name).name, _names(plan.deletions))


def listed(*entries: tuple[str, str, bytes]) -> tuple[list[dict], dict[str, bytes]]:
    """An archive listing of `(type, url, bytes)` entries, a Front-typed one marked front, and the bytes behind each."""
    return ([caa_image(n, [kind], url, front=kind == "Front") for n, (kind, url, _data) in enumerate(entries, start=1)],
            {url: data for _kind, url, data in entries})


class ADownloadThatIsNotAnImage(_FrontPlanning):
    """A fetched archive image that is not an image counts as a failed image.

    It is not saved, is named in `ImagePlan.unreadable`, adds no problem, and a
    front that is not one falls through the cover order as a failed download
    does. The album-level effects are judged through `plan_album`; the naming
    through `plan_images`, the seam that carries it (a `Plan`'s own `unreadable`
    is unreadable audio files, which is something else).
    """

    def unreadable(self, release_images=(), group_images=None, **arguments) -> images.ImagePlan:
        """The same archive handed to `plan_images` directly."""
        listing, bodies = listed(*release_images)
        group_listing, group_bodies = listed(*(group_images or ()))
        return images.plan_images(listing, {**bodies, **group_bodies}.__getitem__,
                                  group_images=None if group_images is None else lambda: group_listing, **arguments)

    def assert_left_out(self, plan, url: str, body: bytes) -> None:
        # A problem would hold the album; the owner's answer is that it lands without the image.
        self.assertEqual([problem for problem in plan.problems if url in problem], [])
        self.assertNotIn(body, plan.images.values())

    def test_is_left_out_named_as_unreadable_and_never_a_problem_or_a_raise(self) -> None:
        # An HTML error page served with a 200 is not a missing cover, and
        # not a crash either: raising here would file the album under
        # `error` in a batch.
        folder = builders.jpeg(501, 501)
        cases = {
            "the release's front": (dict(release_images=[("Front", RELEASE_FRONT[1], NOT_AN_IMAGE)]),
                                    RELEASE_FRONT[1], folder),
            "the release's back": (dict(release_images=[RELEASE_FRONT, ("Back", RELEASE_BACK[1], b"")]),
                                   RELEASE_BACK[1], RELEASE_FRONT[2]),
            "the release group's front": (dict(release_images=[],
                                               group_images=[("Front", GROUP_FRONT[1], NOT_AN_IMAGE)]),
                                          GROUP_FRONT[1], folder),
        }
        for case, (archive, url, cover) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip({"cover.jpg": folder}, **archive)
                body = dict((u, d) for _k, u, d in [*archive["release_images"], *archive.get("group_images", [])])[url]
                self.assert_left_out(plan, url, body)
                assert_image(self, plan.images.get("cover.jpg"), cover)
                self.assertNotIn("back.jpg", plan.images)
                image_plan = self.unreadable(**archive, local=[("cover.jpg", folder)])
                self.assertEqual(image_plan.unreadable, [url])
                self.assertEqual(image_plan.problems, [])

    def test_a_broken_release_front_falls_through_to_the_folder_cover_and_the_release_group_is_never_asked(
            self) -> None:
        # The release has a front, so the release group is never asked: its
        # front belongs to another release of the album. The folder cover
        # stands in, as it does for a front whose download failed.
        folder = builders.jpeg(501, 501)
        plan = self.plan_rip({"folder.jpg": folder},
                             release_images=[("Front", RELEASE_FRONT[1], NOT_AN_IMAGE)],
                             group_images=[GROUP_FRONT])
        assert_image(self, plan.images.get("cover.jpg"), folder)
        self.assert_left_out(plan, RELEASE_FRONT[1], NOT_AN_IMAGE)
        self.assertEqual([url for url in self.archives.asked if "/release-group/" in url], [])

    def test_a_broken_front_falls_through_to_the_embedded_front_then_the_folder_then_none(self) -> None:
        # The order a failed download takes (`TheCoverOrder`), and never the
        # release group's front, which passes and would win if it were asked.
        broken = [("Front", RELEASE_FRONT[1], NOT_AN_IMAGE), RELEASE_BACK]
        cases = {
            "an embedded front and a folder cover": (dict(embedded=SMALL_EMBEDDED, local=[("folder.jpg", FOLDER)]),
                                                     SMALL_EMBEDDED),
            "a folder cover": (dict(local=[("folder.jpg", SMALL_FOLDER)]), SMALL_FOLDER),
            "neither": ({}, None),
        }
        for case, (arguments, expected) in cases.items():
            with self.subTest(case):
                plan = self.unreadable(broken, [GROUP_FRONT], **arguments)
                self.assertEqual(plan.files.get("cover.jpg"), expected, describe(plan.files.get("cover.jpg")))
                self.assertEqual(plan.unreadable, [RELEASE_FRONT[1]])
                self.assertEqual(plan.files.get("back.jpg"), RELEASE_BACK[2])

    def test_a_truncated_jpeg_or_one_pillow_raises_valueerror_or_syntaxerror_on_is_left_out_the_same_way(
            self) -> None:
        # A JPEG's first three bytes prove nothing about the rest, so one cut
        # off mid-download would otherwise be kept byte for byte as the cover.
        for body_name, body in BROKEN.items():
            for where, archive, url in (
                ("front", dict(release_images=[("Front", RELEASE_FRONT[1], body)]), RELEASE_FRONT[1]),
                ("back", dict(release_images=[RELEASE_FRONT, ("Back", RELEASE_BACK[1], body)]), RELEASE_BACK[1]),
            ):
                with self.subTest(body=body_name, image=where):
                    plan = self.plan_rip({}, **archive)
                    self.assert_left_out(plan, url, body)
                    if where == "back":
                        assert_image(self, plan.images.get("cover.jpg"), RELEASE_FRONT[2])
                        self.assertNotIn("back.jpg", plan.images)
                    image_plan = self.unreadable(**archive)
                    self.assertEqual(image_plan.unreadable, [url])
                    self.assertNotIn(body, image_plan.files.values())


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR_16X16_RGB = struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)

#: Bytes that start as an image and are not one, each failing in Pillow a different way.
BROKEN = {
    # The JPEG magic bytes, and half of the picture after them: OSError on load.
    "truncated JPEG": builders.jpeg(300, 300)[:len(builders.jpeg(300, 300)) // 2],
    # An IHDR chunk one byte short: Pillow raises ValueError from `Image.open`.
    "PNG raising ValueError": _PNG_SIGNATURE + _png_chunk(b"IHDR", _IHDR_16X16_RGB[:12]),
    # A first IDAT too short for the picture, then a chunk whose type is not
    # letters: Pillow raises SyntaxError while loading it.
    "PNG raising SyntaxError": (_PNG_SIGNATURE + _png_chunk(b"IHDR", _IHDR_16X16_RGB)
                                + _png_chunk(b"IDAT", zlib.compress(bytes(16 * 49))[:10])
                                + struct.pack(">I", 16) + b"\x80\xe4P\x02" + bytes(20)),
}


class ABrokenImageInTheFolder(_FrontPlanning):
    def test_is_passed_over_for_the_next_cover_image_in_the_folder(self) -> None:
        # `cover` comes before `front` in the list, so only skipping the
        # broken one reaches the good one.
        good = png(64, 32, (0, 128, 0, 255))
        for body_name, body in BROKEN.items():
            for name in ("cover.jpg", "cover.png"):
                with self.subTest(body=body_name, name=name):
                    plan = self.plan_rip({name: body, "front.png": good})
                    cover = plan.images.get("cover.jpg")
                    self.assertIsNotNone(cover, plan.problems)
                    self.assertEqual(size(cover), (64, 32))
                    self.assertEqual(list(plan.problems), [])


#: Two PDFs that differ, so a name holding the other one shows. Pillow cannot
#: open either, which is how one was held as "not an image" before.
PDF_1 = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n% the first booklet\n%%EOF\n"
PDF_2 = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n% the second booklet\n%%EOF\n"
RELEASE_PDF = f"https://coverartarchive.org/release/{builders.RELEASE_ID}/3.pdf"


def caa_image(image_id: int, types: list[str], url: str, *, front: bool = False) -> dict:
    """One entry of a Cover Art Archive listing, in the shape `release.json` has."""
    return {"approved": True, "back": "Back" in types, "comment": "", "edit": 90000000 + image_id,
            "front": front, "id": image_id, "image": url, "thumbnails": {}, "types": types}


class APdfFromTheArchive(_FrontPlanning):
    """Criterion 62: a `%PDF` download is saved as it is and is never the cover."""

    def test_a_single_pdf_is_saved_as_booklet_pdf_byte_for_byte_and_is_not_embedded(self) -> None:
        plan = self.plan_rip({}, release_images=[RELEASE_FRONT, ("Booklet", RELEASE_PDF, PDF_1)])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(plan.images, {"cover.jpg": RELEASE_FRONT[2], "booklet.pdf": PDF_1})
        # The front is 601 px, under the 1200 px limit, so what every track
        # carries is the front itself.
        self.assertEqual(plan.embedded, RELEASE_FRONT[2])

    def test_a_written_booklet_pdf_is_on_disk_as_downloaded_and_check_finds_nothing(self) -> None:
        # `docs/music-library.md` allows a PDF in the album folder. The plan's
        # own check never sees image files, so only the tree once written
        # shows whether `check` would complain about where the PDF landed.
        plan = self.plan_rip({}, release_images=[RELEASE_FRONT, ("Booklet", RELEASE_PDF, PDF_1)])
        self.assertEqual(list(plan.problems), [])
        _write_album(plan, self.tmp / "extras")
        root = Path(plan.root)
        self.assertEqual((root / plan.destination / "booklet.pdf").read_bytes(), PDF_1)
        self.assertEqual(check.check(root), [])

    def test_several_pdfs_are_numbered_in_the_archives_order_and_the_jpeg_images_keep_their_names(self) -> None:
        # The first PDF has the higher id and the later type name, so
        # numbering by id or by type swaps the pair. Neither PDF is a JPEG of
        # its type: the one typed Back must not make the JPEG back
        # `back-1.jpg`, and the Booklet between the two JPEG booklets must not
        # make the second `booklet-03.jpg`.
        base = f"https://coverartarchive.org/release/{builders.RELEASE_ID}"
        bodies = {f"{base}/1.jpg": builders.jpeg(301, 301), f"{base}/2.jpg": builders.jpeg(302, 302),
                  f"{base}/4.jpg": builders.jpeg(304, 304), f"{base}/5.jpg": builders.jpeg(305, 305),
                  f"{base}/20.pdf": PDF_1, f"{base}/10.pdf": PDF_2}
        listing = [
            caa_image(1, ["Front"], f"{base}/1.jpg", front=True),
            caa_image(2, ["Booklet"], f"{base}/2.jpg"),
            caa_image(20, ["Booklet"], f"{base}/20.pdf"),
            caa_image(4, ["Back"], f"{base}/4.jpg"),
            caa_image(5, ["Booklet"], f"{base}/5.jpg"),
            caa_image(10, ["Back"], f"{base}/10.pdf"),
        ]
        plan = images.plan_images(listing, bodies.__getitem__)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.files, {
            "cover.jpg": bodies[f"{base}/1.jpg"],
            "booklet-01.jpg": bodies[f"{base}/2.jpg"],
            "back.jpg": bodies[f"{base}/4.jpg"],
            "booklet-02.jpg": bodies[f"{base}/5.jpg"],
            "booklet-1.pdf": PDF_1,
            "booklet-2.pdf": PDF_2,
        })

    def test_a_pdf_is_named_booklet_pdf_whatever_its_type_or_address(self) -> None:
        # It is the bytes that make a PDF. The last case's address ends in
        # `.jpg`, so telling a PDF by its URL misses it.
        front = caa_image(1, ["Front"], f"https://coverartarchive.org/release/{builders.RELEASE_ID}/1.jpg",
                          front=True)
        for types, url in ((["Back"], RELEASE_PDF), (["Medium"], RELEASE_PDF), (["Spine", "Tray"], RELEASE_PDF),
                           ([], RELEASE_PDF), (["Booklet"], RELEASE_PDF.replace(".pdf", ".jpg"))):
            with self.subTest(types=types, url=url):
                bodies = {front["image"]: RELEASE_FRONT[2], url: PDF_1}
                plan = images.plan_images([front, caa_image(3, types, url)], bodies.__getitem__)
                self.assertEqual(plan.problems, [])
                self.assertEqual(plan.files, {"cover.jpg": RELEASE_FRONT[2], "booklet.pdf": PDF_1})

    def test_a_pdf_typed_raw_unedited_or_watermark_is_skipped_like_any_image_of_those_types(self) -> None:
        # The two types every archive image is skipped for apply whatever the file is. The PDF check reads bytes before types,
        # so a skip applied only to pictures would still save these.
        front = caa_image(1, ["Front"], f"https://coverartarchive.org/release/{builders.RELEASE_ID}/1.jpg",
                          front=True)
        for types in (["Raw/Unedited"], ["Back", "Watermark"]):
            with self.subTest(types=types):
                bodies = {front["image"]: RELEASE_FRONT[2], RELEASE_PDF: PDF_1}
                plan = images.plan_images([front, caa_image(3, types, RELEASE_PDF)], bodies.__getitem__)
                self.assertEqual(plan.problems, [])
                self.assertEqual(plan.files, {"cover.jpg": RELEASE_FRONT[2]})

    def test_a_pdf_front_is_no_front_so_the_release_groups_front_is_the_cover_and_the_pdf_is_still_saved(
            self) -> None:
        plan = self.plan_rip({"folder.jpg": builders.jpeg(501, 501)},
                             release_images=[("Front", RELEASE_PDF, PDF_1), RELEASE_BACK],
                             group_images=[GROUP_FRONT])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(plan.images, {"cover.jpg": GROUP_FRONT[2], "back.jpg": RELEASE_BACK[2],
                                       "booklet.pdf": PDF_1})
        self.assertEqual(plan.embedded, GROUP_FRONT[2])
        self.assertNotIn("folder.jpg", _names(plan.deletions))

    def test_a_pdf_is_no_front_whether_it_is_marked_front_or_only_typed_front(self) -> None:
        # The fake archive above marks every Front-typed image `front: true`,
        # so the two ways the archive names a front are taken apart here.
        group = [caa_image(7, ["Front"], GROUP_FRONT[1], front=True)]
        bodies = {RELEASE_PDF: PDF_1, GROUP_FRONT[1]: GROUP_FRONT[2]}
        for types, marked in ((["Booklet"], True), (["Front"], False), (["Front", "Booklet"], True)):
            with self.subTest(types=types, marked=marked):
                plan = images.plan_images([caa_image(3, types, RELEASE_PDF, front=marked)], bodies.__getitem__,
                                          group_images=lambda: group)
                self.assertEqual(plan.problems, [])
                self.assertEqual(plan.files, {"cover.jpg": GROUP_FRONT[2], "booklet.pdf": PDF_1})

    def test_with_a_pdf_front_and_no_release_group_front_a_cover_image_in_the_folder_is_the_cover(self) -> None:
        mine = builders.jpeg(501, 501)
        plan = self.plan_rip({"folder.jpg": mine}, release_images=[("Front", RELEASE_PDF, PDF_1)])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(plan.images, {"cover.jpg": mine, "booklet.pdf": PDF_1})
        self.assertIn("folder.jpg", _names(plan.deletions))


def _needs(test: unittest.TestCase, name: str):
    """`images.<name>`, or a failure saying it is missing, so one absent name fails its own tests only."""
    found = getattr(images, name, None)
    if found is None:
        test.fail(f"musiclib.images has no {name} yet")
    return found


def encoded(image: Image.Image, kind: str = "PNG") -> bytes:
    out = io.BytesIO()
    image.save(out, kind)
    return out.getvalue()


def scene(width: int, height: int) -> Image.Image:
    """Shapes of different brightness on a pale ground, drawn in proportion, so any size is the same picture."""
    image = Image.new("RGB", (width, height), (230, 220, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0.05 * width, 0.1 * height, 0.45 * width, 0.6 * height), fill=(20, 30, 120))
    draw.ellipse((0.5 * width, 0.45 * height, 0.95 * width, 0.95 * height), fill=(150, 20, 20))
    draw.polygon([(0.6 * width, 0.05 * height), (0.95 * width, 0.05 * height), (0.6 * width, 0.35 * height)],
                 fill=(10, 10, 10))
    return image


def stripes(width: int, height: int) -> Image.Image:
    """Dark and pale horizontal bands: a different picture from `scene`."""
    image = Image.new("RGB", (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for band in range(0, 8, 2):
        draw.rectangle((0, band * height / 8, width, (band + 1) * height / 8), fill=(15, 15, 15))
    return image


def halves(left: tuple[int, int, int], right: tuple[int, int, int], size: int = 800) -> bytes:
    image = Image.new("RGB", (size, size), right)
    image.paste(left, (0, 0, size // 2, size))
    return encoded(image)


WHITE, BLACK = (255, 255, 255), (0, 0, 0)
# Grey 117 against 105, and 76 against 59.
GREEN, MAGENTA = (0, 200, 0), (255, 0, 255)
RED, DARK_GREEN = (255, 0, 0), (0, 100, 0)


class AverageHash(unittest.TestCase):
    """64 bits, one per pixel of the image in grey at 8 by 8, set above the mean."""

    def hash(self, data: bytes) -> int:
        return _needs(self, "average_hash")(data)

    def distance(self, a: int, b: int) -> int:
        return _needs(self, "hash_distance")(a, b)

    def test_the_distance_is_the_number_of_bits_that_differ(self) -> None:
        for a, b, expected in ((0, 0, 0), (0b1010, 0b0110, 2), (0, 2 ** 64 - 1, 64), (2 ** 63, 1, 2)):
            with self.subTest(a=a, b=b):
                self.assertEqual(self.distance(a, b), expected)
                self.assertEqual(self.distance(b, a), expected)

    def test_a_bit_is_set_only_where_the_pixel_is_above_the_mean(self) -> None:
        # Bit order is the implementation's, so only the count of set bits is
        # read. A flat image has no pixel above its mean: counting "at or
        # above" sets all 64. Eight bands, darkest at the top, set the four
        # lower rows against the mean of all 64; a mean taken from fewer
        # pixels sets more.
        quadrant = Image.new("RGB", (800, 800), BLACK)
        quadrant.paste(WHITE, (0, 0, 400, 400))
        bands = Image.new("RGB", (800, 800))
        for row in range(8):
            bands.paste((row * 32,) * 3, (0, row * 100, 800, row * 100 + 100))
        for case, data, bits in (("flat", encoded(Image.new("RGB", (800, 800), (90, 90, 90))), 0),
                                 ("left half white", halves(WHITE, BLACK), 32),
                                 ("top-left quarter white", encoded(quadrant), 16),
                                 ("eight bands, brighter downwards", encoded(bands), 32)):
            with self.subTest(case):
                value = self.hash(data)
                self.assertTrue(0 <= value < 2 ** 64, value)
                self.assertEqual(bin(value).count("1"), bits)

    def test_brightness_is_read_in_grey_not_from_one_colour_channel_or_their_average(self) -> None:
        # In each pair the left side is the brighter in grey, so each hashes
        # like white beside black. Green is darker than magenta in red, in
        # blue and on average; red is darker than dark green in green. Any
        # one channel, or the plain mean of the three, reads a pair backwards.
        reference = self.hash(halves(WHITE, BLACK))
        for left, right in ((GREEN, MAGENTA), (RED, DARK_GREEN)):
            with self.subTest(left=left, right=right):
                self.assertEqual(self.distance(self.hash(halves(left, right)), reference), 0)
                self.assertEqual(self.distance(self.hash(halves(right, left)), reference), 64)

    def test_an_image_is_0_from_itself_and_10_or_less_from_its_250_px_thumbnail(self) -> None:
        # The archive's 250 px thumbnail of a front is set against the full
        # size cover in the folder, so the two must come out
        # close though the bytes, size and format all differ.
        full = scene(1000, 1000)
        thumbnail = full.resize((250, 250), Image.LANCZOS)
        original = self.hash(encoded(full, "JPEG"))
        self.assertEqual(self.distance(original, self.hash(encoded(full, "JPEG"))), 0)
        self.assertLessEqual(self.distance(original, self.hash(encoded(thumbnail, "JPEG"))), 10)

    def test_two_different_pictures_are_more_than_10_apart(self) -> None:
        self.assertGreater(
            self.distance(self.hash(encoded(scene(600, 600))), self.hash(encoded(stripes(600, 600)))), 10)


class TheBarACoverMustPass(unittest.TestCase):
    """Width over height from 0.9 to 1.1, both ends included, and 500 px on the shorter side."""

    def passes(self, width: int, height: int, types=None) -> bool:
        return _needs(self, "passes")(width, height, types)

    def test_square_enough_and_500_px_on_the_shorter_side_passes(self) -> None:
        for width, height in ((500, 500), (550, 500), (500, 550), (540, 600), (1000, 1000)):
            with self.subTest(size=(width, height)):
                self.assertIs(self.passes(width, height), True)

    def test_too_small_or_too_far_from_square_fails(self) -> None:
        # 551 by 500 and 539 by 600 sit just outside 1.1 and 0.9. The rest are
        # the owner's: Final Fantasy V's book front and Born to Die - The Remix
        # EP on shape, 10cc's Windows in the Jungle on size.
        for width, height in ((499, 499), (551, 500), (539, 600), (1600, 646), (2497, 3483), (317, 320)):
            with self.subTest(size=(width, height)):
                self.assertIs(self.passes(width, height), False)

    def test_an_archive_front_typed_anything_but_front_booklet_or_sticker_fails_whatever_its_size(self) -> None:
        # The Final Fantasy V and VI book fronts are typed `Front, Medium`:
        # a disc photographed as the front.
        for types, expected in ((["Front"], True), (["Front", "Booklet"], True), (["Front", "Sticker"], True),
                                (["Front", "Medium"], False), (["Front", "Back"], False),
                                # No types: judged on size and shape alone
                                # (an assumption the doc does not state).
                                ([], True)):
            with self.subTest(types=types):
                self.assertIs(self.passes(1000, 1000, types), expected)


def shade(width: int, height: int, grey: int) -> bytes:
    """A flat JPEG, so two images of one size can still be told apart by their bytes."""
    return encoded(Image.new("RGB", (width, height), (grey, grey, grey)), "JPEG")


def describe(data: bytes | None) -> str:
    if data is None:
        return "no image"
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        return f"{width} by {height}, grey {image.convert('L').getpixel((0, 0))}"


def assert_image(test: unittest.TestCase, actual: bytes | None, expected: bytes) -> None:
    """The same bytes, and a failure that names each image by size and shade rather than printing JPEG."""
    if actual != expected:
        test.fail(f"got {describe(actual)}, expected {describe(expected)}")


ARCHIVE_BASE = f"https://coverartarchive.org/release/{builders.RELEASE_ID}"


def archive(*entries: tuple[list[str], bytes]) -> tuple[list[dict], dict[str, bytes]]:
    """A release listing, the first entry marked front, and the bytes behind each address."""
    listing, bodies = [], {}
    for number, (types, data) in enumerate(entries, start=1):
        url = f"{ARCHIVE_BASE}/{number}.jpg"
        listing.append(caa_image(number, types, url, front=number == 1 and "Front" in types))
        bodies[url] = data
    return listing, bodies


class WhichImageBecomesTheCover(_FrontPlanning):
    """The archive's front only when it passes the bar."""

    def cover(self, archive_front: bytes | None, local: list[tuple[str, bytes]], types=("Front",)) -> bytes:
        listing, bodies = archive((list(types), archive_front)) if archive_front is not None else ([], {})
        return images.plan_images(listing, bodies.__getitem__, local=local).files.get("cover.jpg")

    def test_an_archive_front_that_passes_beats_a_folder_cover_that_passes(self) -> None:
        front = shade(600, 600, 10)
        assert_image(self, self.cover(front, [("folder.jpg", shade(900, 900, 20))]), front)

    def test_a_folder_cover_that_passes_beats_an_archive_front_that_fails(self) -> None:
        # Born to Die - The Remix EP's archive front is 1600 by 646.
        mine = shade(600, 600, 20)
        assert_image(self, self.cover(shade(1600, 646, 10), [("folder.jpg", mine)]), mine)

    def test_the_first_folder_cover_that_passes_wins_not_the_first_folder_cover(self) -> None:
        # `cover` comes before `front` and `folder` in the local-cover order,
        # and fails; `front` passes and comes before `folder`, which is larger.
        # With no archive front at all the same holds.
        mine = shade(600, 600, 30)
        local = [("cover.jpg", shade(300, 300, 20)), ("front.jpg", mine), ("folder.jpg", shade(900, 900, 40))]
        for case, front in (("a failing archive front", shade(1600, 646, 10)), ("no archive front", None)):
            with self.subTest(case):
                assert_image(self, self.cover(front, local), mine)

    def test_an_archive_front_typed_front_medium_loses_to_a_folder_cover_that_passes(self) -> None:
        mine = shade(600, 600, 20)
        for types, winner in ((("Front", "Medium"), mine), (("Front", "Booklet"), None)):
            with self.subTest(types=types):
                front = shade(1000, 1000, 10)
                assert_image(self, self.cover(front, [("folder.jpg", mine)], types), winner or front)

    def test_with_both_failing_the_one_failing_fewer_tests_then_the_longer_shorter_side_then_the_archives(
            self) -> None:
        # Each case is built so the next rule down would pick the other image:
        # the image failing fewer tests has the shorter shorter side, and the
        # longer shorter side is the folder's.
        url = RELEASE_FRONT[1]
        cases = {
            "the folder's fails fewer": (shade(1600, 480, 10), shade(300, 300, 20), "folder"),
            "the archive's fails fewer": (shade(300, 300, 10), shade(1000, 480, 20), "archive"),
            "one test each, the folder's shorter side is longer": (shade(400, 400, 10), shade(450, 450, 20),
                                                                   "folder"),
            "one test each, the archive's shorter side is longer": (shade(450, 450, 10), shade(400, 400, 20),
                                                                    "archive"),
            "a tie on both": (shade(400, 400, 10), shade(400, 400, 20), "archive"),
        }
        for case, (front, mine, winner) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip({"folder.jpg": mine}, release_images=[("Front", url, front)])
                assert_image(self, plan.images.get("cover.jpg"), front if winner == "archive" else mine)
                (fw, fh), (mw, mh) = size(front), size(mine)
                self.assertIn(f"cover: neither passes: {url} ({fw} by {fh}), folder.jpg ({mw} by {mh})",
                              plan.holds)
                self.assertEqual(plan.status, "review")
                self.assertEqual(list(plan.problems), [])

    def test_with_both_failing_a_wrong_type_counts_as_a_failed_test_and_the_first_folder_cover_is_compared(
            self) -> None:
        # The cover tests are three, where the doc says two: counting only shape and
        # size ties these at one each and the archive's longer side wins.
        # And of several folder covers, none passing, only the first in
        # the local-cover order is weighed: `folder.jpg` would beat the front.
        url = RELEASE_FRONT[1]
        front, mine = shade(450, 450, 10), shade(300, 300, 20)
        cases = {
            "a front typed Front, Medium": (("Front", "Medium"), {"folder.jpg": mine}, "folder.jpg", mine),
            "several folder covers": ("Front", {"cover.jpg": shade(300, 300, 30), "folder.jpg": shade(480, 480, 40)},
                                      "cover.jpg", front),
        }
        for case, (types, local, compared, winner) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip(local, release_images=[(types, url, front)])
                assert_image(self, plan.images.get("cover.jpg"), winner)
                (mw, mh) = size(local[compared])
                self.assertIn(f"cover: neither passes: {url} (450 by 450), {compared} ({mw} by {mh})", plan.holds)

    def test_a_lone_image_is_the_cover_whether_or_not_it_passes_and_nothing_is_held(self) -> None:
        front, mine = shade(1600, 646, 10), shade(300, 300, 20)
        cases = {
            "only an archive front": ({}, dict(release_images=[("Front", RELEASE_FRONT[1], front)]), front),
            "only a folder cover": ({"folder.jpg": mine}, dict(release_images=[RELEASE_BACK]), mine),
        }
        for case, (local, archives, expected) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip(local, **archives)
                assert_image(self, plan.images.get("cover.jpg"), expected)
                self.assertEqual(plan.holds, [])
                self.assertEqual(plan.status, "auto")

    def test_a_release_front_that_fails_never_sends_the_system_to_the_release_groups_front(self) -> None:
        # The release group's front passes, so reaching it would look like the
        # better cover. It belongs to another release of the album.
        front = shade(1600, 646, 10)
        for case, local, expected in (("no folder cover", {}, front),
                                      ("a folder cover that passes", {"folder.jpg": shade(600, 600, 20)}, None)):
            with self.subTest(case):
                plan = self.plan_rip(local, release_images=[("Front", RELEASE_FRONT[1], front)],
                                     group_images=[GROUP_FRONT])
                assert_image(self, plan.images.get("cover.jpg"), expected or local.get("folder.jpg"))
                self.assertEqual([url for url in self.archives.asked if "/release-group/" in url], [])


class AFrontInTheFolderStays(_FrontPlanning):
    """`front.*` is copied into `cover.jpg` and kept; `folder`, `album` and `art` are consumed."""

    def test_a_front_that_becomes_the_cover_is_copied_and_kept_in_any_case_and_extension(self) -> None:
        # It is usually a scan of the booklet's front, and jobs deleted 16 of
        # them when it was consumed like `folder.jpg`.
        for name, data in (("front.jpg", shade(600, 600, 20)), ("Front.PNG", png(600, 600, (0, 128, 0, 255)))):
            with self.subTest(name):
                plan = self.plan_rip({name: data}, release_images=[RELEASE_BACK])
                cover = plan.images.get("cover.jpg")
                self.assertIsNotNone(cover, plan.problems)
                self.assertEqual(size(cover), (600, 600))
                self.assertIn(name, _names(plan.kept))
                self.assertNotIn(name, _names(plan.deletions))
                self.assertEqual(list(plan.problems), [])

    def test_folder_album_and_art_that_become_the_cover_are_still_consumed(self) -> None:
        for name in ("folder.jpg", "Album.png", "art.jpeg"):
            with self.subTest(name):
                plan = self.plan_rip({name: png(600, 600, (0, 0, 200, 255))}, release_images=[RELEASE_BACK])
                self.assertIn("cover.jpg", plan.images, plan.problems)
                self.assertIn(name, _names(plan.deletions))
                self.assertNotIn(name, _names(plan.kept))


PDF_URL = f"{ARCHIVE_BASE}/9.pdf"


class ImagesTheFolderAlreadyHas(_FrontPlanning):
    """An archive image is not saved again when the folder, or the plan, already has its bytes."""

    def test_an_archive_booklet_equal_to_front_jpg_in_the_folder_is_not_saved(self) -> None:
        # Piano Collections KINGDOM HEARTS: the archive's booklet scans are the
        # owner's own `front.jpg` and `inside*.jpg`, uploaded.
        scan = shade(420, 600, 70)
        other = shade(420, 600, 90)
        plan = self.plan_rip({"front.jpg": scan},
                             release_images=[RELEASE_FRONT, ("Booklet", f"{ARCHIVE_BASE}/3.jpg", scan),
                                             ("Booklet", f"{ARCHIVE_BASE}/4.jpg", other)])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual([name for name, data in plan.images.items() if data == scan], [])
        # Numbering runs over what is saved, so the
        # one booklet saved is `-01`, never `-02` beside a gap.
        self.assertEqual([name for name, data in plan.images.items() if data == other], ["booklet-01.jpg"])
        self.assertIn("front.jpg", _names(plan.kept))

    def test_two_archive_images_with_equal_bytes_are_saved_once(self) -> None:
        scan = shade(420, 600, 70)
        plan = self.plan_rip({}, release_images=[RELEASE_FRONT, ("Booklet", f"{ARCHIVE_BASE}/3.jpg", scan),
                                                 ("Booklet", f"{ARCHIVE_BASE}/4.jpg", scan)])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual([name for name, data in plan.images.items() if data == scan], ["booklet-01.jpg"])

    def test_an_archive_image_equal_to_the_cover_is_not_saved_again(self) -> None:
        # The cover is the first image the plan saves,
        # so a back that is the front uploaded twice is a copy of it.
        plan = self.plan_rip({}, release_images=[RELEASE_FRONT, ("Back", f"{ARCHIVE_BASE}/3.jpg", RELEASE_FRONT[2]),
                                                 RELEASE_BACK])
        self.assertEqual(list(plan.problems), [])
        self.assertEqual([name for name, data in plan.images.items() if data == RELEASE_FRONT[2]], ["cover.jpg"])
        self.assertEqual(plan.images.get("back.jpg"), RELEASE_BACK[2])

    def test_a_file_in_a_disc_folder_is_not_one_the_album_folder_already_has(self) -> None:
        # "The album folder" is the folder itself, so a
        # scan kept beside one disc's tracks does not stop the booklet.
        scan = shade(420, 600, 70)
        plan = self.plan_rip({"CD1/scan.jpg": scan},
                             release_images=[RELEASE_FRONT, ("Booklet", f"{ARCHIVE_BASE}/3.jpg", scan)])
        self.assertEqual(plan.images.get("booklet-01.jpg"), scan)

    def test_an_archive_image_is_not_saved_over_a_file_of_the_same_name_and_front_jpg_is_never_deleted(
            self) -> None:
        # A second Front-typed image is named `front.jpg` by the Images rule,
        # the name of the owner's own scan, which is never deleted,
        # moved aside or overwritten. The owner's file
        # wins and the archive's image is not saved. The album moves, where
        # a name the plan writes is otherwise a deletion.
        second = shade(420, 600, 90)
        for name in ("front.jpg", "Front.JPG"):
            with self.subTest(name):
                mine = shade(400, 560, 50)
                plan = self.plan_rip({name: mine},
                                     release_images=[RELEASE_FRONT, ("Front", f"{ARCHIVE_BASE}/3.jpg", second)])
                self.assertNotEqual(plan.source, plan.destination)
                self.assertEqual(list(plan.problems), [])
                assert_image(self, plan.images.get("cover.jpg"), RELEASE_FRONT[2])
                self.assertEqual([n for n, data in plan.images.items() if data == second], [])
                self.assertNotIn("front.jpg", {n.casefold() for n in plan.images})
                self.assertIn(name, _names(plan.kept))
                self.assertNotIn(name, _names(plan.deletions))

    def test_the_bytes_compared_are_the_ones_that_would_be_written(self) -> None:
        # The archive's spine is a PNG and is written as a JPEG. A folder file
        # equal to that JPEG is the same image; one equal to the PNG as
        # downloaded is not what would be written, so the spine is still saved.
        spine = png(64, 32, (0, 128, 0, 255))
        archives = dict(release_images=[RELEASE_FRONT, ("Spine", f"{ARCHIVE_BASE}/5.png", spine)])
        written = self.plan_rip({}, **archives).images["spine.jpg"]
        # `art.*` is a name the folder already has for good: a root image
        # with another name is a stray, and a stray is the copy
        # where the folder's file is the original.
        for case, local, saved in (("the JPEG it becomes", {"art.jpg": written}, False),
                                   ("the PNG as downloaded", {"art.png": spine}, True)):
            with self.subTest(case):
                plan = self.plan_rip(local, **archives)
                self.assertEqual(list(plan.problems), [])
                self.assertIs("spine.jpg" in plan.images, saved)

    def test_a_stray_is_a_copy_of_an_archive_image_by_the_bytes_that_would_be_written(self) -> None:
        # Over the same spine: the archive's image is saved and a stray equal
        # to it as written is deleted as its copy. One equal to the PNG as
        # downloaded is no copy, and loses the name on quality instead
        # (equal pixels).
        spine = png(64, 32, (0, 128, 0, 255))
        archives = dict(release_images=[RELEASE_FRONT, ("Spine", f"{ARCHIVE_BASE}/5.png", spine)])
        written = self.plan_rip({}, **archives).images["spine.jpg"]
        for case, name, data, why in (("the JPEG it becomes", "spine scan.jpg", written, "copy"),
                                      ("the PNG as downloaded", "spine scan.png", spine, "lost")):
            with self.subTest(case):
                plan = self.plan_rip({name: data}, **archives)
                self.assertEqual(list(plan.problems), [])
                self.assertEqual(plan.images.get("spine.jpg"), written)
                self.assertIn(name, _names(plan.deletions))
                self.assertEqual([(s.path, s.why, s.against) for s in plan.strays], [(name, why, "spine.jpg")])

    def test_a_pdf_equal_to_a_file_in_the_folder_or_to_one_saved_before_it_is_not_saved(self) -> None:
        cases = {
            "in the folder": ({"liner notes.pdf": PDF_1}, [("Booklet", PDF_URL, PDF_1)]),
            "saved before it": ({}, [("Booklet", PDF_URL, PDF_1), ("Booklet", f"{ARCHIVE_BASE}/10.pdf", PDF_1)]),
        }
        for case, (local, pdfs) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip(local, release_images=[RELEASE_FRONT, *pdfs])
                self.assertEqual(list(plan.problems), [])
                expected = 0 if local else 1
                self.assertEqual(len([name for name, data in plan.images.items() if data == PDF_1]), expected)

    def test_cover_jpg_is_written_even_when_it_equals_front_jpg_and_front_jpg_stays(self) -> None:
        # The cover is the one archive image the folder may already hold:
        # without `cover.jpg` the album has no cover at all.
        front = RELEASE_FRONT[2]
        plan = self.plan_rip({"front.jpg": front}, release_images=[RELEASE_FRONT])
        assert_image(self, plan.images.get("cover.jpg"), front)
        self.assertIn("front.jpg", _names(plan.kept))
        self.assertNotIn("front.jpg", _names(plan.deletions))
        self.assertEqual(list(plan.problems), [])


class AFileTooLargeToCompare(_FrontPlanning):
    """A folder file too large for the plan to read.

    Its bytes are never compared, but its name is still the owner's: it
    stops an archive image of that name as a small file does, so the plan
    neither writes over it nor deletes it when the album moves. Each case
    plans the rip twice, with the owner's file small and large, and wants
    the same images both times.
    """

    def assert_kept_like_a_small_file(self, name: str, head: bytes, **archive) -> None:
        small = self.plan_rip({name: head}, **archive)
        self.assertNotIn(name, {n.casefold() for n in small.images}, "the small case no longer blocks the name")
        plan = self.plan_rip({}, large={name: head}, **archive)
        self.assertNotEqual(plan.source, plan.destination)
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(sorted(plan.images), sorted(small.images))
        self.assertNotIn(name, {n.casefold() for n in plan.images})
        self.assertIn(name, _names(plan.kept))
        self.assertNotIn(name, _names(plan.deletions))

    def test_an_owners_booklet_pdf_too_large_to_compare_is_kept_and_the_archives_is_not_saved_over_it(self) -> None:
        self.assert_kept_like_a_small_file("booklet.pdf", PDF_2, release_images=[RELEASE_FRONT, ("Booklet", PDF_URL, PDF_1)])

    def test_an_owners_front_jpg_too_large_to_compare_is_kept_and_no_archive_image_is_saved_as_front_jpg(self) -> None:
        # The archive's second Front-typed image is named `front.jpg`.
        self.assert_kept_like_a_small_file("front.jpg", shade(400, 560, 50),
                                           release_images=[RELEASE_FRONT, ("Front", f"{ARCHIVE_BASE}/3.jpg",
                                                                            shade(420, 600, 90))])


def _landed(plan, local: list[str]) -> list[str]:
    """The names the files of `local`, at the album folder's root, have once the plan is written."""
    deleted, kept = _names(plan.deletions), _names(plan.kept)
    moved = {PurePosixPath(source).name: name for source, name in plan.moved.items()}
    return sorted(moved.get(name, name) for name in local
                  if name not in deleted and (name in kept or name in moved))


class CopiesAnEarlierJobSaved(_FrontPlanning):
    """A file with an archive image's name, equal to a file of the owner's, is deleted."""

    def test_an_archive_named_copy_of_an_owners_file_is_deleted_and_the_owners_file_kept(self) -> None:
        # What job `t1` left in Piano Collections KINGDOM HEARTS. The plan
        # writes none of these names itself: the archive has only a front.
        # The PDFs are covered too. The owner's images there were `inside1.jpg`
        # and the like, which are strays (the case below), so the owner's
        # files here take names that stay as they are.
        for copy, owners, data in (("booklet-01.jpg", "folder.jpg", shade(420, 600, 70)),
                                   ("back.jpg", "album.jpg", shade(420, 600, 70)),
                                   ("medium-2.jpg", "art.jpg", shade(420, 600, 70)),
                                   ("booklet.pdf", "liner notes.pdf", PDF_1),
                                   ("booklet-2.pdf", "scan.pdf", PDF_2)):
            with self.subTest(copy):
                plan = self.plan_rip({copy: data, owners: data}, release_images=[RELEASE_FRONT])
                self.assertIn(copy, _names(plan.deletions))
                self.assertIn(owners, _names(plan.kept))
                self.assertNotIn(owners, _names(plan.deletions))

    def test_an_archive_named_copy_of_a_stray_leaves_the_image_in_the_folder_once_under_a_library_name(
            self) -> None:
        # The same leftovers with the owner's scans under their real names,
        # which are strays. Whether the stray is the copy of the archive-named
        # file or the other way round is not settled, so either name may be
        # the one that stays. What must hold is that the image is neither lost
        # nor kept twice.
        for copy, owners, guess in (("booklet-01.jpg", "inside1.jpg", "booklet-01.jpg"),
                                    ("back.jpg", "tray card.jpg", "tray.jpg"),
                                    ("medium-2.jpg", "cd.jpg", "medium.jpg")):
            with self.subTest(copy):
                data = shade(420, 600, 70)
                plan = self.plan_rip({copy: data, owners: data}, release_images=[RELEASE_FRONT])
                self.assertEqual(list(plan.problems), [])
                landed = _landed(plan, [copy, owners])
                self.assertEqual(len(landed), 1, landed)
                self.assertIn(landed[0], {copy, guess})

    def test_equal_files_are_left_alone_unless_one_has_an_archive_name_and_the_other_does_not(self) -> None:
        # `cover.jpg` is a name the Images rule gives, so a `back.jpg` equal to
        # it has no owner's file to be a copy of. Two equal strays are not
        # left alone: the later is a copy (`tests.test_strays`).
        data = shade(420, 600, 70)
        for local in ({"back.jpg": data, "booklet-01.jpg": data},
                      {"album.jpg": data, "art.jpg": data},
                      {"cover.jpg": data, "back.jpg": data}):
            with self.subTest(sorted(local)):
                plan = self.plan_rip(local, release_images=[RELEASE_FRONT])
                self.assertEqual(_names(plan.deletions) & (set(local) - {"cover.jpg"}), set())

    def test_cover_jpg_equal_to_front_jpg_deletes_neither(self) -> None:
        # Both are the owner's. `cover.jpg` is never deleted as a copy, and
        # `front.jpg` is never deleted at all.
        data = shade(600, 600, 70)
        plan = self.plan_rip({"cover.jpg": data, "front.jpg": data}, release_images=[RELEASE_BACK])
        assert_image(self, plan.images.get("cover.jpg"), data)
        self.assertNotIn("front.jpg", _names(plan.deletions))
        self.assertIn("front.jpg", _names(plan.kept))


class CopiesInAnAlbumAnEditMoves(_FrontPlanning):
    """The same deletion on an album an owner's edit moves.

    An edit to `album`, `date` or `albumartist` rebuilds the destination and
    sorts the rip's other files again for it. That second sort has to delete
    the same archive-named copies `plan_album` does, in the entry identify
    writes and in the plan apply rebuilds from it.
    """

    def test_an_album_edit_that_moves_the_album_still_deletes_the_copy_and_keeps_the_owners_file(self) -> None:
        data = shade(420, 600, 70)
        # The archive has only a front, so no plan writes `booklet-01.jpg`
        # itself. A plan that did would delete the rip's one for moving,
        # copy or not, and the case would pass without the rule.
        # `album.jpg` is the owner's under a name that is not a stray.
        self.plan_rip({"booklet-01.jpg": data, "album.jpg": data}, release_images=[RELEASE_FRONT])
        root, unit, release = self.root, self.unit_, self.release
        clients = Clients(mb=self.client, caa=self.art, acoustid=None)
        memory = {"edits": {release["id"]: {position_key(p): {"album": ["Moved Record"]}
                                            for p in pair(unit, release)}}}
        entry, _plan = plan_entry(unit, root, clients, memory, {"action": "repoint", "release": release["id"]}, False)
        rebuilt = rebuild(unit, root, clients, entry["inputs"])

        for where, destination, deletions, kept in (
                ("plan_entry", entry["destination"], entry["deletions"], entry["kept"]),
                ("rebuild", rebuilt.destination, rebuilt.deletions, rebuilt.kept)):
            with self.subTest(where):
                self.assertEqual(destination, "C/Cure, The/(2010) Moved Record", "the edit did not move the album")
                self.assertIn("booklet-01.jpg", _names(deletions))
                self.assertIn("album.jpg", _names(kept))
                self.assertNotIn("album.jpg", _names(deletions))


def raising(make_error):
    """A transport that never answers: each request raises a fresh `make_error()`."""

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        raise make_error()

    return transport


#: What `urlopen` raises when the archive does not answer in time, and when it cannot be reached.
NO_ANSWER = {
    "timeout": lambda: TimeoutError("timed out"),
    "no connection": lambda: urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
}


class AnArchiveThatDoesNotAnswer(unittest.TestCase):
    """A timeout or a failed connection is a failed request, like a 500."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)
        front = by_id(1003)["image"]
        # Each request the client makes: its URL, the call that makes it, and what a working archive answers.
        self.requests = {
            "the release's listing": (f"https://coverartarchive.org/release/{RELEASE_MBID}",
                                      lambda art: art.images(RELEASE_MBID),
                                      json.dumps(RELEASE).encode(), CAA_IMAGES),
            "the release group's listing": (f"https://coverartarchive.org/release-group/{RELEASE_GROUP_MBID}",
                                            lambda art: art.release_group_images(RELEASE_GROUP_MBID),
                                            json.dumps(RELEASE).encode(), CAA_IMAGES),
            "an image download": (front, lambda art: art.download(front), BODIES[front], BODIES[front]),
        }

    def client(self, transport) -> caa.CoverArt:
        return caa.CoverArt(Cache(self.cache_dir), transport=transport)

    def test_a_timeout_or_a_failed_connection_is_a_cover_art_error_naming_the_url_in_place_of_a_status(
            self) -> None:
        for word, make_error in NO_ANSWER.items():
            for request, (url, call, _body, _answer) in self.requests.items():
                with self.subTest(word=word, request=request):
                    self.cache_dir = Path(tempfile.mkdtemp(dir=self.cache_dir))
                    with self.assertRaises(caa.CoverArtError) as raised:
                        call(self.client(raising(make_error)))
                    self.assertEqual(str(raised.exception), f"cover art archive: {url} -> {word}")

    def test_a_request_that_did_not_answer_is_not_cached_and_is_asked_again(self) -> None:
        # Identify again is the only retry, so a failure left in the cache
        # would make the album's archive images unreachable for good.
        for word, make_error in NO_ANSWER.items():
            for request, (url, call, body, answer) in self.requests.items():
                with self.subTest(word=word, request=request):
                    self.cache_dir = Path(tempfile.mkdtemp(dir=self.cache_dir))
                    with self.assertRaises(caa.CoverArtError):
                        call(self.client(raising(make_error)))
                    parts = urlsplit(url)
                    working = Transport({f"{parts.netloc}{parts.path}": (200, body)})
                    self.assertEqual(call(self.client(working)), answer)
                    self.assertEqual(working.requests, [url])



class AnArchiveThatBreaksOffAnAnswer(unittest.TestCase):
    """An answer cut short is a failed connection, like one that never came.

    `urlopen` raises these while reading a body the archive stopped sending,
    and they are not `OSError`, so a client that turns only `OSError` into
    `CoverArtError` lets them through and fails identify.
    """

    BROKEN = {
        "a body cut short": lambda: http.client.IncompleteRead(b"\xff\xd8\xff", 48_000),
        "a status line it cannot read": lambda: http.client.BadStatusLine("HTTP/1.1 5"),
    }

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)
        front = by_id(1003)["image"]
        self.requests = {
            "the release's listing": (f"https://coverartarchive.org/release/{RELEASE_MBID}",
                                      lambda art: art.images(RELEASE_MBID), json.dumps(RELEASE).encode(), CAA_IMAGES),
            "the release group's listing": (f"https://coverartarchive.org/release-group/{RELEASE_GROUP_MBID}",
                                            lambda art: art.release_group_images(RELEASE_GROUP_MBID),
                                            json.dumps(RELEASE).encode(), CAA_IMAGES),
            "an image download": (front, lambda art: art.download(front), BODIES[front], BODIES[front]),
        }

    def client(self, transport) -> caa.CoverArt:
        return caa.CoverArt(Cache(self.cache_dir), transport=transport)

    def test_an_http_exception_is_a_cover_art_error_saying_no_connection_and_is_not_cached(self) -> None:
        for broken, make_error in self.BROKEN.items():
            for request, (url, call, body, answer) in self.requests.items():
                with self.subTest(broken=broken, request=request):
                    self.cache_dir = Path(tempfile.mkdtemp(dir=self.cache_dir))
                    with self.assertRaises(caa.CoverArtError) as raised:
                        call(self.client(raising(make_error)))
                    self.assertEqual(str(raised.exception), f"cover art archive: {url} -> no connection")

                    parts = urlsplit(url)
                    working = Transport({f"{parts.netloc}{parts.path}": (200, body)})
                    self.assertEqual(call(self.client(working)), answer)
                    self.assertEqual(working.requests, [url])

#: Covers told apart by size and shade. The front, the embedded front, the
#: folder's and the owner's each pass the cover test; the `SMALL_` ones fail it.
FRONT = shade(600, 600, 10)
FAILING_FRONT = shade(1600, 646, 15)
GROUP_COVER = shade(700, 700, 30)
EMBEDDED = shade(800, 800, 200)
SMALL_EMBEDDED = shade(300, 300, 210)
FOLDER = shade(900, 900, 60)
SMALL_FOLDER = shade(320, 320, 70)
OWNER = shade(650, 650, 240)
BACK_A, BACK_B, MEDIUM = shade(400, 300, 100), shade(410, 300, 110), shade(420, 300, 120)


def downloads(bodies: dict[str, bytes], *failed: str):
    """A `download` that answers `bodies` and gives None for each URL of `failed`, as a request that failed."""

    def download(url: str) -> bytes | None:
        return None if url in failed else bodies[url]

    return download


def group(*entries: tuple[list[str], bytes]) -> tuple[list[dict], dict[str, bytes]]:
    """A release group's listing, which names another release's images, the first entry marked front."""
    listing, bodies = [], {}
    for number, (types, data) in enumerate(entries, start=1):
        url = f"https://coverartarchive.org/release/{OTHER_RELEASE}/{number}.jpg"
        listing.append(caa_image(number, types, url, front=number == 1 and "Front" in types))
        bodies[url] = data
    return listing, bodies


class TheCoverOrder(unittest.TestCase):
    """The cover order at `plan_images`: owner, fetched front, embedded front, folder cover.

    `download` gives None for an image whose request failed. `embedded` is the
    files' embedded front, which `plan_album` reads and hands in.
    """

    def without_a_fetched_front(self) -> dict[str, dict]:
        """`plan_images` arguments for each way an album can have no archive front, none of them a cover."""
        listing, bodies = archive((["Front"], FRONT), (["Back"], BACK_A))
        back_only, back_bodies = archive((["Back"], BACK_A))
        group_listing, group_bodies = group((["Front"], GROUP_COVER))
        return {
            "the archive answered with no front": dict(
                caa_images=back_only, download=downloads(back_bodies), group_images=lambda: []),
            "the archive has nothing for the release or its group": dict(
                caa_images=[], download=downloads({}), group_images=lambda: []),
            "the release's front failed to download": dict(
                caa_images=listing, download=downloads(bodies, listing[0]["image"])),
            "the release group's front failed to download": dict(
                caa_images=back_only, download=downloads({**back_bodies, **group_bodies}, group_listing[0]["image"]),
                group_images=lambda: group_listing),
        }

    def test_with_no_owner_cover_a_fetched_archive_front_is_the_cover_over_the_embedded_front_and_a_folder_cover(
            self) -> None:
        listing, bodies = archive((["Front"], FRONT), (["Back"], BACK_A))
        back_only, back_bodies = archive((["Back"], BACK_A))
        group_listing, group_bodies = group((["Front"], GROUP_COVER))
        cases = {
            "the release's front": (dict(caa_images=listing, download=downloads(bodies)), FRONT),
            "the release group's front": (dict(caa_images=back_only, download=downloads({**back_bodies, **group_bodies}),
                                               group_images=lambda: group_listing), GROUP_COVER),
        }
        for case, (arguments, expected) in cases.items():
            for local in ([], [("folder.jpg", FOLDER)]):
                with self.subTest(case, local=[name for name, _data in local]):
                    plan = images.plan_images(**arguments, local=local, embedded=EMBEDDED)
                    assert_image(self, plan.files.get("cover.jpg"), expected)

    def test_a_fetched_front_that_fails_the_cover_test_is_weighed_against_folder_covers_only(self) -> None:
        # The embedded front is never weighed against a fetched archive front,
        # though here it passes and the archive's front does not.
        listing, bodies = archive((["Front"], FAILING_FRONT))
        for case, local, expected in (("no folder cover: the archive's front", [], FAILING_FRONT),
                                      ("a folder cover that passes: the folder's", [("folder.jpg", FOLDER)], FOLDER)):
            with self.subTest(case):
                plan = images.plan_images(listing, downloads(bodies), local=local, embedded=EMBEDDED)
                assert_image(self, plan.files.get("cover.jpg"), expected)

    def test_without_a_fetched_front_the_embedded_front_is_the_cover_over_a_folder_cover(self) -> None:
        for case, arguments in self.without_a_fetched_front().items():
            for name in ("folder.jpg", "cover.jpg"):
                with self.subTest(case, folder=name):
                    plan = images.plan_images(**arguments, local=[(name, FOLDER)], embedded=EMBEDDED)
                    assert_image(self, plan.files.get("cover.jpg"), EMBEDDED)
                    # The folder cover that lost stays under its own name.
                    self.assertIsNone(plan.consumed)
                    # A problem here would hold the album.
                    self.assertEqual(plan.problems, [])

    def test_the_embedded_front_is_the_cover_though_it_fails_the_cover_test_and_a_folder_cover_passes(
            self) -> None:
        for case, arguments in self.without_a_fetched_front().items():
            with self.subTest(case):
                plan = images.plan_images(**arguments, local=[("folder.jpg", FOLDER)], embedded=SMALL_EMBEDDED)
                assert_image(self, plan.files.get("cover.jpg"), SMALL_EMBEDDED)
                self.assertEqual(plan.problems, [])
                self.assertEqual(plan.holds, [])

    def test_without_a_fetched_or_an_embedded_front_the_folder_cover_is_the_cover(self) -> None:
        for case, arguments in self.without_a_fetched_front().items():
            for embedded in ({}, {"embedded": None}):
                with self.subTest(case, embedded=embedded):
                    plan = images.plan_images(**arguments, local=[("folder.jpg", SMALL_FOLDER)], **embedded)
                    assert_image(self, plan.files.get("cover.jpg"), SMALL_FOLDER)
                    self.assertEqual(plan.consumed, "folder.jpg")
                    self.assertEqual(plan.problems, [])

    def test_with_none_of_them_there_is_no_cover_and_the_images_that_were_fetched_are_still_planned(self) -> None:
        # A failed front costs the album only the front.
        listing, bodies = archive((["Front"], FRONT), (["Back"], BACK_A))
        plan = images.plan_images(listing, downloads(bodies, listing[0]["image"]), embedded=None)
        self.assertNotIn("cover.jpg", plan.files)
        assert_image(self, plan.files.get("back.jpg"), BACK_A)

    def test_an_owner_cover_is_the_cover_over_every_other_and_drops_the_hold_of_two_failing_covers(self) -> None:
        passing, passing_bodies = archive((["Front"], FRONT))
        failing, failing_bodies = archive((["Front"], FAILING_FRONT))
        cases = {
            "a fetched front that passes": dict(caa_images=passing, download=downloads(passing_bodies)),
            "a fetched front that fails, and a folder cover that fails": dict(
                caa_images=failing, download=downloads(failing_bodies), local=[("folder.jpg", SMALL_FOLDER)]),
            "a front that failed to download": dict(
                caa_images=passing, download=downloads(passing_bodies, passing[0]["image"])),
            "an embedded front": dict(caa_images=[], download=downloads({}), embedded=EMBEDDED),
            "a folder cover": dict(caa_images=[], download=downloads({}), local=[("folder.jpg", FOLDER)]),
            "a failed front, an embedded front and a folder cover": dict(
                caa_images=passing, download=downloads(passing_bodies, passing[0]["image"]),
                embedded=EMBEDDED, local=[("folder.jpg", FOLDER)]),
        }
        for case, arguments in cases.items():
            with self.subTest(case):
                plan = images.plan_images(**arguments, owner_cover=OWNER)
                assert_image(self, plan.files.get("cover.jpg"), OWNER)
                self.assertEqual(plan.holds, [])
                self.assertEqual(plan.problems, [])

    def test_with_the_front_fetched_the_plan_is_the_same_with_or_without_an_embedded_front(self) -> None:
        passing, passing_bodies = archive((["Front"], FRONT), (["Back"], BACK_A), (["Back"], BACK_B))
        failing, failing_bodies = archive((["Front"], FAILING_FRONT), (["Medium"], MEDIUM))
        back_only, back_bodies = archive((["Back"], BACK_A))
        group_listing, group_bodies = group((["Front"], GROUP_COVER), (["Back"], BACK_B))
        cases = {
            "a passing front and a passing folder cover": dict(
                caa_images=passing, download=downloads(passing_bodies), local=[("folder.jpg", FOLDER)]),
            "a failing front and a passing folder cover, consumed": dict(
                caa_images=failing, download=downloads(failing_bodies), local=[("folder.jpg", FOLDER)]),
            "a failing front and a failing folder cover, held": dict(
                caa_images=failing, download=downloads(failing_bodies), local=[("cover.jpg", SMALL_FOLDER)]),
            "a failing front alone": dict(caa_images=failing, download=downloads(failing_bodies)),
            "the release group's front": dict(
                caa_images=back_only, download=downloads({**back_bodies, **group_bodies}),
                group_images=lambda: group_listing, existing={"back.jpg": BACK_A}),
        }
        for case, arguments in cases.items():
            for embedded in (EMBEDDED, SMALL_EMBEDDED):
                with self.subTest(case, embedded=describe(embedded)):
                    today = images.plan_images(**arguments)
                    self.assertNotEqual(today.files.get("cover.jpg"), embedded)
                    self.assertEqual(images.plan_images(**arguments, embedded=embedded), today)


class AFailedArchiveImage(unittest.TestCase):
    """An image that failed to download is left out, and the rest named as if it were absent."""

    def test_of_two_backs_the_first_failing_the_other_is_back_jpg(self) -> None:
        listing, bodies = archive((["Front"], FRONT), (["Back"], BACK_A), (["Back"], BACK_B), (["Medium"], MEDIUM))
        plan = images.plan_images(listing, downloads(bodies, listing[1]["image"]))
        self.assertEqual(sorted(plan.files), ["back.jpg", "cover.jpg", "medium.jpg"])
        assert_image(self, plan.files["back.jpg"], BACK_B)
        assert_image(self, plan.files["cover.jpg"], FRONT)
        self.assertEqual(plan.problems, [])
        self.assertEqual(plan.files, images.plan_images([listing[0], *listing[2:]], downloads(bodies)).files)

    def test_of_two_pdfs_the_first_failing_the_other_is_booklet_pdf(self) -> None:
        listing, bodies = archive((["Front"], FRONT), (["Booklet"], PDF_1), (["Booklet"], PDF_2))
        plan = images.plan_images(listing, downloads(bodies, listing[1]["image"]))
        self.assertEqual(sorted(plan.files), ["booklet.pdf", "cover.jpg"])
        self.assertEqual(plan.files["booklet.pdf"], PDF_2)
        self.assertEqual(plan.problems, [])


if __name__ == "__main__":
    unittest.main()
