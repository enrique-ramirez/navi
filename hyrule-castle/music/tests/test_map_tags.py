"""From a MusicBrainz release to one file's tags.

`docs/music-library.md` *Tags*: exactly the fields listed there, under the
names Picard writes for each format; the file's own value where MusicBrainz
has none; `DATE` and `ORIGINALDATE` as MusicBrainz gives them; a medium's
title in the disc subtitle and never in the album.

`plan_tags` never touches the disk, but what it plans has to match what a
real file would read back as. So every expected value is written by Picard's
names into a copy of a fixture with mutagen (`builders.picard_tags`) and read
back through `files.read`, and the plan is compared against that. A test
never spells out how `Track.tags` renders an MP4 freeform atom or an MP3
`UFID`.
"""

from __future__ import annotations

import itertools
import tempfile
import unicodedata
import unittest

from mutagen.id3 import COMM, SYLT, TCOM, USLT

from musiclib import files, genres, mapping
from tests import builders
from tests.test_check import _Planning, _release, _rip

FORMATS = ("mp3", "flac", "ogg", "m4a")

#: Composed elsewhere and passed in. Not in alphabetical order,
#: so a plan that sorts them shows.
GENRES = ["post-punk", "gothic rock"]

RSQUO, ELLIPSIS, EN_DASH = chr(0x2019), chr(0x2026), chr(0x2013)

_TMP: tempfile.TemporaryDirectory | None = None
_NAMES = itertools.count()


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    _TMP.cleanup()


def on_file(ext: str, tags: dict | None = None) -> files.Track:
    """A fresh copy of the `ext` fixture carrying `tags` (real keys), as the engine reads it."""
    path = builders.copy_fixture(_TMP.name, ext, f"t{next(_NAMES)}")
    if tags:
        builders.write_tags(path, tags, v2_version=4)
    return files.read(path)


def read_back(ext: str, fields: dict, **numbers) -> dict:
    """What a file tagged with `fields` the way Picard does reads back as."""
    return on_file(ext, builders.picard_tags(ext, fields, **numbers)).tags


def key(ext: str, field: str) -> str:
    return builders.picard_key(ext, field)


def plan(track, release=None, medium=2, position=3, genres=GENRES, disc_folder=None):
    release = release if release is not None else builders.mb_release()
    return mapping.plan_tags(track, release, medium, position, list(genres), disc_folder=disc_folder)


def stock(release: dict, medium: int, position: int, artist=("Robert Smith", "Smith, Robert",
                                                             builders.SMITH_ID)) -> dict:
    """Every field `plan_tags` plans for one track of `mb_release()`, apart from the disc subtitle."""
    track = release["media"][medium - 1]["tracks"][position - 1]
    name, sort, artist_id = artist
    return {
        "title": [track["title"]],
        "artist": [name],
        "album": ["Disintegration"],
        "albumartist": ["The Cure"],
        "date": ["2010-05-24"],
        "originaldate": ["1989-05-02"],
        "artistsort": [sort],
        "albumartistsort": ["Cure, The"],
        "genre": list(GENRES),
        "release id": [builders.RELEASE_ID],
        "release group id": [builders.RELEASE_GROUP_ID],
        "recording id": [track["recording"]["id"]],
        "release track id": [track["id"]],
        "artist id": [artist_id],
        "album artist id": [builders.CURE_ID],
        "label": ["Fiction Records"],
        "catalognumber": ["FIXH 14"],
        "barcode": ["600753279578"],
        "asin": ["B003FMTHVS"],
        "releasecountry": ["GB"],
        "media": [release["media"][medium - 1]["format"]],
    }


def for_format(ext: str, fields: dict) -> dict:
    """`fields` less the ones Picard has no name for in `ext`."""
    return {f: v for f, v in fields.items() if builders.picard_key(ext, f) is not None}


class TestCase(unittest.TestCase):
    def assertPlanned(self, ext: str, target: dict, expected: dict) -> None:
        """`target` holds exactly `expected`, and nothing else.

        Picard has no MP4 name for the original date, and the spec does not
        say what an M4A gets instead. One extra key is let through on M4A
        only if it holds the release group's first release date, so the
        test neither demands nor forbids it.
        """
        extra = set(target) - set(expected)
        if ext == "m4a" and len(extra) == 1:
            (k,) = extra
            if any("1989-05-02" in v for v in target[k]):
                target = {x: v for x, v in target.items() if x != k}
        self.assertEqual(target, expected)


class PlannedFields(TestCase):
    def test_a_release_lands_under_each_formats_picard_keys_and_nothing_else(self):
        # A tagless file, so everything in the target came from the plan.
        release = builders.mb_release()
        fields = stock(release, 2, 3)
        for ext in FORMATS:
            with self.subTest(ext):
                result = plan(on_file(ext), release)
                expected = read_back(ext, for_format(ext, fields), track=(3, 4), disc=(2, 3))
                self.assertPlanned(ext, result.target, expected)
                self.assertEqual(list(result.problems), [])
                self.assertEqual(list(result.holds), [])
                self.assertIsNone(result.suggested_discsubtitle)

    def test_musicbrainz_values_replace_the_values_the_file_already_had(self):
        # The file was tagged for another edition. Keeping the file's value
        # is only for fields MusicBrainz has nothing for, and
        # a plan that got that the wrong way round would pass the tagless
        # case above.
        release = builders.mb_release()
        fields = {**stock(release, 3, 2, artist=("The Cure", "Cure, The", builders.CURE_ID)),
                  "discsubtitle": ["Entreat Plus"]}
        stale = {f: ["stale " + f] for f in fields}
        stale.update(date=["1989"], originaldate=["1988"], genre=["rock"])
        for ext in FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, for_format(ext, stale),
                                                          track=(9, 12), disc=(1, 1)))
                result = plan(track, release, medium=3, position=2)
                expected = read_back(ext, for_format(ext, fields), track=(2, 2), disc=(3, 3))
                self.assertPlanned(ext, result.target, expected)

    def test_a_wma_track_lands_under_picards_asf_names_and_nothing_else(self):
        # A tagless file, so everything in the target came from the plan.
        release = builders.mb_release()
        result = plan(on_file("wma"), release)
        expected = read_back("wma", stock(release, 2, 3), track=(3, 4), disc=(2, 3))
        target = dict(result.target)
        # Picard has no ASF name for the track total, and the spec does not
        # say what a WMA gets instead. One extra key is let through only if
        # it holds the total, so the test neither demands nor forbids it.
        extra = set(target) - set(expected)
        if len(extra) == 1 and target[next(iter(extra))] in (["4"], ["3/4"]):
            del target[extra.pop()]
        self.assertEqual(target, expected)
        self.assertEqual(list(result.problems), [])

    def test_labels_and_catalogue_numbers_come_out_as_separate_values_in_musicbrainz_order(self):
        # Polydor comes before Fiction on MusicBrainz and after it
        # alphabetically, and the same holds for the catalogue numbers, so a
        # plan that sorts or dedupes into a set shows here.
        release = builders.mb_release(**{"label-info": [
            {"catalog-number": "POLH 14", "label": {"id": "4d0e0f10-0000-4000-8000-0000000000b2",
                                                    "name": "Polydor"}},
            {"catalog-number": "FIXH 14", "label": {"id": "4d0e0f10-0000-4000-8000-0000000000b1",
                                                    "name": "Fiction Records"}},
        ]})
        for ext in FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext), release).target
                expected = read_back(ext, {"label": ["Polydor", "Fiction Records"],
                                           "catalognumber": ["POLH 14", "FIXH 14"]})
                self.assertEqual(target[key(ext, "label")], expected[key(ext, "label")])
                self.assertEqual(target[key(ext, "catalognumber")], expected[key(ext, "catalognumber")])


class Dates(TestCase):
    """Criteria 13 and 14."""

    def test_date_is_the_release_date_at_whatever_precision_musicbrainz_gives(self):
        for date in ("2010", "2010-05", "2010-05-24"):
            for ext in FORMATS:
                with self.subTest(ext=ext, date=date):
                    track = on_file(ext, builders.picard_tags(ext, {"date": ["1989"]}))
                    target = plan(track, builders.mb_release(date=date)).target
                    self.assertEqual(target[key(ext, "date")], [date])

    def test_no_year_tag_comes_out_even_when_the_file_had_one(self):
        year = {"mp3": "TXXX:YEAR", "flac": "YEAR", "ogg": "YEAR", "m4a": "----:com.apple.iTunes:YEAR"}
        for ext in FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext, {year[ext]: "1989"})).target
                self.assertEqual([k for k in target if k.rsplit(":", 1)[-1].lower() == "year"], [])

    def test_a_release_without_a_date_keeps_the_files_date(self):
        # MusicBrainz gives an unknown date as "" or leaves it null.
        for missing in ("", None):
            for ext in FORMATS:
                with self.subTest(ext=ext, date=missing):
                    track = on_file(ext, builders.picard_tags(ext, {"date": ["1989-05-02"]}))
                    result = plan(track, builders.mb_release(date=missing))
                    self.assertEqual(result.target[key(ext, "date")], ["1989-05-02"])
                    self.assertEqual(list(result.problems), [])

    def test_with_no_date_on_the_release_or_the_file_the_plan_fails_validation(self):
        # The album folder is named after the year, so there is nothing to
        # name it with. The release group has no first date either, which
        # would otherwise date an undated release.
        for missing in ("", None):
            for ext in FORMATS:
                with self.subTest(ext=ext, date=missing):
                    release = builders.mb_release(date=missing)
                    release["release-group"]["first-release-date"] = ""
                    result = plan(on_file(ext), release)
                    self.assertNotIn(key(ext, "date"), result.target)
                    self.assertTrue(result.problems)
                    self.assertIn("date", " ".join(map(str, result.problems)).lower())

    def test_a_release_group_without_a_first_release_date_keeps_the_files_originaldate(self):
        # Picard has no MP4 name for the original date, so M4A is not here.
        for ext in ("mp3", "flac", "ogg"):
            with self.subTest(ext):
                release = builders.mb_release()
                release["release-group"]["first-release-date"] = ""
                track = on_file(ext, builders.picard_tags(ext, {"originaldate": ["1989-05-02"]}))
                self.assertEqual(plan(track, release).target[key(ext, "originaldate")], ["1989-05-02"])
                # And with nothing on the file either, nothing is planned,
                # not an empty value.
                self.assertNotIn(key(ext, "originaldate"), plan(on_file(ext), release).target)


class Genre(TestCase):
    """The list comes from `genres.compose`, as `plan` builds it, because what
    the file keeps depends on whether MusicBrainz had genres at all, and
    only `compose` is told that.
    """

    def test_with_no_musicbrainz_genres_only_the_files_genres_on_the_list_are_planned_lowercased(self):
        on_disk = ["Dark Wave", "made-up genre", "coldwave"]
        for ext in FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, {"genre": on_disk}))
                composed = genres.compose(None, [], on_disk)
                target = plan(track, genres=composed).target
                expected = read_back(ext, {"genre": ["dark wave", "coldwave"]})
                self.assertEqual(target[key(ext, "genre")], expected[key(ext, "genre")])

    def test_musicbrainz_genres_all_off_the_list_leave_the_custom_genre_and_never_the_files(self):
        # MusicBrainz has genres here, just none on the official list, so
        # the fallback to the file's genres does not apply. An
        # empty composed list looks the same as "MusicBrainz had nothing",
        # which is how the file's Darkwave slips back in.
        off_list = [{"name": "seen live", "count": 3}, {"name": "anime", "count": 1}]
        for custom, expected in ((None, []), ("soundtrack", ["soundtrack"])):
            for ext in FORMATS:
                with self.subTest(ext, custom=custom):
                    track = on_file(ext, builders.picard_tags(ext, {"genre": ["Darkwave"]}))
                    composed = genres.compose(custom, off_list, ["Darkwave"])
                    target = plan(track, genres=composed).target
                    self.assertEqual(target.get(key(ext, "genre")) or [], expected)


class DiscSubtitles(TestCase):
    """*Discs* in the docs."""

    def test_a_medium_title_goes_to_the_disc_subtitle_and_nowhere_else(self):
        for ext in FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext), medium=3, position=1).target
                expected = read_back(ext, {"discsubtitle": ["Entreat Plus"], "album": ["Disintegration"]})
                self.assertEqual(target[key(ext, "discsubtitle")], expected[key(ext, "discsubtitle")])
                self.assertEqual(target[key(ext, "album")], expected[key(ext, "album")])
                # "Disintegration (Entreat Plus)" in the album, or the title,
                # is what the rule forbids.
                elsewhere = [k for k, v in target.items()
                             if k != key(ext, "discsubtitle") and any("Entreat" in x for x in v)]
                self.assertEqual(elsewhere, [])

    def test_a_files_own_disc_subtitle_is_kept_when_musicbrainz_has_none(self):
        for ext in FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, {"discsubtitle": ["Rarities 1987-1989"]}))
                result = plan(track, medium=2, position=1, disc_folder="CD2 - Live at Budokan")
                self.assertEqual(result.target[key(ext, "discsubtitle")],
                                 track.tags[key(ext, "discsubtitle")])
                # The file already has one, so the folder name is not offered.
                self.assertIsNone(result.suggested_discsubtitle)
                self.assertEqual(list(result.holds), [])

    def test_a_descriptive_disc_folder_is_suggested_and_holds_the_album_for_review(self):
        # The folder is the only record of the disc's title, and nobody has
        # confirmed it is one, so the album cannot go through as certain or
        # auto. Whether the suggestion keeps the "CD2 - " is not settled by
        # the spec, so only the descriptive part is asserted.
        result = plan(on_file("mp3"), medium=2, position=1, disc_folder="CD2 - Live at Budokan")
        self.assertIsNotNone(result.suggested_discsubtitle)
        self.assertIn("Live at Budokan", result.suggested_discsubtitle)
        self.assertTrue(result.holds)
        self.assertEqual(list(result.problems), [])

    def test_a_folder_that_only_numbers_the_disc_is_not_suggested(self):
        for folder in (None, "CD2", "CD 2", "cd2", "Disc 2", "disc2", "Disk 2", "Bonus",
                       "Bonus Disc", "bonus cd"):
            with self.subTest(folder=folder):
                result = plan(on_file("mp3"), medium=2, position=1, disc_folder=folder)
                self.assertIsNone(result.suggested_discsubtitle)
                self.assertEqual(list(result.holds), [])
                self.assertNotIn("TSST", result.target)

    def test_a_musicbrainz_medium_title_wins_over_a_descriptive_folder(self):
        result = plan(on_file("mp3"), medium=3, position=1, disc_folder="CD3 - Live at Budokan")
        self.assertEqual(result.target["TSST"], ["Entreat Plus"])
        self.assertIsNone(result.suggested_discsubtitle)
        self.assertEqual(list(result.holds), [])


class Typography(TestCase):
    """Where the values come from MusicBrainz."""

    def test_curly_punctuation_comes_out_plain_in_the_name_fields_and_nowhere_else(self):
        release = builders.mb_release(title="Disintegration" + ELLIPSIS)
        release["media"][2]["title"] = "Entreat " + EN_DASH + " Plus"
        release["media"][2]["tracks"][0]["title"] = "Robert" + RSQUO + "s Lament"
        # Label is not a name field, so its apostrophe stays curly.
        release["label-info"][0]["label"]["name"] = "Fiction" + RSQUO + "s Records"
        for ext in FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext), release, medium=3, position=1).target
                expected = read_back(ext, {"title": ["Robert's Lament"],
                                           "album": ["Disintegration..."],
                                           "discsubtitle": ["Entreat - Plus"],
                                           "label": ["Fiction" + RSQUO + "s Records"]})
                for field in ("title", "album", "discsubtitle", "label"):
                    self.assertEqual(target[key(ext, field)], expected[key(ext, field)], field)


ALL_FORMATS = FORMATS + ("wma",)
ITUNES = "----:com.apple.iTunes:"

#: LRC lyrics from a Windows ripper: CRLF, a trailing space on some lines.
LRC = "[00:12.34]I hurt myself today \r\n[00:17.02]To see if I still feel  \r\n"
#: iTunes normalisation and gapless data, as iTunes writes it into a plain comment.
ITUNNORM = (" 00001539 000016E0 0000A7B6 0000C0DE 0002A1F3 0002A1F3 00007FFF 00007FFF"
            " 00017B5A 00017B5A")
ITUNSMPB = " 00000000 00000210 000007F4 0000000000A4E2BC 00000000 005A8B1C 00000000 00000000"

COMPOSER = {"mp3": "TCOM", "flac": "composer", "ogg": "composer", "m4a": "\xa9wrt", "wma": "WM/Composer"}
COPYRIGHT = {"mp3": "TCOP", "flac": "copyright", "ogg": "copyright", "m4a": "cprt", "wma": "Copyright"}
COMMENT = {"mp3": "COMM::eng", "flac": "comment", "ogg": "comment", "m4a": "\xa9cmt"}
LYRICS = {"mp3": "USLT::eng", "flac": "lyrics", "ogg": "lyrics", "m4a": "\xa9lyr", "wma": "WM/Lyrics"}


def _vorbis_kept() -> dict:
    return {
        "unsynced lyrics": LRC, "unsyncedlyrics": LRC, "unsynchronised lyrics": LRC,
        "unsynchronized lyrics": LRC, "lyrics": " la  la",
        "first_played": "2011-07-19 20:01:44 ", "last_played": "2019-04-02 21:14:03 ",
        "play_count": " 3", "play_counter": "12 ", "play_stamp": "2019-04-02  21:14:03",
        "added": "2012-01-01 10:00:00 ",
        "major_brand": "M4A ", "minor_version": " 512", "compatible_brands": "M4A  mp42isom",
        "comment": ITUNNORM,
    }


def kept_as_written(ext: str) -> dict:
    """Every kind of kept-as-written field `ext` can carry, each with stray spaces, as written."""
    if ext == "mp3":
        return {
            "USLT": USLT(encoding=3, lang="eng", desc="", text=LRC),
            "SYLT": SYLT(encoding=3, lang="eng", format=2, type=1, desc="",
                         text=[("I hurt  myself today ", 12340), (" To see if I still feel", 17020)]),
            "TXXX:LYRICS": "la  la ", "TXXX:UNSYNCED LYRICS": LRC,
            "TXXX:first_played": "2011-07-19 20:01:44 ", "TXXX:LAST_PLAYED": "2019-04-02 21:14:03 ",
            "TXXX:PLAY_COUNT": " 3", "TXXX:Play_Counter": "12 ", "TXXX:PLAY_STAMP": "2019-04-02  21:14:03",
            "TXXX:ADDED": "2012-01-01 10:00:00 ",
            "TXXX:major_brand": "M4A ", "TXXX:minor_version": " 512", "TXXX:compatible_brands": "M4A  mp42isom",
            "COMM": COMM(encoding=3, lang="eng", desc="", text=[ITUNNORM]),
        }
    if ext in ("flac", "ogg"):
        return _vorbis_kept()
    if ext == "m4a":
        return {
            "\xa9lyr": "la  la ", ITUNES + "UNSYNCED LYRICS": LRC,
            ITUNES + "LAST_PLAYED": "2019-04-02 21:14:03 ", ITUNES + "play_count": " 3",
            ITUNES + "major_brand": "M4A ", ITUNES + "compatible_brands": "M4A  mp42isom",
            "\xa9cmt": ITUNSMPB,
        }
    return {"WM/Lyrics": LRC, "UNSYNCED LYRICS": "la  la ", "LAST_PLAYED": "2019-04-02 21:14:03 ",
            "PLAY_COUNT": " 3", "minor_version": " 512"}


def composer(ext: str, values: list[str]) -> dict:
    """`values` as the composer field of `ext`, several values in one field."""
    if ext == "mp3":
        return {"TCOM": TCOM(encoding=3, text=list(values))}
    return {COMPOSER[ext]: list(values)}


class Whitespace(TestCase):
    """What the plan cleans and what it keeps as written."""

    def test_single_line_values_are_trimmed_and_their_runs_of_spaces_collapsed_planned_or_not(self):
        # The composer and copyright are not planned, the title is, and the
        # clean reaches both. The title's triple space shows a clean that
        # swaps one pair of spaces and stops.
        release = builders.mb_release()
        release["media"][1]["tracks"][2]["title"] = " Mr.   Self  Destruct "
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                track = on_file(ext, {COMPOSER[ext]: "Trent  Reznor",
                                      COPYRIGHT[ext]: "(C) 1994 Nothing Records "})
                target = plan(track, release).target
                self.assertEqual(target[COMPOSER[ext]], ["Trent Reznor"])
                self.assertEqual(target[COPYRIGHT[ext]], ["(C) 1994 Nothing Records"])
                self.assertEqual(target[key(ext, "title")], ["Mr. Self Destruct"])
                # What plan validation would call `whitespace`: none of it
                # is left anywhere in the target.
                stray = {k: v for k, values in target.items() for v in values
                         if "\n" not in v and (v != v.strip() or "  " in v)}
                self.assertEqual(stray, {})

    def test_a_value_cleaned_to_nothing_is_dropped_and_a_field_left_with_none_is_removed(self):
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext, composer(ext, ["  "]))).target
                self.assertNotIn(COMPOSER[ext], target)
                target = plan(on_file(ext, composer(ext, ["Billy Squier/Danny  Kortchmar", "  "]))).target
                self.assertEqual(target[COMPOSER[ext]], ["Billy Squier/Danny Kortchmar"])

    def test_every_field_kept_as_written_comes_out_byte_for_byte(self):
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                track = on_file(ext, kept_as_written(ext))
                # The file carries nothing else, so every key it reads back
                # with is one of the kept-as-written fields.
                before = dict(track.tags)
                self.assertEqual(len(before), len(kept_as_written(ext)))
                target = plan(track).target
                self.assertEqual({k: target.get(k) for k in before}, before)

    def test_a_value_holding_a_line_break_is_kept_as_it_is(self):
        # Neither lyrics nor machine data, so only the line break keeps it.
        liner = "Recorded at Abbey Road.  \r\nMixed by  Alan Moulder "
        for ext in FORMATS:
            with self.subTest(ext):
                tags = ({"COMM": COMM(encoding=3, lang="eng", desc="", text=[liner])} if ext == "mp3"
                        else {COMMENT[ext]: liner})
                target = plan(on_file(ext, tags)).target
                self.assertEqual(target[COMMENT[ext]], [liner])

    def test_a_rating_is_never_cleaned(self):
        # A plan that changes a rating is refused at write time, so a clean
        # that reaches one stops the whole album.
        for ext, rating_key, value in (("flac", "rating", " 4 "), ("ogg", "fmps_rating", "0.8 "),
                                       ("mp3", "TXXX:FMPS_RATING", "0.8 ")):
            with self.subTest(ext):
                target = plan(on_file(ext, {rating_key: value})).target
                self.assertEqual(target[rating_key], [value])

    def test_a_value_that_is_residue_once_cleaned_is_removed_and_recorded(self):
        # " Track 3" passes the residue patterns, which are anchored, and
        # "Track 3" does not. Cleaning after `residue.strip` and stopping
        # there writes a denylisted value, and validating the plan then
        # finds it and refuses the album.
        for ext in FORMATS:
            with self.subTest(ext):
                tags = ({"COMM": COMM(encoding=3, lang="eng", desc="", text=[" Track 3"])} if ext == "mp3"
                        else {COMMENT[ext]: " Track 3"})
                result = plan(on_file(ext, tags))
                self.assertNotIn(COMMENT[ext], result.target)
                self.assertIn((COMMENT[ext], "track number"), [(r.key, r.rule) for r in result.removals])

    def test_a_blank_comment_is_still_recorded_as_residue_blank(self):
        # Cleaning before `residue.strip` empties the value first, and it
        # vanishes with no record of why.
        for ext in FORMATS:
            with self.subTest(ext):
                tags = ({"COMM": COMM(encoding=3, lang="eng", desc="", text=["  "])} if ext == "mp3"
                        else {COMMENT[ext]: "  "})
                result = plan(on_file(ext, tags))
                self.assertNotIn(COMMENT[ext], result.target)
                self.assertIn((COMMENT[ext], "  ", "blank"), [tuple(r) for r in result.removals])

    def test_a_blank_lyrics_value_is_removed_under_blank_and_recorded(self):
        blanks = {"mp3": " ", "flac": "", "ogg": "", "m4a": "\r\n", "wma": " "}
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                blank = blanks[ext]
                tags = ({"USLT": USLT(encoding=3, lang="eng", desc="", text=blank)} if ext == "mp3"
                        else {LYRICS[ext]: blank})
                track = on_file(ext, tags)
                self.assertEqual(track.tags[LYRICS[ext]], [blank])
                result = plan(track)
                self.assertNotIn(LYRICS[ext], result.target)
                self.assertIn((LYRICS[ext], blank, "blank"), [tuple(r) for r in result.removals])


def nfd(text: str) -> str:
    """`text` decomposed, an accent as its own combining code point, the way some MusicBrainz data arrives."""
    return unicodedata.normalize("NFD", text)


def shown(value):
    """`value` with every non-ASCII character escaped, so a failure shows `e\\u0301` against `\\xe9`.

    The two render the same, and a diff of the raw strings reads as equal.
    """
    return ascii(value)


#: Composed, as the plan must write them. `nfd` of each is what the tests
#: feed in, so every one of these has a character that decomposes.
CAFE, BJORK, DEBRIS = "Caf\u00e9", "Bj\u00f6rk", "D\u00e9bris"
TACVBA = "Caf\u00e9 Tacvba"
MUSICA, MU_14, ENTREE = "M\u00fasica Records", "M\u00dc 14", "Entr\u00e9e Plus"
MPB = "m\u00fasica popular brasileira"
#: Already NFC but not NFKC: NFKC would turn the numeral into "II".
ROMAN_TWO = chr(0x2161)


class UnicodeNormalisation(TestCase):
    """Criteria 23 and 28: what the plan writes is NFC, and what it leaves alone is left alone."""

    @staticmethod
    def decomposed_release() -> dict:
        """`mb_release()` with a decomposed accent in every text field `plan_tags` takes from it.

        Disc 3 track 1, so the medium title fills the disc subtitle. Its
        track credit differs from the release credit, so a plan that
        normalises one credit and not the other shows.
        """
        release = builders.mb_release(title=nfd(DEBRIS))
        release["artist-credit"] = builders.mb_credit(builders.CURE_ID, nfd(TACVBA), nfd(TACVBA))
        release["label-info"] = [{"catalog-number": nfd(MU_14),
                                  "label": {"id": "4d0e0f10-0000-4000-8000-0000000000b1",
                                            "name": nfd(MUSICA)}}]
        medium = release["media"][2]
        medium["title"] = nfd(ENTREE)
        medium["tracks"][0]["title"] = nfd(CAFE)
        medium["tracks"][0]["artist-credit"] = builders.mb_credit(builders.SMITH_ID, nfd(BJORK), nfd(BJORK))
        return release

    def test_a_decomposed_accent_from_musicbrainz_is_planned_as_one_code_point_in_every_field(self):
        # `e` + U+0301 and U+00E9 render the same, so nobody sees the
        # difference until a search typed with the composed accent misses
        # the file. The genre list is handed in by `genres.compose` rather
        # than read off the release, and is held to the same rule.
        composed = {"title": [CAFE], "artist": [BJORK], "artistsort": [BJORK], "album": [DEBRIS],
                    "albumartist": [TACVBA], "albumartistsort": [TACVBA], "label": [MUSICA],
                    "catalognumber": [MU_14], "discsubtitle": [ENTREE], "genre": [MPB, "gothic rock"]}
        release = self.decomposed_release()
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                target = plan(on_file(ext), release, medium=3, position=1,
                              genres=[nfd(MPB), "gothic rock"]).target
                expected = read_back(ext, composed)
                for field in composed:
                    self.assertEqual(shown(target[key(ext, field)]), shown(expected[key(ext, field)]), field)

    def test_a_files_own_disc_subtitle_kept_where_musicbrainz_has_none_is_planned_nfc(self):
        # The plan writes this value, so it is held to the same rule as
        # one from MusicBrainz even though it came from the file.
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, {"discsubtitle": [nfd(ENTREE)]}))
                self.assertEqual(shown(track.tags[key(ext, "discsubtitle")]), shown([nfd(ENTREE)]))
                target = plan(track, medium=2, position=1).target
                self.assertEqual(shown(target[key(ext, "discsubtitle")]), shown([ENTREE]))

    def test_a_decomposed_comment_or_lyrics_the_plan_does_not_set_is_kept_decomposed(self):
        # Normalising the whole merged target would pass the cases above
        # and quietly rewrite text the plan never set, which 001 keeps as
        # written. WMA has no comment field under `COMMENT`, so it is
        # checked on lyrics alone.
        liner = nfd("Enregistr\u00e9 au Studio Guillaume Tell")
        lyric = nfd("[00:12.34]Caf\u00e9 au lait\r\n")
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                if ext == "mp3":
                    tags = {"COMM": COMM(encoding=3, lang="eng", desc="", text=[liner]),
                            "USLT": USLT(encoding=3, lang="eng", desc="", text=lyric)}
                else:
                    tags = {LYRICS[ext]: lyric}
                    if ext in COMMENT:
                        tags[COMMENT[ext]] = liner
                track = on_file(ext, tags)
                before = {k: track.tags[k] for k in (COMMENT.get(ext), LYRICS[ext]) if k}
                self.assertIn(lyric, before[LYRICS[ext]])
                target = plan(track, self.decomposed_release(), medium=3, position=1).target
                self.assertEqual(shown({k: target.get(k) for k in before}), shown(before))

    def test_replanning_a_file_already_written_nfc_proposes_no_change_to_its_text(self):
        # Criterion 28. The file was written by this engine, so it holds
        # the composed text, while MusicBrainz still gives it decomposed.
        # A plan that passes MusicBrainz's form through proposes rewriting
        # every accented field on every run. The roman numeral is NFC
        # already, and must survive too: NFKC would make it "II".
        release = self.decomposed_release()
        release["media"][2]["tracks"][0]["title"] = nfd(CAFE) + " " + ROMAN_TWO
        written = {"title": [CAFE + " " + ROMAN_TWO], "artist": [BJORK], "album": [DEBRIS],
                   "albumartist": [TACVBA], "label": [MUSICA], "discsubtitle": [ENTREE]}
        for ext in ALL_FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, written))
                target = plan(track, release, medium=3, position=1).target
                for field in written:
                    self.assertEqual(shown(target[key(ext, field)]), shown(track.tags[key(ext, field)]), field)


class UnicodeNormalisedNames(_Planning):
    """Criterion 23 reaching the destination: the folder and file names come from the same text as the tags."""

    def test_a_decomposed_artist_album_and_title_give_nfc_folder_and_file_names(self):
        # A decomposed name next to a composed one is two different folders
        # on ext4 that look like one in every file manager, and the second
        # album by the artist lands in the one nobody expected.
        credit = builders.mb_credit(builders.CURE_ID, nfd(TACVBA), nfd(TACVBA))
        root = self.library()
        album = _rip(root, ["Plainsong"])
        release = _release([nfd(CAFE)], title=nfd(DEBRIS), credit=credit)

        result = self.plan(self.unit(root, album), release, status="auto")

        self.assertEqual(shown(str(result.destination)), shown(f"C/{TACVBA}/(2010) {DEBRIS}"))
        self.assertEqual(shown([str(f.destination) for f in result.files]),
                         shown([f"C/{TACVBA}/(2010) {DEBRIS}/01. {CAFE}.flac"]))
        (file_plan,) = result.files
        self.assertEqual(shown(file_plan.target["artist"]), shown([TACVBA]))
        self.assertEqual(shown(file_plan.target["title"]), shown([CAFE]))


if __name__ == "__main__":
    unittest.main()
