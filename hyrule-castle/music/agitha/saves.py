"""A hand edit, saved: `POST /api/library/save` and `GET /api/library/jobs/<id>`.

A save is a job of one entry per album. Each album is a function on the
queue's one worker, so a library folder never has two writers. It copies
the album into its own work folder, `config.jobs / "library-edits" / <job
id> / <n>`, writes the changed files of the copy, renames inside the copy,
checks the copy, and swaps it in by `swap.swap`'s five steps. Anything that
fails leaves the library as it was and the reason in the job.

A work folder is deleted only once the library is settled. One that still
holds a set-aside copy is put back by `recover`, which `make_server` runs.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import sys
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musiclib import check, files, images, tagwrite, walk

from . import covers, drops, editor, library, log, swap
from .albumplan import AlbumPlan
from .refusal import ALBUM_CHANGED, BEING_SAVED, OPEN_IN_REVIEW, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

RACED = "the library's copy changed while saving; save again"
NOTHING_TO_SAVE = "nothing to save"
#: Where a job's work folder is, under `Config.jobs`.
WORK = "library-edits"
#: In the work folder: where the new album folder was to land, so a start can take it out again.
LANDING = "edit.json"
WAITING, WRITING, VERIFYING, DONE, FAILED = "waiting", "writing", "verifying", "done", "failed"
OPEN = (WAITING, WRITING, VERIFYING)


@dataclass
class JobAlbum:
    path: str
    new_path: str
    state: str = WAITING
    error: str | None = None


class Jobs:
    """The jobs of this process, by id. A restart forgets them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, list[JobAlbum]] = {}

    def add(self, plans: list[AlbumPlan]) -> tuple[str, list[JobAlbum]]:
        job, entries = secrets.token_hex(8), [JobAlbum(plan.path, plan.new_path) for plan in plans]
        with self._lock:
            self._jobs[job] = entries
        return job, entries

    def forget(self, job: str) -> None:
        with self._lock:
            self._jobs.pop(job, None)

    def settle(self, album: JobAlbum, state: str, error: str | None = None) -> None:
        with self._lock:
            album.state, album.error = state, error

    def answer(self, job: str) -> dict[str, Any] | None:
        with self._lock:
            albums = self._jobs.get(job)
            return None if albums is None else {"albums": [asdict(album) for album in albums]}

    def active(self, path: str) -> dict[str, str] | None:
        """`{id, state}` of the save of the album at `path` that is waiting or running, else `None`."""
        with self._lock:
            for job, albums in self._jobs.items():
                for album in albums:
                    if album.path == path and album.state in OPEN:
                        return {"id": job, "state": album.state}
        return None


class Failed(Exception):
    """A save that did not land; `clean` is whether its work folder holds nothing `recover` needs."""

    def __init__(self, reason: str, clean: bool = True) -> None:
        super().__init__(reason)
        self.clean = clean


def _has_changes(plan: AlbumPlan) -> bool:
    return (plan.cover_token is not None or plan.new_path != plan.path
            or any(track.changes() or track.new_path != track.path for track in plan.tracks))


def _named_albums(draft: editor.Draft) -> list[str]:
    """The albums an edit, a swap or the cover of `draft` names; one that only lists a track changes nothing."""
    if draft.swaps or draft.cover is not None:
        return list(dict.fromkeys(album for album, _path in draft.tracks))
    return list(dict.fromkeys(album for edit in draft.edits for album in edit.paths))


def save(request: Handler, match: re.Match[str], config: Config) -> None:
    draft = editor.parse(request.read_json())
    server = request.server
    named = _named_albums(draft)
    if any(server.queue.busy_library(album) for album in named):
        raise Refusal(409, BEING_SAVED)
    if not draft.batch:
        in_review = drops.open_matches(config)
        if any(album in in_review for album in named):
            raise Refusal(409, OPEN_IN_REVIEW)
    planned = editor.plan(config, draft)
    if draft.batch:
        # The albums a batch cannot go through with are in the preview with their reasons; the others are saved.
        todo = [plan for plan in planned.albums if plan.skip is None]
    else:
        if planned.stale:
            raise Refusal(409, ALBUM_CHANGED)
        for plan in planned.albums:
            if (sentence := plan.problem_sentence()) is not None:
                raise Refusal(409, sentence)
        todo = [plan for plan in planned.albums if _has_changes(plan)]
    if not todo:
        raise Refusal(409, NOTHING_TO_SAVE)
    job, entries = server.save_jobs.add(todo)
    base = config.jobs / WORK / job
    calls = [(plan.path, partial(run, config, server.save_jobs, plan, entry, base / str(n), len(draft.swaps)))
             for n, (plan, entry) in enumerate(zip(todo, entries))]
    if not server.queue.enqueue_library(calls):
        server.save_jobs.forget(job)
        raise Refusal(409, BEING_SAVED)
    request.send_json(202, {"job": job})


def show(request: Handler, match: re.Match[str], config: Config) -> None:
    found = request.server.save_jobs.answer(match.group(1))
    if found is None:
        raise Refusal(404, "No such job.")
    request.send_json(200, found)


def _logged(plan: AlbumPlan, swaps: int) -> dict[str, Any]:
    """What a save of `plan` changes, as the write log tells it: counts and the names of the tags, never a value."""
    changed = [changes for track in plan.tracks if (changes := track.changes())]
    tags = sorted({change["key"] for changes in changed for change in changes})
    return {
        "to": plan.new_path if plan.new_path != plan.path else None,
        "tracks": len(changed), "tags": ",".join(tags) or None,
        "renamed": sum(track.new_path != track.path for track in plan.tracks) or None,
        "swaps": swaps or None, "cover": "replaced" if plan.cover_token is not None else "kept",
    }


def run(config: Config, jobs: Jobs, plan: AlbumPlan, entry: JobAlbum, work: Path, swaps: int = 0) -> None:
    """Saves one album on the queue's worker and records how it went in the job.

    Only `Exception` is caught, and `work` is not deleted in a `finally`: the
    set-aside copy in it is what `recover` restores the album from. An error
    nobody expected puts the album back the way `recover` would, and `work`
    goes only where that worked.
    """
    jobs.settle(entry, WRITING)
    try:
        extras = _land(config, jobs, entry, plan, work)
    except Failed as failed:
        if failed.clean:
            _clear(config, work)
        log.failed("save", plan.path, failed)
        jobs.settle(entry, FAILED, str(failed))
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if (why := _restore(config, work)) is not None:
            reason = f"{reason}; {why}"
        log.failed("save", plan.path, reason)
        jobs.settle(entry, FAILED, reason)
    else:
        # The album is in the library either way, so the work folder and the cover upload have done their part.
        _clear(config, work)
        if plan.cover_token is not None:
            covers.discard(config, plan.cover_token)
        log.write("save", plan.path, **_logged(plan, swaps), note=extras)
        jobs.settle(entry, DONE if extras is None else FAILED, extras)


def _clear(config: Config, work: Path) -> None:
    """Deletes the work folder and the job's folder where it was the last one."""
    shutil.rmtree(work, ignore_errors=True)
    swap.prune(work.parent, config.jobs / WORK)


def _restore(config: Config, work: Path) -> str | None:
    """Settles the library from a work folder and clears it; else why not, and it stays.

    A swap that had not committed is undone: the library's copy it set aside
    is put back. One that had is finished: the new folder stays and what
    follows a landing is done, and the answer is the sentence of the extras
    that could not follow, if any.
    """
    landed = (drops.read_json(work / LANDING) or {}).get("landed")
    # The new folder is in the library only where it is no longer in the work folder.
    if not isinstance(landed, str) or (work / "new" / landed).exists():
        landed = None
    # `restore_after_crash` deletes the record of where the old copy was.
    old = swap.committed_copy(work)
    if (why := swap.restore_after_crash(config.library, work, landed)) is not None:
        return why
    _clear(config, work)
    if old is not None and landed is not None:
        return swap.after_landing(config.library, config.extras, old, landed)
    return None


def _write(plan: AlbumPlan, folder: Path) -> None:
    """Writes into the copy the keys of each track the draft changed, each as the plan has it, and nothing else."""
    for track in plan.tracks:
        keys = [real for _shown, real in track.named if track.before.get(real) != track.after.get(real)]
        if not keys:
            continue
        live = files.read(str(folder / track.path))
        tagwrite.write(live, tagwrite.merge(live, {real: track.after.get(real) for real in keys}))


def _lay_cover(config: Config, plan: AlbumPlan, folder: Path) -> None:
    """Makes the upload the copy's `cover.jpg`, at full size, and gives every track that image as its one front cover."""
    assert plan.cover_token is not None
    jpeg = images.as_jpeg(covers.read(config, plan.cover_token))
    cover = folder / "cover.jpg"
    # A linked `cover.jpg` is replaced by the file, never written through to what it names.
    if cover.is_symlink():
        cover.unlink()
    cover.write_bytes(jpeg)
    front = images.embedded_front(jpeg)
    for track in plan.tracks:
        images.embed(folder / track.path, front)


def _rename(plan: AlbumPlan, folder: Path) -> None:
    """Gives each file of the copy the name the plan has for it; each goes by a temporary name first, so names may be swapped."""
    moving = [(track.path, track.new_path, f".agitha-moving-{n}")
              for n, track in enumerate(plan.tracks) if track.new_path != track.path]
    for old, _new, temporary in moving:
        os.rename(folder / old, folder / temporary)
    for old, new, temporary in moving:
        (folder / new).parent.mkdir(parents=True, exist_ok=True)
        os.rename(folder / temporary, folder / new)
        swap.prune((folder / old).parent, folder)


def _violations(folder: Path, root: Path, parent: Path, suffix_given: bool) -> list[check.Violation]:
    siblings = [path.name for path in walk.child_dirs(parent)] if parent.is_dir() else []
    return check.check_album(check.read_album(folder, root), siblings, suffix_given)


def _check_copy(config: Config, plan: AlbumPlan, work: Path, copy: Path) -> None:
    """Fails where the copy breaks a rule of `docs/music-library.md` that the library's album did not.

    The two are not checked alike on purpose: a trailing `[..]` of the
    library's folder is an edition only where a sibling folder bears the
    same name, which is what the disk shows, while the copy's is the plan's
    to say, as it has not been named in the library yet.
    """
    root = library.library_root(config)
    known = Counter(found.rule for found in _violations(root / plan.path, root, (root / plan.path).parent, False))
    for found in _violations(copy, work / "new", root / plan.new_path.rpartition("/")[0], plan.edition):
        if known[found.rule] > 0:
            known[found.rule] -= 1
        else:
            raise Failed(f"{found.rule}: {found.detail}")


def _land(config: Config, jobs: Jobs, entry: JobAlbum, plan: AlbumPlan, work: Path) -> str | None:
    """Writes the album's copy and swaps it in; the sentence of the extras that could not follow it, or `None`."""
    old, new = config.library / plan.path, config.library / plan.new_path
    copy = work / "new" / plan.new_path
    taken = swap.stamps(old)
    shutil.copytree(old, copy, symlinks=True)
    _write(plan, copy)
    if plan.cover_token is not None:
        _lay_cover(config, plan, copy)
    _rename(plan, copy)
    jobs.settle(entry, VERIFYING)
    _check_copy(config, plan, work, copy)

    drops.replace_json(work / LANDING, {"landed": plan.new_path})
    # A player may store a rating in a library file while the copy is made; the swap looks for it once the folder is set aside.
    failure = swap.swap(config.library, work, copy, new, old, swap.Unchanged(taken, RACED))
    if failure is not None:
        raise Failed(failure.sentence, failure.restored)
    return swap.after_landing(config.library, config.extras, plan.path, plan.new_path)


def recover(config: Config) -> None:
    """Puts back the album of every work folder a save left with its library copy set aside, then clears the work folders.

    A work folder with no copy set aside holds only a dead job's copy of an
    album. One that cannot be put back is left, with the reason on stderr.
    """
    base = config.jobs / WORK
    if not base.is_dir():
        return
    for job in sorted(base.iterdir()):
        for work in sorted(job.iterdir()) if job.is_dir() else []:
            if work.is_dir() and (why := _restore(config, work)) is not None:
                print(f"agitha: {work}: {why}", file=sys.stderr)
        swap.prune(job, base)
