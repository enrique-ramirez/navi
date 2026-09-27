"""`musiclib batch rollback --job DIR`: undo a job's applied writes.

`applied.jsonl` is undone newest line first - two albums can share a folder
across a job (one moves out, the next moves in under the same names), so
putting the later one back before the earlier one would land it on the
earlier album's own files. A `failed` line is left alone: `write_album`
already put that album back itself before raising. A line already undone by
an earlier rollback (it has a later `rolled back` line for the same source)
is skipped too, so running rollback twice is harmless.

What rollback cannot give back is listed rather than silently dropped: a
`cover.jpg` `write_album` wrote or replaced (`created`), a file it deleted
(`deleted`), and every track's embedded picture. A picture is never
restored - `files.read` keeps only a digest of one, never its bytes
(`write._rollback_target`) - and FLAC does not even keep that digest in the
tags this module can compare (`tagwrite.is_picture_key`'s own docstring), so
every track write_album touched is listed for its picture regardless of
whether the picture actually changed: rollback has no way to tell, for every
format, that it did not.

An album's library moves always go through `write._undo_moves` as one batch,
the same as `write_album` itself moves a whole album at once: that is what
lets a chain of renames or a swap between two tracks undo correctly, since a
move partway through either one can leave a track's own old name occupied by
another track without the album being any less mid-rollback. Once that batch
has gone through, every track is at its source path, and a `moves undone`
line is appended before any tag is touched - so a rollback that then fails
on a track's tags (a read-only file, say) can be run again without replaying
the moves: it sees the `moves undone` line, skips straight to the tags, and
reads each track at its source path, since the moves are already known done.

Extras are undone one at a time, after that batch, never inside it: a video
somebody deleted from the extras folder between apply and rollback must not
sit in the same all-or-nothing batch as the tracks, or its one missing file
would put every track back where apply left them and the album could never
be rolled back at all. Its own failure is listed and the album carries on.
An extra already back - this run's own doing, or an earlier run's - is left
alone rather than retried.
"""

from __future__ import annotations

import sys
from pathlib import Path

from musiclib import files, tagwrite
from musiclib.batch import job as job_module
from musiclib.batch.job import Job
from musiclib.write import FoobarRunning, _guard_foobar, _prune_empty, _rollback_target, _undo_moves


def _cannot_restore(out, not_restored: list[str], path: str, reason: str) -> None:
    """Record that `path` could not be put back, and say why on `out`."""
    print(f"{path}: {reason}", file=out)
    not_restored.append(path)


def _library_pairs(moves: list, root: Path) -> list[tuple[Path, Path]]:
    """An album's library moves only, in the same (source, destination) sense `write_album` made them."""
    return [(root / source, root / destination) for source, destination, kind in moves if kind == "library"]


def _undo_extras(moves: list, root: Path, extras_root: Path, out, not_restored: list[str]) -> None:
    """Every extra, one at a time: a missing one is listed rather than failing the whole album.

    Undone on its own rather than batched with the library moves
    (`_library_pairs`), so one extra somebody deleted from the extras folder
    never blocks the tracks or the tags behind it. Skipped once it is already
    back at its source, so a retry does not ask `_undo_moves` to move a
    destination an earlier attempt already emptied.
    """
    for source, destination, kind in moves:
        if kind != "extras":
            continue
        from_path = root / source
        if from_path.exists():
            continue
        try:
            _undo_moves([(from_path, extras_root / destination)])
        except OSError as exc:
            _cannot_restore(out, not_restored, destination, f"could not move back from extras ({exc})")


def _write_tags(record: dict, root: Path, out, not_restored: list[str]) -> None:
    """Every track's tags, read at its source path - the moves are already known undone by here."""
    tags = record["tags"]
    for source, destination, kind in record["moves"]:
        if kind != "library" or destination not in tags:
            continue
        current = files.read(root / source)
        tagwrite.write(current, _rollback_target(current, tags[destination]))
        _cannot_restore(out, not_restored, destination, "embedded picture not restored")

    for path in record["created"]:
        _cannot_restore(out, not_restored, path, "written by apply; left in place")
    for path in record["deleted"]:
        _cannot_restore(out, not_restored, path, "deleted by apply; not restored")


def _undo_album(entry: dict, root: Path, extras_root: Path, moves_done: bool,
                out, not_restored: list[str], job: Job) -> None:
    """Undo one `applied` line: its moves (unless a `moves undone` line says that already happened),
    then its extras, then its tags.
    """
    record = entry["record"]
    if not moves_done:
        _undo_moves(_library_pairs(record["moves"], root))
        job_module.append_log(job, {"source": entry["source"], "destination": entry["destination"],
                                    "outcome": "moves undone", "error": None, "record": None})

    _undo_extras(record["moves"], root, extras_root, out, not_restored)

    _write_tags(record, root, out, not_restored)

    _prune_empty(root / entry["destination"], root)
    _prune_empty(extras_root / entry["destination"], extras_root)


def run(job: Job, *, extras_root: Path = Path("/srv/music/extras"),
       live_root: Path = Path("/srv/music/library"), systemctl: str = "systemctl",
       out=None, err=None) -> int:
    # `sys.stdout`/`sys.stderr` resolved here, not as the default value: a
    # default is bound once at import time, before a caller's redirect (a
    # test capturing output, or a later reassignment of `sys.stdout`) exists.
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    plan_doc = job_module.read_json(job.plan)
    root = Path(plan_doc["root"])
    extras_root = Path(extras_root)
    live_root = Path(live_root)

    try:
        _guard_foobar(root, live_root, systemctl)
    except FoobarRunning as exc:
        print(str(exc), file=err)
        return 1

    lines = job_module.read_log(job)
    rolled_back = {line["source"] for line in lines if line["outcome"] == "rolled back"}
    moves_done = {line["source"] for line in lines if line["outcome"] == "moves undone"}

    not_restored: list[str] = []
    for line in reversed(lines):
        if line["outcome"] != "applied" or line["source"] in rolled_back:
            continue
        try:
            _undo_album(line, root, extras_root, line["source"] in moves_done, out, not_restored, job)
        except Exception as exc:
            # Left for a later rollback to retry: no `rolled back` line for
            # this source, so it is undone again next time rather than
            # treated as done while it is really half-undone.
            print(f"{line['source']}: {exc}", file=err)
            not_restored.append(line["source"])
            continue
        job_module.append_log(job, {"source": line["source"], "destination": line["destination"],
                                    "outcome": "rolled back", "error": None, "record": None})

    return 1 if not_restored else 0
