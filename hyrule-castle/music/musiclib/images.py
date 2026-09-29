"""Album images and the embedded cover: naming, JPEG conversion and embedding."""

from __future__ import annotations

import base64
import io
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from mutagen.asf import ASF, ASFByteArrayAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from PIL import Image

_SKIP_TYPES = {"Raw/Unedited", "Watermark"}
_EMBED_MAX = 1200


@dataclass
class ImagePlan:
    files: dict[str, bytes]
    problems: list[str]
    consumed: str | None = None  # the folder file that became `cover.jpg`, when it was not one already


def _is_skipped(image: dict) -> bool:
    return any(t in _SKIP_TYPES for t in image.get("types", []))


def _base_name(image: dict) -> str:
    types = image.get("types", [])
    return types[0].lower().replace("/", "-") if types else "other"


def _is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


#: What Pillow raises for bytes that are not a readable image, however the file is broken.
_NOT_AN_IMAGE = (OSError, ValueError, SyntaxError, Image.DecompressionBombError)


def _as_jpeg(data: bytes) -> bytes:
    """`data`, unchanged if it is already a JPEG, else converted to one."""
    if _is_jpeg(data):
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return data
    with Image.open(io.BytesIO(data)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=95)
        return out.getvalue()


_LOCAL_STEMS = ("cover", "front", "folder", "album", "art")
_LOCAL_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def local_covers(folder: Path) -> list[tuple[str, bytes]]:
    """`(name, bytes)` of each image in `folder` that can stand in for the cover, best first."""
    found = []
    for path in folder.iterdir():
        stem = path.stem.casefold()
        if path.is_file() and stem in _LOCAL_STEMS and path.suffix.casefold() in _LOCAL_SUFFIXES:
            found.append((_LOCAL_STEMS.index(stem), path.name.casefold(), path.name, path))
    return [(name, path.read_bytes()) for _rank, _key, name, path in sorted(found, key=lambda f: f[:3])]


def _front_of(caa_images: list[dict]) -> dict | None:
    kept = [image for image in caa_images if not _is_skipped(image)]
    front = next((image for image in kept if image.get("front")), None)
    if front is None:
        front = next((image for image in kept if "Front" in image.get("types", [])), None)
    return front


def plan_images(
    caa_images: list[dict],
    download: Callable[[str], bytes],
    group_images: Callable[[], list[dict]] | None = None,
    local: Sequence[tuple[str, bytes]] = (),
) -> ImagePlan:
    """The album's image files, from the Cover Art Archive's list for the release.

    The front is the release's own; failing that, the front of the list
    `group_images()` returns (asked only then); failing that, the first of
    `local` (see `local_covers`) that Pillow can open. Only the front falls back.
    """
    kept = [image for image in caa_images if not _is_skipped(image)]
    front = _front_of(caa_images)
    if front is None and group_images is not None:
        front = _front_of(group_images())

    files: dict[str, bytes] = {}
    problems: list[str] = []
    consumed: str | None = None

    def fetch(image: dict) -> bytes | None:
        url = image["image"]
        try:
            return _as_jpeg(download(url))
        except _NOT_AN_IMAGE:
            problems.append(f"cover art archive: {url} is not an image")
            return None

    if front is not None:
        cover = fetch(front)
        if cover is not None:
            files["cover.jpg"] = cover
    else:
        for name, data in local:
            try:
                files["cover.jpg"] = _as_jpeg(data)
            except _NOT_AN_IMAGE:
                continue
            if name.casefold() != "cover.jpg":
                consumed = name
            break
        else:
            problems.append(
                "no front cover: not in the Cover Art Archive for the release or its release group, "
                "and no cover image in the folder")

    rest = [image for image in kept if image is not front]
    counts: dict[str, int] = {}
    for image in rest:
        base = _base_name(image)
        counts[base] = counts.get(base, 0) + 1

    seen: dict[str, int] = {}
    for image in rest:
        base = _base_name(image)
        seen[base] = seen.get(base, 0) + 1
        # `booklet` is always numbered, even the only one; every other type
        # is numbered only once there is more than one of it. Numbering
        # follows the archive's list order, not the image id: the fixture
        # deliberately gives the second of each pair the lower id.
        if base == "booklet":
            name = f"booklet-{seen[base]:02d}.jpg"
        elif counts[base] > 1:
            name = f"{base}-{seen[base]}.jpg"
        else:
            name = f"{base}.jpg"
        picture = fetch(image)
        if picture is not None:
            files[name] = picture

    return ImagePlan(files=files, problems=problems, consumed=consumed)


def embedded_front(cover_jpeg: bytes) -> bytes:
    """`cover_jpeg`, resized to at most 1200 px on the long side."""
    with Image.open(io.BytesIO(cover_jpeg)) as image:
        if max(image.size) <= _EMBED_MAX:
            return cover_jpeg
        resized = image.convert("RGB")
        resized.thumbnail((_EMBED_MAX, _EMBED_MAX), Image.LANCZOS)
        out = io.BytesIO()
        resized.save(out, "JPEG", quality=90)
        return out.getvalue()


def _picture(jpeg: bytes) -> Picture:
    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg"
    picture.data = jpeg
    with Image.open(io.BytesIO(jpeg)) as image:
        picture.width, picture.height = image.size
    picture.depth = 24
    return picture


def _asf_picture_bytes(jpeg: bytes, picture_type: int = 3, mime: str = "image/jpeg",
                       description: str = "") -> bytes:
    """A `WM/Picture` value, laid out the way Windows Media Player and Picard write it.

    One byte of picture type, the image's length as a little-endian 32-bit
    number, the MIME type and the description as NUL-terminated UTF-16LE,
    then the image itself.
    """
    return (struct.pack("<bI", picture_type, len(jpeg))
            + mime.encode("utf-16-le") + b"\0\0"
            + description.encode("utf-16-le") + b"\0\0"
            + jpeg)


def _utf16z(raw: bytes, pos: int) -> int:
    """Where the NUL-terminated UTF-16LE string at `pos` ends."""
    end = pos
    while raw[end:end + 2] != b"\0\0":
        end += 2
    return end + 2


def _parse_asf_picture(raw: bytes) -> tuple[int, bytes]:
    """`(picture type, image bytes)` out of a `WM/Picture` value, the inverse of `_asf_picture_bytes`."""
    picture_type, size = struct.unpack_from("<bI", raw)
    pos = _utf16z(raw, 5)  # mime
    pos = _utf16z(raw, pos)  # description
    return picture_type, raw[pos:pos + size]


def embed(path: Path, jpeg: bytes) -> None:
    """Replace every embedded picture in `path` with one front cover, `jpeg`."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        try:
            tag = ID3(path)
        except ID3NoHeaderError:
            tag = ID3()
        tag.delall("APIC")
        tag.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg))
        tag.save(path, v2_version=4, v1=0)
    elif ext == "flac":
        audio = FLAC(path)
        audio.clear_pictures()
        audio.add_picture(_picture(jpeg))
        audio.save()
    elif ext == "ogg":
        audio = OggVorbis(path)
        audio["metadata_block_picture"] = [base64.b64encode(_picture(jpeg).write()).decode("ascii")]
        audio.save()
    elif ext in ("m4a", "mp4"):
        audio = MP4(path)
        audio["covr"] = [MP4Cover(jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
    elif ext == "wma":
        audio = ASF(path)
        audio["WM/Picture"] = [ASFByteArrayAttribute(_asf_picture_bytes(jpeg))]
        audio.save()
    else:
        raise ValueError(f"unsupported extension: {ext!r}")


def embedded_pictures(path: Path) -> list[tuple[int, bytes]]:
    """Every embedded picture in `path`, with its picture type (M4A/MP4 have none: 0)."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "mp3":
        return [(frame.type, frame.data) for frame in ID3(path).getall("APIC")]
    if ext == "flac":
        return [(picture.type, picture.data) for picture in FLAC(path).pictures]
    if ext == "ogg":
        audio = OggVorbis(path)
        pictures = []
        for block in (audio.tags or {}).get("metadata_block_picture", []):
            picture = Picture(base64.b64decode(block))
            pictures.append((picture.type, picture.data))
        return pictures
    if ext in ("m4a", "mp4"):
        return [(0, bytes(cover)) for cover in MP4(path).get("covr", [])]
    if ext == "wma":
        return [_parse_asf_picture(bytes(attribute.value)) for attribute in ASF(path).get("WM/Picture", [])]
    raise ValueError(f"unsupported extension: {ext!r}")
