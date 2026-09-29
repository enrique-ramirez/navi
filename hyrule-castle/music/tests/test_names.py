"""Folder and file names, from `docs/music-library.md` *Layout*."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musiclib import caa, check, mb, names
from musiclib.cache import Cache
from musiclib.units import units
from tests import builders

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


#: Fiona Apple's 1999 album as MusicBrainz titles it, with its curly
#: apostrophes already made straight: `names` is handed converted text and
#: never converts it itself.
FIONA = (
    "When the Pawn Hits the Conflicts He Thinks Like a King What He Knows Throws the Blows "
    "When He Goes to the Fight and He'll Win the Whole Thing 'Fore He Enters the Ring There's "
    "No Body to Batter When Your Mind Is Your Might So When You Go Solo, You Hold Your Own Hand "
    "and Remember That Depth Is the Greatest of Heights and If You Know Where You Stand, Then You "
    "Know Where to Land and If You Fall It Won't Matter, Cuz You'll Know That You're Right"
)

FIONA_FOLDER = (
    "(1999) When the Pawn Hits the Conflicts He Thinks Like a King What He Knows Throws the Blows "
    "When He Goes to the Fight and He'll Win the Whole Thing 'Fore He Enters the Ring There's "
    "No Body to Batter When Your Mind Is Your Might So When You Go Solo, [...]"
)

#: 交 is three bytes in UTF-8, so a name made of it is a third as many
#: characters as bytes. A cut that counts characters leaves it far too long,
#: and one that counts bytes but slices them splits a character.
WIDE = "交"


def words(count: int) -> str:
    return " ".join(f"word{n:02d}" for n in range(1, count + 1))


class Fit(unittest.TestCase):
    def test_a_name_of_exactly_255_bytes_is_left_alone(self) -> None:
        self.assertEqual(names.fit(WIDE * 85), WIDE * 85)
        self.assertEqual(names.fit("a" * 250, ".flac"), "a" * 250 + ".flac")

    def test_a_longer_name_is_cut_at_the_last_whole_word_and_marked(self) -> None:
        # 36 words are 251 bytes and the mark 6, so the 35th word ends at 244
        # and fits with it, and the 36th does not.
        self.assertEqual(names.fit(words(36) + " tail"), words(35) + " [...]")

    def test_the_suffix_is_counted_and_never_cut(self) -> None:
        # `abcd` ends at 249 bytes, which fits beside the mark alone and not
        # beside the mark and `.flac` as well, so it goes.
        cut = names.fit(f"{words(35)} abcd tail", ".flac")
        self.assertEqual(cut, words(35) + " [...].flac")
        self.assertEqual(len(cut.encode()), 255)

    def test_a_name_with_no_spaces_is_cut_at_the_last_whole_character(self) -> None:
        # 83 characters are 249 bytes, and the mark brings it to 255.
        self.assertEqual(names.fit(WIDE * 100), WIDE * 83 + " [...]")


class AlbumFolderOver255Bytes(unittest.TestCase):
    def test_fiona_apples_when_the_pawn_is_criterion_46s_folder_at_255_bytes(self) -> None:
        # Exactly 255 with the mark, and `Solo,` keeps its comma: the cut
        # drops the space and nothing else.
        folder = names.album_folder("1999-11-09", FIONA)
        self.assertEqual(folder, FIONA_FOLDER)
        self.assertEqual(len(folder.encode()), 255)

    def test_the_prefix_counts_toward_the_255_bytes(self) -> None:
        # `(2010) ` and the title are 251 bytes, which fits. `[EP] ` adds 5,
        # which does not, and 34 words then end exactly at 255 with the mark.
        title = words(35)
        self.assertEqual(names.album_folder("2010", title), f"(2010) {title}")
        cut = names.album_folder("2010", title, "EP")
        self.assertEqual(cut, f"(2010) [EP] {words(34)} [...]")
        self.assertEqual(len(cut.encode()), 255)

    def test_a_folder_of_exactly_255_bytes_is_left_alone_and_one_byte_more_is_cut(self) -> None:
        self.assertEqual(names.album_folder("2010", f"{words(35)} abc"), f"(2010) {words(35)} abc")
        self.assertEqual(names.album_folder("2010", f"{words(35)} abcd"), f"(2010) {words(34)} [...]")

    def test_a_title_with_no_spaces_is_cut_at_a_whole_character_after_the_year(self) -> None:
        self.assertEqual(names.album_folder("2010", WIDE * 100), f"(2010) {WIDE * 80} [...]")

    def test_punctuation_ending_the_last_kept_word_stays(self) -> None:
        # A cut made before the character table, or one that trims what it
        # keeps, loses the full stop after `Mr`.
        title = f"{'a' * 238} Mr. Jones Smith"
        self.assertEqual(names.album_folder("2010", title), f"(2010) {'a' * 238} Mr. [...]")

    def test_the_bytes_counted_are_the_ones_left_after_the_character_table(self) -> None:
        # Each `"` becomes `''`, so this 255-byte folder is 257 once the table
        # runs, and has to be cut. Counting before the table leaves it whole.
        self.assertEqual(names.album_folder("2010", f'{words(35)} "b"'), f"(2010) {words(34)} [...]")
        # And the other way: 256 bytes as given, 251 once `?` is removed.
        self.assertEqual(names.album_folder("2010", f"{words(35)} ????"), f"(2010) {words(35)}")


class TrackFilenameOver255Bytes(unittest.TestCase):
    def test_is_cut_before_its_extension_which_stays_whole(self) -> None:
        # The number, the mark and `.flac` all count, so the cut lands a word
        # before the one the Fiona folder keeps.
        name = names.track_filename(1, FIONA, "flac", 10)
        self.assertEqual(name, "01. " + FIONA_FOLDER[len("(1999) "):-len(" Solo, [...]")] + " [...].flac")
        self.assertTrue(name.endswith(" You Go [...].flac"), name)
        self.assertLessEqual(len(name.encode()), 255)

    def test_a_file_name_of_exactly_255_bytes_is_left_alone_and_one_byte_more_is_cut(self) -> None:
        self.assertEqual(names.track_filename(1, f"{words(35)} a", "flac", 10), f"01. {words(35)} a.flac")
        self.assertEqual(names.track_filename(1, f"{words(35)} ab", "flac", 10), f"01. {words(34)} [...].flac")

    def test_a_title_with_no_spaces_is_cut_at_a_whole_character_after_the_number(self) -> None:
        # 80 characters are 240 bytes: with `01. `, the mark and `.flac`, 255.
        self.assertEqual(names.track_filename(1, WIDE * 100, "flac", 10), f"01. {WIDE * 80} [...].flac")


class ALeadingFullStopOrHyphen(unittest.TestCase):
    """Criterion 21: a leading `.` or `-` in an artist folder becomes `_`, as beets does it.

    A folder starting with `.` is hidden on the box and on a Mac, and one
    starting with `-` reads as an option to half the tools that touch it.
    """

    def test_criterion_21s_three_examples_land_under_hash_with_only_the_first_character_replaced(self) -> None:
        # The ellipsis and the trailing hyphen guard the "only the first"
        # half: replacing every leading run, or every hyphen, fails them.
        for name, path in (
            (".38 Special", "#/_38 Special"),
            ("...And You Will Know Us by the Trail of Dead", "#/_..And You Will Know Us by the Trail of Dead"),
            ("-M-", "#/_M-"),
        ):
            for known in (True, False):
                with self.subTest(name=name, known=known):
                    folder = names.artist_folder(name, name, known=known)
                    self.assertEqual(f"{names.letter(folder)}/{folder}", path)

    def test_a_hyphen_left_at_the_front_by_the_character_table_is_replaced_too(self) -> None:
        # `:wumpscut:` only starts with a hyphen once the colon has been
        # through the table. Replacing before the table leaves `-wumpscut-`.
        self.assertEqual(names.artist_folder(":wumpscut:", ":wumpscut:"), "_wumpscut-")

    def test_an_artist_named_only_full_stops_gets_the_folder_underscore_under_hash(self) -> None:
        # The character table strips trailing full stops, which for these
        # names is all of them. An empty artist folder would put the albums
        # straight into the letter folder.
        for name in (".", "..", "..."):
            for known in (True, False):
                with self.subTest(name=name, known=known):
                    folder = names.artist_folder(name, name, known=known)
                    self.assertEqual(f"{names.letter(folder)}/{folder}", "#/_")

    def test_a_full_stop_or_hyphen_anywhere_but_the_front_is_left_alone(self) -> None:
        for name in ("Mr. Bungle", "Jay-Z", "t.A.T.u."):
            with self.subTest(name=name):
                self.assertEqual(names.artist_folder(name, name), names.sanitize(name))


class AnUpperCaseExtension(unittest.TestCase):
    """Criterion 22: a planned file name carries its extension in lower case."""

    def test_the_extension_is_lowercased_and_the_title_is_not(self) -> None:
        self.assertEqual(names.track_filename(1, "Title", "MP3", 10), "01. Title.mp3")
        self.assertEqual(names.track_filename(2, "LOUD", "Flac", 10), "02. LOUD.flac")


class LettersWithAStroke(unittest.TestCase):
    """Criterion 24: `Ø` and `Ł` have no decomposition, so stripping accents alone files them under `#`."""

    def test_o_with_a_stroke_goes_under_o_and_l_with_a_stroke_under_l(self) -> None:
        for folder, expected in (
            ("Øystein Sevåg", "O"),
            ("østkyst", "O"),
            ("Łona", "L"),
            ("łzy", "L"),
        ):
            with self.subTest(folder=folder):
                self.assertEqual(names.letter(folder), expected)


def _planning():
    """`test_check`'s planning helpers, imported late.

    `test_check` imports `FIONA` from this module, so importing it at the
    top would be circular whichever module loads first.
    """
    from tests import test_check

    return test_check


class PlannedNames(unittest.TestCase):
    """Criteria 21 and 22 through `plan_album`, where the folder and file names are actually chosen."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def plan(self, root: Path, album: Path, release: dict):
        tc = _planning()
        services = tc._Services(release, tc._release_group(), front=False)
        cache = Cache(self.tmp / "cache")
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        unit = next(u for u in units(root) if u.path == album)
        return tc._plan_album(unit, release, client, art, status="auto")

    def test_38_special_is_planned_under_hash_underscore_and_its_tags_keep_the_full_stop(self) -> None:
        tc = _planning()
        root = self.tmp / "library"
        album = tc._rip(root, ["Plainsong"])
        credit = builders.mb_credit("1a0b0c0d-0000-4000-8000-0000000000c1", ".38 Special", ".38 Special")
        plan = self.plan(root, album, tc._release(["Plainsong"], credit=credit))

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), "#/_38 Special/(2010) Disintegration")
        self.assertEqual(plan.files[0].target["artist"], [".38 Special"])
        self.assertEqual(plan.files[0].target["albumartist"], [".38 Special"])

    def test_a_rip_with_upper_case_extensions_is_planned_to_lower_case_ones_and_tagged_as_its_format(self) -> None:
        # The format has to come from the file whatever the case of its
        # name: an MP3 planned with Vorbis keys, or refused as unreadable,
        # would show here as a missing TIT2 or a problem.
        tc = _planning()
        for ext, upper, title_key in (("mp3", "MP3", "TIT2"), ("flac", "FLAC", "title")):
            with self.subTest(ext=upper):
                root = self.tmp / f"library-{ext}"
                album = tc._rip(root, ["Plainsong", "Pictures of You"], ext=ext)
                for path in sorted(album.glob(f"*.{ext}")):
                    path.rename(path.with_name(f"{path.stem}.{upper}"))
                plan = self.plan(root, album, tc._release(["Plainsong", "Pictures of You"]))

                self.assertEqual(list(plan.problems), [])
                self.assertEqual(
                    sorted(f.destination for f in plan.files),
                    [f"C/Cure, The/(2010) Disintegration/01. Plainsong.{ext}",
                     f"C/Cure, The/(2010) Disintegration/02. Pictures of You.{ext}"],
                )
                for file_plan in plan.files:
                    self.assertTrue(file_plan.source.endswith(f".{upper}"), file_plan.source)
                    self.assertIn(title_key, file_plan.target)


class CheckAgrees(unittest.TestCase):
    """`check` passes an album already where criteria 21 and 24 put it, so a planned album is not flagged."""

    def test_albums_under_hash_underscore_and_under_o_for_o_with_a_stroke_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builders.library_album(root, letter="#", artist="_38 Special", ext="mp3",
                                   album="Special Forces", date="1982")
            builders.library_album(root, letter="O", artist="Øystein Sevåg", album="Link", date="1993")
            self.assertEqual(check.check(root), [])


if __name__ == "__main__":
    unittest.main()
