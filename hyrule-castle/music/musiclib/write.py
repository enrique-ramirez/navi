"""Writing a plan to disk: the only thing that touches the library.

`write_album` refuses first - a plan `musiclib check` would reject, a live
library foobar2000 is serving, or a collision - before anything is touched,
not even `extras_root` is created. Once past that, an album moves and is
retagged as one unit: every track's move happens before any tag is written,
so a swap or a case-only rename never collides in flight, and any track's
tag write or embed failing puts every track already done back to its prior
tags and path. Files the rules remove are deleted, and videos/disc
images/software go to `extras_root` under the album's own destination path,
only once every track has verified. The record `write_album` returns carries
enough of that history - every track's prior tags, every move, everything
created or deleted - to be reversed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from musiclib import files, images, tagwrite
from musiclib.plan import FilePlan, Plan, relocated


class PlanRefused(Exception):
    """`write_album` never touched the library: `plan.problems` said why."""


class FoobarRunning(Exception):
    """foobar2000 is serving the library `write_album` was asked to change."""


class Collision(Exception):
    """Two of a write's destinations collide, compared case-insensitively."""


class AlbumFailed(Exception):
    """A verified write failed partway through, and the album was rolled back.

    `.record` carries what had actually happened at the point of failure,
    the same shape `write_album` returns on success - useful to a caller that
    logs a failed write, even though the library itself is already back to
    where it started by the time this is raised.
    """

    record: dict


class StalePlan(Exception):
    """A track changed on disk since `plan_album` read it: nothing was touched."""


#: The one instruction every `FoobarRunning` gives, whatever put it in doubt.
_STOP_FOOBAR = "sudo systemctl stop foobar2000 first"


# --- the foobar2000 guard ---------------------------------------------------

def guard_foobar(root: Path, live_root: Path, systemctl: str) -> None:
    """Refuse a write under `live_root` while foobar2000 is serving it.

    A root equal to or nested under the live library is as live as the
    library itself (a Plan whose `root` argument was itself given as a
    subfolder of it). Anything `systemctl` cannot answer - missing, denied,
    any error - is treated the same as "running": the guard would rather
    refuse a safe write than risk one under a foobar2000 it could not check.
    Both paths are resolved first: the deploy links `/srv/fb2k/Musica` to
    `/srv/music/library`, so the same folder has two spellings, and a plan
    rooted at the link must be judged the same as one rooted at the target.
    """
    if not root.resolve().is_relative_to(live_root.resolve()):
        return
    try:
        result = subprocess.run([systemctl, "is-active", "foobar2000"],
                                capture_output=True, text=True)
    except OSError as exc:
        raise FoobarRunning(
            f"could not tell whether foobar2000 is running ({exc}); run {_STOP_FOOBAR}"
        ) from exc
    if result.returncode == 0:
        raise FoobarRunning(f"foobar2000 is running: {_STOP_FOOBAR}")


# --- the collision check ----------------------------------------------------

def _existing_files(root: Path, plan: Plan) -> set[str]:
    """Every file already under the album's source or destination folder.

    Only those two folders can hold anything the write's destinations could
    land on, so this is enough without walking the whole library.
    """
    found: set[str] = set()
    for tree in {plan.source, plan.destination}:
        base = root / tree
        if base.is_dir():
            found.update(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())
    return found


def _final_destinations(plan: Plan) -> list[tuple[str, bool]]:
    """Every path the write creates or overwrites: `(path, is_image)`.

    Extras are left out: they land under `extras_root`, a tree of its own,
    so they can never collide with anything under `root`.
    """
    finals = [(file_plan.destination, False) for file_plan in plan.files]
    finals += [(relocated(plan, kept), False) for kept in plan.kept]
    finals += [(f"{plan.destination}/{name}", True) for name in plan.images]
    return finals


def check_collisions(plan: Plan, root: Path) -> None:
    """Refuse the whole album if two of its destinations collide, Wine's way.

    An image is left out of the "already there" half of this check: it
    replaces whatever already occupies that name (`_write_images`), so a
    case-only difference there is the same slot, not a collision.
    """
    leaving = ({file_plan.source for file_plan in plan.files}
               | set(plan.kept) | set(plan.extras) | set(plan.deletions))
    staying = _existing_files(root, plan) - leaving

    finals = _final_destinations(plan)
    by_fold: dict[str, set[str]] = {}
    for path, _is_image in finals:
        by_fold.setdefault(path.casefold(), set()).add(path)
    for paths in by_fold.values():
        if len(paths) > 1:
            first, second = sorted(paths)[:2]
            raise Collision(f"{first} and {second} collide")

    staying_by_fold = {path.casefold(): path for path in staying}
    for path, is_image in finals:
        if is_image:
            continue
        existing = staying_by_fold.get(path.casefold())
        if existing is not None:
            raise Collision(f"{path} and {existing} collide")


# --- staged moves -----------------------------------------------------------

def _move_all(pairs: list[tuple[Path, Path]]) -> None:
    """Move every `(source, destination)` pair, through a staging name first.

    A straight rename, done one pair at a time, would let an earlier move
    land on a later pair's own source (a swap) or wipe out the file it is
    about to replace (a case-only rename this disk would otherwise treat as
    two different names). Staging every source aside first, then renaming
    every staged file to its destination, makes the whole batch behave as if
    every move happened at once. The staging name is short and owes nothing
    to the original (`.musiclib-write-<n><ext>`, in the same folder as the
    source), so staging itself never pushes an already-long name over the
    filesystem's own limit. `shutil.move` for the final hop, not a plain
    rename, since `extras_root` can sit on another filesystem a rename cannot
    cross.

    Any failure, in either phase, undoes every pair this call already moved
    before re-raising: a batch that cannot finish must never leave a file
    part-way between its source and its destination.
    """
    staged: list[tuple[Path | None, Path, Path]] = []  # (temp, destination, source)
    promoted: list[tuple[Path, Path]] = []  # (now at destination, its original source)
    try:
        for index, (source, destination) in enumerate(pairs):
            if source == destination:
                staged.append((None, destination, source))
                continue
            temp = source.parent / f".musiclib-write-{index}{source.suffix}"
            source.rename(temp)
            staged.append((temp, destination, source))

        for temp, destination, source in staged:
            if temp is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(temp, destination)
            promoted.append((destination, source))
    except OSError:
        for destination, source in promoted:
            shutil.move(destination, source)
        for temp, _destination, source in staged:
            if temp is not None and temp.exists():
                temp.rename(source)
        raise


def undo_moves(pairs: list[tuple[Path, Path]]) -> None:
    """The inverse of `_move_all`: every pair's destination back to its source."""
    _move_all([(destination, source) for source, destination in pairs])


def _remove_empty_tree(base: Path) -> None:
    """`base` and every now-empty directory under it, deepest first."""
    if not base.is_dir():
        return
    for child in sorted(base.iterdir()):
        if child.is_dir():
            _remove_empty_tree(child)
    if not any(base.iterdir()):
        base.rmdir()


def prune_empty(path: Path, root: Path) -> None:
    """`path`'s tree, and every emptied ancestor up to (not including) `root`."""
    _remove_empty_tree(path)
    parent = path.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


# --- images -----------------------------------------------------------------

def _write_images(plan: Plan, root: Path) -> list[str]:
    """Write every planned image, replacing whatever already holds that slot.

    A destination differing only in case from an existing file is the same
    slot (the collision check already let it through on that understanding),
    so that file is removed first rather than left beside the new one. The
    sibling scan runs whether or not `target` itself already "exists": this
    disk answers that case-insensitively too, so a guard of `not
    target.exists()` would skip the scan and let `write_bytes` overwrite
    `Back.JPG` in place under its old name instead of renaming it.
    """
    created = []
    dest_dir = root / plan.destination
    for name, data in plan.images.items():
        target = dest_dir / name
        if dest_dir.is_dir():
            for sibling in dest_dir.iterdir():
                if sibling.is_file() and sibling.name != name and sibling.name.casefold() == name.casefold():
                    sibling.unlink()
                    break
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        created.append(f"{plan.destination}/{name}")
    return created


def _prior_tags(plan: Plan, root: Path) -> dict[str, dict]:
    """Every track's tags, read once, keyed by its planned destination.

    Also where a stale plan is caught: `fingerprint` is the source file's
    tags and audio fingerprint at planning time, and a mismatch here means
    somebody retagged or re-ripped the file since - writing the plan over it
    would silently undo that. `None` is a plan built by hand rather than by
    `plan_album` (`tests.builders.file_plan`), which never had a fingerprint
    to compare against, so that plan is trusted as given. Called before
    anything moves, so a stale file is caught with the album untouched.
    """
    prior: dict[str, dict] = {}
    for file_plan in plan.files:
        current = files.read(root / file_plan.source)
        if file_plan.fingerprint is not None:
            fingerprint = (current.tags, files.audio_fingerprint(current))
            if fingerprint != file_plan.fingerprint:
                raise StalePlan(f"{file_plan.source} changed on disk since it was planned")
        prior[file_plan.destination] = current.tags
    return prior


def rollback_target(current: files.Track, prior: dict) -> dict:
    """`prior`, with every key that cannot be rebuilt swapped for `current`'s own value.

    A picture, an MP3 `PRIV`, `GEOB` or URL frame, or an MP4 or ASF value kept
    as a digest (`tagwrite.is_unrestorable`), cannot be restored from `prior`:
    `files.snapshot` keeps only a digest of it (`files.py`, `snapshot`), never its bytes, so writing `prior` as it stands would
    either crash rebuilding a frame from that digest or, on FLAC/Ogg where
    the digest is comparable text, just fail to verify. An MP3 `USER` frame is
    kept as text but the writer does not rebuild it either. A rollback does
    not owe those back regardless: only every other tag and every path.
    """
    result = {key: value for key, value in prior.items()
             if not tagwrite.is_unrestorable(current.family, key, value)}
    for key, value in current.tags.items():
        if tagwrite.is_unrestorable(current.family, key, value):
            result[key] = value
    return result


def _record(tags: dict, moves: list, created: list, deleted: list) -> dict:
    """The one shape a write's outcome takes, whether it finished or was rolled back partway."""
    return {"tags": tags, "moves": moves, "created": created, "deleted": deleted}


# --- the write itself --------------------------------------------------------

def write_album(
    plan: Plan, extras_root: str | Path,
    live_root: str | Path = Path("/srv/music/library"), systemctl: str = "systemctl",
) -> dict:
    """Write `plan` to disk, or raise having touched nothing.

    A plan `check` would reject is refused before anything is touched - not
    even `extras_root` is created - since `plan.problems` already carries
    every reason: `plan_album` runs the same rules `check` runs on a tree
    already written.
    """
    if plan.problems:
        raise PlanRefused("; ".join(plan.problems))

    root = Path(plan.root)
    live_root = Path(live_root)
    extras_root = Path(extras_root)

    guard_foobar(root, live_root, systemctl)
    check_collisions(plan, root)

    # Read every track's tags before anything moves: this is the record's
    # "prior value", and the only point at which the file is still at its
    # planned source.
    prior_tags = _prior_tags(plan, root)

    track_moves = [(file_plan.source, file_plan.destination) for file_plan in plan.files]
    kept_moves = [(kept, relocated(plan, kept)) for kept in plan.kept]
    library_moves = track_moves + kept_moves
    try:
        _move_all([(root / source, root / destination) for source, destination in library_moves])
    except OSError as exc:
        # A name the filesystem itself refuses (over its own limit, say) is
        # as much a failed write as a tag that would not verify: `_move_all`
        # has already put every file back under its own name by the time
        # this is raised, so nothing was actually done.
        failed = AlbumFailed(f"moving the album failed: {exc}")
        failed.record = _record(tags={}, moves=[], created=[], deleted=[])
        raise failed from exc

    done: list[FilePlan] = []
    try:
        for file_plan in plan.files:
            destination_path = root / file_plan.destination
            current = files.read(destination_path)
            try:
                tagwrite.write(current, file_plan.target)
            except Exception as exc:
                # Every kind of failure here - not just a tag that did not
                # verify - leaves the file untouched or already reverted by
                # `tagwrite.write` itself, so no extra revert is needed for
                # this one file; the files already `done` still need theirs.
                raise AlbumFailed(f"{file_plan.destination}: {exc}") from exc
            if plan.embedded is not None:
                try:
                    images.embed(destination_path, plan.embedded)
                except Exception as exc:
                    # tagwrite.write already verified and left the new tags in
                    # place; embed failed after that, so this file - unlike
                    # one tagwrite itself rejected - is not put back yet.
                    reverted = files.read(destination_path)
                    tagwrite.write(reverted, rollback_target(reverted, current.tags))
                    raise AlbumFailed(f"{file_plan.destination}: {exc}") from exc
            done.append(file_plan)
    except AlbumFailed as failed:
        failed.record = _record(
            tags={file_plan.destination: prior_tags[file_plan.destination] for file_plan in done},
            moves=[[source, destination, "library"] for source, destination in library_moves],
            created=[], deleted=[],
        )
        for file_plan in reversed(done):
            current = files.read(root / file_plan.destination)
            tagwrite.write(current, rollback_target(current, prior_tags[file_plan.destination]))
        undo_moves([(root / source, root / destination) for source, destination in library_moves])
        prune_empty(root / plan.destination, root)
        raise

    created = _write_images(plan, root)

    extra_moves = [(extra, relocated(plan, extra)) for extra in plan.extras]
    _move_all([(root / source, extras_root / destination) for source, destination in extra_moves])

    for deletion in plan.deletions:
        (root / deletion).unlink()

    prune_empty(root / plan.source, root)

    return _record(
        tags=prior_tags,
        moves=([[source, destination, "library"] for source, destination in library_moves]
               + [[source, destination, "extras"] for source, destination in extra_moves]),
        created=created, deleted=list(plan.deletions),
    )
