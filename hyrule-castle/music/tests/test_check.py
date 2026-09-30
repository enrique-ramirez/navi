"""`musiclib check ROOT`: every rule in `docs/music-library.md` an album breaks.

`check` is offline. It sees only the tree, so these
cover the rules that can be judged from the files alone. Each case builds a
library that follows every rule (`builders.library_album`), breaks exactly one
thing, and expects that rule and no other.

The rule ids below are what `check` prints and what the owner reads, so the
test fixes them. One id per rule in the doc:

    letter                the letter folder is not the artist folder's first letter
    album folder          not `(YYYY) Title` with at most one known prefix, or an edition
                          suffix with no other edition beside it
    album year            the folder's year is not the year of DATE
    disc folder           CDn folders where there is one medium, none where there are several,
                          or a file in the wrong one
    file name             not `NN. Title.ext` for the file's own number and title
    characters            a folder or file name the character table would change
    tag format            an MP3 that is not ID3v2.4, or carries ID3v1
    required field        a field every track has is missing
    year tag              a YEAR tag
    duplicate field       a second album artist field, or a TXXX total
    disc in album title   `(disc 1)` and the like in the album title
    genre                 a genre off the official list, miscased or delimited
    no genre              a track that carries no genre at all
    rating                a rating in any form but the documented one
    whitespace            leading, trailing or doubled spaces in a field
    cover.jpg             no cover.jpg
    embedded cover        not exactly one embedded front cover of at most 1200 px
    removed file          OS junk and stale rip lists
    extras                videos, disc images and software
    subfolder             a subfolder other than CDn
    image in disc folder  an image inside a CDn
    unexpected file       a file of a type the doc neither allows, removes nor moves to extras
    unreadable            a file mutagen cannot read, or an embedded picture that is not an image

A residue violation carries the `Removal.rule` from `residue.strip` instead.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, POPM, SYLT, USLT
from PIL import Image

from musiclib import caa, check, genres, mb, residue
from musiclib.__main__ import main
from musiclib.cache import Cache
from musiclib.units import Unit, units
from tests import builders
from tests.test_names import FIONA, FIONA_FOLDER

WMP = "Windows Media Player 9 Series"
ITUNES = "----:com.apple.iTunes:"

#: The shapes the first real run held 1,790 albums on. LRC lyrics from a
#: Windows ripper: CRLF, a trailing space on some lines.
LRC = "[00:12.34]I hurt myself today \r\n[00:17.02]To see if I still feel  \r\n"
#: iTunes normalisation data, which iTunes also writes into a plain comment.
ITUNNORM = (" 00001539 000016E0 0000A7B6 0000C0DE 0002A1F3 0002A1F3 00007FFF 00007FFF"
            " 00017B5A 00017B5A")
#: iTunes gapless data: one 16-digit group among the 8-digit ones.
ITUNSMPB = " 00000000 00000210 000007F4 0000000000A4E2BC 00000000 005A8B1C 00000000 00000000"


#: 59 six-letter words, 412 bytes: `(2007) ` and this cut before ` [...]`
#: and ` [Japan]` or ` [Europe]` leave the first 33 (`test_batch_holds`).
LONG_TITLE = " ".join(f"Part{n:02d}" for n in range(1, 60))
LONG_TITLE_KEPT = " ".join(LONG_TITLE.split(" ")[:33])


def _comm(text: str) -> COMM:
    """A comment with no description, the free-text `COMM::eng`."""
    return COMM(encoding=3, lang="eng", desc="", text=[text])


class _Library(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self._roots = 0

    def library(self) -> Path:
        """A fresh, empty ROOT, so each subtest judges only its own album."""
        self._roots += 1
        root = self.tmp / f"library-{self._roots}"
        root.mkdir()
        return root

    @staticmethod
    def audio(album: Path) -> list[Path]:
        exts = {".mp3", ".flac", ".ogg", ".m4a"}
        return sorted(p for p in album.rglob("*") if p.suffix in exts and not p.name.startswith("._"))

    def assertBreaks(self, root: Path, album: Path, expected: set[str], also: set[str] = frozenset()):
        """`check` names `album` and `expected`, and nothing but `also` besides.

        `also` is for a break that honestly breaks a second rule too, such as
        a folder with no year, which has no year to agree with DATE.
        """
        found = check.check(root)
        rules = {v.rule for v in found}
        for v in found:
            self.assertEqual(Path(v.album), album.relative_to(root))
            self.assertIsInstance(v.detail, str)
        self.assertLessEqual(expected, rules, f"missing, got {sorted(rules)}")
        self.assertLessEqual(rules, expected | set(also), f"too many, got {sorted(rules)}")


class ACleanLibrary(_Library):
    def test_a_library_that_follows_every_rule_has_no_violations(self):
        # Each album also holds a near miss, something that looks like a
        # break and is not one.
        root = self.library()
        builders.library_album(root, ext="mp3", album="With Teeth", date="2005-05-03")
        builders.library_album(root, ext="flac")
        builders.library_album(root, ext="ogg", album="Year Zero", date="2007")
        builders.library_album(root, ext="m4a", album="Ghosts I-IV", date="2008-03-02")
        # Two media, with a rip log per disc: logs may sit in a CDn.
        two = builders.library_album(root, album="The Downward Spiral", date="1994-03-08",
                                     discs=(("Mr. Self Destruct",), ("Piggy",)))
        (two / "CD1" / "rip.log").write_text("EAC log\n")
        # A prefix the table allows. Whether it is the right one needs
        # MusicBrainz, which check never asks.
        builders.library_album(root, folder="(2002) [Live] And All That Could Have Been",
                               album="And All That Could Have Been", date="2002-01-22")
        # LP as part of the title, never as a prefix.
        builders.library_album(root, letter="E", artist="Eminem", album="The Slim Shady LP",
                               date="1999-02-23")
        # Accents and digits in the letter.
        builders.library_album(root, letter="A", artist="Ángeles Azules, Los",
                               album="Divina", date="2006")
        builders.library_album(root, letter="#", artist="311", album="Grassroots", date="1994")
        # Titles the character table changes, named the way it says.
        builders.library_album(root, album="Broken", date="1992-09-22",
                               discs=((("Hurt: Live", "Hurt - Live"), ("Why?", "Why"),
                                       ('Say "Hi"', "Say ''Hi''")),))
        # Custom genres and documented ratings.
        game = builders.library_album(root, letter="K", artist="Koji Kondo", album="Ocarina",
                                      date="1998", ext="mp3")
        for path in self.audio(game):
            builders.write_tags(path, {"TCON": "video game music",
                                       "POPM": POPM(email=WMP, rating=196, count=3)}, v2_version=4)
        film = builders.library_album(root, letter="R", artist="Reznor & Ross", album="The Social Network",
                                      date="2010")
        for path, stars in zip(self.audio(film), ("1", "5")):
            builders.write_tags(path, {"GENRE": "soundtrack", "RATING": stars})

        self.assertEqual(check.check(root), [])


class Layout(_Library):
    def test_an_album_under_the_wrong_letter(self):
        for letter in ("M", "n"):
            with self.subTest(letter):
                root = self.library()
                self.assertBreaks(root, builders.library_album(root, letter=letter), {"letter"})

    def test_an_album_folder_not_shaped_year_prefix_title(self):
        cases = [
            ("The Fragile", {"album year"}),
            ("(99) The Fragile", {"album year"}),
            ("(1999) [EP] [Live] The Fragile", set()),
            ("(1999) [LP] The Fragile", set()),
            ("(1999) [Remastered] The Fragile", set()),
            # The title comes from the album tag.
            ("(1999) Fragile", set()),
        ]
        for folder, also in cases:
            with self.subTest(folder):
                root = self.library()
                album = builders.library_album(root, folder=folder)
                self.assertBreaks(root, album, {"album folder"}, also)

    def rules_by_album(self, root: Path) -> dict[str, set[str]]:
        """Each album folder `check` names under `root`, relative to it, with the rules it breaks."""
        found: dict[str, set[str]] = {}
        for v in check.check(root):
            found.setdefault(Path(v.album).as_posix(), set()).add(v.rule)
        return found

    def test_an_edition_suffix_beside_its_other_edition_under_the_same_artist_is_clean(self):
        # The tags do not
        # say which edition an album is, so check believes a suffix only
        # with the other edition beside it.
        pairs = [
            ("S", "Sonata Arctica", "Unia", "2007-05-23",
             ("(2007) Unia [Japan]", "(2007) Unia [Europe]")),
            ("T", "TV on the Radio", "Dear Science", "2008-09-23",
             ("(2008) Dear Science [CD]", "(2008) Dear Science [Vinyl]")),
            ("N", "Nine Inch Nails", "And All That Could Have Been", "2002-01-22",
             ("(2002) [Live] And All That Could Have Been [Europe]",
              "(2002) [Live] And All That Could Have Been [Japan]")),
            # Cut to 255 bytes before the suffix. Removing the suffix leaves
            # the cut mark, which is the tags' name and stays.
            ("W", "Wordy Band", LONG_TITLE, "2007",
             (f"(2007) {LONG_TITLE_KEPT} [...] [Japan]", f"(2007) {LONG_TITLE_KEPT} [...] [Europe]")),
        ]
        for letter, artist, album_title, date, folders in pairs:
            with self.subTest(folders[0]):
                root = self.library()
                for folder in folders:
                    builders.library_album(root, letter=letter, artist=artist, folder=folder,
                                           album=album_title, date=date)
                self.assertEqual(check.check(root), [])

    def test_an_edition_suffix_with_no_other_edition_beside_it_breaks_album_folder(self):
        # A folder is never its own other edition. The one beside it counts
        # only under the same artist folder and only with the same name once
        # its own suffix is gone, so in the last two cases both break.
        cases = {
            "a lone suffix": [
                ("R", "Radiohead", "(1997) OK Computer [FLAC]", "OK Computer", "1997-05-21"),
            ],
            "the other edition under another artist": [
                ("S", "Sonata Arctica", "(2007) Unia [Japan]", "Unia", "2007-05-23"),
                ("S", "Stratovarius", "(2007) Unia [Europe]", "Unia", "2007-05-23"),
            ],
            "a different album beside it": [
                ("S", "Sonata Arctica", "(2007) Unia [Japan]", "Unia", "2007-05-23"),
                ("S", "Sonata Arctica", "(2007) Unia Live [Europe]", "Unia Live", "2007-05-23"),
            ],
        }
        for case, albums in cases.items():
            with self.subTest(case):
                root = self.library()
                for letter, artist, folder, album_title, date in albums:
                    builders.library_album(root, letter=letter, artist=artist, folder=folder,
                                           album=album_title, date=date)
                self.assertEqual(self.rules_by_album(root),
                                 {f"{letter}/{artist}/{folder}": {"album folder"}
                                  for letter, artist, folder, _album, _date in albums})

    def test_a_folder_whose_brackets_the_album_tag_gives_is_judged_by_the_tag_alone(self):
        # The one folder on the box that has brackets from its tag. Alone in its
        # artist folder, its album tag decides. A name cut with ` [...]` is
        # the other shape the edition allowance leaves alone: `CutNames`.
        folder = "(1998) Something About Airplanes (10th Anniversary Limited Edition) [FLAC]"
        cases = [
            ("Something About Airplanes (10th Anniversary Limited Edition) [FLAC]", {}),
            ("Something About Airplanes (10th Anniversary Limited Edition)",
             {f"D/Death Cab for Cutie/{folder}": {"album folder"}}),
        ]
        for album_title, expected in cases:
            with self.subTest(album_title):
                root = self.library()
                builders.library_album(root, letter="D", artist="Death Cab for Cutie", folder=folder,
                                       album=album_title, date="1998-08-18")
                self.assertEqual(self.rules_by_album(root), expected)

    def test_an_edition_suffix_after_the_wrong_title_or_a_second_one_breaks_album_folder(self):
        # Each sits beside another edition whose
        # name is the same once the last suffix is gone, so the edition
        # allowance cannot be what passes them: what is left must
        # still be the name the tags give.
        cases = [
            ("(1999) Fragile [Japan]", "(1999) Fragile [Europe]"),
            ("(1999) The Fragile [Japan] [CD]", "(1999) The Fragile [Japan] [Vinyl]"),
            ("(1999) [Japan] The Fragile [CD]", "(1999) [Japan] The Fragile [Vinyl]"),
        ]
        for folders in cases:
            with self.subTest(folders[0]):
                root = self.library()
                for folder in folders:
                    builders.library_album(root, folder=folder)
                self.assertEqual(self.rules_by_album(root),
                                 {f"N/Nine Inch Nails/{folder}": {"album folder"} for folder in folders})

    def test_an_album_folder_year_that_disagrees_with_date(self):
        root = self.library()
        album = builders.library_album(root, folder="(1998) The Fragile", date="1999-09-21")
        self.assertBreaks(root, album, {"album year"})

    def test_one_medium_in_a_disc_folder(self):
        root = self.library()
        album = builders.library_album(root)
        (album / "CD1").mkdir()
        for path in self.audio(album):
            path.rename(album / "CD1" / path.name)
        self.assertBreaks(root, album, {"disc folder"})

    def test_several_media_without_disc_folders(self):
        root = self.library()
        album = builders.library_album(root, discs=(("Mr. Self Destruct",), ("Piggy",)))
        for path in self.audio(album):
            path.rename(album / path.name)
        for disc in ("CD1", "CD2"):
            (album / disc).rmdir()
        self.assertBreaks(root, album, {"disc folder"})

    def test_a_track_in_the_other_medium_folder(self):
        root = self.library()
        album = builders.library_album(root, discs=(("Mr. Self Destruct",), ("Piggy",)))
        (album / "CD2" / "01. Piggy.flac").rename(album / "CD1" / "02. Piggy.flac")
        # Numbering restarts per CDn, so 02 in CD1 is a name problem as well.
        self.assertBreaks(root, album, {"disc folder"}, {"file name"})

    def test_a_file_name_that_disagrees_with_the_tags(self):
        for wrong in ("03. Hurt.flac", "02. Hurts.flac", "2. Hurt.flac", "02 - Hurt.flac"):
            with self.subTest(wrong):
                root = self.library()
                album = builders.library_album(root)
                (album / "02. Hurt.flac").rename(album / wrong)
                self.assertBreaks(root, album, {"file name"})

    def test_an_upper_case_audio_extension_is_a_file_name_violation_expecting_it_lower_case(self):
        # A rip made on Windows can carry `.MP3`, and a comparison that
        # lower-cases both sides would call it clean while the plan renames it.
        for ext, upper in (("mp3", "MP3"), ("flac", "FLAC"), ("m4a", "M4a")):
            with self.subTest(upper):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                (album / f"02. Hurt.{ext}").rename(album / f"02. Hurt.{upper}")
                self.assertBreaks(root, album, {"file name"})
                details = [v.detail for v in check.check(root) if v.rule == "file name"]
                self.assertEqual(len(details), 1, details)
                self.assertIn(f"02. Hurt.{upper}", details[0])
                self.assertIn(f"expected '02. Hurt.{ext}'", details[0])

    def test_three_digits_on_a_medium_of_a_hundred_tracks_or_more(self):
        # The count comes from the track total, so one file stands in for a
        # medium of 120.
        for name, expected in (("002. Hurt.flac", set()), ("02. Hurt.flac", {"file name"})):
            with self.subTest(name):
                root = self.library()
                album = builders.library_album(root, discs=(("Hurt",),))
                path = album / "01. Hurt.flac"
                builders.write_tags(path, {"TRACKNUMBER": "2", "TRACKTOTAL": "120"})
                path.rename(album / name)
                if expected:
                    self.assertBreaks(root, album, expected)
                else:
                    self.assertEqual(check.check(root), [])

    def test_a_folder_name_the_character_table_would_change(self):
        # The artist folder has no other rule check can judge offline, so
        # this is the one place characters shows up on its own.
        for artist in ("Why?", "Why.", "AC:DC"):
            with self.subTest(artist):
                root = self.library()
                album = builders.library_album(root, letter=artist[0], artist=artist)
                self.assertBreaks(root, album, {"characters"})


#: The Fiona folder's title up to `You Go`, the word before `Solo,`. It is
#: where the cut lands once `[EP] ` or a track number and extension take
#: some of the 255 bytes, and one word short of where the plain folder's does.
FIONA_TO_GO = FIONA_FOLDER[len("(1999) "):-len(" Solo, [...]")]


class CutNames(_Library):
    def test_an_album_whose_folder_and_file_name_are_cut_by_criterion_46_is_clean(self):
        root = self.library()
        builders.library_album(root, letter="F", artist="Fiona Apple", folder=FIONA_FOLDER,
                               album=FIONA, date="1999-11-09",
                               discs=(((FIONA, f"{FIONA_TO_GO} [...]"), "Paper Bag"),))
        # The prefix is part of what is cut, so the same title under `[EP]`
        # loses a word more. A check that cuts `(YYYY) Title` and then adds
        # the prefix expects `Solo,` here.
        builders.library_album(root, letter="F", artist="Fiona Apple",
                               folder=f"(1999) [EP] {FIONA_TO_GO} [...]", album=FIONA, date="1999-11-09")
        self.assertEqual(check.check(root), [])

    def test_a_folder_cut_at_the_wrong_word_or_cut_when_it_fits_breaks_album_folder(self):
        cases = [
            ("one word short", f"(1999) {FIONA_TO_GO} [...]", FIONA),
            ("cut when the full name fits", "(1999) The [...]", "The Fragile"),
        ]
        for case, folder, album_title in cases:
            with self.subTest(case):
                root = self.library()
                album = builders.library_album(root, folder=folder, album=album_title, date="1999-09-21")
                self.assertBreaks(root, album, {"album folder"})

    def test_a_file_name_cut_at_the_wrong_word_or_cut_when_it_fits_breaks_file_name(self):
        cases = [
            ("one word short", (FIONA, f"{FIONA_TO_GO[:-len(' Go')]} [...]")),
            ("cut when the full name fits", ("Somewhat Damaged", "Somewhat [...]")),
        ]
        for case, track in cases:
            with self.subTest(case):
                root = self.library()
                album = builders.library_album(root, discs=((track, "Hurt"),))
                self.assertBreaks(root, album, {"file name"})


def _wma_album(root: Path, discs: tuple = (("Somewhat Damaged", "Hurt"),)) -> Path:
    """`builders.library_album` for WMA, which the builder does not make: an album that breaks no rule.

    Picard has no ASF name for the track total, so these files carry none,
    the same as a WMA Picard wrote. `discs` holds each medium's titles; more
    than one puts each in a `CDn`. Returns the album folder.
    """
    base = root / "N" / "Nine Inch Nails" / "(1999) The Fragile"
    base.mkdir(parents=True)
    cover = builders.embedded_cover()
    for disc, titles in enumerate(discs, start=1):
        where = base / f"CD{disc}" if len(discs) > 1 else base
        where.mkdir(exist_ok=True)
        for number, title in enumerate(titles, start=1):
            digits = 3 if len(titles) >= 100 else 2
            path = where / f"{number:0{digits}d}. {title}.wma"
            shutil.copyfile(builders.FIXTURES / "tone.wma", path)
            fields = {"title": [title], "artist": ["Nine Inch Nails"], "album": ["The Fragile"],
                      "albumartist": ["Nine Inch Nails"], "date": ["1999-09-21"],
                      "genre": ["industrial rock"], "release id": [builders.MBID],
                      "release group id": [builders.MBID], "recording id": [builders.MBID],
                      "artist id": [builders.MBID]}
            builders.write_tags(path, builders.picard_tags("wma", fields, track=(number, len(titles)),
                                                           disc=(disc, len(discs))))
            builders.embed_picture(path, cover)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


class FileNamesWithoutATotal(_Library):
    # With no track total a file name was never judged at all, so every WMA
    # in the library could carry any name and check said nothing. The digit
    # width then comes from the tracks the album holds in the same disc
    # (decision).

    def file_name_details(self, root: Path) -> list[str]:
        return [v.detail for v in check.check(root) if v.rule == "file name"]

    def test_a_wma_album_named_by_the_rules_has_no_violations(self):
        root = self.library()
        _wma_album(root)
        self.assertEqual(check.check(root), [])

    def test_a_misnamed_wma_is_a_file_name_violation_naming_it(self):
        for wrong in ("hurt (wrong name).wma", "2. Hurt.wma", "02 - Hurt.wma", "01. Hurt.wma"):
            with self.subTest(wrong):
                root = self.library()
                album = _wma_album(root)
                (album / "02. Hurt.wma").rename(album / wrong)
                self.assertBreaks(root, album, {"file name"})
                details = self.file_name_details(root)
                self.assertTrue(any(wrong in d for d in details), f"no detail names {wrong!r}: {details}")

    def test_a_wma_disc_of_a_hundred_tracks_takes_three_digits_counted_per_disc(self):
        # CD1 holds 100 tracks and CD2 two, so the whole album holds 102. A
        # width counted over the album would ask CD2 for three digits, and a
        # fixed width of two would reject every name in CD1.
        root = self.library()
        album = _wma_album(root, discs=(tuple(f"Track {n}" for n in range(1, 101)), ("Piggy", "Hurt")))
        self.assertEqual(self.file_name_details(root), [])

        (album / "CD1" / "007. Track 7.wma").rename(album / "CD1" / "07. Track 7.wma")
        details = self.file_name_details(root)
        self.assertEqual(len(details), 1, details)
        self.assertIn("07. Track 7.wma", details[0])

    def test_an_mp3_whose_trck_has_no_total_is_judged_on_its_name_too(self):
        # A TRCK of "2" rather than "2/2" is its own break (required field);
        # it must not also switch off the name check.
        for name, expected in (("02. Hurt.mp3", {"required field"}),
                               ("hurt.mp3", {"required field", "file name"})):
            with self.subTest(name):
                root = self.library()
                album = builders.library_album(root, ext="mp3")
                for number, path in enumerate(self.audio(album), start=1):
                    builders.write_tags(path, {"TRCK": str(number)}, v2_version=4)
                (album / "02. Hurt.mp3").rename(album / name)
                self.assertBreaks(root, album, expected)


class Tags(_Library):
    def first(self, root, ext="flac", **kwargs) -> tuple[Path, Path]:
        album = builders.library_album(root, ext=ext, **kwargs)
        return album, self.audio(album)[0]

    def test_an_mp3_that_is_not_id3v24_or_carries_id3v1(self):
        for case in ("v2.3", "v1"):
            with self.subTest(case):
                root = self.library()
                album, path = self.first(root, "mp3")
                also = set()
                if case == "v2.3":
                    ID3(path).save(path, v2_version=3)
                    # v2.3 has no multi-value text frames: the two genres
                    # come back as one "industrial rock/electronic".
                    also = {"genre"}
                else:
                    builders.add_id3v1(path, v2_version=4)
                self.assertBreaks(root, album, {"tag format"}, also)

    def test_a_missing_required_field(self):
        cases = [
            ("flac", "album artist", lambda p: builders.delete_tags(p, ["ALBUMARTIST"])),
            ("ogg", "release group id", lambda p: builders.delete_tags(p, ["MUSICBRAINZ_RELEASEGROUPID"])),
            ("flac", "disc total", lambda p: builders.delete_tags(p, ["DISCTOTAL"])),
            ("mp3", "recording id", lambda p: builders.delete_tags(p, ["UFID"])),
            ("mp3", "track total", lambda p: builders.write_tags(p, {"TRCK": "1"}, v2_version=4)),
            ("mp3", "artist id", lambda p: builders.delete_tags(p, ["TXXX:MusicBrainz Artist Id"])),
            ("m4a", "disc total", lambda p: builders.write_tags(p, {"disk": [(1, 0)]})),
            ("m4a", "title", lambda p: builders.delete_tags(p, ["\xa9nam"])),
        ]
        for ext, what, remove in cases:
            with self.subTest(ext=ext, field=what):
                root = self.library()
                album, path = self.first(root, ext)
                remove(path)
                # A file with no title cannot agree with its name.
                also = {"file name"} if what == "title" else set()
                self.assertBreaks(root, album, {"required field"}, also)

    def test_a_missing_date(self):
        root = self.library()
        album, path = self.first(root, "ogg")
        builders.delete_tags(path, ["DATE"])
        self.assertBreaks(root, album, {"required field"}, {"album year"})

    def test_a_year_tag(self):
        for ext, tags in (("flac", {"YEAR": "1999"}), ("mp3", {"TXXX:YEAR": "1999"}),
                          ("m4a", {"----:com.apple.iTunes:YEAR": "1999"})):
            with self.subTest(ext):
                root = self.library()
                album, path = self.first(root, ext)
                builders.write_tags(path, tags, v2_version=4)
                self.assertBreaks(root, album, {"year tag"})

    def test_a_second_album_artist_field_or_a_txxx_total(self):
        for ext, tags in (("mp3", {"TXXX:ALBUM ARTIST": "Nine Inch Nails"}),
                          ("flac", {"ALBUM ARTIST": "Nine Inch Nails"}),
                          ("mp3", {"TXXX:TOTALTRACKS": "2"}),
                          ("mp3", {"TXXX:DISCTOTAL": "1"})):
            with self.subTest(ext=ext, tags=tags):
                root = self.library()
                album, path = self.first(root, ext)
                builders.write_tags(path, tags, v2_version=4)
                self.assertBreaks(root, album, {"duplicate field"})

    def test_a_disc_marker_in_the_album_title(self):
        # The folder carries the same title, so only the tag rule fires.
        for title in ("The Fragile (disc 1)", "The Fragile (Bonus Disc)"):
            with self.subTest(title):
                root = self.library()
                album = builders.library_album(root, album=title)
                self.assertBreaks(root, album, {"disc in album title"})

    def test_a_genre_off_the_list_miscased_or_delimited(self):
        self.assertNotIn("made-up genre", genres.OFFICIAL)
        for ext, tags in (("flac", {"GENRE": "Rock"}), ("flac", {"GENRE": "rock; electronic"}),
                          ("flac", {"GENRE": "made-up genre"}), ("mp3", {"TCON": "Industrial Rock"})):
            with self.subTest(ext=ext, tags=tags):
                root = self.library()
                album, path = self.first(root, ext)
                builders.write_tags(path, tags, v2_version=4)
                self.assertBreaks(root, album, {"genre"})

    def test_every_track_with_no_genre_breaks_no_genre_and_nothing_else(self):
        field = {"mp3": "TCON", "flac": "GENRE", "ogg": "GENRE", "m4a": "\xa9gen"}
        for ext in ("mp3", "flac", "ogg", "m4a"):
            for stripped in (1, 2):
                with self.subTest(ext=ext, tracks_stripped=stripped):
                    root = self.library()
                    album = builders.library_album(root, ext=ext)
                    for path in self.audio(album)[:stripped]:
                        builders.delete_tags(path, [field[ext]])
                    self.assertBreaks(root, album, {"no genre"})
                    found = [v for v in check.check(root) if v.rule == "no genre"]
                    self.assertEqual(len(found), stripped, found)

    def test_a_genre_field_that_is_blank_or_only_spaces_breaks_no_genre(self):
        # The field is there, so a check that only asks whether the key
        # exists passes it. MP3 is left out: mutagen never saves an empty
        # ID3 text frame, so an MP3 cannot carry one. Whether the blank value
        # also breaks `genre` or `whitespace` is not decided, so either may
        # come with it.
        field = {"flac": "GENRE", "ogg": "GENRE", "m4a": "\xa9gen"}
        for ext in ("flac", "ogg", "m4a"):
            for blank in ("", "   "):
                with self.subTest(ext=ext, value=repr(blank)):
                    root = self.library()
                    album = builders.library_album(root, ext=ext)
                    for path in self.audio(album):
                        builders.write_tags(path, {field[ext]: blank})
                    self.assertBreaks(root, album, {"no genre"}, {"genre", "whitespace"})

    def test_a_blank_genre_beside_a_real_one_breaks_genre_naming_the_track(self):
        # The track has a genre, so it is not `no genre`. The blank is still
        # not an official genre, and a check that drops blanks before judging
        # the values passes the track silently. Only one track carries it, so
        # the detail has to say which.
        field = {"flac": "GENRE", "ogg": "GENRE", "m4a": "\xa9gen"}
        for ext in ("flac", "ogg", "m4a"):
            for blank, also in (("", set()), ("   ", {"whitespace"})):
                with self.subTest(ext=ext, value=repr(blank)):
                    root = self.library()
                    album = builders.library_album(root, ext=ext)
                    blanked = self.audio(album)[0]
                    builders.write_tags(blanked, {field[ext]: [blank, "rock"]})
                    self.assertBreaks(root, album, {"genre"}, also)
                    details = [v.detail for v in check.check(root) if v.rule == "genre"]
                    self.assertTrue(all(blanked.name in d for d in details),
                                    f"a genre break does not name {blanked.name}: {details}")

    def test_a_track_carrying_only_video_game_music_is_clean(self):
        # `video game music` is off the official list, and it is still a genre.
        for ext, tags in (("mp3", {"TCON": "video game music"}), ("flac", {"GENRE": "video game music"}),
                          ("ogg", {"GENRE": "video game music"}), ("m4a", {"\xa9gen": "video game music"})):
            with self.subTest(ext):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                for path in self.audio(album):
                    builders.write_tags(path, tags, v2_version=4)
                self.assertEqual(check.check(root), [])

    def test_a_rating_in_any_but_the_documented_form(self):
        # MP3: one POPM from Windows Media Player 9 Series on the WMP scale.
        # FLAC and Ogg: RATING, whole stars 1 to 5. Unrated means no tag.
        cases = [
            ("mp3", {"POPM": POPM(email=WMP, rating=100, count=0)}),
            ("mp3", {"POPM": POPM(email=WMP, rating=0, count=0)}),
            ("mp3", {"POPM": POPM(email="rating@winamp.com", rating=196, count=0)}),
            ("flac", {"RATING": "0"}),
            ("flac", {"RATING": "-1"}),
            ("ogg", {"RATING": "4.5"}),
            ("flac", {"RATING": "80"}),
            ("flac", {"RATING": "6"}),
        ]
        for ext, tags in cases:
            with self.subTest(ext=ext, tags=repr(tags)):
                root = self.library()
                album, path = self.first(root, ext)
                builders.write_tags(path, tags, v2_version=4)
                self.assertBreaks(root, album, {"rating"})

    def test_leading_trailing_or_doubled_spaces_in_any_field(self):
        # A trailing space in the title leaves the file name unchanged: the
        # character table drops it there.
        for tags in ({"TITLE": "Hurt "}, {"ARTIST": " Nine Inch Nails"},
                     {"COMMENT": "liner  notes by the band"}):
            with self.subTest(tags):
                root = self.library()
                album = builders.library_album(root)
                builders.write_tags(album / "02. Hurt.flac", tags)
                self.assertBreaks(root, album, {"whitespace"})

    def test_residue_is_reported_by_its_rule(self):
        for ext, family, tags, key in (("flac", "vorbis", {"ENCODER": "LAME"}, "encoder"),
                                       ("mp3", "id3", {"TSSE": "LAME"}, "TSSE")):
            with self.subTest(ext):
                root = self.library()
                album, path = self.first(root, ext)
                builders.write_tags(path, tags, v2_version=4)
                _, removals = residue.strip(family, {key: ["LAME"]})
                rule = removals[0].rule
                found = check.check(root)
                self.assertTrue(found)
                for v in found:
                    self.assertEqual(Path(v.album), album.relative_to(root))
                    self.assertIn(rule, v.rule)

    def test_an_artist_and_composer_named_will_i_am_are_no_residue(self):
        # `will.i.am` ends in a country code. The engine planned it from
        # MusicBrainz, so calling it a site here would hold his albums for
        # good: the plan writes the name back and check rejects it again.
        for ext, composer in (("flac", "COMPOSER"), ("mp3", "TCOM")):
            with self.subTest(ext):
                root = self.library()
                album = builders.library_album(root, ext=ext, letter="W", artist="will.i.am",
                                               album="Willpower", date="2013-04-19")
                for path in self.audio(album):
                    builders.write_tags(path, {composer: "will.i.am"}, v2_version=4)
                self.assertEqual(check.check(root), [])


class Whitespace(_Library):
    """What `whitespace` reports on disk, and what it leaves alone."""

    def judge(self, ext: str, tags: dict, expected: set[str]) -> None:
        root = self.library()
        album = builders.library_album(root, ext=ext)
        builders.write_tags(self.audio(album)[0], tags, v2_version=4)
        self.assertBreaks(root, album, expected)

    def test_a_track_whose_kept_as_written_fields_carry_stray_spaces_is_clean(self):
        cases = [
            ("LRC lyrics in USLT", "mp3", {"USLT": USLT(encoding=3, lang="eng", desc="", text=LRC)}),
            # SYLT reads back as a repr of its (text, time) pairs, doubled
            # space and all.
            ("synced lyrics in SYLT", "mp3", {"SYLT": SYLT(
                encoding=3, lang="eng", format=2, type=1, desc="",
                text=[("I hurt  myself today ", 12340), (" To see if I still feel", 17020)])}),
            ("lyrics in TXXX, one line", "mp3", {"TXXX:LYRICS": "la  la "}),
            ("unsynced lyrics in Vorbis", "flac", {"UNSYNCED LYRICS": LRC}),
            # One line, so the line-break rule does not cover it. Only the
            # field's name keeps it.
            ("Vorbis lyrics, one line", "ogg", {"LYRICS": " la  la"}),
            ("unsynced lyrics in an MP4 freeform atom", "m4a", {ITUNES + "UNSYNCED LYRICS": LRC}),
            ("MP4 lyrics atom, one line", "m4a", {"\xa9lyr": "la  la "}),
            ("TXXX:LAST_PLAYED with a trailing space", "mp3", {"TXXX:LAST_PLAYED": "2019-04-02 21:14:03 "}),
            ("TXXX:first_played in lower case", "mp3", {"TXXX:first_played": "2011-07-19 20:01:44 "}),
            ("the rest of play history in Vorbis", "flac", {
                "PLAY_COUNT": " 3", "PLAY_COUNTER": "12 ", "PLAY_STAMP": "2019-04-02  21:14:03",
                "ADDED": "2012-01-01 10:00:00 "}),
            ("play history in an MP4 freeform atom", "m4a", {ITUNES + "Last_Played": "2019-04-02 21:14:03 "}),
            ("iTunes normalisation data in COMM::eng", "mp3", {"COMM": _comm(ITUNNORM)}),
            ("iTunes gapless data in a Vorbis comment", "flac", {"COMMENT": ITUNSMPB}),
            ("TXXX:major_brand", "mp3", {"TXXX:major_brand": "M4A "}),
            ("minor_version and compatible_brands in Vorbis", "flac", {
                "MINOR_VERSION": " 512", "COMPATIBLE_BRANDS": "M4A  mp42isom"}),
            # A value holding a line break is kept as it is.
            ("a multi-line Vorbis comment", "flac", {
                "COMMENT": "Recorded at Abbey Road.  \nMixed by  Alan Moulder "}),
            ("a multi-line COMM::eng", "mp3", {"COMM": _comm("Recorded at Abbey Road. \r\nMixed  by Alan Moulder")}),
        ]
        for case, ext, tags in cases:
            with self.subTest(case):
                self.judge(ext, tags, set())

    def test_stray_spaces_in_any_other_single_line_field_break_whitespace(self):
        # The near misses matter as much as the plain ones: a kept name
        # matched as a prefix, or a hex test loose enough to take any
        # comment that starts with a space, would clear these too.
        cases = [
            ("TCOM with a doubled space", "mp3", {"TCOM": "Trent  Reznor"}),
            ("TCOM from the first run", "mp3", {"TCOM": "Billy Squier/Danny  Kortchmar"}),
            ("a copyright with a trailing space", "flac", {"COPYRIGHT": "(C) 1994 Nothing Records "}),
            ("groups of four hex digits are not iTunes data", "mp3", {"COMM": _comm(" 1539 16E0 A7B6")}),
            ("a group of seventeen is not either", "flac", {"COMMENT": " 00000000000001539"}),
            ("a comment that only starts with a space", "flac", {"COMMENT": " Bought at Rough Trade"}),
            ("a name that only starts with a kept one", "mp3", {"TXXX:LAST_PLAYED_BY": "Enrique "}),
            # iTunes data is kept in a comment, and nowhere else.
            ("iTunes-shaped data outside a comment", "flac", {"COPYRIGHT": ITUNNORM}),
        ]
        for case, ext, tags in cases:
            with self.subTest(case):
                self.judge(ext, tags, {"whitespace"})

    def test_a_rating_with_a_stray_space_is_not_whitespace(self):
        # A rating is kept as it is, so the plan never cleans one. Reporting
        # it here would hold the album for good: no plan can make it go
        # away. Whether an FMPS rating breaks `rating` is the rating rule's
        # business, not this one's.
        for ext, tags in (("flac", {"FMPS_RATING": "0.8 "}), ("mp3", {"TXXX:FMPS_RATING": "0.8 "})):
            with self.subTest(ext):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                builders.write_tags(self.audio(album)[0], tags, v2_version=4)
                self.assertBreaks(root, album, set(), also={"rating"})

    def test_a_blank_lyrics_value_is_residue_blank_and_not_whitespace(self):
        cases = [
            ("USLT of one space", "mp3", {"USLT": USLT(encoding=3, lang="eng", desc="", text=" ")}),
            ("empty Vorbis lyrics", "flac", {"LYRICS": ""}),
            ("MP4 lyrics of only a line break", "m4a", {"\xa9lyr": "\r\n"}),
        ]
        for case, ext, tags in cases:
            with self.subTest(case):
                self.judge(ext, tags, {"residue: blank"})


class Images(_Library):
    def test_an_album_without_cover_jpg(self):
        root = self.library()
        album = builders.library_album(root)
        (album / "cover.jpg").unlink()
        self.assertBreaks(root, album, {"cover.jpg"})

    def test_a_track_without_an_embedded_front_cover(self):
        for ext in ("mp3", "flac", "ogg", "m4a"):
            with self.subTest(ext):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                builders.clear_pictures(self.audio(album)[0])
                self.assertBreaks(root, album, {"embedded cover"})

    def test_a_track_with_a_wrong_embedded_cover(self):
        big = (builders.FIXTURES / "cover.jpg").read_bytes()  # 1600 x 900
        cases = [
            ("two front covers", "flac", lambda p: builders.embed_picture(p, builders.embedded_cover())),
            ("two front covers", "mp3", lambda p: builders.embed_picture(p, builders.embedded_cover())),
            ("larger than 1200 px", "flac", lambda p: builders.embed_picture(p, big, replace=True)),
            ("larger than 1200 px", "m4a", lambda p: builders.embed_picture(p, big, replace=True)),
            ("tall rather than wide", "ogg",
             lambda p: builders.embed_picture(p, builders.jpeg(800, 1300), replace=True)),
            ("no front, only a back", "mp3",
             lambda p: builders.embed_picture(p, builders.embedded_cover(), picture_type=4, replace=True)),
        ]
        for case, ext, spoil in cases:
            with self.subTest(case=case, ext=ext):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                spoil(self.audio(album)[0])
                self.assertBreaks(root, album, {"embedded cover"})

    def test_a_cover_exactly_1200_px_is_allowed(self):
        root = self.library()
        album = builders.library_album(root)
        for path in self.audio(album):
            builders.embed_picture(path, builders.jpeg(1200, 1200), replace=True)
        self.assertEqual(check.check(root), [])


class FolderContents(_Library):
    #: The *Removed* list in the doc, one sample each.
    REMOVED = [
        ".DS_Store", "._01. Somewhat Damaged.flac", "Thumbs.db", "desktop.ini", ".directory",
        "Icon\r", "AlbumArtSmall.jpg", "AlbumArt_{9A1C3D2E-0000-4000-8000-000000000001}_Large.jpg",
        "The Fragile.cue", "The Fragile.m3u", "The Fragile.m3u8", "The Fragile.sfv",
        "The Fragile.accurip", "The Fragile.ffp", "The Fragile.md5", "The Fragile.nfo",
        "Buy it.url", "folder.ini", "folder.ico",
    ]
    #: Videos, disc images and software. The doc names the kinds, not the
    #: extensions, so these are only the unarguable ones.
    EXTRAS = ["Making of.mkv", "Live.avi", "The Fragile.iso", "Setup.exe"]

    def test_each_removed_file_type(self):
        for name in self.REMOVED:
            with self.subTest(name=name):
                root = self.library()
                album = builders.library_album(root)
                (album / name).write_bytes(b"x")
                self.assertBreaks(root, album, {"removed file"})

    def test_an_lrc_beside_the_tracks_is_a_removed_file_like_a_cue(self):
        # An .lrc is named after the track file it was saved with, so once
        # the track is renamed it matches nothing and no player finds it.
        # The library's two are under F/Foo Fighters/, named like this one.
        for name in ("Foo Fighters - In Your Honor (CD2) - 08 - Virginia Moon.lrc",
                     "Foo Fighters - In Your Honor (CD2) - 08 - Virginia Moon.LRC"):
            with self.subTest(name=name):
                root = self.library()
                album = builders.library_album(root)
                (album / name).write_text("[00:00.00] Virginia Moon\n")
                self.assertBreaks(root, album, {"removed file"})
                details = [v.detail for v in check.check(root) if v.rule == "removed file"]
                self.assertIn(name, details)

    def test_junk_inside_a_disc_folder_and_a_macosx_folder(self):
        for name in ("CD1/.DS_Store", "__MACOSX/._cover.jpg"):
            with self.subTest(name):
                root = self.library()
                album = builders.library_album(root, discs=(("Mr. Self Destruct",), ("Piggy",)))
                (album / name).parent.mkdir(exist_ok=True)
                (album / name).write_bytes(b"x")
                # __MACOSX is a subfolder too. It is the junk that matters.
                self.assertBreaks(root, album, {"removed file"}, {"subfolder"})

    def test_each_extras_type(self):
        for name in self.EXTRAS:
            with self.subTest(name=name):
                root = self.library()
                album = builders.library_album(root)
                (album / name).write_bytes(b"x")
                self.assertBreaks(root, album, {"extras"})

    def test_a_subfolder_other_than_cdn(self):
        for name in ("Scans/back.jpg", "Artwork/booklet.pdf"):
            with self.subTest(name):
                root = self.library()
                album = builders.library_album(root)
                (album / name).parent.mkdir()
                shutil.copyfile(builders.FIXTURES / "cover.jpg", album / name)
                self.assertBreaks(root, album, {"subfolder"})

    def test_an_image_inside_a_disc_folder(self):
        root = self.library()
        album = builders.library_album(root, discs=(("Mr. Self Destruct",), ("Piggy",)))
        shutil.copyfile(builders.FIXTURES / "cover.jpg", album / "CD2" / "medium.jpg")
        self.assertBreaks(root, album, {"image in disc folder"})

    def test_a_file_of_a_type_the_doc_does_not_list_is_an_unexpected_file_named_in_the_detail(self):
        # The doc lists what an album folder may hold. Anything else was kept
        # silently before, so a Word document or a zip of scans sat in the
        # library with check reporting the album clean.
        for name in ("Liner notes.docx", "Scans.zip", "CD1/Tracklist.docx"):
            with self.subTest(name):
                root = self.library()
                album = builders.library_album(root, discs=(("Mr. Self Destruct",), ("Piggy",)))
                (album / name).write_bytes(b"x")
                self.assertBreaks(root, album, {"unexpected file"})
                details = [v.detail for v in check.check(root) if v.rule == "unexpected file"]
                self.assertTrue(any(PurePosixPath(name).name in d for d in details),
                                f"no detail names {name!r}: {details}")

    def test_every_listed_type_is_expected_whatever_the_case_of_its_extension(self):
        # A rule that matched `.pdf` and not `.PDF` would flag half the rips
        # made on Windows. The builder's album already holds the lower-case
        # forms, so these are the other spellings.
        root = self.library()
        album = builders.library_album(root)
        shutil.copyfile(builders.FIXTURES / "cover.jpg", album / "Inlay.JPEG")
        (album / "Back.PNG").write_bytes(builders.jpeg(10, 10))
        for name in ("Booklet.PDF", "EAC.LOG", "Notes.TXT"):
            (album / name).write_bytes(b"x")
        self.assertEqual(check.check(root), [])


def _link_as_front_cover(path: Path) -> None:
    """An MP3's front cover replaced by an APIC that holds a URL, not an image.

    ID3 allows it: mime `-->` says the data is a link. Nothing can open it
    as a picture.
    """
    tag = ID3(path)
    tag.delall("APIC")
    tag.add(APIC(encoding=3, mime="-->", type=3, desc="", data=b"http://example.com/cover.jpg"))
    tag.save(path, v2_version=4)


def _garbage_as_front_cover(path: Path) -> None:
    """A FLAC's front cover replaced by a picture block whose data is not an image."""
    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg"
    picture.data = b"not a jpeg at all"
    audio = FLAC(path)
    audio.clear_pictures()
    audio.add_picture(picture)
    audio.save()


def _truncate(path: Path) -> None:
    """Cut the file in half, which in these fixtures lands inside the picture block."""
    data = path.read_bytes()
    path.write_bytes(data[:len(data) // 2])


class ABadFile(_Library):
    # The real library is 30,428 files. Before this, one of them that mutagen
    # or Pillow could not read raised out of check and the owner got a
    # traceback and no report on the other 2,299 albums.

    def assertUnreadable(self, root: Path, album: Path, name: str, also: set[str] = frozenset()):
        """`album` breaks `unreadable`, with a detail naming `name`."""
        self.assertBreaks(root, album, {"unreadable"}, also)
        details = [v.detail for v in check.check(root) if v.rule == "unreadable"]
        self.assertTrue(any(name in d for d in details), f"no detail names {name!r}: {details}")

    def test_a_file_mutagen_cannot_read_is_unreadable_and_named(self):
        cases = [
            ("fifty zero bytes named .mp3", "mp3", lambda p: p.write_bytes(b"\0" * 50)),
            ("a truncated FLAC", "flac", _truncate),
        ]
        for case, ext, spoil in cases:
            with self.subTest(case):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                spoil(album / f"02. Hurt.{ext}")
                self.assertUnreadable(root, album, f"02. Hurt.{ext}")

    def test_an_embedded_front_cover_that_is_not_an_image_is_unreadable_and_named(self):
        # Whether the same track also breaks "embedded cover" is left open:
        # there is a front cover, but nobody can say how big it is.
        for case, ext, spoil in (("an MP3 APIC holding a URL", "mp3", _link_as_front_cover),
                                 ("a FLAC picture of garbage bytes", "flac", _garbage_as_front_cover)):
            with self.subTest(case):
                root = self.library()
                album = builders.library_album(root, ext=ext)
                spoil(album / f"02. Hurt.{ext}")
                self.assertUnreadable(root, album, f"02. Hurt.{ext}", {"embedded cover"})

    def test_an_mp3_with_no_id3_header_breaks_the_tag_rules_and_is_not_unreadable(self):
        # mutagen reads the audio fine; there is just no tag. So it is judged
        # like any other track: no ID3v2.4, none of the required fields, no
        # genre, no embedded front cover. Calling it unreadable would hide
        # which rules a retag has to fix.
        root = self.library()
        album = builders.library_album(root, ext="mp3")
        path = album / "02. Hurt.mp3"
        ID3(path).delete(path)
        self.assertNotEqual(path.read_bytes()[:3], b"ID3")
        self.assertBreaks(root, album, {"tag format", "required field", "no genre", "embedded cover"})

    def test_a_bad_file_leaves_the_rest_of_its_album_and_the_next_album_judged(self):
        # The bad album sorts first, and so does the bad file within it: the
        # track and the junk after it are read later. A check that gave up on
        # the first error, or on the rest of the album holding it, reports
        # less than this.
        root = self.library()
        bad = builders.library_album(root, letter="A", artist="Autechre", album="Amber", date="1994")
        (bad / "01. Somewhat Damaged.flac").write_bytes(b"\0" * 50)
        builders.write_tags(bad / "02. Hurt.flac", {"YEAR": "1994"})
        (bad / "Thumbs.db").write_bytes(b"x")
        later = builders.library_album(root)
        (later / "Thumbs.db").write_bytes(b"x")

        found = {(Path(v.album), v.rule) for v in check.check(root)}

        self.assertEqual(found, {(bad.relative_to(root), "unreadable"),
                                 (bad.relative_to(root), "year tag"),
                                 (bad.relative_to(root), "removed file"),
                                 (later.relative_to(root), "removed file")})


def _broken_library(root: Path) -> Path:
    """One clean album and one that breaks three rules, one of them residue.

    The clean one sorts first, so a check that stops early finds nothing.
    """
    builders.library_album(root, ext="flac", album="The Downward Spiral", date="1994")
    album = builders.library_album(root, ext="mp3")
    path = album / "02. Hurt.mp3"
    builders.write_tags(path, {"TSSE": "LAME"})  # also saves it as ID3v2.3
    (album / ".DS_Store").write_bytes(b"x")
    return album


def _snapshot(root: Path) -> dict:
    """Every file and folder under `root`: its content and its mtime."""
    seen = {".": ("dir", root.stat().st_mtime_ns)}
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(folder) / name
            stat = path.stat()
            digest = hashlib.sha1(path.read_bytes()).hexdigest() if path.is_file() else "dir"
            seen[str(path.relative_to(root))] = (digest, stat.st_mtime_ns)
    return seen


class TheCommand(_Library):
    def run_check(self, root: Path) -> tuple[int, list[str]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["check", str(root)])
        return code, out.getvalue().splitlines()

    def test_a_clean_library_exits_0(self):
        root = self.library()
        builders.library_album(root)
        builders.library_album(root, ext="mp3", album="With Teeth", date="2005")
        code, _ = self.run_check(root)
        self.assertEqual(code, 0)

    def test_violations_exit_1_with_a_line_naming_album_and_rule_for_each(self):
        root = self.library()
        album = _broken_library(root)
        found = check.check(root)
        self.assertEqual({Path(v.album) for v in found}, {album.relative_to(root)})
        self.assertIn("tag format", {v.rule for v in found})
        self.assertIn("removed file", {v.rule for v in found})

        code, lines = self.run_check(root)
        self.assertEqual(code, 1)
        for v in found:
            self.assertTrue(
                any(str(album.relative_to(root)) in line and v.rule in line for line in lines),
                f"no line names {v.rule!r} for the album",
            )
        # The clean album is never mentioned.
        self.assertFalse(any("Downward Spiral" in line for line in lines))

    def test_check_writes_nothing(self):
        # The library it reads is the one foobar2000 serves. A check that
        # "helpfully" upgraded a tag or removed a .DS_Store would be a write
        # nobody approved.
        root = self.library()
        _broken_library(root)
        before = _snapshot(root)
        check.check(root)
        self.run_check(root)
        self.assertEqual(_snapshot(root), before)

    def test_an_unreadable_file_is_a_line_and_exit_1_not_a_traceback(self):
        root = self.library()
        album = builders.library_album(root, ext="mp3")
        (album / "02. Hurt.mp3").write_bytes(b"\0" * 50)
        code, lines = self.run_check(root)
        self.assertEqual(code, 1)
        self.assertTrue(any(str(album.relative_to(root)) in line and "unreadable" in line
                            and "02. Hurt.mp3" in line for line in lines), lines)

    def test_a_missing_or_non_directory_root_is_an_error_on_stderr_and_exit_2(self):
        # Exit 1 means "violations found". A typo in ROOT must not look like
        # a library with problems in it, nor like a crash.
        missing = self.tmp / "no such library"
        a_file = self.tmp / "library.txt"
        a_file.write_text("not a folder\n")
        for root in (missing, a_file):
            with self.subTest(root.name):
                out, err = io.StringIO(), io.StringIO()
                try:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        try:
                            code = main(["check", str(root)])
                        except SystemExit as exit_:
                            code = exit_.code
                except Exception as exc:  # the traceback this case exists to rule out
                    self.fail(f"check {root.name!r} raised {exc!r}")
                self.assertEqual(code, 2)
                self.assertIn(str(root), err.getvalue())
                self.assertEqual(out.getvalue(), "")


class TheAlbumState(_Library):
    def test_an_album_is_judged_from_its_state_alone(self):
        # A plan produces the same state without the files existing yet, so
        # check_album must not go back to the disk.
        root = self.library()
        album = _broken_library(root)
        expected = sorted(check.check(root))
        state = check.read_album(album, root)
        shutil.rmtree(album)
        self.assertEqual(sorted(check.check_album(state)), expected)


# --- a plan is checked the way check judges the tree ------------------------
#
# `plan.plan_album` builds the state an album will have once written, and the
# rules above judge that state before anything touches the disk. A plan that
# breaks one carries the reason, and `write.write_album` refuses it.
#
# The two modules are imported inside the cases, so the cases above keep
# running while they do not exist yet.

#: The Cover Art Archive's front for the release. 1600 x 900, so the embedded
#: copy has to shrink to 1200 px and cover.jpg must not.
FRONT = (builders.FIXTURES / "cover.jpg").read_bytes()
FRONT_URL = f"https://coverartarchive.org/release/{builders.RELEASE_ID}/1.jpg"

CURE = builders.mb_credit(builders.CURE_ID, "The Cure", "Cure, The")
NIN_ID = "1a0b0c0d-0000-4000-8000-0000000000a7"
NIN = builders.mb_credit(NIN_ID, "Nine Inch Nails", "Nine Inch Nails")


def _plan_album(*args, **kwargs):
    from musiclib.plan import plan_album

    return plan_album(*args, **kwargs)


def _write_album(*args, **kwargs):
    from musiclib.write import write_album

    return write_album(*args, **kwargs)


def _plan_refused():
    from musiclib.write import PlanRefused

    return PlanRefused


def _release(*media: list[str], title: str = "Disintegration", credit=CURE, **changes) -> dict:
    """`builders.mb_release` cut down to `media`, one list of track titles each."""
    return builders.mb_release(
        title=title, **{"artist-credit": credit},
        media=[builders.mb_medium(n, titles, credit=credit) for n, titles in enumerate(media, start=1)],
        **changes,
    )


#: The stock group's genres when a case names none. A rip carries no genre,
#: and an album that ends with none is refused, so a group with none would
#: stop every plan that is meant to go through clean.
STOCK_GENRES = {"gothic rock": 1}


def _release_group(genre_counts: dict[str, int] | None = None) -> dict:
    """The stock release's group as `mb.release_group` returns it, genres and tags included.

    `genre_counts` of `{}` is MusicBrainz with no genres at all; `None` is `STOCK_GENRES`.
    """
    counts = STOCK_GENRES if genre_counts is None else genre_counts
    return {
        "id": builders.RELEASE_GROUP_ID, "title": "Disintegration", "primary-type": "Album",
        "secondary-types": [], "first-release-date": "1989-05-02", "tags": [],
        "genres": [{"name": name, "count": count} for name, count in counts.items()],
    }


class _Services:
    """MusicBrainz and the Cover Art Archive behind one fake transport, answering by URL.

    `front=False` is the archive's 404 for a release it has nothing for.
    Anything it was not given is a 404 as well. `front_image` is the bytes
    behind the front's address.
    """

    def __init__(self, release: dict, release_group: dict, front: bool, front_image: bytes = FRONT) -> None:
        self.release = release
        self.release_group = release_group
        self.front = front
        self.front_image = front_image

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org":
            if path == f"/ws/2/release-group/{self.release_group['id']}":
                return 200, json.dumps(self.release_group).encode()
            if path == f"/ws/2/release/{self.release['id']}":
                return 200, json.dumps(self.release).encode()
            return 404, b'{"error": "Not Found"}'
        if parts.netloc == "coverartarchive.org" and self.front:
            if path == f"/release/{self.release['id']}":
                listing = {"images": [{"id": 1, "types": ["Front"], "front": True, "back": False,
                                       "image": FRONT_URL, "thumbnails": {}}]}
                return 200, json.dumps(listing).encode()
            if url == FRONT_URL:
                return 200, self.front_image
        return 404, b"Not Found"


def _rip(root: Path, *discs: list[str], where: str = "C/The Cure/Disintegration [rip]",
         ext: str = "flac", album: str = "Disintegration", date: str | None = "1989",
         disc_dirs: tuple[str, ...] | None = None, cover: bool = True,
         genre: tuple[str, ...] = ()) -> Path:
    """An album the way a rip arrives: loose names, lower-case titles, no MusicBrainz IDs.

    Each of `discs` is one medium's titles. More than one puts each medium
    in its own folder, `CDn` unless `disc_dirs` names them. The files are
    dated 1989, the original release, where the matched release is 2010: a
    plan that names the folder from the files rather than the release shows.
    `date=None` leaves the files with no DATE, and the files carry `genre`,
    none unless a case gives some. Returns the album folder.
    """
    base = root / where
    for disc, titles in enumerate(discs, start=1):
        folder = base
        if len(discs) > 1:
            folder = base / (disc_dirs[disc - 1] if disc_dirs else f"CD{disc}")
        folder.mkdir(parents=True, exist_ok=True)
        for number, title in enumerate(titles, start=1):
            path = folder / f"{number:02d} {title.lower()}.{ext}"
            shutil.copyfile(builders.FIXTURES / f"tone.{ext}", path)
            fields = {"title": [title.lower()], "artist": ["The Cure"], "album": [album]}
            if date:
                fields["date"] = [date]
            if genre:
                fields["genre"] = list(genre)
            builders.write_tags(path, builders.picard_tags(ext, fields, track=(number, len(titles)),
                                                           disc=(disc, len(discs))), v2_version=4)
    if cover:
        shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


def _names(entries) -> set[str]:
    """The file names in a plan's `deletions`, `extras` or `kept`, whatever shape each entry has.

    The seam fixes which bucket a file lands in, not whether an entry is a
    path or a `(source, destination)` pair, so only the source's name is read.
    """
    out = set()
    for entry in entries:
        if isinstance(entry, (tuple, list)):
            entry = entry[0]
        entry = getattr(entry, "source", entry)
        out.add(PurePosixPath(str(entry)).name)
    return out


class _Planning(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self._roots = 0

    def library(self) -> Path:
        """A fresh ROOT, so each subtest's album is the only one there."""
        self._roots += 1
        root = self.tmp / f"library-{self._roots}"
        root.mkdir()
        return root

    def plan(self, unit: Unit, release: dict, release_group: dict | None = None, *,
             front: bool = True, front_image: bytes = FRONT, **kwargs):
        services = _Services(release, release_group or _release_group(), front, front_image)
        # A cache of its own per plan: one shared across subtests replays the
        # last subtest's cover art to a case that has none.
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        return _plan_album(unit, release, client, art, **kwargs)

    @staticmethod
    def unit(root: Path, album: Path) -> Unit:
        return next(u for u in units(root) if u.path == album)

    def assertRefused(self, plan, reason: str, root: Path, before: dict):
        """`write_album` raises naming `reason`, and the library and extras root are as they were."""
        extras = self.tmp / "extras"
        with self.assertRaises(_plan_refused()) as raised:
            _write_album(plan, extras)
        self.assertIn(reason, str(raised.exception))
        self.assertEqual(_snapshot(root), before)
        self.assertFalse(extras.exists(), "the refused write created the extras root")


class APlan(_Planning):
    def test_a_clean_rip_plans_every_path_tag_and_image_with_no_problems(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], ["Prayers for Rain"])
        for name in ("rip.log", ".DS_Store", "Disintegration.cue", "Making of.mkv"):
            (album / name).write_bytes(b"x")
        release = _release(["Plainsong", "Pictures of You"], ["Prayers for Rain"])
        # Vote counts in the opposite order to the names, so a plan that
        # sorts by name alone shows.
        group = _release_group({"post-punk": 4, "gothic rock": 9})

        # Square and 1600 px, so it passes the cover bar and beats the
        # rip's own 1600 by 900 `cover.jpg`, which does not.
        front = builders.jpeg(1600, 1600)
        plan = self.plan(self.unit(root, album), release, group, status="auto", front_image=front)

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(Path(plan.root), root)
        self.assertEqual(str(plan.source), "C/The Cure/Disintegration [rip]")
        destination = PurePosixPath("C/Cure, The/(2010) Disintegration")
        self.assertEqual(PurePosixPath(str(plan.destination)), destination)
        self.assertEqual(plan.release_id, builders.RELEASE_ID)
        self.assertEqual(plan.status, "auto")

        source = PurePosixPath("C/The Cure/Disintegration [rip]")
        moves = {PurePosixPath(str(f.source)): PurePosixPath(str(f.destination)) for f in plan.files}
        self.assertEqual(moves, {
            source / "CD1/01 plainsong.flac": destination / "CD1/01. Plainsong.flac",
            source / "CD1/02 pictures of you.flac": destination / "CD1/02. Pictures of You.flac",
            source / "CD2/01 prayers for rain.flac": destination / "CD2/01. Prayers for Rain.flac",
        })
        first = next(f for f in plan.files if PurePosixPath(str(f.source)).name == "01 plainsong.flac")
        self.assertEqual(first.target["title"], ["Plainsong"])
        self.assertEqual(first.target["genre"], ["gothic rock", "post-punk"])

        # cover.jpg is the archive's front byte for byte, replacing the rip's
        # own; what every track embeds is that front shrunk to 1200 px.
        self.assertEqual(plan.images["cover.jpg"], front)
        self.assertEqual(Image.open(io.BytesIO(plan.embedded)).size, (1200, 1200))

        # The rip's old cover.jpg may or may not be listed as deleted once
        # the archive's replaces it, so deletions is only held to a floor.
        self.assertLessEqual({".DS_Store", "Disintegration.cue"}, _names(plan.deletions))
        self.assertEqual(_names(plan.extras), {"Making of.mkv"})
        self.assertIn("rip.log", _names(plan.kept))
        self.assertFalse({"rip.log", "Making of.mkv"} & _names(plan.deletions))

    def test_an_lrc_beside_the_tracks_is_planned_for_deletion_not_carried_along(self):
        # Carried along, it would land beside tracks whose new names it no
        # longer matches. Upper case too, since a Windows rip writes `.LRC`.
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        lrc = ("Foo Fighters - In Your Honor (CD2) - 08 - Virginia Moon.lrc",
               "01 plainsong.LRC")
        for name in lrc:
            (album / name).write_text("[00:00.00] x\n")

        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]),
                         status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertLessEqual(set(lrc), _names(plan.deletions))
        self.assertFalse(set(lrc) & (_names(plan.kept) | _names(plan.extras)))

    def test_a_plan_given_no_status_is_review(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]))
        self.assertEqual(plan.status, "review")

    def test_with_no_front_in_the_archive_the_rips_own_cover_jpg_is_kept(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        own = builders.jpeg(500, 500)
        (album / "cover.jpg").write_bytes(own)
        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]),
                         front=False, status="auto")
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(plan.images["cover.jpg"], own)
        self.assertEqual(plan.embedded, own)

    def test_a_single_medium_mp3_rip_plans_no_disc_folder_and_passes_the_id3_rules(self):
        # The state a plan is judged on has to say the MP3 will be ID3v2.4
        # with no ID3v1, since that is what the write produces. A state that
        # left the version out would fail every MP3 album on "tag format".
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], ext="mp3")
        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]), status="auto")
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(sorted(PurePosixPath(str(f.destination)) for f in plan.files), [
            PurePosixPath("C/Cure, The/(2010) Disintegration/01. Plainsong.mp3"),
            PurePosixPath("C/Cure, The/(2010) Disintegration/02. Pictures of You.mp3"),
        ])

    def test_a_suggested_disc_subtitle_holds_an_auto_album_for_review(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], ["Prayers for Rain"],
                     disc_dirs=("CD1", "CD2 - Live at Budokan"))
        release = _release(["Plainsong", "Pictures of You"], ["Prayers for Rain"])

        plan = self.plan(self.unit(root, album), release, status="auto")

        self.assertEqual(plan.status, "review")
        self.assertTrue(plan.holds)
        self.assertIn("Live at Budokan", repr(plan.suggestions))
        # A hold is not a problem: the album can still be written once a
        # person has looked, and the suggestion is never written unasked.
        self.assertEqual(list(plan.problems), [])
        for file_plan in plan.files:
            self.assertNotIn("discsubtitle", file_plan.target)


class APlanThatBreaksARule(_Planning):
    def test_carries_the_reason_and_write_album_refuses_it_touching_nothing(self):
        cases = [
            # No DATE on the release, its release group or the files, so
            # there is no year to name the album folder with.
            ("no DATE anywhere", "date", dict(date=None),
             dict(date=None, **{"release-group": {**builders.mb_release()["release-group"],
                                                  "first-release-date": ""}}), True),
            # No front in the archive and no cover.jpg to keep.
            ("no cover at all", "cover.jpg", dict(cover=False), {}, False),
            # A title the character table strips to nothing leaves a folder
            # of "(2010)" alone, which is not shaped (YYYY) Title.
            ("a title of only stripped characters", "album folder", dict(album="???"),
             dict(title="???"), True),
        ]
        for case, reason, rip, release_changes, front in cases:
            with self.subTest(case):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"], **rip)
                title = release_changes.pop("title", "Disintegration")
                release = _release(["Plainsong", "Pictures of You"], title=title, **release_changes)
                before = _snapshot(root)

                plan = self.plan(self.unit(root, album), release, front=front, status="auto")

                said = [p for p in plan.problems if reason.casefold() in p.casefold()]
                self.assertTrue(said, f"no problem names {reason!r}: {plan.problems}")
                self.assertRefused(plan, said[0], root, before)

    def test_an_album_that_needs_a_person_is_never_planned_and_is_refused(self):
        # Two albums in one folder: a single filed with the album
        # it came from. Planning either as the other's release would retag it.
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        builders.write_tags(album / "02 pictures of you.flac", {"ALBUM": "Pictures of You (single)"})
        unit = self.unit(root, album)
        self.assertEqual(unit.status, "needs a person")
        before = _snapshot(root)

        plan = self.plan(unit, _release(["Plainsong", "Pictures of You"]), status="auto")

        self.assertEqual(list(plan.files), [])
        said = [p for p in plan.problems if "needs a person" in p or unit.reason in p]
        self.assertTrue(said, f"the problems do not say why: {plan.problems}")
        self.assertRefused(plan, said[0], root, before)

    def test_an_album_with_an_unreadable_file_is_never_planned_and_is_refused(self):
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"])
        (album / "03 closedown.flac").write_bytes(b"not audio at all")
        unit = self.unit(root, album)
        self.assertTrue(unit.unreadable)
        before = _snapshot(root)

        plan = self.plan(unit, _release(["Plainsong", "Pictures of You", "Closedown"]), status="auto")

        self.assertEqual(list(plan.files), [])
        said = [p for p in plan.problems if "03 closedown.flac" in p]
        self.assertTrue(said, f"no problem names the unreadable file: {plan.problems}")
        self.assertRefused(plan, said[0], root, before)

    def test_an_off_list_genre_breaks_genre_on_disk_and_the_plan_drops_it_and_reports_no_genre(self):
        # The same files, judged twice. On disk the value is there and off the
        # list. MusicBrainz has no genres, so the plan falls back to the
        # files' genres, keeps only those on the list, and is left with none.
        root = self.library()
        album = builders.library_album(root, artist="Nine Inch Nails", album="The Fragile",
                                       date="1999-09-21", discs=(("Somewhat Damaged", "Hurt"),))
        for path in sorted(album.glob("*.flac")):
            builders.write_tags(path, {"GENRE": "made-up genre"})
        self.assertEqual({v.rule for v in check.check(root)}, {"genre"})
        release = _release(["Somewhat Damaged", "Hurt"], title="The Fragile", credit=NIN,
                           date="1999-09-21")

        plan = self.plan(self.unit(root, album), release, _release_group({}), status="auto")

        self.assertEqual({p.split(":", 1)[0].strip() for p in plan.problems}, {"no genre"},
                         f"got {plan.problems}")
        self.assertEqual([f.target["genre"] for f in plan.files if "genre" in f.target], [])


class APlanLeftWithNoGenre(_Planning):
    """Both routes through genre composition that leave a track with no genre.

    Neither rip carries a soundtrack or game genre, and the group has no
    tags or Soundtrack type, so there is no custom genre to fall back on.
    """

    def test_carries_a_no_genre_problem_and_write_album_refuses_it_touching_nothing(self):
        cases = [
            # The fallback to the files' genres applies, and none of them
            # is on the list. "Rock; Pop" is two listed genres in one value.
            ("no musicbrainz genres and only off-list file genres", {},
             ("made-up genre", "Rock; Pop")),
            # MusicBrainz's genres are all off the list, so the files get
            # their turn, and theirs are off it too.
            ("musicbrainz genres all off the list and only off-list file genres",
             {"seen live": 5, "anime": 2}, ("made-up genre",)),
        ]
        for case, group_genres, file_genres in cases:
            with self.subTest(case):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"], genre=file_genres)
                unit = self.unit(root, album)
                # The files carry what the case says, so it is their genres
                # that were judged and dropped.
                self.assertEqual(unit.tracks[0].tags.get("genre"), list(file_genres))
                release = _release(["Plainsong", "Pictures of You"])
                before = _snapshot(root)

                plan = self.plan(unit, release, _release_group(group_genres), status="auto")

                said = [p for p in plan.problems if p.split(":", 1)[0].strip() == "no genre"]
                self.assertTrue(said, f"no problem under 'no genre': {plan.problems}")
                self.assertEqual([f.target["genre"] for f in plan.files if "genre" in f.target], [])
                self.assertRefused(plan, said[0], root, before)

    def test_takes_the_files_listed_genre_when_every_musicbrainz_genre_is_off_the_list(self):
        # Off-list genres from MusicBrainz leave the album as short of a
        # genre as none at all, so the files' "gothic rock" applies. It is
        # the whole list: "seen live" and "anime" are never written.
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], genre=("gothic rock",))
        release = _release(["Plainsong", "Pictures of You"])

        plan = self.plan(self.unit(root, album), release, _release_group({"seen live": 5, "anime": 2}),
                         status="auto")

        self.assertFalse([p for p in plan.problems if p.split(":", 1)[0].strip() == "no genre"],
                         plan.problems)
        self.assertEqual([f.target.get("genre") for f in plan.files], [["gothic rock"]] * 2)


class APlanOfARipWithStraySpaces(_Planning):
    def test_carries_no_whitespace_problem_cleaning_the_composer_and_keeping_the_lyrics(self):
        # `check` and plan validation judge whitespace the same way, so a
        # plan that cleans and keeps what it keeps as written validates
        # clean.
        root = self.library()
        album = _rip(root, ["Plainsong", "Pictures of You"], ext="mp3")
        kept = {
            "USLT::eng": [LRC],
            "TXXX:LAST_PLAYED": ["2019-04-02 21:14:03 "],
            "COMM::eng": [ITUNNORM],
        }
        for path in sorted(album.glob("*.mp3")):
            builders.write_tags(path, {
                "TCOM": "Billy Squier/Danny  Kortchmar",
                "TCOP": "(C) 1989 Fiction Records ",
                "USLT": USLT(encoding=3, lang="eng", desc="", text=LRC),
                "TXXX:LAST_PLAYED": "2019-04-02 21:14:03 ",
                "COMM": _comm(ITUNNORM),
            }, v2_version=4)

        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]), status="auto")

        self.assertEqual(list(plan.problems), [])
        for file_plan in plan.files:
            self.assertEqual(file_plan.target["TCOM"], ["Billy Squier/Danny Kortchmar"])
            self.assertEqual(file_plan.target["TCOP"], ["(C) 1989 Fiction Records"])
            self.assertEqual({k: file_plan.target.get(k) for k in kept}, kept)

    def test_a_rip_whose_fmps_rating_has_a_stray_space_plans_with_no_whitespace_problem(self):
        # The plan keeps the rating as written, and plan validation must
        # agree with it, or the album can never be written.
        for ext, rating_key, tags in (("flac", "fmps_rating", {"FMPS_RATING": "0.8 "}),
                                      ("mp3", "TXXX:FMPS_RATING", {"TXXX:FMPS_RATING": "0.8 "})):
            with self.subTest(ext):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"], ext=ext)
                for path in sorted(album.glob(f"*.{ext}")):
                    builders.write_tags(path, tags, v2_version=4)

                plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]),
                                 status="auto")

                self.assertEqual([p for p in plan.problems if p.startswith("whitespace")], [])
                for file_plan in plan.files:
                    self.assertEqual(file_plan.target[rating_key], ["0.8 "])


if __name__ == "__main__":
    unittest.main()
