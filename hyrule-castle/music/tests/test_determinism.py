"""The same input gives the same plan and the same files, and a written album plans as done.

Criteria 35 and 36 in the spec. A plan is compared through `Plan.to_json()`,
its canonical bytes, and "proposes no change" means `plan.changes(plan)` is
empty.

Plans run in child processes with different `PYTHONHASHSEED`s, from copies of
the rip at different absolute paths. A second plan in the same process would
share the first one's hash seed, so a list built by walking a set would come
out in the same order both times and hide the bug the owner meets on the next
day's run. The copies at different paths catch a temp path leaking into the
plan or into a written file.

Every plan after the first reads a warm cache through a transport that fails
the test on any request, so a plan that quietly went to the network for
something the first run never stored shows up here too.

The rip is `test_check`'s: lower-case titles, loose file names, dated 1989
where the release is 2010. Planning it moves and retitles every track. Byte
identity holds on one machine only: Pillow and libjpeg differ between the
MacBook and the box (`plan.md`, *Cannot be verified here*).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from musiclib import caa, mb
from musiclib.cache import Cache
from musiclib.units import units
from tests import builders
from tests.test_check import _release, _rip, _Services, _release_group

FORMATS = ("flac", "mp3", "ogg", "m4a")

HERE = Path(__file__).resolve().parents[1]

#: Two discs, so the disc folders and the per-medium totals are in the plan.
DISCS = (["Plainsong", "Pictures of You"], ["Prayers for Rain"])

#: Two seeds known to walk small sets of strings in different orders.
SEEDS = ("1", "2")

#: What a child process runs: plan every album it is given against the warm
#: cache, offline, and print each plan's `to_json()`. With `extras`, it
#: writes each plan as well.
_CHILD = r"""
import base64, json, sys
from pathlib import Path

from musiclib.plan import plan_album
from musiclib.units import units
from tests.test_determinism import _clients, _offline

job = json.loads(sys.argv[1])
client, art = _clients(Path(job["cache"]), _offline)
out = {}
for name, root in job["roots"].items():
    (unit,) = units(Path(root))
    plan = plan_album(unit, client.release(job["release"]), client, art, status="auto")
    out[name] = base64.b64encode(plan.to_json()).decode("ascii")
    if job["extras"]:
        from musiclib.write import write_album

        write_album(plan, Path(job["extras"][name]))
print(json.dumps(out))
"""


def _offline(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    raise AssertionError(f"a request with a warm cache: {url}")


def _clients(cache: Path, transport) -> tuple[mb.MusicBrainz, caa.CoverArt]:
    store = Cache(cache)
    return (mb.MusicBrainz(store, transport=transport, clock=lambda: 0.0, sleep=lambda s: None),
            caa.CoverArt(store, transport=transport))


def _changes(plan) -> list[str]:
    from musiclib.plan import changes

    return changes(plan)


def _plan_album(*args, **kwargs):
    from musiclib.plan import plan_album

    return plan_album(*args, **kwargs)


def _write_album(*args, **kwargs):
    from musiclib.write import write_album

    return write_album(*args, **kwargs)


def _differing(first: dict, second: dict) -> list[str]:
    """The relative paths whose presence or bytes differ between two `builders.tree` snapshots."""
    missing = object()
    return sorted(p for p in first.keys() | second.keys() if first.get(p, missing) != second.get(p, missing))


class _Determinism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.tmp = Path(tmp.name)
        cls.release = _release(*DISCS)
        # The first plan is the cold one, and the only one that may use the
        # network. Everything after it reads what it left in the cache.
        cls.cache = cls.tmp / "cache"
        client, art = _clients(cls.cache, _Services(cls.release, _release_group({"gothic rock": 9}), True))
        warm_root = cls.tmp / "warm"
        _rip(warm_root, *DISCS)
        client.release(builders.RELEASE_ID)
        _plan_album(next(iter(units(warm_root))), cls.release, client, art, status="auto")

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.tmp))

    def rip(self, root: Path, ext: str) -> Path:
        """The rip, plus a file the write keeps, one it deletes and one it moves to the extras root.

        Two kept files, so a `kept` list built from a set has an order to lose.
        """
        album = _rip(root, *DISCS, ext=ext)
        (album / "rip.log").write_text("Exact Audio Copy V1.6 extraction logfile\n")
        (album / "notes.txt").write_text("Bought at Rough Trade.\n")
        (album / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        (album / "Making of.mkv").write_bytes(b"\x1aE\xdf\xa3 a video")
        return album

    def copies(self, name: str) -> dict[str, Path]:
        """One library root per format under `name`, each holding the rip in that format."""
        roots = {}
        for ext in FORMATS:
            roots[ext] = self.work / name / ext
            self.rip(roots[ext], ext)
        return roots

    def run_child(self, seed: str, roots: dict[str, Path], extras: dict[str, Path] | None) -> dict[str, bytes]:
        """Each root's `to_json()` from a child process hashing strings with `seed`."""
        job = {"cache": str(self.cache), "release": builders.RELEASE_ID,
               "roots": {k: str(v) for k, v in roots.items()},
               "extras": {k: str(v) for k, v in extras.items()} if extras else None}
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-c", _CHILD, json.dumps(job)], cwd=HERE, env=env,
                              capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            self.fail(f"the child process failed:\n{done.stderr[-2000:]}")
        return {k: base64.b64decode(v) for k, v in json.loads(done.stdout).items()}


class TwoPlansOfOneAlbum(_Determinism):
    def test_planning_the_same_files_twice_from_one_warm_cache_gives_byte_identical_plans(self):
        # The copies sit at paths of different length and name, so `root`
        # or any absolute path in the plan shows as a difference.
        first = self.run_child(SEEDS[0], self.copies("first"), None)
        second = self.run_child(SEEDS[1], self.copies("second copy"), None)

        self.assertEqual(sorted(first), sorted(FORMATS))
        for ext in FORMATS:
            with self.subTest(ext):
                self.assertEqual(first[ext], second[ext])


class OnePlanWrittenTwice(_Determinism):
    def test_writing_the_plan_to_two_identical_copies_gives_byte_identical_files(self):
        # Each child plans its own copy and writes that. The case above holds
        # the two plans equal, so a difference here is the write's own.
        first, second = self.copies("first"), self.copies("second copy")
        extras = {name: {ext: self.work / f"{name} extras" / ext for ext in FORMATS}
                  for name in ("first", "second copy")}
        before = {ext: builders.tree(first[ext]) for ext in FORMATS}

        self.run_child(SEEDS[0], first, extras["first"])
        self.run_child(SEEDS[1], second, extras["second copy"])

        for ext in FORMATS:
            with self.subTest(ext):
                # A write that did nothing leaves two identical trees as well.
                self.assertNotEqual(builders.tree(first[ext]), before[ext], "nothing was written")
                self.assertEqual(_differing(builders.tree(first[ext]), builders.tree(second[ext])), [])
                self.assertEqual(_differing(builders.tree(extras["first"][ext]),
                                            builders.tree(extras["second copy"][ext])), [])


class AReplanOfAWrittenAlbum(_Determinism):
    def setUp(self):
        super().setUp()
        self.client, self.art = _clients(self.cache, _offline)

    def plan_rip(self, ext: str, name: str):
        """The rip in `ext` under a root of its own, and its plan. Returns both."""
        root = self.work / name
        self.rip(root, ext)
        (unit,) = units(root)
        plan = _plan_album(unit, self.release, self.client, self.art, status="auto")
        self.assertEqual(list(plan.problems), [], "the rip does not plan clean, so it cannot be written")
        return root, plan

    def write(self, root: Path, plan) -> None:
        _write_album(plan, root.with_name(f"{root.name} extras"))

    def replan(self, root: Path, destination: str):
        """A fresh plan of the album at `destination`, found the way a new run finds it."""
        found = {unit.rel: unit for unit in units(root)}
        self.assertIn(destination, found, "the written album is not where the plan put it")
        return _plan_album(found[destination], self.release, self.client, self.art, status="auto")

    def test_proposes_no_change_after_the_write_where_the_first_plan_proposed_many(self):
        for ext in FORMATS:
            with self.subTest(ext):
                root, first = self.plan_rip(ext, ext)
                # The rip is retitled and renamed, so an empty list below is
                # the write having done it, not `changes` never saying anything.
                self.assertNotEqual(_changes(first), [])
                self.write(root, first)

                self.assertEqual(_changes(self.replan(root, first.destination)), [])

    def test_proposes_the_change_when_one_tag_picture_or_cover_of_the_written_album_is_undone(self):
        # The case above passes for a `changes` that only ever reports moves,
        # since the first plan moves every file. Each undo here leaves every
        # path where the write put it, so only the tag, the picture or the
        # image comparison can see it.
        undos = {
            "a title put back as the rip had it": lambda album, track: builders.write_tags(
                track, builders.picard_tags(track.suffix[1:], {"title": ["plainsong"]}), v2_version=4),
            "the embedded cover stripped": lambda album, track: builders.clear_pictures(track),
            "cover.jpg deleted": lambda album, track: (album / "cover.jpg").unlink(),
        }
        for ext in ("flac", "mp3"):
            for undo, apply in undos.items():
                with self.subTest(ext=ext, undo=undo):
                    root, first = self.plan_rip(ext, f"{ext} {undo}")
                    self.write(root, first)
                    album = root / first.destination
                    track = sorted(album.rglob(f"*.{ext}"))[0]
                    apply(album, track)
                    named = "cover.jpg" if undo == "cover.jpg deleted" else track.name

                    proposed = _changes(self.replan(root, first.destination))

                    self.assertTrue([line for line in proposed if named in line],
                                    f"no change names {named}: {proposed}")


class APlanOfARipWithSubfolders(_Determinism):
    def test_planning_it_under_two_hash_seeds_gives_byte_identical_plans(self):
        # Each subfolder that is not CDn is a problem in the plan, and the
        # plan gathered the subfolders in a set, so the problems came out in
        # hash order. Four names, so two seeds that happen to agree on two
        # still show it.
        folders = ("Extras", "Lyrics", "Scans", "Artwork")
        roots = {}
        for name in ("first", "second copy"):
            roots[name] = self.work / name / "flac"
            album = self.rip(roots[name], "flac")
            for folder in folders:
                (album / folder).mkdir()
                (album / folder / "notes.txt").write_text("Bought at Rough Trade.\n")

        first = self.run_child(SEEDS[0], {"flac": roots["first"]}, None)["flac"]
        second = self.run_child(SEEDS[1], {"flac": roots["second copy"]}, None)["flac"]

        problems = json.loads(first)["problems"]
        self.assertEqual(sorted(f for f in folders if any(f in p for p in problems)), sorted(folders),
                         f"the plan does not name every subfolder: {problems}")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
