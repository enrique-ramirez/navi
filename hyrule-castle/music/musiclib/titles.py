"""When a file and a MusicBrainz track are the same track.

A pair passes on titles that agree and a length within a loose tolerance, or
on a placeholder file title and a length within a tight one. Titles are
compared normalised, so a remaster suffix or a different punctuation habit
does not separate two spellings of one song.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from musiclib import files, mapping
from musiclib.units import first_value

_AGREEING_LENGTH_S = 15.0
_PLACEHOLDER_LENGTH_S = 1.5
_RATIO = 0.8

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_WORD = re.compile(r"\W")
_PLACEHOLDER = re.compile(r"silence|untitled|hiddentrack|data|blank|interview|track\d+|\d+")
_LEADING_NUMBER = re.compile(r"^\d+[ .\-_]*")


def normalise(title: str) -> str:
    """`title` with accents, case, bracketed text, `&` and punctuation removed.

    Letters outside Latin are not transliterated, but every combining mark
    goes, so kana lose their voicing marks.
    """
    decomposed = unicodedata.normalize("NFKD", title)
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    unbracketed = _BRACKETED.sub("", unaccented.casefold())
    return _NON_WORD.sub("", unbracketed.replace("&", "and"))


def agree(a: str, b: str) -> bool:
    """Whether two titles name one song. A title that normalises to nothing agrees with nothing."""
    a, b = normalise(a), normalise(b)
    if not a or not b:
        return False
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= _RATIO


def is_placeholder(title: str) -> bool:
    """Whether `title` is what a ripper or a silent gap leaves, not a song's name."""
    normalised = normalise(title)
    return not normalised or _PLACEHOLDER.fullmatch(normalised) is not None


def file_title(track: files.Track) -> str:
    """The title tag, or the filename less its extension and leading number when the tag is missing or blank."""
    tagged = first_value(track, mapping.PICARD["title"])
    if tagged is not None and tagged.strip():
        return tagged
    return _LEADING_NUMBER.sub("", Path(track.path).stem)


def pair_passes(title: str, file_length: float, mb_title: str, mb_length: float | None) -> bool:
    """Whether a file is the MusicBrainz track, by title and length.

    `mb_length` is `None` for a track nobody has timed: an agreeing title
    passes on its own, and a placeholder has nothing to be compared with.
    """
    if mb_length is None:
        return agree(title, mb_title)
    off = abs(file_length - mb_length)
    if agree(title, mb_title) and off <= _AGREEING_LENGTH_S:
        return True
    return is_placeholder(title) and off <= _PLACEHOLDER_LENGTH_S
