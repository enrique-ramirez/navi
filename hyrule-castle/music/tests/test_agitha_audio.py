"""An album's data and its files' audio facts, as the album view gets them.

For a track the view shows its format, lossless or lossy, bitrate, sample
rate, bit depth where there is one, channels, length, size, and its path now
and after. `agitha.audio.facts` reads those from the file; the truth here is
what mutagen itself reports for each fixture, never a number copied from a
run.

`GET /api/drops/<drop>/albums/<n>` answers the preview, the
full path the album will have, the album folder as it will land, the files
that go to extras with their path there, and the status. The inbox and job
are laid out by hand the way agitha stages them, and the plan is the engine's
own (`tests/fixtures/agitha/auto-clean/plan.json`), copied as it is.

A binary frame shows as its kind and size. The engine records
one as a digest (`musiclib.files.snapshot`), so the size comes from the file.
"""

from __future__ import annotations

import copy
import hashlib
import io
import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import mutagen
from mutagen.id3 import ID3, TIT2
from PIL import Image

from agitha.audio import facts
from agitha.server import Config, make_server
from musiclib import files as engine_files
from musiclib.mapping import READABLE, readable_name
from tests import builders

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUB = Path(__file__).resolve().parent / "agitha_stub.py"
AUTO_CLEAN = FIXTURES / "agitha" / "auto-clean" / "plan.json"

LENGTH_TOLERANCE = 0.01

#: fixture -> (format, family, lossless)
EXPECTED = {
    "tone.flac": ("FLAC", "vorbis", True),
    "tone.mp3": ("MP3", "id3", False),
    "tone.m4a": ("MP4", "mp4", False),
    "tone.ogg": ("Ogg Vorbis", "vorbis", False),
    "tone.wma": ("WMA", "asf", False),
}


def truth(path: Path) -> dict:
    """What mutagen and the filesystem say about `path`, the numbers `facts` must agree with."""
    info = mutagen.File(path).info
    return {
        "bitrate": info.bitrate,
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "length": info.length,
        "bits_per_sample": getattr(info, "bits_per_sample", None),
        "size": path.stat().st_size,
    }


class Facts(unittest.TestCase):
    def test_each_fixture_reports_its_format_family_and_whether_it_is_lossless(self) -> None:
        for name, (format_, family, lossless) in EXPECTED.items():
            with self.subTest(name=name):
                got = facts(FIXTURES / name)
                self.assertEqual(got.format, format_)
                self.assertEqual(got.family, family)
                self.assertIs(got.lossless, lossless)

    def test_each_fixture_reports_the_numbers_mutagen_and_stat_give(self) -> None:
        for name in EXPECTED:
            with self.subTest(name=name):
                path = FIXTURES / name
                want = truth(path)
                got = facts(path)
                self.assertEqual(got.sample_rate, want["sample_rate"])
                self.assertEqual(got.channels, want["channels"])
                self.assertEqual(got.bitrate, want["bitrate"])
                self.assertAlmostEqual(got.length, want["length"], delta=LENGTH_TOLERANCE)
                self.assertEqual(got.size, want["size"])

    def test_flac_has_a_bit_depth_and_lossy_formats_have_none(self) -> None:
        # types.ts: `bit_depth` is null for a lossy format. The AAC fixture's
        # MP4 header carries 16 bits per sample anyway, and that number is
        # not a bit depth the owner should read as the rip's.
        flac = facts(FIXTURES / "tone.flac")
        self.assertEqual(flac.bit_depth, truth(FIXTURES / "tone.flac")["bits_per_sample"])
        self.assertIsNotNone(flac.bit_depth)
        for name in ("tone.mp3", "tone.m4a", "tone.ogg", "tone.wma"):
            with self.subTest(name=name):
                self.assertIsNone(facts(FIXTURES / name).bit_depth)

    def test_a_file_that_is_not_audio_gives_none(self) -> None:
        # None, not an exception, so the view can skip a stray file without a
        # try around it.
        self.assertIsNone(facts(FIXTURES / "cover.jpg"))


DROP = "20260929-210000"
EXTRAS_DROP = "20260929-210000-2"
PICTURE_DROP = "20260929-210000-3"
OWNER_UNUSED_DROP = "20260929-210000-4"
OWNER_USED_DROP = "20260929-210000-5"
ALBUM = "Clean Album"
TRACKS = ["01 one.mp3", "02 two.mp3", "03 three.mp3"]
EXTRA = f"drop/album/{ALBUM}/Scans/booklet.pdf"
KEPT = f"drop/album/{ALBUM}/Artwork/back.jpg"


def stage_album(inbox: Path, drop: str, n: str, name: str, record: dict) -> Path:
    """`inbox/<drop>/<n>/drop/album/<name>/` and `album.json`, as agitha leaves an album after staging."""
    (inbox / drop).mkdir(parents=True, exist_ok=True)
    (inbox / drop / "drop.json").write_text(json.dumps({
        "started": "2026-09-29T21:00:00", "done": True,
        "items": [{"name": name, "kind": "folder", "files": []}],
    }), encoding="utf-8")
    folder = inbox / drop / n / "drop" / "album" / name
    folder.mkdir(parents=True)
    (inbox / drop / n / "album.json").write_text(json.dumps(
        {"n": n, "name": name, "item": name, **record}), encoding="utf-8")
    return folder


def png(side: int, colour: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (side, side), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def owner_name(data: bytes) -> str:
    """`cover-<sha8>.png`, the name an owner cover is kept under in the job's `owner/`."""
    return f"cover-{hashlib.sha256(data).hexdigest()[:8]}.png"


def stage_tracks(folder: Path) -> None:
    for index, track in enumerate(TRACKS, start=1):
        path = folder / track
        shutil.copyfile(FIXTURES / "tone.mp3", path)
        # A tag padded differently per track gives each file its own size,
        # so a size read from the wrong file shows.
        tags = ID3()
        tags.add(TIT2(encoding=3, text=[track]))
        tags.save(path, padding=lambda _info, index=index: index * 700)
    shutil.copyfile(FIXTURES / "cover.jpg", folder / "cover.jpg")


class AlbumView(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        folders = {name: cls.root / name for name in ("inbox", "jobs", "library", "extras", "static")}
        for folder in folders.values():
            folder.mkdir()
        (folders["static"] / "index.html").write_bytes(b"<!doctype html>\n")
        cls.folders = folders
        cls.plan = json.loads(AUTO_CLEAN.read_text(encoding="utf-8"))
        cls.entry = cls.plan["albums"][0]

        ready = {"state": "ready", "stderr": "", "error": None}
        cls.album = stage_album(folders["inbox"], DROP, "01", ALBUM, ready)
        stage_tracks(cls.album)
        job = folders["jobs"] / f"agitha-{DROP}-01"
        job.mkdir()
        shutil.copyfile(AUTO_CLEAN, job / "plan.json")

        # 02 failed identify: album.json is all there is, no job.
        cls.failed = {"state": "identify failed", "stderr": "musiclib: line 1\nmusiclib: line 2",
                      "error": "identify stopped with an error."}
        failed = stage_album(folders["inbox"], DROP, "02", "Other Album", cls.failed)
        shutil.copyfile(FIXTURES / "tone.mp3", failed / "01 x.mp3")

        # A second drop whose plan sends a file to extras and keeps another,
        # with its files listed in reverse so plan order differs from sorted.
        cls.extras_album = stage_album(folders["inbox"], EXTRAS_DROP, "01", ALBUM, ready)
        stage_tracks(cls.extras_album)
        for rel in (EXTRA, KEPT):
            target = cls.extras_album / PurePosixPath(rel).relative_to(f"drop/album/{ALBUM}")
            target.parent.mkdir(parents=True)
            target.write_bytes(b"not audio\n")
        cls.extras_plan = copy.deepcopy(cls.plan)
        extras_entry = cls.extras_plan["albums"][0]
        extras_entry["extras"] = [EXTRA]
        extras_entry["kept"] = [KEPT]
        extras_entry["files"] = list(reversed(extras_entry["files"]))
        extras_job = folders["jobs"] / f"agitha-{EXTRAS_DROP}-01"
        extras_job.mkdir()
        (extras_job / "plan.json").write_text(json.dumps(cls.extras_plan, indent=1), encoding="utf-8")

        config = Config(
            inbox=folders["inbox"], jobs=folders["jobs"], library=folders["library"],
            extras=folders["extras"], musiclib=str(STUB), static=folders["static"],
            port=0, host="127.0.0.1",
        )
        cls.stage_pictures()
        cls.stage_owner_covers()
        cls.server = make_server(config)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.view = cls.get_json(f"/api/drops/{DROP}/albums/01")
        cls.extras_view = cls.get_json(f"/api/drops/{EXTRAS_DROP}/albums/01")
        cls.picture_view = cls.get_json(f"/api/drops/{PICTURE_DROP}/albums/01")

    @classmethod
    def stage_pictures(cls) -> None:
        """A third drop whose first track has one picture and second has two, of three sizes.

        Each file's `before` carries what the engine itself records for its
        pictures, and the first file's `after` keeps its picture.
        """
        cls.picture_album = stage_album(cls.folders["inbox"], PICTURE_DROP, "01", ALBUM,
                                        {"state": "ready", "stderr": "", "error": None})
        stage_tracks(cls.picture_album)
        one, two = cls.picture_album / TRACKS[0], cls.picture_album / TRACKS[1]
        builders.embed_picture(one, builders.embedded_cover())
        builders.embed_picture(two, builders.jpeg(300, 300))
        builders.embed_picture(two, builders.jpeg(40, 40))
        cls.picture_plan = copy.deepcopy(cls.plan)
        planned = cls.picture_plan["albums"][0]["files"]
        for path, entry in ((one, planned[0]), (two, planned[1])):
            for key, value in engine_files.read(path).tags.items():
                if key.startswith("APIC:"):
                    entry["before"][key] = value
        first = next(key for key in planned[0]["before"] if key.startswith("APIC:"))
        planned[0]["after"][first] = planned[0]["before"][first]
        job = cls.folders["jobs"] / f"agitha-{PICTURE_DROP}-01"
        job.mkdir()
        (job / "plan.json").write_text(json.dumps(cls.picture_plan, indent=1), encoding="utf-8")

    @classmethod
    def stage_owner_covers(cls) -> None:
        """Two drops whose jobs hold owner covers in `owner/`: one plan names none, the other names one.

        In the first, a 600 x 600 PNG sits in `owner/` under the name today's
        upload gives it and under its `cover-<sha8>` name, and the plan is
        the fixture's, whose cover is the dropped 1600 x 900 JPEG. In the
        second, `owner/` holds two owner covers and the plan names the one
        that sorts last, so taking the first file found shows.
        """
        ready = {"state": "ready", "stderr": "", "error": None}
        cls.owner_png = png(600, (200, 40, 40))
        other = png(700, (40, 40, 200))

        stage_tracks(stage_album(cls.folders["inbox"], OWNER_UNUSED_DROP, "01", ALBUM, ready))
        job = cls.folders["jobs"] / f"agitha-{OWNER_UNUSED_DROP}-01"
        (job / "owner").mkdir(parents=True)
        (job / "owner" / "cover.png").write_bytes(cls.owner_png)
        (job / "owner" / owner_name(cls.owner_png)).write_bytes(cls.owner_png)
        shutil.copyfile(AUTO_CLEAN, job / "plan.json")

        stage_tracks(stage_album(cls.folders["inbox"], OWNER_USED_DROP, "01", ALBUM, ready))
        job = cls.folders["jobs"] / f"agitha-{OWNER_USED_DROP}-01"
        (job / "owner").mkdir(parents=True)
        (job / "owner" / owner_name(cls.owner_png)).write_bytes(cls.owner_png)
        (job / "owner" / owner_name(other)).write_bytes(other)
        # Swap the two if needed so the named cover is not the first in name order.
        cls.used_png, cls.unused_png = (cls.owner_png, other) \
            if owner_name(cls.owner_png) > owner_name(other) else (other, cls.owner_png)
        plan = copy.deepcopy(cls.plan)
        entry = plan["albums"][0]
        entry["inputs"]["owner_cover"] = {"path": f"owner/{owner_name(cls.used_png)}",
                                          "sha256": hashlib.sha256(cls.used_png).hexdigest()}
        entry["images"]["cover.jpg"] = {"length": len(cls.used_png),
                                        "sha256": hashlib.sha256(cls.used_png).hexdigest()}
        (job / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)
        shutil.rmtree(cls.root)

    @classmethod
    def fetch(cls, path: str) -> tuple[int, str, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.headers.get("Content-Type", ""), response.read()
        finally:
            connection.close()

    @classmethod
    def get_json(cls, path: str) -> dict | None:
        status, _type, body = cls.fetch(path)
        return json.loads(body) if status == 200 else {"status": status, "body": body.decode("utf-8", "replace")}

    def test_the_album_answers_200_json(self) -> None:
        status, content_type, _body = self.fetch(f"/api/drops/{DROP}/albums/01")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")

    def test_the_view_names_the_album_and_carries_its_record(self) -> None:
        view = self.view
        self.assertEqual(view["drop"], DROP)
        self.assertEqual(view["n"], "01")
        self.assertEqual(view["name"], ALBUM)
        self.assertEqual(view["state"], "ready")
        self.assertEqual(view["stderr"], "")
        self.assertIsNone(view["error"])
        self.assertIs(view["busy"], False)
        self.assertIsNone(view["duplicate"])
        self.assertIsNone(view["decision"])

    def test_the_preview_is_the_jobs_plan_entry(self) -> None:
        self.assertEqual(self.view["preview"], self.entry)

    def test_each_track_has_its_facts_and_paths_in_plan_order(self) -> None:
        files = self.view["files"]
        self.assertEqual([f["position"] for f in files], ["1-1", "1-2", "1-3"])
        for got, planned, track in zip(files, self.entry["files"], TRACKS):
            with self.subTest(track=track):
                self.assertEqual(got["path_now"], track)
                self.assertEqual(got["path_after"], planned["destination"])
                self.assertEqual(got["format"], "MP3")
                self.assertEqual(got["family"], "id3")
                self.assertIs(got["lossless"], False)
                self.assertIsNone(got["bit_depth"])
                want = truth(self.album / track)
                self.assertEqual(got["size"], want["size"])
                self.assertEqual(got["bitrate"], want["bitrate"])
                self.assertEqual(got["sample_rate"], want["sample_rate"])
                self.assertEqual(got["channels"], want["channels"])
                self.assertAlmostEqual(got["length"], want["length"], delta=LENGTH_TOLERANCE)

    def test_each_tracks_audio_url_is_its_dropped_path_percent_encoded(self) -> None:
        urls = [f["audio_url"] for f in self.view["files"]]
        prefix = f"/api/drops/{DROP}/albums/01/audio/"
        self.assertEqual(urls, [prefix + "01%20one.mp3", prefix + "02%20two.mp3", prefix + "03%20three.mp3"])

    def test_the_files_follow_the_plans_order_rather_than_their_names(self) -> None:
        self.assertEqual([f["path_now"] for f in self.extras_view["files"]], list(reversed(TRACKS)))
        self.assertEqual([f["position"] for f in self.extras_view["files"]], ["1-3", "1-2", "1-1"])

    def test_names_map_every_readable_key_of_each_family_and_nothing_else(self) -> None:
        names = self.view["names"]
        self.assertEqual(set(names), {"id3", "vorbis", "mp4", "asf"})
        self.assertEqual(names["id3"]["TPE2"], "Album artist")
        self.assertEqual(names["id3"]["TCOM"], "Composer")
        self.assertNotIn("TXXX:MOOD", names["id3"])
        self.assertNotIn("uploader", names["vorbis"])
        for family in names:
            with self.subTest(family=family):
                keys = {row[family] for row in READABLE.values() if row.get(family) is not None}
                self.assertEqual(names[family], {key: readable_name(family, key) for key in keys})

    def test_the_library_path_is_the_library_root_joined_to_the_destination(self) -> None:
        self.assertEqual(self.view["library_path"],
                         str(self.folders["library"] / self.entry["destination"]))

    def test_the_tree_lists_the_landing_folders_files_sorted(self) -> None:
        # The dropped cover.jpg is a deletion, but the plan writes a
        # cover.jpg of its own (`images`), so the name lands.
        self.assertEqual(self.view["tree"], ["01. One.mp3", "02. Two.mp3", "03. Three.mp3", "cover.jpg"])

    def test_the_tree_holds_kept_files_and_leaves_out_extras(self) -> None:
        # Codepoint order puts `Artwork/` before `cover.jpg`, and the plan's
        # reversed track order must not leak into the tree.
        self.assertEqual(self.extras_view["tree"],
                         ["01. One.mp3", "02. Two.mp3", "03. Three.mp3", "Artwork/back.jpg", "cover.jpg"])

    def test_no_extras_in_the_plan_gives_no_extras_targets(self) -> None:
        self.assertEqual(self.view["extras_to"], [])

    def test_an_extra_lands_under_the_extras_root_at_the_albums_destination(self) -> None:
        # musiclib's rule (`plan.relocated`, used by `write.write_album`):
        # the path under the album's source, moved under its destination, in
        # the extras tree.
        destination = self.entry["destination"]
        self.assertEqual(self.extras_view["extras_to"], [{
            "source": EXTRA,
            "path": str(self.folders["extras"] / destination / "Scans" / "booklet.pdf"),
        }])

    def test_the_planned_cover_is_measured_against_the_cover_test(self) -> None:
        # The fixture cover is 1600 x 900: its ratio fails the test.
        with Image.open(FIXTURES / "cover.jpg") as image:
            width, height = image.size
        cover = self.view["cover"]
        self.assertEqual(cover["url"], f"/api/drops/{DROP}/albums/01/cover")
        self.assertEqual((cover["width"], cover["height"]), (width, height))
        self.assertIs(cover["passes"], False)
        self.assertIsInstance(cover["problem"], str)
        self.assertNotEqual(cover["problem"].strip(), "")

    def test_an_owner_cover_the_plan_does_not_name_is_not_the_cover(self) -> None:
        # After a reload the header must show the cover apply will write:
        # an image in owner/ that the plan's inputs do not name is not it.
        cover = self.get_json(f"/api/drops/{OWNER_UNUSED_DROP}/albums/01")["cover"]
        with Image.open(FIXTURES / "cover.jpg") as image:
            self.assertEqual((cover["width"], cover["height"]), image.size)
        self.assertIs(cover["passes"], False)
        status, _type, body = self.fetch(f"/api/drops/{OWNER_UNUSED_DROP}/albums/01/cover")
        self.assertEqual(status, 200)
        self.assertEqual(body, (FIXTURES / "cover.jpg").read_bytes())

    def test_the_owner_cover_the_plan_names_is_the_cover(self) -> None:
        view = self.get_json(f"/api/drops/{OWNER_USED_DROP}/albums/01")
        side = 600 if self.used_png is self.owner_png else 700
        cover = view["cover"]
        self.assertIsNotNone(cover, "no cover shown for the owner cover the plan names")
        self.assertEqual(cover["url"], f"/api/drops/{OWNER_USED_DROP}/albums/01/cover")
        self.assertEqual((cover["width"], cover["height"]), (side, side))
        self.assertIs(cover["passes"], True)
        self.assertIsNone(cover["problem"])
        status, _type, body = self.fetch(f"/api/drops/{OWNER_USED_DROP}/albums/01/cover")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.used_png)

    def test_a_plan_with_no_cover_image_gives_no_cover(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["albums"][0]["images"] = {}
        job = self.folders["jobs"] / f"agitha-{DROP}-01" / "plan.json"
        original = job.read_bytes()
        job.write_text(json.dumps(plan), encoding="utf-8")
        try:
            view = self.get_json(f"/api/drops/{DROP}/albums/01")
        finally:
            job.write_bytes(original)
        self.assertIsNone(view["cover"])

    def test_approve_is_refused_with_a_reason_when_agitha_wrote_no_decision(self) -> None:
        # Only an accept agitha wrote enables Approve. This
        # job has none, so the plan's `certain` status does not matter.
        approvable = self.view["approvable"]
        self.assertIs(approvable["ok"], False)
        self.assertIsInstance(approvable["reason"], str)
        self.assertNotEqual(approvable["reason"].strip(), "")

    def test_an_album_with_no_plan_answers_its_record_and_nothing_planned(self) -> None:
        view = self.get_json(f"/api/drops/{DROP}/albums/02")
        self.assertEqual(view["name"], "Other Album")
        self.assertEqual(view["state"], self.failed["state"])
        self.assertEqual(view["stderr"], self.failed["stderr"])
        self.assertEqual(view["error"], self.failed["error"])
        self.assertIsNone(view["preview"])
        self.assertEqual(view["files"], [])
        self.assertIsNone(view["library_path"])
        self.assertEqual(view["tree"], [])
        self.assertEqual(view["extras_to"], [])
        self.assertIsNone(view["cover"])

    def test_an_album_with_no_plan_still_shows_its_files_as_uploaded(self) -> None:
        uploaded = self.get_json(f"/api/drops/{DROP}/albums/02")["uploaded"]
        self.assertEqual([f["path"] for f in uploaded], ["01 x.mp3"])
        self.assertEqual(uploaded[0]["audio_url"], f"/api/drops/{DROP}/albums/02/audio/01%20x.mp3")

    def test_the_uploaded_files_are_every_track_in_path_order_with_its_facts(self) -> None:
        # The extras album's plan lists its tracks in reverse; `uploaded` is the folder's own order, tracks only.
        uploaded = self.extras_view["uploaded"]
        self.assertEqual([f["path"] for f in uploaded], TRACKS)
        for got, track in zip(uploaded, TRACKS):
            with self.subTest(track=track):
                want = truth(self.extras_album / track)
                self.assertEqual((got["format"], got["family"], got["lossless"], got["bit_depth"]),
                                 ("MP3", "id3", False, None))
                self.assertEqual((got["size"], got["bitrate"], got["sample_rate"], got["channels"]),
                                 (want["size"], want["bitrate"], want["sample_rate"], want["channels"]))
                self.assertAlmostEqual(got["length"], want["length"], delta=LENGTH_TOLERANCE)
                self.assertEqual(got["audio_url"], f"/api/drops/{EXTRAS_DROP}/albums/01/audio/{quote(track)}")

    def test_the_uploaded_tags_read_as_the_plans_before_does_pictures_as_kind_and_size(self) -> None:
        # The picture album's `before` is what the engine read, sized by the view: the same text is expected here.
        uploaded = self.picture_view["uploaded"]
        before = {PurePosixPath(f["source"]).name: f["before"] for f in self.picture_view["preview"]["files"]}
        for got in uploaded[:2]:
            with self.subTest(path=got["path"]):
                pictures = {k: v for k, v in got["tags"].items() if k.startswith("APIC:")}
                self.assertTrue(pictures)
                self.assertEqual(pictures, {k: v for k, v in before[got["path"]].items() if k.startswith("APIC:")})
                self.assertEqual(got["tags"]["TIT2"], [got["path"]])

    def test_an_unknown_album_or_drop_is_404_json_with_an_error(self) -> None:
        for path in (f"/api/drops/{DROP}/albums/09", f"/api/drops/20000101-000000/albums/01"):
            with self.subTest(path=path):
                status, content_type, body = self.fetch(path)
                self.assertEqual(status, 404)
                self.assertEqual(content_type, "application/json; charset=utf-8")
                error = json.loads(body).get("error")
                self.assertIsInstance(error, str)
                self.assertNotEqual(error.strip(), "")

    def picture_sizes(self, track: str) -> dict[str, str]:
        """`{APIC key: "APIC (N bytes)"}` for each picture in `track`, N as mutagen reads it from disk."""
        tags = mutagen.File(self.picture_album / track).tags
        return {frame.HashKey: f"APIC ({len(frame.data)} bytes)" for frame in tags.getall("APIC")}

    def test_a_picture_before_shows_as_its_kind_and_size_read_from_its_own_file(self) -> None:
        # Three pictures of three sizes over two files: a size read from the
        # wrong file, or from the first picture of a file, shows. Text tags and
        # the file with no picture come through as the plan has them.
        self.assertEqual(len(self.picture_sizes(TRACKS[1])), 2)
        self.assertEqual(len(set(self.picture_sizes(TRACKS[0]).values())
                             | set(self.picture_sizes(TRACKS[1]).values())), 3)
        planned = self.picture_plan["albums"][0]["files"]
        got = self.picture_view["preview"]["files"]
        for index, track in enumerate(TRACKS):
            with self.subTest(track=track):
                want = dict(planned[index]["before"])
                for key, shown in self.picture_sizes(track).items():
                    self.assertIn(key, want)
                    want[key] = [shown]
                self.assertEqual(got[index]["before"], want)

    def test_a_picture_the_engine_keeps_shows_after_as_its_kind_and_size(self) -> None:
        planned = self.picture_plan["albums"][0]["files"][0]
        want = dict(planned["after"])
        want.update({key: [shown] for key, shown in self.picture_sizes(TRACKS[0]).items()})
        self.assertEqual(self.picture_view["preview"]["files"][0]["after"], want)


if __name__ == "__main__":
    unittest.main()
