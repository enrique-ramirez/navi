"""Finding the albums of a drop and staging each one for its own musiclib job.

A drop arrives as `raw/<item>/...`: each item is a dropped folder, or the
folder an archive was extracted into, named after the item. A folder is an
album when it holds an audio file of its own or a `CD`/`Disc`/`Disk`
subfolder holding audio; any other folder is searched in turn. Each album is
moved to `<n>/drop/album/<name>/`, numbered from `01` in the order the items
were dropped and then in path order, and `raw/` goes away.

Finding is by extension and folder shape, so every file here is a few bytes
of text. Each file holds its own path, so a file staged under the wrong name
or copied from the wrong place does not compare equal.

`agitha.albums` is imported inside each case, so every case fails on what it
finds rather than all of them on one import.
"""

from __future__ import annotations

import importlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from musiclib import files

NO_AUDIO = "no audio files"
OUTSIDE = "outside every album"

#: Disc folder names the engine reads as media, from `tests/test_units.py`
#: (`CD1`, `CD2 - Live at Budokan`, `CD3`, `Disc 1`) and `tests/test_identify.py`
#: (`disk 3`, `CD 1`, `Disc 2`, `CD 2`, `CD1 - Live`).
DISC_FOLDERS = ("CD1", "CD2", "CD3", "CD2 - Live at Budokan", "Disc 1", "disk 3", "CD 1", "Disc 2", "CD 2",
                "CD1 - Live")

#: Names the engine does not read as a disc folder, from `tests/test_identify.py`.
#: `Bonus CD 2` holds the words of a disc folder without starting with them.
NOT_DISC_FOLDERS = ("Bonus", "Scans", "Bonus CD 2")


def albums():
    return importlib.import_module("agitha.albums")


class Drop:
    """One drop's folder, built item by item in the order the items were dropped."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir()
        self._items: list[tuple[str, str]] = []

    def item(self, name: str, *rels: str, kind: str = "folder") -> Path:
        """Drop an item holding a file at each of `rels`, each file's bytes being its own path."""
        self._items.append((name, kind))
        root = self.raw / name
        root.mkdir(parents=True)
        for rel in rels:
            self.put(name, rel)
        return root

    def put(self, item: str, rel: str, data: bytes | None = None) -> Path:
        path = self.raw / item / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{item}/{rel}".encode() if data is None else data)
        return path

    @property
    def raw(self) -> Path:
        return self.path / "raw"

    def contents(self, folder: Path) -> dict[str, bytes]:
        """Every file under `folder`, by its `/`-separated path inside it."""
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def stage(self):
        """Write `drop.json` as the upload leaves it, then stage the drop."""
        record = {"started": "2026-09-29T12:00:00", "done": True, "items": [
            {"name": name, "kind": kind,
             "files": [{"path": rel, "size": len(data)} for rel, data in sorted(self.contents(self.raw / name).items())]}
            for name, kind in self._items
        ]}
        (self.path / "drop.json").write_text(json.dumps(record), encoding="utf-8")
        return albums().stage(self.path)

    def staged(self, n: str, name: str) -> dict[str, bytes]:
        return self.contents(self.path / n / "drop" / "album" / name)


def found(staging) -> list[tuple[str, str, str]]:
    return [(a.n, a.name, a.item) for a in staging.albums]


def ignored(staging) -> list[tuple[str, str, str]]:
    # No order is promised for what is ignored.
    return sorted((i.item, i.path, i.reason) for i in staging.ignored)


class _Staging(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self._drops = 0

    def drop(self) -> Drop:
        self._drops += 1
        return Drop(self.tmp / f"drop-{self._drops}")

    def assertStagedExactly(self, drop: Drop, expected: dict[tuple[str, str], dict[str, bytes]]) -> None:
        """Only the numbered folders expected, each holding exactly `drop/album/<name>` and those files, and no `raw/`."""
        self.assertFalse(drop.raw.exists(), "raw/ is still there")
        self.assertEqual(sorted(p.name for p in drop.path.iterdir() if p.is_dir()), sorted(n for n, _ in expected))
        for (n, name), contents in expected.items():
            with self.subTest(album=f"{n}/{name}"):
                self.assertEqual([p.name for p in (drop.path / n).iterdir()], ["drop"])
                self.assertEqual([p.name for p in (drop.path / n / "drop").iterdir()], ["album"])
                self.assertEqual([p.name for p in (drop.path / n / "drop" / "album").iterdir()], [name])
                self.assertEqual(drop.staged(n, name), contents)


def as_placed(item: str, prefix: str, *rels: str) -> dict[str, bytes]:
    """What `Drop.put` wrote at `<item>/<prefix><rel>`, keyed by `rel`: the album's files as they should arrive."""
    return {rel: f"{item}/{prefix}{rel}".encode() for rel in rels}


class FindingAlbums(_Staging):
    """Which folders are albums, and where each one goes."""

    def test_an_artist_folder_gives_the_album_inside_it(self) -> None:
        drop = self.drop()
        tracks = ("01. Stones Grow Her Name.mp3", "02. Cloud Factory.mp3")
        drop.item("Sonata Arctica", *(f"2014 - Pariah's Child/{t}" for t in tracks))
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "2014 - Pariah's Child", "Sonata Arctica")])
        self.assertEqual(ignored(staging), [])
        self.assertStagedExactly(drop, {
            ("01", "2014 - Pariah's Child"): as_placed("Sonata Arctica", "2014 - Pariah's Child/", *tracks),
        })

    def test_an_extracted_archive_wrapping_one_album_folder_gives_that_album(self) -> None:
        drop = self.drop()
        item = "La La Love You - Blockbuster.zip"
        tracks = ("01 - Mi novia se droga.mp3", "02 - El fin del mundo.mp3")
        drop.item(item, *(f"Blockbuster/{t}" for t in tracks), kind="archive")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "Blockbuster", item)])
        self.assertEqual(ignored(staging), [])
        self.assertStagedExactly(drop, {("01", "Blockbuster"): as_placed(item, "Blockbuster/", *tracks)})

    def test_an_item_holding_audio_directly_is_one_album_named_after_the_item_with_everything_in_it(self) -> None:
        # The cover, the log and the scans folder sit in the album, so they
        # travel with it rather than being ignored.
        drop = self.drop()
        rels = ("01. Hurt.mp3", "02. Piggy.mp3", "folder.jpg", "rip.log", "Scans/booklet 01.jpg")
        drop.item("The Downward Spiral", *rels)
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "The Downward Spiral", "The Downward Spiral")])
        self.assertEqual(ignored(staging), [])
        self.assertStagedExactly(drop, {("01", "The Downward Spiral"): as_placed("The Downward Spiral", "", *rels)})

    def test_sixty_seven_flac_files_in_one_folder_are_one_album_of_sixty_seven_files(self) -> None:
        drop = self.drop()
        item = "chrono_cross-original_soundtrack-1999"
        rels = tuple(f"{i:02d}-yasunori_mitsuda-track_{i:02d}.flac" for i in range(1, 68))
        drop.item(item, *rels)
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", item, item)])
        self.assertEqual(len(drop.staged("01", item)), 67)
        self.assertStagedExactly(drop, {("01", item): as_placed(item, "", *rels)})

    def test_disc_folders_holding_audio_make_their_parent_one_album_and_stay_inside_it(self) -> None:
        drop = self.drop()
        rels = ("CD1/01. Somewhat Damaged.flac", "CD1/02. The Day the World Went Away.flac",
                "CD2/01. The Wretched.flac", "Scans/back.jpg")
        drop.item("Nine Inch Nails", *(f"The Fragile/{r}" for r in rels))
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "The Fragile", "Nine Inch Nails")])
        self.assertEqual(ignored(staging), [])
        self.assertStagedExactly(drop, {("01", "The Fragile"): as_placed("Nine Inch Nails", "The Fragile/", *rels)})

    def test_a_folder_beside_disc_folders_holding_audio_of_its_own_is_its_own_album(self) -> None:
        drop = self.drop()
        discs = ("CD1/01. Plainsong.flac", "CD2/01. Prayers for Rain.flac")
        drop.item("The Cure", *(f"Disintegration/{r}" for r in discs), "Disintegration/Bonus/01. Fascination Street.mp3")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "Disintegration", "The Cure"), ("02", "Bonus", "The Cure")])
        self.assertEqual(ignored(staging), [])
        # Bonus goes to its own number, so it must not also ride along inside Disintegration.
        self.assertStagedExactly(drop, {
            ("01", "Disintegration"): as_placed("The Cure", "Disintegration/", *discs),
            ("02", "Bonus"): as_placed("The Cure", "Disintegration/Bonus/", "01. Fascination Street.mp3"),
        })

    def test_the_disc_folder_names_are_the_ones_the_engine_reads_as_discs(self) -> None:
        # A disc folder keeps its parent as the album. Any other name is a
        # folder searched in turn, so it becomes the album itself.
        for disc in DISC_FOLDERS:
            with self.subTest(disc_folder=disc):
                drop = self.drop()
                drop.item("Artist", f"Album/{disc}/01. One.flac")
                self.assertEqual(found(drop.stage()), [("01", "Album", "Artist")])
                self.assertEqual(drop.staged("01", "Album"), as_placed("Artist", "Album/", f"{disc}/01. One.flac"))
        for other in NOT_DISC_FOLDERS:
            with self.subTest(not_a_disc_folder=other):
                drop = self.drop()
                drop.item("Artist", f"Album/{other}/01. One.flac")
                self.assertEqual(found(drop.stage()), [("01", other, "Artist")])
                self.assertEqual(drop.staged("01", other), as_placed("Artist", f"Album/{other}/", "01. One.flac"))

    def test_a_disc_folder_with_no_audio_does_not_make_its_parent_an_album(self) -> None:
        drop = self.drop()
        drop.item("Artist", "Album/CD1/cover.jpg", "Album/Real/01. One.mp3")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "Real", "Artist")])
        self.assertEqual(ignored(staging), [("Artist", "Album/CD1/cover.jpg", OUTSIDE)])

    def test_every_audio_extension_the_engine_reads_makes_an_album_whatever_its_case(self) -> None:
        # `musiclib.files.AUDIO_EXTENSIONS`, the engine's one list: an album
        # agitha stages with no file the engine calls a track would only fail later.
        for ext in sorted(files.AUDIO_EXTENSIONS):
            for spelt in (ext, ext.upper()):
                with self.subTest(extension=spelt):
                    drop = self.drop()
                    drop.item("Album", f"01. One{spelt}")
                    self.assertEqual(found(drop.stage()), [("01", "Album", "Album")])

    def test_files_outside_every_album_are_ignored_with_their_path_inside_the_item(self) -> None:
        drop = self.drop()
        item = "Sonata Arctica - Pariah's Child.zip"
        drop.item(item, "Sonata Arctica/2014 - Pariah's Child/01. Stones Grow Her Name.mp3",
                  "x.txt", "cover.jpg", "Sonata Arctica/artist.jpg", "Extras/Scans/front.jpg", kind="archive")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "2014 - Pariah's Child", item)])
        self.assertEqual(ignored(staging), sorted([
            (item, "x.txt", OUTSIDE), (item, "cover.jpg", OUTSIDE), (item, "Sonata Arctica/artist.jpg", OUTSIDE),
            (item, "Extras/Scans/front.jpg", OUTSIDE),
        ]))
        self.assertStagedExactly(drop, {
            ("01", "2014 - Pariah's Child"): as_placed(item, "Sonata Arctica/2014 - Pariah's Child/",
                                                       "01. Stones Grow Her Name.mp3"),
        })

    def test_two_albums_in_one_item_are_numbered_in_path_order(self) -> None:
        drop = self.drop()
        # Written in the opposite order, so the order the files were created in gives the wrong answer.
        drop.item("Moby", "2005 - Hotel/01. Raining Again.mp3", "1999 - Play/01. Honey.mp3")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "1999 - Play", "Moby"), ("02", "2005 - Hotel", "Moby")])
        self.assertStagedExactly(drop, {
            ("01", "1999 - Play"): as_placed("Moby", "1999 - Play/", "01. Honey.mp3"),
            ("02", "2005 - Hotel"): as_placed("Moby", "2005 - Hotel/", "01. Raining Again.mp3"),
        })

    def test_albums_are_numbered_in_the_order_the_items_were_dropped_before_path_order(self) -> None:
        # Dropped Zeta first, then an item with no audio, then Alpha. Sorting
        # the item names puts Alpha first, and the item with no audio takes no number.
        drop = self.drop()
        drop.item("Zeta", "B/01. Two.mp3", "A/01. One.mp3")
        drop.item("Liner notes", "notes.txt")
        drop.item("Alpha", "01. Three.mp3")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "A", "Zeta"), ("02", "B", "Zeta"), ("03", "Alpha", "Alpha")])
        self.assertEqual(ignored(staging), [("Liner notes", "", NO_AUDIO)])
        self.assertStagedExactly(drop, {
            ("01", "A"): as_placed("Zeta", "A/", "01. One.mp3"),
            ("02", "B"): as_placed("Zeta", "B/", "01. Two.mp3"),
            ("03", "Alpha"): as_placed("Alpha", "", "01. Three.mp3"),
        })

    def test_albums_of_the_same_name_from_two_items_are_both_staged_under_their_own_numbers(self) -> None:
        drop = self.drop()
        drop.item("Rip by Ana", "Hotel/01. Raining Again.mp3")
        drop.item("Rip by Luis", "Hotel/01. Raining Again.flac")
        staging = drop.stage()
        self.assertEqual(found(staging), [("01", "Hotel", "Rip by Ana"), ("02", "Hotel", "Rip by Luis")])
        self.assertStagedExactly(drop, {
            ("01", "Hotel"): as_placed("Rip by Ana", "Hotel/", "01. Raining Again.mp3"),
            ("02", "Hotel"): as_placed("Rip by Luis", "Hotel/", "01. Raining Again.flac"),
        })


class NestedArchives(_Staging):
    """An archive inside an archive is a file of its album, never opened."""

    def test_an_archive_inside_an_album_is_moved_with_it_byte_for_byte_and_unopened(self) -> None:
        for ext in (".zip", ".rar", ".7z"):
            with self.subTest(extension=ext):
                drop = self.drop()
                item = "Hotel.zip"
                drop.item(item, "Hotel/01. Raining Again.mp3", kind="archive")
                if ext == ".zip":
                    # A real zip holding audio, so a stage that opened it would find a track.
                    nested = drop.raw / item / "Hotel" / "bonus.zip"
                    with zipfile.ZipFile(nested, "w") as z:
                        z.writestr("Hotel (Bonus)/01. Dream About Me.mp3", b"audio")
                    data = nested.read_bytes()
                else:
                    data = f"{ext} bytes".encode()
                    drop.put(item, f"Hotel/bonus{ext}", data)
                staging = drop.stage()
                self.assertEqual(found(staging), [("01", "Hotel", item)])
                self.assertEqual(ignored(staging), [])
                self.assertStagedExactly(drop, {("01", "Hotel"): {
                    **as_placed(item, "Hotel/", "01. Raining Again.mp3"), f"bonus{ext}": data,
                }})

    def test_an_item_whose_only_audio_is_inside_a_nested_archive_has_no_audio_files(self) -> None:
        drop = self.drop()
        root = drop.item("Singles.zip", kind="archive")
        with zipfile.ZipFile(root / "singles.zip", "w") as z:
            z.writestr("Singles/01. Porcelain.mp3", b"audio")
        staging = drop.stage()
        self.assertEqual(found(staging), [])
        self.assertEqual(ignored(staging), [("Singles.zip", "", NO_AUDIO)])
        self.assertStagedExactly(drop, {})


class NoAudio(_Staging):
    """An item with no audio at all is listed once, and nothing is staged from it."""

    def test_an_item_with_no_audio_is_one_ignored_entry_and_takes_no_number(self) -> None:
        drop = self.drop()
        drop.item("Artwork", "cover.jpg", "info.txt", "Scans/back.jpg", "album.cue", "rip.log", "booklet.pdf")
        staging = drop.stage()
        self.assertEqual(found(staging), [])
        # One entry for the item, not one per file as `outside every album`.
        self.assertEqual(ignored(staging), [("Artwork", "", NO_AUDIO)])
        self.assertStagedExactly(drop, {})

    def test_an_empty_item_has_no_audio_files(self) -> None:
        drop = self.drop()
        drop.item("Empty")
        staging = drop.stage()
        self.assertEqual(found(staging), [])
        self.assertEqual(ignored(staging), [("Empty", "", NO_AUDIO)])
        self.assertStagedExactly(drop, {})


if __name__ == "__main__":
    unittest.main()
