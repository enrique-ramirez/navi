"""The facts of one audio file the album view shows, read with mutagen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

#: mutagen type -> (format, tag family), the four families of `musiclib.mapping`.
KINDS: dict[type, tuple[str, str]] = {
    FLAC: ("FLAC", "vorbis"),
    MP3: ("MP3", "id3"),
    MP4: ("MP4", "mp4"),
    OggVorbis: ("Ogg Vorbis", "vorbis"),
    ASF: ("WMA", "asf"),
}


@dataclass(frozen=True)
class Facts:
    format: str
    family: str
    lossless: bool
    bitrate: int
    sample_rate: int
    #: None for a lossy format, whatever its header says.
    bit_depth: int | None
    channels: int
    length: float
    size: int


def facts(path: Path) -> Facts | None:
    """The facts of `path`, or None where it is not an audio file of a format the library holds."""
    try:
        found = mutagen.File(path)
    except (OSError, mutagen.MutagenError):
        return None
    return facts_of(found, path)


def facts_of(found: mutagen.FileType | None, path: Path) -> Facts | None:
    """`facts` of the file mutagen already loaded from `path` as `found`."""
    kind = KINDS.get(type(found)) if found is not None else None
    if kind is None:
        return None
    info = found.info
    lossless = isinstance(found, FLAC) or getattr(info, "codec", "") == "alac"
    return Facts(
        format=kind[0], family=kind[1], lossless=lossless,
        bitrate=info.bitrate, sample_rate=info.sample_rate,
        bit_depth=getattr(info, "bits_per_sample", None) if lossless else None,
        channels=info.channels, length=info.length, size=path.stat().st_size,
    )


def encoder(found: mutagen.FileType) -> str | None:
    """What made the file, where it says: an MP3's LAME header (`LAME 3.99.1+ -b 320`), a FLAC or Ogg vendor string, an MP4's `©too`."""
    info_line = " ".join(part for part in (getattr(found.info, "encoder_info", ""),
                                           getattr(found.info, "encoder_settings", "")) if part)
    if info_line:
        return info_line
    vendor = getattr(found.tags, "vendor", None)
    if vendor:
        return vendor
    if isinstance(found, MP4):
        tool = (found.tags or {}).get("\xa9too")
        return str(tool[0]) if tool else None
    return None
