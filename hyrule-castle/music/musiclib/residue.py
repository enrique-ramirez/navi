"""The residue denylist: what rippers, encoders and download sites left behind.

The spec's *Residue denylist* section is the source for every table below. A
name from that section is written here exactly as the section spells it; the
code only adds the per-format key it resolves to (`TXXX:<name>` on MP3, the
name itself in Vorbis and ASF, `----:<mean>:<name>` on MP4, whatever `<mean>`
is) and the case-folding needed because real files spell the same name in
several cases.
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

from musiclib import tagwrite


class Removal(NamedTuple):
    """One value, or one whole field (`value` is `None`), taken out by `rule`."""

    key: str
    value: str | None
    rule: str


# --- "Removed whole, whatever the value" --------------------------------
#
# A free-form name here matches wherever a free-form name can be carried:
# an MP3 TXXX description, a Vorbis comment field, an MP4 `----` freeform
# atom's name, or an ASF attribute name - all folded to lower case, since
# MP4 in particular carries these in mixed case in real files. A name the
# spec's table writes as "TXXX `name`" is narrower than that: it only ever
# showed up in the MP3 dump, and the sets below stop it at MP3, or MP3 and
# the one or two other formats the row names.
_FREEFORM: dict[str, str] = {
    "ripping tool": "ripping tool",
    "rip date": "rip date",
    "releaser": "releaser",
    "supplier": "supplier",
    "#helium comment": "#helium comment",
    "encoded by": "encoded by",
    "encodedby": "encoded by",
    "encoded-by": "encoded by",
    "encoder": "encoder",
    "encoder settings": "encoder settings",
    "encoding params": "encoder settings",
    "encoding": "encoder settings",
    "software": "software",
    "tool": "software",
    "tool name": "software",
    "tool version": "software",
    "pztageditor info": "tag editor",
    "metadatacreator": "tag editor",
    "creator": "tag editor",
    "encodingtime": "timestamps",
    "encoding time": "timestamps",
    "taggingtime": "timestamps",
    "tagging time": "timestamps",
    "logfile": "logfile",
    "notes": "notes",
    "url": "links",
    "www": "links",
    "wwwartist": "links",
    "web": "links",
    "gg": "links",
    "related": "links",
    "buycdurl": "links",
    "purl": "links",
    "episodeid": "episodeid",
    "account_id": "purchase",
    "purchase_date": "purchase",
    "_purchasedate": "purchase",
    "mp3gain_minmax": "mp3gain_minmax",
    "cuesheet": "cuesheet",
    "itunmovi": "iTunes blobs",
    "itunnorm": "iTunes blobs",
    "itunsmpb": "iTunes blobs",
    "itunes_cddb_1": "itunes_cddb",
    "itunes_cddb_ids": "itunes_cddb",
    "itunes_cddb_tracknumber": "itunes_cddb",
    # Picard's Vorbis name for encoder settings, written with no space.
    "encodersettings": "encoder settings",
    # AccurateRip verification output the ripper wrote in.
    "accurateripresult": "accurateripresult",
}

# Denylist rows write "TXXX `name`" or "(TXXX and Vorbis)" for a name that
# does not travel to every format the way an unqualified name does. A name
# absent from all three sets below applies wherever `_FREEFORM` matches it.
_TXXX_ONLY = {
    "account_id", "encodingtime", "pztageditor info", "url", "web",
    "software", "tool", "logfile", "episodeid", "cuesheet", "mp3gain_minmax",
}
_TXXX_AND_VORBIS = {
    "ripping tool", "itunes_cddb_1", "itunes_cddb_ids", "itunes_cddb_tracknumber",
    "accurateripresult",
}
_TXXX_AND_VORBIS_MP4 = {"itunmovi", "itunnorm", "itunsmpb"}


def _freeform_rule(family: str, name: str) -> str | None:
    """The `_FREEFORM` rule for `name`, or `None` if this row stops at a
    narrower set of formats than `family` is in."""
    name = name.lower()
    rule = _FREEFORM.get(name)
    if rule is None:
        return None
    if name in _TXXX_ONLY and family != "id3":
        return None
    if name in _TXXX_AND_VORBIS and family not in ("id3", "vorbis"):
        return None
    if name in _TXXX_AND_VORBIS_MP4 and family not in ("id3", "vorbis", "mp4"):
        return None
    return rule


#: The native, non-freeform names Picard gives these rows in MP4 and ASF
#: (its tag mapping appendix): a file an encoder or player wrote itself
#: carries them here, never in a freeform atom or attribute.
_MP4_NATIVE_WHOLE = {"\xa9too": "encoded by"}
_ASF_NATIVE_WHOLE = {
    "wm/encodedby": "encoded by",
    "wm/encodingsettings": "encoder settings",
    "wm/toolname": "software",
    "wm/toolversion": "software",
    "wm/encodingtime": "timestamps",
}

#: `MusicMatch_*`, `musicbrainz_*` and `Media Jukebox: *` in the COMM table
#: below are prefixes, not exact names; kept apart from `_FREEFORM` because
#: they only ever showed up in a COMM description, never a free-form field.
_COMM_EXACT: dict[str, str] = {
    "itunnorm": "COMM iTunes",
    "itunsmpb": "COMM iTunes",
    "itunpgap": "COMM iTunes",
    "id3v1 comment": "COMM ID3v1 Comment",
    "album artist": "COMM ALBUM ARTIST",
    "descriptor": "COMM Descriptor",
    "c0": "COMM c0 and Media Jukebox",
    "totaldiscs": "COMM Picard fields",
    "totaltracks": "COMM Picard fields",
    "ensemble": "COMM Picard fields",
    "sourcemedia": "COMM Picard fields",
    "source medium": "COMM Picard fields",
    "releasecountry": "COMM Picard fields",
    "release date": "COMM Picard fields",
    "catalog number": "COMM Picard fields",
}
_COMM_PREFIX: list[tuple[str, str]] = [
    ("itunes_cddb_", "COMM iTunes"),
    ("musicmatch_", "COMM MusicMatch"),
    ("media jukebox:", "COMM c0 and Media Jukebox"),
    ("musicbrainz_", "COMM Picard fields"),
]

#: `GEOB` is removed by its description, either whole or by a fixed list.
_GEOB_EXACT: dict[str, str] = {"RealJukebox:Metadata": "GEOB RealJukebox"}
_GEOB_SET = {"SfAcidChunk", "SfAcidBeatMapInfo", "SfAcidBeatMapMarkers", "SfMarkers"}


def _comm_desc(key: str) -> str:
    """The description out of a `COMM:<desc>:<lang>` HashKey.

    `<desc>` can itself hold a colon (`Media Jukebox: Date`), so the
    language - always the last three-letter piece - is split off from the
    right, not the description split off from the left.
    """
    rest = key[len("COMM:"):]
    desc, _, _lang = rest.rpartition(":")
    return desc


def _comm_whole_rule(key: str) -> str | None:
    desc = _comm_desc(key).lower()
    if desc in _COMM_EXACT:
        return _COMM_EXACT[desc]
    for prefix, rule in _COMM_PREFIX:
        if desc.startswith(prefix):
            return rule
    return None


def _id3_whole_rule(key: str) -> str | None:
    """The rule that removes an ID3 frame whole, or `None` to keep looking."""
    if key.startswith("TXXX:"):
        desc = key[len("TXXX:"):]
        if desc == "":
            return "empty TXXX description"
        return _freeform_rule("id3", desc)
    if key == "TENC":
        return "encoded by"
    if key == "TSSE":
        return "encoder"
    frame_id = key.split(":", 1)[0]
    if len(frame_id) == 4 and frame_id[0] == "W":
        return "W*** frames"
    if key.startswith("PRIV:"):
        return "PRIV"
    if key.startswith("GEOB:"):
        desc = key[len("GEOB:"):]
        if desc in _GEOB_EXACT:
            return _GEOB_EXACT[desc]
        if desc in _GEOB_SET:
            return "GEOB Sony Acid"
        return None
    if key.startswith("USER:"):
        return "USER"
    if key.startswith("COMM:"):
        return _comm_whole_rule(key)
    return None


def _whole_rule(family: str, key: str) -> str | None:
    """The rule that removes `key` whole, or `None` to keep looking."""
    if family == "id3":
        return _id3_whole_rule(key)
    if family == "vorbis":
        return _freeform_rule(family, key)
    if family == "asf":
        native = _ASF_NATIVE_WHOLE.get(key.lower())
        if native is not None:
            return native
        return _freeform_rule(family, key)
    if family == "mp4":
        native = _MP4_NATIVE_WHOLE.get(key)
        if native is not None:
            return native
        if key.startswith("----:"):
            return _freeform_rule(family, key.rsplit(":", 1)[-1])
        # `purl` is the one freeform name Picard also gives a bare MP4 atom.
        if key.lower() == "purl":
            return _freeform_rule(family, "purl")
        return None
    return None


def _is_free_text(family: str, key: str) -> bool:
    """A field the docs call free-text: kept, but stripped value by value."""
    if family == "id3":
        if key.startswith("TXXX:"):
            return key[len("TXXX:"):].lower() in ("comment", "description")
        if key.startswith("COMM:"):
            desc = _comm_desc(key).lower()
            return desc in ("", "comments")
        return False
    if family == "vorbis":
        return key in ("comment", "description")
    if family == "mp4":
        # `desc` is not qualified TXXX in the spec row, so MP4's native
        # description atom is free-text too, alongside the comment one.
        return key in ("\xa9cmt", "desc")
    if family == "asf":
        return key == "Description"
    return False


# --- "Removed value by value, only in free-text fields" -----------------

_RIPPED_BY = re.compile(r"(?i)\b(ripped|rip|encoded)\s+(by|with)\b")
_URL = re.compile(r"(?i)https?://|www\.")
_DOMAIN = re.compile(r"(?i)\b[\w-]+\.(com|net|org|info|fm|ru|it)\b")
#: "Equals" is exact everywhere but the TCOP list, so these keep their case.
_EQUALS = {"RG Aniboters", "pollodav", "Unicode cue-file"}
_STARTS_WITH = ("Collected by ", "Davis [ICQ:")
_TRACK_NUMBER = re.compile(r"(?i)track\s+\d+")
_FREEDB = (re.compile(r"(?i)^freedbID\s*:"), re.compile(r"(?i)^YEAR:\s*\d{4}\s+ID3G:"))


def _pattern_rule(value: str) -> str | None:
    """Which *Removed value by value* pattern `value` matches, if any."""
    if value.strip() == "":
        return "blank"
    if _RIPPED_BY.search(value):
        return "ripped by"
    if _URL.search(value) or _DOMAIN.search(value):
        return "url"
    if value in _EQUALS:
        return "equals"
    if value.startswith(_STARTS_WITH):
        return "starts with"
    if _TRACK_NUMBER.fullmatch(value):
        return "track number"
    if any(p.match(value) for p in _FREEDB):
        return "freedb"
    return None


# --- "Removed by value in other fields" ----------------------------------

_TCOP_VALUES = {
    "", "metalgods.es", "flawl3ss rg", "www.mundodelmp3.com", "lomasrankiao.com",
    "latestfreedownload.org", "www.viperial.com", "by gioca",
}


def _tcop_match(value: str) -> str | None:
    return "TCOP" if value.strip().lower() in _TCOP_VALUES else None


def _core_radio_match(value: str) -> str | None:
    # Exact, unlike the TCOP list: the spec's CORE RADIO and TOWN bullets
    # carry no "ignoring case" wording of their own.
    return "CORE RADIO" if value == "CORE RADIO" else None


def _town_match(value: str) -> str | None:
    return "TOWN" if value == "[Pirate Shovon]" else None


def _blank_lyrics_match(value: str) -> str | None:
    """The one residue rule for lyrics: blank or whitespace only.

    No other *Removed value by value* pattern runs on lyrics: those were
    written for rippers' comments, and would eat a "Track 3" chorus or a
    spoken URL in a verse.
    """
    return "blank" if value.strip() == "" else None


def _other_field_matcher(family: str, key: str) -> Callable[[str], str | None] | None:
    """A by-value matcher for a field that is otherwise kept, or `None`."""
    if tagwrite.is_lyrics_field(family, key):
        return _blank_lyrics_match
    if family == "id3":
        if key == "TCOP":
            return _tcop_match
        if key == "TOWN":
            return _town_match
        if key == "TPUB":  # organization's MP3 field
            return _core_radio_match
        if key.startswith("TXXX:") and key[len("TXXX:"):].lower() == "source":
            return _core_radio_match
        return None
    if family == "vorbis":
        if key in ("source", "organization"):
            return _core_radio_match
        if key == "copyright":
            return _tcop_match
        return None
    if family == "mp4":
        if key == "cprt":
            return _tcop_match
        # Picard's label is MP4 LABEL; ORGANIZATION and SOURCE are its own.
        if key.startswith("----:") and key.rsplit(":", 1)[-1].lower() in (
            "source", "organization", "label",
        ):
            return _core_radio_match
        return None
    if family == "asf":
        if key == "Copyright":
            return _tcop_match
        if key == "WM/Publisher":  # Picard's ASF name for organization/label
            return _core_radio_match
        return None
    return None


def strip(family: str, tags: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[Removal]]:
    """`tags` with every field and value in the residue denylist taken out.

    Returns `(kept, removals)`; `tags` itself is never modified. A listed
    field goes whole, with one `Removal` recording it (`value` is `None`,
    since no value decided it). A free-text field, or a field the denylist
    only strips specific values from, is filtered value by value; if
    nothing survives, the field disappears rather than being kept empty.
    Everything else - including any field or value the denylist does not
    name - passes through untouched.
    """
    kept: dict[str, list[str]] = {}
    removals: list[Removal] = []
    for key, values in tags.items():
        rule = _whole_rule(family, key)
        if rule is not None:
            removals.append(Removal(key, None, rule))
            continue

        matcher = _pattern_rule if _is_free_text(family, key) else _other_field_matcher(family, key)
        if matcher is None:
            kept[key] = values
            continue

        surviving = []
        for value in values:
            value_rule = matcher(value)
            if value_rule is None:
                surviving.append(value)
            else:
                removals.append(Removal(key, value, value_rule))
        if surviving:
            kept[key] = surviving

    return kept, removals
