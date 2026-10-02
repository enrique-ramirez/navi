"""Putting a finished album folder in the library in place of the library's copy, in five steps.

Both callers go through `swap`: the review flow's Keep the new one
(`duplicates.replace`) and a hand edit's save (`saves.run`). Every step is an
`os.rename` or an `os.replace` and never a copy, so a failure leaves each
folder whole on one side or the other. The work folder `folder` holds what a
start needs to put the library's copy back: `replaced.json`, `replaced/`
and, once the new folder has verified, `committed/`.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
from pathlib import Path
from typing import NamedTuple

from musiclib import files

from . import audio, drops, log

#: Each file of a folder by its path: its SHA-256 and, for audio, its length.
_Record = dict[str, tuple[str, float | None]]


class _Problem(Exception):
    def __init__(self, step: int, file: Path, reason: str) -> None:
        super().__init__(reason)
        self.step, self.file, self.reason = step, file, reason


class _Changed(_Problem):
    """Step 2 found a file of the library's copy changed since it was stamped; `reason` is the whole sentence."""


class Unchanged(NamedTuple):
    """What the library's folder held before the new folder was made from it, and what to say where it holds something else."""

    held: dict[str, list[int]]
    sentence: str


class Failure(NamedTuple):
    """A swap that did not finish: the step that failed, what was done about it, and whether the library's copy is back."""

    problem: _Problem
    outcome: str
    restored: bool

    @property
    def at(self) -> tuple[int | None, str | None]:
        """The step and file the failure is recorded under; neither where no step went wrong but the library's copy had changed."""
        if isinstance(self.problem, _Changed) and self.restored:
            return None, None
        return self.problem.step, str(self.problem.file)

    @property
    def sentence(self) -> str:
        """Where it failed and what was done about it; a library copy that changed and is back is told as `Unchanged` says."""
        problem = self.problem
        if isinstance(problem, _Changed) and self.restored:
            return problem.reason
        return f"Step {problem.step} failed at {problem.file}: {problem.reason}. {self.outcome}"


def _files(folder: Path) -> list[Path]:
    """Every file of `folder` and every link, each as itself: a link is never followed, as a relative one may dangle in another folder."""
    return [p for p in folder.rglob("*") if p.is_symlink() or p.is_file()]


def _length(path: Path) -> float | None:
    found = audio.facts(path) if path.suffix.lower() in files.AUDIO_EXTENSIONS and not path.is_symlink() else None
    return found.length if found else None


def _digest(path: Path) -> str:
    """The SHA-256 of a file's bytes, or of the text of a link."""
    if path.is_symlink():
        return hashlib.sha256(b"link:" + os.fsencode(os.readlink(path))).hexdigest()
    return drops.file_sha256(path)


def _record(folder: Path) -> _Record:
    """Step 1: every file's SHA-256 by its path in `folder`, and an audio file's length as mutagen reads it now."""
    return {p.relative_to(folder).as_posix(): (_digest(p), _length(p)) for p in sorted(_files(folder))}


def stranded(folder: Path) -> bool:
    """Whether the album folder `folder` holds a library copy set aside, which only Move may settle."""
    aside = folder / "replaced"
    return aside.is_dir() and bool(_files(aside))


def _saved(folder: Path) -> tuple[str, _Record] | None:
    """The library copy's path and the step 1 record an earlier run left in `replaced.json`, where it is stranded."""
    body = drops.read_json(folder / "replaced.json")
    if body is None or not stranded(folder):
        return None
    try:
        return body["copy"], {name: (digest, length) for name, (digest, length) in body["files"].items()}
    except (KeyError, TypeError, ValueError):
        return None


def _verify(folder: Path, recorded: _Record) -> None:
    """Step 4: the names, the hashes, and that each audio file opens with the length step 1 read, within 0.1 s.

    The plan holds no length per file, so the length compared is the finished
    folder's own, taken before it moved.
    """
    now = {p.relative_to(folder).as_posix() for p in _files(folder)}
    for name in sorted(set(recorded) - now):
        raise _Problem(4, folder / name, "the file is missing after the move")
    for name in sorted(now - set(recorded)):
        raise _Problem(4, folder / name, "the file was not in the finished folder")
    for name, (digest, length) in sorted(recorded.items()):
        path = folder / name
        try:
            if _digest(path) != digest:
                raise _Problem(4, path, "its SHA-256 differs from the finished folder's")
        except OSError as exc:
            raise _Problem(4, path, f"could not be read: {exc.strerror or exc}") from exc
        if path.suffix.lower() in files.AUDIO_EXTENSIONS:
            found = _length(path)
            # A file no reader opened at step 1 and none opens now is unchanged.
            if (found is None) != (length is None) or (found is not None and abs(found - length) > 0.1):
                raise _Problem(4, path, "it does not open, or its length changed")


def stamps(folder: Path) -> dict[str, list[int]]:
    """Each file of `folder` by its path, with its size and mtime in nanoseconds; lists, so it reads back from JSON as it was."""
    found = {}
    for path in sorted(_files(folder)):
        stat = path.lstat()
        found[path.relative_to(folder).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return found


def missing_parents(path: Path, root: Path) -> list[Path]:
    """The folders between `root` and `path` that do not exist yet, the deepest first."""
    return [folder for folder in path.parents if folder.is_relative_to(root) and folder != root
            and not folder.exists()]


def remove_empty(folders: list[Path]) -> None:
    for folder in folders:
        with contextlib.suppress(OSError):
            folder.rmdir()


def move_extras(extras: Path, old: str, new: str) -> str | None:
    """Moves the album's extras from `old` to `new` under `extras`, with the folders it empties pruned.

    None where they moved or there was nothing to move; else why they could not.
    """
    source, target = extras / old, extras / new
    if new == old or not source.exists():
        return None
    made = missing_parents(target, extras)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        remove_empty(made)
        return exc.strerror or str(exc)
    prune(source.parent, extras)
    return None


def prune(start: Path, stop: Path) -> None:
    """Removes the empty folders from `start` up to, not including, `stop`."""
    for parent in (start, *start.parents):
        if parent == stop:
            return
        try:
            parent.rmdir()
        except OSError:
            return


def after_landing(library: Path, extras: Path, old: str, new: str) -> str | None:
    """What follows an album landing at `new` in the library where it was at `old`: the folders it left empty go, and its extras follow.

    None where all of it was done. Else the sentence for the extras that
    could not follow; the library is already as the owner wants it.
    """
    prune((library / old).parent, library)
    if (why := move_extras(extras, old, new)) is not None:
        return f"The album is in the library at {new}, but its extras could not be moved: {why}."
    return None


def _set_aside(library_folder: Path, aside: Path) -> None:
    try:
        aside.parent.mkdir(parents=True, exist_ok=True)
        os.rename(library_folder, aside)
    except OSError as exc:
        raise _Problem(2, library_folder, f"could not be set aside: {exc.strerror or exc}") from exc


def _begin(folder: Path, source: Path, library_folder: Path, aside: Path, relative: str) -> _Record:
    """Steps 1 and 2: the record of the new folder, saved, and then the library's copy set aside."""
    try:
        recorded = _record(source)
        drops.replace_json(folder / "replaced.json", {"copy": relative, "files": recorded})
    except OSError as exc:
        raise _Problem(1, Path(exc.filename) if exc.filename else source,
                       f"could not be read or recorded: {exc.strerror or exc}") from exc
    _set_aside(library_folder, aside)
    return recorded


def _move_in(source: Path, target: Path) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        raise _Problem(3, target, f"could not be moved into the library: {exc.strerror or exc}") from exc


def _restore_old(folder: Path, aside: Path, library_folder: Path, problem: _Problem) -> Failure:
    """The undo of step 2, and the failure for `problem`."""
    try:
        os.rename(aside, library_folder)
    except OSError as exc:
        return Failure(problem, f"The library's copy could not be put back and is at {aside}: {exc.strerror or exc}.",
                       False)
    prune(aside.parent, folder)
    (folder / "replaced.json").unlink(missing_ok=True)
    return Failure(problem, "The library's copy is back where it was.", True)


def _remove_new_and_restore_old(folder: Path, source: Path, target: Path, aside: Path, library_folder: Path,
                                problem: _Problem) -> Failure:
    """The undo of step 3, then of step 2, after a step that came once the new folder was in the library."""
    try:
        os.rename(target, source)
    except OSError as exc:
        return Failure(problem, f"The new album could not be moved out of the library ({exc.strerror or exc}); "
                                f"the library's copy stays at {aside}.", False)
    return _restore_old(folder, aside, library_folder, problem)


def swap(library: Path, folder: Path, source: Path, target: Path, library_folder: Path | None,
         unchanged: Unchanged | None = None) -> Failure | None:
    """The five steps of a swap: the finished folder `source`, under the work folder `folder`, for the library's copy.

    1 records the new folder's hashes and lengths in `replaced.json`, 2 sets
    the library's copy `library_folder` (under `library`) aside, 3 renames
    the new folder in at `target`, 4 verifies it, 5 deletes the copy set
    aside (`_commit`). Where an earlier run left the copy set aside
    (`stranded`), this one resumes at step 3 against that record and
    `library_folder` and `unchanged` are not used.

    A file stored in the library's copy while step 1 hashes the new folder
    would be lost with the copy, so once step 2 has set it aside it is
    stamped again, and where `unchanged` says it held other stamps it is put
    back and the swap fails with the sentence of `unchanged`.

    None where the new folder is in the library and the old copy is deleted,
    or a delete cut short has left the rest of it for `restore_after_crash`.
    Otherwise the failure, with the library's copy back where it was where
    it could be put back, and the folders made for `target` removed.
    """
    made = missing_parents(target, library)
    failure = _steps(library, folder, source, target, library_folder, unchanged)
    if failure is not None:
        remove_empty(made)
    return failure


def _steps(library: Path, folder: Path, source: Path, target: Path, library_folder: Path | None,
           unchanged: Unchanged | None) -> Failure | None:
    saved = _saved(folder)
    if saved is not None:
        relative, recorded = saved
        library_folder = library / relative
        aside = folder / "replaced" / relative
    else:
        assert library_folder is not None
        relative = library_folder.relative_to(library).as_posix()
        aside = folder / "replaced" / relative
        try:
            recorded = _begin(folder, source, library_folder, aside, relative)
        except _Problem as problem:
            prune(aside.parent, folder)
            (folder / "replaced.json").unlink(missing_ok=True)
            return Failure(problem, "Nothing was moved.", True)
        if unchanged is not None and stamps(aside) != unchanged.held:
            return _restore_old(folder, aside, library_folder, _Changed(2, library_folder, unchanged.sentence))

    try:
        _move_in(source, target)
    except _Problem as problem:
        return _restore_old(folder, aside, library_folder, problem)

    try:
        _verify(target, recorded)
    except _Problem as problem:
        return _remove_new_and_restore_old(folder, source, target, aside, library_folder, problem)

    return _commit(folder, source, target, aside, library_folder)


def _commit(folder: Path, source: Path, target: Path, aside: Path, library_folder: Path) -> Failure | None:
    """Step 5: the verified new folder is committed by renaming `replaced` to `committed`, and the copy under it is deleted.

    From the rename on, a delete cut short never leaves a half-deleted copy
    to be put back: `restore_after_crash` and Move keep the new folder and
    finish the delete. A delete that removed nothing is not a commit: the
    name goes back and the old folder is put back. One that removed
    something is, and the new folder stays.
    """
    replaced, committed = folder / "replaced", folder / "committed"
    deleting = committed / aside.relative_to(replaced)
    try:
        os.rename(replaced, committed)
    except OSError as exc:
        return _remove_new_and_restore_old(
            folder, source, target, aside, library_folder,
            _Problem(5, aside, f"the library's copy could not be marked for deletion: {exc.strerror or exc}"))
    held = len(_files(committed))
    shutil.rmtree(committed, ignore_errors=True)
    if len(_files(committed)) == held:
        problem = _Problem(5, deleting, "the library's copy could not be deleted")
        try:
            os.rename(committed, replaced)
        except OSError as exc:
            return Failure(problem, f"The library's copy could not be put back and is at {deleting}: "
                                    f"{exc.strerror or exc}.", False)
        return _remove_new_and_restore_old(folder, source, target, aside, library_folder, problem)
    (folder / "replaced.json").unlink(missing_ok=True)
    return None


def is_committed(folder: Path) -> bool:
    """Whether a swap under the work folder `folder` verified the new folder and did not finish deleting the old copy."""
    return (folder / "committed").exists()


def unsettled(folder: Path) -> bool:
    """Whether the work folder `folder` holds a landing that only Move may finish: a copy set aside, or a commit not cleaned up."""
    return stranded(folder) or is_committed(folder)


def committed_copy(folder: Path) -> str | None:
    """The library-relative path of the copy a committed swap under `folder` replaced, or `None`.

    `restore_after_crash` deletes the record this reads, so it is asked first.
    """
    copy = (drops.read_json(folder / "replaced.json") or {}).get("copy") if is_committed(folder) else None
    return copy if isinstance(copy, str) else None


def restore_after_crash(library: Path, folder: Path, landed: str | None) -> str | None:
    """Puts back the library copy a swap left set aside under the work folder `folder`, as it was.

    `landed` is the library-relative path the new folder was renamed to, or
    `None` where it was not; a folder at `landed` is taken out first. A
    swap that had committed is finished instead: the new folder stays. None
    where the library holds one whole album; else why not.
    """
    if is_committed(folder):
        shutil.rmtree(folder / "committed", ignore_errors=True)
        if is_committed(folder):
            # `replaced.json` stays: a later start still has the old path to finish the landing from.
            log.failed("finish-landing", landed or folder, "the old copy could not be deleted")
            return f"the old copy under {folder / 'committed'} could not be deleted"
        (folder / "replaced.json").unlink(missing_ok=True)
        log.write("finish-landing", landed or folder)
        return None
    saved = _saved(folder)
    if saved is None:
        return None
    relative, _recorded = saved
    aside = folder / "replaced" / relative
    new = library / landed if landed else None
    try:
        if new is not None and new.exists():
            away = folder / "undone" / landed
            away.parent.mkdir(parents=True, exist_ok=True)
            os.rename(new, away)
        (library / relative).parent.mkdir(parents=True, exist_ok=True)
        os.rename(aside, library / relative)
    except OSError as exc:
        log.failed("restore", relative, f"could not be put back from {aside}: {exc.strerror or exc}")
        return f"the library's copy could not be put back from {aside}: {exc.strerror or exc}"
    log.write("restore", relative)
    if new is not None:
        prune(new.parent, library)
    prune(aside.parent, folder)
    (folder / "replaced.json").unlink(missing_ok=True)
    return None
