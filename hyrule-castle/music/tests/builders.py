"""Fixture builders, so a test says only what it is actually about.

These talk to mutagen directly, never to musiclib, so they stay a fair
description of what is actually on disk rather than of what the engine
thinks is on disk.
"""

from __future__ import annotations

import base64
import copy
import functools
import io
import shutil
import struct
from pathlib import Path
from typing import Any

from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, PRIV, TXXX, UFID, Frame, Frames, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Extension -> the tagless sample it is copied from.
_SOURCE = {
    "mp3": FIXTURES / "tone.mp3",
    "flac": FIXTURES / "tone.flac",
    "ogg": FIXTURES / "tone.ogg",
    "m4a": FIXTURES / "tone.m4a",
}

#: The other two audio kinds the library holds. Kept out of `_SOURCE`, which
#: `retitled_tracks` reads as the list of audio extensions a write test uses.
#: An audio-only `.mp4` is the same container as `.m4a`, so it is the same
#: sample under another name.
_MORE_SOURCE = {
    "mp4": FIXTURES / "tone.m4a",
    "wma": FIXTURES / "tone.wma",
}

#: A music video in miniature: three frames of H.264 and a second of AAC. The
#: audio track means mutagen reads it as a good MP4 audio file, so only its
#: video track says it is not one.
VIDEO_MP4 = FIXTURES / "video.mp4"


def album_dir(tmp: Path | str, layout: dict[str, Any]) -> Path:
    """Copy fixtures into a `Letter/Artist/(YYYY) Album/` unit under `tmp`.

    `layout` is `{"letter", "artist", "year", "album", "tracks"}`, where each
    track is `{"number", "title", "ext", "disc"}` (`disc`, e.g. `1`,
    optional). A track with a `disc` lands under a `CDn` subfolder; one
    without lands directly in the album folder. Returns the album folder.
    """
    base = Path(tmp) / layout["letter"] / layout["artist"] / f"({layout['year']}) {layout['album']}"
    for track in layout["tracks"]:
        disc = track.get("disc")
        folder = base / f"CD{disc}" if disc else base
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{track['number']:02d}. {track['title']}.{track['ext']}"
        shutil.copyfile(_SOURCE[track["ext"]], folder / name)
    return base


def copy_fixture(tmp: Path | str, ext: str, name: str = "track") -> Path:
    """One tagless sample copied to `tmp/<name>.<ext>`, safe to write to."""
    target = Path(tmp) / f"{name}.{ext}"
    shutil.copyfile({**_SOURCE, **_MORE_SOURCE}[ext], target)
    return target


def add_id3v1(path: Path | str, v2_version: int = 3) -> None:
    """Append an ID3v1 trailer to an MP3, saving its ID3v2 tag as `v2_version`.

    The v1 trailer is built from the v2 frames already in the file, so seed
    those first with `write_tags`.
    """
    ID3(path).save(path, v1=2, v2_version=v2_version)


def id3_key(tmp: Path | str, frame: Frame) -> str:
    """The key mutagen reads back for `frame` once it is saved in a real MP3.

    For frames whose HashKey shape is easy to get wrong by hand (`PRIV`,
    `GEOB`, `USER`, the `W***` links). Raises if the frame does not survive
    the save, since a key for a frame no file can hold tests nothing.
    """
    path = copy_fixture(tmp, "mp3", "key")
    write_tags(path, {frame.FrameID: frame})
    keys = list(ID3(path).keys())
    if len(keys) != 1:
        raise ValueError(f"{frame!r} read back as {keys}")
    return keys[0]


def write_tags(path: Path | str, tags: dict[str, Any], v2_version: int = 3) -> None:
    """Set raw tags by the format's real keys.

    MP3: a plain key like `TPE1` becomes a text frame; `TXXX:<desc>` and
    `PRIV:<owner>` build those frames from the description/owner in the key;
    a `mutagen.id3.Frame` instance is added as-is for anything odder.
    FLAC/Ogg: keys are Vorbis comment field names (e.g. `ripping tool`).
    M4A and MP4: keys are MP4 atom names, including `----:`-style freeform
    atoms. WMA: keys are ASF attribute names, and a value is text unless it
    is already an ASF attribute (a `WM/Picture`, say).
    An MP3 is saved as ID3v2.3 unless `v2_version` says otherwise.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        try:
            audio = ID3(path)
        except ID3NoHeaderError:
            audio = ID3()
        for key, value in tags.items():
            if isinstance(value, Frame):
                audio.add(value)
            elif key.startswith("TXXX:"):
                audio.add(TXXX(encoding=3, desc=key.split(":", 1)[1], text=[str(value)]))
            elif key.startswith("PRIV:"):
                data = value if isinstance(value, bytes) else str(value).encode("utf-8")
                audio.add(PRIV(owner=key.split(":", 1)[1], data=data))
            else:
                audio.add(Frames[key](encoding=3, text=[str(value)]))
        audio.save(path, v2_version=v2_version)
    elif ext in ("flac", "ogg"):
        audio = FLAC(path) if ext == "flac" else OggVorbis(path)
        for key, value in tags.items():
            audio[key] = value if isinstance(value, list) else [str(value)]
        audio.save()
    elif ext in ("m4a", "mp4"):
        audio = MP4(path)
        for key, value in tags.items():
            if key.startswith("----") and isinstance(value, str):
                value = value.encode("utf-8")
            audio[key] = value if isinstance(value, list) else [value]
        audio.save()
    elif ext == "wma":
        audio = ASF(path)
        for key, value in tags.items():
            audio[key] = value if isinstance(value, list) else [value]
        audio.save()
    else:
        raise ValueError(f"unsupported extension: {ext!r}")


def read_tags(path: Path | str) -> dict[str, Any]:
    """The raw tags back, in a form plain `assertEqual` can compare."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        try:
            audio = ID3(path)
        except ID3NoHeaderError:
            return {}
        result: dict[str, Any] = {}
        for key, frame in audio.items():
            if hasattr(frame, "data"):
                result[key] = frame.data
            elif hasattr(frame, "text"):
                result[key] = list(frame.text)
            else:
                result[key] = str(frame)
        return result
    elif ext in ("flac", "ogg"):
        audio = FLAC(path) if ext == "flac" else OggVorbis(path)
        result = {}
        for key, value in audio.tags or []:
            result.setdefault(key, []).append(value)
        return result
    elif ext in ("m4a", "mp4"):
        audio = MP4(path)
        return dict(audio.tags or {})
    elif ext == "wma":
        return {key: [attribute.value for attribute in values]
                for key, values in (ASF(path).tags or {}).items()}
    else:
        raise ValueError(f"unsupported extension: {ext!r}")


# --- a library that follows docs/music-library.md -------------------------

#: Stand-in MusicBrainz IDs. Real ones are UUIDs; the rules only ask that
#: they are there.
MBID = "8b2c6d0c-0000-4000-8000-000000000001"


def jpeg(width: int, height: int) -> bytes:
    """A plain JPEG of the given size."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 40, 40)).save(out, "JPEG")
    return out.getvalue()


def picture(width: int, height: int, colour: tuple[int, int, int], fmt: str = "JPEG") -> bytes:
    """A plain image in one colour, as a JPEG unless `fmt` names another format Pillow writes.

    The colour tells two pictures of the same size apart, by their bytes and
    after a conversion that changes the bytes.
    """
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, fmt)
    return out.getvalue()


def two_tone(width: int, height: int, fmt: str = "JPEG",
             colours: tuple[tuple[int, int, int], tuple[int, int, int]] = ((230, 230, 230), (30, 30, 30))) -> bytes:
    """One picture at any size: split corner to corner, the first colour above the diagonal, the second below.

    A flat picture's average hash is 0 whatever its colour, so two flat
    pictures look alike to a same-picture test; this one has a hash of its own,
    and the same one at every size.
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), colours[0])
    ImageDraw.Draw(image).polygon([(0, height), (width, 0), (width, height)], fill=colours[1])
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


@functools.cache
def embedded_cover() -> bytes:
    """`cover.jpg` shrunk to 1200 px on the long side, as the rules embed it."""
    from PIL import Image

    image = Image.open(FIXTURES / "cover.jpg")
    image.thumbnail((1200, 1200))
    out = io.BytesIO()
    image.save(out, "JPEG")
    return out.getvalue()


def embed_picture(path: Path | str, data: bytes, picture_type: int = 3, replace: bool = False,
                  mime: str = "image/jpeg") -> None:
    """Embed a JPEG, as a front cover (type 3) unless told otherwise.

    `mime` is what the tag says the picture is; give it with any other
    format. MP3 is saved as ID3v2.4. M4A has no picture types, so every
    `covr` is a front cover there and `picture_type` is ignored.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        tag = ID3(path)
        if replace:
            tag.delall("APIC")
        # The description keeps a second picture from replacing the first.
        desc = f"picture {len(tag.getall('APIC')) + 1}"
        tag.add(APIC(encoding=3, mime=mime, type=picture_type, desc=desc, data=data))
        tag.save(path, v2_version=4)
    elif ext in ("flac", "ogg"):
        from PIL import Image

        picture = Picture()
        picture.type = picture_type
        picture.mime = mime
        picture.width, picture.height = Image.open(io.BytesIO(data)).size
        picture.depth = 24
        picture.data = data
        if ext == "flac":
            audio = FLAC(path)
            if replace:
                audio.clear_pictures()
            audio.add_picture(picture)
        else:
            audio = OggVorbis(path)
            blocks = [] if replace else list(audio.get("metadata_block_picture", []))
            blocks.append(base64.b64encode(picture.write()).decode("ascii"))
            audio["metadata_block_picture"] = blocks
        audio.save()
    elif ext in ("m4a", "mp4"):
        audio = MP4(path)
        covers = [] if replace else list(audio.get("covr", []))
        covers.append(MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG))
        audio["covr"] = covers
        audio.save()
    elif ext == "wma":
        audio = ASF(path)
        blobs = [] if replace else list(audio.get("WM/Picture", []))
        blobs.append(ASFByteArrayAttribute(asf_picture(data, picture_type, mime)))
        audio["WM/Picture"] = blobs
        audio.save()
    else:
        raise ValueError(f"unsupported extension: {ext!r}")


def asf_picture(data: bytes, picture_type: int = 3, mime: str = "image/jpeg",
                description: str = "") -> bytes:
    """A `WM/Picture` value, laid out the way Windows Media Player and Picard write it.

    One byte of picture type, the image's length as a little-endian 32-bit
    number, the MIME type and the description as NUL-terminated UTF-16LE,
    then the image itself.
    """
    return (struct.pack("<bI", picture_type, len(data))
            + mime.encode("utf-16-le") + b"\0\0"
            + description.encode("utf-16-le") + b"\0\0"
            + data)


def _utf16z(raw: bytes, pos: int) -> tuple[str, int]:
    """The NUL-terminated UTF-16LE string at `pos`, and where the next field starts."""
    end = pos
    while raw[end:end + 2] != b"\0\0":
        end += 2
    return raw[pos:end].decode("utf-16-le"), end + 2


def asf_pictures(path: Path | str) -> list[tuple[int, str, bytes]]:
    """Every `WM/Picture` in a WMA file as `(type, mime, image bytes)`, read with mutagen alone."""
    found = []
    for attribute in ASF(path).get("WM/Picture", []):
        raw = attribute.value
        picture_type, size = struct.unpack_from("<bI", raw)
        mime, pos = _utf16z(raw, 5)
        _description, pos = _utf16z(raw, pos)
        found.append((picture_type, mime, raw[pos:pos + size]))
    return found


def clear_pictures(path: Path | str) -> None:
    """Remove every embedded picture, leaving the other tags alone."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        delete_tags(path, ["APIC"])
    elif ext == "flac":
        audio = FLAC(path)
        audio.clear_pictures()
        audio.save()
    elif ext == "ogg":
        delete_tags(path, ["metadata_block_picture"])
    else:
        delete_tags(path, ["covr"])


def delete_tags(path: Path | str, keys: list[str]) -> None:
    """Remove tags by the format's real key, keeping an MP3's ID3 version.

    MP3 keys are a frame ID (every frame of that kind) or a full HashKey.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        tag = ID3(path)
        for key in keys:
            tag.delall(key)
        tag.save(path, v2_version=tag.version[1] if tag.version[1] in (3, 4) else 4)
        return
    audio = {"flac": FLAC, "ogg": OggVorbis, "m4a": MP4}[ext](path)
    for key in keys:
        if key in audio:
            del audio[key]
    audio.save()


def library_tags(ext: str, *, title: str, number: int, total: int, disc: int, discs: int,
                 artist: str, album: str, date: str) -> dict[str, Any]:
    """Every field the rules require, under the names Picard writes."""
    if ext == "mp3":
        return {
            "TIT2": title, "TPE1": artist, "TALB": album, "TPE2": artist, "TDRC": date,
            "TRCK": f"{number}/{total}", "TPOS": f"{disc}/{discs}",
            "TCON": Frames["TCON"](encoding=3, text=["industrial rock", "electronic"]),
            "TXXX:MusicBrainz Album Id": MBID,
            "TXXX:MusicBrainz Release Group Id": MBID,
            "TXXX:MusicBrainz Artist Id": MBID,
            "UFID": UFID(owner="http://musicbrainz.org", data=MBID.encode("ascii")),
        }
    if ext in ("flac", "ogg"):
        return {
            "TITLE": title, "ARTIST": artist, "ALBUM": album, "ALBUMARTIST": artist, "DATE": date,
            "TRACKNUMBER": str(number), "TRACKTOTAL": str(total),
            "DISCNUMBER": str(disc), "DISCTOTAL": str(discs),
            "GENRE": ["industrial rock", "electronic"],
            "MUSICBRAINZ_ALBUMID": MBID, "MUSICBRAINZ_RELEASEGROUPID": MBID,
            "MUSICBRAINZ_TRACKID": MBID, "MUSICBRAINZ_ARTISTID": MBID,
        }
    if ext == "m4a":
        free = "----:com.apple.iTunes:"
        return {
            "\xa9nam": title, "\xa9ART": artist, "\xa9alb": album, "aART": artist, "\xa9day": date,
            "trkn": [(number, total)], "disk": [(disc, discs)],
            "\xa9gen": ["industrial rock", "electronic"],
            free + "MusicBrainz Album Id": MBID, free + "MusicBrainz Release Group Id": MBID,
            free + "MusicBrainz Track Id": MBID, free + "MusicBrainz Artist Id": MBID,
        }
    raise ValueError(f"unsupported extension: {ext!r}")


def library_album(root: Path | str, *, ext: str = "flac", letter: str = "N",
                  artist: str = "Nine Inch Nails", folder: str | None = None,
                  album: str = "The Fragile", date: str = "1999-09-21",
                  discs: tuple = (("Somewhat Damaged", "Hurt"),)) -> Path:
    """An album unit under `root` that breaks none of the rules.

    `discs` holds each medium's titles. More than one medium puts each in a
    `CDn` folder. A title given as `(title, name)` uses `name` in the file
    name, for titles the character table changes. `folder` defaults to
    `(YYYY) Album`. Returns the album folder.
    """
    base = Path(root) / letter / artist / (folder or f"({date[:4]}) {album}")
    base.mkdir(parents=True)
    for disc, titles in enumerate(discs, start=1):
        where = base / f"CD{disc}" if len(discs) > 1 else base
        where.mkdir(exist_ok=True)
        for number, entry in enumerate(titles, start=1):
            title, name = entry if isinstance(entry, tuple) else (entry, entry)
            digits = 3 if len(titles) >= 100 else 2
            path = where / f"{number:0{digits}d}. {name}.{ext}"
            shutil.copyfile(_SOURCE[ext], path)
            write_tags(path, library_tags(ext, title=title, number=number, total=len(titles),
                                          disc=disc, discs=len(discs), artist=artist,
                                          album=album, date=date), v2_version=4)
            embed_picture(path, embedded_cover())
    shutil.copyfile(FIXTURES / "cover.jpg", base / "cover.jpg")
    shutil.copyfile(FIXTURES / "cover.jpg", base / "back.jpg")
    (base / "booklet.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (base / "rip.log").write_text("Exact Audio Copy V1.6 extraction logfile\n")
    (base / "notes.txt").write_text("Bought at Rough Trade.\n")
    (base / "credits.txt").write_text("Produced by Trent Reznor and Alan Moulder.\n")
    return base


# --- MusicBrainz releases and Picard's tag names ---------------------------

#: `family -> real key` for every field a tag plan carries, by the name
#: Picard's tag mapping gives it. Vorbis keys are lower case, as `Track.tags`
#: holds them. Picard has no MP4 name for the original date, hence `None`.
#: The ASF (WMA) names are from Picard's tag-mapping appendix
#: (picard-docs.musicbrainz.org, *Picard Tag Mapping*), as of Picard 2.x.
#: Track and disc numbers are left out: their shape differs per format
#: (`TRCK` "3/4", Vorbis number and total apart, MP4 a pair), so
#: `picard_tags` takes them on their own.
PICARD_KEYS: dict[str, dict[str, str | None]] = {
    "title": {"id3": "TIT2", "vorbis": "title", "mp4": "\xa9nam",
              "asf": "Title"},
    "artist": {"id3": "TPE1", "vorbis": "artist", "mp4": "\xa9ART",
               "asf": "Author"},
    "album": {"id3": "TALB", "vorbis": "album", "mp4": "\xa9alb",
              "asf": "WM/AlbumTitle"},
    "albumartist": {"id3": "TPE2", "vorbis": "albumartist", "mp4": "aART",
                    "asf": "WM/AlbumArtist"},
    "date": {"id3": "TDRC", "vorbis": "date", "mp4": "\xa9day",
             "asf": "WM/Year"},
    "originaldate": {"id3": "TDOR", "vorbis": "originaldate", "mp4": None,
                     "asf": "WM/OriginalReleaseTime"},
    "artistsort": {"id3": "TSOP", "vorbis": "artistsort", "mp4": "soar",
                   "asf": "WM/ArtistSortOrder"},
    "albumartistsort": {"id3": "TSO2", "vorbis": "albumartistsort", "mp4": "soaa",
                        "asf": "WM/AlbumArtistSortOrder"},
    "discsubtitle": {"id3": "TSST", "vorbis": "discsubtitle",
                     "mp4": "----:com.apple.iTunes:DISCSUBTITLE",
                     "asf": "WM/SetSubTitle"},
    "genre": {"id3": "TCON", "vorbis": "genre", "mp4": "\xa9gen",
              "asf": "WM/Genre"},
    "release id": {"id3": "TXXX:MusicBrainz Album Id", "vorbis": "musicbrainz_albumid",
                   "mp4": "----:com.apple.iTunes:MusicBrainz Album Id",
                   "asf": "MusicBrainz/Album Id"},
    "release group id": {"id3": "TXXX:MusicBrainz Release Group Id",
                         "vorbis": "musicbrainz_releasegroupid",
                         "mp4": "----:com.apple.iTunes:MusicBrainz Release Group Id",
                         "asf": "MusicBrainz/Release Group Id"},
    # Picard's "track id" on Vorbis and MP4 is the recording, not the track.
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
                      "mp4": "----:com.apple.iTunes:CATALOGNUMBER",
                      "asf": "WM/CatalogNo"},
    "barcode": {"id3": "TXXX:BARCODE", "vorbis": "barcode", "mp4": "----:com.apple.iTunes:BARCODE",
                "asf": "WM/Barcode"},
    "asin": {"id3": "TXXX:ASIN", "vorbis": "asin", "mp4": "----:com.apple.iTunes:ASIN",
             "asf": "ASIN"},
    "releasecountry": {"id3": "TXXX:MusicBrainz Album Release Country", "vorbis": "releasecountry",
                       "mp4": "----:com.apple.iTunes:MusicBrainz Album Release Country",
                       "asf": "MusicBrainz/Album Release Country"},
    "media": {"id3": "TMED", "vorbis": "media", "mp4": "----:com.apple.iTunes:MEDIA",
              "asf": "WM/Media"},
}

#: The release-specific fields: the six, then the
#: release-level MusicBrainz IDs.
RELEASE_SPECIFIC = ("label", "catalognumber", "barcode", "asin", "releasecountry", "media",
                    "release id", "release group id", "album artist id")

FAMILY = {"mp3": "id3", "flac": "vorbis", "ogg": "vorbis", "m4a": "mp4", "mp4": "mp4", "wma": "asf"}


def picard_key(ext: str, field: str) -> str | None:
    """The real key Picard gives `field` in an `ext` file, as `Track.tags` names it."""
    return PICARD_KEYS[field][FAMILY[ext]]


def picard_tags(ext: str, fields: dict[str, list[str]], *, track: tuple[int, int] | None = None,
                disc: tuple[int, int] | None = None) -> dict[str, Any]:
    """`fields` (named as in `PICARD_KEYS`) as `write_tags` takes them, the way Picard writes them.

    `track` and `disc` are `(number, total)`. Every value is a list, so a
    field with two values is written as two values rather than one joined
    string. An MP3 so written has to be saved as ID3v2.4: `TDOR` and `TSST`
    do not exist in 2.3. A WMA gets `WM/TrackNumber` with no total, since
    Picard has no ASF name for the track total, and `WM/PartOfSet` as
    `disc/total`, the way Picard 1.3.1 and later write it.
    """
    out: dict[str, Any] = {}
    family = FAMILY[ext]
    for field, values in fields.items():
        key = PICARD_KEYS[field][family]
        if key is None:
            raise ValueError(f"Picard has no {ext} name for {field}")
        if family == "id3":
            if key.startswith("TXXX:"):
                out[key] = TXXX(encoding=3, desc=key[len("TXXX:"):], text=list(values))
            elif key.startswith("UFID:"):
                out[key] = UFID(owner=key[len("UFID:"):], data=values[0].encode("ascii"))
            else:
                out[key] = Frames[key](encoding=3, text=list(values))
        elif family == "vorbis":
            out[key.upper()] = list(values)
        elif family == "asf":
            out[key] = list(values)
        elif key.startswith("----:"):
            out[key] = [v.encode("utf-8") for v in values]
        else:
            out[key] = list(values)
    if family == "asf":
        if track is not None:
            out["WM/TrackNumber"] = [str(track[0])]
        if disc is not None:
            out["WM/PartOfSet"] = [f"{disc[0]}/{disc[1]}"]
        return out
    if track is not None:
        out.update(_numbers(family, track, "TRCK", "TRACKNUMBER", "TRACKTOTAL", "trkn"))
    if disc is not None:
        out.update(_numbers(family, disc, "TPOS", "DISCNUMBER", "DISCTOTAL", "disk"))
    return out


def _numbers(family: str, pair: tuple[int, int], id3: str, vorbis_number: str,
             vorbis_total: str, mp4: str) -> dict[str, Any]:
    number, total = pair
    if family == "id3":
        return {id3: f"{number}/{total}"}
    if family == "vorbis":
        return {vorbis_number: str(number), vorbis_total: str(total)}
    return {mp4: [(number, total)]}


#: MusicBrainz IDs of the stock release `mb_release` returns.
RELEASE_ID = "1a0b0c0d-0000-4000-8000-0000000000a1"
RELEASE_GROUP_ID = "1a0b0c0d-0000-4000-8000-0000000000a2"
CURE_ID = "1a0b0c0d-0000-4000-8000-0000000000a5"
SMITH_ID = "1a0b0c0d-0000-4000-8000-0000000000a6"


def mb_credit(artist_id: str, name: str, sort_name: str) -> list[dict[str, Any]]:
    """A one-artist `artist-credit`, as ws/2 gives it."""
    return [{"name": name, "joinphrase": "",
             "artist": {"id": artist_id, "name": name, "sort-name": sort_name}}]


def _mb_medium(position: int, fmt: str | None, title: str, titles: list[str]) -> dict[str, Any]:
    tracks = []
    for number, name in enumerate(titles, start=1):
        # Track 3 of disc 2 is Robert Smith's alone, so a track artist read
        # from the release credit shows up there.
        solo = (position, number) == (2, 3)
        tracks.append({
            "id": f"2b0c0d0e-0000-4000-8000-{position:04d}{number:04d}0001",
            "position": number,
            "number": str(number),
            "title": name,
            "length": 240000 + number * 1000,
            "artist-credit": (mb_credit(SMITH_ID, "Robert Smith", "Smith, Robert") if solo
                              else mb_credit(CURE_ID, "The Cure", "Cure, The")),
            "recording": {"id": f"3c0d0e0f-0000-4000-8000-{position:04d}{number:04d}0002",
                          "length": 240000 + number * 1000},
        })
    return {"position": position, "format": fmt, "title": title,
            "track-count": len(tracks), "tracks": tracks}


def mb_medium(position: int, titles: list[str], *, fmt: str | None = "CD", title: str = "",
              credit: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One ws/2 medium for `mb_release(media=[...])`, its tracks titled `titles`.

    `credit` replaces every track's artist credit. Without it the tracks are
    The Cure's, as in the stock release.
    """
    medium = _mb_medium(position, fmt, title, list(titles))
    if credit is not None:
        for track in medium["tracks"]:
            track["artist-credit"] = copy.deepcopy(credit)
    return medium


_MB_RELEASE: dict[str, Any] = {
    "id": RELEASE_ID,
    "title": "Disintegration",
    "status": "Official",
    "date": "2010-05-24",
    "country": "GB",
    "barcode": "600753279578",
    "asin": "B003FMTHVS",
    "label-info": [{"catalog-number": "FIXH 14",
                    "label": {"id": "4d0e0f10-0000-4000-8000-0000000000b1", "name": "Fiction Records"}}],
    "artist-credit": mb_credit(CURE_ID, "The Cure", "Cure, The"),
    "release-group": {"id": RELEASE_GROUP_ID, "title": "Disintegration",
                      "first-release-date": "1989-05-02", "primary-type": "Album",
                      "secondary-types": []},
    "media": [
        _mb_medium(1, "CD", "", ["Plainsong", "Pictures of You", "Closedown"]),
        _mb_medium(2, "Digital Media", "", ["Prayers for Rain", "Babble", "Fear of Drowning", "Out of Mind"]),
        _mb_medium(3, "CD", "Entreat Plus", ["Last Dance", "Fascination Street"]),
    ],
}


def mb_release(**changes: Any) -> dict[str, Any]:
    """A fresh ws/2 release: The Cure, *Disintegration*, three media.

    Each call returns its own deep copy, so a test that edits a medium or a
    label never reaches the next test. `changes` replace top-level keys.
    Medium 3 is the only one with a title; disc 2 track 3 is credited to
    Robert Smith rather than the band, and disc 2 is `Digital Media` where
    the others are `CD`.
    """
    release = copy.deepcopy(_MB_RELEASE)
    release.update(copy.deepcopy(changes))
    return release


# --- plans for the write path, made by hand --------------------------------
#
# The one place builders reaches into musiclib. A plan is the engine's own
# type, and the write tests hand one over without planning anything, so they
# stay clear of MusicBrainz and of `plan_album`. Everything is imported inside
# the functions, so a test that never builds a plan never needs musiclib.

#: The title under each format's real key, as `files.read` names it.
TITLE_KEY = {"mp3": "TIT2", "flac": "title", "ogg": "title", "m4a": "\xa9nam"}


def tree(root: Path | str) -> dict[str, bytes | None]:
    """Every file and folder under `root` by its path relative to `root`.

    A file maps to its bytes and a folder to `None`, so two snapshots compare
    equal only when nothing was written, moved, created or removed. A root
    that does not exist is `{}`.
    """
    root = Path(root)
    if not root.exists():
        return {}
    return {path.relative_to(root).as_posix(): (path.read_bytes() if path.is_file() else None)
            for path in sorted(root.rglob("*"))}


def file_plan(root: Path | str, source: str, destination: str, title: str):
    """A `FilePlan` that moves `source` to `destination` and sets its title.

    Both paths are relative to `root`. Every other tag is planned as the
    file carries it now, so the title is the only field the write changes.
    """
    from musiclib import files, tagwrite
    from musiclib.plan import FilePlan

    track = files.read(Path(root) / source)
    key = TITLE_KEY[Path(source).suffix.lower().lstrip(".")]
    return FilePlan(source=source, destination=destination,
                    target=tagwrite.merge(track, {key: [title]}), removals=[])


def retitled_tracks(root: Path | str, album: Path | str, destination: str | None = None,
                    suffix: str = " (Remastered)") -> list:
    """A `FilePlan` for every audio file of `album`, in path order.

    Each lands at the same spot under `destination` (relative to `root`, the
    album's own folder unless given), with `suffix` added to both its title
    and its file name, so every file is both moved and retagged.
    """
    from musiclib import files

    root, album = Path(root), Path(album)
    destination = destination or album.relative_to(root).as_posix()
    plans = []
    for path in sorted(album.rglob("*")):
        ext = path.suffix.lower().lstrip(".")
        if ext not in _SOURCE:
            continue
        title = files.read(path).tags[TITLE_KEY[ext]][0]
        inside = path.relative_to(album).with_name(f"{path.stem}{suffix}{path.suffix}")
        plans.append(file_plan(root, path.relative_to(root).as_posix(),
                               f"{destination}/{inside.as_posix()}", title + suffix))
    return plans


def album_plan(root: Path | str, source: str, destination: str, tracks: list, **fields: Any):
    """A `musiclib.plan.Plan` for one album unit, with no problems and nothing held.

    `source` and `destination` are album folders relative to `root`. Every
    field not given is empty, apart from `embedded`, which is the cover
    `library_album` already embeds, and `status`, which is `certain`.
    """
    from musiclib.plan import Plan

    values: dict[str, Any] = {
        "release_id": RELEASE_ID, "status": "certain", "images": {},
        "embedded": embedded_cover(), "deletions": [], "extras": [], "kept": [],
        "holds": [], "suggestions": [], "problems": [],
    }
    values.update(fields)
    return Plan(root=Path(root), source=source, destination=destination, files=list(tracks), **values)
