"""Whether the artist the files carry is the artist a release credits.

The files' artist is the album artist tag, else the artist tag, whichever
value most files carry. It agrees with a credit when it agrees, as titles do,
with the credit as joined, a credited name, or the own name or sort name of a
credited artist; failing those, with an alias of type Artist name or Legal
name from the artist's lookup. A search hint is a way to find an artist and
never a name for one.
"""

from __future__ import annotations

import unicodedata
from collections import Counter

from musiclib import mapping, titles
from musiclib.mb import VARIOUS_ARTISTS, MusicBrainz, MusicBrainzError, MusicBrainzUnavailable
from musiclib.units import Unit, first_value

_NAMING_ALIASES = ("Artist name", "Legal name")


def track_artist(track) -> str | None:
    return first_value(track, mapping.PICARD["albumartist"]) or first_value(track, mapping.PICARD["artist"])


def files_artist(unit: Unit) -> str | None:
    """The artist most files carry, first seen winning a tie, or `None` when no file carries one."""
    values = (track_artist(t) for t in unit.tracks)
    counts = Counter(v.strip() for v in values if v is not None and v.strip())
    return counts.most_common(1)[0][0] if counts else None


def _differing_track_artists(unit: Unit) -> bool:
    """Whether no file has an album artist and the track artists are not all one."""
    if any(first_value(t, mapping.PICARD["albumartist"]) for t in unit.tracks):
        return False
    artists = {a.strip().casefold() for t in unit.tracks if (a := first_value(t, mapping.PICARD["artist"]))}
    return len(artists) > 1


def _credited_names(credit: list[dict]) -> list[str]:
    names = [mapping.join_credit(credit, "name")]
    for part in credit:
        artist = part.get("artist", {})
        names += [n for n in (part.get("name"), artist.get("name"), artist.get("sort-name")) if n]
    return names


def _aliases(artist_id: str | None, client: MusicBrainz) -> list[dict]:
    """The aliases MusicBrainz lists for an artist.

    An artist MusicBrainz has no record of has none; MusicBrainz being down is
    not the same and is raised.
    """
    if not artist_id:
        return []
    try:
        return client.artist(artist_id).get("aliases", [])
    except MusicBrainzUnavailable:
        raise
    except MusicBrainzError:
        return []


def _alias_names(credit: list[dict], client: MusicBrainz):
    """The naming aliases of each credited artist, looked up one artist at a time."""
    for part in credit:
        for alias in _aliases(part.get("artist", {}).get("id"), client):
            if alias.get("type") in _NAMING_ALIASES and alias.get("name"):
                yield alias["name"]


def agrees(unit: Unit, release: dict, client: MusicBrainz) -> bool:
    """Whether the files' artist agrees with `release`'s credit. Nothing to compare is no."""
    wanted = files_artist(unit)
    if wanted is None:
        return False
    credit = release.get("artist-credit") or []
    if any(titles.agree(wanted, name) for name in _credited_names(credit)):
        return True
    if any(part.get("artist", {}).get("id") == VARIOUS_ARTISTS for part in credit) and _differing_track_artists(unit):
        return True
    return any(titles.agree(wanted, name) for name in _alias_names(credit, client))


def is_latin(name: str) -> bool:
    """Whether every letter of `name` is a Latin one, by its Unicode name; digits and punctuation do not count."""
    return all(unicodedata.name(c, "").startswith("LATIN") for c in name if c.isalpha())


def english_name(artist_id: str | None, client: MusicBrainz) -> str | None:
    """The artist's primary alias with locale exactly `en`, or `None`."""
    for alias in _aliases(artist_id, client):
        if alias.get("primary") and alias.get("locale") == "en" and alias.get("name"):
            return alias["name"]
    return None


def _romanized(name: str, artist_id: str | None, client: MusicBrainz) -> str:
    if is_latin(name):
        return name
    return english_name(artist_id, client) or name


def credited_name(credit: list[dict], client: MusicBrainz) -> str:
    """The credit as joined for `ARTIST` and `ALBUMARTIST`: each credited name, in its English alias where not Latin."""
    return "".join(_romanized(part["name"], part.get("artist", {}).get("id"), client) + part.get("joinphrase", "")
                   for part in credit)


def own_name(credit: list[dict], client: MusicBrainz) -> str:
    """The credit as joined for the artist folder: each artist's own name, in its English alias where not Latin."""
    return "".join(_romanized(part["artist"]["name"], part["artist"].get("id"), client) + part.get("joinphrase", "")
                   for part in credit)
