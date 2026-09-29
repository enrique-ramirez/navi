"""The one walk of the library, shared by `units` and `check`, that leaves NAS and OS litter alone."""

from __future__ import annotations

from pathlib import Path

#: Folder names, compared lower-cased, that are never music.
_IGNORED_FOLDERS = {"@eadir", "#recycle", "#snapshot", "lost+found", "system volume information",
                    "$recycle.bin", ".appledouble"}
#: A desktop trash is `.Trash-<uid>`; an NFS client leaves `.nfs<hex>` for a file deleted while open.
_IGNORED_FOLDER_PREFIX = ".trash-"
_IGNORED_FILE_PREFIX = ".nfs"


def is_ignored(name: str) -> bool:
    """Whether one path component is litter. A name that merely starts with `.` is not."""
    lower = name.lower()
    return lower in _IGNORED_FOLDERS or lower.startswith((_IGNORED_FOLDER_PREFIX, _IGNORED_FILE_PREFIX))


def _music_dirs(parent: Path) -> list[Path]:
    return sorted(p for p in Path(parent).iterdir()
                  if p.is_dir() and not p.is_symlink() and not is_ignored(p.name))


def child_dirs(parent: Path) -> list[Path]:
    """The folders directly under `parent` that are music folders, in path order; none if it cannot be listed."""
    try:
        return _music_dirs(parent)
    except OSError:
        return []


def album_dirs(root: Path) -> list[Path]:
    """Every `Letter/Artist/Album` folder under `root`, in path order.

    A folder below `root` that cannot be listed is skipped. `root` itself
    raises: a misspelt or unmounted library must not read as an empty one.
    """
    return [album for letter in _music_dirs(root)
            for artist in child_dirs(letter)
            for album in child_dirs(artist)]


def album_contents(album_dir: Path) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Every file under `album_dir` at any depth, in path order, none inside an ignored folder.

    Also each folder that could not be listed, in path order, with the reason;
    that includes `album_dir` itself.
    """
    found: list[Path] = []
    unlistable: list[tuple[Path, str]] = []
    pending = [Path(album_dir)]
    while pending:
        folder = pending.pop()
        try:
            entries = list(folder.iterdir())
        except OSError as exc:
            unlistable.append((folder, f"folder is unreadable: {exc.strerror or type(exc).__name__}"))
            continue
        for entry in entries:
            if is_ignored(entry.name):
                continue
            if entry.is_dir() and not entry.is_symlink():
                pending.append(entry)
            elif entry.is_file():
                found.append(entry)
    return sorted(found), sorted(unlistable)
