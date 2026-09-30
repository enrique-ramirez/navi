"""The owner's cover: uploaded into the job, measured against the library's test, and made the album's.

The owner drops an image onto the cover. `PUT
/api/drops/<drop>/albums/<n>/cover` stores each upload under a name of its
own, `owner/cover-<first 8 hex of its sha256>.<ext>`, and answers the cover
test (ratio 0.9 to 1.1, shorter side 500 px or more) with that `path`; a cover
that fails is still kept, and the answer says how it fails. Earlier uploads
stay, so a second one is a new path the page must send, never a changed file
under a path an accepted plan already names. The album view and `GET
.../cover` show the plan's cover until a decision naming the upload has been
identified; from then on they show the owner's, and the plan's `cover.jpg` is
that image whatever the test said.

The album and server are `tests.test_agitha_decision`'s. Images are made
here with Pillow, each a size the fixture cover (1600 x 900) is not.
"""

from __future__ import annotations

import io
import json
import subprocess
import unittest

from PIL import Image

from musiclib.cache import Cache
from tests import builders
from tests.test_agitha_decision import ALBUM, CLEAN_ID, DROP, PYTHON, STUB, AlbumCase, accept, sha256

URL = f"/api/drops/{DROP}/albums/01/cover"

#: Content type -> the extension the job keeps it under, and Pillow's name for the format.
TYPES = {
    "image/png": ("png", "PNG"),
    "image/jpeg": ("jpg", "JPEG"),
    "image/webp": ("webp", "WEBP"),
    "image/gif": ("gif", "GIF"),
}


#: The cover dropped with the album, which the plan's `cover.jpg` is until the owner's replaces it.
PLANNED = builders.FIXTURES / "cover.jpg"


def stored_as(data: bytes, content_type: str) -> str:
    return f"owner/cover-{sha256(data)[:8]}.{TYPES[content_type][0]}"


def image(width: int, height: int, content_type: str = "image/png") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (180, 40, 60)).save(out, TYPES[content_type][1])
    return out.getvalue()


class CoverCase(AlbumCase):
    def put_cover(self, data: bytes, content_type: str) -> tuple[int, dict]:
        status, _type, raw = self.request("PUT", URL, data, {"Content-Type": content_type})
        body = json.loads(raw) if raw else {}
        if status == 200:
            self.assertIn("path", body, "the answer names where the upload was stored")
        return status, body

    def owner_files(self) -> dict[str, bytes]:
        """Every file under the job's `owner/`, by its path relative to the job."""
        folder = self.job / "owner"
        return {f"owner/{p.name}": p.read_bytes() for p in folder.iterdir()} if folder.is_dir() else {}

    def assertShowsThePlannedCover(self) -> None:
        with Image.open(PLANNED) as planned:
            size = planned.size
        cover = self.view()["cover"]
        self.assertEqual((cover["url"], cover["width"], cover["height"]), (URL, *size))
        self.assertEqual(self.served(), (200, "image/jpeg", PLANNED.read_bytes()))

    def choose(self, path: str) -> dict:
        """Sends an accept naming `path` as the cover and answers the view once identify has run."""
        decision = accept(CLEAN_ID, edits={}, game=None, cover=path)
        status, body = self.post_decision(decision)
        self.assertEqual(status, 202, body)
        view = self.finish()
        self.assertEqual(view["decision"], decision)
        self.assertIsNone(view["error"])
        return view

    def served(self) -> tuple[int, str, bytes]:
        status, content_type, body = self.request("GET", URL)
        return status, content_type.split(";")[0].strip(), body


class Uploading(CoverCase):
    def test_a_square_600_px_png_passes_and_is_stored_under_its_own_name(self) -> None:
        data = image(600, 600)
        status, body = self.put_cover(data, "image/png")
        self.assertEqual(status, 200, body)
        path = stored_as(data, "image/png")
        self.assertEqual(body, {"width": 600, "height": 600, "passes": True, "problem": None, "path": path})
        self.assertEqual(self.owner_files(), {path: data})

    def test_a_400_by_300_jpeg_fails_the_test_saying_how_and_is_still_stored(self) -> None:
        data = image(400, 300, "image/jpeg")
        status, body = self.put_cover(data, "image/jpeg")
        self.assertEqual(status, 200, body)
        self.assertEqual((body["width"], body["height"], body["passes"]), (400, 300, False))
        # It fails both halves of the test; the sentence names at least one.
        problem = body["problem"]
        self.assertIsInstance(problem, str)
        self.assertTrue("500" in problem or "ratio" in problem.lower(), problem)
        self.assertEqual(body["path"], stored_as(data, "image/jpeg"))
        self.assertEqual(self.owner_files(), {body["path"]: data})

    def test_every_upload_is_kept_under_its_own_path_whatever_its_type(self) -> None:
        # Two PNGs: the same type must still give two files, or a later upload
        # would change the image under a path an accepted plan names.
        uploads = [(image(510, 510), "image/png"), (image(520, 520), "image/png"),
                   (image(530, 530, "image/jpeg"), "image/jpeg"), (image(540, 540, "image/webp"), "image/webp"),
                   (image(550, 550, "image/gif"), "image/gif")]
        kept: dict[str, bytes] = {}
        for data, content_type in uploads:
            with self.subTest(content_type=content_type, size=len(data)):
                status, body = self.put_cover(data, content_type)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["path"], stored_as(data, content_type))
                self.assertNotIn(body["path"], kept)
                kept[body["path"]] = data
                self.assertEqual(self.owner_files(), kept)
        self.assertEqual(len(kept), len(uploads))


class Showing(CoverCase):
    def test_an_upload_is_shown_and_served_only_once_a_decision_naming_it_has_been_identified(self) -> None:
        data = image(600, 600)
        status, body = self.put_cover(data, "image/png")
        self.assertEqual(status, 200, body)
        # Uploaded and not yet in any plan: the view is still the plan's.
        self.assertShowsThePlannedCover()

        view = self.choose(body["path"])
        self.assertEqual(view["preview"]["inputs"]["owner_cover"]["path"], body["path"])
        self.assertEqual(view["cover"], {"url": URL, "width": 600, "height": 600, "passes": True, "problem": None})
        self.assertEqual(self.served(), (200, "image/png", data))

    def test_a_second_upload_of_the_same_type_changes_nothing_shown_until_its_path_is_chosen(self) -> None:
        first, second = image(600, 600), image(700, 700)
        _status, one = self.put_cover(first, "image/png")
        self.choose(one["path"])
        status, two = self.put_cover(second, "image/png")
        self.assertEqual(status, 200, two)
        self.assertNotEqual(two["path"], one["path"])

        # The accepted plan names the first, so the first is still what is
        # shown, and it is still on disk unchanged.
        view = self.view()
        self.assertEqual((view["cover"]["width"], view["cover"]["height"]), (600, 600))
        self.assertEqual(self.served(), (200, "image/png", first))
        self.assertEqual(self.owner_files(), {one["path"]: first, two["path"]: second})

        view = self.choose(two["path"])
        self.assertEqual(view["preview"]["inputs"]["owner_cover"]["path"], two["path"])
        self.assertEqual((view["cover"]["width"], view["cover"]["height"]), (700, 700))
        self.assertEqual(self.served(), (200, "image/png", second))


class TheTest(CoverCase):
    def test_the_answer_applies_the_librarys_bounds_ratio_0_9_to_1_1_and_500_px(self) -> None:
        # Width x height -> passes. Each failing size fails one half only, so
        # a test that drops either half lets one through.
        cases = {
            (500, 500): True, (499, 499): False,
            (540, 600): True, (530, 600): False,
            (660, 600): True, (670, 600): False,
        }
        for (width, height), passes in cases.items():
            with self.subTest(size=f"{width}x{height}"):
                status, body = self.put_cover(image(width, height), "image/png")
                self.assertEqual(status, 200, body)
                self.assertEqual((body["width"], body["height"], body["passes"]), (width, height, passes))
                if passes:
                    self.assertIsNone(body["problem"])
                else:
                    self.assertIsInstance(body["problem"], str)
                    self.assertNotEqual(body["problem"].strip(), "")

    def test_the_problem_says_which_half_of_the_test_fails(self) -> None:
        status, small = self.put_cover(image(400, 400), "image/png")
        self.assertEqual(status, 200, small)
        status, oblong = self.put_cover(image(1000, 600), "image/png")
        self.assertEqual(status, 200, oblong)
        self.assertIs(small["passes"], False)
        self.assertIs(oblong["passes"], False)
        self.assertIn("500", small["problem"])
        # The wording is free; two different failures must not read the same.
        self.assertNotEqual(small["problem"], oblong["problem"])


class Refusing(CoverCase):
    def test_another_content_type_is_415_and_stores_nothing(self) -> None:
        status, body = self.put_cover(image(600, 600), "text/plain")
        self.assertEqual(status, 415, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertEqual(self.owner_files(), {})

    def test_bytes_that_are_not_an_image_are_400_and_store_nothing(self) -> None:
        # The second starts like a PNG, so a check of the first bytes alone lets it through.
        for name, data in (("text", b"not an image at all\n"), ("PNG signature only", b"\x89PNG\r\n\x1a\n" + b"x" * 64)):
            with self.subTest(name):
                status, body = self.put_cover(data, "image/png")
                self.assertEqual(status, 400, body)
                self.assertIsInstance(body.get("error"), str)
                self.assertEqual(self.owner_files(), {})

    def test_an_upload_while_identify_runs_is_409_and_stores_nothing(self) -> None:
        self.hold()
        status, body = self.post_decision(accept(edits={}, game=None))
        self.assertEqual(status, 202, body)
        status, body = self.put_cover(image(600, 600), "image/png")
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertEqual(self.owner_files(), {})
        self.finish()


class TheOwnersCoverWins(CoverCase):
    def test_a_decision_naming_the_uploaded_cover_makes_it_the_plans_cover_though_it_fails_the_test(self) -> None:
        planned = self.entry["images"]["cover.jpg"]["sha256"]
        data = image(400, 300, "image/jpeg")
        # A JPEG is kept as it is, so the plan's digest is the upload's.
        self.assertNotEqual(sha256(data), planned)
        status, body = self.put_cover(data, "image/jpeg")
        self.assertEqual(status, 200, body)
        self.assertIs(body["passes"], False)

        view = self.choose(body["path"])
        preview = view["preview"]
        self.assertEqual(preview["images"]["cover.jpg"]["sha256"], sha256(data))
        self.assertEqual(preview["inputs"]["owner_cover"]["path"], body["path"])
        self.assertEqual((view["cover"]["width"], view["cover"]["height"], view["cover"]["passes"]), (400, 300, False))


class ThePlannedCover(CoverCase):
    """The plan's `cover.jpg` is shown however the engine came by it, byte for byte what it writes."""

    def identify_again(self) -> dict:
        found = subprocess.run([PYTHON, str(STUB), *self.identify_argv()], capture_output=True, text=True)
        self.assertEqual(found.returncode, 0, found.stderr)
        return self.view()

    def assertServesThePlan(self, view: dict, size: tuple[int, int]) -> None:
        planned = view["preview"]["images"]["cover.jpg"]
        self.assertEqual((view["cover"]["url"], view["cover"]["width"], view["cover"]["height"]), (URL, *size))
        status, content_type, body = self.served()
        self.assertEqual((status, content_type), (200, "image/jpeg"))
        self.assertEqual((sha256(body), len(body)), (planned["sha256"], planned["length"]))

    def test_a_folder_png_the_engine_converts_is_shown_as_the_jpeg_it_becomes(self) -> None:
        folder = self.inbox / DROP / "01" / "drop" / "album" / ALBUM
        (folder / "cover.jpg").unlink()
        (folder / "cover.png").write_bytes(image(600, 600))
        self.assertServesThePlan(self.identify_again(), (600, 600))

    def test_a_cover_archive_download_in_the_jobs_cache_is_shown_before_it_is_written(self) -> None:
        # Where the engine keeps an archive front it fetched; nothing in the folder is that image.
        data = image(700, 700, "image/jpeg")
        Cache(self.job / "cache").fetch(f"https://coverartarchive.org/release/{CLEAN_ID}/1.jpg", lambda: data)
        doc = json.loads(self.plan_bytes)
        doc["albums"][0]["images"]["cover.jpg"] = {"length": len(data), "sha256": sha256(data)}
        (self.job / "plan.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertServesThePlan(self.view(), (700, 700))

    def test_no_cover_in_the_plan_is_null_and_404(self) -> None:
        doc = json.loads(self.plan_bytes)
        doc["albums"][0]["images"] = {}
        (self.job / "plan.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertIsNone(self.view()["cover"])
        self.assertEqual(self.served()[0], 404)


NOW = f"{URL}/now"


class TheCurrentCover(CoverCase):
    """`cover_now` is the album as dropped: the first track's picture, else the folder's image."""

    def folder(self):
        return self.inbox / DROP / "01" / "drop" / "album" / ALBUM

    def served_now(self) -> tuple[int, str, bytes]:
        status, content_type, body = self.request("GET", NOW)
        return status, content_type.split(";")[0].strip(), body

    def test_the_first_tracks_embedded_picture_comes_before_the_folders_image(self) -> None:
        data = image(640, 480, "image/jpeg")
        builders.embed_picture(self.folder() / "01 one.mp3", data)
        cover = self.view()["cover_now"]
        self.assertEqual(cover["url"], NOW)
        self.assertEqual((cover["width"], cover["height"], cover["passes"]), (640, 480, False))
        self.assertIsInstance(cover["problem"], str)
        self.assertEqual(self.served_now(), (200, "image/jpeg", data))

    def test_with_nothing_embedded_it_is_the_folders_cover(self) -> None:
        cover = self.view()["cover_now"]
        self.assertEqual((cover["url"], cover["width"], cover["height"]), (NOW, 1600, 900))
        self.assertEqual(self.served_now(), (200, "image/jpeg", PLANNED.read_bytes()))

    def test_with_no_picture_anywhere_it_is_null_and_404(self) -> None:
        (self.folder() / "cover.jpg").unlink()
        self.assertIsNone(self.view()["cover_now"])
        self.assertEqual(self.served_now()[0], 404)


if __name__ == "__main__":
    unittest.main()
