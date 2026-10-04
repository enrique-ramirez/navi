"""From a MusicBrainz release to one file's tags.

`docs/music-library.md` *Tags*: exactly the fields it lists, under the names
Picard writes for each format; a release-specific field removed where the
matched release has none; the file's own value kept where MusicBrainz has
none for `DATE`, `ORIGINALDATE`, genre and `DISCSUBTITLE`; curly punctuation
made plain in the name fields; every value the plan sets in NFC; a medium's
title in the disc subtitle and never in the album.

`plan_tags` never touches the disk. It builds those fields under their
neutral names, converts the name fields with `ascii.convert`, maps them to
each format's real keys through `PICARD`, folds in the release-specific
removals, then runs the result through `tagwrite.merge` (so everything the
plan does not mention survives), `residue.strip` (so the denylist is
enforced on the way out, same as `check`), a whitespace clean, and
`residue.strip` a second time - a value the first pass let through can
become denylisted once cleaned (`" Track 3"` -> `"Track 3"`), and planning
it clean the first time keeps a re-plan from proposing a second change on
the next pass.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from musiclib import ascii as ascii_
from musiclib import files, residue, tagwrite

#: Neutral field name -> `{family: real key}`, in the names Picard uses.
#: Track and disc numbers are not here: their shape differs per format
#: (`TRCK` "3/4", Vorbis number and total apart, MP4 a pair), so they are
#: built directly by `_number_fields`. Picard has no MP4 name for the
#: original date; this engine gives it one anyway
#: (`----:com.apple.iTunes:ORIGINALDATE`), since the field still exists on
#: the release group and dropping it on one format only would be inconsistent.
PICARD: dict[str, dict[str, str | None]] = {
    "title": {"id3": "TIT2", "vorbis": "title", "mp4": "\xa9nam", "asf": "Title"},
    "artist": {"id3": "TPE1", "vorbis": "artist", "mp4": "\xa9ART", "asf": "Author"},
    "album": {"id3": "TALB", "vorbis": "album", "mp4": "\xa9alb", "asf": "WM/AlbumTitle"},
    "albumartist": {"id3": "TPE2", "vorbis": "albumartist", "mp4": "aART", "asf": "WM/AlbumArtist"},
    "date": {"id3": "TDRC", "vorbis": "date", "mp4": "\xa9day", "asf": "WM/Year"},
    "originaldate": {"id3": "TDOR", "vorbis": "originaldate",
                     "mp4": "----:com.apple.iTunes:ORIGINALDATE", "asf": "WM/OriginalReleaseTime"},
    "artistsort": {"id3": "TSOP", "vorbis": "artistsort", "mp4": "soar", "asf": "WM/ArtistSortOrder"},
    "albumartistsort": {"id3": "TSO2", "vorbis": "albumartistsort", "mp4": "soaa",
                        "asf": "WM/AlbumArtistSortOrder"},
    "discsubtitle": {"id3": "TSST", "vorbis": "discsubtitle",
                     "mp4": "----:com.apple.iTunes:DISCSUBTITLE", "asf": "WM/SetSubTitle"},
    "genre": {"id3": "TCON", "vorbis": "genre", "mp4": "\xa9gen", "asf": "WM/Genre"},
    "release id": {"id3": "TXXX:MusicBrainz Album Id", "vorbis": "musicbrainz_albumid",
                   "mp4": "----:com.apple.iTunes:MusicBrainz Album Id",
                   "asf": "MusicBrainz/Album Id"},
    "release group id": {"id3": "TXXX:MusicBrainz Release Group Id",
                         "vorbis": "musicbrainz_releasegroupid",
                         "mp4": "----:com.apple.iTunes:MusicBrainz Release Group Id",
                         "asf": "MusicBrainz/Release Group Id"},
    # Picard's "track id" on Vorbis, MP4 and ASF is the recording, not the track.
    "recording id": {"id3": "UFID:http://musicbrainz.org", "vorbis": "musicbrainz_trackid",
                     "mp4": "----:com.apple.iTunes:MusicBrainz Track Id",
                     "asf": "MusicBrainz/Track Id"},
    "release track id": {"id3": "TXXX:MusicBrainz Release Track Id",
                         "vorbis": "musicbrainz_releasetrackid",
                         "mp4": "----:com.apple.iTunes:MusicBrainz Release Track Id",
                         "asf": "MusicBrainz/Release Track Id"},
    "artist id": {"id3": "TXXX:MusicBrainz Artist Id", "vorbis": "musicbrainz_artistid",
                 "mp4": "----:com.apple.iTunes:MusicBrainz Artist Id",
                 "asf": "MusicBrainz/Artist Id"},
    "album artist id": {"id3": "TXXX:MusicBrainz Album Artist Id",
                        "vorbis": "musicbrainz_albumartistid",
                        "mp4": "----:com.apple.iTunes:MusicBrainz Album Artist Id",
                        "asf": "MusicBrainz/Album Artist Id"},
    "label": {"id3": "TPUB", "vorbis": "label", "mp4": "----:com.apple.iTunes:LABEL",
             "asf": "WM/Publisher"},
    "catalognumber": {"id3": "TXXX:CATALOGNUMBER", "vorbis": "catalognumber",
                      "mp4": "----:com.apple.iTunes:CATALOGNUMBER", "asf": "WM/CatalogNo"},
    "barcode": {"id3": "TXXX:BARCODE", "vorbis": "barcode", "mp4": "----:com.apple.iTunes:BARCODE",
               "asf": "WM/Barcode"},
    "asin": {"id3": "TXXX:ASIN", "vorbis": "asin", "mp4": "----:com.apple.iTunes:ASIN", "asf": "ASIN"},
    "releasecountry": {"id3": "TXXX:MusicBrainz Album Release Country", "vorbis": "releasecountry",
                       "mp4": "----:com.apple.iTunes:MusicBrainz Album Release Country",
                       "asf": "MusicBrainz/Album Release Country"},
    "media": {"id3": "TMED", "vorbis": "media", "mp4": "----:com.apple.iTunes:MEDIA", "asf": "WM/Media"},
}

_ITUNES_FREEFORM = "----:com.apple.iTunes:"

#: The time an import added the album, `YYYY-MM-DDTHH:MM` local, as foobar2000 reads `$meta(added)`.
ADDED: dict[str, str] = {"id3": "TXXX:ADDED", "vorbis": "added", "mp4": _ITUNES_FREEFORM + "ADDED", "asf": "ADDED"}

#: Readable name -> `{family: real key}`, for showing a tag by name. The rows
#: after `PICARD`'s are tags the engine never plans, in Picard's keys. The ASF
#: comment is `Description`, the key `files.read` reports for it.
READABLE: dict[str, dict[str, str | None]] = {
    "Title": PICARD["title"],
    "Artist": PICARD["artist"],
    # Each artist of the credit as a value of its own, which a player reads to tell `A & B` the two acts from `A & B` the band.
    "Artists": {"id3": "TXXX:ARTISTS", "vorbis": "artists", "mp4": _ITUNES_FREEFORM + "ARTISTS", "asf": "WM/ARTISTS"},
    "Album": PICARD["album"],
    "Album artist": PICARD["albumartist"],
    "Album artists": {"id3": "TXXX:ALBUMARTISTS", "vorbis": "albumartists", "mp4": _ITUNES_FREEFORM + "ALBUMARTISTS",
                      "asf": "WM/ALBUMARTISTS"},
    "Date": PICARD["date"],
    "Original release date": PICARD["originaldate"],
    "Artist sort order": PICARD["artistsort"],
    "Album artist sort order": PICARD["albumartistsort"],
    "Disc subtitle": PICARD["discsubtitle"],
    "Genre": PICARD["genre"],
    "MusicBrainz release id": PICARD["release id"],
    "MusicBrainz release group id": PICARD["release group id"],
    "MusicBrainz recording id": PICARD["recording id"],
    "MusicBrainz track id": PICARD["release track id"],
    "MusicBrainz artist id": PICARD["artist id"],
    "MusicBrainz album artist id": PICARD["album artist id"],
    "Label": PICARD["label"],
    "Catalogue number": PICARD["catalognumber"],
    "Barcode": PICARD["barcode"],
    "ASIN": PICARD["asin"],
    "Release country": PICARD["releasecountry"],
    "Media": PICARD["media"],
    "Track number": {"id3": "TRCK", "vorbis": "tracknumber", "mp4": "trkn", "asf": "WM/TrackNumber"},
    "Disc number": {"id3": "TPOS", "vorbis": "discnumber", "mp4": "disk", "asf": "WM/PartOfSet"},
    "Composer": {"id3": "TCOM", "vorbis": "composer", "mp4": "\xa9wrt", "asf": "WM/Composer"},
    "Composer sort order": {"id3": "TSOC", "vorbis": "composersort", "mp4": "soco",
                            "asf": "WM/ComposerSortOrder"},
    "Lyricist": {"id3": "TEXT", "vorbis": "lyricist", "mp4": _ITUNES_FREEFORM + "LYRICIST", "asf": "WM/Writer"},
    "Conductor": {"id3": "TPE3", "vorbis": "conductor", "mp4": _ITUNES_FREEFORM + "CONDUCTOR",
                  "asf": "WM/Conductor"},
    "Comment": {"id3": "COMM::eng", "vorbis": "comment", "mp4": "\xa9cmt", "asf": "Description"},
    "Lyrics": {"id3": "USLT::eng", "vorbis": "lyrics", "mp4": "\xa9lyr", "asf": "WM/Lyrics"},
    "BPM": {"id3": "TBPM", "vorbis": "bpm", "mp4": "tmpo", "asf": "WM/BeatsPerMinute"},
    "ReplayGain track gain": {"id3": "TXXX:REPLAYGAIN_TRACK_GAIN", "vorbis": "replaygain_track_gain",
                              "mp4": _ITUNES_FREEFORM + "REPLAYGAIN_TRACK_GAIN", "asf": "ReplayGain/Track Gain"},
    "ReplayGain track peak": {"id3": "TXXX:REPLAYGAIN_TRACK_PEAK", "vorbis": "replaygain_track_peak",
                              "mp4": _ITUNES_FREEFORM + "REPLAYGAIN_TRACK_PEAK", "asf": "ReplayGain/Track Peak"},
    "ReplayGain album gain": {"id3": "TXXX:REPLAYGAIN_ALBUM_GAIN", "vorbis": "replaygain_album_gain",
                              "mp4": _ITUNES_FREEFORM + "REPLAYGAIN_ALBUM_GAIN", "asf": "ReplayGain/Album Gain"},
    "ReplayGain album peak": {"id3": "TXXX:REPLAYGAIN_ALBUM_PEAK", "vorbis": "replaygain_album_peak",
                              "mp4": _ITUNES_FREEFORM + "REPLAYGAIN_ALBUM_PEAK", "asf": "ReplayGain/Album Peak"},
    "Compilation": {"id3": "TCMP", "vorbis": "compilation", "mp4": "cpil", "asf": "WM/IsCompilation"},
    "Added": ADDED,
}

_BY_KEY: dict[str, dict[str, str]] = {
    family: {key: name for name, row in READABLE.items() if (key := row.get(family)) is not None}
    for family in ("id3", "vorbis", "mp4", "asf")
}


def readable_name(family: str, key: str) -> str | None:
    """The readable name of `key` as `files.read` reports it in `family`, or `None` if it has none."""
    return _BY_KEY.get(family, {}).get(key)


#: The release-specific fields (docs *Tags*): the six named there, and the
#: MusicBrainz release-level IDs (the release, release group and album
#: artist always carry one on a real release, so in practice only the six
#: ever come out empty and get removed).
RELEASE_SPECIFIC = ("label", "catalognumber", "barcode", "asin", "releasecountry", "media",
                    "release id", "release group id", "album artist id")

#: A disc folder that says nothing about the disc beyond its position
#: (`CD2`, `Disc 2`, `Bonus`, `bonus cd`, ...).
_GENERIC_ONLY = re.compile(r"(?i)^(?:(?:cd|disc|disk)\s*\d+|bonus(?:\s*(?:cd|disc))?)$")

#: The generic marker and its separator, stripped off the front of a
#: descriptive folder name (`"CD2 - Live at Budokan"` -> `"Live at Budokan"`).
_LEADING_MARKER = re.compile(r"(?i)^(?:cd|disc|disk)\s*\d+\s*[-:]?\s*")


@dataclass(frozen=True)
class FileTags:
    """One file's planned tag state, and everything a reviewer needs to see about it.

    `target` is the full real-key tag state, ready for `tagwrite.write`.
    `removals` covers both the release-specific removals and the residue
    `residue.strip` enforces, each with the rule that took it. `problems`
    stops the plan being written at all (currently: no `DATE` anywhere).
    `holds` keeps the album out of `certain`/`auto` without failing the plan.
    `suggested_discsubtitle` is never written to `target` itself.
    """

    target: dict[str, list[str]]
    removals: list[residue.Removal]
    problems: list[str]
    holds: list[str]
    suggested_discsubtitle: str | None


def join_credit(credits: list[dict], name_key: str) -> str:
    """A MusicBrainz `artist-credit` list joined the way Picard writes it.

    `name_key` is `"name"` for the credited name (what `ARTIST`/`ALBUMARTIST`
    hold) or `"sort-name"` for the sort fields; either way, the join phrases
    between artists are the same. Public: `plan` joins the release's sort
    names with it, and `artists` and `batch.identify` join credited names.
    """
    out = ""
    for credit in credits:
        name = credit[name_key] if name_key == "name" else credit["artist"]["sort-name"]
        out += name + credit.get("joinphrase", "")
    return out


def release_date(release: dict) -> str | None:
    """The release's own date, else its release group's first, else `None`."""
    group = release.get("release-group") or {}
    return release.get("date") or group.get("first-release-date") or None


def _credit_ids(credits: list[dict]) -> list[str]:
    return [credit["artist"]["id"] for credit in credits]


def _kept_or_mb(neutral: str, mb_values: list[str], track: files.Track, family: str) -> list[str] | None:
    """`mb_values` where MusicBrainz has any, else the file's current value for `neutral`.

    `DATE`, `ORIGINALDATE`, genre and `DISCSUBTITLE` all fall back this way.
    `None` means neither has one, so the field is left out of the plan
    entirely rather than written empty.
    """
    if mb_values:
        return list(mb_values)
    key = PICARD[neutral].get(family)
    if key is None:
        return None
    file_values = track.tags.get(key)
    return list(file_values) if file_values else None


def _number_fields(family: str, track_pair: tuple[int, int], disc_pair: tuple[int, int]) -> dict[str, list[str]]:
    """Track and disc number/total, under each format's real keys."""
    (number, total), (disc, discs) = track_pair, disc_pair
    if family == "id3":
        return {"TRCK": [f"{number}/{total}"], "TPOS": [f"{disc}/{discs}"]}
    if family == "vorbis":
        return {"tracknumber": [str(number)], "tracktotal": [str(total)],
                "discnumber": [str(disc)], "disctotal": [str(discs)]}
    if family == "mp4":
        return {"trkn": [files.mp4_pair_text(number, total)],
                "disk": [files.mp4_pair_text(disc, discs)]}
    if family == "asf":
        # Picard has no ASF name for the track total (decision: a WMA carries
        # none), so only the number itself is written; the disc pair keeps
        # ID3's TRCK/TPOS shape under Picard's own WM/PartOfSet name.
        return {"WM/TrackNumber": [str(number)], "WM/PartOfSet": [f"{disc}/{discs}"]}
    return {}


def _clean_whitespace(family: str, tags: dict[str, list[str]]) -> dict[str, list[str]]:
    """Trim, collapse runs of spaces, and drop what that empties.

    Skips exactly what `check`'s `whitespace` rule skips, so a cleaned plan
    never disagrees with `check` run over the file it writes: a rating, the
    kept-as-written fields and a value holding a line break (all three,
    `tagwrite.keeps_whitespace`, plus `tagwrite.has_line_break`), and the
    shapes that are not text at all - digests, MP4 pairs, embedded pictures
    (`tagwrite.is_non_text_key`).
    """
    cleaned: dict[str, list[str]] = {}
    for key, values in tags.items():
        if tagwrite.is_non_text_key(family, key):
            cleaned[key] = values
            continue
        kept_values = []
        for value in values:
            if tagwrite.keeps_whitespace(family, key, value) or tagwrite.has_line_break(value):
                kept_values.append(value)
                continue
            scrubbed = re.sub(r" {2,}", " ", value.strip())
            if scrubbed:
                kept_values.append(scrubbed)
        if kept_values:
            cleaned[key] = kept_values
    return cleaned


def _suggest_discsubtitle(folder: str | None) -> str | None:
    """The disc-subtitle suggestion: `folder` less its generic disc marker, or `None`.

    `None` both when there is no folder and when the folder is generic-only
    (`"CD2"`, `"Bonus Disc"`, ...): a name that says nothing about the disc
    is not a suggestion, it is the same marker `disc_folder` already told the
    caller about.
    """
    if not folder or _GENERIC_ONLY.match(folder.strip()):
        return None
    suggestion = _LEADING_MARKER.sub("", folder, count=1).strip(" -:")
    return suggestion or None


def with_titles_of(release: dict, pseudo: dict) -> dict:
    """`release` with its album title and every track title taken from `pseudo`.

    `pseudo` has the same tracks on each medium. Every other field, the IDs
    included, stays `release`'s.
    """
    media = []
    for medium, other in zip(release["media"], pseudo["media"]):
        tracks = [{**track, "title": theirs["title"]} for track, theirs in zip(medium.get("tracks", []), other["tracks"])]
        media.append({**medium, "tracks": tracks} if "tracks" in medium else medium)
    return {**release, "title": pseudo["title"], "media": media}


def plan_tags(track: files.Track, release: dict, medium_position: int, track_position: int,
             genres: list[str], disc_folder: str | None = None, *, number: int | None = None,
             total: int | None = None, disc: int | None = None, discs: int | None = None,
             credited_name: Callable[[list[dict]], str] | None = None, added: str | None = None) -> FileTags:
    """The tag plan for one track of `release`, at `medium_position`/`track_position` (both 1-based).

    Track position 0 is the medium's pregap. `number`, `total`, `disc` and
    `discs` are what gets written as the track and disc pairs; each falls
    back to the position or count the release gives. `credited_name` turns a
    credit into the text of `ARTIST` and `ALBUMARTIST`; the credit as joined
    when it is not given. `added` is written as `ADDED`, replacing one the file
    has in any case; without it the file's own is kept as it is.
    """
    family = track.family
    media = release["media"]
    medium = media[medium_position - 1]
    tracks_on_medium = medium["tracks"]
    mb_track = medium["pregap"] if track_position == 0 else tracks_on_medium[track_position - 1]

    track_credit = mb_track.get("artist-credit") or release["artist-credit"]
    release_credit = release["artist-credit"]
    name_of = credited_name or (lambda credit: join_credit(credit, "name"))

    fields: dict[str, list[str]] = {
        "title": [mb_track["title"]],
        "artist": [name_of(track_credit)],
        "album": [release["title"]],
        "albumartist": [name_of(release_credit)],
        "artistsort": [join_credit(track_credit, "sort-name")],
        "albumartistsort": [join_credit(release_credit, "sort-name")],
        "release id": [release["id"]],
        "release group id": [release["release-group"]["id"]],
        "recording id": [mb_track["recording"]["id"]],
        "release track id": [mb_track["id"]],
        "artist id": _credit_ids(track_credit),
        "album artist id": _credit_ids(release_credit),
    }

    label_info = release.get("label-info") or []
    labels = [li["label"]["name"] for li in label_info if li.get("label") and li["label"].get("name")]
    catalog_numbers = [li["catalog-number"] for li in label_info
                       if li.get("catalog-number") and li["catalog-number"] != "[none]"]
    if labels:
        fields["label"] = labels
    if catalog_numbers:
        fields["catalognumber"] = catalog_numbers
    if release.get("barcode"):
        fields["barcode"] = [release["barcode"]]
    if release.get("asin"):
        fields["asin"] = [release["asin"]]
    if release.get("country"):
        fields["releasecountry"] = [release["country"]]
    if medium.get("format"):
        fields["media"] = [medium["format"]]

    problems: list[str] = []
    mb_date = release_date(release)
    date_values = _kept_or_mb("date", [mb_date] if mb_date else [], track, family)
    if date_values:
        fields["date"] = date_values
    else:
        problems.append("no DATE: neither the matched release nor the file has one, "
                        "so the album folder cannot be named")

    first_release_date = release["release-group"].get("first-release-date")
    orig_values = _kept_or_mb("originaldate", [first_release_date] if first_release_date else [],
                              track, family)
    if orig_values:
        fields["originaldate"] = orig_values

    # `genres` is final, from `genres.compose`, which already decided whether
    # the file's own genres survive: an empty list here means none, not "ask
    # the file", so it plans the field removed rather than falling back.
    if genres:
        fields["genre"] = list(genres)

    holds: list[str] = []
    suggested_discsubtitle = None
    disc_values = _kept_or_mb("discsubtitle", [medium["title"]] if medium.get("title") else [],
                              track, family)
    if disc_values:
        fields["discsubtitle"] = disc_values
    else:
        suggested_discsubtitle = _suggest_discsubtitle(disc_folder)
        if suggested_discsubtitle:
            holds.append(f"disc subtitle: {disc_folder!r} looks descriptive; "
                        "needs confirming before it becomes DISCSUBTITLE")

    fields = ascii_.convert(fields)

    planned: dict[str, list[str] | None] = {}
    for neutral, values in fields.items():
        key = PICARD[neutral].get(family)
        if key is not None:
            planned[key] = [ascii_.nfc(value) for value in values]
    planned.update(_number_fields(family, (track_position if number is None else number,
                                           len(tracks_on_medium) if total is None else total),
                                  (medium_position if disc is None else disc,
                                   len(media) if discs is None else discs)))

    removals: list[residue.Removal] = []
    for neutral in RELEASE_SPECIFIC:
        if neutral in fields:
            continue
        key = PICARD[neutral].get(family)
        if key is None:
            continue
        planned[key] = None
        if key in track.tags:
            removals.append(residue.Removal(key, None, f"the matched release has no {neutral}"))

    if "genre" not in fields:
        genre_key = PICARD["genre"].get(family)
        if genre_key is not None:
            planned[genre_key] = None
            if genre_key in track.tags:
                removals.append(residue.Removal(genre_key, None, "no genres for the album"))

    if added is not None:
        planned.update({key: None for key in track.tags if tagwrite.is_added_field(family, key)})
        planned[ADDED[family]] = [added]

    merged = tagwrite.merge(track, planned)
    target, residue_removals = residue.strip(family, merged)
    removals.extend(residue_removals)

    cleaned = _clean_whitespace(family, target)
    target, cleanup_removals = residue.strip(family, cleaned)
    removals.extend(cleanup_removals)

    return FileTags(target=target, removals=removals, problems=problems, holds=holds,
                    suggested_discsubtitle=suggested_discsubtitle)
