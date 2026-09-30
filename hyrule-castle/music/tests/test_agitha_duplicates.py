"""An album already in the library: finding it, comparing the two copies, keeping one.

An album is already in the library when a folder under the
planned artist folder has audio files carrying the preview's release group
id, or has the planned album folder's name once a leading `(YYYY) `, a
leading `[EP]`/`[Single]`/`[Mixtape]`/`[Live]` and a trailing ` [..]` are
removed from each, compared without case. Only the planned artist folder is
searched. The album view carries both copies' facts. The comparison
recommends one copy by the first rule that differs, and says which.

Keep the new one runs apply, records the finished folder's
hashes, sets the library's copy aside under the album's `replaced/`,
renames the new folder in, verifies it, and only then deletes the copy set
aside. A failure at steps 2 to 4 puts the library's copy back, leaves the
new album in the inbox as `written, not moved` with the step and file, and
deletes nothing. Keep the one in the library discards the album and leaves
the library as it was.

The preview is the engine's own: a staged album is identified by
`tests/agitha_stub.py` over a fake MusicBrainz, accepted with a
`decisions.json`, and identified again. The server runs on a thread over
temporary folders, so a patched `os.rename` reaches its moves, while apply
runs in a subprocess the patch never touches.
"""

from __future__ import annotations

import dataclasses
import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from statistics import mean
from unittest import mock

import mutagen
from mutagen.flac import FLAC
from PIL import Image

from agitha.server import Config, make_server
from tests import builders
from tests.test_batch_identify import release

FIXTURES = builders.FIXTURES
STUB = Path(__file__).resolve().parent / "agitha_stub.py"
# Not resolved: the venv's python is a symlink, and following it loses the venv's mutagen.
PYTHON = os.path.abspath(sys.executable)

DROP = "20260929-210000"
N = "01"
STAGED = "chrono_cross-original_soundtrack-1999"
ARTIST = "Yasunori Mitsuda"
TITLES = ["One", "Two", "Three"]
CHRONO = release(91, ARTIST, "Chrono Cross", TITLES)
RELEASE_GROUP = CHRONO[1]["id"]
OTHER_GROUP = builders.MBID

#: Where the stub's engine plans this album: the fake release is dated 2010.
DESTINATION = f"Y/{ARTIST}/(2010) Chrono Cross"
#: For `find` called on an entry directly.
JAPAN = f"Y/{ARTIST}/(2000) Chrono Cross [Japan]"

SETTLED = {"in the library", "written, not moved", "apply failed"}
DEADLINE = 20.0

RULES = {
    "files": "more audio files",
    "lossless": "lossless over lossy",
    "depth": "higher bit depth",
    "rate": "higher sample rate",
    "bitrate": "higher average bitrate",
    "tie": "the copy in the library",
}

WRAPPER = """\
#!{python}
# musiclib for these tests: records the call, then runs the stub over this file's catalogue.
import json, os, sys
with open({calls!r}, "a", encoding="utf-8") as out:
    out.write(json.dumps(sys.argv[1:]) + "\\n")
os.environ["AGITHA_STUB_CATALOGUE"] = {catalogue!r}
os.environ.pop("AGITHA_STUB_FAIL", None)
os.execv({python!r}, [{python!r}, {stub!r}, *sys.argv[1:]])
"""


class Setting:
    """One temporary root: inbox, jobs, library, extras, static, and a recording musiclib."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        for name in ("inbox", "jobs", "library", "extras", "static"):
            (self.root / name).mkdir()
        (self.static / "index.html").write_bytes(b"<!doctype html>\n")
        self.catalogue = self.root / "catalogue.json"
        self.catalogue.write_text(json.dumps([list(CHRONO)]), encoding="utf-8")
        self.calls = self.root / "calls.jsonl"
        self.musiclib = self.root / "musiclib"
        self.musiclib.write_text(WRAPPER.format(python=PYTHON, calls=str(self.calls),
                                                catalogue=str(self.catalogue), stub=str(STUB)),
                                 encoding="utf-8")
        self.musiclib.chmod(self.musiclib.stat().st_mode | stat.S_IXUSR)

    inbox = property(lambda self: self.root / "inbox")
    jobs = property(lambda self: self.root / "jobs")
    library = property(lambda self: self.root / "library")
    extras = property(lambda self: self.root / "extras")
    static = property(lambda self: self.root / "static")
    album_root = property(lambda self: self.inbox / DROP / N)
    staged = property(lambda self: self.album_root / "drop" / "album" / STAGED)
    finished = property(lambda self: self.album_root / DESTINATION)
    job = property(lambda self: self.jobs / f"agitha-{DROP}-{N}")

    def config(self, library: Path | None = None) -> Config:
        return Config(inbox=self.inbox, jobs=self.jobs, library=library or self.library,
                      extras=self.extras, musiclib=str(self.musiclib), static=self.static,
                      port=0, host="127.0.0.1")

    def stage(self) -> None:
        """The album as agitha leaves it after staging: three tagged FLACs and a cover, `ready`."""
        (self.inbox / DROP).mkdir()
        (self.inbox / DROP / "drop.json").write_text(json.dumps({
            "started": "2026-09-29T21:00:00", "done": True,
            "items": [{"name": STAGED, "kind": "folder", "files": []}],
        }), encoding="utf-8")
        self.staged.mkdir(parents=True)
        (self.album_root / "album.json").write_text(json.dumps({
            "n": N, "name": STAGED, "item": STAGED, "state": "ready", "stderr": "", "error": None,
        }), encoding="utf-8")
        found = CHRONO[0]
        for number, title in enumerate(TITLES, start=1):
            path = self.staged / f"{number:02d} {title.lower()}.flac"
            shutil.copyfile(FIXTURES / "tone.flac", path)
            fields = {"title": [title.lower()], "artist": [ARTIST], "album": ["Chrono Cross"],
                      "date": ["1999"], "release id": [found["id"]]}
            builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(TITLES)),
                                                           disc=(1, 1)))
        shutil.copyfile(FIXTURES / "cover.jpg", self.staged / "cover.jpg")

    def musiclib_run(self, *words: str) -> None:
        subprocess.run([str(self.musiclib), *words], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def accept(self) -> dict:
        """Identify, accept the found release as the page would, identify again; the preview."""
        self.musiclib_run("batch", "identify", str(self.album_root), "--job", str(self.job))
        entry = self.plan_entry()
        decisions = {"job": self.job.name, "albums": {entry["source"]: {
            "action": "accept", "release_id": CHRONO[0]["id"], "edits": {}, "game": None}}}
        (self.job / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
        self.musiclib_run("batch", "identify", str(self.album_root), "--job", str(self.job))
        entry = self.plan_entry()
        # The rest of this file leans on these; a changed stub should say so here, not later.
        assert entry["destination"] == DESTINATION, entry["destination"]
        assert entry["decision"] == "accept" and not entry["holds"], (entry["decision"], entry["holds"])
        self.calls.unlink()
        return entry

    def plan_entry(self) -> dict:
        return json.loads((self.job / "plan.json").read_text(encoding="utf-8"))["albums"][0]

    def apply(self) -> None:
        self.musiclib_run("batch", "apply", "--job", str(self.job), "--extras", str(self.extras),
                          "--live-root", str(self.library))

    def calls_made(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]


def library_copy(library: Path, relative: str, *, ext: str = "mp3", group: str | None = None,
                 discs: int = 1) -> Path:
    """An album under `library/relative` with real tagged files, its release group id `group`.

    `builders.library_album` tags every file with an unrelated id; `None`
    here removes that tag, so the folder can match by its name alone.
    """
    letter, artist, folder = relative.split("/")
    titles = tuple(tuple(f"{title} {disc}" for title in TITLES) for disc in range(1, discs + 1))
    base = builders.library_album(library, ext=ext, letter=letter, artist=artist, folder=folder,
                                  album="Chrono Cross", date="1999-11-18", discs=titles)
    key = builders.picard_key(ext, "release group id")
    for path in sorted(base.rglob(f"*.{ext}")):
        if group is None:
            builders.delete_tags(path, [key])
        else:
            builders.write_tags(path, {key: group}, v2_version=4)
    return base


def flac(path: Path, *, bits: int = 16, rate: int | None = None, padding: int = 0) -> Path:
    """`tone.flac` at `path` with its stream header saying `bits` and `rate`, one second long.

    mutagen reads depth and rate from the header and the bitrate from the
    bytes after the metadata over the length, so `padding` bytes at the
    end raise the bitrate mutagen reports and change nothing else.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "tone.flac", path)
    info = FLAC(path).info
    length = info.length
    info.bits_per_sample = bits
    if rate is not None:
        info.sample_rate = rate
        info.total_samples = round(length * rate)
    data = bytearray(path.read_bytes())
    assert data[:4] == b"fLaC" and data[4] & 0x7F == 0, "tone.flac no longer starts with its stream header"
    data[8:8 + 34] = info.write()
    path.write_bytes(bytes(data) + b"\0" * padding)
    return path


def mp3(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "tone.mp3", path)
    return path


def folder_of(root: Path, name: str, count: int, make, **options) -> Path:
    """`root/name` with `count` audio files made by `make`, numbered from 01."""
    base = root / name
    for number in range(1, count + 1):
        make(base / f"{number:02d}. Track.{'mp3' if make is mp3 else 'flac'}", **options)
    return base


def hashes(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def plain(value):
    """A `Comparison` as its JSON would carry it, whether it is a dataclass or a dict."""
    return json.loads(json.dumps(value, default=dataclasses.asdict))


def truth(folder: Path) -> dict:
    """What mutagen and the filesystem say about a copy, the numbers a `Copy` must agree with."""
    audio = [found for found in (mutagen.File(path) for path in sorted(folder.rglob("*")) if path.is_file())
             if found is not None]
    return {
        "files": len(audio),
        "length": sum(found.info.length for found in audio),
        "size": sum(path.stat().st_size for path in folder.rglob("*") if path.is_file()),
        "bitrate": mean(found.info.bitrate for found in audio),
        "sample_rate": audio[0].info.sample_rate,
    }


class Served:
    """A server over `setting`, on a thread, answering on a free port."""

    def __init__(self, setting: Setting) -> None:
        self.server = make_server(setting.config())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            data = None if body is None else json.dumps(body).encode("utf-8")
            headers = {} if data is None else {"Content-Type": "application/json"}
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            try:
                return response.status, json.loads(raw) if raw else None
            except ValueError:
                return response.status, {"not json": raw.decode("utf-8", "replace")}
        finally:
            connection.close()

    def fetch(self, path: str) -> tuple[int, str, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.headers.get("Content-Type", ""), response.read()
        finally:
            connection.close()

    def view(self) -> tuple[int, dict]:
        return self.request("GET", f"/api/drops/{DROP}/albums/{N}")

    def approve(self, body: dict) -> tuple[int, dict]:
        return self.request("POST", f"/api/drops/{DROP}/albums/{N}/approve", body)

    def settle(self) -> dict:
        """The album view once apply and the moves after it are over.

        A landed album still answers at its address, `in the library` with
        its `library_path`, so a 404 here is a failure.
        """
        deadline = time.monotonic() + DEADLINE
        last = None
        while time.monotonic() < deadline:
            status, view = self.view()
            last = (status, view)
            if status == 200 and view.get("state") in SETTLED:
                return view
            time.sleep(0.05)
        raise AssertionError(f"the album did not settle in {DEADLINE} s; last view: {last!r}")


class Finding(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.setting = Setting()
        cls.setting.stage()
        cls.entry = cls.setting.accept()
        cls.japan = dict(cls.entry, destination=JAPAN)
        cls.served = Served(cls.setting)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.served.close()
        shutil.rmtree(cls.setting.root)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.library = self.tmp / "library"
        self.library.mkdir()
        self.config = self.setting.config(self.library)

    def find(self, entry: dict):
        from agitha.duplicates import find

        return find(self.config, entry)

    def assertFinds(self, entry: dict, folder: Path) -> None:
        found = self.find(entry)
        self.assertIsNotNone(found, f"{folder.relative_to(self.library)} was not found")
        self.assertEqual(plain(found)["library"]["folder"], str(folder))

    def test_a_folder_whose_audio_carries_the_previews_release_group_is_found_whatever_its_name(self) -> None:
        # Another edition of the release group, under a name no rule would match.
        # The library copies are in each family, so reading the preview's
        # family key from a file of another family finds nothing.
        for ext in ("mp3", "flac", "m4a"):
            with self.subTest(ext=ext):
                folder = library_copy(self.library, f"Y/{ARTIST}/(1999) Kurono Kurosu {ext}", ext=ext,
                                      group=RELEASE_GROUP)
                try:
                    self.assertFinds(self.japan, folder)
                finally:
                    shutil.rmtree(self.library / "Y")

    def test_the_release_group_is_read_from_audio_in_disc_folders_too(self) -> None:
        # The library puts a multi-disc album's files in CD1, CD2.
        folder = library_copy(self.library, f"Y/{ARTIST}/(1999) Kurono Kurosu", group=RELEASE_GROUP, discs=2)
        self.assertFinds(self.japan, folder)

    def test_the_criterions_example_another_year_and_no_edition_is_found(self) -> None:
        folder = library_copy(self.library, f"Y/{ARTIST}/(1999) Chrono Cross", group=RELEASE_GROUP)
        self.assertFinds(self.japan, folder)

    def test_a_folder_differing_only_by_year_edition_and_case_is_found_by_its_name_alone(self) -> None:
        for name in ("(1999) Chrono Cross", "(1999) CHRONO cross", "(2000) Chrono Cross [Limited]",
                     "Chrono Cross"):
            with self.subTest(name=name):
                folder = library_copy(self.library, f"Y/{ARTIST}/{name}", group=None)
                try:
                    self.assertFinds(self.japan, folder)
                finally:
                    shutil.rmtree(self.library / "Y")

    def test_a_type_prefix_is_removed_before_the_names_are_compared(self) -> None:
        for prefix in ("EP", "Single", "Mixtape", "Live"):
            with self.subTest(prefix=prefix):
                folder = library_copy(self.library, f"Y/{ARTIST}/(1999) [{prefix}] Chrono Cross", group=None)
                try:
                    self.assertFinds(self.japan, folder)
                finally:
                    shutil.rmtree(self.library / "Y")

    def test_a_single_of_another_title_is_not_the_album(self) -> None:
        library_copy(self.library, f"Y/{ARTIST}/(1999) [Single] Radical Dreamers", group=OTHER_GROUP)
        self.assertIsNone(self.find(self.japan))

    def test_a_folder_of_the_same_name_whose_audio_names_another_release_group_is_not_the_album(self) -> None:
        # Weezer's Green Album against its Red Album: both titled "Weezer".
        library_copy(self.library, f"Y/{ARTIST}/(2008) Chrono Cross", group=OTHER_GROUP)
        self.assertIsNone(self.find(self.japan))

    def test_a_name_that_only_contains_the_title_is_not_the_album(self) -> None:
        # Guards a substring or prefix match standing in for equality.
        library_copy(self.library, f"Y/{ARTIST}/(1999) Chrono Cross Arrange Album", group=OTHER_GROUP)
        self.assertIsNone(self.find(self.japan))

    def test_the_album_under_another_artist_folder_is_not_searched(self) -> None:
        # Same letter, a name that starts like the planned artist's, the
        # same album name and the same release group: still not searched.
        library_copy(self.library, f"Y/{ARTIST} & Millennial Fair/(2000) Chrono Cross [Japan]",
                     group=RELEASE_GROUP)
        self.assertIsNone(self.find(self.japan))

    def test_the_same_artist_folder_under_another_letter_is_not_searched(self) -> None:
        library_copy(self.library, f"M/{ARTIST}/(2000) Chrono Cross [Japan]", group=RELEASE_GROUP)
        self.assertIsNone(self.find(self.japan))

    def test_an_artist_folder_missing_from_the_library_finds_nothing(self) -> None:
        self.assertIsNone(self.find(self.japan))

    def test_the_view_carries_no_duplicate_while_the_planned_artist_folder_holds_none(self) -> None:
        library_copy(self.setting.library, f"Y/{ARTIST} & Millennial Fair/(2010) Chrono Cross",
                     group=RELEASE_GROUP)
        self.addCleanup(shutil.rmtree, self.setting.library / "Y")
        status, view = self.served.view()
        self.assertEqual(status, 200, view)
        self.assertEqual(view["state"], "ready")
        self.assertIsNone(view["duplicate"])

    def test_the_view_shows_both_copies_and_the_recommendation_and_leaves_approvable_alone(self) -> None:
        status, alone = self.served.view()
        self.assertEqual(status, 200, alone)
        copy = library_copy(self.setting.library, f"Y/{ARTIST}/(1999) Chrono Cross", group=RELEASE_GROUP)
        self.addCleanup(shutil.rmtree, self.setting.library / "Y")
        status, view = self.served.view()
        self.assertEqual(status, 200, view)
        duplicate = view["duplicate"]
        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate["new"]["folder"], str(self.setting.staged))
        self.assertEqual(duplicate["library"]["folder"], str(copy))
        self.assertEqual((duplicate["new"]["format"], duplicate["new"]["files"]), ("FLAC", 3))
        self.assertEqual((duplicate["library"]["format"], duplicate["library"]["files"]), ("MP3", 3))
        self.assertEqual((duplicate["recommended"], duplicate["rule"]), ("new", RULES["lossless"]))
        self.assertEqual(view["approvable"], alone["approvable"])
        self.assertIsNone(view["step"])
        self.assertIsNone(view["file"])

    def test_each_copys_cover_is_served_at_its_side_of_the_comparison(self) -> None:
        copy = library_copy(self.setting.library, f"Y/{ARTIST}/(1999) Chrono Cross", group=RELEASE_GROUP)
        self.addCleanup(shutil.rmtree, self.setting.library / "Y")
        # Not the new copy's image, so a route serving the wrong side shows.
        (copy / "cover.jpg").write_bytes(builders.jpeg(600, 600))
        status, view = self.served.view()
        self.assertEqual(status, 200, view)
        self.assertEqual(view["state"], "ready")
        base = f"/api/drops/{DROP}/albums/{N}/duplicate/cover"
        for side, folder in (("new", self.setting.staged), ("library", copy)):
            with self.subTest(side=side):
                url = view["duplicate"][side]["cover"]["url"]
                self.assertEqual(url, f"{base}?side={side}")
                status, content_type, body = self.served.fetch(url)
                self.assertEqual(status, 200, body[:200])
                self.assertTrue(content_type.startswith("image/"), content_type)
                self.assertEqual(body, (folder / "cover.jpg").read_bytes())

    def compare(self, new: Path, library: Path) -> dict:
        from agitha.duplicates import compare

        return plain(compare(new, library))

    def assertRecommends(self, new: Path, library: Path, side: str, rule: str) -> None:
        got = self.compare(new, library)
        self.assertEqual((got["recommended"], got["rule"]), (side, rule))

    def test_the_criterions_example_67_flacs_beat_67_mp3s_by_lossless_over_lossy(self) -> None:
        new = folder_of(self.tmp, "new", 67, flac, rate=44100)
        library = folder_of(self.tmp, "library copy", 67, mp3)
        self.assertRecommends(new, library, "new", RULES["lossless"])

    def test_lossless_in_the_library_is_kept_over_a_lossy_new_copy(self) -> None:
        new = folder_of(self.tmp, "new", 3, mp3)
        library = folder_of(self.tmp, "library copy", 3, flac)
        self.assertRecommends(new, library, "library", RULES["lossless"])

    def test_more_audio_files_wins_before_lossless(self) -> None:
        new = folder_of(self.tmp, "new", 4, mp3)
        library = folder_of(self.tmp, "library copy", 3, flac)
        self.assertRecommends(new, library, "new", RULES["files"])

    def test_only_audio_files_are_counted(self) -> None:
        # Three FLACs and three other files against four MP3s: counting every
        # file would give the new copy six.
        new = folder_of(self.tmp, "new", 3, flac)
        for name in ("cover.jpg", "folder.jpg"):
            shutil.copyfile(FIXTURES / "cover.jpg", new / name)
        (new / "rip.log").write_text("Exact Audio Copy\n", encoding="utf-8")
        library = folder_of(self.tmp, "library copy", 4, mp3)
        self.assertRecommends(new, library, "library", RULES["files"])

    def test_higher_bit_depth_wins_before_sample_rate(self) -> None:
        new = folder_of(self.tmp, "new", 3, flac, bits=24, rate=44100)
        library = folder_of(self.tmp, "library copy", 3, flac, bits=16, rate=48000)
        self.assertRecommends(new, library, "new", RULES["depth"])

    def test_higher_sample_rate_wins_before_bitrate(self) -> None:
        new = folder_of(self.tmp, "new", 3, flac, rate=48000)
        library = folder_of(self.tmp, "library copy", 3, flac, rate=44100, padding=20000)
        self.assertRecommends(new, library, "new", RULES["rate"])

    def test_a_lower_sample_rate_in_the_new_copy_keeps_the_library_copy(self) -> None:
        new = folder_of(self.tmp, "new", 3, flac, rate=44100, padding=20000)
        library = folder_of(self.tmp, "library copy", 3, flac, rate=48000)
        self.assertRecommends(new, library, "library", RULES["rate"])

    def test_higher_average_bitrate_decides_when_all_else_is_equal(self) -> None:
        # The new copy's average is higher though two of its three files are
        # below every library file, so a minimum or a median picks the library.
        new = self.tmp / "new"
        flac(new / "01.flac", padding=6000)
        flac(new / "02.flac")
        flac(new / "03.flac")
        library = folder_of(self.tmp, "library copy", 3, flac, padding=1500)
        self.assertRecommends(new, library, "new", RULES["bitrate"])
        self.assertRecommends(library, new, "library", RULES["bitrate"])

    def test_with_no_difference_the_copy_in_the_library_is_recommended(self) -> None:
        new = folder_of(self.tmp, "new", 3, flac)
        library = folder_of(self.tmp, "library copy", 3, flac)
        # A cover and a log on one side only are not a rule.
        shutil.copyfile(FIXTURES / "cover.jpg", new / "cover.jpg")
        (new / "rip.log").write_text("Exact Audio Copy\n", encoding="utf-8")
        self.assertRecommends(new, library, "library", RULES["tie"])

    def test_each_copys_facts_are_what_mutagen_and_the_filesystem_say(self) -> None:
        new = folder_of(self.tmp, "new", 3, flac, bits=24, rate=48000)
        flac(new / "04.flac", bits=24, rate=48000, padding=4000)
        shutil.copyfile(FIXTURES / "cover.jpg", new / "cover.jpg")
        (new / "rip.log").write_text("Exact Audio Copy\n", encoding="utf-8")
        library = folder_of(self.tmp, "library copy", 2, mp3)
        got = self.compare(new, library)
        with Image.open(FIXTURES / "cover.jpg") as image:
            cover = image.size
        for side, folder, format_, lossless, depth, pictured in (
                ("new", new, "FLAC", True, 24, cover), ("library", library, "MP3", False, None, None)):
            with self.subTest(side=side):
                copy, want = got[side], truth(folder)
                self.assertEqual(copy["folder"], str(folder))
                self.assertEqual(copy["format"], format_)
                self.assertIs(copy["lossless"], lossless)
                self.assertEqual(copy["bit_depth"], depth)
                self.assertEqual(copy["sample_rate"], want["sample_rate"])
                self.assertEqual(copy["files"], want["files"])
                self.assertAlmostEqual(copy["bitrate"], want["bitrate"], delta=1)
                self.assertAlmostEqual(copy["length"], want["length"], delta=0.01)
                self.assertEqual(copy["size"], want["size"])
                if pictured is None:
                    self.assertIsNone(copy["cover"])
                else:
                    self.assertEqual((copy["cover"]["width"], copy["cover"]["height"]), pictured)
                    self.assertIsInstance(copy["cover"]["url"], str)
                    self.assertNotEqual(copy["cover"]["url"].strip(), "")

    def test_the_cover_is_read_from_folder_jpg_or_front_jpg_when_there_is_no_cover_jpg(self) -> None:
        library = folder_of(self.tmp, "library copy", 1, mp3)
        for name, size in (("folder.jpg", (640, 610)), ("front.jpg", (700, 520))):
            with self.subTest(name=name):
                new = folder_of(self.tmp, f"new {name}", 1, flac)
                (new / name).write_bytes(builders.jpeg(*size))
                cover = self.compare(new, library)["new"]["cover"]
                self.assertEqual((cover["width"], cover["height"]), size)

    def test_a_copy_with_flac_and_mp3_files_is_of_mixed_format(self) -> None:
        new = self.tmp / "new"
        flac(new / "01.flac")
        mp3(new / "02.mp3")
        library = folder_of(self.tmp, "library copy", 2, mp3)
        self.assertEqual(self.compare(new, library)["new"]["format"], "mixed")

    def test_audio_files_in_disc_folders_count(self) -> None:
        library = self.tmp / "library copy"
        for disc in (1, 2):
            for number in (1, 2):
                flac(library / f"CD{disc}" / f"{number:02d}.flac")
        new = folder_of(self.tmp, "new", 3, flac)
        got = self.compare(new, library)
        self.assertEqual(got["library"]["files"], 4)
        self.assertEqual((got["recommended"], got["rule"]), ("library", RULES["files"]))


#: What Picard would tag a copy of the album with; each test changes what it needs.
TAGS = {"album": ["Chrono Cross"], "albumartist": [ARTIST], "date": ["1999-11-18"], "label": ["Square"],
        "catalognumber": ["SSCX-10040"], "releasecountry": ["JP"], "media": ["CD"],
        "release id": [CHRONO[0]["id"]]}


def tagged(path: Path, number: int, total: int, *, disc: int = 1, discs: int = 1,
           fields: dict[str, list[str]] | None = None, seconds: float | None = None) -> Path:
    """A fixture file at `path` with Picard's tags, `seconds` long where given (FLAC only)."""
    ext = path.suffix.lstrip(".")
    if ext == "flac":
        flac(path)
        if seconds is not None:
            info = FLAC(path).info
            info.total_samples = round(seconds * info.sample_rate)
            data = bytearray(path.read_bytes())
            data[8:8 + 34] = info.write()
            path.write_bytes(bytes(data))
    else:
        mp3(path)
    builders.write_tags(path, builders.picard_tags(ext, TAGS if fields is None else fields,
                                                   track=(number, total), disc=(disc, discs)), v2_version=4)
    return path


class Telling(unittest.TestCase):
    """What the page shows to choose between two copies the rules cannot tell apart, both MP3s among them."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)

    def compare(self, new: Path, library: Path) -> dict:
        from agitha.duplicates import compare

        return plain(compare(new, library))

    def test_two_mp3_copies_show_their_release_tags_bitrates_and_tagging(self) -> None:
        new, library = self.tmp / "new", self.tmp / "library copy"
        for number in (1, 2, 3):
            tagged(new / f"{number:02d}.mp3", number, 3)
            tagged(library / f"{number:02d}.mp3", number, 3,
                   fields={"album": ["Chrono Cross OST"], "release id": [OTHER_GROUP]})
        got = self.compare(new, library)
        self.assertEqual((got["recommended"], got["rule"], got["rule_code"]), ("library", RULES["tie"], "library"))
        mine = {key: got["new"][key] for key in
                ("release_id", "album", "album_artist", "date", "label", "catalog", "country", "media", "discs")}
        self.assertEqual(mine, {"release_id": CHRONO[0]["id"], "album": "Chrono Cross", "album_artist": ARTIST,
                                "date": "1999-11-18", "label": "Square", "catalog": "SSCX-10040",
                                "country": "JP", "media": "CD", "discs": 1})
        theirs = got["library"]
        self.assertEqual((theirs["release_id"], theirs["album"], theirs["label"]), (OTHER_GROUP, "Chrono Cross OST", None))
        bitrate = mutagen.File(new / "01.mp3").info.bitrate
        self.assertEqual((got["new"]["bitrate_min"], got["new"]["bitrate_max"]), (bitrate, bitrate))
        # The fixture was made by ffmpeg, whose MP3s carry no LAME header.
        self.assertIsNone(got["new"]["encoder"])
        keys = [len(mutagen.File(path).tags) for path in sorted(new.iterdir())]
        self.assertAlmostEqual(got["new"]["tag_count"], mean(keys), delta=0.05)
        self.assertGreater(got["new"]["tag_count"], got["library"]["tag_count"])
        self.assertEqual(got["tracks"], {"paired": 3, "length_differs": 0, "only_new": 0, "only_library": 0,
                                         "max_length_diff": 0.0})

    def test_the_lowest_and_highest_bitrate_show_a_straggler(self) -> None:
        new = self.tmp / "new"
        flac(new / "01.flac")
        flac(new / "02.flac", padding=6000)
        got = self.compare(new, folder_of(self.tmp, "library copy", 2, flac))["new"]
        rates = sorted(mutagen.File(path).info.bitrate for path in new.iterdir())
        self.assertEqual((got["bitrate_min"], got["bitrate_max"]), (rates[0], rates[-1]))
        self.assertLess(got["bitrate_min"], got["bitrate_max"])

    def test_tracks_pair_by_disc_and_track_number_whatever_their_file_names(self) -> None:
        new, library = self.tmp / "new", self.tmp / "library copy"
        # Named against their numbers, so pairing by order would pair 1 with 3.
        for name, number in (("a.flac", 3), ("b.flac", 2), ("c.flac", 1)):
            tagged(new / name, number, 3)
        tagged(library / "01.flac", 1, 3)
        tagged(library / "03.flac", 3, 3, seconds=5.5)
        tagged(library / "04.flac", 4, 4)
        tracks = self.compare(new, library)["tracks"]
        self.assertEqual({k: v for k, v in tracks.items() if k != "max_length_diff"},
                         {"paired": 2, "length_differs": 1, "only_new": 1, "only_library": 1})
        self.assertAlmostEqual(tracks["max_length_diff"], 4.5, delta=0.01)

    def test_a_difference_of_two_seconds_or_less_is_the_same_length(self) -> None:
        new, library = self.tmp / "new", self.tmp / "library copy"
        tagged(new / "01.flac", 1, 1)
        tagged(library / "01.flac", 1, 1, seconds=3.0)
        tracks = self.compare(new, library)["tracks"]
        self.assertEqual((tracks["paired"], tracks["length_differs"]), (1, 0))
        self.assertAlmostEqual(tracks["max_length_diff"], 2.0, delta=0.01)

    def test_without_track_numbers_on_a_side_tracks_pair_in_path_order(self) -> None:
        new = folder_of(self.tmp, "new", 3, mp3)
        library = self.tmp / "library copy"
        for number in (1, 2):
            tagged(library / f"{number:02d}.mp3", number, 2)
        tracks = self.compare(new, library)["tracks"]
        self.assertEqual((tracks["paired"], tracks["only_new"], tracks["only_library"]), (2, 1, 0))

    def test_discs_count_disc_numbers_else_disc_folders(self) -> None:
        by_tag = self.tmp / "by tag"
        for disc in (1, 2, 3):
            tagged(by_tag / f"{disc}-01.flac", 1, 1, disc=disc, discs=3)
        by_folder = self.tmp / "by folder"
        for disc in (1, 2):
            flac(by_folder / f"CD{disc}" / "01.flac")
        got = self.compare(by_tag, by_folder)
        self.assertEqual((got["new"]["discs"], got["library"]["discs"]), (3, 2))

    def test_a_disc_folder_named_after_its_album_gives_its_files_that_disc(self) -> None:
        # The library's files carry no disc tag. Read as disc 2, `Album [Disc 2]`
        # pairs the new copy's 5.5 s disc 2 track with the library's 5.5 s file.
        # Read as the folder's name, nothing pairs. Read as one disc for both,
        # the copies pair in path order, and a.flac, the disc 2 track, sorts first.
        new, library = self.tmp / "new", self.tmp / "library copy"
        tagged(new / "a.flac", 1, 1, disc=2, discs=2, seconds=5.5)
        tagged(new / "b.flac", 1, 1, disc=1, discs=2)
        for disc, seconds in ((1, None), (2, 5.5)):
            path = tagged(library / f"Album [Disc {disc}]" / "01.flac", 1, 1, seconds=seconds)
            builders.delete_tags(path, ["discnumber", "disctotal"])
        got = self.compare(new, library)
        self.assertEqual({k: v for k, v in got["tracks"].items() if k != "max_length_diff"},
                         {"paired": 2, "length_differs": 0, "only_new": 0, "only_library": 0})
        self.assertEqual(got["library"]["discs"], 2)

    def test_the_encoder_is_what_the_file_says(self) -> None:
        from agitha.audio import encoder

        path = tagged(self.tmp / "01.flac", 1, 1)
        self.assertEqual(encoder(mutagen.File(path)), FLAC(path).tags.vendor)
        self.assertIsNone(encoder(mutagen.File(mp3(self.tmp / "01.mp3"))))
        # mutagen reads a LAME header into these two; the fixture has none, so they are set here.
        lame = mutagen.File(self.tmp / "01.mp3")
        lame.info.encoder_info, lame.info.encoder_settings = "LAME 3.100", "-V 0"
        self.assertEqual(encoder(lame), "LAME 3.100 -V 0")


class Keeping(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # What apply writes for this album, so each test can say what the
        # library should end up holding. Apply is byte-for-byte repeatable
        # and writes no path into a file, so one rehearsal serves every root.
        rehearsal = Setting()
        try:
            rehearsal.stage()
            rehearsal.accept()
            rehearsal.apply()
            cls.expected = hashes(rehearsal.finished)
        finally:
            shutil.rmtree(rehearsal.root)

    def setUp(self) -> None:
        # A root and a server per test: a move left running by one case
        # must not land in the next one's folders.
        self.setting = Setting()
        self.addCleanup(shutil.rmtree, self.setting.root)
        self.setting.stage()
        self.setting.accept()
        self.served = Served(self.setting)
        self.addCleanup(self.served.close)

    def lay_library(self, folder: str = "(1999) Chrono Cross", check: bool = True) -> Path:
        copy = library_copy(self.setting.library, f"Y/{ARTIST}/{folder}", group=RELEASE_GROUP)
        self.before = builders.tree(self.setting.library)
        if not check:
            return copy
        status, view = self.served.view()
        self.assertEqual(status, 200, view)
        self.assertIsNotNone(view["duplicate"], "the library copy was not found, so nothing here is a keep")
        return copy

    def keep_new(self, rename=None) -> dict:
        """Keep the new one and wait for it to settle, with `rename` standing in for `os.rename` throughout."""
        with mock.patch("os.rename", rename or os.rename), mock.patch("os.replace", rename or os.replace):
            status, body = self.served.approve({"keep": "new"})
            self.assertTrue(200 <= status < 300, (status, body))
            return self.served.settle()

    def assertLanded(self, view: dict) -> None:
        self.assertEqual(view["state"], "in the library", view)
        self.assertEqual(view["library_path"], str(self.setting.library / DESTINATION))
        self.assertIsNone(view["error"])
        self.assertIsNone(view["step"])

    def assertLibraryAsBefore(self) -> None:
        self.assertEqual(builders.tree(self.setting.library), self.before)

    def assertWrittenNotMoved(self, view: dict | None, step: int) -> None:
        self.assertEqual(view["state"], "written, not moved")
        self.assertEqual(view["step"], step)
        self.assertIsInstance(view["error"], str)
        self.assertNotEqual(view["error"].strip(), "")
        self.assertIsInstance(view["file"], str)
        self.assertNotEqual(view["file"].strip(), "")
        self.assertTrue(self.setting.job.is_dir())

    def failing(self, when) -> tuple:
        """`os.rename` that raises once, on the first call `when(src, dst)` picks, and records every call."""
        real = os.rename
        seen: list[tuple[str, str]] = []
        raised: list[tuple[str, str]] = []

        def rename(src, dst, *args, **kwargs):
            pair = (os.path.realpath(src), os.path.realpath(dst))
            seen.append(pair)
            if not raised and when(*pair):
                raised.append(pair)
                raise PermissionError(13, "Permission denied (injected by the test)", str(src))
            return real(src, dst, *args, **kwargs)

        return rename, raised

    def test_approve_without_keep_is_409_and_runs_nothing_while_a_duplicate_is_set(self) -> None:
        self.lay_library()
        staged = builders.tree(self.setting.album_root)
        status, body = self.served.approve({})
        self.assertEqual(status, 409, body)
        self.assertIsInstance(body.get("error"), str)
        self.assertNotEqual(body["error"].strip(), "")
        status, view = self.served.view()
        self.assertEqual(view["state"], "ready")
        self.assertEqual(self.setting.calls_made(), [])
        self.assertEqual(builders.tree(self.setting.album_root), staged)
        self.assertLibraryAsBefore()

    def test_keep_the_one_in_the_library_discards_the_album_and_leaves_the_library_as_it_was(self) -> None:
        self.lay_library()
        status, body = self.served.approve({"keep": "library"})
        self.assertEqual(status, 200, body)
        status, _view = self.served.view()
        self.assertEqual(status, 404)
        self.assertFalse(self.setting.album_root.exists())
        self.assertFalse(self.setting.job.exists())
        status, drops = self.served.request("GET", "/api/drops")
        self.assertEqual(status, 200, drops)
        listed = [(drop["id"], album["n"]) for drop in drops for album in drop["albums"]]
        self.assertNotIn((DROP, N), listed)
        self.assertNotIn("apply", [word for call in self.setting.calls_made() for word in call])
        self.assertLibraryAsBefore()

    def test_keep_the_one_in_the_library_needs_no_accepted_preview(self) -> None:
        # The common case: a duplicate straight after identify, before the
        # owner has sent any decision. Discarding needs no accept.
        (self.setting.job / "decisions.json").unlink()
        self.setting.musiclib_run("batch", "identify", str(self.setting.album_root), "--job", str(self.setting.job))
        self.assertIsNone(self.setting.plan_entry()["decision"])
        self.setting.calls.unlink()
        self.lay_library()
        status, body = self.served.approve({"keep": "library"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["state"], "discarded")
        status, _view = self.served.view()
        self.assertEqual(status, 404)
        self.assertFalse(self.setting.album_root.exists())
        self.assertNotIn("apply", [word for call in self.setting.calls_made() for word in call])
        self.assertLibraryAsBefore()

    def written_not_moved(self) -> None:
        """The album applied and left in the inbox, as a failed rename leaves it."""
        self.setting.apply()
        record_path = self.setting.album_root / "album.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record.update(state="written, not moved", error="could not move it: Invalid cross-device link")
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.setting.calls.unlink(missing_ok=True)

    def assertMoveRefusedAsDuplicate(self, library_folder: Path) -> None:
        status, body = self.served.request("POST", f"/api/drops/{DROP}/albums/{N}/move", {})
        self.assertEqual(status, 409, body)
        self.assertIn("already in the library", body["error"])
        self.assertLibraryAsBefore()
        self.assertEqual(hashes(self.setting.finished), self.expected)
        status, view = self.served.view()
        self.assertEqual(status, 200, view)
        self.assertEqual(view["state"], "written, not moved")
        self.assertIsNotNone(view["duplicate"], "the owner is offered no choice")
        self.assertEqual(view["duplicate"]["new"]["folder"], str(self.setting.finished))
        self.assertEqual(view["duplicate"]["library"]["folder"], str(library_folder))

    def test_move_is_refused_when_another_edition_reached_the_artist_folder_meanwhile(self) -> None:
        self.written_not_moved()
        copy = self.lay_library("(1999) Chrono Cross", check=False)
        self.assertMoveRefusedAsDuplicate(copy)

    def test_move_is_refused_when_a_copy_reached_the_exact_destination_meanwhile(self) -> None:
        # Two albums of one drop with one destination: the second finds the
        # first already there, and a rename onto it would only fail.
        self.written_not_moved()
        copy = self.lay_library("(2010) Chrono Cross", check=False)
        self.assertMoveRefusedAsDuplicate(copy)

    def stranded(self) -> Path:
        """The library's copy left under `replaced/`: step 3 fails and so does putting it back.

        The server reaches this state itself, so whatever it records at step
        1 is there for Move to resume from. Returns the copy set aside.
        """
        old = self.lay_library("(1999) Chrono Cross")
        finished = str(self.setting.finished)
        aside = self.setting.album_root / "replaced" / "Y" / ARTIST / old.name
        real = os.rename

        def rename(src, dst, *args, **kwargs):
            if os.path.realpath(src) in (finished, str(aside)):
                raise PermissionError(13, "Permission denied (injected by the test)", str(src))
            return real(src, dst, *args, **kwargs)

        view = self.keep_new(rename)
        self.assertEqual(view["state"], "written, not moved", view)
        self.assertFalse(old.exists())
        self.assertTrue(any(path.is_file() for path in aside.rglob("*")), "nothing was set aside")
        return aside

    def test_discard_is_refused_while_the_librarys_copy_is_set_aside(self) -> None:
        aside = self.stranded()
        kept, finished = builders.tree(aside), builders.tree(self.setting.finished)
        status, body = self.served.request("POST", f"/api/drops/{DROP}/albums/{N}/discard", {})
        self.assertEqual(status, 409, body)
        self.assertIn("replaced/", body["error"])
        self.assertEqual(builders.tree(aside), kept)
        self.assertEqual(builders.tree(self.setting.finished), finished)

    def test_move_resumes_the_swap_after_the_librarys_copy_was_left_aside(self) -> None:
        self.stranded()
        status, body = self.served.request("POST", f"/api/drops/{DROP}/albums/{N}/move", {})
        self.assertEqual(status, 200, body)
        view = self.served.settle()
        self.assertLanded(view)
        self.assertEqual(hashes(self.setting.library / DESTINATION), self.expected)
        self.assertFalse((self.setting.album_root / "replaced").exists())
        self.assertFalse((self.setting.library / "Y" / ARTIST / "(1999) Chrono Cross").exists())

    def test_move_after_the_copy_was_left_aside_verifies_and_puts_the_copy_back_on_a_changed_file(self) -> None:
        self.stranded()
        finished = str(self.setting.finished)
        real = os.rename
        altered: list[str] = []

        def rename(src, dst, *args, **kwargs):
            result = real(src, dst, *args, **kwargs)
            if not altered and os.path.realpath(src) == finished:
                target = Path(dst) / "01. One.flac"
                data = bytearray(target.read_bytes())
                data[-1] ^= 0xFF
                target.write_bytes(bytes(data))
                altered.append(str(target))
            return result

        with mock.patch("os.rename", rename), mock.patch("os.replace", rename):
            status, body = self.served.request("POST", f"/api/drops/{DROP}/albums/{N}/move", {})
            view = self.served.settle()
        self.assertTrue(altered, "the finished album was never renamed into the library")
        self.assertWrittenNotMoved(view, 4)
        self.assertEqual(Path(view["file"]).name, "01. One.flac")
        self.assertLibraryAsBefore()
        self.assertEqual(set(hashes(self.setting.finished)), set(self.expected))

    def test_keep_the_new_one_replaces_another_edition_with_the_applied_album(self) -> None:
        old = self.lay_library("(1999) Chrono Cross")
        view = self.keep_new()
        self.assertLanded(view)
        self.assertFalse(old.exists())
        artist = self.setting.library / "Y" / ARTIST
        self.assertEqual(sorted(path.name for path in artist.iterdir()), ["(2010) Chrono Cross"])
        self.assertEqual(hashes(self.setting.library / DESTINATION), self.expected)
        self.assertFalse(self.setting.album_root.exists())
        self.assertTrue((self.setting.job / "plan.json").is_file())

    def test_keep_the_new_one_replaces_a_copy_already_at_the_destination(self) -> None:
        self.lay_library("(2010) Chrono Cross")
        view = self.keep_new()
        self.assertLanded(view)
        self.assertEqual(hashes(self.setting.library / DESTINATION), self.expected)
        self.assertFalse(self.setting.album_root.exists())
        self.assertTrue((self.setting.job / "plan.json").is_file())

    def test_a_failure_setting_the_library_copy_aside_leaves_both_copies_where_they_were(self) -> None:
        old = self.lay_library()
        rename, raised = self.failing(lambda src, dst: src == str(old))
        view = self.keep_new(rename)
        self.assertTrue(raised, "the library copy was never moved aside")
        self.assertWrittenNotMoved(view, 2)
        self.assertEqual(Path(view["file"]).name, old.name)
        self.assertLibraryAsBefore()
        self.assertEqual(hashes(self.setting.finished), self.expected)

    def test_a_failure_renaming_the_new_album_in_puts_the_library_copy_back(self) -> None:
        self.lay_library()
        finished = str(self.setting.finished)
        rename, raised = self.failing(lambda src, dst: src == finished)
        view = self.keep_new(rename)
        self.assertTrue(raised, "the finished album was never renamed into the library")
        self.assertWrittenNotMoved(view, 3)
        self.assertEqual(Path(view["file"]).name, Path(DESTINATION).name)
        self.assertLibraryAsBefore()
        self.assertEqual(hashes(self.setting.finished), self.expected)

    def test_a_file_that_changed_in_the_move_fails_verification_and_both_copies_go_back(self) -> None:
        self.lay_library()
        finished = str(self.setting.finished)
        real = os.rename
        altered: list[str] = []

        def rename(src, dst, *args, **kwargs):
            result = real(src, dst, *args, **kwargs)
            if not altered and os.path.realpath(src) == finished:
                # One byte of one file, flipped the moment the album lands.
                target = Path(dst) / "01. One.flac"
                data = bytearray(target.read_bytes())
                data[-1] ^= 0xFF
                target.write_bytes(bytes(data))
                altered.append(str(target))
            return result

        view = self.keep_new(rename)
        self.assertTrue(altered, "the finished album was never renamed into the library")
        self.assertWrittenNotMoved(view, 4)
        self.assertEqual(Path(view["file"]).name, "01. One.flac")
        self.assertLibraryAsBefore()
        # Nothing deleted: every file of the new album is back in the inbox,
        # the altered one as it now is.
        back = hashes(self.setting.finished)
        self.assertEqual(set(back), set(self.expected))
        self.assertEqual({name: digest for name, digest in back.items() if name != "01. One.flac"},
                         {name: digest for name, digest in self.expected.items() if name != "01. One.flac"})


if __name__ == "__main__":
    unittest.main()
