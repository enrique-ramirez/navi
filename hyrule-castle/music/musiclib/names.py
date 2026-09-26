"""Folder and file names, from `docs/music-library.md` *Layout*."""

from __future__ import annotations

import re
import unicodedata

# The fallback article list in docs/music-library.md *Artist folder*, in the
# order it lists them. L' is handled separately, in _split_leading_article.
_FALLBACK_ARTICLES = ("The", "A", "An", "Los", "Las", "La", "El", "Die", "Der", "Das", "Les", "Le")
_FALLBACK_CASEFOLD = {article.casefold() for article in _FALLBACK_ARTICLES}

# One prefix at most, in the table's order: EP, Single, Mixtape, Live.
_PREFIX_ORDER = ("EP", "Single", "Mixtape/Street", "Live")
_PREFIX_LABEL = {"EP": "EP", "Single": "Single", "Mixtape/Street": "Mixtape", "Live": "Live"}


def sanitize(s: str) -> str:
    """Replace the characters Windows and FAT32 cannot hold in a name."""
    s = s.replace(": ", " - ").replace(":", "-").replace("/", "-").replace("\\", "-")
    s = re.sub(r"[?*<>|]", "", s).replace('"', "''")
    s = " ".join(s.split())
    return s.rstrip(". ")


def letter(folder: str) -> str:
    """The first character of `folder`, decomposed and uppercased, or `#`."""
    if not folder:
        return "#"
    base = unicodedata.normalize("NFKD", folder[0])[0].upper()
    return base if "A" <= base <= "Z" else "#"


def _split_leading_article(name: str) -> tuple[str, str] | None:
    """The leading fallback article and the rest of `name`, or `None`.

    `L'` has no space after it, so `str.split(" ")` can never carry it to a
    "rest, article" folder on its own; it is matched as a two-character
    prefix instead of a word.
    """
    if len(name) > 2 and name[1] == "'" and name[:2].casefold() == "l'":
        return name[:2], name[2:]
    words = name.split(" ", 1)
    if len(words) == 2 and words[0].casefold() in _FALLBACK_CASEFOLD:
        return words[0], words[1]
    return None


def artist_folder(name: str, sort_name: str | None = None, known: bool = True, compilation: bool = False) -> str:
    """The artist folder for `name`, following `docs/music-library.md` *Artist folder*."""
    if compilation:
        return "Various Artists"
    if known:
        folder = name
        if sort_name is not None:
            words = name.split(" ", 1)
            if len(words) == 2:
                first, rest = words
                # The sort name is used only when it does nothing but move a
                # leading article to the end, and that word is itself an
                # article: a sort name that merely puts the surname first
                # (Sabina, Joaquin) must not be mistaken for one.
                if sort_name == f"{rest}, {first}" and first.casefold() in _FALLBACK_CASEFOLD:
                    folder = sort_name
        return sanitize(folder)
    split = _split_leading_article(name)
    folder = f"{split[1]}, {split[0]}" if split else name
    return sanitize(folder)


def album_folder(
    date: str,
    title: str,
    primary_type: str | None = None,
    secondary_types: tuple[str, ...] = (),
) -> str:
    """The album folder: `(YYYY) Title` or `(YYYY) [Prefix] Title`."""
    year = date[:4]
    prefix = None
    for candidate in _PREFIX_ORDER:
        if candidate == primary_type or candidate in secondary_types:
            prefix = _PREFIX_LABEL[candidate]
            break
    name = f"[{prefix}] {title}" if prefix else title
    return sanitize(f"({year}) {name}")


def disc_folder(position: int, medium_count: int) -> str | None:
    """`CDn` for a multi-medium release, or `None` for a single medium."""
    if medium_count <= 1:
        return None
    return f"CD{position}"


def track_filename(number: int, title: str, ext: str, tracks_on_medium: int) -> str:
    """`NN. Title.ext`, with three digits on a medium of 100 tracks or more."""
    digits = 3 if tracks_on_medium >= 100 else 2
    return sanitize(f"{number:0{digits}d}. {title}") + f".{ext}"
