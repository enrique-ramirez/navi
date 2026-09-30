"""Stray files in an album folder: the name agitha guesses for each, and the names the owner may give one.

Everything here works on album-relative, `/`-separated path strings and on bytes it is handed, and reads no file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from musiclib import names
from musiclib.check import IMAGE_EXTS
from musiclib.images import ARCHIVE_TYPES, LOCAL_STEMS, LOCAL_SUFFIXES, NOT_AN_IMAGE, pixel_size, type_base

#: `front` and every type `images.plan_images` writes: the names a kept image may take.
LIBRARY_TYPES: tuple[str, ...] = ("front", *(type_base(t) for t in ARCHIVE_TYPES))

_TYPE_WORDS = {
    **dict.fromkeys(("front", "cover", "folder", "fr", "box"), "front"),
    **dict.fromkeys(("back", "rear"), "back"),
    **dict.fromkeys(("cd", "disc", "disk", "dvd", "onbody", "label", "vinyl"), "medium"),
    **dict.fromkeys(("tray", "inlay"), "tray"),
    **dict.fromkeys(("booklet", "book", "page", "inside", "insert", "sleeve"), "booklet"),
    **{word: word for word in ("obi", "spine", "sticker", "poster", "liner")},
}

#: Folders whose number-only images are booklet pages and whose PDFs are the booklet.
_BOOKLET_FOLDERS = {"scans", "scan", "booklet", "book", "сканы"}

#: A PDF whose name holds one of these is the booklet.
_BOOKLET_PDF_WORDS = {"booklet", "book", "scan"}

_WORD = re.compile(r"[^\W\d_]+|\d+")

_LIBRARY_NAME = re.compile(
    r"(?:booklet-(?:0[1-9]|[1-9]\d+)"
    rf"|(?:{'|'.join(re.escape(t) for t in LIBRARY_TYPES if t != 'booklet')})(?:-[1-9]\d*)?)"
)


def kind(path: str) -> str:
    """`image`, `pdf` or `text`, by the file's extension."""
    ext = PurePosixPath(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    return "pdf" if ext == ".pdf" else "text"


def _words(text: str) -> list[str]:
    """The runs of letters and the runs of digits in `text`, lowercased."""
    return [word.casefold() for word in _WORD.findall(text)]


def _natural(text: str) -> list:
    # `re.split` with a group alternates text and number, so two keys never compare a str with an int.
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text)]


def path_order(path: str) -> tuple:
    """Natural order folder by folder, then the stem without its extension; the path breaks ties."""
    *folders, file = path.split("/")
    return tuple(_natural(part) for part in (*folders, PurePosixPath(file).stem)), path


def _image_type(path: str) -> str | None:
    """The type `path`'s own words give, else its parent folder's; `None` when neither does."""
    *folders, file = path.split("/")
    stem = PurePosixPath(file).stem
    words = _words(stem)
    for at in range(len(words) - 1, -1, -1):
        type_ = _TYPE_WORDS.get(words[at])
        if type_ is None:
            continue
        # `Cover 1` is one of several covers the rip cannot tell apart, not the front.
        if type_ == "front" and at + 1 < len(words) and words[at + 1].isdigit():
            return None
        return type_
    folder = folders[-1] if folders else ""
    if words and all(word.isdigit() for word in words) and folder.casefold() in _BOOKLET_FOLDERS:
        return "booklet"
    for word in reversed(_words(folder)):
        if word in _TYPE_WORDS:
            return _TYPE_WORDS[word]
    return None


def _is_booklet_pdf(path: str) -> bool:
    *folders, file = path.split("/")
    if folders and folders[-1].casefold() in _BOOKLET_FOLDERS:
        return True
    return bool(_BOOKLET_PDF_WORDS.intersection(_words(PurePosixPath(file).stem)))


def _extension(path: str) -> str:
    """The extension a kept image takes: lowercased, `.jpeg` as `.jpg`."""
    ext = PurePosixPath(path).suffix.lower()
    return ".jpg" if ext == ".jpeg" else ext


def guess(paths: Sequence[str], discs: Mapping[str, int] | None = None) -> dict[str, str | None]:
    """The file name each stray in `paths` is guessed to keep, or `None` where there is no guess.

    Numbering follows the archive's (`images.plan_images`) over the whole
    list, in natural order of path, so the result does not depend on the
    order of `paths`. `discs` maps a first-level disc folder's name to its
    disc number.
    """
    discs = discs or {}
    ordered = sorted(dict.fromkeys(paths), key=path_order)
    result: dict[str, str | None] = {}

    images: dict[str, list[str]] = {}
    pdfs: list[str] = []
    for path in ordered:
        match kind(path):
            case "image":
                type_ = _image_type(path)
                if type_ is None:
                    result[path] = None
                else:
                    images.setdefault(type_, []).append(path)
            case "pdf" if _is_booklet_pdf(path):
                pdfs.append(path)
            case _:
                own = PurePosixPath(path).name
                result[path] = None if name_offence(path, own) else own

    for type_, group in images.items():
        claimed: dict[str, int] = {}
        taken: set[int] = set()
        if type_ == "medium":
            for path in group:
                folders = path.split("/")[:-1]
                number = discs.get(folders[0]) if folders else None
                if number is not None and number not in taken and not re.search(r"\d", PurePosixPath(path).stem):
                    claimed[path] = number
                    taken.add(number)
        free = (number for number in range(1, len(group) + 1) if number not in taken)
        for path in group:
            ext = _extension(path)
            if path in claimed:
                result[path] = f"{type_}-{claimed[path]}{ext}"
            elif type_ == "booklet":
                result[path] = f"booklet-{next(free):02d}{ext}"
            elif len(group) > 1:
                result[path] = f"{type_}-{next(free)}{ext}"
            else:
                result[path] = f"{type_}{ext}"

    for number, path in enumerate(pdfs, 1):
        result[path] = "booklet.pdf" if len(pdfs) == 1 else f"booklet-{number}.pdf"

    return {path: result[path] for path in paths}


def name_offence(path: str, name: str) -> str | None:
    """`None` when the owner may give `path` the file name `name`, else one line saying why not."""
    def refuse(reason: str) -> str:
        return f"{path} cannot be named {name!r}: {reason}."

    if "/" in name:
        return refuse("a name cannot hold a /")
    own_ext = PurePosixPath(path).suffix
    if kind(path) == "image":
        own_ext = _extension(path)
    stem = name[: len(name) - len(own_ext)] if own_ext else name
    if not own_ext or not name.endswith(own_ext) or not stem:
        return refuse(f"it must end in {own_ext or 'the file’s own extension'}")
    if stem.casefold() == "cover":
        return refuse("cover is the front's own name")
    if kind(path) == "image":
        if not _LIBRARY_NAME.fullmatch(stem):
            return refuse("an image takes a library name such as front, back-2 or booklet-03")
        return None
    if names.sanitize(name) != name:
        return refuse("the name holds characters a Windows or FAT32 name cannot")
    return None


def is_root_stray(name: str) -> bool:
    """Whether an image at the album folder's root named `name` is a stray.

    Not a stray: a name `images.local_covers` reads as a cover (which includes
    `cover.jpg`), and a library name.
    """
    path = PurePosixPath(name)
    stem = path.stem.casefold()
    if stem in LOCAL_STEMS and path.suffix.casefold() in LOCAL_SUFFIXES:
        return False
    return not _LIBRARY_NAME.fullmatch(stem)


def name_key(name: str) -> tuple[str, str]:
    """What two file names must share to be the same name: an image's stem, any other file's whole name, casefolded."""
    if kind(name) == "image":
        return "image", PurePosixPath(name).stem.casefold()
    return "file", name.casefold()


@dataclass(frozen=True)
class Stray:
    """One stray and what happens to it. `answer` is `{"keep": name}`, `{"delete": True}` or `None` for undecided.

    `why` is `guessed`, `copy`, `lost`, `won`, `owner` or `no guess`; `against`
    names the other file for `copy`, `lost` and `won`.
    """

    path: str
    kind: str
    answer: dict | None
    why: str
    against: str | None
    size: tuple[int, int] | None

    def to_json(self) -> dict:
        return {"path": self.path, "kind": self.kind, "answer": self.answer, "why": self.why,
                "against": self.against, "size": list(self.size) if self.size else None}

    @property
    def keeps(self) -> str | None:
        return self.answer.get("keep") if self.answer else None


def _pixels(data: bytes) -> tuple[int, int] | None:
    try:
        return pixel_size(data)
    except NOT_AN_IMAGE:
        return None


def _beats(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    """Whether `a` has at least 10 % more pixels than `b`; an image that cannot be read beats nothing."""
    return a is not None and b is not None and 10 * a[0] * a[1] >= 11 * b[0] * b[1]


def settle(contents: Mapping[str, bytes], discs: Mapping[str, int], owner: Mapping[str, str | None],
           cover: bytes | None, archive: Mapping[str, bytes], folder: Mapping[str, bytes]) -> list[Stray]:
    """Every stray in `contents` (path to bytes), answered, in natural order of path.

    `discs` is `guess`'s argument of that name; `owner` the accept's `strays`
    (a name, or `None` to delete). `cover` is `cover.jpg` as planned,
    `archive` the other images the plan saves and `folder` the files already
    at the album folder's root that are not strays, each by name. Order of
    answering: the owner's word; a copy of the cover, an archive image, a
    folder file or a stray earlier in path order that stays; then the
    quality test (at least 10 % more pixels) among the strays and files
    sharing a name, where the folder's file and then the archive's win a tie.
    """
    ordered = sorted(contents, key=path_order)
    sizes = {path: _pixels(contents[path]) if kind(path) == "image" else None for path in ordered}
    answers: dict[str, tuple[dict | None, str, str | None]] = {}

    owner_keys: set[tuple[str, str]] = set()
    for path in ordered:
        if path in owner:
            name = owner[path]
            answers[path] = ({"delete": True} if name is None else {"keep": name}, "owner", None)
            if name is not None:
                owner_keys.add(name_key(name))

    standing: list[tuple[bytes, str]] = []
    if cover is not None:
        standing.append((cover, "cover.jpg"))
    standing += [(data, name) for name, data in sorted(archive.items())]
    standing += [(data, name) for name, data in sorted(folder.items())]
    candidates = []
    for path in ordered:
        if path in answers:
            if answers[path][0] != {"delete": True}:
                standing.append((contents[path], path))
            continue
        twin = next((label for data, label in standing if data == contents[path]), None)
        if twin is not None:
            answers[path] = ({"delete": True}, "copy", twin)
        else:
            standing.append((contents[path], path))
            candidates.append(path)

    # Guessed over the strays that are left, so a copy takes no number from those that stay,
    # and the names below are the final ones the archive's and the folder's are compared with.
    guesses = guess(candidates, discs)
    groups: dict[tuple[str, str], list[str]] = {}
    for path in candidates:
        guessed = guesses.get(path)
        if guessed is None:
            answers[path] = (None, "no guess", None)
        elif name_key(guessed) in owner_keys:
            answers[path] = (None, "no guess", None)
        else:
            groups.setdefault(name_key(guessed), []).append(path)

    for key, group in groups.items():
        # The folder's file is listed before the archive's: where no image is clearly larger they win,
        # and `against` names the first.
        outside = [(name, data) for name, data in (*sorted(folder.items()), *sorted(archive.items()))
                   if name_key(name) == key]
        rivals = [(name, _pixels(data) if kind(name) == "image" else None) for name, data in outside]
        rivals += [(path, sizes[path]) for path in group]
        strong = next((label for label, size in rivals
                       if all(_beats(size, other) for label_, other in rivals if label_ != label)), None)
        if strong in group:
            for path in group:
                if path == strong:
                    answers[path] = ({"keep": guesses[path]}, "won" if len(rivals) > 1 else "guessed",
                                     next((label for label, _ in rivals if label != path), None))
                else:
                    answers[path] = ({"delete": True}, "lost", strong)
        elif outside:
            for path in group:
                answers[path] = ({"delete": True}, "lost", outside[0][0])
        elif len(group) == 1:
            answers[group[0]] = ({"keep": guesses[group[0]]}, "guessed", None)
        else:
            for path in group:
                answers[path] = (None, "no guess", None)

    return [Stray(path, kind(path), *answers[path], sizes[path]) for path in ordered]


def answer_offences(entry: dict, strays: object) -> list[str]:
    """One sentence per offence in an accept's `strays`, against the stray list of the album's entry in the previous `plan.json`.

    An entry planned before strays existed has no list, so only the name
    rules apply to it. Names are compared by `name_key`, as the engine settles them:
    an image by its stem, any other file by its whole name, casefolded.
    """
    if not isinstance(strays, dict) or not all(name is None or isinstance(name, str) for name in strays.values()):
        return [f"strays must be paths to a name or null, not {strays!r}"]
    known = {stray["path"] for stray in entry["strays"]} if "strays" in entry else None
    source = entry.get("source", "")
    taken = {name_key(PurePosixPath(path).name) for path in entry.get("kept") or []
             if PurePosixPath(path).parent.as_posix() == source
             and PurePosixPath(path).relative_to(source).as_posix() not in (known or set())}
    destination = entry.get("destination")
    taken |= {name_key(PurePosixPath(planned["destination"]).name) for planned in entry.get("files") or []
              if PurePosixPath(planned.get("destination", "")).parent.as_posix() == destination}
    offences = []
    kept_as = {name_key(row["answer"]["keep"]): row["path"] for row in entry.get("strays") or []
               if row["path"] not in strays and isinstance(row.get("answer"), dict) and "keep" in row["answer"]}
    named: dict[str, str] = {}
    for path, name in strays.items():
        key = name_key(name) if name is not None else None
        if known is not None and path not in known:
            offences.append(f"{path} is not a stray of this album")
        elif name is None:
            continue
        elif offence := name_offence(path, name):
            offences.append(offence)
        elif key in taken:
            offences.append(f"{path} cannot be named {name!r}: the album already has a file of that name.")
        elif key in named or key in kept_as:
            holder = named.get(key) or kept_as[key]
            offences.append(f"{path} cannot be named {name!r}: {holder} has that name.")
        else:
            named[key] = path
    return offences
