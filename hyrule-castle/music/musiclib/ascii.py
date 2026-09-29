"""Typographic punctuation in the name fields, and Unicode NFC for text.

The table is built from code points, not literal characters, so the file
stays plain ASCII: every one of these has a plain-ASCII look-alike close
enough that a literal curly quote in the source would be easy to misread.
"""

from __future__ import annotations

import unicodedata

FIELDS = ("title", "album", "artist", "albumartist", "artistsort", "albumartistsort", "discsubtitle")

_CONVERSIONS = {
    chr(0x2019): "'",  # right single quotation mark
    chr(0x2018): "'",  # left single quotation mark
    chr(0x201C): '"',  # left double quotation mark
    chr(0x201D): '"',  # right double quotation mark
    chr(0x2026): "...",  # horizontal ellipsis
    chr(0x2010): "-",  # hyphen
    chr(0x2013): "-",  # en dash
    chr(0x2014): "-",  # em dash
}


def nfc(s: str) -> str:
    """`s` in Unicode NFC (not NFKC: compatibility forms such as U+2161 stay as they are)."""
    return unicodedata.normalize("NFC", s)


def to_ascii(s: str) -> str:
    """Replace every listed character in `s` and compose it to NFC; leave everything else as it is."""
    for char, replacement in _CONVERSIONS.items():
        s = s.replace(char, replacement)
    return nfc(s)


def convert(fields: dict[str, list[str]]) -> dict[str, list[str]]:
    """A copy of `fields` with `to_ascii` applied to the values of the name fields."""
    result = dict(fields)
    for field in FIELDS:
        if field in fields:
            result[field] = [to_ascii(value) for value in fields[field]]
    return result
