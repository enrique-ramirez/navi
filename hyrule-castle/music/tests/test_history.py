"""A file's original tags, an album's original source and the images earlier jobs created, read from the jobs' records.

`--rejudge` has to know what an album looked like before any job wrote it.
The only record of that is the `applied.jsonl` of each job beside `DIR`: an
`applied` line's `tags` hold every track's tags as they were just before
that write, keyed by where the track went, and its `moves` say where it came
from. A track two jobs moved has to be followed back through both, or the
"original" is only what the first job wrote.

The two jobs here are built the way `batch.apply` and `batch.rollback` write
them: `write._record` for the record, `job.append_log` for the line, and
each track's prior tags read off a real tagged file with `files.read`, so a
record shape that drifted in the writer drifts here too. Every path is
relative to the library root, as the records hold them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from musiclib import files
from musiclib.batch import job as job_module
from musiclib.batch.job import Job
from musiclib.write import _record
from tests import builders

#: What a job wrote on the three Final Fantasy albums: the score book's
#: release, not the reissue. Made up; only its difference from the others counts.
SCORE_BOOK = "00000000-0000-4000-8000-0000000000b0"
REISSUE = "636e958b-54bc-36e5-adc7-54f51ea4602e"
HOW_DARE_YOU = "c934405c-0173-4669-8d02-7c9c9b3d51be"
SOMETHING_ELSE = "00000000-0000-4000-8000-0000000000e1"

# Final Fantasy IV: moved by both jobs. The newer one re-applied it under the
# same release, so the tags it recorded already carry SCORE_BOOK. Only the
# older job's record holds the rip as it was.
FF4_ORIGINAL = "N/Nobuo Uematsu/(1992) Final Fantasy IV - Piano Collections"
FF4_OLDER = "N/Nobuo Uematsu/(1992) Piano Collections Final Fantasy IV"
FF4_NEWER = "N/Nobuo Uematsu/(1992) Final Fantasy IV Piano Collections"
FF4_TRACKS = ["01. Prelude.flac", "02. Theme of Love.flac"]
FF4_RIP_TRACKS = ["01 prelude.flac", "02 theme of love.flac"]

# Final Fantasy V: the older job tried it once and failed, the owner fixed
# the rip (its tags and its folder name) and the same job applied it.
FF5_ORIGINAL = "N/Nobuo Uematsu/(1993) Final Fantasy V - Piano Collections"
FF5_FIRST_TRY = "N/Nobuo Uematsu/ff5 pc [rip]"
FF5_OLDER = "N/Nobuo Uematsu/(1993) Piano Collections Final Fantasy V"

# 10cc: moved by the older job only, an MP3 whose tags already named its release.
TENCC_ORIGINAL = "#/10cc/How Dare You!"
TENCC_OLDER = "#/10cc/(1976) How Dare You!"

# Moved by the newer job only, an M4A whose tags named another release.
KH_ORIGINAL = "S/Yoko Shimomura/Piano Collections Kingdom Hearts"
KH_NEWER = "S/Yoko Shimomura/(2004) Piano Collections KINGDOM HEARTS"

# Applied in place by both jobs. The newer one wrote its own cover over the
# older one's, kept the back cover where it was and deleted the booklet page.
TWICE_IN_PLACE = "T/Twice Band/(2005) Written Twice"

# Written in place (source and destination the same folder), then undone.
MOVES_UNDONE = "H/Halfway Band/(2000) Stopped Halfway"
ROLLED_BACK = "P/Put Back Band/(2001) Put Back"

NEVER_APPLIED = "U/Untouched/(1999) Nobody Wrote This"


def _tags(scratch: Path, ext: str, fields: dict[str, list[str]]) -> dict:
    """`fields` written Picard's way onto a real `ext` file, read back as `write._prior_tags` records them."""
    path = builders.copy_fixture(scratch, ext, f"t{len(list(scratch.iterdir()))}")
    builders.write_tags(path, builders.picard_tags(ext, fields))
    return files.read(path).tags


def _line(source: str, destination: str, outcome: str, record: dict | None, error: str | None = None) -> dict:
    """One `applied.jsonl` line, in the envelope `batch.apply` and `batch.rollback` write."""
    return {"source": source, "destination": destination, "outcome": outcome, "error": error, "record": record}


def _library(pairs: list[tuple[str, str]]) -> list[list[str]]:
    return [[source, destination, "library"] for source, destination in pairs]


def _build(jobs: Path, scratch: Path) -> dict:
    """Two applied jobs and the job being re-judged, under `jobs`. Returns the tags the cases compare against."""
    # How a job's age is known is open, so every signal here
    # agrees: the older job sorts first by name and has the older times.
    # No case below depends on which one the engine reads.
    older, newer, current = Job(jobs / "job-1"), Job(jobs / "job-2"), Job(jobs / "job-3")
    for job in (older, newer, current):
        job.path.mkdir(parents=True)
    # `job-3` is DIR itself, with no `applied.jsonl` yet: the first
    # `--rejudge` identify runs before that job has applied anything.

    ff4_rip = [_tags(scratch, "flac", {"album": ["Final Fantasy IV - Piano Collections"],
                                       "albumartist": ["Toshiyuki Mori"], "title": [title]})
               for title in ("Prelude", "Theme of Love")]
    ff4_written = [_tags(scratch, "flac", {"album": ["Piano Collections Final Fantasy IV"],
                                           "albumartist": ["植松伸夫"], "title": [title],
                                           "release id": [SCORE_BOOK]})
                   for title in ("Prelude", "Theme of Love")]
    ff5_first_try = _tags(scratch, "flac", {"album": ["ff5 pc"], "title": ["Main Theme"]})
    ff5_rip = _tags(scratch, "flac", {"album": ["Final Fantasy V - Piano Collections"],
                                      "title": ["Main Theme of Final Fantasy V"]})
    tencc_rip = _tags(scratch, "mp3", {"album": ["How Dare You!"], "title": ["How Dare You"],
                                       "release id": [HOW_DARE_YOU]})
    kh_rip = _tags(scratch, "m4a", {"album": ["Piano Collections Kingdom Hearts"], "title": ["Dearly Beloved"],
                                    "release id": [SOMETHING_ELSE]})
    in_place_rip = _tags(scratch, "flac", {"album": ["Stopped Halfway"], "title": ["One"]})

    ff4_older = [f"{FF4_OLDER}/{name}" for name in FF4_TRACKS]
    ff4_newer = [f"{FF4_NEWER}/{name}" for name in FF4_TRACKS]
    ff5_older = f"{FF5_OLDER}/01. Main Theme of Final Fantasy V.flac"
    tencc_older = f"{TENCC_OLDER}/01. How Dare You.mp3"
    undone_track = f"{MOVES_UNDONE}/01. One.flac"
    rolled_track = f"{ROLLED_BACK}/01. One.flac"
    twice_track = f"{TWICE_IN_PLACE}/01. One.flac"

    for line in [
        _line(FF4_ORIGINAL, FF4_OLDER, "applied", _record(
            tags=dict(zip(ff4_older, ff4_rip)),
            moves=(_library([(f"{FF4_ORIGINAL}/{rip}", dest) for rip, dest in zip(FF4_RIP_TRACKS, ff4_older)])
                   + [[f"{FF4_ORIGINAL}/scans/obi.jpg", f"{FF4_OLDER}/scans/obi.jpg", "extras"]]),
            created=[f"{FF4_OLDER}/cover.jpg", f"{FF4_OLDER}/back.jpg", f"{FF4_OLDER}/booklet-01.jpg"],
            deleted=[f"{FF4_ORIGINAL}/folder.jpg"])),
        # A tag-stage failure: the first track was written and put back, so
        # the record names its prior tags and every move, all of it undone.
        _line(FF5_FIRST_TRY, FF5_OLDER, "failed", _record(
            tags={ff5_older: ff5_first_try},
            moves=_library([(f"{FF5_FIRST_TRY}/01.flac", ff5_older)]),
            created=[], deleted=[]), error=f"{FF5_OLDER}/02. Mog.flac: did not verify"),
        _line(FF5_ORIGINAL, FF5_OLDER, "applied", _record(
            tags={ff5_older: ff5_rip},
            moves=_library([(f"{FF5_ORIGINAL}/01 main theme.flac", ff5_older)]),
            created=[f"{FF5_OLDER}/cover.jpg"], deleted=[])),
        _line(TENCC_ORIGINAL, TENCC_OLDER, "applied", _record(
            tags={tencc_older: tencc_rip},
            moves=_library([(f"{TENCC_ORIGINAL}/01 How Dare You.mp3", tencc_older)]),
            created=[], deleted=[])),
        _line(MOVES_UNDONE, MOVES_UNDONE, "applied", _record(
            tags={undone_track: in_place_rip},
            moves=_library([(undone_track, undone_track)]), created=[], deleted=[])),
        # A rollback that stopped after putting the files back and before
        # their tags: the tracks still carry what the job wrote.
        _line(MOVES_UNDONE, MOVES_UNDONE, "moves undone", None),
        _line(TWICE_IN_PLACE, TWICE_IN_PLACE, "applied", _record(
            tags={twice_track: in_place_rip},
            moves=_library([(twice_track, twice_track)]),
            created=[f"{TWICE_IN_PLACE}/cover.jpg", f"{TWICE_IN_PLACE}/back.jpg",
                     f"{TWICE_IN_PLACE}/booklet-01.jpg"],
            deleted=[])),
    ]:
        job_module.append_log(older, line)

    for line in [
        _line(FF4_OLDER, FF4_NEWER, "applied", _record(
            tags=dict(zip(ff4_newer, ff4_written)),
            moves=_library(list(zip(ff4_older, ff4_newer))
                           + [(f"{FF4_OLDER}/back.jpg", f"{FF4_NEWER}/back.jpg"),
                              (f"{FF4_OLDER}/booklet-01.jpg", f"{FF4_NEWER}/booklet-01.jpg")]),
            # The album moved, so the plan deleted the cover the older job
            # made and wrote its own: `plan.sort_others` on a moving album.
            created=[f"{FF4_NEWER}/cover.jpg"],
            deleted=[f"{FF4_OLDER}/cover.jpg"])),
        _line(KH_ORIGINAL, KH_NEWER, "applied", _record(
            tags={f"{KH_NEWER}/01. Dearly Beloved.m4a": kh_rip},
            moves=_library([(f"{KH_ORIGINAL}/01 Dearly Beloved.m4a", f"{KH_NEWER}/01. Dearly Beloved.m4a")]),
            created=[f"{KH_NEWER}/cover.jpg"], deleted=[])),
        _line(ROLLED_BACK, ROLLED_BACK, "applied", _record(
            tags={rolled_track: in_place_rip},
            moves=_library([(rolled_track, rolled_track)]), created=[], deleted=[])),
        _line(ROLLED_BACK, ROLLED_BACK, "moves undone", None),
        _line(ROLLED_BACK, ROLLED_BACK, "rolled back", None),
        _line(TWICE_IN_PLACE, TWICE_IN_PLACE, "applied", _record(
            tags={twice_track: in_place_rip},
            moves=_library([(twice_track, twice_track),
                            (f"{TWICE_IN_PLACE}/back.jpg", f"{TWICE_IN_PLACE}/back.jpg")]),
            created=[f"{TWICE_IN_PLACE}/cover.jpg"],
            deleted=[f"{TWICE_IN_PLACE}/booklet-01.jpg"])),
    ]:
        job_module.append_log(newer, line)

    now = time.time()
    for age, job in ((3, older), (2, newer), (1, current)):
        for path in (job.applied, job.path):
            if path.exists():
                os.utime(path, (now - age * 86400, now - age * 86400))

    return {"ff4_rip": ff4_rip, "ff5_rip": ff5_rip, "kh_rip": kh_rip}


def setUpModule():
    global JOBS, RECORDED
    tmp = Path(tempfile.mkdtemp())
    unittest.addModuleCleanup(shutil.rmtree, tmp)
    (tmp / "scratch").mkdir()
    JOBS = tmp / "jobs"
    RECORDED = _build(JOBS, tmp / "scratch")


class _Loaded(unittest.TestCase):
    def setUp(self):
        from musiclib.batch import history
        self.history = history.load(JOBS)


class OriginalTags(_Loaded):
    def test_a_track_both_jobs_moved_gets_the_tags_the_older_job_recorded(self):
        # The newer job's record holds what the older job wrote, release ID
        # and all. Stopping there reads a job's own write as the rip.
        for index, name in enumerate(FF4_TRACKS):
            with self.subTest(track=name):
                self.assertEqual(self.history.original_tags(f"{FF4_NEWER}/{name}"), RECORDED["ff4_rip"][index])

    def test_a_track_only_the_newer_job_moved_gets_that_jobs_record(self):
        self.assertEqual(self.history.original_tags(f"{KH_NEWER}/01. Dearly Beloved.m4a"), RECORDED["kh_rip"])

    def test_a_failed_attempt_before_the_applied_line_is_not_the_original(self):
        # The failed write was put back and the owner retagged the rip before
        # the retry, so the failed line's tags are older than the original
        # and were never written over.
        self.assertEqual(self.history.original_tags(f"{FF5_OLDER}/01. Main Theme of Final Fantasy V.flac"),
                         RECORDED["ff5_rip"])

    def test_a_track_no_job_wrote_has_none(self):
        self.assertIsNone(self.history.original_tags(f"{NEVER_APPLIED}/01. Track.flac"))


class OriginalSource(_Loaded):
    def test_an_album_both_jobs_moved_comes_from_the_older_jobs_source(self):
        self.assertEqual(self.history.original_source(FF4_NEWER), FF4_ORIGINAL)

    def test_an_album_one_job_moved_comes_from_that_jobs_source(self):
        self.assertEqual(self.history.original_source(KH_NEWER), KH_ORIGINAL)

    def test_the_source_of_a_failed_first_try_is_not_the_original(self):
        self.assertEqual(self.history.original_source(FF5_OLDER), FF5_ORIGINAL)

    def test_an_album_no_job_applied_has_none(self):
        self.assertIsNone(self.history.original_source(NEVER_APPLIED))


class Created(_Loaded):
    def test_images_an_earlier_job_created_are_listed_where_a_later_job_moved_them(self):
        # The older job's cover was deleted by the newer one and replaced, so
        # it has no current path: listing it at the old folder would name a
        # file that is not there. Each image once, at its current path.
        self.assertEqual(sorted(self.history.created(FF4_NEWER)),
                         [f"{FF4_NEWER}/back.jpg", f"{FF4_NEWER}/booklet-01.jpg", f"{FF4_NEWER}/cover.jpg"])

    def test_an_image_two_jobs_created_in_the_same_folder_is_listed_once_and_one_a_later_job_deleted_not_at_all(self):
        # Each of these is deleted. A path listed twice is a second
        # delete of a file already gone, and a deleted one was never there.
        self.assertEqual(sorted(self.history.created(TWICE_IN_PLACE)),
                         [f"{TWICE_IN_PLACE}/back.jpg", f"{TWICE_IN_PLACE}/cover.jpg"])

    def test_an_album_no_job_applied_has_no_created_images(self):
        self.assertEqual(self.history.created(NEVER_APPLIED), [])


class JobWritten(_Loaded):
    def test_an_album_whose_rip_had_no_release_id_is_job_written_even_when_both_jobs_wrote_the_same_one(self):
        # The case of the three Final Fantasy albums: the newer job re-applied
        # SCORE_BOOK, so its own record already carries it. Judged against
        # that record instead of the rip, the album looks untouched.
        current = {f"{FF4_NEWER}/{name}": SCORE_BOOK for name in FF4_TRACKS}
        self.assertTrue(self.history.job_written(FF4_NEWER, current))

    def test_an_album_whose_rip_named_another_release_is_job_written(self):
        self.assertTrue(self.history.job_written(KH_NEWER, {f"{KH_NEWER}/01. Dearly Beloved.m4a": REISSUE}))

    def test_an_album_whose_rip_already_named_the_release_on_its_files_is_not_job_written(self):
        # 10cc, How Dare You!: an MP3, so the release ID sits in a TXXX frame.
        self.assertFalse(self.history.job_written(TENCC_OLDER, {f"{TENCC_OLDER}/01. How Dare You.mp3": HOW_DARE_YOU}))

    def test_an_album_whose_files_do_not_all_carry_one_release_id_is_not_job_written(self):
        first, second = (f"{FF4_NEWER}/{name}" for name in FF4_TRACKS)
        kh = f"{KH_NEWER}/01. Dearly Beloved.m4a"
        # The last one's rip named a release and its file names none: "none"
        # differs from what the rip carried, but a file with none carries no
        # release ID, so the album is not job-written.
        for label, album, current in (("two releases", FF4_NEWER, {first: SCORE_BOOK, second: REISSUE}),
                                      ("one file with none", FF4_NEWER, {first: SCORE_BOOK, second: None}),
                                      ("every file with none", KH_NEWER, {kh: None})):
            with self.subTest(label):
                self.assertFalse(self.history.job_written(album, current))

    def test_an_album_whose_newest_line_is_moves_undone_is_not_job_written(self):
        # Its tracks still carry the job's release ID and its rip had none,
        # which would read as job-written without this rule.
        self.assertFalse(self.history.job_written(MOVES_UNDONE, {f"{MOVES_UNDONE}/01. One.flac": SCORE_BOOK}))

    def test_an_album_whose_newest_line_is_rolled_back_is_not_job_written(self):
        # Put back, then tagged by hand with a release its rip did not name.
        self.assertFalse(self.history.job_written(ROLLED_BACK, {f"{ROLLED_BACK}/01. One.flac": SCORE_BOOK}))

    def test_an_album_no_job_applied_is_not_job_written(self):
        self.assertFalse(self.history.job_written(NEVER_APPLIED, {f"{NEVER_APPLIED}/01. Track.flac": SCORE_BOOK}))


if __name__ == "__main__":
    unittest.main()
