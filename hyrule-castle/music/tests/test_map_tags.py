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
import unittest

from musiclib import files, genres, mapping
from tests import builders

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
        # name it with.
        for missing in ("", None):
            for ext in FORMATS:
                with self.subTest(ext=ext, date=missing):
                    result = plan(on_file(ext), builders.mb_release(date=missing))
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

    def test_with_no_musicbrainz_genres_the_files_genres_are_kept(self):
        for ext in FORMATS:
            with self.subTest(ext):
                track = on_file(ext, builders.picard_tags(ext, {"genre": ["darkwave", "coldwave"]}))
                composed = genres.compose(None, [], ["darkwave", "coldwave"])
                target = plan(track, genres=composed).target
                self.assertEqual(target[key(ext, "genre")], track.tags[key(ext, "genre")])

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


if __name__ == "__main__":
    unittest.main()
