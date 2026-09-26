"""Album images and the embedded cover, from spec criteria 25, 26 and 27.

`tests/fixtures/caa/release.json` is written in the shape the Cover Art
Archive returns for a release. Its list order is chosen so that sorting by
id, counting a type before skipping, or looking only at the first type all
give the wrong names. The image bytes are generated here with Pillow.
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from PIL import Image

from musiclib import caa, images
from tests import builders

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
        self.plan = images.plan_images(CAA_IMAGES, download, None)

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
        plan = images.plan_images([by_id(1003), by_id(1008), by_id(1009)], download, None)
        self.assertEqual(set(plan.files), {"cover.jpg", "medium.jpg", "booklet-01.jpg"})


class WhichImageIsTheFront(unittest.TestCase):
    def image(self, image_id: int, types: list[str], front: bool) -> dict:
        return {**by_id(image_id), "types": types, "front": front}

    def test_the_image_marked_front_wins_over_an_earlier_front_typed_one(self) -> None:
        caa_images = [self.image(1001, ["Front"], False), self.image(1002, ["Front"], True)]
        plan = images.plan_images(caa_images, download, None)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])

    def test_without_a_marked_front_the_first_front_typed_image_is_the_cover(self) -> None:
        caa_images = [self.image(1001, ["Back"], False), self.image(1002, ["Front"], False)]
        plan = images.plan_images(caa_images, download, None)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])

    def test_a_raw_unedited_front_is_never_the_cover(self) -> None:
        caa_images = [self.image(1006, ["Raw/Unedited", "Front"], True), self.image(1002, ["Front"], False)]
        plan = images.plan_images(caa_images, download, None)
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1002)["image"]])


class NoFrontInTheArchive(unittest.TestCase):
    def test_the_archive_front_replaces_the_existing_cover(self) -> None:
        plan = images.plan_images(CAA_IMAGES, download, builders.jpeg(10, 10))
        self.assertEqual(plan.files["cover.jpg"], BODIES[by_id(1003)["image"]])

    def test_the_existing_cover_is_kept(self) -> None:
        existing = builders.jpeg(10, 10)
        plan = images.plan_images([by_id(1001)], download, existing)
        self.assertEqual(plan.files["cover.jpg"], existing)
        self.assertEqual(plan.files["back.jpg"], BODIES[by_id(1001)["image"]])
        self.assertFalse(plan.problems)

    def test_with_no_existing_cover_either_the_plan_fails_naming_cover_jpg(self) -> None:
        for caa_images in ([], [by_id(1001)], [by_id(1006)]):
            with self.subTest(ids=[i["id"] for i in caa_images]):
                plan = images.plan_images(caa_images, download, None)
                self.assertNotIn("cover.jpg", plan.files)
                self.assertTrue(any("cover.jpg" in str(p) for p in plan.problems), plan.problems)


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
        plan = images.plan_images([front], lambda url: COVER, None)
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


if __name__ == "__main__":
    unittest.main()
