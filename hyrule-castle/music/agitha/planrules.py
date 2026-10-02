"""The rules of `docs/music-library.md` a plan newly breaks.

The engine's rules (`musiclib.check`) are judged on the album as it is and as
the plan leaves it; a violation counts only where the plan did not already
have it. Agitha's own rule, one number to a disc, is `shared_numbers`.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path
from typing import Callable, Hashable, Iterable, Sequence, TypeVar

from musiclib import check, files, walk

from .albumplan import AlbumPlan, TrackPlan

T = TypeVar("T")

#: Rules whose detail is the file's own name or folder, so a path that moves changes the text and not the rule.
_PATH_RULES = ("file name", "disc folder")


def _added(known: Iterable[Hashable], new: Sequence[T], key: Callable[[T], Hashable]) -> list[T]:
    """The items of `new` whose `key` the `known` keys do not account for, counting each key as many times as it occurs."""
    left = Counter(known)
    added = []
    for item in new:
        if left[key(item)] > 0:
            left[key(item)] -= 1
        else:
            added.append(item)
    return added


def shared_numbers(plan: AlbumPlan) -> list[dict[str, str]]:
    """The tracks the draft gave a number another track of the same disc holds; a pair that already shared one is not named."""
    def place(track: TrackPlan, tags: dict[str, list[str]]) -> tuple[int, int]:
        return track.number("Disc number", tags) or 1, track.number("Track number", tags)

    held = Counter(place(track, track.after) for track in plan.tracks)
    problems = []
    for track in plan.tracks:
        disc, number = place(track, track.after)
        if (disc, number) != place(track, track.before) and number and held[disc, number] > 1:
            problems.append({"rule": "track number",
                             "detail": f"{track.path}: number {number} is held by another track of disc {disc}"})
    return problems


def _same_violation_key(rule: str, detail: str, filename: str, path: str) -> tuple[str, str, str]:
    """What makes two violations of one track the same, whatever the file is called."""
    if rule in _PATH_RULES:
        return path, rule, ""
    return path, rule, detail[len(filename):] if detail.startswith(filename) else detail


def _with_path(detail: str, filename: str, path: str) -> str:
    """`detail` with the track's path where the engine puts its file name, or before it where it puts none."""
    return path + detail[len(filename):] if detail.startswith(filename) else f"{path}: {detail}"


def _target_state(state: check.AlbumState, by_state: dict[int, TrackPlan], new_path: str) -> check.AlbumState:
    """`state` as the plan leaves it: the new tags, the new names and the album under its new path."""
    letter, artist, folder = new_path.split("/")
    tracks = []
    for track in state.tracks:
        plan = by_state[id(track)]
        directory, _, name = plan.new_path.rpartition("/")
        moved = files.Track(path=track.track.path, family=plan.family, tags=plan.after, length=plan.length)
        tracks.append(dataclasses.replace(track, filename=name, disc_dir=directory.partition("/")[0] or None,
                                          track=moved))
    return dataclasses.replace(state, album=Path(new_path), letter=letter, artist=artist, folder=folder,
                               tracks=tuple(tracks))


def engine_rules(root: Path, folder: Path, state: check.AlbumState, plan: AlbumPlan) -> list[dict[str, str]]:
    """The engine's rules `plan` breaks and `state`, the album as it is, did not; each track's is told with its path.

    A track's violations are matched by track, rule and detail with the file
    name left out, so a rename does not make an old one new; the album's own
    are matched by rule. Nothing is judged where the engine's reader and the
    library's disagree on which files are tracks.
    """
    by_state = {id(track.state): track for track in plan.tracks if track.state is not None}
    if len(by_state) != len(state.tracks):
        return []
    after = _target_state(state, by_state, plan.new_path)
    parent = root / plan.new_path.rpartition("/")[0]
    siblings_before = [path.name for path in walk.child_dirs(folder.parent)]
    siblings_after = [path.name for path in walk.child_dirs(parent)] if parent.is_dir() else []
    counts_before, counts_after = check.disc_track_counts(state), check.disc_track_counts(after)

    problems = []
    for was, now in zip(state.tracks, after.tracks):
        track = by_state[id(was)]
        known = (_same_violation_key(rule, detail, was.filename, track.path)
                 for rule, detail in check.track_violations(was, counts_before))
        for rule, detail in _added(known, check.track_violations(now, counts_after),
                                   key=lambda found: _same_violation_key(*found, now.filename, track.path)):
            problems.append({"rule": rule, "detail": _with_path(detail, now.filename, track.path)})
    old_album = check.album_violations(state, siblings_before)
    new_album = check.album_violations(after, siblings_after, plan.edition)
    problems.extend({"rule": found.rule, "detail": found.detail}
                    for found in _added((found.rule for found in old_album), new_album, key=lambda found: found.rule))
    return problems
