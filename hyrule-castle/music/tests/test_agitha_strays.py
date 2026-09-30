"""Files outside the album's rules, as the server shows them and as they hold or free an album.

The server harness is `tests.test_agitha_decision`'s: one album staged the
way agitha stages it, identified once by `tests/agitha_stub.py` (the real
engine over a fake MusicBrainz), served over HTTP with a `musiclib` wrapper
that records each call.
"""

from __future__ import annotations

import io
import json
import mimetypes
import time
import unittest
from urllib.parse import quote

from PIL import Image

from musiclib import strays
from tests import builders
from tests.test_agitha_decision import DROP, SECONDS, AlbumCase, accept

LONG_SIDE = 320
#: How far a JPEG's centre pixel may drift from the colour it was drawn in.
COLOUR_TOLERANCE = 16


def picture(fmt: str, size: tuple[int, int], colour: tuple[int, int, int], mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    fill = (*colour, 255) if mode == "RGBA" else colour
    Image.new(mode, size, fill).save(out, fmt)
    return out.getvalue()


#: One stray per format, each larger than the thumbnail and in its own colour, so a thumbnail of the wrong
#: file is told apart. The PNG has an alpha channel, which JPEG cannot hold.
IMAGES = {
    "COVERS/Bowie00001.jpg": (picture("JPEG", (1200, 800), (200, 30, 30)), (200, 30, 30)),
    "COVERS/Bowie00002.png": (picture("PNG", (500, 900), (30, 200, 30), mode="RGBA"), (30, 200, 30)),
    "COVERS/Bowie00003.tif": (picture("TIFF", (640, 480), (30, 30, 200)), (30, 30, 200)),
    "COVERS/Bowie00004.bmp": (picture("BMP", (700, 400), (220, 220, 40)), (220, 220, 40)),
    # A space and a Cyrillic folder, sent percent-encoded.
    "сканы/Bowie 5.jpg": (picture("JPEG", (400, 1000), (40, 200, 200)), (40, 200, 200)),
}


class StrayAlbum(AlbumCase):
    def stray_url(self, path: str, n: str = "01") -> str:
        return f"/api/drops/{DROP}/albums/{n}/strays/{quote(path)}"

    def row(self, preview: dict, path: str) -> dict:
        rows = [row for row in preview.get("strays", []) if row["path"] == path]
        self.assertEqual(len(rows), 1, preview.get("strays"))
        return rows[0]


class Thumbnails(StrayAlbum):
    """The thumbnail route, over an entry whose `strays` lists the files in `IMAGES`."""

    files = {path: data for path, (data, _colour) in IMAGES.items()}

    def setUp(self) -> None:
        super().setUp()
        # The route serves what the entry lists. The rows are written here as the engine writes them, so these
        # cases read the route alone and not the engine's settling of strays.
        plan = json.loads(self.plan_bytes)
        plan["albums"][0]["strays"] = [
            {"path": path, "kind": strays.kind(path), "answer": None, "why": "no guess", "against": None,
             "size": list(Image.open(io.BytesIO(data)).size)}
            for path, (data, _colour) in IMAGES.items()]
        (self.job / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def test_each_stray_image_answers_a_jpeg_of_itself_at_most_320_px_on_its_long_side(self) -> None:
        for path, (_data, colour) in IMAGES.items():
            with self.subTest(path):
                status, content_type, raw = self.request("GET", self.stray_url(path))
                self.assertEqual(status, 200, raw[:300])
                self.assertEqual(content_type.split(";")[0], "image/jpeg")
                thumbnail = Image.open(io.BytesIO(raw))
                self.assertEqual(thumbnail.format, "JPEG")
                self.assertLessEqual(max(thumbnail.size), LONG_SIDE, thumbnail.size)
                centre = thumbnail.convert("RGB").getpixel((thumbnail.width // 2, thumbnail.height // 2))
                for got, want in zip(centre, colour):
                    self.assertAlmostEqual(got, want, delta=COLOUR_TOLERANCE, msg=f"centre {centre}, drawn {colour}")

    def test_full_answers_the_files_own_bytes_and_type(self) -> None:
        for path, (data, _colour) in IMAGES.items():
            with self.subTest(path):
                status, content_type, raw = self.request("GET", self.stray_url(path) + "?full")
                self.assertEqual(status, 200, raw[:300])
                self.assertEqual(content_type.split(";")[0], mimetypes.guess_type(path)[0])
                self.assertEqual(raw, data)

    def test_a_path_outside_the_album_or_not_a_stray_is_404(self) -> None:
        stray = "COVERS/Bowie00001.jpg"
        # The same route answers for a stray, so each 404 below is about the path and not a missing route.
        for suffix in ("", "?full"):
            status, _type, raw = self.request("GET", self.stray_url(stray) + suffix)
            self.assertEqual(status, 200, raw[:300])

        # Listed in the entry, and gone from the folder since identify.
        gone = "сканы/Bowie 5.jpg"
        (self.album_folder / gone).unlink()
        absolute = str(self.album_folder / stray)
        cases = [
            ("a climb", f"/api/drops/{DROP}/albums/01/strays/COVERS/../cover.jpg"),
            # The absolute path of a real stray: joined to the album folder it lands inside it.
            ("an absolute path", f"/api/drops/{DROP}/albums/01/strays/{quote(absolute)}"),
            ("an encoded absolute path", f"/api/drops/{DROP}/albums/01/strays/{quote(absolute, safe='')}"),
            ("a track", self.stray_url("01 one.mp3")),
            ("an image that is not a stray", self.stray_url("cover.jpg")),
            ("a stray whose file is gone", self.stray_url(gone)),
        ]
        for name, url in cases:
            for suffix in ("", "?full"):
                with self.subTest(name, full=bool(suffix)):
                    status, content_type, raw = self.request("GET", url + suffix)
                    self.assertEqual(status, 404, raw[:300])
                    self.assertEqual(content_type, "application/json; charset=utf-8")
                    self.assertIsInstance(json.loads(raw).get("error"), str)


STRAY = "COVERS/Bowie00001.jpg"
STRAY_BYTES = builders.jpeg(700, 700)


class Holding(StrayAlbum):
    """One `COVERS/` stray with no guess, in an album the accept would otherwise leave approvable."""

    files = {STRAY: STRAY_BYTES}

    def approve(self) -> tuple[int, dict]:
        status, _type, raw = self.request("POST", f"/api/drops/{DROP}/albums/01/approve", b"{}",
                                          {"Content-Type": "application/json"})
        return status, (json.loads(raw) if raw else {})

    def decided(self, strays_map: dict) -> dict:
        """The view once an accept carrying `strays_map` is identified; asserts Approve is offered."""
        status, body = self.post_decision(accept(edits={}, game=None, strays=strays_map))
        self.assertEqual(status, 202, body)
        view = self.finish()
        self.assertIsNone(view["error"])
        details = [hold.get("detail") or "" for hold in view["preview"]["holds"]]
        self.assertFalse([d for d in details if "subfolder" in d or "image in disc folder" in d], details)
        self.assertEqual(view["approvable"], {"ok": True, "reason": None, "code": None, "hold": None})
        return view

    def test_approve_is_refused_while_the_covers_stray_is_undecided(self) -> None:
        status, body = self.post_decision(accept(edits={}, game=None))
        self.assertEqual(status, 202, body)
        view = self.finish()

        self.assertIsNone(self.row(view["preview"], STRAY)["answer"])
        approvable = view["approvable"]
        self.assertEqual((approvable["ok"], approvable["code"]), (False, "held"), approvable)
        self.assertIn("subfolder: COVERS", approvable["hold"]["detail"])

        status, body = self.approve()
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertEqual([argv[1] for argv in self.calls()], ["identify"])
        # Left where it is: the library has nothing and the stray has not moved.
        self.assertEqual([p for p in self.root.joinpath("library").rglob("*")], [])
        self.assertEqual((self.album_folder / STRAY).read_bytes(), STRAY_BYTES)

    def test_a_deleted_stray_frees_the_album_and_approve_is_offered(self) -> None:
        view = self.decided({STRAY: None})
        self.assertEqual(self.row(view["preview"], STRAY)["answer"], {"delete": True})

    def test_a_named_stray_frees_the_album_and_it_lands_under_that_name_with_no_covers_folder(self) -> None:
        view = self.decided({STRAY: "booklet-01.jpg"})
        row = self.row(view["preview"], STRAY)
        self.assertEqual((row["answer"], row["why"]), ({"keep": "booklet-01.jpg"}, "owner"))
        destination = view["preview"]["destination"]

        status, body = self.approve()
        self.assertEqual(status, 202, body)
        self.wait_gone()

        landed = self.root / "library" / destination
        self.assertTrue(landed.is_dir(), destination)
        self.assertEqual((landed / "booklet-01.jpg").read_bytes(), STRAY_BYTES)
        self.assertFalse((landed / "COVERS").exists())
        self.assertEqual([p for p in landed.rglob("*") if p.is_dir()], [])
        self.assertEqual([argv[1] for argv in self.calls()], ["identify", "apply"])

    def wait_gone(self) -> None:
        """Polls `GET /api/drops` until album 01 has left the list, as a landed album does."""
        deadline = time.monotonic() + SECONDS
        while True:
            status, _type, raw = self.request("GET", "/api/drops")
            self.assertEqual(status, 200, raw[:300])
            albums = [a for d in json.loads(raw) if d["id"] == DROP for a in d["albums"] if a["n"] == "01"]
            if not albums:
                return
            if albums[0]["state"] in ("apply failed", "written, not moved"):
                self.fail(f"the approve did not land: {albums[0]}")
            if time.monotonic() > deadline:
                self.fail(f"gave up waiting; last seen: {albums[0]}")
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
