"""Reading a file's tags and writing them back without losing anything.

`docs/music-library.md` *Tags*:
ratings are never touched, a field nobody planned is kept (apart from the
forbidden duplicates), and an MP3 comes out as ID3v2.4 with no ID3v1.

Every case works on a copy of a tagless fixture in a temporary folder. What
the file holds afterwards is read with mutagen directly, through `builders`,
so a test never takes the engine's own word for what is on disk.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import APIC, COMM, ID3, POPM, TIT2, USLT
from mutagen.mp4 import MP4Cover
from mutagen.oggvorbis import OggVorbis

from musiclib import files, tagwrite
from tests import builders

FORMATS = ("mp3", "flac", "ogg", "m4a")

WMP = "Windows Media Player 9 Series"
COVER = (builders.FIXTURES / "cover.jpg").read_bytes()

#: The title field under each format's real key, as the snapshot names it.
TITLE = {"mp3": "TIT2", "flac": "title", "ogg": "title", "m4a": "\xa9nam"}


def _vorbis_seed() -> dict:
    # Upper case on purpose: that is how Picard and foobar2000 write Vorbis
    # keys, while the snapshot names them in lower case.
    return {
        "TITLE": "Old title",
        "ARTIST": "Nine Inch Nails",
        "ALBUM": "The Fragile",
        "ALBUMARTIST": "Nine Inch Nails",
        "DATE": "1999-09-21",
        "TRACKNUMBER": "3",
        "TRACKTOTAL": "12",
        "GENRE": ["industrial rock", "electronic"],
        "LYRICS": "one line\nand another",
        "REPLAYGAIN_TRACK_GAIN": "-6.20 dB",
    }


def seed(ext: str) -> dict:
    """A realistic set of tags for `ext`, none of them a rating or a duplicate."""
    if ext == "mp3":
        return {
            "TIT2": "Old title",
            "TPE1": "Nine Inch Nails",
            "TALB": "The Fragile",
            "TPE2": "Nine Inch Nails",
            "TRCK": "3/12",
            "TDRC": "1999-09-21",
            "TXXX:REPLAYGAIN_TRACK_GAIN": "-6.20 dB",
            "TXXX:MusicBrainz Album Id": "8b2c6d0c-0000-4000-8000-000000000001",
            "PRIV:WM/MediaClassPrimaryID": b"\xbc}\x60\xd1#\xe3\xe2K\x86\xa1H\xa4*(D\x1e",
            "COMM": COMM(encoding=3, lang="eng", desc="", text=["ripped on a Tuesday"]),
            "USLT": USLT(encoding=3, lang="eng", desc="", text="one line\nand another"),
            "APIC": APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=COVER),
        }
    if ext in ("flac", "ogg"):
        return _vorbis_seed()
    if ext == "m4a":
        return {
            "\xa9nam": "Old title",
            "\xa9ART": "Nine Inch Nails",
            "\xa9alb": "The Fragile",
            "aART": "Nine Inch Nails",
            "\xa9day": "1999-09-21",
            "trkn": [(3, 12)],
            "disk": [(1, 2)],
            "\xa9gen": ["industrial rock", "electronic"],
            "\xa9lyr": "one line\nand another",
            "covr": [MP4Cover(COVER, imageformat=MP4Cover.FORMAT_JPEG)],
            "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN": "-6.20 dB",
        }
    raise ValueError(ext)


def ratings_seed(ext: str) -> dict:
    """Every rating field the format can carry, set to something non-default."""
    if ext == "mp3":
        return {
            "POPM": POPM(email=WMP, rating=196, count=7),
            "TXXX:FMPS_Rating": "0.8",
        }
    return {"RATING": "4", "FMPS_RATING": "0.8"}


def ratings_on_disk(path: Path) -> list:
    """The ratings as mutagen reads them, in a form assertEqual can compare."""
    if path.suffix == ".mp3":
        try:
            tag = ID3(path)
        except mutagen.id3.ID3NoHeaderError:
            return []
        found = [("POPM", f.email, f.rating, getattr(f, "count", 0)) for f in tag.getall("POPM")]
        found += [("TXXX", f.desc, list(f.text)) for f in tag.getall("TXXX")
                  if f.desc.lower() == "fmps_rating"]
        return sorted(found)
    audio = FLAC(path) if path.suffix == ".flac" else OggVorbis(path)
    return sorted((k.lower(), v) for k, v in (audio.tags or [])
                  if k.lower() in ("rating", "fmps_rating"))


def on_disk(path: Path) -> dict:
    """Every tag in the file, read by mutagen, keys folded for Vorbis.

    Vorbis keys are case-insensitive, so `TITLE` rewritten as `title` is the
    same field. Everywhere else the key is compared exactly.
    """
    raw = builders.read_tags(path)
    if path.suffix in (".flac", ".ogg"):
        return {k.lower(): v for k, v in raw.items()}
    return raw


class _TempDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def file(self, ext: str, tags: dict | None = None, name: str = "track") -> Path:
        path = builders.copy_fixture(self.tmp, ext, name)
        if tags:
            builders.write_tags(path, tags)
        return path


class ReadingAFile(_TempDir):
    def test_each_format_reports_its_tag_family_and_its_length(self):
        family = {"mp3": "id3", "flac": "vorbis", "ogg": "vorbis", "m4a": "mp4"}
        for ext in FORMATS:
            with self.subTest(ext):
                path = self.file(ext)
                track = files.read(path)
                self.assertEqual(track.family, family[ext])
                self.assertEqual(track.path, str(path))
                self.assertAlmostEqual(track.length, mutagen.File(path).info.length, places=2)

    def test_tags_are_keyed_by_the_formats_own_names(self):
        # Every other part of the engine plans against these keys, so they are
        # the contract: ID3 by frame HashKey with a TXXX description's case
        # kept, Vorbis in lower case whatever the file used, MP4 by atom name.
        mp3 = files.read(self.file("mp3", {
            "TIT2": "t",
            "TXXX:encoded by": "LAME",
            "COMM": COMM(encoding=3, lang="eng", desc="", text=["c"]),
            "POPM": POPM(email=WMP, rating=196, count=7),
        }, name="a"))
        self.assertEqual(mp3.tags["TIT2"], ["t"])
        self.assertEqual(mp3.tags["TXXX:encoded by"], ["LAME"])
        self.assertIn("COMM::eng", mp3.tags)
        self.assertIn(f"POPM:{WMP}", mp3.tags)

        flac = files.read(self.file("flac", {"TITLE": "t", "Ripping Tool": "EAC"}, name="b"))
        self.assertEqual(flac.tags["title"], ["t"])
        self.assertEqual(flac.tags["ripping tool"], ["EAC"])
        self.assertNotIn("TITLE", flac.tags)

        m4a = files.read(self.file("m4a", {
            "\xa9nam": "t",
            "----:com.apple.iTunes:MusicBrainz Album Id": "id",
        }, name="c"))
        self.assertEqual(m4a.tags["\xa9nam"], ["t"])
        self.assertIn("----:com.apple.iTunes:MusicBrainz Album Id", m4a.tags)

    def test_a_picture_reads_the_same_twice_and_differently_once_it_changes(self):
        # A non-text frame is compared by digest. A digest that never varies
        # would let a replaced or damaged cover through the verify unnoticed.
        def cover(data, name):
            return self.file("mp3", {"APIC": APIC(encoding=3, mime="image/jpeg",
                                                  type=3, desc="", data=data)}, name)

        first = files.read(cover(COVER, "a")).tags["APIC:"]
        again = files.read(cover(COVER, "b")).tags["APIC:"]
        other = files.read(cover(COVER[:-1] + b"\x00", "c")).tags["APIC:"]
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_a_file_mutagen_cannot_read_raises_unreadable(self):
        for name, content in (("notes.txt", b"not audio"), ("broken.flac", b"\x00" * 512)):
            with self.subTest(name):
                path = self.tmp / name
                path.write_bytes(content)
                with self.assertRaises(files.Unreadable):
                    files.read(path)


class TheAudioFingerprint(_TempDir):
    def test_it_does_not_change_when_only_the_tags_do(self):
        for ext in FORMATS:
            with self.subTest(ext):
                path = self.file(ext)
                before = files.audio_fingerprint(files.read(path))
                builders.write_tags(path, {TITLE[ext]: "A much longer title than before"})
                self.assertEqual(files.audio_fingerprint(files.read(path)), before)

    def test_it_changes_when_a_byte_of_mp3_or_flac_audio_does(self):
        # Only MP3 and FLAC: Ogg pages and MP4 atoms are re-laid on every
        # save, so for those the engine compares the duration instead, and a
        # flipped byte in the middle of the audio does not show up in it.
        for ext in ("mp3", "flac"):
            with self.subTest(ext):
                path = self.file(ext, {TITLE[ext]: "t"})
                before = files.audio_fingerprint(files.read(path))
                data = bytearray(path.read_bytes())
                data[-1] ^= 0xFF
                path.write_bytes(bytes(data))
                self.assertNotEqual(files.audio_fingerprint(files.read(path)), before)


class ANoOpWrite(_TempDir):
    def test_writing_a_files_own_tags_back_leaves_every_tag_as_it_was(self):
        for ext in FORMATS:
            with self.subTest(ext):
                path = self.file(ext, {**seed(ext), **(ratings_seed(ext) if ext != "m4a" else {})})
                raw_before = on_disk(path)
                track = files.read(path)
                tagwrite.write(track, track.tags)
                self.assertEqual(files.read(path).tags, track.tags)
                self.assertEqual(on_disk(path), raw_before)


class Ratings(_TempDir):
    """A rating comes from listening, never from the import."""

    RATED = ("mp3", "flac", "ogg")

    def rated(self, ext: str) -> Path:
        return self.file(ext, {**seed(ext), **ratings_seed(ext)})

    def test_ratings_read_back_identical_after_a_no_op_write(self):
        for ext in self.RATED:
            with self.subTest(ext):
                path = self.rated(ext)
                before = ratings_on_disk(path)
                self.assertTrue(before, "the fixture carries no rating to protect")
                track = files.read(path)
                tagwrite.write(track, tagwrite.merge(track, {}))
                self.assertEqual(ratings_on_disk(path), before)

    def test_ratings_read_back_identical_after_a_write_that_changes_the_title(self):
        for ext in self.RATED:
            with self.subTest(ext):
                path = self.rated(ext)
                before = ratings_on_disk(path)
                track = files.read(path)
                tagwrite.write(track, tagwrite.merge(track, {TITLE[ext]: ["New title"]}))
                self.assertEqual(files.read(path).tags[TITLE[ext]], ["New title"])
                self.assertEqual(ratings_on_disk(path), before)

    def test_a_plan_that_sets_or_removes_a_rating_changes_nothing(self):
        # A plan naming a rating is a bug somewhere upstream. The write is the
        # last place it can be stopped before somebody's listening history is
        # gone, and a rating cannot be recovered from MusicBrainz.
        attempts = {
            "mp3": {f"POPM:{WMP}": None, "TXXX:FMPS_Rating": ["1.0"]},
            "flac": {"rating": ["1"], "fmps_rating": None},
            "ogg": {"rating": None, "fmps_rating": ["0.2"]},
        }
        for ext in self.RATED:
            with self.subTest(ext):
                path = self.rated(ext)
                before = ratings_on_disk(path)
                track = files.read(path)
                merged = tagwrite.merge(track, attempts[ext])
                for key in attempts[ext]:
                    self.assertEqual(merged.get(key), track.tags[key], key)
                tagwrite.write(track, merged)
                self.assertEqual(ratings_on_disk(path), before)

    def test_an_unrated_file_stays_unrated_when_the_plan_names_a_rating(self):
        # The docs: an unrated track has no rating tag at all.
        attempts = {
            "mp3": {f"POPM:{WMP}": ["rating=255,count=0"], "TXXX:FMPS_Rating": ["1.0"]},
            "flac": {"rating": ["5"], "fmps_rating": ["1.0"]},
            "ogg": {"rating": ["5"], "fmps_rating": ["1.0"]},
        }
        for ext in self.RATED:
            with self.subTest(ext):
                path = self.file(ext, seed(ext))
                track = files.read(path)
                merged = tagwrite.merge(track, attempts[ext])
                for key in attempts[ext]:
                    self.assertNotIn(key, merged)
                tagwrite.write(track, merged)
                self.assertEqual(ratings_on_disk(path), [])


class UnplannedFields(_TempDir):
    """What the engine did not plan, it keeps."""

    def test_every_field_the_plan_does_not_name_survives_a_title_change(self):
        # Lyrics, ReplayGain, comments, private frames and cover art are all
        # things the engine has no opinion on, and all things a careless
        # "write the planned tags" would drop.
        for ext in FORMATS:
            with self.subTest(ext):
                path = self.file(ext, seed(ext))
                expected = on_disk(path)
                track = files.read(path)
                returned = tagwrite.write(track, tagwrite.merge(track, {TITLE[ext]: ["New title"]}))
                after = on_disk(path)
                expected[TITLE[ext]] = after[TITLE[ext]]
                self.assertEqual(files.read(path).tags[TITLE[ext]], ["New title"])
                self.assertEqual(after, expected)
                self.assertEqual(returned.tags, files.read(path).tags)

    def test_a_field_planned_as_none_is_removed_and_nothing_else_is(self):
        gain = {"mp3": "TXXX:REPLAYGAIN_TRACK_GAIN", "flac": "replaygain_track_gain",
                "ogg": "replaygain_track_gain",
                "m4a": "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"}
        for ext in FORMATS:
            with self.subTest(ext):
                path = self.file(ext, seed(ext))
                track = files.read(path)
                expected = {k: v for k, v in track.tags.items() if k != gain[ext]}
                merged = tagwrite.merge(track, {gain[ext]: None})
                self.assertEqual(merged, expected)
                tagwrite.write(track, merged)
                self.assertEqual(files.read(path).tags, expected)


class ForbiddenDuplicates(_TempDir):
    """The second exception to keeping unplanned fields, and *No duplicate fields* in the docs.

    Each case keeps the proper field beside the duplicate, because the rule is
    "one album artist field", not "no album artist".
    """

    def check(self, ext: str, tags: dict, dropped: set, kept: set):
        path = self.file(ext, tags)
        track = files.read(path)
        self.assertLessEqual(dropped | kept, set(track.tags), "the fixture is missing a field")
        merged = tagwrite.merge(track, {})
        self.assertEqual(merged, {k: v for k, v in track.tags.items() if k not in dropped})
        tagwrite.write(track, merged)
        on_file = set(files.read(path).tags)
        self.assertFalse(dropped & on_file, "a duplicate is still in the file")
        self.assertLessEqual(kept, on_file)

    def test_mp3_drops_txxx_year_album_artist_and_totals_in_any_case(self):
        # Mixed case because taggers disagree: Mp3tag writes TOTALTRACKS,
        # foobar2000 TRACKTOTAL, and older rips carry anything.
        self.check("mp3", {
            "TPE2": "Nine Inch Nails",
            "TRCK": "3/12",
            "TPOS": "1/2",
            "TDRC": "1999",
            "TXXX:YEAR": "1999",
            "TXXX:ALBUM ARTIST": "Nine Inch Nails",
            "TXXX:TOTALTRACKS": "12",
            "TXXX:TrackTotal": "12",
            "TXXX:totaldiscs": "2",
            "TXXX:DISCTOTAL": "2",
        }, dropped={"TXXX:YEAR", "TXXX:ALBUM ARTIST", "TXXX:TOTALTRACKS",
                    "TXXX:TrackTotal", "TXXX:totaldiscs", "TXXX:DISCTOTAL"},
            kept={"TPE2", "TRCK", "TPOS", "TDRC"})

    def test_vorbis_drops_year_and_album_artist_but_keeps_its_own_totals(self):
        # TRACKTOTAL and DISCTOTAL are where Vorbis keeps totals, so they are
        # the proper field here. Only the TXXX totals on MP3 are duplicates.
        for ext in ("flac", "ogg"):
            with self.subTest(ext):
                self.check(ext, {
                    "ALBUMARTIST": "Nine Inch Nails",
                    "DATE": "1999",
                    "TRACKTOTAL": "12",
                    "DISCTOTAL": "2",
                    "YEAR": "1999",
                    "ALBUM ARTIST": "Nine Inch Nails",
                }, dropped={"year", "album artist"},
                    kept={"albumartist", "date", "tracktotal", "disctotal"})

    def test_mp4_drops_freeform_year_and_album_artist(self):
        self.check("m4a", {
            "aART": "Nine Inch Nails",
            "\xa9day": "1999",
            "----:com.apple.iTunes:YEAR": "1999",
            "----:com.apple.iTunes:ALBUM ARTIST": "Nine Inch Nails",
        }, dropped={"----:com.apple.iTunes:YEAR", "----:com.apple.iTunes:ALBUM ARTIST"},
            kept={"aART", "\xa9day"})


class Id3Version(_TempDir):
    def test_an_mp3_written_is_id3v24_with_no_id3v1_trailer(self):
        path = self.file("mp3", seed("mp3"))
        builders.add_id3v1(path)
        self.assertEqual(path.read_bytes()[-128:][:3], b"TAG", "the fixture has no ID3v1")
        self.assertEqual(ID3(path).version[:2], (2, 3), "the fixture is not ID3v2.3")

        track = files.read(path)
        tagwrite.write(track, tagwrite.merge(track, {"TIT2": ["New title"]}))

        self.assertEqual(ID3(path).version[:2], (2, 4))
        self.assertNotEqual(path.read_bytes()[-128:][:3], b"TAG")


class VerifiedWrite(_TempDir):
    """A write reads the file back and refuses to leave it half-done.

    The failures are injected at mutagen's own save, which every route to
    disk goes through, so these do not depend on how the write is built. Each
    tampers only with the first save: the restore saves too, and has to work.
    """

    def tamper_first_save(self, cls, before=None, after=None):
        original = cls.save
        calls = []

        def save(obj, *args, **kwargs):
            first = not calls
            calls.append(1)
            if first and before:
                before(obj)
            result = original(obj, *args, **kwargs)
            if first and after:
                after(obj, args, kwargs)
            return result

        self.addCleanup(lambda: self.assertTrue(calls, "the write never saved through mutagen"))
        return mock.patch.object(cls, "save", save)

    def test_tags_that_read_back_wrong_raise_and_the_prior_tags_are_restored(self):
        def mp3(tags):
            tags.setall("TIT2", [TIT2(encoding=3, text=["tampered"])])

        def vorbis(audio):
            audio["title"] = ["tampered"]

        cases = (("mp3", ID3, mp3), ("flac", FLAC, vorbis), ("ogg", OggVorbis, vorbis))
        for ext, cls, spoil in cases:
            with self.subTest(ext):
                path = self.file(ext, {**seed(ext), **ratings_seed(ext)})
                before = on_disk(path)
                track = files.read(path)
                target = tagwrite.merge(track, {TITLE[ext]: ["New title"]})
                with self.tamper_first_save(cls, before=spoil):
                    with self.assertRaises(tagwrite.VerifyError):
                        tagwrite.write(track, target)
                self.assertEqual(on_disk(path), before)

    def test_audio_that_changed_during_the_save_raises(self):
        path = self.file("mp3", seed("mp3"))
        before = on_disk(path)
        track = files.read(path)
        target = tagwrite.merge(track, {"TIT2": ["New title"]})

        def flip_last_byte(_tags, _args, _kwargs):
            with open(path, "r+b") as handle:
                handle.seek(-1, 2)
                last = handle.read(1)
                handle.seek(-1, 2)
                handle.write(bytes([last[0] ^ 0xFF]))

        with self.tamper_first_save(ID3, after=flip_last_byte):
            with self.assertRaises(tagwrite.VerifyError):
                tagwrite.write(track, target)
        self.assertEqual(on_disk(path), before)


if __name__ == "__main__":
    unittest.main()
