"""One walk of the library, shared by `units` and `check`, that leaves NAS and OS litter alone.

A Synology puts an `@eaDir` in every folder it indexes, a Linux disk keeps
`lost+found` at its root, a desktop leaves `.Trash-1000`, and an NFS client
leaves a `.nfs0001` behind for a file somebody deleted while it was open.
None of it is music. Walked as music, `@eaDir` at the album level becomes an
album called `@eaDir`, and one inside an album becomes a subfolder `check`
reports and a thumbnail `units` carries as one of the album's files.

A name that merely starts with `.` is not litter: `.38 Special` is a band.

`musiclib.walk` is imported inside each case that needs it, so the cases that
go through `units` and `check` fail on what they find, not on an import.
"""

from __future__ import annotations

import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from musiclib import check, units
from tests import builders

#: Every folder name criterion 26 skips. `.Trash-1000` stands for `.Trash-*`.
IGNORED_FOLDERS = ("@eaDir", "#recycle", "#snapshot", "lost+found", "System Volume Information",
                   "$RECYCLE.BIN", ".AppleDouble", ".Trash-1000")

#: What a Synology writes inside `@eaDir`.
THUMB = "SYNOPHOTO_THUMB_M.jpg"


def walk():
    return importlib.import_module("musiclib.walk")


def touch(path: Path, data: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def files_in(album: Path) -> list[Path]:
    """The files `units` and `check` both take from one album folder."""
    return walk().album_contents(album)[0]


def rels(paths: list[Path], base: Path) -> list[str]:
    return [p.relative_to(base).as_posix() for p in paths]


class _Tree(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self._roots = 0

    def root(self) -> Path:
        self._roots += 1
        path = self.tmp / f"library-{self._roots}"
        path.mkdir()
        return path


class IsIgnored(_Tree):
    def test_each_listed_folder_name_and_any_nfs_file_is_ignored(self) -> None:
        for name in IGNORED_FOLDERS + (".Trash-0", ".nfs0001", ".nfs000000000123abcd00000004"):
            with self.subTest(name):
                self.assertTrue(walk().is_ignored(name))

    def test_a_name_that_only_starts_with_a_dot_or_looks_like_a_listed_one_is_walked(self) -> None:
        # `._x` and `.DS_Store` are removed by `check`'s own rules, which
        # only happens if the walk hands them over. The rest are near misses
        # a prefix or substring match would swallow.
        for name in (".38 Special", "...And You Will Know Us by the Trail of Dead", "._01. Hurt.flac",
                     ".DS_Store", "#", "recycle", "eaDir", "Trash-1000", "nfs0001", "01. .nfs.flac"):
            with self.subTest(name):
                self.assertFalse(walk().is_ignored(name))


class AlbumDirs(_Tree):
    def test_every_letter_artist_album_folder_in_path_order_and_nothing_else(self) -> None:
        root = self.root()
        # Made out of order, so only sorting by path gives the expected list.
        for rel in ("N/Nine Inch Nails/(1999) The Fragile", "#/.38 Special/(1981) Wild-Eyed Southern Boys",
                    "M/Moby/(2005) Hotel", "N/Nine Inch Nails/(1994) The Downward Spiral"):
            (root / rel).mkdir(parents=True)
        # A stray file at each level is not a folder to go into.
        for rel in (".DS_Store", "N/.DS_Store", "N/Nine Inch Nails/folder.jpg"):
            touch(root / rel)
        # Deeper folders belong to the album above them.
        (root / "N/Nine Inch Nails/(1999) The Fragile/CD1").mkdir()

        self.assertEqual(rels(walk().album_dirs(root), root), [
            "#/.38 Special/(1981) Wild-Eyed Southern Boys",
            "M/Moby/(2005) Hotel",
            "N/Nine Inch Nails/(1994) The Downward Spiral",
            "N/Nine Inch Nails/(1999) The Fragile",
        ])

    def test_an_ignored_folder_at_the_letter_artist_or_album_level_is_never_an_album(self) -> None:
        # Each level on its own, so a walk that checks only one of them
        # fails for the others by name.
        for name in IGNORED_FOLDERS:
            for level, rel in (("letter", f"{name}/N/(1999) The Fragile"),
                               ("artist", f"N/{name}/(1999) The Fragile"),
                               ("album", f"N/Nine Inch Nails/{name}")):
                with self.subTest(name=name, level=level):
                    root = self.root()
                    (root / "N/Nine Inch Nails/(1999) The Fragile").mkdir(parents=True)
                    touch(root / rel / THUMB)
                    self.assertEqual(rels(walk().album_dirs(root), root),
                                     ["N/Nine Inch Nails/(1999) The Fragile"])


class AlbumContents(_Tree):
    def test_every_file_at_any_depth_in_path_order_skipping_ignored_folders_and_nfs_files(self) -> None:
        album = self.root() / "N/Nine Inch Nails/(1999) The Fragile"
        for rel in ("CD2/01. The Wretched.flac", "cover.jpg", "CD1/01. Somewhat Damaged.flac",
                    "._cover.jpg", "Scans/extra/back.jpg", ".DS_Store"):
            touch(album / rel)
        # Litter in the album, in a disc folder and two levels down.
        for rel in (f"@eaDir/cover.jpg/{THUMB}", f"CD1/@eaDir/01. Somewhat Damaged.flac/{THUMB}",
                    f"Scans/#recycle/{THUMB}", f"Scans/extra/.AppleDouble/back.jpg",
                    ".nfs0001", "CD2/.nfs000000000123abcd00000004"):
            touch(album / rel)

        self.assertEqual(rels(files_in(album), album), [
            ".DS_Store",
            "._cover.jpg",
            "CD1/01. Somewhat Damaged.flac",
            "CD2/01. The Wretched.flac",
            "Scans/extra/back.jpg",
            "cover.jpg",
        ])


#: The ignored names in cases other than the ones `IGNORED_FOLDERS` spells
#: them in. A Synology writes `@eaDir` and Windows `$RECYCLE.BIN`, but a copy
#: through another client or file system can change the case.
IGNORED_IN_OTHER_CASES = ("@EADIR", "$Recycle.Bin", "#RECYCLE", "Lost+Found", ".trash-1000")


class TheIgnoreListIgnoresCase(_Tree):
    def test_album_dirs_skips_a_listed_name_in_another_case_at_every_level(self) -> None:
        for name in IGNORED_IN_OTHER_CASES:
            for level, rel in (("letter", f"{name}/N/(1999) The Fragile"),
                               ("artist", f"N/{name}/(1999) The Fragile"),
                               ("album", f"N/Nine Inch Nails/{name}")):
                with self.subTest(name=name, level=level):
                    root = self.root()
                    (root / "N/Nine Inch Nails/(1999) The Fragile").mkdir(parents=True)
                    touch(root / rel / THUMB)
                    self.assertEqual(rels(walk().album_dirs(root), root),
                                     ["N/Nine Inch Nails/(1999) The Fragile"])

    def test_album_contents_skips_a_listed_name_in_another_case_at_any_depth(self) -> None:
        for name in IGNORED_IN_OTHER_CASES:
            with self.subTest(name):
                album = self.root() / "N/Nine Inch Nails/(1999) The Fragile"
                touch(album / "01. Somewhat Damaged.flac")
                touch(album / name / THUMB)
                touch(album / "CD1" / name / THUMB)
                self.assertEqual(rels(files_in(album), album), ["01. Somewhat Damaged.flac"])


@unittest.skipUnless(hasattr(os, "symlink"), "no os.symlink on this platform")
class SymlinksAreNotFollowed(_Tree):
    """A symlinked folder is never walked into.

    A link inside the library points at music already in it or at something
    outside it, and neither is an album of this library to plan and rename.
    A link back up the tree would walk forever.
    """

    def link(self, link: Path, target: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"cannot make a symlink here: {exc}")

    def test_album_dirs_finds_no_album_through_a_symlinked_letter_artist_or_album_folder(self) -> None:
        elsewhere = self.tmp / "elsewhere"
        (elsewhere / "Moby/(2005) Hotel").mkdir(parents=True)
        for level, rel, target in (("letter", "M", elsewhere),
                                   ("artist", "M/Moby", elsewhere / "Moby"),
                                   ("album", "M/Moby/(2005) Hotel", elsewhere / "Moby/(2005) Hotel")):
            with self.subTest(level):
                root = self.root()
                (root / "N/Nine Inch Nails/(1999) The Fragile").mkdir(parents=True)
                self.link(root / rel, target)
                self.assertEqual(rels(walk().album_dirs(root), root),
                                 ["N/Nine Inch Nails/(1999) The Fragile"])

    def test_album_contents_takes_nothing_through_a_symlinked_folder_and_ends_on_a_link_to_itself(self) -> None:
        album = self.root() / "N/Nine Inch Nails/(1999) The Fragile"
        touch(album / "CD1/01. Somewhat Damaged.flac")
        touch(self.tmp / "scans/back.jpg")
        self.link(album / "Scans", self.tmp / "scans")
        # A walk that follows this one never returns.
        self.link(album / "CD1/again", album)
        self.assertEqual(rels(files_in(album), album), ["CD1/01. Somewhat Damaged.flac"])


@unittest.skipUnless(hasattr(os, "symlink"), "no os.symlink on this platform")
class ASymlinkedFileIsReadLikeAnyOther(_Tree):
    """Only a symlinked folder is left alone; a symlinked file in an album is one of its files.

    A disc ripped once and linked into a second edition's folder is still
    that album's music. A walk that skips every link, or one that resolves a
    link to its target's path, loses the track or plans it somewhere else.
    """

    def test_units_reads_an_album_whose_tracks_and_cover_are_links_as_it_reads_the_same_album_with_real_files(self) -> None:
        discs = (("Mr. Self Destruct",), ("Piggy",))
        clean, linked = self.root(), self.root()
        for root in (clean, linked):
            builders.library_album(root, album="The Downward Spiral", date="1994-03-08", discs=discs)
        album = linked / "N/Nine Inch Nails/(1994) The Downward Spiral"
        # Links at the album's top and inside a disc folder, each to a file
        # outside the library.
        outside = self.tmp / "outside"
        outside.mkdir()
        for rel in ("CD2/01. Piggy.flac", "cover.jpg"):
            target = outside / Path(rel).name
            shutil.move(album / rel, target)
            try:
                os.symlink(target, album / rel)
            except OSError as exc:
                self.skipTest(f"cannot make a symlink here: {exc}")
        self.assertTrue((album / "CD2/01. Piggy.flac").is_symlink())

        def read(root: Path) -> list[tuple]:
            """Each track's path in its album, as units gives it, with the tags and length read from it."""
            return sorted((Path(t.path).relative_to(u.path).as_posix(), t.tags, t.length)
                          for u in units.units(root) for t in u.tracks)

        self.assertEqual(UnitsAndCheckShareTheWalk.seen(linked), UnitsAndCheckShareTheWalk.seen(clean))
        self.assertEqual(read(linked), read(clean))


class UnreadableFolders(_Tree):
    """A folder the walk may not list is skipped, and the walk goes on past it.

    On the NAS a folder can come out of a copy owned by another user or
    with its mode stripped. The old `rglob` passed over one without a word;
    `iterdir` raises `PermissionError`, which ends the whole library's walk
    at the first such folder.
    """

    def lock(self, folder: Path) -> None:
        """Make `folder` unlistable until the case ends, or skip the case where that cannot be done."""
        folder.chmod(0)
        # Registered after the temporary directory, so it runs first and
        # the directory can be removed.
        self.addCleanup(folder.chmod, 0o755)
        try:
            list(folder.iterdir())
        except PermissionError:
            return
        self.skipTest("chmod 000 does not stop this user listing a folder (root?)")

    def test_an_unreadable_letter_or_artist_folder_is_skipped_and_every_other_album_is_found(self) -> None:
        # The locked folder sorts first, so a walk that stops at it finds nothing after.
        for level, locked in (("letter", "A"), ("artist", "N/A Perfect Circle")):
            with self.subTest(level):
                root = self.root()
                for rel in ("A/A Perfect Circle/(2000) Mer de Noms", "N/A Perfect Circle/(2003) Thirteenth Step",
                            "N/Nine Inch Nails/(1999) The Fragile", "M/Moby/(2005) Hotel"):
                    (root / rel).mkdir(parents=True)
                self.lock(root / locked)
                found = rels(walk().album_dirs(root), root)
                self.assertIn("N/Nine Inch Nails/(1999) The Fragile", found)
                self.assertIn("M/Moby/(2005) Hotel", found)
                self.assertFalse([rel for rel in found if rel.startswith(locked + "/")], found)

    def test_an_unreadable_album_folder_has_no_files_and_raises_nothing(self) -> None:
        album = self.root() / "N/Nine Inch Nails/(1999) The Fragile"
        touch(album / "01. Somewhat Damaged.flac")
        self.lock(album)
        self.assertEqual(files_in(album), [])

    def test_an_unreadable_folder_inside_an_album_is_skipped_and_the_files_beside_it_are_found(self) -> None:
        # `CD1` is locked and sorts before `CD2` and `cover.jpg`.
        album = self.root() / "N/Nine Inch Nails/(1999) The Fragile"
        for rel in ("CD1/01. Somewhat Damaged.flac", "CD2/01. The Wretched.flac", "cover.jpg"):
            touch(album / rel)
        self.lock(album / "CD1")
        self.assertEqual(rels(files_in(album), album), ["CD2/01. The Wretched.flac", "cover.jpg"])


class AMissingRoot(_Tree):
    """Folders below the root are skipped when they cannot be listed; the root itself never is.

    A misspelt or unmounted library read as an empty one plans nothing, and
    `batch identify` then writes that nothing over the job it was asked to
    refresh.
    """

    def test_album_dirs_raises_for_a_root_that_does_not_exist(self) -> None:
        with self.assertRaises(FileNotFoundError):
            walk().album_dirs(self.tmp / "libary")

    def test_batch_identify_over_a_misspelt_root_fails_and_leaves_the_jobs_plan_alone(self) -> None:
        from tests.test_batch_apply import new_library
        from tests.test_batch_identify import Services, run_identify

        lib = new_library(self)
        lib.add("A/Alpha/One [rip]", 1)
        lib.identify()
        before = (lib.job / "plan.json").read_bytes()
        self.assertTrue(lib.entries())
        try:
            code, _out, _err = run_identify(lib.root.parent / "libary", lib.job, lib.memory, Services(lib.catalogue))
        except OSError:
            code = None  # raised out of the command: a traceback and exit 1
        self.assertNotEqual(code, 0)
        self.assertEqual((lib.job / "plan.json").read_bytes(), before)


def _litter(root: Path) -> None:
    """Everything criterion 26 skips, where it turns up on the NAS."""
    # `@eaDir` at the letter, artist and album level, each deep enough to be
    # taken for an album, and inside an album and its disc folder.
    touch(root / "@eaDir/N/(1999) The Fragile" / THUMB, builders.jpeg(8, 8))
    touch(root / "N/@eaDir/(1999) The Fragile" / THUMB, builders.jpeg(8, 8))
    touch(root / "N/Nine Inch Nails/@eaDir" / THUMB, builders.jpeg(8, 8))
    touch(root / "N/Nine Inch Nails/(1999) The Fragile/@eaDir/cover.jpg" / THUMB, builders.jpeg(8, 8))
    touch(root / "N/Nine Inch Nails/(1994) The Downward Spiral/CD1/@eaDir/01. Mr. Self Destruct.flac"
          / THUMB, builders.jpeg(8, 8))
    touch(root / "lost+found/#1234/#5678/#9012/#3456", b"\0" * 16)
    # A deleted album in the recycle bin and the desktop trash is still a
    # whole album, which is why it has to be skipped rather than judged.
    shutil.copytree(root / "N/Nine Inch Nails/(1999) The Fragile",
                    root / "#recycle/N/Nine Inch Nails/(1999) The Fragile")
    shutil.copytree(root / "N/Nine Inch Nails/(1999) The Fragile",
                    root / ".Trash-1000/files/Nine Inch Nails/(1999) The Fragile")
    touch(root / "N/Nine Inch Nails/(1999) The Fragile/.nfs0001", b"ID3")


class UnitsAndCheckShareTheWalk(_Tree):
    def twin_libraries(self) -> tuple[Path, Path]:
        """Two identical, clean libraries; the second one then gets the litter."""
        pair = []
        for _ in range(2):
            root = self.root()
            builders.library_album(root)
            builders.library_album(root, album="The Downward Spiral", date="1994-03-08",
                                   discs=(("Mr. Self Destruct",), ("Piggy",)))
            builders.library_album(root, letter="M", artist="Moby", album="Hotel", date="2005")
            pair.append(root)
        _litter(pair[1])
        return pair[0], pair[1]

    @staticmethod
    def seen(root: Path) -> list[tuple]:
        return [(u.rel, sorted(Path(t.path).relative_to(u.path).as_posix() for t in u.tracks),
                 sorted(u.others), u.unreadable, u.status)
                for u in units.units(root)]

    def test_units_finds_the_same_albums_and_files_with_the_litter_as_without_it(self) -> None:
        clean, littered = self.twin_libraries()
        self.assertEqual([u.rel for u in units.units(littered)], [
            "M/Moby/(2005) Hotel",
            "N/Nine Inch Nails/(1994) The Downward Spiral",
            "N/Nine Inch Nails/(1999) The Fragile",
        ])
        self.assertEqual(self.seen(littered), self.seen(clean))

    def test_check_reports_nothing_about_the_litter(self) -> None:
        clean, littered = self.twin_libraries()
        # The clean twin is clean, so any violation here is litter walked as music.
        self.assertEqual(check.check(clean), [])
        self.assertEqual(check.check(littered), [])

    def test_a_band_whose_name_starts_with_a_dot_is_walked_by_units_and_check(self) -> None:
        # Criterion 21 renames `.38 Special` to `_38 Special`, which it can
        # only do if the walk ever reaches it.
        root = self.root()
        album = builders.library_album(root, letter="#", artist=".38 Special",
                                       album="Wild-Eyed Southern Boys", date="1981")
        self.assertEqual([u.rel for u in units.units(root)],
                         ["#/.38 Special/(1981) Wild-Eyed Southern Boys"])
        # A rule check is sure to judge, whatever criterion 21 makes of the
        # name: with no cover.jpg, a walked album breaks `cover.jpg`.
        (album / "cover.jpg").unlink()
        self.assertIn(("#/.38 Special/(1981) Wild-Eyed Southern Boys", "cover.jpg"),
                      {(Path(v.album).as_posix(), v.rule) for v in check.check(root)})


class CheckKeys(unittest.TestCase):
    def test_check_keeps_no_tag_key_table_of_its_own(self) -> None:
        # Its keys come from `mapping.PICARD` and from where `units` keeps
        # the number keys, so a key fixed there is fixed for check too.
        self.assertFalse(hasattr(check, "_KEYS"))


if __name__ == "__main__":
    unittest.main()
