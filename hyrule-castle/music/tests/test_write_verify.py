"""An album is written whole or not at all.

Each file's tag write is verified by `tagwrite.write`, which
puts that one file back when it fails. These tests are about the album
around it: when any file fails, the files already written go back too, to
their prior tags and their prior paths. Embedded pictures are the stated
exception. On FLAC they live outside the tags; on MP3 and M4A they are tags
like any other, so `APictureThatChanged` checks every tag but the picture.

Failures are injected by patching `musiclib.tagwrite.write` and
`musiclib.images.embed` as the write path finds them, the same style as
`tests/test_write.py`, or made real: a file the write cannot save, a name
the disk refuses, a file changed on disk after it was planned.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen import MutagenError

from musiclib import files, images, tagwrite, write
from musiclib.units import units
from tests import builders
from tests.test_check import _release, _rip
from tests.test_plan import Archive, plan_with

ALBUM = "N/Nine Inch Nails/(1999) The Fragile"
DESTINATION = "N/Nine Inch Nails/(1999) The Fragile (Deluxe)"
TITLES = ("Somewhat Damaged", "The Day the World Went Away", "The Frail", "The Wretched")
KEPT = ("back.jpg", "booklet.pdf", "cover.jpg", "lyrics.lrc", "notes.txt", "rip.log")


def tags_on_disk(path: Path) -> dict:
    """Every tag as mutagen reads it, Vorbis keys folded (their case means nothing)."""
    raw = builders.read_tags(path)
    if path.suffix in (".flac", ".ogg"):
        return {k.lower(): v for k, v in raw.items()}
    return raw


def without_pictures(tags: dict) -> dict:
    """`tags` less the embedded pictures, under the name each format keeps them (FLAC keeps none)."""
    return {k: v for k, v in tags.items()
            if not k.startswith("APIC") and k not in ("covr", "metadata_block_picture")}


class _Album(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.extras = self.tmp / "extras"


def moved_plan(root: Path, album: Path, **fields):
    """Every track moved into the new folder and retitled, the other files carried along."""
    return builders.album_plan(root, ALBUM, DESTINATION, builders.retitled_tracks(root, album, DESTINATION),
                               kept=[f"{ALBUM}/{name}" for name in KEPT], **fields)


def state(root: Path) -> tuple[dict, dict]:
    """The library as it stands: tags by audio path, bytes by every other file's path."""
    audio, other = {}, {}
    for rel, data in builders.tree(root).items():
        if data is None:
            continue
        if Path(rel).suffix in (".flac", ".mp3"):
            audio[rel] = tags_on_disk(root / rel)
        else:
            other[rel] = data
    return audio, other


def failing(target: str, attribute: str, on_call: int, error: Exception):
    """Patch `target` so that its `on_call`-th call raises `error` and every other goes through.

    Returns the patch and the list of file names it was called with, in order.
    """
    module = {"tagwrite": tagwrite, "images": images}[target]
    real = getattr(module, attribute)
    names: list[str] = []

    def fake(track_or_path, *args, **kwargs):
        path = getattr(track_or_path, "path", track_or_path)
        names.append(Path(path).name)
        if len(names) == on_call:
            raise error
        return real(track_or_path, *args, **kwargs)

    return mock.patch.object(module, attribute, fake), names


class AFailedFile(_Album):
    def test_a_failure_on_track_3_puts_every_track_back_to_its_prior_tags_and_path(self):
        # Two ways a file fails. A tag write that does not verify has already
        # put its own file back, so only tracks 1 and 2 need undoing. A front
        # cover that will not embed fails after track 3's tags were written,
        # so a rollback that skipped the failing file would leave it retagged.
        for where, attribute, error in (
            ("tagwrite", "write", tagwrite.VerifyError("injected: did not verify")),
            ("images", "embed", OSError("injected: no space left on device")),
        ):
            with self.subTest(f"{where}.{attribute}"):
                root = self.tmp / where
                album = builders.library_album(root, discs=(TITLES,))
                plan = moved_plan(root, album)
                before = state(root)
                patch, names = failing(where, attribute, 3, error)

                with patch, self.assertRaises(write.AlbumFailed) as caught:
                    write.write_album(plan, self.extras)

                self.assertEqual(len(set(names[:3])), 3, "the failure did not come after two other files")
                failed = next((t for t in plan.files if Path(t.destination).name == names[2]), None)
                self.assertIsNotNone(failed, f"{names[2]} is not a destination the plan names")
                self.assertTrue(Path(failed.destination).name in str(caught.exception)
                                or Path(failed.source).name in str(caught.exception),
                                f"{caught.exception} does not name {failed.source}")
                self.assertEqual(state(root), before)

    def test_a_clean_write_leaves_every_track_at_its_destination_carrying_exactly_its_target(self):
        # MP3 as well as FLAC because the target carries the cover already in
        # the file: embedding the new front first would leave a picture the
        # target does not name, and the tag write would then fail on every MP3.
        front = builders.jpeg(300, 300)
        for ext in ("flac", "mp3"):
            with self.subTest(ext):
                root = self.tmp / ext
                album = builders.library_album(root, ext=ext, discs=(TITLES,))
                plan = builders.album_plan(root, ALBUM, DESTINATION,
                                           builders.retitled_tracks(root, album, DESTINATION),
                                           embedded=front)

                write.write_album(plan, self.extras)

                for track in plan.files:
                    self.assertFalse((root / track.source).exists(), track.source)
                    path = root / track.destination
                    self.assertEqual(without_pictures(files.read(path).tags),
                                     without_pictures(track.target))
                    self.assertEqual(images.embedded_pictures(path), [(3, front)])


AUDIO = (".flac", ".mp3", ".m4a", ".ogg")


def state_but_pictures(root: Path) -> tuple[dict, dict]:
    """`state`, for every audio format, with the embedded pictures left out of the tags."""
    audio, other = {}, {}
    for rel, data in builders.tree(root).items():
        if data is None:
            continue
        if Path(rel).suffix in AUDIO:
            audio[rel] = without_pictures(tags_on_disk(root / rel))
        else:
            other[rel] = data
    return audio, other


def staged(root: Path) -> list[str]:
    """Every file left under a name the write stages a move through."""
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if ".musiclib-write-" in p.name]


class APictureThatChanged(_Album):
    def test_a_rollback_on_mp3_and_m4a_puts_back_every_tag_but_the_picture_and_every_path(self):
        # The new cover differs from the one each file already carries. On
        # MP3 and M4A the old picture is itself a tag, held in the prior
        # values as a digest nothing can rebuild a picture from, so a
        # rollback that writes every prior value back crashes halfway and
        # leaves the album moved. The picture is kept out of the rollback.
        for ext in ("mp3", "m4a"):
            with self.subTest(ext):
                root = self.tmp / ext
                album = builders.library_album(root, ext=ext, discs=(TITLES,))
                plan = builders.album_plan(root, ALBUM, DESTINATION,
                                           builders.retitled_tracks(root, album, DESTINATION),
                                           embedded=builders.jpeg(300, 300))
                before = state_but_pictures(root)
                patch, names = failing("tagwrite", "write", 3, tagwrite.VerifyError("injected: did not verify"))

                with patch, self.assertRaises(write.AlbumFailed):
                    write.write_album(plan, self.extras)

                self.assertEqual(len(set(names[:3])), 3, "the failure did not come after two other files")
                self.assertEqual(state_but_pictures(root), before)
                self.assertEqual(staged(root), [])


class AFailureOfAnyKind(_Album):
    def test_rolls_the_album_back_and_raises_album_failed_naming_the_file(self):
        # Any failure here rolls the album back, not just a tag write that
        # fails to verify: anything else raising straight out of the write
        # would leave the album half moved and half retagged. The first
        # three are the errors a real file raises; the last two are real
        # files the write cannot finish on.
        def injected(error):
            def make(root, plan):
                return failing("tagwrite", "write", 3, error)[0]
            return make

        def rating_in_the_plan(root, plan):
            # A plan may not change a rating, and `tagwrite` raises
            # ValueError on one that does, after two files are done.
            plan.files[2].target["rating"] = ["5"]
            return contextlib.nullcontext()

        def read_only(root, plan):
            (root / plan.files[2].source).chmod(0o444)
            return contextlib.nullcontext()

        cases = {
            "MutagenError": injected(MutagenError("injected: could not save")),
            "Unreadable": injected(files.Unreadable("injected: not a recognised audio file")),
            "OSError": injected(OSError(28, "injected: no space left on device")),
            "a rating the plan changes": rating_in_the_plan,
            "a file the write cannot save": read_only,
        }
        if os.geteuid() == 0:
            del cases["a file the write cannot save"]
        for case, arrange in cases.items():
            with self.subTest(case):
                root = self.tmp / case
                album = builders.library_album(root, discs=(TITLES,))
                plan = moved_plan(root, album)
                before = state(root)
                failed = plan.files[2]

                with arrange(root, plan), self.assertRaises(write.AlbumFailed) as caught:
                    write.write_album(plan, self.extras)

                self.assertTrue(Path(failed.destination).name in str(caught.exception)
                                or Path(failed.source).name in str(caught.exception),
                                f"{caught.exception} does not name {failed.source}")
                self.assertIsNotNone(caught.exception.__cause__, "the error it failed on is not chained")
                self.assertEqual(state(root), before)
                self.assertEqual(staged(root), [])


class AFailedMove(_Album):
    def test_a_name_the_disk_refuses_puts_every_file_back_under_its_own_name(self):
        # Track 3's new name is over 255 bytes, so its move fails after
        # tracks 1 and 2 have already landed. Moves go through a temporary
        # name first, and a failure outside the rollback left every file
        # there: nothing at its old name, nothing at its new one.
        root = self.tmp / "library"
        album = builders.library_album(root, discs=(TITLES,))
        plan = moved_plan(root, album)
        plan.files[2].destination = f"{DESTINATION}/03. {'x' * 260}.flac"
        before = state(root)

        with self.assertRaises(write.AlbumFailed):
            write.write_album(plan, self.extras)

        self.assertEqual(staged(root), [])
        self.assertEqual(state(root), before)


class AStalePlan(_Album):
    def plan_rip(self, root: Path):
        album = _rip(root, ["Plainsong", "Pictures of You"])
        release = _release(["Plainsong", "Pictures of You"])
        (unit,) = units(root)
        plan = plan_with(self.tmp, unit, release, Archive(release), status="auto")
        self.assertEqual(list(plan.problems), [], "the rip does not plan clean, so it cannot be written")
        return album, plan

    def test_a_file_changed_on_disk_since_it_was_planned_is_refused_before_anything_moves(self):
        # A plan names every tag the file ends with, so writing it over a
        # file somebody retagged since silently undoes their edit. The
        # rating is protected too: a plan written over a rating added since
        # would fail on that file, after the others had moved.
        def flip_an_audio_byte(path: Path):
            data = bytearray(path.read_bytes())
            data[-100] ^= 0xFF
            path.write_bytes(bytes(data))

        changes = {
            "a title edited": lambda path: builders.write_tags(path, {"TITLE": "pictures of you (edit)"}),
            "a rating added": lambda path: builders.write_tags(path, {"RATING": "5"}),
            "the audio changed": flip_an_audio_byte,
        }
        for case, change in changes.items():
            with self.subTest(case):
                root = self.tmp / case
                album, plan = self.plan_rip(root)
                changed = album / "02 pictures of you.flac"
                change(changed)
                before = builders.tree(root)

                stale = getattr(write, "StalePlan", None)
                self.assertIsNotNone(stale, "musiclib.write has no StalePlan to refuse a stale plan with")
                with self.assertRaises(stale) as caught:
                    write.write_album(plan, self.extras)

                self.assertIn(changed.name, str(caught.exception))
                self.assertEqual(builders.tree(root), before)
                self.assertFalse(self.extras.exists(), "the refused write created the extras root")


class StagedMoves(_Album):
    def test_two_tracks_swapping_names_both_arrive_with_their_own_tags(self):
        # Moving track 1 straight onto track 2's name would replace track 2
        # before it had moved. Neither destination is a file that stays, so
        # the collision check rightly lets this through, and only the moves
        # going through temporary names keeps both files.
        root = self.tmp / "library"
        album = builders.library_album(root, discs=(TITLES,))
        first = f"{ALBUM}/01. Somewhat Damaged.flac"
        second = f"{ALBUM}/02. The Day the World Went Away.flac"
        plan = builders.album_plan(root, ALBUM, ALBUM, [
            builders.file_plan(root, first, second, "Somewhat Damaged (swapped)"),
            builders.file_plan(root, second, first, "The Day the World Went Away (swapped)"),
        ])

        write.write_album(plan, self.extras)

        self.assertEqual(sorted(p.name for p in album.glob("*.flac")),
                         [f"{n:02d}. {t}.flac" for n, t in enumerate(TITLES, start=1)])
        self.assertEqual(files.read(root / second).tags["title"], ["Somewhat Damaged (swapped)"])
        self.assertEqual(files.read(root / first).tags["title"],
                         ["The Day the World Went Away (swapped)"])


if __name__ == "__main__":
    unittest.main()
