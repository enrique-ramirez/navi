"""The composers MusicBrainz gives each recording of a release.

A recording's composers are the artists of every `composer` relationship on
each work it has a `performance` relationship to, in the order MusicBrainz
lists the works and then the relationships, each artist once. Every other
relationship type is ignored, on the work, the recording or the release.
"""

from __future__ import annotations

from musiclib import artists, mapping
from musiclib import ascii as ascii_


def _tracks(works: dict):
    for medium in works.get("media") or []:
        if medium.get("pregap"):
            yield medium["pregap"]
        yield from medium.get("tracks") or []


def _composer_artists(recording: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for relation in recording.get("relations") or []:
        if relation.get("type") != "performance" or not relation.get("work"):
            continue
        for credit in relation["work"].get("relations") or []:
            artist = credit.get("artist")
            if credit.get("type") == "composer" and artist and artist.get("id"):
                found.setdefault(artist["id"], artist)
    return list(found.values())


def composers_by_recording(works: dict, mb) -> dict[str, list[tuple[str, str]]]:
    """Each recording's ordered `(name, sort name)` composers, for the recordings that have any.

    A name that is not Latin becomes the artist's primary English alias when
    there is one (`artists.romanized`); the sort name stays as MusicBrainz gives it.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for track in _tracks(works):
        recording = track.get("recording") or {}
        people = _composer_artists(recording)
        if not people:
            continue
        out[recording["id"]] = [
            (artists.romanized(artist["name"], artist["id"], mb), artist.get("sort-name") or artist["name"])
            for artist in people]
    return out


def tags(people: list[tuple[str, str]], family: str) -> dict[str, list[str]]:
    return {
        mapping.READABLE[readable][family]: [ascii_.nfc(value) for value in values]
        for readable, values in (("Composer", [name for name, _ in people]),
                                 ("Composer sort order", [sort for _, sort in people]))}
