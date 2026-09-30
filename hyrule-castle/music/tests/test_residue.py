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
import io
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
    (MP4, ITUNES + "REPLAYGAIN_TRACK_GAIN", ["-6.20 dB"]),
    (ASF, "WM/Genre", ["industrial rock"]),
    (ASF, "Author", ["Nine Inch Nails"]),
    # Only Description is free text on ASF: a title or lyrics that look like
    # residue are still a title and lyrics.
    (ASF, "Title", ["Track 3"]),
    (ASF, "WM/Lyrics", ["Ripped by the storm, see scene.org"]),
    # Starts with is case-sensitive, as the spec words it; not asserted either way.
    (ID3, "TCOP", ["℗ 1999 Nothing Records"]),
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
    (VORBIS, "software", ["Lavf52.94.0"]),
    (VORBIS, "tool", ["Media Center"]),
    (VORBIS, "logfile", ["Exact Audio Copy V0.99 prebeta 5 ..."]),
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
    # "Equals" is exact. Only the TCOP list says ignoring case and spaces.
    (VORBIS, "comment", ["RG ANIBOTERS"]),
    (VORBIS, "comment", ["  rg aniboters "]),
    (ID3, "COMM::eng", ["Pollodav"]),
    (MP4, "\xa9cmt", ["Unicode cue-file "]),
    (VORBIS, "source", ["Core Radio"]),
    (VORBIS, "organization", [" CORE RADIO"]),
    (ID3, "TOWN", ["[pirate shovon]"]),
]

#: Values that are wholly a link, in fields the engine does not plan from
#: MusicBrainz: (family, key, value, the record it leaves). `WM/AuthorURL`
#: is Picard's `website`, so it goes whole as a site key first.
WHOLLY_LINKS = [
    (MP4, "cprt", "www.some-label.com", "www.some-label.com"),
    (ID3, "TCOP", "www.some-label.com", "www.some-label.com"),
    (VORBIS, "url", "http://gamemp3s.net/", "http://gamemp3s.net/"),
    (VORBIS, "web", "http://example.org/", "http://example.org/"),
    (VORBIS, "episodeid", "LOMASRANKIAO.COM", "LOMASRANKIAO.COM"),
    (ASF, "WM/AuthorURL", "http://example.org/", None),
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


#: The Acoustic Adventures rip (24-bit 88.2 kHz FLAC) as `Track.tags` holds
#: its Vorbis comments. PMEDIA, the site it came from, is in fourteen keys.
#: `website`, `wwwaudiofile` and `wwwaudiosource` hold the three shapes a
#: link comes in: an `https://` URL, a `www.` URL and a bare domain.
ACOUSTIC_ADVENTURES = {
    "title": ["Morning Light"],
    "artist": ["Various Artists"],
    "album": ["Acoustic Adventures"],
    "date": ["2019"],
    "tracknumber": ["1"],
    "genre": ["Folk"],
    "uploader": ["PMEDIA"],
    "provider": ["PMEDIA"],
    "website": ["https://pmedia.example"],
    "wwwaudiofile": ["www.pmedia.example/file"],
    "wwwaudiosource": ["pmedia.example"],
    "encoded-by": ["PMEDIA"],
    "comment": ["PMEDIA"],
    "conductor": ["PMEDIA"],
    "credits": ["PMEDIA"],
    "work": ["PMEDIA"],
    "language": ["PMEDIA"],
    "publisher": ["PMEDIA"],
    "copyright": ["PMEDIA"],
    "compilation": ["PMEDIA"],
}
SITE_KEYS = ("uploader", "provider", "website", "wwwaudiofile", "wwwaudiosource")

#: Each of the five names as every format carries a free-form name, in the
#: case taggers write them: (name, family, key or frame).
SITE_KEY_FORMS = [
    form
    for name, upper, mixed in (
        ("uploader", "UPLOADER", "Uploader"),
        ("provider", "PROVIDER", "Provider"),
        ("website", "WEBSITE", "Website"),
        ("wwwaudiofile", "WWWAUDIOFILE", "WwwAudioFile"),
        ("wwwaudiosource", "WWWAUDIOSOURCE", "WwwAudioSource"),
    )
    for form in (
        (name, VORBIS, name),
        (name, ID3, TXXX(upper)),
        (name, ID3, TXXX(mixed)),
        (name, MP4, ITUNES + upper),
        (name, MP4, ITUNES + mixed),
        (name, ASF, mixed),
    )
] + [
    # Picard's native ASF name for `website`: a Windows Media file carries
    # the site's link here, never under a free-form name.
    ("website", ASF, "WM/AuthorURL"),
]

#: A link as rippers leave it: every value here is a URL or a bare domain
#: and nothing else. `.example` and `.xyz` are real top-level domains no
#: fixed list of site TLDs has had; a bare domain of any top-level label counts.
LINKS = [
    "https://pmedia.example/album/acoustic-adventures",
    "www.pmedia.example",
    "pmedia.example",
    "PMEDIA.EXAMPLE",
    "downloads.pmedia.xyz",
    # Sites write their own names in mixed case.
    "Pmedia.net",
    "RuTracker.org",
    "Musify.club",
]

#: Text tags the engine does not plan from MusicBrainz: free text, fields
#: with their own by-value list (copyright, organization), credit and work
#: fields, and a free-form name the denylist qualifies TXXX (Vorbis `url`),
#: which is kept by name but not when it holds a link.
TEXT_TAGS = [
    (VORBIS, "comment"),
    (VORBIS, "conductor"),
    (VORBIS, "credits"),
    (VORBIS, "work"),
    (VORBIS, "language"),
    (VORBIS, "publisher"),
    (VORBIS, "copyright"),
    (VORBIS, "organization"),
    (VORBIS, "compilation"),
    (VORBIS, "url"),
    (VORBIS, "lyricist"),
    (ID3, "COMM::eng"),
    (ID3, "TPE3"),
    (ID3, "TPUB"),
    (ID3, "TCOP"),
    (ID3, "TIT1"),
    (ID3, "TLAN"),
    (ID3, "TEXT"),
    (ID3, "TXXX:CREDITS"),
    (ID3, "TXXX:source"),
    (MP4, "\xa9cmt"),
    (MP4, "cprt"),
    (MP4, ITUNES + "CONDUCTOR"),
    (MP4, ITUNES + "LABEL"),
    (MP4, ITUNES + "LYRICIST"),
    (ASF, "Description"),
    (ASF, "WM/Conductor"),
    (ASF, "WM/Publisher"),
    (ASF, "Copyright"),
    (ASF, "WM/Writer"),
]

#: The name fields the engine plans from MusicBrainz, in every family:
#: title, artist, album, album artist, the two sort names, composer and
#: composer sort.
PLANNED_NAMES = [
    (ID3, k) for k in ("TIT2", "TPE1", "TALB", "TPE2", "TSOP", "TSO2", "TCOM", "TSOC")
] + [
    (VORBIS, k) for k in ("title", "artist", "album", "albumartist", "artistsort",
                          "albumartistsort", "composer", "composersort")
] + [
    (MP4, k) for k in ("\xa9nam", "\xa9ART", "\xa9alb", "aART", "soar", "soaa", "\xa9wrt", "soco")
] + [
    (ASF, k) for k in ("Title", "Author", "WM/AlbumTitle", "WM/AlbumArtist", "WM/ArtistSortOrder",
                       "WM/AlbumArtistSortOrder", "WM/Composer", "WM/ComposerSortOrder")
]

#: Artist names MusicBrainz spells with dots. `will.i.am` ends in a country
#: code (`.am`), so only a planned field keeps it. The rest end in a label
#: no top-level domain has, like the names in `NOT_A_TLD`.
DOTTED_NAMES = ["will.i.am", "AC.DC", "MC.SOLAAR", "MR.CHILDREN"]
NOT_A_TLD = ["St.Anger", "Mr.Big", "B.o.B", "R.E.M.", "Vol.2", "Op.27"]


class DownloadSiteKeys(unittest.TestCase):
    """`uploader`, `provider`, `website`, `wwwaudiofile` and
    `wwwaudiosource` go whole, in every format."""

    def test_the_acoustic_adventures_rip_loses_the_five_site_keys_and_encoded_by_and_nothing_else(self):
        kept, removals = residue.strip(VORBIS, copy.deepcopy(ACOUSTIC_ADVENTURES))
        gone = (*SITE_KEYS, "encoded-by")
        # Every PMEDIA left in comment, conductor, credits, work, language,
        # publisher, copyright and compilation is the owner's to remove.
        self.assertEqual(kept, {k: v for k, v in ACOUSTIC_ADVENTURES.items() if k not in gone})
        # One whole-field record per key, even for the three holding a link.
        self.assertEqual(removed(removals), sorted(((k, None) for k in gone), key=repr))
        for removal in removals:
            with self.subTest(key=removal.key):
                self.assertTrue(removal.rule.strip())

    def test_each_site_key_goes_whole_in_vorbis_id3_mp4_and_asf_under_one_rule_per_name(self):
        rules: dict[str, set[str]] = {}
        for name, family, spec in SITE_KEY_FORMS:
            k = key(spec)
            with self.subTest(key=k):
                # PMEDIA is no link, so only the key can remove it; the link
                # beside it must not add a second, per-value record.
                tags = {**CONTEXT[family], k: ["PMEDIA", "https://pmedia.example"]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, CONTEXT[family])
                self.assertEqual(removed(removals), [(k, None)])
                self.assertTrue(removals[0].rule.strip())
                rules.setdefault(name, set()).add(removals[0].rule)
        # The page shows the rule: one name reads the same in every format.
        for name, found in rules.items():
            with self.subTest(name=name):
                self.assertEqual(len(found), 1, found)


class LinksInAnyTextTag(unittest.TestCase):
    """A value that is a URL or a bare domain goes from any
    text tag but lyrics."""

    def test_a_url_or_bare_domain_value_goes_from_any_text_tag_and_the_rest_of_the_field_stays(self):
        rules = set()
        for family, k in TEXT_TAGS:
            for link in LINKS:
                with self.subTest(key=k, value=link):
                    tags = {**CONTEXT[family], k: ["PMEDIA", link]}
                    kept, removals = residue.strip(family, tags)
                    self.assertEqual(kept, {**CONTEXT[family], k: ["PMEDIA"]})
                    self.assertEqual(removed(removals), [(k, link)])
                    self.assertTrue(removals[0].rule.strip())
                    rules.add(removals[0].rule)
        # One clause, so one rule on the page, whatever the
        # field it was found in.
        self.assertEqual(len(rules), 1, rules)

    def test_the_links_kept_before_criterion_38_now_go(self):
        for family, k, value, record in WHOLLY_LINKS:
            with self.subTest(key=k, value=value):
                kept, removals = residue.strip(family, {**CONTEXT[family], k: [value]})
                self.assertEqual(kept, CONTEXT[family])
                self.assertEqual(removed(removals), [(k, record)])
                if record is not None:
                    # The rule the same value gets in a comment today.
                    _, in_comment = residue.strip(VORBIS, {"comment": [value]})
                    self.assertEqual(removals[0].rule, in_comment[0].rule)

    def test_a_name_field_planned_from_musicbrainz_keeps_a_dotted_name_a_site_or_a_pattern(self):
        # The engine writes these from the matched release, and `check` runs
        # residue again on what it wrote. A value rule here would strip
        # will.i.am from his own album and hold it for good.
        for family, k in PLANNED_NAMES:
            for value in (*DOTTED_NAMES, "pmedia.example", "https://pmedia.example", "Track 3"):
                with self.subTest(key=k, value=value):
                    tags = {**CONTEXT[family], k: [value]}
                    kept, removals = residue.strip(family, tags)
                    self.assertEqual(kept, tags)
                    self.assertEqual(list(removals), [])

    def test_a_dotted_name_whose_last_label_is_no_top_level_domain_stays_in_any_field(self):
        for family, k in TEXT_TAGS + PLANNED_NAMES:
            for value in NOT_A_TLD + DOTTED_NAMES[1:]:
                with self.subTest(key=k, value=value):
                    tags = {**CONTEXT[family], k: [value]}
                    kept, removals = residue.strip(family, tags)
                    self.assertEqual(kept, tags)
                    self.assertEqual(list(removals), [])

    def test_a_field_holding_only_a_link_disappears(self):
        for family, k in ((VORBIS, "conductor"), (ID3, "TPE3"), (MP4, ITUNES + "CONDUCTOR"),
                          (ASF, "WM/Conductor")):
            with self.subTest(key=k):
                kept, removals = residue.strip(family, {**CONTEXT[family], k: ["pmedia.example"]})
                self.assertEqual(kept, CONTEXT[family])
                self.assertEqual(removed(removals), [(k, "pmedia.example")])

    def test_a_link_in_lyrics_is_kept(self):
        for family, spec in LYRICS:
            k = key(spec)
            for link in LINKS:
                with self.subTest(key=k, value=link):
                    tags = {**CONTEXT[family], k: [link]}
                    kept, removals = residue.strip(family, tags)
                    self.assertEqual(kept, tags)
                    self.assertEqual(list(removals), [])

    def test_values_with_a_dot_that_no_reading_makes_a_domain_are_kept(self):
        # A domain has no spaces and no all-digit top-level label, so none
        # of these is one. A link rule that only looks for a dot eats them.
        for family, k, value in (
            (VORBIS, "album", "Acoustic Adventures, Vol. 1"),
            (VORBIS, "title", "Symphony No. 5 in C minor, Op. 67"),
            (VORBIS, "date", "2019.05.01"),
            (VORBIS, "replaygain_track_gain", "-6.20 dB"),
            (ID3, "TALB", "Acoustic Adventures, Vol. 1"),
            (MP4, ITUNES + "REPLAYGAIN_TRACK_GAIN", "-6.20 dB"),
            (ASF, "WM/AlbumTitle", "Acoustic Adventures, Vol. 1"),
        ):
            with self.subTest(key=k, value=value):
                tags = {**CONTEXT[family], k: [value]}
                kept, removals = residue.strip(family, tags)
                self.assertEqual(kept, tags)
                self.assertEqual(list(removals), [])

    def test_an_m4a_cover_whose_image_carries_links_is_kept(self):
        # `Track.tags` holds `covr` as the repr of the image bytes. A JPEG
        # with an XMP packet has `http://ns.adobe.com/xap/1.0/` and
        # `www.w3.org` in them, as text. A picture is not a text tag.
        from PIL import Image

        from musiclib import files

        xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
               b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></x:xmpmeta>')
        out = io.BytesIO()
        Image.new("RGB", (8, 8)).save(out, "JPEG", xmp=xmp)
        path = builders.copy_fixture(_TMP.name, "m4a", "xmp-cover")
        builders.embed_picture(path, out.getvalue())
        tags = files.read(path).tags
        self.assertIn("http://", tags["covr"][0])  # the trap is really there

        kept, removals = residue.strip(MP4, tags)
        self.assertEqual(kept, tags)
        self.assertEqual(list(removals), [])


if __name__ == "__main__":
    unittest.main()
