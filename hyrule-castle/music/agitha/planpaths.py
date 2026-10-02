"""Where the files and the album folder would sit once a plan's tags are written.

Paths follow tags by `docs/music-library.md` *Layout*, and only the parts
whose tag the draft changed; every other part stays as the library has it.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath

from musiclib import names, walk

from .albumplan import AlbumPlan, TrackPlan
from .refusal import TAKEN

_FILE_STEM = re.compile(r"(\d+)\. (.*)", re.DOTALL)
#: The run of `[Type] ` prefixes that opens an album folder's title.
_PREFIX_RUN = re.compile(r"(?:\[[^\[\]]+\] )*")


def _track_name(plan: TrackPlan, on_disc: int, number: int, title: str | None) -> str:
    """The file name `plan` would have: the number and the title the draft changed rebuilt, the rest as the name has it.

    `number` is the new track number where the draft changed it, else 0.
    """
    name = plan.path.rpartition("/")[2]
    suffix = PurePosixPath(name).suffix
    ext = suffix.lstrip(".")
    found = _FILE_STEM.fullmatch(name[:len(name) - len(suffix)])
    if found is None:
        tagged = plan.number("Track number", plan.after)
        return names.track_filename(tagged, title, ext, on_disc) if tagged and title else name
    if number:
        return names.track_filename(number, title or found.group(2), ext, on_disc)
    if title is None:
        return name
    # A number left alone keeps the digits the name has.
    return names.track_filename(int(found.group(1)), title, ext, digits=3 if len(found.group(1)) >= 3 else 2)


def name_files(plans: list[TrackPlan], disc_folders: bool) -> None:
    """Sets each track's `new_path` from the tags the draft changed in it; `disc_folders` is whether the album has `CDn` folders."""
    directories = {}
    for plan in plans:
        directories[plan.path] = plan.path.rpartition("/")[0]
        disc = plan.edited_number("Disc number")
        if disc_folders and disc:
            directories[plan.path] = names.disc_dir(disc)
    tracks_on_disc = Counter(directories.values())
    for plan in plans:
        directory = directories[plan.path]
        name = _track_name(plan, tracks_on_disc[directory], plan.edited_number("Track number"), plan.edited("Title"))
        plan.new_path = f"{directory}/{name}" if directory else name


def _split_folder(rest: str, old_title: str | None) -> tuple[list[str], str | None]:
    """The type prefixes and the edition of an album folder's name after its `(YYYY) `.

    A trailing bracket is the edition unless the album's own title ends in it
    or it is the mark of a cut name.
    """
    title = names.sanitize(old_title or "")
    prefix = _PREFIX_RUN.match(rest).group()  # type: ignore[union-attr]
    body = rest[len(prefix):]
    if title and rest.startswith(title) and not body.startswith(title):
        prefix, body = "", rest
    found = names.EDITION_RE.search(body)
    edition = found.group(1) if found and found.group(1) != "..." and not title.endswith(found.group(0)) else None
    return names.PREFIX_RE.findall(prefix), edition


def album_path(plans: list[TrackPlan], path: str) -> tuple[str, bool]:
    """Where the album at `path` would sit, from its first track as edited, and whether the folder keeps an edition suffix."""
    letter, artist, folder = path.split("/")
    first = plans[0]
    edition = False
    new_artist = first.edited("Album artist")
    if new_artist:
        artist = names.artist_folder(new_artist, known=False)
        letter = names.letter(artist)
    year, title = first.edited_year(), first.edited("Album")
    found = names.DATED_FOLDER_RE.fullmatch(folder)
    if found and (year or title):
        old_year, rest = found.groups()
        prefixes, edited = _split_folder(rest, first.first("Album", first.before))
        edition = edited is not None
        if title:
            label = names.sanitize(edited) if edited else ""
            folder = names.folder_name(year or old_year, prefixes, title, label or None)
        else:
            folder = f"({year}) {rest}"
    return f"{letter}/{artist}/{folder}", edition


def _in_any_case(parts: list[str], under: Path, own: Path) -> bool:
    """Whether `under / parts` holds a folder, spelt in any case, that is not `own`."""
    if not parts:
        try:
            return not under.samefile(own)
        except OSError:
            return False
    try:
        children = os.listdir(under)
    except OSError:
        return False
    return any(_in_any_case(parts[1:], under / child, own)
               for child in children if child.casefold() == parts[0].casefold())


def is_taken(root: Path, new_path: str, own: Path) -> bool:
    """Whether the library-relative `new_path`, spelt in any case, is a folder other than the album folder `own`."""
    return _in_any_case(new_path.split("/"), root, own)


def folder_taken(root: Path, folder: Path, plan: AlbumPlan) -> list[dict[str, str]]:
    """A problem where the album's new folder is already another album's; the folder renamed in case alone is its own."""
    if plan.new_path != plan.path and is_taken(root, plan.new_path, folder):
        return [{"rule": TAKEN, "detail": plan.new_path}]
    return []


def file_collisions(folder: Path, plan: AlbumPlan) -> list[dict[str, str]]:
    """One problem per file name two files would share, where a track moves onto it.

    A name matches in any case, and a track may take the name of any other
    file in the folder, track or not.
    """
    tracks = {track.path for track in plan.tracks}
    strangers = {rel.casefold() for path in walk.album_contents(folder)[0]
                 if (rel := path.relative_to(folder).as_posix()) not in tracks}
    claimed: dict[str, list[TrackPlan]] = {}
    for track in plan.tracks:
        claimed.setdefault(track.new_path.casefold(), []).append(track)
    return [{"rule": TAKEN, "detail": f"{plan.new_path}/{claimants[0].new_path}"}
            for name, claimants in claimed.items()
            if any(track.new_path != track.path for track in claimants) and (len(claimants) > 1 or name in strangers)]
