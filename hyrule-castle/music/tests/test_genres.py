"""Genre composition.

MusicBrainz genres arrive as the release group's `genres` array. The custom
genre (`video game music` or `soundtrack`) is decided separately, and
neither of them is on MusicBrainz's official list.
"""

from __future__ import annotations

import unittest

from musiclib import genres

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
        # Alphabetical order and the order given are both wrong here.
        self.assertEqual(
            genres.compose(None, mb(("rock", 1), ("ambient", 3), ("jazz", 5)), []),
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
    # MusicBrainz answered with genres, just none that count. That is not
    # the same as having none, so the file's genres go too.
    def test_gives_just_the_custom_genre(self) -> None:
        self.assertEqual(genres.compose(VGM, mb(("seen live", 3), ("anime", 2)), ["rock"]), [VGM])

    def test_gives_nothing_without_a_custom_genre(self) -> None:
        self.assertEqual(genres.compose(None, mb(("seen live", 3)), ["rock"]), [])


if __name__ == "__main__":
    unittest.main()
