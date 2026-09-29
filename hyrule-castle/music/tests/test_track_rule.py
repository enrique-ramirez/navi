"""When a file and a MusicBrainz track are the same track, and what that makes the album.

A track pair passes on an agreeing title and a length within 15 s, or on a
placeholder title and a length within 1.5 s. An album is `certain` or `auto`
only when every pair passes, and `review` otherwise.

The title rules are pure functions in `musiclib.titles`, imported inside
each test, so the album cases below still run while that module does not
exist. The album cases go through `identify` against the fake MusicBrainz
server of `tests.test_identify`, with releases built here, since the stock
ones title every track `Track n`.
"""

from __future__ import annotations

import importlib
import unittest

from musiclib import files
from tests.test_identify import IdentifyTestCase, Server, mbid, search_json, unit, vorbis

TAGGED = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"


def titles():
    return importlib.import_module("musiclib.titles")


def titled_release(release_id: str, tracks: list[tuple[str, float | None]], date: str = "1991-08-27") -> dict:
    """One medium of `(title, seconds)` tracks, as `mb.release` returns it.

    A length of `None` leaves it off both the track and its recording, as
    MusicBrainz does for a track nobody has timed.
    """
    media_tracks = []
    for number, (title, seconds) in enumerate(tracks, start=1):
        ms = None if seconds is None else round(seconds * 1000)
        media_tracks.append({
            "position": number, "number": str(number), "title": title, "length": ms,
            "recording": {"id": mbid(f"1{number:02d}"), "title": title, "length": ms},
        })
    return {
        "id": release_id, "title": "Ten", "status": "Official", "date": date,
        "release-group": {"id": mbid("9"), "title": "Ten", "primary-type": "Album"},
        "artist-credit": [{"name": "Pearl Jam", "joinphrase": "", "artist": {"id": mbid("8"), "name": "Pearl Jam"}}],
        "media": [{"position": 1, "format": "CD", "track-count": len(media_tracks), "tracks": media_tracks}],
    }


# --- criterion 3: when two titles agree --------------------------------------


class Normalise(unittest.TestCase):
    def test_accents_case_brackets_ampersands_and_punctuation_are_normalised_away(self) -> None:
        cases = {
            "Hier Kommt Alex (Remastered)": "hierkommtalex",
            "Rock & Roll": "rockandroll",
            "Café del Mar [Live]": "cafedelmar",
            # Casefolded, not lowercased: `ß` casefolds to `ss`.
            "Straße": "strasse",
            "Mr. Self-Destruct!": "mrselfdestruct",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(titles().normalise(title), expected)

    def test_letters_outside_latin_are_kept_and_never_transliterated(self) -> None:
        # No voiced kana here: NFKD splits their dakuten off as a combining
        # mark, which the rule then removes.
        self.assertEqual(titles().normalise("ロックンロール"), "ロックンロール")


class Agree(unittest.TestCase):
    def assertAgree(self, a: str, b: str, expected: bool) -> None:
        # Both orders, since "one contains the other" reads either way round.
        self.assertEqual(titles().agree(a, b), expected, f"{a!r} against {b!r}")
        self.assertEqual(titles().agree(b, a), expected, f"{b!r} against {a!r}")

    def test_a_remastered_suffix_in_brackets_agrees(self) -> None:
        self.assertAgree("Hier Kommt Alex (Remastered)", "Hier kommt Alex", True)

    def test_an_ampersand_agrees_with_and(self) -> None:
        self.assertAgree("Rock & Roll", "Rock and Roll", True)

    def test_titles_that_differ_only_by_normalisation_agree_even_where_the_raw_ratio_is_low(self) -> None:
        # The examples above agree on the lowercased raw titles as well, by
        # containment or a ratio over 0.8. These two do not (0.57 and 0.75),
        # so they agree only when the comparison is on the normalised titles.
        self.assertAgree("Déjà Vu", "DEJA-VU", True)
        self.assertAgree("You & I", "You and I", True)

    def test_an_empty_normalised_title_agrees_with_nothing(self) -> None:
        # Every string contains the empty one, so containment alone would
        # let `[silence]` agree with any title. It agrees with none.
        self.assertAgree("", "Fly", False)
        self.assertAgree("[silence]", "Interview (German)", False)
        self.assertAgree("(untitled)", "[untitled]", False)

    def test_a_title_in_katakana_does_not_agree_with_its_english_one(self) -> None:
        self.assertAgree("ロックンロール", "Rock and Roll", False)

    def test_one_title_containing_the_other_agrees_however_far_apart_the_ratio_is(self) -> None:
        # The ratio here is 0.37, so only containment makes these agree.
        self.assertAgree("Alive", "Alive - Live at Pinkpop 1992", True)

    def test_a_ratio_of_exactly_0_8_agrees_and_one_below_does_not(self) -> None:
        # `hello`/`hallo` is 0.8 exactly and `hello`/`halloa` 0.727, and
        # neither contains the other. The first catches `>` for `>=`, the
        # second a looser threshold.
        self.assertAgree("Hello", "Hallo", True)
        self.assertAgree("Hello", "Halloa", False)
        self.assertAgree("Colour of Love", "Color of Love", True)

    def test_different_songs_do_not_agree(self) -> None:
        self.assertAgree("Frontier City", "The Bucket (CSS remix)", False)

    def test_one_title_inside_the_other_agrees_only_when_the_shorter_has_3_characters_or_more(self) -> None:
        # Criterion 54. A letter or two is inside almost any name, and the
        # ratio is far from 0.8 in every pair here, so containment alone
        # decides. `Air` against `Airbag` is the 3-character edge, and `Up`
        # against `Upside Down` the 2-character one.
        self.assertAgree("I", "Nightmare", False)
        self.assertAgree("M", "Eminem", False)
        self.assertAgree("Up", "Upside Down", False)
        self.assertAgree("Air", "Airbag", True)

    def test_a_short_title_equal_once_normalised_still_agrees(self) -> None:
        # Equal is not containment, so the 3-character floor never applies
        # to it: `I` is `I`.
        self.assertAgree("Air", "Air (Remastered)", True)
        self.assertAgree("I", "I", True)


class Placeholder(unittest.TestCase):
    def test_each_placeholder_on_the_list_is_one(self) -> None:
        for title in ("", "Silence", "[silence]", "Untitled", "(untitled)", "Hidden Track",
                      "Data", "Blank", "Interview", "Track 12", "Track 13", "track01", "7",
                      "Ｔｒａｃｋ １２"):
            with self.subTest(title=title):
                self.assertTrue(titles().is_placeholder(title))

    def test_a_title_that_only_contains_a_placeholder_word_is_not_one(self) -> None:
        # The list is what the whole normalised title is, so `Blank Space`
        # is a song, and so is `Track` with no number after it.
        for title in ("Alive", "Track Record", "Track", "Blank Space", "Silence Is Golden",
                      "Hidden Track 2 Remix", "Data 7"):
            with self.subTest(title=title):
                self.assertFalse(titles().is_placeholder(title))


# --- criterion 1: when a track pair passes ------------------------------------


class PairPasses(unittest.TestCase):
    def passes(self, file_title: str, file_length: float, mb_title: str, mb_length: float | None) -> bool:
        return titles().pair_passes(file_title, file_length, mb_title, mb_length)

    def test_an_agreeing_title_passes_up_to_15_seconds_either_way_and_not_beyond(self) -> None:
        for file_length, expected in ((255.0, True), (225.0, True), (255.5, False), (224.5, False)):
            with self.subTest(file_length=file_length):
                self.assertEqual(self.passes("Alive", file_length, "Alive", 240.0), expected)

    def test_ten_with_one_track_4_seconds_off_passes(self) -> None:
        self.assertTrue(self.passes("Alive", 345.0, "Alive", 341.0))

    def test_a_placeholder_passes_up_to_1_5_seconds_either_way_and_not_at_2(self) -> None:
        # The MusicBrainz title is a real song, so agreement cannot rescue it.
        for file_length, expected in ((241.5, True), (238.5, True), (242.0, False), (238.0, False)):
            with self.subTest(file_length=file_length):
                self.assertEqual(self.passes("Track 12", file_length, "Dead Sound of Misery", 240.0), expected)

    def test_a_different_title_fails_however_close_the_length(self) -> None:
        self.assertFalse(self.passes("Frontier City", 240.0, "The Bucket (CSS remix)", 240.4))

    def test_an_agreeing_title_passes_when_musicbrainz_has_no_length(self) -> None:
        self.assertTrue(self.passes("Alive", 341.0, "Alive", None))

    def test_a_placeholder_fails_when_musicbrainz_has_no_length(self) -> None:
        self.assertFalse(self.passes("Track 12", 240.0, "Dead Sound of Misery", None))

    def test_a_placeholder_that_normalises_to_nothing_passes_only_within_1_5_seconds(self) -> None:
        # If an empty title agreed, `[silence]` would pass at 10 s on the
        # 15 s rule, and against no length on the title alone.
        self.assertFalse(self.passes("[silence]", 1056.7, "Interview (German)", None))
        self.assertFalse(self.passes("[silence]", 100.0, "Interview", 110.0))
        self.assertTrue(self.passes("[silence]", 100.0, "Interview", 101.0))

    def test_a_placeholder_whose_title_also_agrees_passes_on_the_15_second_rule(self) -> None:
        # Either rule is enough. Checking a placeholder by its own rule
        # alone would fail this pair, 10 s off.
        self.assertTrue(self.passes("Untitled", 250.0, "Untitled", 240.0))


# --- criterion 4: the file title ----------------------------------------------


def track(name: str, family: str = "vorbis", **tags: str) -> files.Track:
    return files.Track(path=f"/music/P/Pearl Jam/(1991) Ten/{name}", family=family,
                       tags={k: [v] for k, v in tags.items()}, length=341.0)


class FileTitle(unittest.TestCase):
    def test_the_title_tag_is_the_file_title_in_every_family(self) -> None:
        for family, key, name in (("vorbis", "title", "03. Once.flac"), ("id3", "TIT2", "03. Once.mp3"),
                                  ("mp4", "\xa9nam", "03. Once.m4a"), ("asf", "Title", "03. Once.wma")):
            with self.subTest(family=family):
                self.assertEqual(titles().file_title(track(name, family, **{key: "Alive"})), "Alive")

    def test_without_a_title_tag_the_filename_less_its_number_and_separators_is_the_file_title(self) -> None:
        for name in ("03 - Alive.flac", "03. Alive.flac", "3_Alive.flac", "Alive.flac", "CD1/03 - Alive.flac"):
            with self.subTest(name=name):
                self.assertEqual(titles().file_title(track(name, tracknumber="3")), "Alive")

    def test_an_empty_or_blank_title_tag_is_no_title_and_the_filename_stands_in(self) -> None:
        for value in ("", "  "):
            with self.subTest(value=value):
                self.assertEqual(titles().file_title(track("03 - Alive.flac", title=value)), "Alive")

    def test_only_the_extension_and_the_leading_number_come_off_the_filename(self) -> None:
        self.assertEqual(titles().file_title(track("02. Mr. Self Destruct.flac")), "Mr. Self Destruct")


# --- criterion 2: what the pairs make the album ------------------------------

TEN = [("Once", 231), ("Even Flow", 293), ("Alive", 341), ("Why Go", 200), ("Black", 343),
       ("Jeremy", 318), ("Oceans", 161), ("Porch", 210), ("Garden", 298), ("Deep", 258), ("Release", 545)]


class AlbumStatus(IdentifyTestCase):
    def album_tracks(self, titled: list[tuple[str, str | None, float]], release_id: str | None = None) -> list[files.Track]:
        """FLAC tracks from `(filename, title tag or None, length)`, numbered in order."""
        out = []
        for number, (name, title, length) in enumerate(titled, start=1):
            tags = {"tracknumber": str(number), "album": "Ten", "albumartist": "Pearl Jam", "artist": "Pearl Jam"}
            if title is not None:
                tags["title"] = title
            if release_id:
                tags["musicbrainz_albumid"] = release_id
            out.append(vorbis(self.album, name, length, **tags))
        return out

    def searched(self, release: dict, tracks: list[files.Track]):
        server = Server(search=search_json(release), releases=(release,))
        return self.identify(unit(self.album, tracks), server)

    def test_ten_tagged_with_whole_second_lengths_and_one_track_4_seconds_off_is_certain(self) -> None:
        # Files named as a CD ripper names them, so their names are
        # placeholders: only the title tags can make these pairs agree.
        release = titled_release(TAGGED, TEN)
        tracks = self.album_tracks(
            [(f"Track{n:02d}.flac", title, seconds + (4.0 if title == "Alive" else 0.4 - 0.08 * n))
             for n, (title, seconds) in enumerate(TEN, start=1)],
            release_id=TAGGED)
        server = Server(releases=(release,))
        result = self.identify(unit(self.album, tracks), server)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertEqual(server.searches(), [])

    def test_placeholder_bonus_tracks_within_a_second_are_auto(self) -> None:
        # A Twist in the Myth with its bonus tracks titled `Track 12` and
        # `Track 13` on the files. Otherland is 5 s off, which only the
        # 15 s rule for an agreeing title lets through.
        mb = [("This Will Never End", 305), ("Otherland", 334), ("Turn the Page", 267), ("Fly", 350),
              ("Carry the Blessed Home", 250), ("Another Stranger Me", 272), ("Straight Through the Mirror", 333),
              ("Lionheart", 257), ("Skalds and Shadows", 196), ("The Edge", 263), ("The New Order", 402),
              ("Dead Sound of Misery", 241), ("All the King's Horses", 212)]
        files_ = [(title, mb_length + (5.0 if title == "Otherland" else 0.0)) for title, mb_length in mb[:11]]
        files_ += [("Track 12", 241.9), ("Track 13", 211.1)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([(f"{n:02d}. {t}.flac", t, s) for n, (t, s) in enumerate(files_, start=1)])
        result = self.searched(release, tracks)
        self.assertEqual((result.status, result.reason), ("auto", None))
        self.assertEqual(result.candidates[0].release_id, mbid("a1"))

    def test_a_different_track_3_within_half_a_second_is_review(self) -> None:
        # Only by the Night against an edition whose track 3 is a remix.
        # Every length is within 0.5 s, so only the title can hold it.
        mb = [("Closer", 237), ("Crawl", 246), ("The Bucket (CSS remix)", 175), ("Revelry", 202)]
        on_files = [("Closer", 237.2), ("Crawl", 245.8), ("Frontier City", 175.4), ("Revelry", 202.0)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([(f"{n:02d}. {t}.flac", t, s) for n, (t, s) in enumerate(on_files, start=1)])
        result = self.searched(release, tracks)
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("a1")])
        self.assertTrue(result.candidates[0].matches_counts)

    def test_a_musicbrainz_track_with_no_length_passes_on_its_title_and_the_album_is_auto(self) -> None:
        mb = [("Once", 231), ("Even Flow", None), ("Alive", 341)]
        on_files = [("Once", 231.3), ("Even Flow", 293.4), ("Alive", 340.8)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([(f"{n:02d}. {t}.flac", t, s) for n, (t, s) in enumerate(on_files, start=1)])
        result = self.searched(release, tracks)
        self.assertEqual((result.status, result.reason), ("auto", None))

    def test_files_with_no_title_tag_that_agree_by_filename_are_auto(self) -> None:
        # Every file is 10 s off, which only an agreeing title lets through.
        mb = [("Once", 231), ("Even Flow", 293), ("Alive", 341)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([("01 - Once.flac", None, 241.0), ("02. Even Flow.flac", None, 283.0),
                                    ("3_Alive.flac", None, 351.0)])
        result = self.searched(release, tracks)
        self.assertEqual((result.status, result.reason), ("auto", None))

    def test_files_with_a_blank_title_tag_that_agree_by_filename_are_auto(self) -> None:
        # 10 s off, as above. A blank tag read as the title is a placeholder,
        # held to 1.5 s, so it would make this review.
        mb = [("Once", 231), ("Even Flow", 293), ("Alive", 341)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([("01 - Once.flac", "", 241.0), ("02. Even Flow.flac", "  ", 283.0),
                                    ("3_Alive.flac", "", 351.0)])
        result = self.searched(release, tracks)
        self.assertEqual((result.status, result.reason), ("auto", None))

    def test_a_remembered_title_edit_stands_in_for_the_musicbrainz_title(self) -> None:
        # The owner once retitled track 2 `Rain Again`, and the file carries
        # that. Plainsong is 5 s off, which only the 15 s rule lets through,
        # so without the edit this is review on track 2 alone.
        release = titled_release(TAGGED, [("Plainsong", 312), ("Prayers for Rain", 365), ("Closedown", 259)])
        tracks = self.album_tracks([("01. Plainsong.flac", "Plainsong", 317.0),
                                    ("02. Rain Again.flac", "Rain Again", 365.0),
                                    ("03. Closedown.flac", "Closedown", 259.0)], release_id=TAGGED)
        without = self.identify(unit(self.album, tracks), Server(releases=(release,)),
                                owner_input={"composers": {}, "edits": {}})
        self.assertEqual(without.status, "review")
        self.forget()
        edits = {TAGGED: {"1-2": {"title": ["Rain Again"]}}}
        server = Server(releases=(release,))
        remembered = self.identify(unit(self.album, tracks), server,
                                   owner_input={"composers": {}, "edits": edits})
        self.assertEqual((remembered.status, remembered.reason), ("certain", None))
        self.assertEqual(server.searches(), [])

    def test_a_file_with_no_title_tag_whose_filename_names_another_song_is_review(self) -> None:
        # An empty title is contained in every other title, so it agrees
        # with anything. A missing tag read as an empty title, rather than
        # as the filename, would make this auto.
        mb = [("Closer", 237), ("Crawl", 246), ("The Bucket (CSS remix)", 175)]
        release = titled_release(mbid("a1"), mb)
        tracks = self.album_tracks([("01 - Closer.flac", None, 237.0), ("02. Crawl.flac", None, 246.0),
                                    ("3_Frontier City.flac", None, 175.2)])
        result = self.searched(release, tracks)
        self.assertEqual(result.status, "review")
        self.assertTrue(result.candidates[0].matches_counts)


if __name__ == "__main__":
    unittest.main()
