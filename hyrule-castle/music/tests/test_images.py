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
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from PIL import Image

from musiclib import caa, images, mb
from musiclib.cache import Cache
from tests import builders
from tests.test_check import _names, _Planning, _plan_album, _release, _release_group, _rip, _Services

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


class NoFrontInTheArchive(unittest.TestCase):
    def test_the_archive_front_replaces_the_folders_cover(self) -> None:
        plan = images.plan_images(CAA_IMAGES, download, local=[("cover.jpg", builders.jpeg(10, 10))])
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1003)["image"]])

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


RELEASE_FRONT = ("Front", f"https://coverartarchive.org/release/{builders.RELEASE_ID}/1.jpg", builders.jpeg(301, 301))
RELEASE_BACK = ("Back", f"https://coverartarchive.org/release/{builders.RELEASE_ID}/2.jpg", builders.jpeg(302, 302))
# The release-group endpoint lists another release's images, so its URLs
# name that release, not the one being planned.
OTHER_RELEASE = "1a0b0c0d-0000-4000-8000-0000000000b9"
GROUP_FRONT = ("Front", f"https://coverartarchive.org/release/{OTHER_RELEASE}/7.jpg", builders.jpeg(401, 401))
GROUP_BACK = ("Back", f"https://coverartarchive.org/release/{OTHER_RELEASE}/8.jpg", builders.jpeg(402, 402))
GROUP_BOOKLET = ("Booklet", f"https://coverartarchive.org/release/{OTHER_RELEASE}/9.jpg", builders.jpeg(403, 403))
NOT_AN_IMAGE = b"<!DOCTYPE html><html><title>Service Temporarily Unavailable</title></html>"


class Archives:
    """MusicBrainz as `test_check._Services` answers it, and both Cover Art Archive listings.

    `release_images` and `group_images` are `(type, url, bytes)` for each
    image the release's and the release group's listing hold, in order. An empty
    listing is the archive's 404; so is any URL neither names.
    """

    def __init__(self, release: dict, *, release_images=(), group_images=()) -> None:
        self.release_id = release["id"]
        self.group_id = release["release-group"]["id"]
        self.musicbrainz = _Services(release, _release_group(), front=False)
        self.listings = {f"/release/{self.release_id}": list(release_images),
                         f"/release-group/{self.group_id}": list(group_images)}

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc != "coverartarchive.org":
            return self.musicbrainz(url, headers)
        listing = self.listings.get(parts.path.rstrip("/"))
        if listing is not None:
            if not listing:
                return 404, b"Not Found"
            return 200, json.dumps({"images": [
                {"id": n, "types": [kind], "front": kind == "Front", "back": kind == "Back",
                 "image": image_url, "thumbnails": {}}
                for n, (kind, image_url, _data) in enumerate(listing, start=1)]}).encode()
        for listing in self.listings.values():
            for _kind, image_url, data in listing:
                if url == image_url:
                    return 200, data
        return 404, b"Not Found"


class _FrontPlanning(_Planning):
    TITLES = ["Plainsong", "Pictures of You"]

    def plan_rip(self, local: dict[str, bytes], **archive):
        """A rip with no cover of its own but `local`'s files, planned against `archive`."""
        root = self.library()
        album = _rip(root, self.TITLES, cover=False)
        for name, data in local.items():
            (album / name).parent.mkdir(parents=True, exist_ok=True)
            (album / name).write_bytes(data)
        release = _release(self.TITLES)
        services = Archives(release, **archive)
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        return _plan_album(self.unit(root, album), release, client, art, status="auto")


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

    def test_a_name_or_extension_off_the_list_or_a_file_in_a_subfolder_is_not_a_cover(self) -> None:
        for name in ("cover.gif", "cover.bmp", "covers.jpg", "front cover.jpg", "back.jpg", "scans/cover.jpg"):
            with self.subTest(name):
                plan = self.plan_rip({name: builders.jpeg(90, 90)})
                # A plan refused before tagging (a unit `units` blocks) holds
                # no images either, so the tracks show it was really planned.
                self.assertTrue(plan.files, plan.problems)
                self.assertNotIn("cover.jpg", plan.images)
                self.assertIn(NO_FRONT, plan.problems)


class ADownloadThatIsNotAnImage(_FrontPlanning):
    def test_is_a_problem_naming_its_url_and_never_raises(self) -> None:
        # An HTML error page served with a 200 is not a missing cover, and
        # not a crash either: raising here would file the album under
        # `error` in a batch, where a problem holds it for the owner.
        cases = {
            "the release's front": (dict(release_images=[("Front", RELEASE_FRONT[1], NOT_AN_IMAGE)]),
                                    RELEASE_FRONT[1]),
            "the release's back": (dict(release_images=[RELEASE_FRONT, ("Back", RELEASE_BACK[1], b"")]),
                                   RELEASE_BACK[1]),
            "the release group's front": (dict(release_images=[],
                                               group_images=[("Front", GROUP_FRONT[1], NOT_AN_IMAGE)]),
                                          GROUP_FRONT[1]),
        }
        for case, (archive, url) in cases.items():
            with self.subTest(case):
                plan = self.plan_rip({"cover.jpg": builders.jpeg(501, 501)}, **archive)
                self.assertIn(f"cover art archive: {url} is not an image", plan.problems)

    def test_a_truncated_jpeg_or_one_pillow_raises_valueerror_or_syntaxerror_on_is_the_same_problem(self) -> None:
        # A JPEG's first three bytes prove nothing about the rest, so one cut
        # off mid-download would otherwise be kept byte for byte as the cover.
        for body_name, body in BROKEN.items():
            for where, archive, url in (
                ("front", dict(release_images=[("Front", RELEASE_FRONT[1], body)]), RELEASE_FRONT[1]),
                ("back", dict(release_images=[RELEASE_FRONT, ("Back", RELEASE_BACK[1], body)]), RELEASE_BACK[1]),
            ):
                with self.subTest(body=body_name, image=where):
                    plan = self.plan_rip({}, **archive)
                    self.assertIn(f"cover art archive: {url} is not an image", plan.problems)
                    self.assertNotIn(body, plan.images.values())


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


if __name__ == "__main__":
    unittest.main()
