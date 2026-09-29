"""`batch identify ROOT --job DIR --rejudge ORIGINAL`: the albums a job tagged, judged again from what they were.

A job of this engine wrote a release ID on albums whose rip had none, or had
another, and it chose the edition without the rip's own cover. The re-judge
identifies each such album from its tags as the job found them and from the
cover in its folder on the read-only drive (`ORIGINAL`), and plans it over
the files as they are now. Where that names another release, the new plan
wins and the images the job saved from the old release go.

The library here is made by a real job, `t1`, built the way `plan.md` runs a
round: rips on disk, `batch identify`, `decisions.json` for the two albums
the owner accepted, identify again, `batch apply`. `ORIGINAL` is a copy of
the rips taken before `t1` ran. Its search lists one edition per album, so
`t1` takes the edition this file needs it to have taken. The re-judging job
`j2` sits beside it, and its search lists every edition. Nothing reaches the
network: MusicBrainz and the Cover Art Archive are one fake transport,
AcoustID is unavailable.

The pictures are `tests.test_cover_ties`'s halves: one white on its left
half (how every *later* edition's front looks), one white on its top half
(every *earlier* one), 32 bits apart. A front at 600 px passes the
cover bar and one at 250 px does not.

`t1` is built once for the module. Each case works on its own copy of the
whole tree, because apply moves the library and a job's `applied.jsonl`
changes what the next job reads.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from musiclib import files, mapping, mb
from musiclib.__main__ import main
from tests import builders
from tests import test_batch_identify as batch
from tests.test_cover_ties import ARCHIVE, Archive, half
from tests.test_identify import search_json

TITLES = ["Prelude", "Theme of Love"]
RELEASE_ID = mapping.PICARD["release id"]["vorbis"]


def solid(rgb: tuple[int, int, int]) -> bytes:
    """A 600 px JPEG in one colour: a booklet page, a back cover, a cover no edition shows."""
    out = io.BytesIO()
    Image.new("RGB", (600, 600), rgb).save(out, "JPEG")
    return out.getvalue()


EARLIER_THUMB, LATER_THUMB = half("top"), half("left")
EARLIER_FRONT, LATER_FRONT = half("top", size=600), half("left", size=600)
#: The later Final Fantasy IV's archive front: too small to pass, so the
#: plan's `cover.jpg` is the local cover it stands beside.
LATER_FRONT_SMALL = half("left")
#: The rip's cover of every job-written album below: drawn like the later edition.
RIP_COVER = half("left", size=600)
TENCC_RIP_COVER = solid((200, 40, 40))
#: What `t1` left as 10cc's `cover.jpg`, where the rip had `TENCC_RIP_COVER`.
TENCC_LIBRARY_COVER = solid((40, 40, 200))
NEVER_COVER = solid((40, 200, 40))
PLAIN_COVER = solid((120, 90, 60))


def edition(number: int, artist: str, title: str, date: str, titles: list[str] = TITLES) -> tuple[dict, dict]:
    found, group = batch.release(number, artist, title, titles)
    found["date"], found["status"] = date, "Official"
    return found, group


UEMATSU, SHIMOMURA = "Nobuo Uematsu", "Yoko Shimomura"

# Each album's rip key under ORIGINAL (and under the library, before t1), its
# editions and what t1 did with it.

# Final Fantasy IV: t1 applied the 1994 book. The rip had no release ID and
# a cover drawn like the 2001 reissue.
IV = "N/Nobuo Uematsu/Final Fantasy IV [rip]"
IV_1994, IV_2001 = edition(11, UEMATSU, "Final Fantasy IV", "1994-08-26"), edition(12, UEMATSU, "Final Fantasy IV", "2001-10-31")

# Final Fantasy V: t1 applied the March edition and saved its back and two
# booklet pages. Both editions are dated 1993, so they share one folder.
V = "N/Nobuo Uematsu/Final Fantasy V [rip]"
V_MARCH, V_DECEMBER = (edition(21, UEMATSU, "Final Fantasy V", "1993-03-25"),
                       edition(22, UEMATSU, "Final Fantasy V", "1993-12-10"))

# Final Fantasy VI: the rip's album artist is the pianist. t1's search found
# the 1994 book, held it for the artist, and the owner accepted it.
VI = "N/Nobuo Uematsu/Final Fantasy VI [rip]"
VI_1994, VI_2001 = (edition(31, UEMATSU, "Final Fantasy VI", "1994-11-25"),
                    edition(32, UEMATSU, "Final Fantasy VI", "2001-10-31"))

# Piano Collections Kingdom Hearts: t1 applied the 2004 edition, the one the
# rip's cover shows.
PCKH = "S/Yoko Shimomura/Piano Collections Kingdom Hearts [rip]"
PCKH_2002, PCKH_2004 = (edition(41, SHIMOMURA, "Piano Collections Kingdom Hearts", "2002-06-19"),
                        edition(42, SHIMOMURA, "Piano Collections Kingdom Hearts", "2004-01-21"))

# Dragon Quest V: t1 applied the 2000 edition and saved its front, which
# looks like it. The rip's folder is not on the drive.
DQ = "K/Koichi Sugiyama/Dragon Quest V [rip]"
DQ_1992, DQ_2000 = (edition(51, "Koichi Sugiyama", "Dragon Quest V", "1992-09-27"),
                    edition(52, "Koichi Sugiyama", "Dragon Quest V", "2000-03-23"))

# Kingdom Hearts Orchestra: the rip carried the 2005 release's ID on every
# file, and the owner accepted the 2008 one in t1. The rip's folder is not on
# the drive either.
KHO = "S/Yoko Shimomura/Kingdom Hearts Orchestra [rip]"
KHO_2005, KHO_2008 = (edition(61, SHIMOMURA, "Kingdom Hearts Orchestra", "2005-03-30"),
                      edition(62, SHIMOMURA, "Kingdom Hearts Orchestra", "2008-04-02"))

# 10cc, How Dare You: the rip already carried the release t1 applied.
TENCC = "#/10cc/How Dare You [rip]"
TENCC_1976 = edition(71, "10cc", "How Dare You", "1976-01-09")

# Found by t1's search. Re-judged, the search finds only an edition with a
# third track, which cannot fit two files, so the re-judge is `unidentified`
# with that edition on top.
NOWHERE = "Z/Zero Band/Nowhere Near [rip]"
NOWHERE_1999 = edition(81, "Zero Band", "Nowhere Near", "1999-05-05")
NOWHERE_LONGER = edition(82, "Zero Band", "Nowhere Near", "1998-05-05", titles=[*TITLES, "Bonus"])

# Put in the library after t1 ran, so no job applied it.
NEVER = "Y/Young Band/Added Later [rip]"
NEVER_2010 = edition(91, "Young Band", "Added Later", "2010-02-02")

APPLIED_BY_T1 = [IV, V, VI, PCKH, DQ, KHO, TENCC, NOWHERE]
GONE_FROM_ORIGINAL = [DQ, KHO]

EDITIONS = [IV_1994, IV_2001, V_MARCH, V_DECEMBER, VI_1994, VI_2001, PCKH_2002, PCKH_2004,
            DQ_1992, DQ_2000, KHO_2005, KHO_2008, TENCC_1976, NOWHERE_1999, NOWHERE_LONGER, NEVER_2010]


def rid(release: tuple[dict, dict]) -> str:
    return release[0]["id"]


def title_of(key: str) -> str:
    return key.split("/")[2].removesuffix(" [rip]").lower()


#: What each job's search lists, by the album title it is asked for. t1 finds
#: one edition; the re-judge finds every edition, earlier first.
T1_SEARCH = {title_of(key): [found] for key, (found, _group) in (
    (IV, IV_1994), (V, V_MARCH), (VI, VI_1994), (PCKH, PCKH_2004), (DQ, DQ_2000), (NOWHERE, NOWHERE_1999))}
J2_SEARCH = {title_of(key): [a[0] for a in found] for key, found in (
    (IV, (IV_1994, IV_2001)), (V, (V_MARCH, V_DECEMBER)), (VI, (VI_1994, VI_2001)),
    (PCKH, (PCKH_2002, PCKH_2004)), (DQ, (DQ_1992, DQ_2000)), (KHO, (KHO_2008,)), (TENCC, (TENCC_1976,)),
    (NOWHERE, (NOWHERE_LONGER,)))}

#: Every image the archive holds, as (release, image id, types, full image, 250 px thumbnail).
#: Each non-front image is its own colour, so no two in a folder share bytes.
PICTURES = [
    (IV_1994, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
    (IV_1994, 2, ("Back",), solid((250, 0, 0)), None),
    (IV_1994, 3, ("Booklet",), solid((0, 250, 0)), None),
    (IV_2001, 1, ("Front",), LATER_FRONT_SMALL, LATER_THUMB),
    (V_MARCH, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
    (V_MARCH, 2, ("Back",), solid((0, 0, 250)), None),
    (V_MARCH, 3, ("Booklet",), solid((250, 250, 0)), None),
    (V_MARCH, 4, ("Booklet",), solid((0, 250, 250)), None),
    (V_DECEMBER, 1, ("Front",), LATER_FRONT, LATER_THUMB),
    (V_DECEMBER, 2, ("Back",), solid((250, 0, 250)), None),
    (VI_1994, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
    (VI_2001, 1, ("Front",), LATER_FRONT, LATER_THUMB),
    (PCKH_2002, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
    (PCKH_2004, 1, ("Front",), LATER_FRONT, LATER_THUMB),
    (DQ_1992, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
    (DQ_2000, 1, ("Front",), LATER_FRONT, LATER_THUMB),
    (KHO_2005, 1, ("Front",), EARLIER_FRONT, EARLIER_THUMB),
]


def archive() -> Archive:
    fake = Archive()
    for release, image_id, types, full, thumb in PICTURES:
        fake.image(rid(release), image_id, {"250": thumb} if thumb else {}, types=types, front=types == ("Front",))
        fake.bodies[f"https://{ARCHIVE}/release/{rid(release)}/{image_id}.jpg"] = full
    return fake


class Services:
    """MusicBrainz and the Cover Art Archive as one transport.

    A search answers from `searches` by the title in its `release:(...)`
    term, and `searched` is every such title, in order. Every release and
    release group in `EDITIONS` is a 200; anything else is a 404.
    """

    def __init__(self, searches: dict[str, list[dict]]) -> None:
        self.searches = searches
        self.catalogue = batch.Services(EDITIONS)
        self.archive = archive()
        self.searched: list[str | None] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc == ARCHIVE:
            return self.archive(url, headers)
        if parts.path.rstrip("/") == "/ws/2/release":
            query = parse_qs(parts.query).get("query", [""])[0]
            found = re.search(r"release:\((.*?)\)", query)
            title = found.group(1) if found else None
            self.searched.append(title)
            return 200, json.dumps(search_json(*self.searches.get(title, []))).encode()
        return self.catalogue(url, headers)


def rip(root: Path, key: str, *, cover: bytes, albumartist: str, release_id: str | None = None,
        others: dict[str, bytes] | None = None) -> None:
    """An album at `root/key` as the owner ripped it: lower-case titles, the album artist given, a `cover.jpg`."""
    base = root / key
    base.mkdir(parents=True)
    for number, title in enumerate(TITLES, start=1):
        path = base / f"{number:02d} {title.lower()}.flac"
        shutil.copyfile(builders.FIXTURES / "tone.flac", path)
        fields = {"title": [title.lower()], "artist": [key.split("/")[1]], "albumartist": [albumartist],
                  "album": [key.split("/")[2].removesuffix(" [rip]")], "date": ["1990"]}
        if release_id:
            fields["release id"] = [release_id]
        builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(TITLES)), disc=(1, 1)))
    (base / "cover.jpg").write_bytes(cover)
    for name, data in (others or {}).items():
        (base / name).write_bytes(data)


def systemctl(folder: Path) -> Path:
    """A stub `systemctl` that says foobar2000 is not running."""
    script = folder / "systemctl"
    script.write_text("#!/bin/sh\necho inactive\nexit 3\n")
    script.chmod(0o755)
    return script


def apply(base: Path, job: Path, services) -> tuple[int, str]:
    from musiclib.batch.apply import run
    from musiclib.batch.job import Job

    out, err = io.StringIO(), io.StringIO()
    code = run(Job(job), base / ".musiclib" / "memory.json", extras_root=base / "extras",
               live_root=base / "library", systemctl=str(systemctl(base)), transport=services, out=out, err=err)
    return code, err.getvalue()


def log(job: Path) -> list[dict]:
    path = job / "applied.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def snapshot(root: Path) -> dict[str, tuple[bytes | None, int]]:
    """Every path under `root` with its bytes (`None` for a folder) and its modification time."""
    return {path.relative_to(root).as_posix(): (path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns)
            for path in [root, *sorted(root.rglob("*"))]}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build(base: Path) -> dict[str, str]:
    """ORIGINAL, the library job t1 left and t1's own job directory under `base`. Returns each rip's current key."""
    original, library = base / "original", base / "library"
    jobs = base / ".musiclib" / "jobs"
    t1 = jobs / "t1"
    t1.mkdir(parents=True)
    base.joinpath("bin").mkdir()

    rip(original, IV, cover=RIP_COVER, albumartist=UEMATSU)
    rip(original, V, cover=RIP_COVER, albumartist=UEMATSU, others={"inside.jpg": solid((90, 90, 90))})
    rip(original, VI, cover=RIP_COVER, albumartist="Toshiyuki Mori")
    rip(original, PCKH, cover=RIP_COVER, albumartist=SHIMOMURA)
    rip(original, DQ, cover=RIP_COVER, albumartist="Koichi Sugiyama")
    rip(original, KHO, cover=PLAIN_COVER, albumartist=SHIMOMURA, release_id=rid(KHO_2005))
    rip(original, TENCC, cover=TENCC_RIP_COVER, albumartist="10cc", release_id=rid(TENCC_1976))
    rip(original, NOWHERE, cover=PLAIN_COVER, albumartist="Zero Band")
    shutil.copytree(original, library)

    memory = base / ".musiclib" / "memory.json"
    code, _out, err = batch.run_identify(library, t1, memory, Services(T1_SEARCH))
    if code != 0:
        raise AssertionError(f"fixture: t1's identify failed: {err}")
    (t1 / "decisions.json").write_text(json.dumps({"job": "t1", "albums": {
        VI: {"action": "accept", "release_id": rid(VI_1994), "edits": {}, "game": None},
        KHO: {"action": "accept", "release_id": rid(KHO_2008), "edits": {}, "game": None},
    }}), encoding="utf-8")
    batch.run_identify(library, t1, memory, Services(T1_SEARCH))
    code, err = apply(base, t1, Services(T1_SEARCH))
    applied = {line["source"]: line["destination"] for line in log(t1) if line["outcome"] == "applied"}
    if code != 0 or sorted(applied) != sorted(APPLIED_BY_T1):
        raise AssertionError(f"fixture: t1 applied {sorted(applied)}, not every album; apply said: {err}")

    # The library's cover differs from the rip's, as it does wherever t1 took
    # the archive's front. Written here, in the folder and in every track,
    # because the archive has none for this release, so the only cover a
    # plan can read is a local one.
    tencc = library / applied[TENCC]
    (tencc / "cover.jpg").write_bytes(TENCC_LIBRARY_COVER)
    for track in tencc.glob("*.flac"):
        builders.embed_picture(track, TENCC_LIBRARY_COVER, replace=True)
    rip(library, NEVER, cover=NEVER_COVER, albumartist="Young Band", release_id=rid(NEVER_2010))
    for key in GONE_FROM_ORIGINAL:
        shutil.rmtree(original / key)
    return applied


def setUpModule():
    global BASE, CURRENT
    tmp = Path(tempfile.mkdtemp())
    unittest.addModuleCleanup(shutil.rmtree, tmp)
    patcher = mock.patch.object(mb, "_MIN_INTERVAL", 0.0)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
    BASE = tmp / "base"
    CURRENT = _build(BASE)


class _Rejudge(unittest.TestCase):
    """A copy of the tree t1 left, and the job `j2` beside t1."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / "base"
        shutil.copytree(BASE, self.base, symlinks=True)
        self.root = self.base / "library"
        self.original = self.base / "original"
        self.job = self.base / ".musiclib" / "jobs" / "j2"
        self.services = Services(J2_SEARCH)

    def identify(self, *, rejudge: bool = True) -> dict[str, dict]:
        """`batch identify` for j2, by current album key. Imported here so the file loads while `--rejudge` does not exist."""
        from musiclib.batch.identify import run
        from musiclib.batch.job import Job

        out, err = io.StringIO(), io.StringIO()
        extra = {"rejudge": self.original} if rejudge else {}
        code = run(self.root, Job(self.job), self.base / ".musiclib" / "memory.json", [],
                   transport=self.services, env={}, which=lambda _name: None, out=out, err=err, **extra)
        self.err = err.getvalue()
        self.assertEqual(code, 0, self.err)
        doc = json.loads((self.job / "plan.json").read_text(encoding="utf-8"))
        return {entry["source"]: entry for entry in doc["albums"]}

    def original_cover(self, key: str) -> str:
        return sha256((self.original / key / "cover.jpg").read_bytes())


class WhatTheRejudgeChooses(_Rejudge):
    def test_final_fantasy_iv_tagged_1994_by_the_job_is_planned_against_the_2001_release_its_rip_and_cover_choose(self):
        entry = self.identify()[CURRENT[IV]]
        self.assertEqual((entry["status"], entry["state"]), ("auto", "auto"), entry["holds"])
        self.assertEqual(entry["release_id"], rid(IV_2001))
        self.assertEqual(entry["candidates"][0]["release_id"], rid(IV_2001))
        # The plan is of the files on disk, which carry what t1 wrote. Planned
        # over the rip's tags instead, apply's stale check would refuse it.
        self.assertEqual({tuple(f["before"].get(RELEASE_ID) or ()) for f in entry["files"]}, {(rid(IV_1994),)})

    def test_final_fantasy_vi_whose_rip_names_toshiyuki_mori_comes_back_review_with_artist_does_not_agree(self):
        # t1 wrote the credit's own name over the pianist's, so judged on the
        # files as they are the artist would agree.
        entry = self.identify()[CURRENT[VI]]
        self.assertEqual(entry["status"], "review")
        self.assertIn({"kind": "status", "detail": "review: artist does not agree"}, entry["holds"])
        self.assertEqual((entry["release_id"], entry["state"]), (rid(VI_2001), "held"))

    def test_an_album_whose_rip_named_another_release_on_every_file_goes_back_to_it_by_the_tagged_path(self):
        # A search would list only the 2008 release, so it could never
        # find the 2005 one.
        entry = self.identify()[CURRENT[KHO]]
        self.assertEqual((entry["status"], entry["release_id"]), ("certain", rid(KHO_2005)))
        self.assertEqual([c["release_id"] for c in entry["candidates"]], [rid(KHO_2005)])
        self.assertNotIn(title_of(KHO), self.services.searched)

    def test_an_album_whose_rejudge_names_the_release_already_on_its_files_is_planned_as_without_rejudge(self):
        # The re-judge searches and comes back `auto` on the 2004 edition.
        # Only the ordinary identification, by the tagged path, is `certain`.
        entry = self.identify()[CURRENT[PCKH]]
        self.assertIn(title_of(PCKH), self.services.searched, "the album was never re-judged")
        self.assertEqual((entry["status"], entry["release_id"], entry["state"]),
                         ("certain", rid(PCKH_2004), "unchanged"))

    def test_an_album_whose_rejudge_is_unidentified_is_planned_as_without_rejudge(self):
        entry = self.identify()[CURRENT[NOWHERE]]
        self.assertIn(title_of(NOWHERE), self.services.searched, "the album was never re-judged")
        self.assertEqual((entry["status"], entry["release_id"], entry["state"]),
                         ("certain", rid(NOWHERE_1999), "unchanged"))

    def test_an_album_whose_rip_already_carried_its_current_release_id_is_not_searched(self):
        entry = self.identify()[CURRENT[TENCC]]
        self.assertNotIn(title_of(TENCC), self.services.searched)
        self.assertEqual((entry["status"], entry["release_id"]), ("certain", rid(TENCC_1976)))

    def test_without_rejudge_every_album_the_job_applied_is_unchanged_and_with_it_six_are_not(self):
        without = self.identify(rejudge=False)
        self.assertEqual({CURRENT[key]: without[CURRENT[key]]["state"] for key in APPLIED_BY_T1},
                         {CURRENT[key]: "unchanged" for key in APPLIED_BY_T1})
        self.assertNotIn("rejudge:", self.err)

        shutil.rmtree(self.job)
        with_it = self.identify()
        # 10cc keeps its release. Its cover changes back to the rip's.
        self.assertEqual({CURRENT[key]: with_it[CURRENT[key]]["state"] for key in APPLIED_BY_T1}, {
            CURRENT[IV]: "auto", CURRENT[V]: "auto", CURRENT[VI]: "held", CURRENT[PCKH]: "unchanged",
            CURRENT[DQ]: "auto", CURRENT[KHO]: "auto", CURRENT[TENCC]: "auto", CURRENT[NOWHERE]: "unchanged"})


class TheOriginalFolder(_Rejudge):
    def test_the_original_folders_cover_is_the_local_cover_of_every_album_a_job_applied_and_only_those(self):
        entries = self.identify()
        for label, key, expected in (
            ("job-written", CURRENT[IV], self.original_cover(IV)),
            ("applied, not job-written", CURRENT[TENCC], self.original_cover(TENCC)),
            ("never applied: its own folder", NEVER, sha256(NEVER_COVER)),
        ):
            with self.subTest(label):
                self.assertEqual(entries[key]["images"]["cover.jpg"]["sha256"], expected)

    def test_an_album_whose_original_folder_is_gone_is_rejudged_with_no_local_cover(self):
        # The library's cover shows the 2000 edition, so reading it instead
        # would keep that edition. With no cover, the oldest is chosen.
        entry = self.identify()[CURRENT[DQ]]
        self.assertEqual((entry["status"], entry["release_id"]), ("auto", rid(DQ_1992)))

    def test_each_album_whose_original_folder_is_gone_is_named_on_stderr_and_counted_once(self):
        self.identify()
        lines = [line for line in self.err.splitlines() if line.startswith("rejudge:")]
        # An album no job applied has no original folder to miss.
        self.assertEqual(sorted(lines), sorted([
            *(f"rejudge: {CURRENT[key]}: no original folder at {self.original / key}" for key in GONE_FROM_ORIGINAL),
            f"rejudge: {len(GONE_FROM_ORIGINAL)} albums had no original folder",
        ]))

    def test_nothing_under_original_is_written_moved_or_deleted_by_identify_or_apply(self):
        before = snapshot(self.original)
        self.identify()
        code, err = apply(self.base, self.job, self.services)
        self.assertTrue(any(line["outcome"] == "applied" for line in log(self.job)),
                        f"apply wrote nothing, so this proves nothing: {err}")
        self.assertEqual(snapshot(self.original), before)


class TheOldReleasesImages(_Rejudge):
    def test_an_album_moving_to_another_release_deletes_the_images_the_job_saved_from_the_old_one(self):
        # IV moves from its 1994 folder to a 2001 one. The 2001 release has
        # no back or booklet, so these two would move with it.
        entry = self.identify()[CURRENT[IV]]
        for name in ("back.jpg", "booklet-01.jpg"):
            with self.subTest(name):
                self.assertIn(f"{CURRENT[IV]}/{name}", entry["deletions"])
                self.assertNotIn(f"{CURRENT[IV]}/{name}", entry["kept"])

    def test_an_album_staying_in_its_folder_deletes_the_old_releases_images_except_names_the_new_plan_writes(self):
        # Both V editions are 1993, so the folder stays. The December
        # edition writes its own cover and back over t1's; deleting those
        # names as well would remove the files the write replaces.
        entry = self.identify()[CURRENT[V]]
        self.assertEqual(entry["release_id"], rid(V_DECEMBER))
        self.assertEqual(entry["destination"], CURRENT[V], "the fixture meant V to stay in its folder")
        folder = CURRENT[V]
        self.assertEqual(sorted(p for p in entry["deletions"] if p.startswith(folder + "/")),
                         [f"{folder}/booklet-01.jpg", f"{folder}/booklet-02.jpg"])
        self.assertEqual(sorted(entry["images"]), ["back.jpg", "cover.jpg"])
        # The owner's own scan was never the job's to delete.
        self.assertIn(f"{folder}/inside.jpg", entry["kept"])


class Applying(_Rejudge):
    def test_batch_apply_writes_a_rejudged_album(self):
        entry = self.identify()[CURRENT[IV]]
        code, err = apply(self.base, self.job, self.services)
        self.assertEqual(code, 0, err)
        self.assertIn((CURRENT[IV], "applied"), [(line["source"], line["outcome"]) for line in log(self.job)])
        for planned in entry["files"]:
            self.assertEqual(files.read(self.root / planned["destination"]).tags.get(RELEASE_ID), [rid(IV_2001)])
        folder = self.root / entry["destination"]
        self.assertEqual(sha256((folder / "cover.jpg").read_bytes()), self.original_cover(IV))
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.suffix == ".jpg"), ["cover.jpg"])

    def test_batch_apply_refuses_a_rejudged_album_as_changed_when_the_original_folder_has_gone(self):
        # The drive unmounted between identify and apply.
        self.identify()
        before = builders.tree(self.root / CURRENT[IV])
        self.original.rename(self.base / "unmounted")
        code, err = apply(self.base, self.job, self.services)
        self.assertEqual(code, 1)
        self.assertIn(f"{CURRENT[IV]}: its plan has changed since identify; refused", err.splitlines())
        self.assertNotIn(CURRENT[IV], [line["source"] for line in log(self.job)])
        self.assertEqual(builders.tree(self.root / CURRENT[IV]), before)


class TheFlag(unittest.TestCase):
    def test_batch_identify_help_lists_rejudge_original(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(["batch", "identify", "--help"])
        self.assertIn("--rejudge ORIGINAL", out.getvalue())

    def test_rejudge_reaches_identify_and_is_absent_without_the_flag(self):
        with mock.patch("musiclib.batch.identify.run", return_value=0) as run:
            main(["batch", "identify", "/lib", "--job", "/jobs/j2", "--rejudge", "/mnt/falchion/Musica"])
            main(["batch", "identify", "/lib", "--job", "/jobs/j2"])
        given, absent = (call.kwargs.get("rejudge") for call in run.call_args_list)
        self.assertIsNotNone(given, "--rejudge never reached identify")
        self.assertEqual(Path(given), Path("/mnt/falchion/Musica"))
        self.assertIsNone(absent)


if __name__ == "__main__":
    unittest.main()
