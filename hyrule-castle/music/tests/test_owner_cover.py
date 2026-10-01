"""The owner's own cover, named by an `accept` in `decisions.json`.

The accept carries `"cover": "owner/cover.png"`, a path inside the job
directory. That image becomes `cover.jpg` and the picture embedded in every
track, as a JPEG, over the Cover Art Archive's front whether that front
passes the cover test or not. `batch apply` reads the image from the job
again and refuses the album as changed where it is not the image identify
planned with.

Every job is built the way `tests.test_batch_apply` builds one: a rip on
disk, `batch identify` over it, `decisions.json` by hand, identify again to
fold it in, then apply against a transport that refuses every request. The
transport identify gets is `tests.test_batch_identify.Services` for
MusicBrainz with an archive in front of it that lists one release: a front
and a back, served at full size.

The cases of the archive failing, the files' embedded front and no cover
at all apply through `Job.apply`, which hands apply the archive as it
answers at that moment: identify caches no failed answer, so apply asks
the archive again for whatever failed.

Every picture here is one flat colour, each a different one, so a file on
disk can be told apart from every other by its pixels even after a PNG is
converted to JPEG.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from mutagen.flac import FLAC
from PIL import Image

from tests import builders
from tests.test_batch_apply import Library, new_library
from tests.test_batch_identify import Services, run_identify

KEY = "A/Alpha/First [rip]"
ARCHIVE = "coverartarchive.org"
OWNER_PATH = "owner/cover.png"


def picture(size: tuple[int, int], colour: tuple[int, int, int], fmt: str = "JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


# The owner's cover fails the cover test on both counts (4:3, shorter side
# 300), so an engine that runs it through the test would pick something else.
OWNER_COLOUR = (200, 30, 90)
OWNER_PNG = picture((400, 300), OWNER_COLOUR, "PNG")
OWNER_JPEG = picture((400, 300), OWNER_COLOUR)
# What the owner puts in place of the first image, for apply to find.
REPLACED_PNG = picture((400, 300), (10, 200, 200), "PNG")

PASSING_FRONT = picture((600, 600), (20, 160, 40))
FAILING_FRONT = picture((300, 300), (20, 160, 40))
BACK = picture((500, 500), (30, 60, 200))

# The rip's own images. `folder.jpg` passes and `front.jpg` does not, so
# with a failing archive front and no owner cover `folder.jpg` is the cover
# today and is consumed; `front.*` ranks above `folder.*`, so a `front.jpg`
# that passed would take the cover instead and the case would prove nothing.
FOLDER = picture((600, 600), (240, 200, 20))
FRONT = picture((300, 200), (90, 90, 90))

# The front every track already carries, 500 by 500 as Waking Up's FLACs do.
EMBEDDED = picture((500, 500), (120, 40, 160))

UNAVAILABLE = "cover art archive unavailable:"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def front_url(release_id: str) -> str:
    return f"https://{ARCHIVE}/release/{release_id}/1.jpg"


class Archive:
    """MusicBrainz through `Services`, and the Cover Art Archive listing `front` and `BACK` for `release_id`.

    With `front` None the release lists only the back, and the release
    group has nothing. A URL in `statuses` answers that status and no body.
    """

    def __init__(self, catalogue: list[tuple[dict, dict]], release_id: str, front: bytes | None,
                 statuses: dict[str, int] | None = None) -> None:
        self.services = Services(catalogue)
        base = f"https://{ARCHIVE}/release/{release_id}"
        self.listing = f"/release/{release_id}"
        self.images = [
            {"id": 1, "types": ["Front"], "front": True, "back": False, "approved": True, "comment": "",
             "edit": 1, "image": front_url(release_id), "thumbnails": {}},
            {"id": 2, "types": ["Back"], "front": False, "back": True, "approved": True, "comment": "",
             "edit": 1, "image": f"{base}/2.jpg", "thumbnails": {}},
        ]
        self.bodies = {front_url(release_id): front, f"{base}/2.jpg": BACK}
        if front is None:
            self.images, self.bodies = self.images[1:], {f"{base}/2.jpg": BACK}
        self.statuses = dict(statuses or {})

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc != ARCHIVE:
            return self.services(url, headers)
        if url in self.statuses:
            return self.statuses[url], b"Internal Server Error"
        if parts.path.rstrip("/") == self.listing:
            return 200, json.dumps({"images": self.images, "release": url}).encode()
        if url in self.bodies:
            return 200, self.bodies[url]
        return 404, b"Not Found"


class Job:
    """One album, `KEY`, in a `Library`, with the rip's `folder.jpg` and `front.jpg` and no `cover.jpg`."""

    def __init__(self, case: unittest.TestCase, front: bytes | None) -> None:
        self.lib: Library = new_library(case)
        self.folder = self.lib.add(KEY, 1)
        (self.folder / "cover.jpg").unlink()
        (self.folder / "folder.jpg").write_bytes(FOLDER)
        (self.folder / "front.jpg").write_bytes(FRONT)
        self.release_id = self.lib.catalogue[0][0]["id"]
        self.front = front
        #: What the archive answers in place of a 200, by URL, at the next identify or apply.
        self.statuses: dict[str, int] = {}

    def archive(self) -> Archive:
        return Archive(self.lib.catalogue, self.release_id, self.front, self.statuses)

    def front_url(self) -> str:
        return front_url(self.release_id)

    def identify(self) -> tuple[int, str, str]:
        return run_identify(self.lib.root, self.lib.job, self.lib.memory, self.archive())

    def apply(self) -> tuple[int, str, str]:
        """`batch.apply.run` as `Library.apply` runs it, but against the archive as it answers now.

        Identify caches no failed answer, so an album planned through a
        failure asks the archive again at apply.
        """
        from musiclib.batch.apply import run
        from musiclib.batch.job import Job as JobDir

        out, err = io.StringIO(), io.StringIO()
        code = run(JobDir(self.lib.job), self.lib.memory, extras_root=self.lib.extras, live_root=self.lib.root,
                   systemctl=str(self.lib.systemctl(False)), transport=self.archive(), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def without_folder_covers(self) -> None:
        (self.folder / "folder.jpg").unlink()
        (self.folder / "front.jpg").unlink()

    def embed(self, data: bytes) -> None:
        """Every track carries `data` as its one front picture."""
        for track in sorted(self.folder.glob("*.flac")):
            builders.embed_picture(track, data, replace=True)

    def owner_cover(self, data: bytes, path: str = OWNER_PATH) -> None:
        target = self.lib.job / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def accept(self, cover: str | None = OWNER_PATH) -> None:
        """The page's accept of `KEY` naming `cover`, and identify again to fold it in."""
        (self.lib.job / "decisions.json").write_text(json.dumps({"job": "j1", "albums": {KEY: {
            "action": "accept", "release_id": self.release_id, "edits": {}, "game": None, "cover": cover,
        }}}), encoding="utf-8")
        code, _out, err = self.identify()
        assert code == 0, err

    def entry(self) -> dict:
        return self.lib.entries()[KEY]

    def destination(self) -> Path:
        return self.lib.root / self.entry()["destination"]


class _Case(unittest.TestCase):
    def assertOwnerJpeg(self, data: bytes) -> None:
        """`data` is a JPEG of the owner's picture: its size, and its colour give or take the compression."""
        self.assertEqual(data[:3], b"\xff\xd8\xff", "not a JPEG")
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (400, 300))
            pixel = image.convert("RGB").getpixel((200, 150))
        for got, want in zip(pixel, OWNER_COLOUR):
            self.assertAlmostEqual(got, want, delta=8, msg=f"{pixel} is not the owner's colour")

    def assertEmbedded(self, folder: Path, cover: bytes) -> None:
        """Every track under `folder` carries one front picture, `cover`, byte for byte."""
        tracks = sorted(folder.rglob("*.flac"))
        self.assertEqual(len(tracks), 2, f"tracks under {folder}: {tracks}")
        for track in tracks:
            self.assertEqual([(p.type, p.data) for p in FLAC(track).pictures], [(3, cover)], track.name)

    def applied(self, job: Job) -> None:
        code, _out, err = job.lib.apply()
        self.assertEqual(code, 0, err)
        entry = job.entry()
        self.assertEqual([(line["source"], line["outcome"], line["plan_digest"]) for line in job.lib.log()],
                         [(KEY, "applied", entry["plan_digest"])])

    def appliedOwnerCover(self, job: Job) -> None:
        """`job.apply()` writes the album with the owner's image as `cover.jpg` and in every track."""
        code, _out, err = job.apply()
        self.assertEqual(code, 0, err)
        self.assertEqual([(line["source"], line["outcome"]) for line in job.lib.log()], [(KEY, "applied")])
        folder = job.destination()
        cover = (folder / "cover.jpg").read_bytes()
        self.assertOwnerJpeg(cover)
        self.assertEmbedded(folder, cover)

    def assertRefused(self, job: Job, before: dict, line: str | None = None) -> None:
        """`job.apply()` exits 1, names `KEY` on stderr (with `line` exactly, where given), and writes nothing."""
        code, _out, err = job.apply()
        self.assertEqual(code, 1, err)
        if line is None:
            self.assertTrue(any(text.startswith(f"{KEY}: ") for text in err.splitlines()), err)
        else:
            self.assertIn(line, err.splitlines())
        self.assertEqual(job.lib.log(), [])
        self.assertEqual(builders.tree(job.lib.root), before)


class OverAPassingArchiveFront(_Case):
    def setUp(self):
        self.job = Job(self, PASSING_FRONT)
        self.job.identify()
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()

    def test_the_plan_puts_the_owners_image_in_cover_jpg_and_keeps_the_archives_back(self):
        images = self.job.entry()["images"]
        self.assertNotEqual(images["cover.jpg"]["sha256"], sha256(PASSING_FRONT))
        self.assertEqual(images["back.jpg"]["sha256"], sha256(BACK))

    def test_the_plan_records_the_owner_cover_path_and_the_sha256_of_its_bytes(self):
        self.assertEqual(self.job.entry()["inputs"]["owner_cover"], {"path": OWNER_PATH, "sha256": sha256(OWNER_PNG)})

    def test_apply_writes_the_owners_png_as_cover_jpg_and_embeds_the_same_bytes_in_every_track(self):
        self.applied(self.job)
        folder = self.job.destination()
        cover = (folder / "cover.jpg").read_bytes()
        self.assertOwnerJpeg(cover)
        # What was written is what the page was shown.
        self.assertEqual(sha256(cover), self.job.entry()["images"]["cover.jpg"]["sha256"])
        self.assertEmbedded(folder, cover)
        self.assertEqual((folder / "back.jpg").read_bytes(), BACK)
        self.assertEqual((folder / "front.jpg").read_bytes(), FRONT)


class OverAFailingArchiveFront(_Case):
    def setUp(self):
        self.job = Job(self, FAILING_FRONT)
        code, _out, err = self.job.identify()
        self.assertEqual(code, 0, err)
        # Without the owner's cover, the rip's folder.jpg beats the failing
        # front: the owner's cover has something to take the place of.
        self.assertEqual(self.job.entry()["images"]["cover.jpg"]["sha256"], sha256(FOLDER))
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()

    def test_apply_writes_the_owners_image_removes_the_folder_jpg_it_replaces_and_keeps_front_jpg(self):
        self.applied(self.job)
        source, destination = self.job.lib.root / KEY, self.job.destination()
        # The fixture moves the album, so a file left in either folder shows.
        self.assertNotEqual(source, destination)
        cover = (destination / "cover.jpg").read_bytes()
        self.assertOwnerJpeg(cover)
        self.assertEmbedded(destination, cover)
        self.assertEqual((destination / "back.jpg").read_bytes(), BACK)
        self.assertEqual((destination / "front.jpg").read_bytes(), FRONT)
        self.assertEqual(sorted(p.name for p in destination.iterdir() if p.suffix == ".jpg"),
                         ["back.jpg", "cover.jpg", "front.jpg"])
        self.assertFalse((source / "folder.jpg").exists())


class AJpegOwnerCover(_Case):
    def test_a_jpeg_owner_cover_is_written_as_cover_jpg_byte_for_byte(self):
        job = Job(self, PASSING_FRONT)
        job.identify()
        job.owner_cover(OWNER_JPEG, "owner/cover.jpg")
        job.accept("owner/cover.jpg")
        self.applied(job)
        cover = (job.destination() / "cover.jpg").read_bytes()
        self.assertEqual(cover, OWNER_JPEG)
        self.assertEmbedded(job.destination(), OWNER_JPEG)


class ApplyRefusesAChangedImage(_Case):
    def setUp(self):
        self.job = Job(self, PASSING_FRONT)
        self.job.identify()
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()
        self.before = builders.tree(self.job.lib.root)

    def assertRefusedAsChanged(self) -> None:
        code, _out, err = self.job.lib.apply()
        self.assertEqual(code, 1, err)
        self.assertIn(f"{KEY}: its plan has changed since identify; refused", err.splitlines())
        self.assertEqual(self.job.lib.log(), [])
        self.assertEqual(builders.tree(self.job.lib.root), self.before)

    def test_apply_refuses_the_album_as_changed_when_the_image_was_replaced_after_identify(self):
        self.job.owner_cover(REPLACED_PNG)
        self.assertRefusedAsChanged()

    def test_apply_refuses_the_album_as_changed_when_the_image_was_deleted_after_identify(self):
        (self.job.lib.job / OWNER_PATH).unlink()
        self.assertRefusedAsChanged()


class TheCoverPathIsRefused(unittest.TestCase):
    """`decisions.read` against a job one real identify has planned, copied per case as `tests.test_decisions` does."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        job = Job(cls, PASSING_FRONT)
        code, _out, err = job.identify()
        assert code == 0, err
        cls.template = job.lib.job
        cls.release_id = job.release_id
        cls.scratch = Path(tmp.name)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.job = self.base / "jobs" / "j1"
        shutil.copytree(self.template, self.job)
        (self.job / "owner").mkdir()
        (self.job / OWNER_PATH).write_bytes(OWNER_PNG)

    def read(self, cover):
        from musiclib.batch import decisions
        from musiclib.batch.job import Job as JobDir

        (self.job / "decisions.json").write_text(json.dumps({"job": "j1", "albums": {KEY: {
            "action": "accept", "release_id": self.release_id, "edits": {}, "game": None, "cover": cover,
        }}}), encoding="utf-8")
        return decisions.read(JobDir(self.job))

    def assertRejected(self, cover, *named: str) -> None:
        from musiclib.batch import decisions

        with self.assertRaises(decisions.DecisionsRejected) as raised:
            self.read(cover)
        for text in (repr(KEY), *named):
            self.assertIn(text, str(raised.exception))

    def test_a_cover_inside_the_job_is_read(self):
        # Guards the refusals below against a reader that refuses every cover.
        self.assertEqual(self.read(OWNER_PATH)["albums"][KEY]["cover"], OWNER_PATH)

    def test_a_cover_that_is_not_a_string_is_refused(self):
        self.assertRejected(["owner/cover.png"], "cover")

    def test_an_absolute_cover_path_is_refused_even_inside_the_job(self):
        absolute = str(self.job / OWNER_PATH)
        self.assertRejected(absolute, absolute)

    def test_a_cover_path_through_dot_dot_is_refused_even_when_it_lands_back_in_the_job(self):
        through = "owner/../owner/cover.png"
        self.assertRejected(through, through)

    def test_a_cover_whose_file_is_a_link_out_of_the_job_is_refused(self):
        outside = self.base / "elsewhere.png"
        outside.write_bytes(OWNER_PNG)
        os.symlink(outside, self.job / "owner" / "link.png")
        self.assertRejected("owner/link.png", "owner/link.png")


class OverAFailedArchiveFront(_Case):
    """Waking Up, accepted with an owner cover while its front answers 500."""

    def setUp(self):
        self.job = Job(self, PASSING_FRONT)
        self.job.statuses = {self.job.front_url(): 500}
        code, _out, err = self.job.identify()
        self.assertEqual(code, 0, err)
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()

    def test_the_accepted_album_carries_only_the_archive_note_which_names_the_front_and_the_owners_cover(self):
        holds = self.job.entry()["holds"]
        # One `validation` hold and nothing else: no `decision` hold keeps
        # apply off it, and no `cover.jpg` or `embedded cover` problem is shown.
        self.assertEqual([hold["kind"] for hold in holds], ["validation"], holds)
        detail = holds[0]["detail"]
        self.assertTrue(detail.startswith(UNAVAILABLE), detail)
        for named in (self.job.front_url(), "500", "the owner's"):
            self.assertIn(named, detail)

    def test_apply_with_the_front_still_failing_writes_the_owners_image_as_cover_jpg_and_in_every_track(self):
        self.appliedOwnerCover(self.job)


class OverTheFilesEmbeddedFront(_Case):
    """The archive has no front and every track carries one."""

    def setUp(self):
        self.job = Job(self, None)
        self.job.without_folder_covers()
        self.job.embed(EMBEDDED)
        code, _out, err = self.job.identify()
        self.assertEqual(code, 0, err)
        # Without the owner's cover the files' front is the cover, so the
        # owner's has something to take the place of.
        planned = self.job.entry()["images"].get("cover.jpg")
        self.assertEqual(planned and planned["sha256"], sha256(EMBEDDED), "the files' front is not the cover")
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()

    def test_apply_writes_the_owners_image_as_cover_jpg_and_replaces_the_tracks_picture_with_it(self):
        self.appliedOwnerCover(self.job)


class OverAFolderCover(_Case):
    """The archive has no front, the files carry none, and `folder.jpg` passes."""

    def setUp(self):
        self.job = Job(self, None)
        code, _out, err = self.job.identify()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.job.entry()["images"]["cover.jpg"]["sha256"], sha256(FOLDER))
        self.job.owner_cover(OWNER_PNG)
        self.job.accept()

    def test_apply_writes_the_owners_image_as_cover_jpg_and_in_every_track(self):
        self.appliedOwnerCover(self.job)


class ApplyAfterTheArchiveAnswersAgain(_Case):
    """Identify saw the front fail, and by apply it answers."""

    CHANGED = f"{KEY}: its plan has changed since identify; refused"

    def accepted_through_a_failed_front(self, cover: str | None) -> Job:
        job = Job(self, PASSING_FRONT)
        job.statuses = {job.front_url(): 500}
        job.identify()
        if cover is not None:
            job.owner_cover(OWNER_PNG)
        job.accept(cover)
        # A `decision` hold would refuse the album for another reason.
        self.assertNotIn("decision", [hold["kind"] for hold in job.entry()["holds"]])
        return job

    def test_apply_refuses_the_album_as_changed_where_the_cover_came_from_the_folder(self):
        job = self.accepted_through_a_failed_front(None)
        before = builders.tree(job.lib.root)
        job.statuses = {}
        self.assertRefused(job, before, self.CHANGED)

    def test_apply_refuses_the_album_as_changed_even_where_the_owners_cover_is_the_cover_either_way(self):
        job = self.accepted_through_a_failed_front(OWNER_PATH)
        before = builders.tree(job.lib.root)
        job.statuses = {}
        self.assertRefused(job, before, self.CHANGED)


class AnAcceptWithNoCoverAnywhere(_Case):
    """No owner cover, no archive front, no embedded picture and no folder cover."""

    def accepted(self, front: bytes | None, failing: bool) -> Job:
        job = Job(self, front)
        job.without_folder_covers()
        if failing:
            job.statuses = {job.front_url(): 500}
        job.identify()
        job.accept(None)
        self.assertNotIn("cover.jpg", job.entry().get("images") or {})
        return job

    def test_batch_apply_refuses_it_where_the_archive_answered_with_no_front(self):
        job = self.accepted(None, failing=False)
        self.assertRefused(job, builders.tree(job.lib.root))

    def test_batch_apply_refuses_it_where_the_archives_front_failed(self):
        job = self.accepted(PASSING_FRONT, failing=True)
        self.assertRefused(job, builders.tree(job.lib.root))


if __name__ == "__main__":
    unittest.main()
