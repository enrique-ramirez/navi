"""Genre composition: the album's custom genre first, then its MusicBrainz
genres restricted to the official list.

Game-music detection, which decides `custom`, is not part of this module;
`compose` only orders and filters what it is given, so it stays small.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from musiclib.mb import VARIOUS_ARTISTS

# Loaded relative to this file rather than the current directory, so it
# still finds the list once the engine is installed to
# /usr/local/lib/musiclib/musiclib/. Kept next to the module rather than
# under a directory named `data`, which the repo's top-level .gitignore
# swallows at any depth.
_DATA_FILE = Path(__file__).parent / "mb-genres.txt"
OFFICIAL = frozenset(_DATA_FILE.read_text(encoding="utf-8").splitlines())

_VGM = "video game music"
_SOUNDTRACK = "soundtrack"
_MIN_VOTE_SHARE = 0.25
_GAME_TAGS = {"video game", "vgm", "game", "game music", _VGM}
_INCOMING_GAME_GENRES = {"game", "video game", "vgm", _SOUNDTRACK}


def _top_quarter(mb_genres: list[dict[str, object]]) -> list[str]:
    """The on-list names with at least `_MIN_VOTE_SHARE` of the top vote count, by count then name."""
    on_list = [(g["name"].lower(), g.get("count") or 0) for g in mb_genres if g["name"].lower() in OFFICIAL]
    if not on_list:
        return []
    line = max(count for _name, count in on_list) * _MIN_VOTE_SHARE
    kept = [(name, count) for name, count in on_list if count >= line]
    kept.sort(key=lambda item: (-item[1], item[0]))
    return [name for name, _count in kept]


def compose(
    custom: str | None,
    mb_genres: list[dict[str, object]],
    file_genres: list[str],
    artist_genres: Callable[[], list[dict[str, object]]] | None = None,
) -> list[str]:
    """The album's genres: `custom` first, then what the sources contribute.

    Sources in order, the first that yields any winning: the release group's
    `mb_genres`, the file's own genres, then `artist_genres()`, which is
    called only when both are empty and there is no `custom`.
    """
    names = _top_quarter(mb_genres)
    if not names:
        # Neither `custom` nor a dropped file `soundtrack` needs removing by
        # hand: both are already off the official list, so the same filter
        # drops them on its own.
        seen: set[str] = set()
        for value in file_genres:
            name = value.strip().casefold()
            if not name or name not in OFFICIAL or name in seen:
                continue
            seen.add(name)
            names.append(name)
    if not names and custom is None and artist_genres is not None:
        names = _top_quarter(artist_genres())
    return names if custom is None else [custom] + names


def composer(release: dict) -> str | None:
    """The album-artist MBID, or `None` for Various Artists or several artists."""
    credit = release.get("artist-credit") or []
    if len(credit) != 1:
        return None
    mbid = credit[0].get("artist", {}).get("id")
    return None if mbid in (None, VARIOUS_ARTISTS) else mbid


def tag_says_game(release_group: dict) -> bool:
    return any(
        tag["name"].casefold() in _GAME_TAGS and (tag.get("count") or 0) > 0
        for tag in release_group.get("tags", [])
    )


def files_say(file_genres: list[str], name: str) -> bool:
    return any(g.casefold() == name for g in file_genres)


def incoming_says_game(incoming: str | None) -> bool:
    return incoming is not None and incoming.casefold() in _INCOMING_GAME_GENRES


def composer_remembered_as(composer: str | None, owner_input: dict, value: str) -> bool:
    if composer is None:
        return False
    return owner_input.get("composers", {}).get(composer) == value


def _secondary_type(release_group: dict, name: str) -> bool:
    return name in release_group.get("secondary-types", [])


def custom_genre(
    release_group: dict,
    file_genres: list[str],
    composer: str | None,
    owner_input: dict,
    incoming: str | None = None,
) -> str | None:
    """`"video game music"`, `"soundtrack"`, or `None`.

    Video game music wins: a game tag, a file already carrying it, an
    incoming game genre, or a composer the owner has remembered as game
    music before, over a soundtrack from the files or the release group's
    secondary type.
    """
    if (
        tag_says_game(release_group)
        or files_say(file_genres, _VGM)
        or incoming_says_game(incoming)
        or composer_remembered_as(composer, owner_input, _VGM)
    ):
        return _VGM
    if files_say(file_genres, _SOUNDTRACK) or _secondary_type(release_group, "Soundtrack"):
        return _SOUNDTRACK
    return None
