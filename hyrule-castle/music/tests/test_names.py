"""Folder and file names, from `docs/music-library.md` *Layout*."""

from __future__ import annotations

import unittest

from musiclib import names

FALLBACK_ARTICLES = ("The", "A", "An", "Los", "Las", "La", "El", "Die", "Der", "Das", "Les", "Le")


class Sanitize(unittest.TestCase):
    def test_a_colon_followed_by_a_space_becomes_a_spaced_hyphen(self) -> None:
        self.assertEqual(names.sanitize("Reich & Sexy II: Die fetten Jahre"), "Reich & Sexy II - Die fetten Jahre")

    def test_any_other_colon_becomes_a_hyphen(self) -> None:
        self.assertEqual(names.sanitize("10:30 Returns"), "10-30 Returns")

    def test_both_slashes_become_hyphens(self) -> None:
        self.assertEqual(names.sanitize("AC/DC"), "AC-DC")
        self.assertEqual(names.sanitize("Either\\Or"), "Either-Or")

    def test_question_mark_asterisk_angle_brackets_and_pipe_are_removed(self) -> None:
        self.assertEqual(names.sanitize("Why?"), "Why")
        self.assertEqual(names.sanitize("F*ck"), "Fck")
        self.assertEqual(names.sanitize("<Intro>"), "Intro")
        self.assertEqual(names.sanitize("Side|B"), "SideB")

    def test_a_double_quote_becomes_two_single_quotes(self) -> None:
        self.assertEqual(names.sanitize('The "Real" One'), "The ''Real'' One")

    def test_trailing_full_stops_and_spaces_are_removed(self) -> None:
        self.assertEqual(names.sanitize("R.I.P."), "R.I.P")
        self.assertEqual(names.sanitize("Wait... "), "Wait")

    def test_a_removed_character_between_spaces_leaves_one_space(self) -> None:
        # Dropping the `|` from `A | B` leaves two spaces, which the old
        # restructure script collapsed and the existing library relies on.
        self.assertEqual(names.sanitize("A | B"), "A B")


class Letter(unittest.TestCase):
    def test_is_the_first_character_uppercased(self) -> None:
        self.assertEqual(names.letter("Toten Hosen, Die"), "T")
        self.assertEqual(names.letter("dEUS"), "D")

    def test_drops_the_accent_from_the_first_character(self) -> None:
        self.assertEqual(names.letter("Ángeles Azules, Los"), "A")
        self.assertEqual(names.letter("Émilie Simon"), "E")

    def test_a_digit_goes_under_hash(self) -> None:
        self.assertEqual(names.letter("311"), "#")

    def test_a_non_latin_script_goes_under_hash(self) -> None:
        self.assertEqual(names.letter("Кино"), "#")
        # Greek capital alpha looks like A and strips to a bare alpha, which
        # is still not A. An implementation that trusts the glyph files it
        # under A.
        self.assertEqual(names.letter("Άλκηστις"), "#")


class ArtistFolder(unittest.TestCase):
    def test_uses_the_sort_name_when_it_only_moves_a_leading_article(self) -> None:
        for name, sort_name in (
            ("Die Toten Hosen", "Toten Hosen, Die"),
            ("The Strokes", "Strokes, The"),
            ("Los Bunkers", "Bunkers, Los"),
            ("Les Rita Mitsouko", "Rita Mitsouko, Les"),
            ("A Perfect Circle", "Perfect Circle, A"),
        ):
            with self.subTest(name=name):
                self.assertEqual(names.artist_folder(name, sort_name), sort_name)

    def test_keeps_a_person_as_written_when_the_sort_name_puts_the_surname_first(self) -> None:
        self.assertEqual(names.artist_folder("Joaquín Sabina", "Sabina, Joaquín"), "Joaquín Sabina")

    def test_keeps_the_name_when_the_sort_name_does_more_than_move_the_article(self) -> None:
        # Article-led, and the sort name ends in the article, but the words in
        # between are reordered too. Checking only that the name starts with
        # an article and the sort name ends with it takes the sort name here.
        self.assertEqual(
            names.artist_folder("The Alan Parsons Project", "Parsons, Alan, Project, The"),
            "The Alan Parsons Project",
        )

    def test_keeps_a_leading_the_when_musicbrainz_sorts_the_artist_under_it(self) -> None:
        # The fallback list would move this `The`. A known artist follows
        # MusicBrainz, and MusicBrainz leaves it where it is.
        self.assertEqual(names.artist_folder("The The", "The The"), "The The")

    def test_moves_a_fallback_article_for_an_artist_musicbrainz_does_not_know(self) -> None:
        self.assertEqual(names.artist_folder("The Foo", known=False), "Foo, The")
        for article in FALLBACK_ARTICLES:
            with self.subTest(article=article):
                self.assertEqual(names.artist_folder(f"{article} Foo Bar", known=False), f"Foo Bar, {article}")

    def test_moves_an_apostrophe_article_that_is_attached_to_the_next_word(self) -> None:
        self.assertEqual(names.artist_folder("L'Arc~en~Ciel", known=False), "Arc~en~Ciel, L'")

    def test_matches_a_fallback_article_whatever_its_case(self) -> None:
        # Only the match is promised. Whether the moved article keeps its
        # case is left open, so the comparison ignores case.
        self.assertEqual(names.artist_folder("the Foo", known=False).casefold(), "foo, the")

    def test_leaves_an_unknown_artist_alone_when_the_first_word_is_not_an_article(self) -> None:
        for name in ("Madonna", "Joaquín Sabina", "Theatre of Tragedy", "Lana Del Rey", "Leftfield", "The"):
            with self.subTest(name=name):
                self.assertEqual(names.artist_folder(name, known=False), name)

    def test_a_compilation_goes_to_various_artists(self) -> None:
        self.assertEqual(names.artist_folder("The Foo", known=False, compilation=True), "Various Artists")
        self.assertEqual(names.artist_folder("Die Toten Hosen", "Toten Hosen, Die", compilation=True), "Various Artists")

    def test_passes_the_character_table(self) -> None:
        self.assertEqual(names.artist_folder("AC/DC", "AC/DC"), "AC-DC")


class AlbumFolder(unittest.TestCase):
    def test_is_the_year_then_the_title(self) -> None:
        self.assertEqual(names.album_folder("2002-11-04", "Reich & Sexy II"), "(2002) Reich & Sexy II")

    def test_takes_the_year_from_every_date_precision(self) -> None:
        for date in ("1999", "1999-02", "1999-02-23"):
            with self.subTest(date=date):
                self.assertEqual(names.album_folder(date, "Title"), "(1999) Title")

    def test_a_plain_album_has_no_prefix_even_when_its_title_says_lp(self) -> None:
        self.assertEqual(
            names.album_folder("1999-02-23", "The Slim Shady LP", "Album"),
            "(1999) The Slim Shady LP",
        )

    def test_takes_each_prefix_from_the_release_group_types(self) -> None:
        for primary, secondary, expected in (
            ("EP", (), "(2010) [EP] Title"),
            ("Single", (), "(2010) [Single] Title"),
            ("Album", ("Mixtape/Street",), "(2010) [Mixtape] Title"),
            ("Album", ("Live",), "(2010) [Live] Title"),
        ):
            with self.subTest(primary=primary, secondary=secondary):
                self.assertEqual(names.album_folder("2010", "Title", primary, secondary), expected)

    def test_uses_one_prefix_the_first_in_table_order(self) -> None:
        # The secondary types are listed Live-first, so an implementation
        # that walks the release's types instead of the table picks Live.
        for primary, secondary, expected in (
            ("EP", ("Live",), "(2010) [EP] Title"),
            ("Single", ("Live", "Mixtape/Street"), "(2010) [Single] Title"),
            ("Album", ("Live", "Mixtape/Street"), "(2010) [Mixtape] Title"),
        ):
            with self.subTest(primary=primary, secondary=secondary):
                self.assertEqual(names.album_folder("2010", "Title", primary, secondary), expected)

    def test_a_secondary_type_outside_the_table_adds_no_prefix(self) -> None:
        self.assertEqual(names.album_folder("2000", "Title", "Album", ("Soundtrack", "Compilation")), "(2000) Title")

    def test_passes_the_character_table(self) -> None:
        self.assertEqual(
            names.album_folder("2002", "Reich & Sexy II: Die fetten Jahre"),
            "(2002) Reich & Sexy II - Die fetten Jahre",
        )
        self.assertEqual(names.album_folder("2008", "R.I.P."), "(2008) R.I.P")


class DiscFolder(unittest.TestCase):
    def test_a_single_medium_release_has_no_disc_folder(self) -> None:
        self.assertIsNone(names.disc_folder(1, 1))

    def test_each_medium_of_a_multi_medium_release_gets_its_own_cd_folder(self) -> None:
        self.assertEqual(names.disc_folder(1, 2), "CD1")
        self.assertEqual(names.disc_folder(2, 2), "CD2")
        self.assertEqual(names.disc_folder(10, 12), "CD10")


class TrackFilename(unittest.TestCase):
    def test_is_two_digits_a_full_stop_a_space_and_the_title(self) -> None:
        self.assertEqual(names.track_filename(1, "Hier kommt Alex", "flac", 14), "01. Hier kommt Alex.flac")
        self.assertEqual(names.track_filename(12, "Title", "mp3", 99), "12. Title.mp3")

    def test_uses_three_digits_on_a_medium_of_a_hundred_tracks_or_more(self) -> None:
        self.assertEqual(names.track_filename(7, "Title", "mp3", 100), "007. Title.mp3")
        self.assertEqual(names.track_filename(100, "Title", "mp3", 100), "100. Title.mp3")
        self.assertEqual(names.track_filename(7, "Title", "mp3", 99), "07. Title.mp3")

    def test_passes_the_title_through_the_character_table(self) -> None:
        self.assertEqual(names.track_filename(3, "Who: Me?", "ogg", 10), "03. Who - Me.ogg")
        # The trailing dots belong to the title, so they go even though the
        # extension follows them. Sanitizing the whole filename keeps them.
        self.assertEqual(names.track_filename(4, "Wait...", "m4a", 10), "04. Wait.m4a")


if __name__ == "__main__":
    unittest.main()
