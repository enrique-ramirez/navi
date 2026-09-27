"""The residue denylist: what rippers, encoders and download sites left behind.

The spec's *Residue denylist* section is the
source for every table here. Each row of the spec has at least one sample
below, named after the row, so a failure says which row broke.

`strip` works on a `Track.tags`-shaped dict: real keys, Vorbis in lower case,
ID3 by mutagen's HashKey. MP3 keys are read back from a real file wherever
their shape is not obvious, because a hand-typed `PRIV` key that no file can
produce would pass a test and match nothing in the library.
"""

from __future__ import annotations

import copy
import tempfile
import unittest

from mutagen.id3 import Frames

from musiclib import residue
from tests import builders

_TMP: tempfile.TemporaryDirectory | None = None
_KEYS: dict[str, str] = {}


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    _TMP.cleanup()


def key(spec) -> str:
    """A key as written, or the key mutagen reads back for a frame."""
    if isinstance(spec, str):
        return spec
    if spec.HashKey not in _KEYS:
        _KEYS[spec.HashKey] = builders.id3_key(_TMP.name, spec)
    return _KEYS[spec.HashKey]


def TXXX(desc):
    return Frames["TXXX"](encoding=3, desc=desc, text=["x"])


def COMM(desc, lang="eng"):
    return Frames["COMM"](encoding=3, lang=lang, desc=desc, text=["x"])


def GEOB(desc):
    return Frames["GEOB"](encoding=3, mime="application/octet-stream",
                          filename="", desc=desc, data=b"\x00\x01")


def PRIV(owner):
    return Frames["PRIV"](owner=owner, data=b"\x00\x01\x02")


def LINK(frame_id, url="http://gamemp3s.net/"):
    if frame_id == "WXXX":
        return Frames["WXXX"](encoding=3, desc="", url=url)
    return Frames[frame_id](url=url)


def USER():
    return Frames["USER"](encoding=3, lang="eng", text="Terms of use: do not share")


def USLT(lang="eng"):
    return Frames["USLT"](encoding=3, lang=lang, desc="", text="x")


ID3 = "id3"
VORBIS = "vorbis"
MP4 = "mp4"
ASF = "asf"
ITUNES = "----:com.apple.iTunes:"

#: *Removed whole, whatever the value*: (row, family, key or frame, a value).
#: Where a row names a field without saying TXXX, the name is the Vorbis one.
WHOLE = [
    ("ripping tool", VORBIS, "ripping tool", "EAC"),
    ("ripping tool", ID3, TXXX("ripping tool"), "dBpoweramp"),
    ("rip date", VORBIS, "rip date", "2009-03-14"),
    ("releaser", VORBIS, "releaser", "SecToid from A.C."),
    ("supplier", VORBIS, "supplier", "Team wWs"),
    ("#helium comment", VORBIS, "#helium comment", "Ripped by Z-Unit"),
    ("encoded by", VORBIS, "encoded by", "Exact Audio Copy"),
    ("encoded by", VORBIS, "encodedby", "iTunes v7.7.1.11"),
    ("encoded by", VORBIS, "encoded-by", "#gamemp3s"),
    ("encoded by", ID3, TXXX("encoded by"), "by DrStandBy"),
    ("encoded by", ID3, "TENC", "Exact Audio Copy"),
    ("encoder", VORBIS, "encoder", "LAME"),
    ("encoder", ID3, TXXX("encoder"), "Lavf52.54.0"),
    ("encoder", ID3, "TSSE", "Easy CD-DA Extractor"),
    ("encoder settings", VORBIS, "encoder settings", "-V0"),
    ("encoder settings", VORBIS, "encoding params", "vbr"),
    ("encoder settings", VORBIS, "encoding", "q8"),
    ("encoder settings", ID3, TXXX("encoding"), "-b 320"),
    ("software", ID3, TXXX("software"), "Lavf52.94.0"),
    ("software", ID3, TXXX("tool"), "Media Center"),
    ("software", VORBIS, "tool name", "Media Center"),
    ("software", VORBIS, "tool version", "12.0"),
    ("tag editor", ID3, TXXX("pztageditor info"), "stamp"),
    ("tag editor", VORBIS, "metadatacreator", "stamp"),
    ("tag editor", VORBIS, "creator", "stamp"),
    ("timestamps", ID3, TXXX("encodingtime"), "2009-03-14 10:00"),
    ("timestamps", VORBIS, "encoding time", "2009-03-14 10:00"),
    ("timestamps", VORBIS, "taggingtime", "2009-03-14 10:00"),
    ("timestamps", VORBIS, "tagging time", "2009-03-14 10:00"),
    ("logfile", ID3, TXXX("logfile"), "Exact Audio Copy V0.99 prebeta 5 ..."),
    ("notes", VORBIS, "notes", "Split with CUE Splitter"),
    ("notes", ID3, TXXX("notes"), "Split with CUE Splitter"),
    ("links", ID3, TXXX("url"), "http://gamemp3s.net/"),
    ("links", VORBIS, "www", "http://example.org/"),
    ("links", VORBIS, "wwwartist", "http://example.org/"),
    ("links", ID3, TXXX("web"), "http://example.org/"),
    ("links", VORBIS, "gg", "x"),
    ("links", VORBIS, "related", "x"),
    ("links", VORBIS, "buycdurl", "http://example.org/"),
    ("links", VORBIS, "purl", "http://example.org/"),
    *[("W*** frames", ID3, LINK(fid), "a link")
      for fid in ("WXXX", "WCOM", "WOAR", "WOAF", "WOAS", "WPUB", "WFED", "WORS",
                  # Not in the row's list, but the row says every W*** frame.
                  "WCOP", "WPAY")],
    ("episodeid", ID3, TXXX("episodeid"), "LOMASRANKIAO.COM"),
    ("purchase", ID3, TXXX("account_id"), "someone@example.org"),
    ("purchase", VORBIS, "purchase_date", "2012-01-01 10:00:00"),
    ("purchase", VORBIS, "_purchasedate", "2012-01-01 10:00:00"),
    ("mp3gain_minmax", ID3, TXXX("mp3gain_minmax"), "091,208"),
    ("cuesheet", ID3, TXXX("cuesheet"), 'FILE "x.wav" WAVE'),
    ("empty TXXX description", ID3, TXXX(""), "////"),
    ("iTunes blobs", ID3, TXXX("itunmovi"), "<plist/>"),
    ("iTunes blobs", ID3, TXXX("itunnorm"), " 00000312"),
    ("iTunes blobs", ID3, TXXX("itunsmpb"), " 00000000 00000210"),
    ("iTunes blobs", VORBIS, "itunnorm", " 00000312"),
    ("iTunes blobs", VORBIS, "itunsmpb", " 00000000 00000210"),
    # The row says MP4 as well. iTunes writes these atoms in mixed case.
    ("iTunes blobs", MP4, ITUNES + "iTunSMPB", " 00000000 00000210"),
    ("iTunes blobs", MP4, ITUNES + "iTunNORM", " 00000312"),
    ("iTunes blobs", MP4, ITUNES + "iTunMOVI", "<plist/>"),
    ("COMM iTunes", ID3, COMM("iTunNORM"), " 00000312"),
    ("COMM iTunes", ID3, COMM("iTunSMPB", "XXX"), " 00000000 00000210"),
    ("COMM iTunes", ID3, COMM("iTunPGAP", "spa"), "0"),
    ("COMM iTunes", ID3, COMM("iTunes_CDDB_1"), "A10B3E0C+..."),
    ("COMM iTunes", ID3, COMM("iTunes_CDDB_TrackNumber"), "3"),
    ("COMM ID3v1 Comment", ID3, COMM("ID3v1 Comment"), "0"),
    ("COMM ALBUM ARTIST", ID3, COMM("ALBUM ARTIST"), "Nine Inch Nails"),
    ("COMM Descriptor", ID3, COMM("Descriptor"), "MusicMatch"),
    ("COMM MusicMatch", ID3, COMM("MusicMatch_Mood"), "Brooding"),
    ("COMM MusicMatch", ID3, COMM("MusicMatch_Preference"), "Excellent"),
    ("COMM MusicMatch", ID3, COMM("MusicMatch_Tempo"), "Medium"),
    ("PRIV", ID3, PRIV("WM/MediaClassPrimaryID"), "digest"),
    ("PRIV", ID3, PRIV("ZuneAlbumArtistMediaID"), "digest"),
    ("PRIV", ID3, PRIV("Google/StoreLabelCode"), "digest"),
    ("PRIV", ID3, PRIV("PeakValue"), "digest"),
    ("PRIV", ID3, PRIV("AverageLevel"), "digest"),
    ("GEOB RealJukebox", ID3, GEOB("RealJukebox:Metadata"), "digest"),
    ("GEOB Sony Acid", ID3, GEOB("SfAcidChunk"), "digest"),
    ("GEOB Sony Acid", ID3, GEOB("SfAcidBeatMapInfo"), "digest"),
    ("GEOB Sony Acid", ID3, GEOB("SfAcidBeatMapMarkers"), "digest"),
    ("GEOB Sony Acid", ID3, GEOB("SfMarkers"), "digest"),
    ("USER", ID3, USER(), "Terms of use: do not share"),
    ("COMM c0 and Media Jukebox", ID3, COMM("c0"), "x"),
    ("COMM c0 and Media Jukebox", ID3, COMM("Media Jukebox: Date", "rus"), "x"),
    # "Ignoring case", in the row itself, hence the mixed spellings.
    ("COMM Picard fields", ID3, COMM("TOTALDISCS"), "2"),
    ("COMM Picard fields", ID3, COMM("totaltracks"), "12"),
    ("COMM Picard fields", ID3, COMM("Ensemble"), "x"),
    ("COMM Picard fields", ID3, COMM("sourcemedia"), "CD"),
    ("COMM Picard fields", ID3, COMM("Source Medium"), "CD"),
    ("COMM Picard fields", ID3, COMM("releasecountry"), "US"),
    ("COMM Picard fields", ID3, COMM("release date"), "1999"),
    ("COMM Picard fields", ID3, COMM("Catalog Number"), "halo 14"),
    ("COMM Picard fields", ID3, COMM("musicbrainz_albumid"), "x"),
    ("COMM Picard fields", ID3, COMM("MusicBrainz_TrackId"), "x"),
    ("itunes_cddb", VORBIS, "itunes_cddb_1", "x"),
    ("itunes_cddb", VORBIS, "itunes_cddb_ids", "x"),
    ("itunes_cddb", VORBIS, "itunes_cddb_tracknumber", "3"),
    ("itunes_cddb", ID3, TXXX("itunes_cddb_1"), "x"),
    ("itunes_cddb", ID3, TXXX("itunes_cddb_ids"), "x"),
    ("itunes_cddb", ID3, TXXX("itunes_cddb_tracknumber"), "3"),
    # A name the row does not qualify applies to every format's free-form
    # name, matched ignoring case: TXXX, Vorbis, an MP4 `----` atom and an
    # ASF attribute, in the case taggers actually write. A row that says
    # "(TXXX and Vorbis)" stops there, so MP4 `RIPPING TOOL` is in KEPT.
    ("encoded by", MP4, ITUNES + "Encoded By", "Exact Audio Copy"),
    ("encoded by", ID3, TXXX("Encoded By"), "Exact Audio Copy"),
    ("encoder", ASF, "Encoder", "LAME"),
    ("rip date", ASF, "Rip Date", "2009-03-14"),
    ("rip date", ID3, TXXX("rip date"), "2009-03-14"),
    ("rip date", MP4, ITUNES + "RIP DATE", "2009-03-14"),
    ("releaser", ID3, TXXX("releaser"), "SecToid from A.C."),
    ("releaser", MP4, ITUNES + "RELEASER", "SecToid from A.C."),
    ("releaser", ASF, "Releaser", "SecToid from A.C."),
    ("supplier", ID3, TXXX("supplier"), "H3X"),
    ("supplier", MP4, ITUNES + "SUPPLIER", "H3X"),
    ("supplier", ASF, "Supplier", "H3X"),
    ("#helium comment", ID3, TXXX("#helium comment"), "Ripped by Z-Unit"),
    ("#helium comment", MP4, ITUNES + "#HELIUM COMMENT", "Ripped by Z-Unit"),
    ("#helium comment", ASF, "#helium comment", "Ripped by Z-Unit"),
    ("encoder", MP4, ITUNES + "ENCODER", "LAME"),
    ("encoder settings", MP4, ITUNES + "encoding params", "vbr"),
    ("encoder settings", ASF, "Encoding", "q8"),
    ("software", ID3, TXXX("tool name"), "Media Center"),
    ("software", MP4, ITUNES + "tool version", "12.0"),
    ("tag editor", ID3, TXXX("creator"), "stamp"),
    ("tag editor", MP4, ITUNES + "MetadataCreator", "stamp"),
    ("tag editor", ASF, "creator", "stamp"),
    ("timestamps", ID3, TXXX("tagging time"), "2009-03-14 10:00"),
    ("timestamps", MP4, ITUNES + "TaggingTime", "2009-03-14 10:00"),
    ("timestamps", ASF, "encoding time", "2009-03-14 10:00"),
    ("notes", MP4, ITUNES + "NOTES", "Split with CUE Splitter"),
    ("notes", ASF, "Notes", "Split with CUE Splitter"),
    ("links", ID3, TXXX("purl"), "http://example.org/"),
    ("links", MP4, ITUNES + "WWW", "http://example.org/"),
    ("links", ASF, "buycdurl", "http://example.org/"),
    ("purchase", MP4, ITUNES + "purchase_date", "2012-01-01 10:00:00"),
    ("purchase", ASF, "_purchasedate", "2012-01-01 10:00:00"),
    # The same fields under the native name Picard gives them in MP4 and ASF
    # (Picard's tag mapping appendix: encodedby, encodersettings,
    # podcasturl). A file tagged by iTunes or Windows Media Player carries
    # its encoder here and nowhere else, so matching only free-form names
    # misses it.
    ("encoded by", MP4, "\xa9too", "iTunes v7.7.1.11"),
    ("encoded by", ASF, "WM/EncodedBy", "Exact Audio Copy"),
    ("encoder settings", ASF, "WM/EncodingSettings", "Lavf52.54.0"),
    # Picard's Vorbis name for encodersettings has no space.
    ("encoder settings", VORBIS, "encodersettings", "-V0"),
    ("links", MP4, "purl", "http://www.gamemp3s.net/"),
    # No Picard mapping for these three. They are ASF's own spelling of the
    # row's `tool name`, `tool version` and `encoding time`.
    ("software", ASF, "WM/ToolName", "Media Center"),
    ("software", ASF, "WM/ToolVersion", "12.0.0.0"),
    ("timestamps", ASF, "WM/EncodingTime", "128745012000000000"),
    # The row says TXXX and Vorbis, ignoring case, and foobar2000 and EAC
    # write it in both cases.
    ("accurateripresult", ID3, TXXX("AccurateRipResult"), "AccurateRip: Accurate (confidence 5)  [37DEB629]"),
    ("accurateripresult", ID3, TXXX("ACCURATERIPRESULT"), "AccurateRip: Not present in database"),
    ("accurateripresult", VORBIS, "accurateripresult", "AccurateRip: Accurate (confidence 5)  [37DEB629]"),
]

#: Every free-text field the spec names, and a value in it that must stay.
FREE_TEXT = [
    (VORBIS, "comment"),
    (VORBIS, "description"),
    (ID3, "TXXX:comment"),
    (ID3, "COMM::eng"),
    (ID3, "COMM::XXX"),
    (ID3, "COMM::spa"),
    (ID3, "COMM::rus"),
    (ID3, "COMM::esl"),
    (ID3, "COMM:Comments:eng"),
    (MP4, "\xa9cmt"),
    (ASF, "Description"),
    # `description` is not qualified TXXX, so it is every format's
    # description: MP4 carries it in the native `desc` atom.
    (ID3, "TXXX:description"),
    (MP4, "desc"),
]
LINER_NOTE = "Recorded at Abbey Road in 1999. Mixed by Alan Moulder"

#: *Removed value by value*: (pattern, one value it removes). Spread across
#: the free-text fields in turn, so each field is exercised by several rules.
PATTERNS = [
    ("blank", ""),
    ("blank", "   "),
    ("ripped by", "Ripped by Z-Unit"),
    ("ripped by", "rip with EAC"),
    ("ripped by", "Encoded  by DrStandBy"),
    ("url", "https://sonixgvn.net/"),
    ("url", "get more at WWW.gamemp3s"),
    ("url", "gamemp3s.net"),
    ("url", "visit mp3ddl.com today"),
    ("url", "radio.fm"),
    ("url", "warez.ru"),
    ("url", "musica.it"),
    ("url", "old-rips.info"),
    ("url", "scene.org"),
    ("url", "http://example.org"),
    ("equals", "RG Aniboters"),
    ("equals", "pollodav"),
    ("equals", "Unicode cue-file"),
    ("starts with", "Collected by DJ Night"),
    ("starts with", "Davis [ICQ:123456]"),
    ("track number", "Track 3"),
    ("track number", "track  12"),
    ("freedb", "freedbID: 8a0b3c0c"),
    ("freedb", "YEAR: 1999 ID3G: 17"),
]
PATTERN_SAMPLES = [
    (row, *FREE_TEXT[i % len(FREE_TEXT)], value)
    for i, (row, value) in enumerate(PATTERNS)
] + [
    ("url", MP4, "\xa9cmt", "https://sonixgvn.net/"),
    ("url", ASF, "Description", "www.gamemp3s.net"),
    ("url", MP4, "desc", "www.gamemp3s.net"),
]

#: *Removed by value in other fields*: (row, family, key, removed, kept).
OTHER_FIELDS = [
    ("CORE RADIO", VORBIS, "source", "CORE RADIO", "CD"),
    ("CORE RADIO", VORBIS, "organization", "CORE RADIO", "Nothing Records"),
    ("TCOP", ID3, "TCOP", "", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "MetalGods.ES", "℗ 1999 Nothing Records"),
    # "Ignoring case and surrounding spaces", from the spec.
    ("TCOP", ID3, "TCOP", "  flawl3ss rg ", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "WwW.MundoDelMp3.CoM", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "LOMASRANKIAO.COM", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "LatestFreeDownload.Org", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "www.viperial.com", "℗ 1999 Nothing Records"),
    ("TCOP", ID3, "TCOP", "By Gioca", "℗ 1999 Nothing Records"),
    ("TOWN", ID3, "TOWN", "[Pirate Shovon]", "Enrique"),
    # The TCOP list is the copyright field's list in every format, and
    # organization is TPUB on MP3.
    ("TCOP", VORBIS, "copyright", "FLAWL3SS RG", "\u2117 1999 Nothing Records"),
    ("TCOP", MP4, "cprt", " www.viperial.com", "\u2117 1999 Nothing Records"),
    ("CORE RADIO", ID3, "TPUB", "CORE RADIO", "Nothing Records"),
    ("CORE RADIO", ID3, "TXXX:source", "CORE RADIO", "CD"),
    # The same two rules in MP4 and ASF. organization is Picard's label,
    # which it writes as MP4 `LABEL` and ASF `WM/Publisher`.
    ("CORE RADIO", MP4, ITUNES + "SOURCE", "CORE RADIO", "CD"),
    ("CORE RADIO", MP4, ITUNES + "ORGANIZATION", "CORE RADIO", "Nothing Records"),
    ("CORE RADIO", MP4, ITUNES + "LABEL", "CORE RADIO", "Nothing Records"),
    ("CORE RADIO", ASF, "WM/Publisher", "CORE RADIO", "Nothing Records"),
    ("TCOP", ASF, "Copyright", "MetalGods.ES", "\u2117 1999 Nothing Records"),
]

#: Things that look like residue and are not on the list. Each one is kept.
KEPT = [
    # Title, artist and album are never matched against a pattern. "Team"
    # and "scene" alone would hit real titles.
    (ID3, "TIT2", ["Scene"]),
    (ID3, "TPE1", ["Team Sleep"]),
    (ID3, "TALB", ["Track 12"]),
    (VORBIS, "title", ["Ripped by the Tide"]),
    (VORBIS, "artist", ["www.example.com"]),
    (VORBIS, "album", ["Collected by Night"]),
    (VORBIS, "lyrics", ["encoded with love, see scene.org"]),
    (MP4, "\xa9nam", ["Track 3"]),
    # Fields next to listed ones that are not listed themselves.
    (ID3, "TPUB", ["Nothing Records"]),
    (ID3, "TXXX:source", ["CD"]),
    (VORBIS, "copyright", ["\u2117 1999 Nothing Records"]),
    (MP4, "cprt", ["\u2117 1999 Nothing Records"]),
    (MP4, "cprt", ["www.some-label.com"]),
    (MP4, ITUNES + "REPLAYGAIN_TRACK_GAIN", ["-6.20 dB"]),
    (ASF, "WM/Genre", ["industrial rock"]),
    (ASF, "Author", ["Nine Inch Nails"]),
    # Only Description is free text on ASF: a title or lyrics that look like
    # residue are still a title and lyrics.
    (ASF, "Title", ["Track 3"]),
    (ASF, "WM/Lyrics", ["Ripped by the storm, see scene.org"]),
    # Starts with is case-sensitive, as the spec words it; not asserted either way.
    (ID3, "TCOP", ["℗ 1999 Nothing Records"]),
    # TCOP is removed by listed value only. An unlisted site name waits for
    # `check` to show it and the owner to add it.
    (ID3, "TCOP", ["www.some-label.com"]),
    (ID3, "TMED", ["CD"]),
    (ID3, "TXXX:CATALOGNUMBER", ["halo 14"]),
    (ID3, "TXXX:RELEASECOUNTRY", ["US"]),
    (ID3, "TXXX:MusicBrainz Album Id", ["8b2c6d0c-0000-4000-8000-000000000001"]),
    (ID3, "TXXX:REPLAYGAIN_TRACK_GAIN", ["-6.20 dB"]),
    (VORBIS, "source", ["CD"]),
    (VORBIS, "organization", ["Nothing Records"]),
    (VORBIS, "tracktotal", ["12"]),
    (MP4, ITUNES + "MusicBrainz Album Id", ["8b2c6d0c-0000-4000-8000-000000000001"]),
    # Liner notes in every free-text field.
    *[(family, k, [LINER_NOTE]) for family, k in FREE_TEXT],
    # The patterns are anchored where the spec anchors them.
    (ID3, "COMM::eng", ["Track 3 is the single"]),
    (ID3, "COMM::eng", ["Bootleg. Collected by a fan"]),
    (ID3, "COMM::eng", ["pollodav was here"]),
    # *Seen, not listed*.
    (ID3, "COMM::eng", ["VampirE"]),
    (VORBIS, "comment", ["VampirE"]),
    (ID3, COMM("Fefiloff"), ["x"]),
    (ID3, COMM("Songs-DB_Tempo"), ["120"]),
    (ID3, COMM("CDDB Disc ID"), ["8a0b3c0c"]),
    (ID3, COMM("playcount:quodlibet@lastfm"), ["3"]),
    (ID3, GEOB("CREAF_LCID"), ["digest"]),
    # A name the table qualifies TXXX is removed from TXXX only. The same
    # name in Vorbis, MP4 or ASF is off the list, even holding a link.
    (VORBIS, "cuesheet", ['FILE "x.wav" WAVE']),
    (VORBIS, "url", ["http://gamemp3s.net/"]),
    (VORBIS, "web", ["http://example.org/"]),
    (VORBIS, "software", ["Lavf52.94.0"]),
    (VORBIS, "tool", ["Media Center"]),
    (VORBIS, "logfile", ["Exact Audio Copy V0.99 prebeta 5 ..."]),
    (VORBIS, "episodeid", ["LOMASRANKIAO.COM"]),
    (VORBIS, "account_id", ["someone@example.org"]),
    (VORBIS, "mp3gain_minmax", ["091,208"]),
    (VORBIS, "pztageditor info", ["stamp"]),
    (VORBIS, "encodingtime", ["2009-03-14 10:00"]),
    (MP4, ITUNES + "cuesheet", ['FILE "x.wav" WAVE']),
    (ASF, "software", ["Lavf52.94.0"]),
    # A row that names its formats stops at them.
    (MP4, ITUNES + "RIPPING TOOL", ["EAC"]),
    (ASF, "ripping tool", ["EAC"]),
    (MP4, ITUNES + "iTunes_CDDB_1", ["x"]),
    (ASF, "itunnorm", [" 00000312"]),
    (MP4, ITUNES + "AccurateRipResult", ["AccurateRip: Accurate (confidence 5)  [37DEB629]"]),
    (ASF, "AccurateRipResult", ["AccurateRip: Accurate (confidence 5)  [37DEB629]"]),
    # Picard's `website` is ASF `WM/AuthorURL`, but the table has no
    # `website`, and its `url` is qualified TXXX.
    (ASF, "WM/AuthorURL", ["http://example.org/"]),
    # "Equals" is exact. Only the TCOP list says ignoring case and spaces.
    (VORBIS, "comment", ["RG ANIBOTERS"]),
    (VORBIS, "comment", ["  rg aniboters "]),
    (ID3, "COMM::eng", ["Pollodav"]),
    (MP4, "\xa9cmt", ["Unicode cue-file "]),
    (VORBIS, "source", ["Core Radio"]),
    (VORBIS, "organization", [" CORE RADIO"]),
    (ID3, "TOWN", ["[pirate shovon]"]),
]

#: What every sample file carries besides the field under test, so a strip
#: that throws everything away does not pass.
CONTEXT = {ID3: {"TIT2": ["Hurt"]}, VORBIS: {"title": ["Hurt"]}, MP4: {"\xa9nam": ["Hurt"]},
           ASF: {"Title": ["Hurt"]}}


def removed(removals) -> list:
    return sorted(((r.key, r.value) for r in removals), key=repr)


class RemovedWhole(unittest.TestCase):
    def test_every_listed_field_goes_whole_and_is_recorded_once_with_its_rule(self):
        for row, family, spec, value in WHOLE:
            k = key(spec)
            with self.subTest(row=row, key=k):
                tags = {**CONTEXT[family], k: [value, "a second value"]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, CONTEXT[family])
                # One record for the field, not one per value: the value is
                # None because nothing about the value decided it.
                self.assertEqual(removed(removals), [(k, None)])
                self.assertIsInstance(removals[0].rule, str)
                self.assertTrue(removals[0].rule.strip())


class RemovedByValue(unittest.TestCase):
    def test_each_pattern_removes_its_value_from_a_free_text_field(self):
        for row, family, k, value in PATTERN_SAMPLES:
            with self.subTest(row=row, key=k, value=value):
                tags = {**CONTEXT[family], k: [LINER_NOTE, value]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, {**CONTEXT[family], k: [LINER_NOTE]})
                self.assertEqual(removed(removals), [(k, value)])
                self.assertTrue(removals[0].rule.strip())

    def test_a_list_of_empty_strings_is_blank(self):
        # COMM::XXX holds 776 of these. mutagen writes no COMM with empty
        # text, so this key is typed rather than read back from a file.
        kept, removals = residue.strip(ID3, {**CONTEXT[ID3], "COMM::XXX": ["", ""]})
        self.assertEqual(kept, CONTEXT[ID3])
        self.assertEqual(removed(removals), [("COMM::XXX", ""), ("COMM::XXX", "")])

    def test_a_free_text_field_with_nothing_left_disappears_and_each_value_is_recorded(self):
        tags = {**CONTEXT[VORBIS], "comment": ["Track 3", "https://sonixgvn.net/"]}
        kept, removals = residue.strip(VORBIS, tags)
        self.assertEqual(kept, CONTEXT[VORBIS])
        self.assertEqual(removed(removals), sorted(
            [("comment", "Track 3"), ("comment", "https://sonixgvn.net/")], key=repr))

    def test_listed_values_go_from_source_organization_tcop_and_town(self):
        for row, family, k, value, keep in OTHER_FIELDS:
            with self.subTest(row=row, key=k, value=value):
                tags = {**CONTEXT[family], k: [keep, value]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, {**CONTEXT[family], k: [keep]})
                self.assertEqual(removed(removals), [(k, value)])
                self.assertTrue(removals[0].rule.strip())

    def test_a_tcop_holding_only_a_site_name_disappears(self):
        kept, removals = residue.strip(ID3, {**CONTEXT[ID3], "TCOP": ["FLAWL3SS RG"]})
        self.assertEqual(kept, CONTEXT[ID3])
        self.assertEqual(removed(removals), [("TCOP", "FLAWL3SS RG")])


class Kept(unittest.TestCase):
    """The "and nothing else" half of the residue rules."""

    def test_fields_and_values_off_the_list_are_kept(self):
        for family, spec, values in KEPT:
            k = key(spec)
            with self.subTest(key=k, values=values):
                tags = {**CONTEXT[family], k: list(values)}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, tags)
                self.assertEqual(list(removals), [])

    def test_the_tags_passed_in_are_not_changed(self):
        # The plan compares before with after. A strip that edits its input
        # in place leaves the "before" side already stripped.
        tags = {
            **CONTEXT[ID3],
            "TSSE": ["LAME"],
            "COMM::eng": [LINER_NOTE, "Track 3"],
            "TCOP": ["FLAWL3SS RG"],
        }
        before = copy.deepcopy(tags)
        residue.strip(ID3, tags)
        self.assertEqual(tags, before)


#: Every field this engine calls lyrics, in the formats that can carry it.
#: SYLT is lyrics too, but `Track.tags` holds it as a repr of its
#: (text, time) pairs, which is never blank, so it has no sample here.
LYRICS = [
    (ID3, USLT()),
    (ID3, USLT("XXX")),
    (ID3, TXXX("LYRICS")),
    (ID3, TXXX("unsyncedlyrics")),
    (ID3, TXXX("UNSYNCED LYRICS")),
    (VORBIS, "lyrics"),
    (VORBIS, "unsyncedlyrics"),
    (VORBIS, "unsynced lyrics"),
    (VORBIS, "unsynchronised lyrics"),
    (VORBIS, "unsynchronized lyrics"),
    (MP4, "\xa9lyr"),
    (MP4, ITUNES + "UNSYNCED LYRICS"),
    (MP4, ITUNES + "lyrics"),
    (ASF, "WM/Lyrics"),
    (ASF, "Unsynchronized Lyrics"),
]

#: LRC lyrics as a Windows ripper leaves them: CRLF, and a space at the end
#: of some lines.
LRC = "[00:12.34]I hurt myself today \r\n[00:17.02]To see if I still feel\r\n"


class AccurateRip(unittest.TestCase):
    def test_accurateripresult_goes_whole_under_its_own_rule_in_mp3_and_vorbis(self):
        for family, spec in ((ID3, TXXX("AccurateRipResult")), (ID3, TXXX("accurateripresult")),
                             (VORBIS, "accurateripresult")):
            k = key(spec)
            with self.subTest(key=k):
                tags = {**CONTEXT[family], k: ["AccurateRip: Accurate (confidence 5)  [37DEB629]"]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, CONTEXT[family])
                self.assertEqual([tuple(r) for r in removals], [(k, None, "accurateripresult")])


class BlankLyrics(unittest.TestCase):
    """The one residue rule that reaches lyrics."""

    def test_an_empty_or_whitespace_only_lyrics_value_is_removed_under_blank(self):
        # The three the first run found are USLT ' ', Vorbis '' and MP4 '\r\n'.
        # Each blank is tried in every lyrics field, so a rule keyed to one
        # spelling of the name shows.
        for family, spec in LYRICS:
            k = key(spec)
            for blank in ("", " ", "\r\n", " \n  "):
                with self.subTest(key=k, value=blank):
                    kept, removals = residue.strip(family, {**CONTEXT[family], k: [blank]})
                    self.assertEqual(kept, CONTEXT[family])
                    self.assertEqual([tuple(r) for r in removals], [(k, blank, "blank")])

    def test_a_blank_lyrics_value_beside_real_lyrics_goes_and_the_lyrics_stay_as_written(self):
        for family, spec in LYRICS:
            k = key(spec)
            with self.subTest(key=k):
                kept, removals = residue.strip(family, {**CONTEXT[family], k: [LRC, " "]})
                self.assertEqual(kept, {**CONTEXT[family], k: [LRC]})
                self.assertEqual([tuple(r) for r in removals], [(k, " ", "blank")])

    def test_lyrics_that_match_any_other_free_text_pattern_are_kept(self):
        # Lyrics are sung words. "Ripped by the storm", a line that is only
        # "Track 3", a URL in a spoken intro: the free-text patterns were
        # written for rippers' comments, and a lyrics rule built by reusing
        # them would eat verses.
        for family, spec in LYRICS:
            k = key(spec)
            for row, value in PATTERNS:
                if row == "blank":
                    continue
                with self.subTest(key=k, row=row, value=value):
                    tags = {**CONTEXT[family], k: [value]}
                    kept, removals = residue.strip(family, tags)
                    self.assertEqual(kept, tags)
                    self.assertEqual(list(removals), [])


class Rules(unittest.TestCase):
    def test_each_row_and_pattern_names_its_own_rule(self):
        # The plan shows the rule so the owner can tell why a value went.
        # Two rows sharing a name would make that answer ambiguous. The exact
        # wording is not asserted.
        rules: dict[str, set[str]] = {}

        def collect(row, family, tags):
            _, removals = residue.strip(family, {**CONTEXT[family], **tags})
            rules.setdefault(row, set()).update(r.rule for r in removals)

        for row, family, spec, value in WHOLE:
            collect(row, family, {key(spec): [value]})
        for row, family, k, value in PATTERN_SAMPLES:
            collect("pattern: " + row, family, {k: [value]})
        for row, family, k, value, _ in OTHER_FIELDS:
            collect("value: " + row, family, {k: [value]})

        rows = sorted(rules)
        for i, a in enumerate(rows):
            self.assertTrue(rules[a], f"{a} recorded no rule")
            for b in rows[i + 1:]:
                if (a, b) == ("pattern: blank", "value: TCOP"):
                    # A blank TCOP is in the TCOP row, and blank is also its
                    # own pattern. Either name is honest for that value.
                    continue
                self.assertFalse(rules[a] & rules[b], f"{a!r} and {b!r} share a rule")


if __name__ == "__main__":
    unittest.main()
