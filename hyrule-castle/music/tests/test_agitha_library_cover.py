"""agitha's editor, the cover: uploaded, shown in the preview, and saved as `cover.jpg` and every track's one front.

`PUT /api/library/covers` takes the image as the body and answers its size,
the cover test (width over height between 0.9 and 1.1, shorter side 500 px or
more) and a token. The token goes in a draft as `cover`, with every track of
the album listed, because a new cover touches every file. `POST
/api/library/preview` answers what the upload answered, before anything is
written. `POST /api/library/save` makes the image `cover.jpg`, as a JPEG at
its full size, and replaces each track's embedded pictures with one front
cover of at most 1200 px.

The uploads and the previews write nothing, so they share one server
(`tests.test_agitha_editor`'s `EditorCase`). Each save has its own
(`tests.test_agitha_save`'s `SaveCase`, whose `land` also checks that nothing
outside the album changed).

Every picture here is two tones split corner to corner, in colours no fixture
album has, so a picture is told from the album's old one by its size and by
its colours, and from another upload by its colours.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import time
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mutagen.flac import FLAC
from mutagen.id3 import ID3
from PIL import Image

from tests import builders
from tests import test_agitha_editor as editor_tests
from tests import test_agitha_library as shelf_tests
from tests import test_agitha_save as saves

address = shelf_tests.address
edit = editor_tests.edit
neighbour = shelf_tests.neighbour

COVERS = "/api/library/covers"
CONTRACT = builders.FIXTURES / "agitha" / "library" / "cover-upload.json"

NOT_AN_IMAGE = "Those bytes are not an image."
WRONG_TYPE = "The cover must be a JPEG, PNG, WebP or GIF image."
#: What the cover test says of a 600 x 837 image, as the album page says it of such a `cover.jpg`.
OBLONG = "The cover is its width and height differ by more than 10 %."

Tones = tuple[tuple[int, int, int], tuple[int, int, int]]
#: Above the diagonal, then below it. Each channel is one a 216-colour palette holds, so a GIF keeps it.
RED_BLUE: Tones = ((204, 51, 51), (51, 51, 204))
GREEN_PINK: Tones = ((51, 204, 51), (204, 51, 204))
#: How far a channel may drift through a conversion and a resize. The fixture's tones are 130 or more away.
DRIFT = 30

#: Content type -> Pillow's name for the format.
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/gif": "GIF"}


def image(width: int, height: int, content_type: str = "image/png", tones: Tones = RED_BLUE) -> bytes:
    return builders.two_tone(width, height, FORMATS.get(content_type, "BMP"), colours=tones)


def with_alpha(png: bytes) -> bytes:
    """`png` with an alpha channel, as most PNGs saved from a browser have. A JPEG cannot hold one."""
    with Image.open(io.BytesIO(png)) as opened:
        out = io.BytesIO()
        opened.convert("RGBA").save(out, "PNG")
        return out.getvalue()


def put(port: int, data: bytes, content_type: str) -> neighbour.Answer:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("PUT", COVERS, body=data, headers={"Content-Type": content_type})
        response = connection.getresponse()
        return neighbour.Answer(response.status, response.headers, response.read())
    finally:
        connection.close()


def outside_jobs(root: Path) -> dict[str, bytes | None]:
    """Every file and folder the server was given but the jobs folder, where the builder keeps the uploads."""
    return {name: data for name, data in builders.tree(root).items()
            if name != "jobs" and not name.startswith("jobs/")}


def embedded(path: Path) -> list[tuple[int, str, bytes]]:
    """`(picture type, the type the tag says it is, the image)` of every picture a track embeds."""
    if path.suffix == ".flac":
        return [(int(picture.type), picture.mime, picture.data) for picture in FLAC(path).pictures]
    return [(int(frame.type), frame.mime, frame.data) for frame in ID3(path).getall("APIC")]


def text_tags(held: dict[str, Any]) -> dict[str, Any]:
    """The tags of `saves.held` without an MP3's pictures, which are tags there and are told apart by `embedded`."""
    return {key: value for key, value in held["tags"].items() if not key.startswith("APIC")}


def strangers(folder: Path, token: str) -> dict[str, Any]:
    """Tokens that name no upload: one of the right form, and ones that reach for a real picture of the library."""
    assert (folder / "front.jpg").is_file()
    # Each character changed, so it is of the form of `token` and is not `token`.
    out: dict[str, Any] = {"never uploaded": "".join("1" if char == "0" else "0" for char in token),
                           "climbs": "../x", "not text": 7}
    # With and without the extension: a server may add one to the token.
    for form, name in (("", "front.jpg"), (", extension left off", "front")):
        out[f"an absolute path{form}"] = str(folder / name)
        for depth in (1, 2, 3):
            climb = "../" * depth + (folder / name).relative_to(folder.parents[3]).as_posix()
            out[f"climbs {depth} to a picture{form}"] = climb
    return out


class Covers(unittest.TestCase):
    """What both kinds of case do: upload a picture, build a draft that names it, and look at a picture."""

    port: int
    root: Path
    #: Both are the case's: `EditorCase.draft`, and `LibraryCase.answer`.
    draft: Any
    answer: Any

    #: The one album a preview of a draft answers.
    preview_answer = editor_tests.EditorCase.preview

    def upload(self, data: bytes, content_type: str = "image/png") -> dict[str, Any]:
        """The answer to an upload the server took."""
        got = put(self.port, data, content_type)
        self.assertEqual(got.status, 200, f"PUT {COVERS} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(got.body)
        self.assertIsInstance(body.get("cover"), str, body)
        self.assertNotEqual(body["cover"], "")
        return body

    def turned_down(self, data: bytes, content_type: str) -> tuple[int, Any]:
        """The status and the sentence of an upload the server refused."""
        got = put(self.port, data, content_type)
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8", got.status)
        body = json.loads(got.body)
        self.assertEqual(list(body), ["error"], f"PUT {COVERS} answered {got.status}: {body}")
        return got.status, body["error"]

    def cover_draft(self, album: str, token: Any, *edits: dict[str, Any]) -> dict[str, Any]:
        """A draft of `token` as the cover and `edits` over `album`, listing every track as the page shows it."""
        draft = self.draft(album, *edits)
        seen = {track["path"]: track["seen"] for track in draft["tracks"]}
        view = self.answer(address(album))
        draft["tracks"] = [{"album": album, "path": track["path"], "loaded": track["loaded"],
                            "seen": seen.get(track["path"], {})} for track in view["tracks"]]
        draft["cover"] = token
        return draft

    def assertPicture(self, data: bytes, size: tuple[int, int] | tuple[tuple[int, int], ...], tones: Tones,
                      what: str) -> None:
        """`data` is a JPEG of `size`, or of one of the sizes, and shows `tones`: the upload, and no fixture picture."""
        sizes = size if isinstance(size[0], tuple) else (size,)
        with Image.open(io.BytesIO(data)) as opened:
            self.assertEqual(opened.format, "JPEG", what)
            self.assertIn(opened.size, sizes, what)
            width, height = opened.size
            pixels = opened.convert("RGB")
            shown = (pixels.getpixel((width // 8, height // 8)),
                     pixels.getpixel((width - 1 - width // 8, height - 1 - height // 8)))
        for found, wanted in zip(shown, tones):
            self.assertLessEqual(max(abs(a - b) for a, b in zip(found, wanted)), DRIFT,
                                 f"{what} shows {shown}, and the upload is {tones}")

    def refuses(self, got: neighbour.Answer, what: str) -> None:
        """`got` is a refusal with a sentence, whatever its 4xx."""
        self.assertTrue(400 <= got.status < 500, f"{what} answered {got.status}: {got.body[:300]!r}")
        body = json.loads(got.body)
        self.assertEqual(list(body), ["error"])
        self.assertIsInstance(body["error"], str)
        self.assertNotEqual(body["error"].strip(), "")


class UploadCase(Covers, editor_tests.EditorCase):
    """One server over `builders.library` for every case of a class: nothing here may write in the library."""


class TakesAnUpload(UploadCase):
    def test_a_png_answers_its_size_the_cover_test_and_a_token_under_the_keys_of_cover_upload_json(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        body = self.upload(image(1800, 1700))
        self.assertEqual(sorted(body), sorted(contract))
        self.assertEqual({key: value for key, value in body.items() if key != "cover"},
                         {"width": 1800, "height": 1700, "passes": True, "problem": None})

    def test_the_answer_applies_the_cover_tests_bounds_ratio_0_9_to_1_1_and_500_px(self) -> None:
        # Each failing size fails one half only, so a test that drops either half lets one through.
        sizes = {(500, 500): True, (499, 499): False, (540, 600): True, (530, 600): False,
                 (660, 600): True, (670, 600): False}
        for (width, height), passes in sizes.items():
            with self.subTest(size=f"{width}x{height}"):
                body = self.upload(image(width, height))
                self.assertEqual((body["width"], body["height"], body["passes"]), (width, height, passes))
                if passes:
                    self.assertIsNone(body["problem"])
                else:
                    self.assertIsInstance(body["problem"], str)
                    self.assertNotEqual(body["problem"].strip(), "")

    def test_bytes_that_are_not_an_image_are_refused_as_not_an_image(self) -> None:
        # The second starts like a PNG, so a check of the first bytes alone lets it through.
        for name, data in (("text", b"not an image at all\n"),
                           ("PNG signature only", b"\x89PNG\r\n\x1a\n" + b"x" * 64)):
            with self.subTest(name):
                self.assertEqual(self.turned_down(data, "image/png"), (400, NOT_AN_IMAGE))

    def test_a_bmp_is_refused_with_the_sentence_that_names_the_four_types(self) -> None:
        # Small enough to be sent whole to a server that answers before it reads.
        bmp = image(80, 80, "image/bmp")
        with Image.open(io.BytesIO(bmp)) as opened:
            # An image Pillow reads, so it is the type that is refused and not the bytes.
            self.assertEqual(opened.format, "BMP")
        self.assertEqual(self.turned_down(bmp, "image/bmp"), (415, WRONG_TYPE))

    def test_uploads_taken_and_refused_and_a_preview_of_one_write_nothing_in_the_library_or_the_extras(self) -> None:
        before = outside_jobs(self.root)
        token = self.upload(image(900, 900))["cover"]
        self.upload(image(600, 837, "image/jpeg"), "image/jpeg")
        self.turned_down(b"not an image at all\n", "image/png")
        self.turned_down(image(80, 80, "image/bmp"), "image/bmp")
        self.preview_answer(self.cover_draft(self.path("discovery"), token))
        after = outside_jobs(self.root)
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name, 0) != after.get(name, 0))
        self.assertEqual(changed, [], "these were written, removed or changed")


class PreviewsACover(UploadCase):
    def test_a_draft_with_a_token_answers_the_uploads_size_and_test_and_lists_no_tag_change(self) -> None:
        path = self.path("discovery")
        token = self.upload(image(1800, 1700))["cover"]
        album = self.preview_answer(self.cover_draft(path, token))
        self.assertEqual(album["cover"], {"width": 1800, "height": 1700, "passes": True, "problem": None})
        self.assertEqual(album["tracks"], [])
        self.assertEqual((album["new_path"], album["problems"], album["refused"]), (path, [], []))
        # A new cover is something to save.
        self.assertIsNone(album["skip"])

    def test_a_token_still_names_its_own_upload_after_a_later_upload(self) -> None:
        # Two album pages open at once: the second upload must not become the first page's cover.
        first = self.upload(image(810, 800))["cover"]
        second = self.upload(image(820, 800))["cover"]
        self.assertNotEqual(first, second)
        for token, width in ((first, 810), (second, 820)):
            album = self.preview_answer(self.cover_draft(self.path("silence"), token))
            self.assertEqual(album["cover"], {"width": width, "height": 800, "passes": True, "problem": None})

    def test_a_draft_with_a_cover_and_a_tag_edit_answers_both(self) -> None:
        path = self.path("ecliptica")
        first = self.tracks("ecliptica")[0]
        token = self.upload(image(900, 900))["cover"]
        album = self.preview_answer(self.cover_draft(path, token, edit((first,), set={"Composer": ["Tony Kakko"]})))
        self.assertEqual(album["cover"], {"width": 900, "height": 900, "passes": True, "problem": None})
        self.assertEqual(self.changes(album), {first: {"Composer": (None, ["Tony Kakko"])}})

    def test_a_draft_with_no_cover_answers_no_cover(self) -> None:
        # An upload nobody put in a draft is no album's cover.
        self.upload(image(900, 900))
        album = self.preview_answer(self.cover_draft(self.path("ecliptica"), None,
                                                     edit(set={"Composer": ["Tony Kakko"]})))
        self.assertIsNone(album["cover"])

    def test_a_token_that_names_no_upload_is_refused(self) -> None:
        path = self.path("ecliptica")
        token = self.upload(image(900, 900))["cover"]
        for name, stranger in strangers(self.shelf / path, token).items():
            with self.subTest(name, token=stranger):
                got = editor_tests.post(self.port, editor_tests.PREVIEW, self.cover_draft(path, stranger))
                self.refuses(got, f"a preview of {stranger!r}")


class SaveCase(Covers, saves.SaveCase):
    """A server and a `builders.library` for each case, with `saves.SaveCase`'s helpers to save a draft."""

    def beside(self, album: str, tracks: tuple[str, ...]) -> dict[str, bytes | None]:
        """Everything in the album folder but its tracks and `cover.jpg`: what a new cover may not touch."""
        return {name: data for name, data in builders.tree(self.shelf / album).items()
                if name not in tracks and name != "cover.jpg"}

    def cover_of(self, album: str) -> bytes:
        cover = self.shelf / album / "cover.jpg"
        self.assertTrue(cover.is_file(), f"{album} has no cover.jpg")
        return cover.read_bytes()

    def assertOneFront(self, path: Path, size: tuple[int, int] | tuple[tuple[int, int], ...], tones: Tones) -> None:
        """`path` embeds one picture: a front cover, a JPEG that says so, of `size`, showing `tones`."""
        pictures = embedded(path)
        self.assertEqual([(kind, mime) for kind, mime, _data in pictures], [(3, "image/jpeg")], path.name)
        self.assertPicture(pictures[0][2], size, tones, f"the picture in {path.name}")


class SavesACover(SaveCase):
    def test_a_png_becomes_cover_jpg_at_full_size_and_each_tracks_one_front_at_1200_px_and_nothing_else(self) -> None:
        path = self.path("discovery")
        folder = self.shelf / path
        tracks = self.tracks("discovery")
        self.assertEqual([Path(track).suffix for track in tracks], [".flac", ".mp3", ".flac"])
        before = self.holds(path, tracks)
        beside = self.beside(path, tracks)
        # What the save must keep is there to be kept.
        self.assertEqual(before[tracks[0]]["tags"]["rating"], ["4"])
        self.assertRegex(before[tracks[0]]["tags"]["added"][0], r"^2026-09-\d\dT18:30$")
        self.assertRegex(before[tracks[1]]["tags"]["TXXX:ADDED"][0], r"^2026-09-\d\dT18:30$")
        self.assertEqual(sorted(name for name in beside if name.endswith(".jpg")), ["back.jpg", "front.jpg"])
        token = self.upload(with_alpha(image(1800, 1700)))["cover"]

        with saves.no_way_out() as asked:
            self.land(self.cover_draft(path, token))

        self.assertPicture(self.cover_of(path), (1800, 1700), RED_BLUE, "cover.jpg")
        after = self.holds(path, tracks)
        for track in tracks:
            with self.subTest(track=track):
                # The long side is cut to 1200; the short one is 1133.3 px at that scale.
                self.assertOneFront(folder / track, ((1200, 1133), (1200, 1134)), RED_BLUE)
                self.assertEqual(text_tags(after[track]), text_tags(before[track]))
                self.assertEqual(after[track]["audio"], before[track]["audio"])
        # `front.jpg`, `back.jpg`, the booklet and the notes, and no file more or fewer.
        self.assertEqual(self.beside(path, tracks), beside)
        self.assertEqual(asked, [])

    def test_over_mp3s_a_jpeg_is_cover_jpg_as_uploaded_and_embedded_at_its_own_size_and_the_rating_stays(self) -> None:
        path = self.path("silence")
        folder = self.shelf / path
        tracks = self.tracks("silence")
        self.assertEqual({Path(track).suffix for track in tracks}, {".mp3"})
        before = self.holds(path, tracks)
        # An MP3 holds its rating in a frame of its own, beside the picture's.
        self.assertIn("POPM:no@email", before[tracks[0]]["tags"])
        data = image(900, 880, "image/jpeg")

        self.land(self.cover_draft(path, self.upload(data, "image/jpeg")["cover"]))

        # Converted to JPEG where it is not one: a JPEG is not written again, which would cost it detail.
        self.assertEqual(self.cover_of(path), data)
        after = self.holds(path, tracks)
        for track in tracks:
            with self.subTest(track=track):
                # Under 1200 px, so it is embedded as it is and never enlarged.
                self.assertOneFront(folder / track, (900, 880), RED_BLUE)
                self.assertEqual(text_tags(after[track]), text_tags(before[track]))
                self.assertEqual(after[track]["audio"], before[track]["audio"])

    def test_a_gif_and_a_webp_each_become_a_jpeg_cover_jpg(self) -> None:
        for name, content_type, size, tones in (("ecliptica", "image/gif", (1000, 960), RED_BLUE),
                                                ("winterheart", "image/webp", (1100, 1040), GREEN_PINK)):
            with self.subTest(content_type):
                path = self.path(name)
                token = self.upload(image(*size, content_type, tones), content_type)["cover"]
                self.land(self.cover_draft(path, token))
                self.assertPicture(self.cover_of(path), size, tones, "cover.jpg")
                for track in self.tracks(name):
                    self.assertOneFront(self.shelf / path / track, size, tones)

    def test_a_track_with_two_pictures_and_a_track_with_none_each_end_with_the_one_front(self) -> None:
        path = self.path("discovery")
        folder = self.shelf / path
        flac, mp3, bare = self.tracks("discovery")
        # A back cover after the front in a FLAC and in an MP3, and a FLAC with no picture at all.
        for track in (flac, mp3):
            builders.embed_picture(folder / track, builders.two_tone(640, 640, colours=GREEN_PINK), picture_type=4)
        builders.clear_pictures(folder / bare)
        self.assertEqual([[kind for kind, _mime, _data in embedded(folder / track)] for track in (flac, mp3, bare)],
                         [[3, 4], [3, 4], []])

        self.land(self.cover_draft(path, self.upload(image(1000, 1000))["cover"]))

        for track in (flac, mp3, bare):
            with self.subTest(track=track):
                self.assertOneFront(folder / track, (1000, 1000), RED_BLUE)

    def test_an_image_that_fails_the_cover_test_warns_in_the_upload_and_the_preview_and_is_saved(self) -> None:
        path = self.path("ecliptica")
        tracks = self.tracks("ecliptica")
        data = image(600, 837, "image/jpeg")
        answer = self.upload(data, "image/jpeg")
        warned = {"width": 600, "height": 837, "passes": False, "problem": OBLONG}
        self.assertEqual({key: answer[key] for key in warned}, warned)
        draft = self.cover_draft(path, answer["cover"])
        previewed = self.preview_answer(draft)
        self.assertEqual(previewed["cover"], warned)
        self.assertEqual((previewed["problems"], previewed["skip"]), ([], None))

        self.land(draft)

        self.assertPicture(self.cover_of(path), (600, 837), RED_BLUE, "cover.jpg")
        for track in tracks:
            self.assertOneFront(self.shelf / path / track, (600, 837), RED_BLUE)
        cover = self.answer(address(path))["cover"]
        self.assertEqual({key: cover[key] for key in warned}, warned)

    def test_an_album_with_no_cover_jpg_answers_no_cover_and_has_one_after_a_save(self) -> None:
        path = self.path("fullmoon")
        folder = self.shelf / path
        tracks = self.tracks("fullmoon")
        (folder / "cover.jpg").unlink()
        self.assertIsNone(self.answer(address(path))["cover"])

        self.land(self.cover_draft(path, self.upload(image(1300, 1300))["cover"]))

        self.assertPicture(self.cover_of(path), (1300, 1300), RED_BLUE, "cover.jpg")
        for track in tracks:
            self.assertOneFront(folder / track, (1200, 1200), RED_BLUE)
        cover = self.answer(address(path))["cover"]
        self.assertEqual({key: cover[key] for key in ("width", "height", "passes", "problem")},
                         {"width": 1300, "height": 1300, "passes": True, "problem": None})
        got = self.fetch(cover["url"])
        self.assertEqual((got.status, got.body), (200, self.cover_of(path)))

    def test_a_cover_and_a_tag_edit_in_one_draft_both_land_in_one_save(self) -> None:
        path = self.path("ecliptica")
        folder = self.shelf / path
        first, middle, last = self.tracks("ecliptica")
        before = self.holds(path, (first, middle, last))
        token = self.upload(image(1000, 1000))["cover"]

        self.land(self.cover_draft(path, token, edit((first,), set={"Genre": saves.NEW_GENRES})))

        self.assertPicture(self.cover_of(path), (1000, 1000), RED_BLUE, "cover.jpg")
        after = self.holds(path, (first, middle, last))
        for track in (first, middle, last):
            with self.subTest(track=track):
                self.assertOneFront(folder / track, (1000, 1000), RED_BLUE)
                wanted = text_tags(before[track])
                if track == first:
                    wanted["genre"] = saves.NEW_GENRES
                self.assertEqual(text_tags(after[track]), wanted)

    def over_a_linked_cover(self, relative: bool) -> None:
        """A new cover saved over `ecliptica`, whose `cover.jpg` is a link to the `cover.jpg` of `silence`.

        The job is `done`, the album's `cover.jpg` is a file of its own
        that holds the upload, and the cover of `silence` is the bytes it
        was. A `relative` link names that cover from the album's place in
        the library alone, and names nothing from a work folder.
        """
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        named = self.shelf / self.path("silence") / "cover.jpg"
        link = self.shelf / path / "cover.jpg"
        link.unlink()
        link.symlink_to(os.path.relpath(named, link.parent) if relative else named)
        # By a digest: a failure prints a line and not two pictures.
        was = saves.digest(named.read_bytes())
        self.assertEqual(saves.digest(link.read_bytes()), was, "the link does not name the other album's cover")
        draft = self.cover_draft(path, self.upload(image(1000, 1000))["cover"])
        before = self.on_disk()

        found = self.settle(self.accepted(draft))

        self.assertEqual(saves.digest(named.read_bytes()), was,
                         "the new cover was written through the link, over another album's")
        self.assertEqual((found["state"], found["error"]), ("done", None))
        self.assertFalse(link.is_symlink(), "the album's cover.jpg is still a link")
        self.assertPicture(self.cover_of(path), (1000, 1000), RED_BLUE, "cover.jpg")
        for track in tracks:
            self.assertOneFront(self.shelf / path / track, (1000, 1000), RED_BLUE)
        # The album's cover and its tracks, and nothing of any other album.
        self.assertEqual(self.differing(before, self.on_disk()),
                         sorted(f"shelf/{path}/{name}" for name in ("cover.jpg", *tracks)))

    def test_a_new_cover_takes_the_place_of_a_cover_jpg_that_is_a_link_and_the_file_it_names_stays(self) -> None:
        self.over_a_linked_cover(relative=False)

    def test_a_new_cover_takes_the_place_of_a_cover_jpg_that_is_a_relative_link(self) -> None:
        self.over_a_linked_cover(relative=True)

    def test_a_new_cover_is_not_embedded_through_a_track_that_is_a_link_out_of_the_library(self) -> None:
        # The album's page does not show such a file, and the draft does not list it. A save that gave
        # every audio file of its copy the picture would write it into the file outside.
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        link, outside = self.lay_linked_track(path)
        was = outside.read_bytes()

        self.land(self.cover_draft(path, self.upload(image(1000, 1000))["cover"]))

        self.assertEqual(outside.read_bytes(), was, "the save wrote through the link")
        self.assertTrue(link.is_symlink(), "a file took the place of the link in the library")
        self.assertEqual(os.readlink(link), str(outside))
        for track in tracks:
            self.assertOneFront(self.shelf / path / track, (1000, 1000), RED_BLUE)

    def test_a_new_cover_lands_over_an_album_that_holds_a_link_to_another_albums_track_and_that_file_stays(
            self) -> None:
        # A file that is a link is no track of the album, wherever it leads: this one names a file under the
        # library's root, another album's track. A picture embedded through it would change that album in
        # place, with no copy to put back. The draft is the page's, every track the album's page lists.
        path, tracks = self.path("ecliptica"), self.tracks("ecliptica")
        link, theirs = self.lay_linked_track(path, "04. Weballergy.mp3",
                                             to=self.shelf / self.path("silence") / self.tracks("silence")[0])
        page = self.answer(address(path))
        self.assertEqual([track["path"] for track in page["tracks"]], list(tracks))
        self.assertNotIn(link.name, page["unreadable"])
        draft = self.cover_draft(path, self.upload(image(1000, 1000))["cover"])
        # By a digest: a failure prints a line and not two files.
        was = saves.digest(theirs.read_bytes())
        before = self.on_disk()

        found = self.settle(self.accepted(draft))

        self.assertEqual(saves.digest(theirs.read_bytes()), was,
                         "the picture was embedded through the link, into another album's file")
        self.assertEqual((found["state"], found["error"]), ("done", None))
        self.assertTrue(link.is_symlink(), "a file took the place of the link in the library")
        self.assertEqual(os.readlink(link), str(theirs))
        self.assertPicture(self.cover_of(path), (1000, 1000), RED_BLUE, "cover.jpg")
        for track in tracks:
            self.assertOneFront(self.shelf / path / track, (1000, 1000), RED_BLUE)
        # The album's cover and its own tracks, and nothing of the album the link names.
        self.assertEqual(self.differing(before, self.on_disk()),
                         sorted(f"shelf/{path}/{name}" for name in ("cover.jpg", *tracks)))


class RefusesACoverItCannotSave(SaveCase):
    def turns_down(self, draft: dict[str, Any], what: str) -> None:
        """A save of `draft` is refused with a sentence, and nothing in the library or the extras changed."""
        before = self.on_disk()
        got = self.send(draft)
        if got.status == 202:
            # Taken, which is the failure. The save ends before the next case looks at the disk.
            job = quote(json.loads(got.body)["job"], safe="")
            deadline = time.monotonic() + saves.DEADLINE
            while time.monotonic() < deadline and any(album["state"] not in ("done", "failed") for album in
                                                      self.answer(f"/api/library/jobs/{job}")["albums"]):
                time.sleep(0.02)
        self.refuses(got, what)
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])

    def test_a_token_that_names_no_upload_is_refused_and_nothing_is_written(self) -> None:
        path = self.path("ecliptica")
        token = self.upload(image(900, 900))["cover"]
        for name, stranger in strangers(self.shelf / path, token).items():
            with self.subTest(name, token=stranger):
                # With a tag edit no earlier case made, so a server that drops the token has something to save.
                self.turns_down(self.cover_draft(path, stranger, edit(set={"Composer": [f"Tony Kakko, {name}"]})),
                                f"a save of {stranger!r}")

    def test_a_cover_over_the_tracks_of_two_albums_is_refused_and_nothing_is_written(self) -> None:
        token = self.upload(image(900, 900))["cover"]
        # The tag edit alone is a batch the server takes. With a cover, no album can be the one it is for.
        composer = edit(set={"Composer": ["Tony Kakko"]})
        draft = self.cover_draft(self.path("ecliptica"), token, composer)
        other = self.cover_draft(self.path("silence"), token, composer)
        draft["tracks"] += other["tracks"]
        draft["edits"] += other["edits"]
        self.turns_down(draft, "a save of one cover over two albums")


if __name__ == "__main__":
    unittest.main()
