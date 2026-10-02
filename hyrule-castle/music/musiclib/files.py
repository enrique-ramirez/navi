"""Reading an audio file's tags without losing anything."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import mutagen
from mutagen.asf import ASF, ASFUnicodeAttribute
from mutagen.id3 import ID3FileType
from mutagen.mp4 import MP4, AtomDataType


class Unreadable(Exception):
    """Mutagen could not make sense of the file."""


@dataclass(frozen=True)
class Track:
    """A read-only snapshot of one audio file's tags and length."""

    path: str
    family: str  # "id3", "vorbis", "mp4" or "asf"
    tags: dict[str, list[str]]
    length: float


#: Every extension the library holds a track in, whatever the case. The one
#: definition `units`, `check` and `plan` all share: a list of its own in
#: each would let a format one of them missed come out planned and never
#: written, or written and never checked.
AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".wma"}
#: Extension -> tag family, `_family` with no file to open. A planned
#: destination keeps its source's extension, so this tells `plan` and the
#: decisions which family a file is without reading anything off disk.
FAMILY_BY_EXTENSION = {".mp3": "id3", ".flac": "vorbis", ".ogg": "vorbis", ".m4a": "mp4", ".mp4": "mp4",
                       ".wma": "asf"}

#: MP4 box types a video's `trak/mdia/hdlr` can be nested under. `hdlr` sits
#: directly inside `mdia` (ISO/IEC 14496-12), so these three are the only
#: boxes worth opening; everything else - the sample tables, the actual
#: video and audio data - is skipped over by its length alone.
_MP4_CONTAINERS = {b"moov", b"trak", b"mdia"}


def _mp4_has_video_handler(f, start: int, end: int) -> bool:
    """Whether an `hdlr` box under `f[start:end]` names the `vide` handler.

    Walks the box tree by hand rather than through a full MP4 parser, and by
    seeking rather than reading the file in: a music video is hundreds of MB,
    and `units` and `check` both call this for every `.mp4` in the library,
    so only the handful of small container boxes on the path to `hdlr` are
    ever read; the sample and media data box past them, however large, is
    skipped with a seek. Every box here (size, then a four-byte type) is
    self-describing enough to skip without decoding its payload.
    """
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            break  # truncated: `files.read` (mutagen) is what reports that
        size, name = struct.unpack(">I4s", header)
        header_len = 8
        if size == 1:
            size_bytes = f.read(8)
            if len(size_bytes) < 8:
                break
            size = struct.unpack(">Q", size_bytes)[0]
            header_len = 16
        elif size == 0:
            size = end - pos
        content_start = pos + header_len
        content_end = pos + size
        if name == b"hdlr":
            # version+flags (4 bytes), pre_defined (4 bytes), then the
            # four-byte handler type ISO/IEC 14496-12 defines this box as.
            f.seek(content_start + 8)
            if f.read(4) == b"vide":
                return True
        elif name in _MP4_CONTAINERS and _mp4_has_video_handler(f, content_start, content_end):
            return True
        pos += size
    return False


def is_mp4_video(path) -> bool:
    """Whether the MP4 at `path` carries a video track.

    A music video carries an audio track too, so mutagen reads it as a good
    MP4 audio file; only its `trak/mdia/hdlr` handler (`vide`) says
    otherwise (docs *What an album folder may contain*).
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            return _mp4_has_video_handler(f, 0, size)
    except OSError:
        # Unreadable, not a video: `files.read` (mutagen) is what reports
        # that, the same way as every other format, so a file this cannot
        # even open must not stop `is_track` calling it. A truncated box
        # tree does not raise at all - `_mp4_has_video_handler` breaks out of
        # its own loop and answers `False` - so there is nothing to catch for
        # that case.
        return False


def is_track_by_name(path, rel: PurePosixPath) -> bool:
    """The part of `is_track` that needs no file opened: extension, no AppleDouble sidecar, album or disc folder depth."""
    path = Path(path)
    if path.name.startswith("._"):
        return False
    if len(rel.parts) not in (1, 2):
        return False
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_track(path, rel: PurePosixPath) -> bool:
    """Whether the file at `path` counts as a track of the album `rel` sits under.

    One of the library's audio extensions, whatever the case; in the album
    folder or a direct subfolder (`rel` one or two parts) - that subfolder is
    the track's disc folder, whatever it is called; never an AppleDouble
    sidecar (`._name` copies the real file's extension but holds no audio);
    and, since an `.mp4` video reads as good MP4 audio otherwise, never one
    that carries a video track.
    """
    if not is_track_by_name(path, rel):
        return False
    return not (Path(path).suffix.lower() == ".mp4" and is_mp4_video(path))


def _family(audio) -> str:
    if isinstance(audio, ID3FileType):
        return "id3"
    if isinstance(audio, MP4):
        return "mp4"
    if isinstance(audio, ASF):
        return "asf"
    return "vorbis"


def load(path):
    """Load `path` with mutagen, turning every way it can fail into `Unreadable`.

    Returns the live mutagen file object, not a `Track`: `tagwrite` needs it
    to change and save tags, which a read-only snapshot cannot do.
    """
    try:
        audio = mutagen.File(path)
    except Exception as exc:
        raise Unreadable(f"{path}: {exc}") from exc
    if audio is None:
        raise Unreadable(f"{path}: not a recognised audio file")
    if isinstance(audio, ID3FileType) and audio.tags is None:
        audio.add_tags()
    return audio


def mp4_pair_text(number: int, total: int) -> str:
    """An MP4 `trkn`/`disk` pair as `Track.tags` renders it: `"n/total"`, or bare `"n"`.

    `total == 0` is MP4's own way of saying there is no total, so it is
    dropped rather than written as `"n/0"`. The shape matches ID3's
    `TRCK`/`TPOS` on purpose, so a caller need not special-case the format.
    """
    return f"{number}/{total}" if total else str(number)


def mp4_pair_value(text: str) -> tuple[int, int]:
    """The inverse of `mp4_pair_text`, for writing a pair back to MP4."""
    number, _, total = text.partition("/")
    return int(number), int(total) if total else 0


def _decode_freeform(value) -> str:
    """An MP4 freeform atom's value as text, or a digest for binary data.

    `dataformat` is `AtomDataType.UTF8` for every freeform atom Picard or
    this engine writes; anything else is somebody else's binary blob, kept
    comparable the same way a non-text ID3 frame is.
    """
    dataformat = getattr(value, "dataformat", AtomDataType.UTF8)
    if int(dataformat) == int(AtomDataType.UTF8):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            pass
    return hashlib.sha1(bytes(value)).hexdigest()


def snapshot(audio, family: str) -> dict[str, list[str]]:
    """Every tag on `audio` as `{key: [str, ...]}`, keyed by the format's own name.

    ID3 keys are the frame's `HashKey`, so `TXXX`, `COMM` and `USLT` keep the
    description (and, for `COMM`/`USLT`, the language) that tells two
    same-named frames apart. `POPM` has no text of its own, so its rating and
    play count are folded into a comparable string. `UFID` carries the
    MusicBrainz recording ID as raw bytes, so it is decoded to that text
    rather than digested: it is a plan-able field, not an opaque one.
    Any other non-text frame (`APIC`, `PRIV`, ...) is turned into
    a digest of its own repr: two reads of an untouched frame must compare
    equal, and a changed or replaced one must not, which a digest of its
    actual bytes gives for free. Vorbis keys are folded to lower case, since
    foobar2000 and Picard both write them upper case but a Vorbis comment
    field is case-insensitive. MP4 keeps its own atom names; a `----`
    freeform atom holding UTF-8 text is decoded to that text, and `trkn`/
    `disk` pairs render through `mp4_pair_text`. ASF keeps its own attribute
    names; a text attribute renders as that text, and a binary one (a
    `WM/Picture`, say) as a digest of its actual bytes rather than mutagen's
    own `"[binary data (N bytes)]"`, so two different pictures of the same
    size never compare equal.
    """
    tags = audio.tags or {}
    out: dict[str, list[str]] = {}
    if family == "id3":
        for frame in tags.values():
            key = frame.HashKey
            if frame.FrameID == "POPM":
                out[key] = [f"rating={frame.rating},count={getattr(frame, 'count', 0)}"]
            elif frame.FrameID == "UFID":
                try:
                    out[key] = [frame.data.decode("utf-8")]
                except UnicodeDecodeError:
                    out[key] = [hashlib.sha1(frame.data).hexdigest()]
            elif frame.FrameID in ("COMM", "USLT"):
                text = frame.text
                out[key] = [str(x) for x in text] if isinstance(text, list) else [str(text)]
            elif hasattr(frame, "text"):
                out[key] = [str(x) for x in frame.text]
            else:
                out[key] = [hashlib.sha1(repr(frame).encode("utf-8", "replace")).hexdigest()]
    elif family == "vorbis":
        # `tags.items()` walks mutagen's `VCommentDict.keys()`, which builds
        # a `set` of key names - hash-randomized, so two reads of the same
        # file could disagree on which key came first. A `VComment` is
        # documented as "a list of key/value pairs" with "all comment
        # ordering ... preserved", so reading it as the list it already is
        # keeps the file's own, on-disk order regardless of the interpreter's
        # hash seed.
        for key, value in tags:
            out.setdefault(key.lower(), []).append(value)
    elif family == "mp4":
        for key, value in tags.items():
            if key in ("trkn", "disk"):
                out[key] = [mp4_pair_text(*pair) for pair in value]
            elif key.startswith("----:"):
                out[key] = [_decode_freeform(v) for v in value]
            elif isinstance(value, list):
                out[key] = [x if isinstance(x, str) else repr(x) for x in value]
            else:
                out[key] = [repr(value)]
    else:  # asf
        for key, value in tags.items():
            out[key] = [
                str(attribute) if isinstance(attribute, ASFUnicodeAttribute)
                else hashlib.sha1(bytes(attribute.value)).hexdigest()
                for attribute in value
            ]
    return out


def read(path) -> Track:
    """Read every tag and the length of the audio file at `path`."""
    audio = load(path)
    family = _family(audio)
    return Track(path=str(path), family=family, tags=snapshot(audio, family), length=audio.info.length)


def audio_fingerprint(track: Track) -> str:
    """The audio itself, independent of tags.

    MP3 and FLAC keep the audio bytes untouched when mutagen rewrites the tag
    block, so those are hashed directly. Ogg pages and MP4 atoms are relaid
    on every save regardless of whether the audio changed, so a flipped byte
    in the middle would not show up in a byte hash of those; the duration
    stands in for them instead.
    """
    path = track.path
    if track.family == "id3" or path.lower().endswith(".flac"):
        data = Path(path).read_bytes()
        start, end = 0, len(data)
        if data[:3] == b"ID3":
            size = data[6:10]
            start = 10 + ((size[0] << 21) | (size[1] << 14) | (size[2] << 7) | size[3])
            if data[5] & 0x10:
                start += 10  # a footer duplicates the header's 10 bytes
        if data[start:start + 4] == b"fLaC":
            pos = start + 4
            while True:
                head = data[pos]
                pos += 4 + int.from_bytes(data[pos + 1:pos + 4], "big")
                if head & 0x80:
                    break
            start = pos
        elif data[end - 128:end - 125] == b"TAG":
            end -= 128
        return hashlib.sha1(data[start:end]).hexdigest()
    return f"length={round(track.length, 3)}"
