"""The owner's standing choices, carried from one job into the next.

An applied field edit and a Soundtrack-type album's `video game music` /
`not game music` choice both outlive the job that made them, so a re-run or
a later import gets the same answer without asking again.

001's `plan_album` takes no field edits, so this module also carries the
*Edits* mechanism: laying a position's edited neutral fields over an
already-built `Plan`, re-deriving the destination when an edited field is
one the destination is built from, and validating the result again with
`check.check_album` - the same rules `plan_album` itself is judged by.
`musiclib.batch.identify` calls `lay_edits` from both `plan_entry` (the
owner's page) and `rebuild` (apply's warm-cache replay), with exactly the
same `edits` dict either way, so the two give the same `Plan.to_json()`.
"""

from __future__ import annotations

from pathlib import Path

from musiclib import ascii as ascii_
from musiclib import check, mapping, names
from musiclib.batch import job as job_module
from musiclib.plan import Plan, _is_compilation, _sort_others, state_from_plan
from musiclib.units import Unit

#: The two choices the page offers for a Soundtrack-type or `video game
#: music` album.
VIDEO_GAME_MUSIC = "video game music"
NOT_GAME_MUSIC = "not game music"

#: Edited fields the destination is built from: a track's own title only
#: moves that track's file, the rest move the album.
_PATH_FIELDS = {"title", "album", "albumartist", "albumartistsort", "date"}


def load(path: Path) -> dict:
    """`memory.json` at `path`, or the empty shape for a file that does not exist yet."""
    if not Path(path).is_file():
        return {"edits": {}, "composers": {}, "reopened": []}
    doc = job_module.read_json(path)
    return {
        "edits": dict(doc.get("edits") or {}),
        "composers": dict(doc.get("composers") or {}),
        "reopened": list(doc.get("reopened") or []),
    }


def save(path: Path, memory: dict) -> None:
    job_module.write_json(path, memory)


def merge_edits(*sources: dict) -> dict:
    """Every `source`'s per-position field edits, later sources winning field for field."""
    combined: dict[str, dict[str, list[str]]] = {}
    for source in sources:
        for position, fields in (source or {}).items():
            combined.setdefault(position, {}).update(fields)
    return combined


def video_game_genre_edit(plan: Plan, positions: list[str], family_by_source: dict[str, str]) -> dict:
    """The synthetic `genre` edit for a no-composer album's `video game music` choice.

    Every position gets the same edit: `video game music` takes the first
    (custom-genre) slot in place of whatever the engine planned there, the
    rest of the list kept, because the genre list is one album-wide value,
    not one per track (`plan._album_genres`).
    """
    if not plan.files:
        return {}
    first = plan.files[0]
    family = family_by_source.get(first.source)
    key = mapping.PICARD["genre"].get(family) if family else None
    current = list(first.target.get(key, [])) if key else []
    new_genres = [VIDEO_GAME_MUSIC] + current[1:] if current else [VIDEO_GAME_MUSIC]
    return {position: {"genre": list(new_genres)} for position in positions}


def _dedupe(items) -> list:
    seen: set = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _check_problems(plan: Plan) -> list[str]:
    return [f"{v.rule}: {v.detail}" for v in check.check_album(state_from_plan(plan))]


def _value(target: dict, field: str, family: str) -> str | None:
    key = mapping.PICARD[field].get(family)
    if not key:
        return None
    values = target.get(key)
    return values[0] if values else None


def _rederive_destination(plan: Plan, release: dict, release_group: dict, positions: list[str],
                          family_by_source: dict[str, str], touched: set[str]) -> None:
    """Recompute `plan.destination` and every file's destination the way `plan_album` does.

    Read back off the (already edited) targets rather than off `release`,
    so an edit and the engine's own value are named the same way; only the
    artist folder falls back to `release` at all, and only when an edit
    actually touched the fields it is built from.
    """
    first = plan.files[0]
    family0 = family_by_source[first.source]

    old_letter, old_artist_folder, _old_album_folder = (plan.destination.split("/", 2) + ["", ""])[:3]

    if touched & {"albumartist", "albumartistsort"}:
        name = _value(first.target, "albumartist", family0) or ""
        sort_name = _value(first.target, "albumartistsort", family0)
        compilation = _is_compilation(release)
        artist_folder = names.artist_folder(name, sort_name, known=True, compilation=compilation)
        letter = names.letter(artist_folder)
    else:
        artist_folder, letter = old_artist_folder, old_letter

    album_title = _value(first.target, "album", family0) or ""
    album_date = _value(first.target, "date", family0) or ""
    album_folder = names.album_folder(
        album_date, album_title, release_group.get("primary-type"),
        tuple(release_group.get("secondary-types", [])),
    )
    destination = f"{letter}/{artist_folder}/{album_folder}"
    plan.destination = destination

    medium_tracks: dict[int, list[int]] = {}
    for position in positions:
        medium_str, track_str = position.split("-")
        medium_tracks.setdefault(int(medium_str), []).append(int(track_str))
    medium_count = len(medium_tracks)

    for file_plan, position in zip(plan.files, positions):
        medium_str, track_str = position.split("-")
        medium_index, track_index = int(medium_str), int(track_str)
        family = family_by_source[file_plan.source]
        title = _value(file_plan.target, "title", family) or ""
        ext = Path(file_plan.destination).suffix.lstrip(".")
        tracks_on_medium = len(medium_tracks[medium_index])
        filename = names.track_filename(track_index, title, ext, tracks_on_medium)
        disc_dir = names.disc_folder(medium_index, medium_count)
        file_plan.destination = f"{destination}/{disc_dir}/{filename}" if disc_dir else f"{destination}/{filename}"


def lay_edits(plan: Plan, edits: dict, release: dict, release_group: dict, positions: list[str],
             family_by_source: dict[str, str], unit: Unit) -> Plan:
    """`plan`, with `edits` laid over it, mutated and returned.

    Each edited neutral field replaces the real key `mapping.PICARD` maps it
    to, run through `ascii.convert` the way `mapping.plan_tags` does. A field
    the destination is built from re-derives it, and the whole plan is
    validated again: an edit laid without that re-derivation gives a plan
    `check` refuses, because a filename or album folder would then disagree
    with the tag it is supposed to follow.

    A destination that moves also re-sorts `unit`'s other files exactly as
    `plan_album` does: whether the existing cover.jpg is a deletion or a file
    left in place depends on whether the album is moving, and an edit can
    flip that after the fact. Left alone, a title edit that moves an
    already up-to-date album away from its own folder would leave that
    folder's cover behind, and one that moves it back would delete a cover
    nothing is replacing.
    """
    if not edits:
        return plan

    before_check = set(_check_problems(plan))
    kept_problems = [p for p in plan.problems if p not in before_check]

    by_position = dict(zip(positions, plan.files))
    touched: set[str] = set()
    for position, fields in edits.items():
        file_plan = by_position.get(position)
        if file_plan is None:
            continue
        family = family_by_source[file_plan.source]
        converted = ascii_.convert(fields)
        target = dict(file_plan.target)
        for field, values in converted.items():
            key = mapping.PICARD[field][family]
            target[key] = list(values)
            if field in _PATH_FIELDS:
                touched.add(field)
        file_plan.target = target

    if touched:
        _rederive_destination(plan, release, release_group, positions, family_by_source, touched)
        image_names = {"cover.jpg"} | {name.casefold() for name in plan.images}
        plan.deletions, plan.extras, plan.kept = _sort_others(
            unit, image_names, moving=(plan.source != plan.destination))

    plan.problems = _dedupe(kept_problems + _check_problems(plan))
    return plan


def remember(memory: dict, entry: dict) -> None:
    """Fold one just-applied album's edits and genre choice into `memory`, in place.

    Read from the job's own `entry` - `inputs.edits`, `composer`,
    `game_choice` - never from the owner's raw decision: identify already
    folded the decision in, and `entry` is what it planned and the page
    showed.
    """
    inputs = entry.get("inputs") or {}
    release_id = entry.get("release_id")
    edits = inputs.get("edits") or {}
    if release_id and edits:
        memory.setdefault("edits", {})[release_id] = edits

    # `composer` is only set for a single album-artist credit: a Various
    # Artists or multi-artist album leaves it `None`, keeping it out of the
    # composer memory even if `owner_input` carries an unrelated value for
    # the same id.
    composer = entry.get("composer")
    if entry.get("game_choice") and composer:
        choice = (inputs.get("owner_input") or {}).get("composers", {}).get(composer)
        if choice is not None:
            memory.setdefault("composers", {})[composer] = choice
