"""Genre composition.

MusicBrainz genres arrive as the release group's `genres` array. The custom
genre (`video game music` or `soundtrack`) is decided separately, and
neither of them is on MusicBrainz's official list.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from musiclib import caa, genres
from musiclib.cache import Cache
from musiclib.mb import MusicBrainz, MusicBrainzUnavailable
from tests import builders
from tests.test_check import CURE, NIN, _Planning, _plan_album, _release, _release_group, _rip, _Services

VGM = "video game music"


def mb(*pairs: tuple[str, int]) -> list[dict[str, object]]:
    return [{"name": name, "count": count} for name, count in pairs]


class Official(unittest.TestCase):
    def test_holds_the_whole_list_from_first_line_to_last(self) -> None:
        # The data file has no trailing newline. Reading it wrong loses the
        # last entry or keeps a line ending on it, and the first and last
        # entries are where that shows.
        self.assertIn("2 tone", genres.OFFICIAL)
        self.assertIn("zydeco", genres.OFFICIAL)
        self.assertIn("drum and bass", genres.OFFICIAL)
        self.assertNotIn("", genres.OFFICIAL)

    def test_leaves_out_tags_that_are_not_genres(self) -> None:
        for name in ("seen live", "vgm", "anime", VGM, "soundtrack"):
            with self.subTest(name=name):
                self.assertNotIn(name, genres.OFFICIAL)


class Compose(unittest.TestCase):
    def test_chrono_cross_gets_the_custom_genre_then_its_musicbrainz_genres(self) -> None:
        self.assertEqual(
            genres.compose(VGM, mb(("electronic", 1), ("ambient", 2), ("downtempo", 1)), []),
            [VGM, "ambient", "downtempo", "electronic"],
        )

    def test_piano_collections_gets_the_custom_genre_then_classical(self) -> None:
        self.assertEqual(genres.compose(VGM, mb(("classical", 4)), []), [VGM, "classical"])

    def test_orders_musicbrainz_genres_by_vote_count_highest_first(self) -> None:
        # Alphabetical order and the order given are both wrong here. Every
        # count is above a quarter of the top, so all three stay.
        self.assertEqual(
            genres.compose(None, mb(("rock", 2), ("ambient", 3), ("jazz", 5)), []),
            ["jazz", "ambient", "rock"],
        )

    def test_breaks_a_tie_in_votes_by_name(self) -> None:
        # Within each count the names arrive out of order, so keeping
        # MusicBrainz's order, or sorting names descending, fails.
        self.assertEqual(
            genres.compose(None, mb(("rock", 1), ("jazz", 3), ("ambient", 1), ("electronic", 3)), []),
            ["electronic", "jazz", "ambient", "rock"],
        )

    def test_drops_musicbrainz_genres_that_are_not_on_the_official_list(self) -> None:
        self.assertEqual(
            genres.compose(None, mb(("seen live", 9), ("shoegaze", 2), ("anime", 7), ("lo-fi", 1)), []),
            ["shoegaze", "lo-fi"],
        )

    def test_musicbrainz_genres_replace_the_files_genres(self) -> None:
        self.assertEqual(genres.compose("soundtrack", mb(("ambient", 1)), ["rock", "jazz"]), ["soundtrack", "ambient"])


class ComposeWhenMusicBrainzHasNoGenres(unittest.TestCase):
    # The file's genres are the fallback, and only the ones on the official
    # list survive it. MusicBrainz spells it "dark wave", so "Darkwave" would
    # not be on the list at all.
    def test_keeps_only_the_files_genres_on_the_list_lowercased_and_once_each(self) -> None:
        # "Rock; Pop" names two genres that are both on the list, and is
        # still dropped: split it and the rule is broken the other way.
        self.assertEqual(
            genres.compose(None, [], ["Dark Wave", "made-up genre", "dark wave", "Rock; Pop"]),
            ["dark wave"],
        )

    def test_finds_a_miscased_file_genre_on_the_list(self) -> None:
        self.assertEqual(genres.compose(None, [], ["J-Pop", "anime"]), ["j-pop"])

    def test_keeps_the_order_the_files_first_give_them(self) -> None:
        self.assertEqual(
            genres.compose(None, [], ["Shoegaze", "ambient", "shoegaze", "Jazz"]),
            ["shoegaze", "ambient", "jazz"],
        )

    def test_gives_nothing_when_no_file_genre_is_on_the_list(self) -> None:
        self.assertEqual(genres.compose(None, [], ["made-up genre", "Rock; Pop"]), [])

    def test_drops_a_blank_or_whitespace_only_file_genre(self) -> None:
        self.assertEqual(genres.compose(None, [], ["", "   ", "Rock"]), ["rock"])
        self.assertEqual(genres.compose(None, [], ["", "   "]), [])

    def test_puts_the_custom_genre_first_and_lowercases_the_rest(self) -> None:
        # The file's own "Soundtrack" is the custom genre miscased, so it goes
        # rather than sitting after it a second time.
        self.assertEqual(
            genres.compose("soundtrack", [], ["Rock", "Soundtrack", "made-up genre", "jazz"]),
            ["soundtrack", "rock", "jazz"],
        )

    def test_gives_the_custom_genre_alone_when_no_file_genre_is_on_the_list(self) -> None:
        self.assertEqual(genres.compose(VGM, [], ["made-up genre"]), [VGM])

    def test_video_game_music_still_drops_a_file_soundtrack(self) -> None:
        # "soundtrack" is off the official list, so the list filter drops it
        # too: this holds the promise, and cannot tell the two reasons apart.
        self.assertEqual(genres.compose(VGM, [], ["Soundtrack", "Ambient"]), [VGM, "ambient"])

    def test_moves_the_custom_genre_to_the_front_of_the_files_genres(self) -> None:
        self.assertEqual(
            genres.compose(VGM, [], ["rock", VGM, "electronic"]),
            [VGM, "rock", "electronic"],
        )

    def test_adds_the_custom_genre_in_front_when_the_file_lacks_it(self) -> None:
        self.assertEqual(genres.compose("soundtrack", [], ["rock", "jazz"]), ["soundtrack", "rock", "jazz"])


class ComposeWhenNoMusicBrainzGenreIsOnTheList(unittest.TestCase):
    # MusicBrainz answered with genres, none of them on the list. That leaves
    # the album as short of a genre as no answer at all, so the files' genres
    # get their turn, the same as when MusicBrainz has none.
    def test_falls_back_to_the_files_genres_on_the_list(self) -> None:
        self.assertEqual(
            genres.compose(None, mb(("seen live", 3), ("anime", 2)), ["Rock", "made-up genre"]),
            ["rock"],
        )

    def test_puts_the_custom_genre_before_the_files_genres(self) -> None:
        self.assertEqual(genres.compose(VGM, mb(("seen live", 3), ("anime", 2)), ["rock"]), [VGM, "rock"])

    def test_gives_just_the_custom_genre_when_no_file_genre_is_on_the_list_either(self) -> None:
        self.assertEqual(genres.compose(VGM, mb(("seen live", 3)), ["made-up genre"]), [VGM])

    def test_gives_nothing_when_nothing_is_on_the_list(self) -> None:
        self.assertEqual(genres.compose(None, mb(("seen live", 3)), ["made-up genre"]), [])


# Live vote counts from MusicBrainz, every name on the official list.
OK_COMPUTER = mb(
    ("alternative rock", 25), ("rock", 13), ("art rock", 13), ("space rock revival", 3),
    ("post-britpop", 3), ("experimental", 3), ("pop rock", 2), ("leftfield", 2), ("indie rock", 2),
    ("experimental rock", 2), ("electronic", 2), ("neo-psychedelia", 1), ("britpop", 1),
)
METEORA = mb(
    ("nu metal", 19), ("alternative metal", 12), ("rap rock", 6), ("alternative rock", 6), ("rock", 4),
    ("rap metal", 4), ("electronic", 3), ("rapcore", 1), ("post-industrial", 1), ("post-grunge", 1),
    ("pop", 1), ("metal", 1), ("heavy metal", 1), ("alternative pop", 1),
)
RUMOURS = mb(
    ("rock", 14), ("soft rock", 10), ("pop rock", 10), ("blues", 6), ("folk pop", 4), ("classic rock", 2),
    ("blues rock", 2), ("folk rock", 1),
)
NEVERMIND = mb(("grunge", 48), ("alternative rock", 20), ("rock", 5), ("punk rock", 3))


class ComposeKeepsGenresWithAQuarterOfTheTopVotes(unittest.TestCase):
    # A release group's long tail is one or two people's opinion. Only a
    # genre with at least a quarter of the votes of the most-voted genre on
    # the list is the album's.
    def test_live_release_groups_keep_what_clears_the_line(self) -> None:
        cases = {
            "OK Computer, 13 to 3": (OK_COMPUTER, ["alternative rock", "art rock", "rock"]),
            "Meteora, 14 to 4": (METEORA, ["nu metal", "alternative metal", "alternative rock", "rap rock"]),
            "Rumours, 8 to 5": (RUMOURS, ["rock", "pop rock", "soft rock", "blues", "folk pop"]),
            "Nevermind, 4 to 2": (NEVERMIND, ["grunge", "alternative rock"]),
        }
        for case, (group, expected) in cases.items():
            with self.subTest(case):
                self.assertEqual(genres.compose(None, group, []), expected)

    def test_the_custom_genre_still_comes_first(self) -> None:
        self.assertEqual(genres.compose(VGM, NEVERMIND, []), [VGM, "grunge", "alternative rock"])

    def test_keeps_a_single_genre_with_one_vote(self) -> None:
        self.assertEqual(genres.compose(None, mb(("shoegaze", 1)), []), ["shoegaze"])

    def test_keeps_a_genre_exactly_on_the_line(self) -> None:
        # 2 is exactly a quarter of 8, so "at least" keeps it and 1 goes.
        self.assertEqual(genres.compose(None, mb(("rock", 8), ("jazz", 2), ("ambient", 1)), []), ["rock", "jazz"])

    def test_does_not_round_the_line_down(self) -> None:
        # A quarter of 9 is 2.25. A line cut to a whole number keeps the 2.
        self.assertEqual(genres.compose(None, mb(("rock", 9), ("jazz", 3), ("ambient", 2)), []), ["rock", "jazz"])

    def test_measures_the_line_against_the_top_genre_on_the_list(self) -> None:
        # "seen live" is off the list. Measured against its 40 votes, both of
        # the listed genres would fall under the line and the album would be
        # left with none.
        self.assertEqual(
            genres.compose(None, mb(("seen live", 40), ("rock", 4), ("jazz", 1)), []),
            ["rock", "jazz"],
        )


class ArtistGenres:
    """The zero-argument callable `compose` takes as `artist_genres`, counting its calls.

    `compose` calls it only when it needs the artist's genres, so a call
    stands for a lookup made against MusicBrainz.
    """

    def __init__(self, answer: list[dict[str, object]]) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> list[dict[str, object]]:
        self.calls += 1
        return self.answer


RADIOHEAD = mb(("seen live", 60), ("alternative rock", 20), ("art rock", 8), ("electronic", 4))


class ComposeFallsBackToTheArtistsGenres(unittest.TestCase):
    # Only an album that would otherwise have no genre at all, custom genre
    # included, asks after its artist's genres.
    def test_takes_the_artists_genres_by_the_same_quarter_rule(self) -> None:
        # "seen live" is off the list and so is not the top; 4 is under a
        # quarter of 20.
        artist = ArtistGenres(RADIOHEAD)
        self.assertEqual(genres.compose(None, [], [], artist_genres=artist), ["alternative rock", "art rock"])
        self.assertEqual(artist.calls, 1)

    def test_takes_them_when_nothing_from_musicbrainz_or_the_files_is_on_the_list(self) -> None:
        artist = ArtistGenres(RADIOHEAD)
        self.assertEqual(
            genres.compose(None, mb(("seen live", 3)), ["made-up genre", "Rock; Pop"], artist_genres=artist),
            ["alternative rock", "art rock"],
        )

    def test_gives_nothing_when_none_of_the_artists_genres_is_on_the_list(self) -> None:
        self.assertEqual(genres.compose(None, [], [], artist_genres=ArtistGenres(mb(("seen live", 9)))), [])

    def test_is_never_asked_when_the_album_has_a_genre_from_anywhere_else(self) -> None:
        cases = {
            "the release group's": (None, NEVERMIND, [], ["grunge", "alternative rock"]),
            "the files', with nothing from MusicBrainz": (None, [], ["Rock"], ["rock"]),
            "the files', with nothing on the list from MusicBrainz": (None, mb(("anime", 3)), ["Rock"], ["rock"]),
            # A soundtrack with nothing else is `[soundtrack]`, which is a
            # genre: the artist's would add to an album that has one.
            "the custom genre alone": ("soundtrack", [], [], ["soundtrack"]),
        }
        for case, (custom, group, files, expected) in cases.items():
            with self.subTest(case):
                artist = ArtistGenres(RADIOHEAD)
                self.assertEqual(genres.compose(custom, group, files, artist_genres=artist), expected)
                self.assertEqual(artist.calls, 0)


VARIOUS_ARTISTS = builders.mb_credit("89ad4ac3-39f7-470e-963a-56509c546377", "Various Artists", "Various Artists")
TITLES = ["Plainsong", "Pictures of You"]
THE_CURE = {"seen live": 50, "gothic rock": 20, "post-punk": 12, "new wave": 4}


class WithArtists(_Services):
    """`test_check._Services`, answering any artist lookup with `THE_CURE`'s genres, and keeping every URL.

    Any artist gets an answer, so a lookup that should never have been made
    shows up in `urls` and not as a 404 somewhere else in the plan.
    `artist_status` other than 200 answers every artist lookup with that
    error instead, and `group_status` the release group's.
    """

    def __init__(self, release: dict, release_group: dict, artist_status: int = 200,
                 group_status: int = 200) -> None:
        super().__init__(release, release_group, front=True)
        self.urls: list[str] = []
        self.artist_status = artist_status
        self.group_status = group_status

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.urls.append(url)
        parts = urlsplit(url)
        if parts.netloc == "musicbrainz.org" and parts.path.startswith("/ws/2/release-group/"):
            if self.group_status != 200:
                return self.group_status, b"error"
        if parts.netloc == "musicbrainz.org" and parts.path.startswith("/ws/2/artist/"):
            if self.artist_status != 200:
                return self.artist_status, b"error"
            artist = {"id": parts.path.rstrip("/").rsplit("/", 1)[1], "name": "The Cure",
                      "genres": [{"name": n, "count": c} for n, c in THE_CURE.items()]}
            return 200, json.dumps(artist).encode()
        return super().__call__(url, headers)

    def artist_lookups(self) -> list[str]:
        return [u for u in self.urls if urlsplit(u).path.startswith("/ws/2/artist/")]


class APlanFallsBackToTheAlbumArtistsGenres(_Planning):
    def plan_with(self, release: dict, group: dict, genre: tuple[str, ...] = (), **statuses: int):
        root = self.library()
        album = _rip(root, TITLES, genre=genre)
        services = WithArtists(release, group, **statuses)
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        plan = _plan_album(self.unit(root, album), release, client, art, status="auto")
        return plan, services

    @staticmethod
    def album_genres(plan) -> list[list[str]]:
        return [f.target.get("genre") for f in plan.files]

    def test_an_album_with_no_genre_anywhere_takes_the_album_artists(self) -> None:
        plan, services = self.plan_with(_release(TITLES), _release_group({}))

        self.assertEqual(self.album_genres(plan), [["gothic rock", "post-punk"]] * 2)
        self.assertFalse([p for p in plan.problems if p.startswith("no genre")], plan.problems)
        [lookup] = services.artist_lookups()
        self.assertEqual(urlsplit(lookup).path, f"/ws/2/artist/{builders.CURE_ID}")

    def test_an_artist_musicbrainz_does_not_know_leaves_the_album_with_no_genre(self) -> None:
        # A 404 is an answer: the artist has no genres to give, and the plan
        # says `no genre` exactly as it did before there was a fallback.
        plan, services = self.plan_with(_release(TITLES), _release_group({}), artist_status=404)

        self.assertEqual(len(services.artist_lookups()), 1)
        self.assertEqual(self.album_genres(plan), [None, None])
        self.assertTrue([p for p in plan.problems if p.split(":", 1)[0].strip() == "no genre"], plan.problems)

    def test_musicbrainz_unavailable_for_the_artist_stops_the_plan_as_it_does_for_the_release_group(self) -> None:
        # Unavailable is not an answer. Taken as "no artist genres", an
        # outage would leave an album `no genre` that a working day gives a
        # genre to. The release group's case holds the plan to the same
        # behaviour for both lookups.
        for case, statuses in {"the release group": {"group_status": 503},
                               "the artist": {"artist_status": 503}}.items():
            with self.subTest(case):
                with self.assertRaises(MusicBrainzUnavailable):
                    self.plan_with(_release(TITLES), _release_group({}), **statuses)

    def test_the_artist_is_never_looked_up_when_the_album_has_a_genre_or_no_single_artist(self) -> None:
        soundtrack = _release_group({})
        soundtrack["secondary-types"] = ["Soundtrack"]
        several = [{**CURE[0], "joinphrase": " & "}, NIN[0]]
        cases = {
            "the release group has genres": (_release(TITLES), _release_group({"gothic rock": 3}), ()),
            "the files have genres": (_release(TITLES), _release_group({}), ("Gothic Rock",)),
            "a soundtrack with nothing else": (_release(TITLES), soundtrack, ()),
            # Various Artists and a credit to several artists have no one
            # artist whose genres would be the album's.
            "Various Artists": (_release(TITLES, credit=VARIOUS_ARTISTS), _release_group({}), ()),
            "several artists": (_release(TITLES, credit=several), _release_group({}), ()),
        }
        for case, (release, group, genre) in cases.items():
            with self.subTest(case):
                _plan, services = self.plan_with(release, group, genre)
                self.assertEqual(services.artist_lookups(), [])


if __name__ == "__main__":
    unittest.main()
