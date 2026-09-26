"""What leaves the album folder, and the record that lets a write be undone.

Criteria 33 and 34, and `docs/music-library.md` *What an album folder may
contain*: rip lists and OS junk are deleted, videos and disc images go to the
extras root under the album's own `Letter/Artist/Album` path, and the write
returns a record from which the tags and paths can be put back.

The record is checked by using it. `replay_reverse` undoes a write from the
record alone, after a trip through JSON, and the test then looks for every
original file at its original path with its original tags.

`RemovalsAndExtras` hands the write a plan built by hand. `APlannedWrite`
plans a rip with the real `plan_album` first, because a hand-built plan can
list a file `plan_album` never does, and the old cover was one: it passed
here and stayed behind on every real write.
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from musiclib import files, tagwrite, write
from musiclib.units import units
from tests import builders
from tests.test_check import FRONT, _Planning, _release, _rip
from tests.test_plan import BACK, BACK_URL, FRONT_URL, Archive, plan_with

ALBUM = "N/Nine Inch Nails/(1999) The Fragile"
DESTINATION = "N/Nine Inch Nails/(1999) The Fragile (Deluxe)"
TITLES = ("Somewhat Damaged", "The Day the World Went Away", "The Frail")
KEPT = ("back.jpg", "booklet.pdf", "lyrics.lrc", "notes.txt", "rip.log")
DELETED = ("album.cue", ".DS_Store", "cover.jpg")
EXTRAS = ("The Fragile.iso", "Making of.mkv")


def moved_to(move: list, root: Path, extras_root: Path) -> Path:
    """Where a record's move `[from, to, root]` put the file.

    `from` is always under the library root. `to` is under the root the move
    names, so undoing it never has to look for the file in both.
    """
    return (extras_root if move[2] == "extras" else root) / move[1]


def replay_reverse(record: dict, root: Path, extras_root: Path) -> None:
    """Undo a write using nothing but its record.

    Prior tags go back first, while every file is still at the path the
    record keys it by. The moves are then undone last to first, so a move
    through a temporary name unwinds in order, each from the root the move
    names. Files the write created are removed. Deleted files cannot come
    back, and this is not something a write is expected to undo.
    """
    for final, prior in record["tags"].items():
        path = root / final
        tagwrite.write(files.read(path), prior)
    for move in reversed(record["moves"]):
        source = move[0]
        here = moved_to(move, root, extras_root)
        back = root / source
        back.parent.mkdir(parents=True, exist_ok=True)
        here.rename(back)
    for made in record["created"]:
        if (root / made).is_file():
            (root / made).unlink()


def paths(entries: list, root: Path) -> set[Path]:
    """Record entries as absolute paths, whether they were written relative to `root` or not."""
    return {root / entry for entry in entries}


class RemovalsAndExtras(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "library"
        self.extras = Path(tmp.name) / "extras"
        self.album = builders.library_album(self.root, discs=(TITLES,))
        (self.album / "album.cue").write_text('FILE "01. Somewhat Damaged.flac" WAVE\n')
        (self.album / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        (self.album / "The Fragile.iso").write_bytes(b"CD001 disc image")
        (self.album / "Making of.mkv").write_bytes(b"\x1aE\xdf\xa3 a video")
        self.cover = builders.jpeg(900, 900)
        self.plan = builders.album_plan(
            self.root, ALBUM, DESTINATION,
            builders.retitled_tracks(self.root, self.album, DESTINATION),
            images={"cover.jpg": self.cover},
            deletions=[f"{ALBUM}/{name}" for name in DELETED],
            extras=[f"{ALBUM}/{name}" for name in EXTRAS],
            kept=[f"{ALBUM}/{name}" for name in KEPT])
        self.before = builders.tree(self.root)
        self.tags = {rel: files.read(self.root / rel).tags
                     for rel in self.before if rel.endswith(".flac")}

    def test_rip_lists_and_os_junk_are_deleted_rather_than_carried_along(self):
        write.write_album(self.plan, self.extras)

        left = [p for top in (self.root, self.extras) for p in top.rglob("*")
                if p.name in ("album.cue", ".DS_Store")]
        self.assertEqual(left, [])

    def test_disc_images_and_videos_go_under_the_extras_root_at_the_albums_destination(self):
        write.write_album(self.plan, self.extras)

        for name in EXTRAS:
            with self.subTest(name):
                self.assertEqual((self.extras / DESTINATION / name).read_bytes(),
                                 self.before[f"{ALBUM}/{name}"])
                self.assertEqual([p for p in self.root.rglob(name)], [])

    def test_kept_files_and_new_images_land_in_the_destination_and_the_old_folder_goes(self):
        write.write_album(self.plan, self.extras)

        for name in KEPT:
            with self.subTest(name):
                self.assertEqual((self.root / DESTINATION / name).read_bytes(),
                                 self.before[f"{ALBUM}/{name}"])
        self.assertEqual((self.root / DESTINATION / "cover.jpg").read_bytes(), self.cover)
        self.assertFalse((self.root / ALBUM).exists(), "the emptied source folder was left behind")

    def test_the_record_names_what_was_deleted_and_what_was_created(self):
        record = json.loads(json.dumps(write.write_album(self.plan, self.extras)))

        self.assertLessEqual(paths([f"{ALBUM}/album.cue", f"{ALBUM}/.DS_Store"], self.root),
                             paths(record["deleted"], self.root))
        self.assertIn(self.root / DESTINATION / "cover.jpg", paths(record["created"], self.root))

    def test_the_record_after_a_trip_through_json_puts_every_tag_and_path_back(self):
        record = json.loads(json.dumps(write.write_album(self.plan, self.extras)))

        replay_reverse(record, self.root, self.extras)

        for rel, tags in self.tags.items():
            with self.subTest(rel):
                self.assertEqual(files.read(self.root / rel).tags, tags)
        for name in KEPT + EXTRAS:
            with self.subTest(name):
                self.assertEqual((self.root / ALBUM / name).read_bytes(), self.before[f"{ALBUM}/{name}"])
        left = [p.relative_to(self.root).as_posix() for p in (self.root / DESTINATION).rglob("*")
                if p.is_file()] if (self.root / DESTINATION).exists() else []
        self.assertEqual(left, [], "files the record does not account for")
        self.assertEqual([p for p in self.extras.rglob("*") if p.is_file()], [])

    def test_the_record_names_the_root_each_move_lands_under(self):
        # An extra's `to` is its path under the extras root, and a kept
        # file's the same shape under the library root. Undoing a move from
        # the wrong one finds nothing, or finds another album's file.
        record = json.loads(json.dumps(write.write_album(self.plan, self.extras)))

        named = {Path(move[0]).name: move[2] if len(move) == 3 else None for move in record["moves"]}
        self.assertEqual(named, {**{Path(t.source).name: "library" for t in self.plan.files},
                                 **{name: "library" for name in KEPT},
                                 **{name: "extras" for name in EXTRAS}})
        for move in record["moves"]:
            self.assertTrue(moved_to(move, self.root, self.extras).is_file(), move)

    def test_an_extra_reaches_an_extras_root_on_another_filesystem(self):
        # /srv/music/extras can sit on another disk from the library, and a
        # rename cannot cross one. The fake refuses every rename between the
        # two roots with the error the kernel gives, and lets every other
        # rename through.
        real_rename, real_replace = os.rename, os.replace
        library, extras = self.root.resolve(), self.extras.resolve()

        def across(src, dst) -> bool:
            src, dst = Path(src).resolve(), Path(dst).resolve()
            return src.is_relative_to(extras) != dst.is_relative_to(extras) and (
                src.is_relative_to(library) or dst.is_relative_to(library))

        def rename(src, dst, *args, **kwargs):
            if across(src, dst):
                raise OSError(errno.EXDEV, "Invalid cross-device link", str(src))
            return real_rename(src, dst, *args, **kwargs)

        def replace(src, dst, *args, **kwargs):
            if across(src, dst):
                raise OSError(errno.EXDEV, "Invalid cross-device link", str(src))
            return real_replace(src, dst, *args, **kwargs)

        with mock.patch("os.rename", rename), mock.patch("os.replace", replace):
            write.write_album(self.plan, self.extras)

        for name in EXTRAS:
            with self.subTest(name):
                self.assertEqual((self.extras / DESTINATION / name).read_bytes(),
                                 self.before[f"{ALBUM}/{name}"])
                self.assertEqual([p for p in self.root.rglob(name)], [])


class APlannedWrite(_Planning):
    """Real `plan_album`, then `write_album`: what is left once a rip is filed."""

    def write_rip(self, name: str, *, where: str = "C/The Cure/Disintegration [rip]",
                  images=(("Front", FRONT_URL, FRONT),), arrange=lambda album: None):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], where=where, cover=False)
        arrange(album)
        release = _release(["Plainsong", "Pictures of You"])
        (unit,) = units(root)
        plan = plan_with(self.tmp, unit, release, Archive(release, images=images), status="auto")
        self.assertEqual(list(plan.problems), [], f"{name} does not plan clean, so it cannot be written")
        record = json.loads(json.dumps(write.write_album(plan, self.tmp / f"extras {name}")))
        return root, album, plan, record

    @staticmethod
    def named(folder: Path, name: str) -> list[str]:
        """Every file in `folder` whose name is `name` in any case."""
        return sorted(p.name for p in folder.iterdir() if p.name.casefold() == name.casefold())

    def test_an_album_that_moves_leaves_no_file_and_no_folder_behind(self):
        # The old cover was in none of the plan's lists, so the write never
        # moved or deleted it and the rip's folder survived, holding only
        # `cover.jpg`. The next run then found an album with no tracks.
        own = builders.jpeg(500, 500)
        cases = {
            "the archive's front replaces cover.jpg": ("cover.jpg", True, FRONT),
            "the archive's front replaces Cover.jpg": ("Cover.jpg", True, FRONT),
            "the rip's own cover.jpg is kept": ("cover.jpg", False, own),
        }
        for case, (name, front, expected) in cases.items():
            with self.subTest(case):
                root, album, plan, record = self.write_rip(
                    case, images=(("Front", FRONT_URL, FRONT),) if front else (),
                    arrange=lambda album: (album / name).write_bytes(own))
                destination = root / plan.destination

                self.assertFalse(album.exists(), f"the old folder is still there: {builders.tree(album)}")
                left = [p for p in builders.tree(root) if not p.startswith(f"{plan.destination}/")
                        and builders.tree(root)[p] is not None]
                self.assertEqual(left, [], "files outside the album's new folder")
                self.assertEqual(self.named(destination, "cover.jpg"), ["cover.jpg"])
                self.assertEqual((destination / "cover.jpg").read_bytes(), expected)
                self.assertIn(album / name, {root / entry for entry in record["deleted"]})

    def test_an_image_the_archive_replaces_leaves_one_file_under_the_name_the_rules_give(self):
        # `Back.JPG` from the rip and the archive's `back.jpg` are one slot
        # on Wine's case-blind reading of the disk, so the write refused the
        # album as a collision. Written in place or moved, the archive's
        # image takes the slot and the rules' name.
        images = (("Front", FRONT_URL, FRONT), ("Back", BACK_URL, BACK))
        cases = {
            "the album moves": "C/The Cure/Disintegration [rip]",
            "the album stays where it is": "C/Cure, The/(2010) Disintegration",
        }
        for case, where in cases.items():
            with self.subTest(case):
                def arrange(album):
                    (album / "Back.JPG").write_bytes(builders.jpeg(400, 400))
                    (album / "Cover.jpg").write_bytes(builders.jpeg(500, 500))

                root, album, plan, record = self.write_rip(case, where=where, images=images,
                                                           arrange=arrange)
                destination = root / plan.destination

                self.assertEqual(plan.source == plan.destination, where == plan.destination)
                self.assertEqual(self.named(destination, "back.jpg"), ["back.jpg"])
                self.assertEqual((destination / "back.jpg").read_bytes(), BACK)
                self.assertEqual(self.named(destination, "cover.jpg"), ["cover.jpg"])
                self.assertEqual((destination / "cover.jpg").read_bytes(), FRONT)
                if plan.source != plan.destination:
                    self.assertFalse(album.exists(), f"the old folder is still there: {builders.tree(album)}")


if __name__ == "__main__":
    unittest.main()
