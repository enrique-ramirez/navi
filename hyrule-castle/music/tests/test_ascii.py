"""Typographic punctuation in the name fields.

The characters are written as escapes so the source shows which code point
each one is. Several of them are indistinguishable on screen.
"""

from __future__ import annotations

import unittest

from musiclib import ascii

CONVERTED = {
    "\u2019": "'",  # right single quotation mark
    "\u2018": "'",  # left single quotation mark
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u2026": "...",  # horizontal ellipsis
    "\u2010": "-",  # hyphen
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
}

# Close neighbours of the converted characters. A range or a Unicode
# category does not tell them apart, which is how they get caught up.
KEPT = (
    "\u201a",  # single low-9 quotation mark
    "\u201e",  # double low-9 quotation mark
    "\u201b",  # single high-reversed-9 quotation mark
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign
    "\u00ab",  # left-pointing double angle quotation mark
    "\u00f8",  # o with stroke
    "\u00e9",  # e with acute
)

NAME_FIELDS = ("title", "album", "artist", "albumartist", "artistsort", "albumartistsort", "discsubtitle")


class ToAscii(unittest.TestCase):
    def test_replaces_each_listed_character(self) -> None:
        for char, replacement in CONVERTED.items():
            with self.subTest(char=f"U+{ord(char):04X}"):
                self.assertEqual(ascii.to_ascii(f"a{char}b"), f"a{replacement}b")

    def test_replaces_every_occurrence_in_one_string(self) -> None:
        self.assertEqual(
            ascii.to_ascii("\u201cDon\u2019t\u201d \u2013 \u201cWon\u2019t\u201d\u2026 \u2013 Live\u2026"),
            "\"Don't\" - \"Won't\"... - Live...",
        )

    def test_leaves_every_other_character_as_it_is(self) -> None:
        for char in KEPT:
            with self.subTest(char=f"U+{ord(char):04X}"):
                self.assertEqual(ascii.to_ascii(f"a{char}b"), f"a{char}b")


class Convert(unittest.TestCase):
    def test_the_converted_fields_are_the_seven_name_fields(self) -> None:
        self.assertEqual(set(ascii.FIELDS), set(NAME_FIELDS))

    def test_converts_each_listed_character_in_each_name_field(self) -> None:
        for field in NAME_FIELDS:
            for char, replacement in CONVERTED.items():
                with self.subTest(field=field, char=f"U+{ord(char):04X}"):
                    out = ascii.convert({field: [f"a{char}b"]})
                    self.assertEqual(out, {field: [f"a{replacement}b"]})

    def test_converts_every_value_of_a_multi_valued_field_in_order(self) -> None:
        out = ascii.convert({"artist": ["Guns N\u2019 Roses", "Sin\u00e9ad O\u2019Connor"]})
        self.assertEqual(out, {"artist": ["Guns N' Roses", "Sin\u00e9ad O'Connor"]})

    def test_leaves_unlisted_characters_in_the_name_fields(self) -> None:
        for field in NAME_FIELDS:
            with self.subTest(field=field):
                value = "".join(KEPT)
                self.assertEqual(ascii.convert({field: [value]}), {field: [value]})

    def test_leaves_every_other_field_as_it_is(self) -> None:
        value = "".join(CONVERTED)
        for field in ("genre", "label", "comment", "composer", "musicbrainz_albumid"):
            with self.subTest(field=field):
                self.assertEqual(ascii.convert({field: [value]}), {field: [value]})

    def test_converts_only_the_name_fields_of_a_mixed_dict(self) -> None:
        fields = {"title": ["It\u2019s"], "comment": ["It\u2019s"], "genre": ["drum \u2013 bass"]}
        self.assertEqual(
            ascii.convert(fields),
            {"title": ["It's"], "comment": ["It\u2019s"], "genre": ["drum \u2013 bass"]},
        )

    def test_leaves_the_input_unchanged(self) -> None:
        # A caller that compares the file's tags with the converted ones
        # needs both. Editing the argument in place leaves nothing to compare.
        fields = {"title": ["It\u2019s"], "genre": ["rock"]}
        ascii.convert(fields)
        self.assertEqual(fields, {"title": ["It\u2019s"], "genre": ["rock"]})

    def test_adds_no_field_that_was_not_there(self) -> None:
        self.assertEqual(ascii.convert({}), {})
        self.assertEqual(ascii.convert({"title": ["x"]}), {"title": ["x"]})


if __name__ == "__main__":
    unittest.main()
