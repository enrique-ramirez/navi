"""Genre composition: the album's custom genre first, then its MusicBrainz
genres restricted to the official list.

Game-music detection, which decides `custom`, is not part of this module;
`compose` only orders and filters what it is given, so it stays small.
"""

from __future__ import annotations

from pathlib import Path

# Loaded relative to this file rather than the current directory, so it
# still finds the list once the engine is installed to
# /usr/local/lib/musiclib/musiclib/. Kept next to the module rather than
# under a directory named `data`, which the repo's top-level .gitignore
# swallows at any depth.
_DATA_FILE = Path(__file__).parent / "mb-genres.txt"
OFFICIAL = frozenset(_DATA_FILE.read_text(encoding="utf-8").splitlines())

_VGM = "video game music"
_SOUNDTRACK = "soundtrack"
_VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
_GAME_TAGS = {"video game", "vgm", "game", "game music", _VGM}
_INCOMING_GAME_GENRES = {"game", "video game", "vgm", _SOUNDTRACK}


def compose(custom: str | None, mb_genres: list[dict[str, object]], file_genres: list[str]) -> list[str]:
    """The album's genres: `custom` first, then what `mb_genres` contributes.

    With no MusicBrainz genres at all, the file's own genres survive as they
    came, `custom` moved to the front. With some, only the ones on `OFFICIAL`
    survive, ranked by vote count, and the file's genres play no part.
    """
    if not mb_genres:
        # No MusicBrainz genres at all is not the same as MusicBrainz genres
        # that all fail the official-list filter: here the file's genres
        # survive, unchecked against the list.
        kept = list(file_genres)
        if custom is None:
            return kept
        kept = [g for g in kept if g.casefold() != custom.casefold()]
        if custom == _VGM:
            # `video game music` replaces a file `soundtrack`.
            kept = [g for g in kept if g.casefold() != _SOUNDTRACK]
        return [custom] + kept

    on_list = [(g["name"].lower(), g.get("count") or 0) for g in mb_genres if g["name"].lower() in OFFICIAL]
    on_list.sort(key=lambda item: (-item[1], item[0]))
    names = [name for name, _count in on_list]
    return [custom] + names if custom is not None else names


def composer(release: dict) -> str | None:
    """The album-artist MBID, or `None` for Various Artists or several artists."""
    credit = release.get("artist-credit") or []
    if len(credit) != 1:
        return None
    mbid = credit[0].get("artist", {}).get("id")
    return None if mbid in (None, _VARIOUS_ARTISTS) else mbid


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
