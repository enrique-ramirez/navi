"""`musiclib batch identify`: every album under ROOT planned through the 001 engine into one job.

`run` walks every album unit once, plans it against the memory's standing
choices, and writes `plan.json` and `review.html` only once every album has
been tried: a run interrupted partway leaves neither file touched, and the
next run does the whole walk again against the same warm cache, so it makes
no MusicBrainz, AcoustID or Cover Art Archive request the first run already
made.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

from musiclib import acoustid, identify as identify_engine, mapping
from musiclib.batch import decisions as decisions_module
from musiclib.batch import job as job_module
from musiclib.batch import memory as memory_module
from musiclib.batch import review
from musiclib.batch.job import Job
from musiclib.cache import Cache
from musiclib.caa import CoverArt
from musiclib.mb import MusicBrainz
from musiclib.plan import Plan, changes as plan_changes, edition_fields, plan_album
from musiclib.units import TrackPair, Unit, pair, position_key, units as list_units
from musiclib.write import Collision, check_collisions

#: The identification statuses `plan_entry` may build a plan for, at all: any
#: other status (`unidentified`, `needs a person`) means there is no release
#: to plan against, so the entry carries only the status and no plan.
_PLANNABLE = ("certain", "auto", "review")


@dataclass
class Clients:
    """The three engine clients a job's cache is warmed through, built once per run."""

    mb: MusicBrainz
    caa: CoverArt
    acoustid: acoustid.AcoustID | None


def clients(job: Job, *, transport=None, env: Mapping[str, str] = os.environ,
            which: Callable[[str], str | None] = shutil.which) -> Clients:
    """The job's three clients, sharing one `Cache` under `job.cache`.

    `MusicBrainz` and `AcoustID` get their default clock and sleep, so a
    real run keeps to one request a second.
    """
    cache = Cache(job.cache)
    mb_client = MusicBrainz(cache, transport=transport)
    caa_client = CoverArt(cache, transport=transport)
    acoustid_client = None
    if acoustid.unavailable(env, which) is None:
        acoustid_client = acoustid.AcoustID(cache, env.get("ACOUSTID_API_KEY", ""), transport=transport)
    return Clients(mb=mb_client, caa=caa_client, acoustid=acoustid_client)


# --- one album, judged on its own --------------------------------------------


def _status_detail(status: str, reason: str | None) -> str:
    """The `status`-kind hold detail: the status, then `": " + reason` where the engine gave one."""
    return status if reason is None else f"{status}: {reason}"


def _candidate_dict(candidate) -> dict:
    release = candidate.release
    if release is None:
        title = artist = date = country = fmt = None
        track_counts: list = []
    else:
        credit = release.get("artist-credit") or []
        title = release.get("title")
        artist = mapping.join_credit(credit, "name") if credit else None
        date = release.get("date")
        country = release.get("country")
        media = release.get("media", [])
        fmt = media[0].get("format") if media else None
        track_counts = [medium.get("track-count") for medium in media]
    return {
        "release_id": candidate.release_id, "title": title, "artist": artist, "date": date,
        "country": country, "format": fmt, "track_counts": track_counts,
        "matches_counts": candidate.matches_counts, "duration_diff": candidate.duration_diff,
        "thumbnail": f"https://coverartarchive.org/release/{candidate.release_id}/front-250",
    }


def _files(plan: Plan, positions: list[str]) -> list[dict]:
    out = []
    for file_plan, position in zip(plan.files, positions):
        before = dict(file_plan.fingerprint[0]) if file_plan.fingerprint else {}
        out.append({
            "source": file_plan.source, "destination": file_plan.destination, "position": position,
            "before": before, "after": dict(file_plan.target),
        })
    return out


def _fields(plan: Plan, positions: list[str], family_by_source: dict[str, str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for file_plan, position in zip(plan.files, positions):
        family = family_by_source.get(file_plan.source)
        neutral: dict[str, list[str]] = {}
        for name, keys in mapping.PICARD.items():
            if name in decisions_module.ID_FIELDS:
                continue
            key = keys.get(family)
            if key and key in file_plan.target:
                neutral[name] = list(file_plan.target[key])
        out[position] = neutral
    return out


def _residue(plan: Plan) -> list[dict]:
    return [{"file": file_plan.source, "key": removal.key, "value": removal.value, "rule": removal.rule}
           for file_plan in plan.files for removal in file_plan.removals]


def _image_digest(data: bytes) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(), "length": len(data)}


def _blank_entry(source: str, status: str) -> dict:
    """The fields every entry has, before anything a plan or a hold adds."""
    return {
        "source": source, "status": status, "holds": [], "decision": None, "release_id": None,
        "destination": None, "game_choice": False, "candidates": [], "files": [],
        "fields": {}, "images": {}, "residue": [], "deletions": [], "extras": [], "kept": [], "changes": [],
        "inputs": None, "plan_digest": None, "game": None, "owner_edits": {},
    }


def _entry_pairs(unit: Unit, root: Path, release: dict, plan: Plan) -> tuple[list[TrackPair], dict[str, str]]:
    """The pairs `plan_album` planned `plan.files` from, in the same order, and each file's tag family."""
    family_by_source = {Path(t.path).relative_to(root).as_posix(): t.family for t in unit.tracks}
    return (pair(unit, release) or [])[:len(plan.files)], family_by_source


def plan_entry(unit: Unit, root: Path, clients: Clients, memory: dict, decision: dict | None,
               reopened: bool, *, edition: str | None = None, env: Mapping[str, str] = os.environ,
               which: Callable[[str], str | None] = shutil.which) -> tuple[dict, Plan | None]:
    """One album's entry, and its `Plan` if it has one. Collision holds and `state` are not this function's to add.

    `decision` folds the owner's `decisions.json` answer for this album in:
    `repoint` and an `accept` of a release the engine did not put on top are
    both planned via `identify.chosen`, a `game` choice is folded into
    `owner_input` by release before the engine decides anything, and every
    edit - the memory's and the decision's - is laid over the plan before this entry is built from it.
    """
    action = decision.get("action") if decision else None
    owner_input = {"soundtracks": dict(memory.get("soundtracks") or {}), "edits": dict(memory.get("edits") or {})}
    if action == "accept":
        # The accepted release's own edit is on the files it will write, so
        # the engine must not read it as a disagreement with MusicBrainz.
        accepted = decision["release_id"]
        owner_input["edits"][accepted] = memory_module.merge_edits(
            owner_input["edits"].get(accepted, {}), decision.get("edits", {}))

    game = memory_module.current_choice(decision.get("game")) if action == "accept" else None
    if game is not None:
        # The owner's choice is read like a remembered one, so this job, the
        # apply that replays it and the next job all see the same thing.
        owner_input["soundtracks"][decision["release_id"]] = game

    forced_choice = False
    if action == "repoint":
        identification = identify_engine.chosen(unit, clients.mb, decision["release"], owner_input, None)
        forced_choice = True
    else:
        identification = identify_engine.identify(
            unit, clients.mb, clients.acoustid, owner_input=owner_input, incoming=None, env=env, which=which,
        )
        if action == "accept":
            normal_top = identification.candidates[0] if identification.candidates else None
            if normal_top is None or normal_top.release_id != decision["release_id"]:
                identification = identify_engine.chosen(unit, clients.mb, decision["release_id"], owner_input, None)
                forced_choice = True

    entry = _blank_entry(unit.rel, identification.status)
    entry["decision"] = action
    # The decision's own game choice, kept on the entry however the album
    # ends up (even with no plan at all): apply and a later fold both read
    # this off the entry, never back off the raw decision.
    entry["game"] = game
    if identification.status not in ("certain", "auto"):
        entry["holds"].append({"kind": "status", "detail": _status_detail(
            identification.status, identification.reason)})

    top = identification.candidates[0] if identification.candidates else None
    entry["candidates"] = [_candidate_dict(c) for c in identification.candidates]

    plan: Plan | None = None
    if identification.status in _PLANNABLE and top is not None and top.release is not None:
        release = top.release
        plan = plan_album(unit, release, clients.mb, clients.caa, owner_input=owner_input,
                          incoming=None, status=identification.status, pairs=top.pairs, edition=edition)

        pairs, family_by_source = _entry_pairs(unit, root, release, plan)
        positions = [position_key(p) for p in pairs]
        release_group = clients.mb.release_group(release["release-group"]["id"])
        memory_edits = (memory.get("edits") or {}).get(top.release_id, {})
        decision_edits = decision.get("edits", {}) if action == "accept" else {}
        edits = memory_module.merge_edits(memory_edits, decision_edits)

        if edits:
            plan = memory_module.lay_edits(plan, edits, release, release_group, pairs, family_by_source, unit,
                                           edition)

        for problem in plan.problems:
            entry["holds"].append({"kind": "validation", "detail": problem})
        for hold_text in plan.holds:
            entry["holds"].append({"kind": "validation", "detail": hold_text})
        if action == "accept" and plan.problems:
            # Kept so the page still shows why, even though the owner
            # already said yes.
            entry["holds"].append({"kind": "decision", "detail": ""})

        choice = owner_input["soundtracks"].get(top.release_id)
        entry["release_id"] = top.release_id
        entry["destination"] = plan.destination
        # Offered whatever else holds the album, while it waits on the choice
        # and once the owner has made it, so a re-export carries it forward.
        entry["game_choice"] = game is not None or identify_engine.awaits_soundtrack_choice(
            release_group, release, unit, owner_input, None)
        entry["files"] = _files(plan, positions)
        entry["fields"] = _fields(plan, positions, family_by_source)
        entry["images"] = {name: _image_digest(data) for name, data in sorted(plan.images.items())}
        entry["residue"] = _residue(plan)
        entry["deletions"] = list(plan.deletions)
        entry["extras"] = list(plan.extras)
        entry["kept"] = list(plan.kept)
        entry["changes"] = plan_changes(plan)
        entry["owner_edits"] = edits
        entry["inputs"] = {
            "release_id": top.release_id, "chosen": forced_choice, "status": identification.status,
            "owner_input": {"soundtracks": {top.release_id: choice} if choice else {}}, "edits": edits,
        }
        if edition is not None:
            entry["inputs"]["edition"] = edition
        entry["plan_digest"] = hashlib.sha256(plan.to_json()).hexdigest()

        if action == "repoint":
            # Held for the paste itself, however well it fits; a `status`
            # hold alongside is fine, `chosen` never returns `certain`/`auto`.
            entry["holds"].append({"kind": "repointed", "detail": top.release_id})

    if reopened:
        entry["holds"].append({"kind": "reopened", "detail": ""})

    return entry, plan


def rebuild(unit: Unit, root: Path, clients: Clients, inputs: dict) -> Plan:
    """The `Plan` an entry's `inputs` describes, rebuilt from the warm cache for `batch apply`.

    `inputs["status"]` is the status `plan_entry` passed to `plan_album`;
    without it `Plan.to_json()` would not match `plan_digest` (`Plan.status`
    is part of it), so `apply` could never tell a still-good plan from a
    stale one. `inputs["edits"]` is laid exactly the way `plan_entry` laid
    it - the same `edits` dict, the same pairs and families - so the two
    give the same digest.
    """
    release = clients.mb.release(inputs["release_id"])
    plan = plan_album(unit, release, clients.mb, clients.caa, owner_input=inputs["owner_input"],
                      status=inputs["status"], edition=inputs.get("edition"))
    edits = inputs.get("edits") or {}
    if edits:
        pairs, family_by_source = _entry_pairs(unit, root, release, plan)
        release_group = clients.mb.release_group(release["release-group"]["id"])
        plan = memory_module.lay_edits(plan, edits, release, release_group, pairs, family_by_source, unit,
                                       inputs.get("edition"))
    return plan


# --- every album together: collisions and state ------------------------------


def _edition_field_index(fields: list[list[str]]) -> int | None:
    """The index of the first field every album has and no two share, compared casefolded, or `None`."""
    for index in range(len(fields[0])):
        values = [album[index].casefold() for album in fields]
        if all(values) and len(set(values)) == len(values):
            return index
    return None


def _sharing_a_destination(plans: dict[str, Plan]) -> list[list[str]]:
    """Each set of two or more album keys whose destinations match casefolded, the keys sorted."""
    by_destination: dict[str, list[str]] = {}
    for key, plan in plans.items():
        by_destination.setdefault(plan.destination.casefold(), []).append(key)
    return [sorted(keys) for keys in by_destination.values() if len(keys) > 1]


def _separate_editions(entries: list[dict], plans: dict[str, Plan], fields_of: Callable[[dict], list[str]],
                       replan: Callable[[str, str], tuple], err) -> None:
    """Give each album of a set that would share one album folder a suffix from its own release.

    The first of the disambiguation comment, the country and the format that
    every album in the set has and that differs between all of them; no such
    field leaves the set as it is, and `_finalize` holds it for the
    collision. `fields_of(entry)` gives the release's fields, in the order
    `plan.edition_fields` does, and `replan(key, edition)` plans the album
    again with the suffix on, so its changes, digest and inputs carry the
    folder it will be written to.

    A set is suffixed whole or not at all: every album is planned again
    before any entry is swapped, and a set that raises is reported on `err`
    and left as it was, for the others to go on.
    """
    by_source = {entry["source"]: entry for entry in entries}
    for keys in _sharing_a_destination(plans):
        try:
            fields = [fields_of(by_source[key]) for key in keys]
            index = _edition_field_index(fields)
            if index is None:
                continue
            replanned = [replan(key, values[index]) for key, values in zip(keys, fields)]
        except Exception as exc:
            print(f"identify: editions of {', '.join(keys)} not separated: {type(exc).__name__}: {exc}",
                  file=err)
            continue
        position = {entry["source"]: n for n, entry in enumerate(entries)}
        for key, (entry, plan) in zip(keys, replanned):
            entries[position[key]] = entry
            plans[key] = plan


def _add_collision(entry: dict, detail: str) -> None:
    entry["holds"].append({"kind": "collision", "detail": detail})
    if entry["decision"] == "accept" and not any(h["kind"] == "decision" for h in entry["holds"]):
        # An accept no single album could know would fail until every
        # album's destination was known.
        entry["holds"].append({"kind": "decision", "detail": ""})


def _finalize(entries: list[dict], plans: dict[str, Plan], root: Path) -> None:
    """Add every `collision` hold (the one thing no single album can see for itself) and decide `state`."""
    by_source = {entry["source"]: entry for entry in entries}

    for keys in _sharing_a_destination(plans):
        for key in keys:
            others = ", ".join(sorted(other for other in keys if other != key))
            _add_collision(by_source[key], f"same destination as {others}")

    for key, plan in plans.items():
        try:
            check_collisions(plan, root)
        except Collision as exc:
            _add_collision(by_source[key], str(exc))
        except Exception as exc:
            # A name the filesystem itself refuses (an artist folder over
            # 255 bytes raised `OSError` from `Path.is_dir` on the box's
            # Python 3.13) rather than a collision the check found: held
            # like any other engine crash, but every other album still gets
            # its own check.
            by_source[key]["holds"].append(
                {"kind": "error", "detail": f"{type(exc).__name__}: {exc}"})

    for entry in entries:
        # Every condition that would hold an album for review (a non-
        # `certain`/`auto` status, a validation problem, a collision, a
        # reopened album) already added its own hold above, so an entry with
        # no holds at all needs none.
        entry["state"] = "held" if entry["holds"] else ("auto" if entry["changes"] else "unchanged")


def _error_entry(unit: Unit, exc: Exception, decision: dict | None) -> dict:
    """An album the engine crashed on: no plan, held, and the crash named.

    `decision` is the one identify was folding in when the engine raised (a
    pasted or accepted release MusicBrainz 404s for, say). Its `action` and
    `game` are kept on the entry anyway: without them an owner's `accept`
    would look like no decision at all, and `batch apply` would never report
    the album it said yes to but could not write.
    """
    entry = _blank_entry(unit.rel, "error")
    entry["holds"].append({"kind": "error", "detail": f"{type(exc).__name__}: {exc}"})
    if decision:
        action = decision.get("action")
        entry["decision"] = action
        entry["game"] = decision.get("game") if action == "accept" else None
    return entry


class ReopenNotFound(Exception):
    """`--reopen PATH` names something that is not an album unit under `ROOT`."""


def _reopen_key(root: Path, raw: str) -> str | None:
    """The album key `--reopen PATH` names: `PATH` absolute or relative to `ROOT` either way.

    `None` for an absolute path that does not resolve under `ROOT` at all -
    the caller still has to check the result against the job's actual album
    units, since a relative path that names no album is the same argument
    error and this function alone cannot see that.
    """
    given = Path(raw)
    if given.is_absolute():
        try:
            return given.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
    return PurePosixPath(raw).as_posix()


def _reopen_keys(root: Path, reopen: list[str]) -> list[str]:
    """Every `--reopen` argument, resolved to its album key and checked against `ROOT`'s actual units.

    Raises `ReopenNotFound` naming the first bad argument: a path outside
    `ROOT`, or one that is under it but names no album unit at all, is an
    argument error, not a crash and not a silently-ignored hold.
    """
    if not reopen:
        return []
    unit_rels = {unit.rel for unit in list_units(root)}
    keys = []
    for raw in reopen:
        key = _reopen_key(root, raw)
        if key is None or key not in unit_rels:
            raise ReopenNotFound(raw)
        keys.append(key)
    return keys


def _print_counts(entries: list[dict], out) -> None:
    """`status <status>: N`, then `state <state>: N`, then `hold <kind>: N`, each sorted, zero counts left out."""
    status_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    hold_counts: dict[str, int] = {}
    for entry in entries:
        status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1
        state_counts[entry["state"]] = state_counts.get(entry["state"], 0) + 1
        for kind in sorted({hold["kind"] for hold in entry["holds"]}):
            hold_counts[kind] = hold_counts.get(kind, 0) + 1
    for label, counts in (("status", status_counts), ("state", state_counts), ("hold", hold_counts)):
        for name, count in sorted(counts.items()):
            print(f"{label} {name}: {count}", file=out)


def run(root: Path, job: Job, memory_path: Path, reopen: list[str] = (), *, transport=None,
        env: Mapping[str, str] = os.environ, which: Callable[[str], str | None] = shutil.which,
        out=None, err=None) -> int:
    # `sys.stdout`/`sys.stderr` resolved here, not as the default value: a
    # default is bound once at import time, before a caller's redirect (a
    # test capturing output, or a later reassignment of `sys.stdout`) exists.
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    root = Path(root)

    try:
        reopen_keys = _reopen_keys(root, list(reopen))
    except ReopenNotFound as exc:
        # Checked before anything else is written - no job directory, no
        # plan, no memory.
        print(f"--reopen {exc}: not an album under {root}", file=err)
        return 2

    job.path.mkdir(parents=True, exist_ok=True)

    try:
        decisions_doc = decisions_module.read(job)
    except decisions_module.DecisionsRejected as exc:
        # Refused whole, before the cache is even opened: no plan.json, no
        # review.html, no cache directory, no memory.
        print(str(exc), file=err)
        return 1
    decisions_by_album = (decisions_doc or {}).get("albums", {})
    decisions_sha256 = decisions_module.decisions_sha256(job)

    memory = memory_module.load(memory_path)
    # Not saved yet: the reopen list is only worth persisting once every
    # decision in `decisions.json` has been placed on an album this job
    # actually has - a decision nobody can place must leave `memory.json`
    # untouched too, the same as `plan.json` and `review.html` below.
    reopened_keys = set(memory.get("reopened", [])) | set(reopen_keys)

    units = list_units(root)
    unit_rels = {unit.rel for unit in units}
    applied = decisions_module.applied_map(job)
    resolved_decisions = {decisions_module.follow_moves(key, applied): (key, decision)
                          for key, decision in decisions_by_album.items()}
    unplaced = sorted(original_key for resolved_key, (original_key, _decision) in resolved_decisions.items()
                      if resolved_key not in unit_rels)
    if unplaced:
        for key in unplaced:
            print(f"{key}: decisions.json names an album this job cannot find", file=err)
        return 1

    built_clients = clients(job, transport=transport, env=env, which=which)

    entries: list[dict] = []
    plans: dict[str, Plan] = {}
    for n, unit in enumerate(units, start=1):
        # Flushed before the album's first request: a run over hundreds of
        # albums, each possibly a network round trip, otherwise leaves the
        # owner watching a blank terminal for hours.
        print(f"identify: {n}/{len(units)} {unit.rel}", file=err, flush=True)
        decision = resolved_decisions.get(unit.rel, (None, None))[1]
        try:
            entry, plan = plan_entry(unit, root, built_clients, memory, decision,
                                     unit.rel in reopened_keys, env=env, which=which)
        except Exception as exc:
            entry, plan = _error_entry(unit, exc, decision), None
        entries.append(entry)
        if plan is not None:
            plans[unit.rel] = plan

    if reopen_keys:
        # Persisted, sorted and deduplicated, so a later job without
        # `--reopen` still holds the album: an auto-applied album is
        # corrected in a later sitting, from a later identify.
        memory["reopened"] = sorted(reopened_keys)
        memory_module.save(memory_path, memory)

    units_by_rel = {unit.rel: unit for unit in units}

    def replan(key: str, edition: str) -> tuple[dict, Plan]:
        return plan_entry(units_by_rel[key], root, built_clients, memory, resolved_decisions.get(key, (None, None))[1],
                          key in reopened_keys, edition=edition, env=env, which=which)

    _separate_editions(entries, plans, lambda e: edition_fields(built_clients.mb.release(e["release_id"])),
                       replan, err)

    _finalize(entries, plans, root)
    entries.sort(key=lambda e: e["source"])

    doc = {"job": job.id, "root": str(root.resolve()), "albums": entries}
    if decisions_sha256 is not None:
        # Left out rather than carried as `null`: every reader here is
        # `dict.get("decisions_sha256")`, which already gives `None` for a
        # key that is simply not there.
        doc["decisions_sha256"] = decisions_sha256
    job_module.write_json(job.plan, doc)
    job_module.write_bytes(job.review, review.render(doc))

    _print_counts(entries, out)
    return 0
