"""Album images and the embedded cover: naming, JPEG conversion and embedding."""

from __future__ import annotations

import base64
import io
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

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
    holds: list[str] = field(default_factory=list)


def _is_skipped(image: dict) -> bool:
    return any(t in _SKIP_TYPES for t in image.get("types", []))


def _type_base(type_name: str) -> str:
    return type_name.lower().replace("/", "-")


def _base_name(image: dict) -> str:
    types = image.get("types", [])
    return _type_base(types[0]) if types else "other"


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


_COVER_TYPES = {"Front", "Booklet", "Sticker"}


def _failures(width: int, height: int, types: Sequence[str] | None) -> int:
    """How many of the three tests of a cover (shape, size, type) the image fails.

    `types` is None for a local image, which has none; an archive image with
    no types is judged on shape and size alone.
    """
    shape = 10 * width >= 9 * height and 10 * width <= 11 * height
    return (not shape) + (min(width, height) < 500) + bool(types and not set(types) <= _COVER_TYPES)


def passes(width: int, height: int, types: Sequence[str] | None = None) -> bool:
    """Whether an image of this size, and an archive image of these `types`, may be the cover."""
    return _failures(width, height, types) == 0


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def average_hash(data: bytes) -> int:
    """The 64-bit average hash of an image: one bit per pixel of its 8 by 8 grey thumbnail, set above the mean."""
    with Image.open(io.BytesIO(data)) as image:
        pixels = list(image.convert("L").resize((8, 8), Image.BOX).tobytes())
    mean = sum(pixels) / 64
    return sum(1 << bit for bit, pixel in enumerate(pixels) if pixel > mean)


def hash_distance(a: int, b: int) -> int:
    """The number of bits that differ between two hashes."""
    return bin(a ^ b).count("1")


#: The archive types whose images the *Images* rule names by type, apart from
#: `Front`, which a rip's own scan may carry and which is never a copy to delete.
#: `other` is `_base_name`'s fallback for an image with no type.
_ARCHIVE_TYPES = ("Back", "Booklet", "Medium", "Obi", "Spine", "Track", "Tray", "Sticker", "Poster", "Liner",
                  "Matrix/Runout", "Top", "Bottom", "Other")
_ARCHIVE_BASES = "|".join(re.escape(_type_base(t)) for t in _ARCHIVE_TYPES)
_ARCHIVE_NAME = re.compile(rf"(?:(?:{_ARCHIVE_BASES})(?:-\d+)?\.jpg|booklet(?:-\d+)?\.pdf)", re.IGNORECASE)


def redundant_archive_names(folder: Mapping[str, bytes]) -> list[str]:
    """The names in `folder` (name to bytes) named like an archive image whose bytes another file of another kind has.

    The other file must have a name the *Images* rule does not give, so
    `cover.jpg` and two archive-named files equal to each other delete nothing.
    """
    owned = {data for name, data in folder.items()
             if not _ARCHIVE_NAME.fullmatch(name) and name.casefold() != "cover.jpg"}
    return [name for name, data in folder.items() if _ARCHIVE_NAME.fullmatch(name) and data in owned]


def _unseen(pairs: Iterable[tuple[dict, bytes]], have: set[bytes]) -> list[tuple[dict, bytes]]:
    """The `pairs` whose bytes are not in `have` and not an earlier pair's; adds those bytes to `have`."""
    kept = []
    for image, data in pairs:
        if data not in have:
            have.add(data)
            kept.append((image, data))
    return kept


def _local_over_archive(
    front: dict, archive_cover: bytes, candidates: Sequence[tuple[str, bytes]],
) -> tuple[tuple[str, bytes] | None, list[str]]:
    """The local cover that replaces an archive front failing the bar, and the holds that raises.

    The first passing candidate wins. When none passes, the first candidate
    wins only if it fails fewer tests than the front, or the same number with
    a longer short side, and the hold is raised either way. None when the front
    passes or keeps the cover.
    """
    types = front.get("types", [])
    archive_size = _size(archive_cover)
    if passes(*archive_size, types):
        return None, []
    passing = next((c for c in candidates if passes(*_size(c[1]))), None)
    if passing is not None:
        return passing, []
    mine = candidates[0]
    mine_size = _size(mine[1])
    mine_key = (_failures(*mine_size, None), -min(mine_size))
    archive_key = (_failures(*archive_size, types), -min(archive_size))
    hold = (f"cover: neither passes: {front['image']} ({archive_size[0]} by {archive_size[1]}), "
            f"{mine[0]} ({mine_size[0]} by {mine_size[1]})")
    return (mine if mine_key < archive_key else None), [hold]


def _is_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def _front_candidates(caa_images: list[dict]) -> list[dict]:
    kept = [image for image in caa_images if not _is_skipped(image)]
    return ([image for image in kept if image.get("front")]
            + [image for image in kept if not image.get("front") and "Front" in image.get("types", [])])


def front_thumbnail_url(caa_images: list[dict]) -> str | None:
    """The 250 px thumbnail (else `small`) of the release's own front, as the listing gives it, or None.

    The front is the one `plan_images` takes, told by the listing alone: whether
    a front is really a PDF is only known from its bytes, which this never fetches.
    """
    fronts = _front_candidates(caa_images)
    if not fronts:
        return None
    thumbnails = fronts[0].get("thumbnails", {})
    return thumbnails.get("250") or thumbnails.get("small")


def average_hash_or_none(data: bytes) -> int | None:
    """`average_hash(data)`, or None where `data` is not an image."""
    try:
        return average_hash(data)
    except _NOT_AN_IMAGE:
        return None


def plan_images(
    caa_images: list[dict],
    download: Callable[[str], bytes],
    group_images: Callable[[], list[dict]] | None = None,
    local: Sequence[tuple[str, bytes]] = (),
    existing: Mapping[str, bytes] | None = None,
) -> ImagePlan:
    """The album's image files, from the Cover Art Archive's list for the release.

    The front is the release's own; failing that, the front of the list
    `group_images()` returns (asked only then). It is `cover.jpg` when it
    `passes`; else the first of `local` (see `local_covers`) that Pillow can
    open and that passes; else, with both an archive front and a local cover
    failing, the better of the two, and the plan holds the album. With only
    one of the two, that one is `cover.jpg` whether or not it passes. Only the
    front falls back.

    A PDF is named by its position among the PDFs saved (duplicates of the
    folder or of an earlier PDF do not count), so the name is the same on every
    run: skipping an existing `booklet-1.pdf` leaves `booklet-2.pdf`.
    `existing` maps the album folder's file names to their bytes. An archive
    image other than the cover is not saved when its bytes, as they would be
    written, are a file in `existing` or an image saved before it.
    """
    existing = existing or {}
    downloads: dict[str, bytes] = {}

    def get(image: dict) -> bytes:
        url = image["image"]
        if url not in downloads:
            downloads[url] = download(url)
        return downloads[url]

    def first_front(listing: list[dict]) -> dict | None:
        return next((image for image in _front_candidates(listing) if not _is_pdf(get(image))), None)

    kept = [image for image in caa_images if not _is_skipped(image)]
    pdfs = [image for image in kept if _is_pdf(get(image))]
    pictures = [image for image in kept if image not in pdfs]

    front = first_front(caa_images)
    if front is None and group_images is not None:
        front = first_front(group_images())

    files: dict[str, bytes] = {}
    problems: list[str] = []
    holds: list[str] = []  # set by `_local_over_archive`
    consumed: str | None = None

    def fetch(image: dict) -> bytes | None:
        try:
            return _as_jpeg(get(image))
        except _NOT_AN_IMAGE:
            problems.append(f"cover art archive: {image['image']} is not an image")
            return None

    candidates: list[tuple[str, bytes]] = []
    for name, data in local:
        try:
            candidates.append((name, _as_jpeg(data)))
        except _NOT_AN_IMAGE:
            continue

    cover: bytes | None = None
    chosen: tuple[str, bytes] | None = None
    if front is not None:
        cover = fetch(front)
        # A broken front stays broken: it does not hand the cover to the folder.
        if cover is not None and candidates:
            chosen, holds = _local_over_archive(front, cover, candidates)
    elif candidates:
        chosen = next((c for c in candidates if passes(*_size(c[1]))), candidates[0])
    else:
        problems.append(
            "no front cover: not in the Cover Art Archive for the release or its release group, "
            "and no cover image in the folder")

    if chosen is not None:
        cover = chosen[1]
        # `front.*` is usually a scan of the booklet and is the owner's: copied, never consumed.
        if chosen[0].casefold() != "cover.jpg" and Path(chosen[0]).stem.casefold() != "front":
            consumed = chosen[0]
    if cover is not None:
        files["cover.jpg"] = cover

    have = set(existing.values())
    if cover is not None:
        have.add(cover)
    folder_names = {name.casefold() for name in existing}

    rest = [image for image in pictures if image is not front]
    fetched = _unseen(((image, picture) for image in rest if (picture := fetch(image)) is not None), have)

    counts: dict[str, int] = {}
    for image, _picture in fetched:
        base = _base_name(image)
        counts[base] = counts.get(base, 0) + 1

    seen: dict[str, int] = {}
    for image, picture in fetched:
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
        # A local `front.*` is never overwritten.
        if name == "front.jpg" and name in folder_names:
            continue
        files[name] = picture

    unique_pdfs = [data for _image, data in _unseen(((image, get(image)) for image in pdfs), have)]
    for number, data in enumerate(unique_pdfs, 1):
        name = "booklet.pdf" if len(unique_pdfs) == 1 else f"booklet-{number}.pdf"
        if name.casefold() not in folder_names:
            files[name] = data

    return ImagePlan(files=files, problems=problems, consumed=consumed, holds=holds)


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
