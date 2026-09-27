"""Reading `decisions.json`: refused whole when it does not fit the job.

A file for another job, one naming an album the job does not have, two keys
that lead to the same album, an unknown action, a repoint the engine's own
`release_ref` refuses, a `game` value outside the two the page offers, an
`accept` of a `game_choice` album with no `game`, an `accept` with no
`release_id`, an `accept` whose `edits` is not an object of objects of
lists, an edit to a field the page never offers or at a position the album
does not have, or JSON that does not parse: any of these refuses the file
entire, naming every offence found rather than only the first, so the owner
does not re-export once per problem.
"""

from __future__ import annotations

import hashlib
import json

from musiclib import mapping
from musiclib.batch import job as job_module
from musiclib.batch.job import Job
from musiclib.batch.memory import NOT_GAME_MUSIC, VIDEO_GAME_MUSIC
from musiclib.identify import release_ref

_ACTIONS = {"accept", "repoint", "skip"}
_GAME_CHOICES = {VIDEO_GAME_MUSIC, NOT_GAME_MUSIC}

#: MusicBrainz identifiers, never offered as an editable field on the page:
#: every other `mapping.PICARD` key is a neutral field an `accept` may edit.
_ID_FIELDS = {"release id", "release group id", "recording id", "release track id",
             "artist id", "album artist id"}
_OFFERED_FIELDS = set(mapping.PICARD) - _ID_FIELDS


class DecisionsRejected(Exception):
    """`decisions.json` does not fit this job. Its message names every offence, not only the first."""


def _decisions_sha256(job: Job) -> str | None:
    """The sha256 hex of `job.decisions`'s bytes, or `None` where there is no file.

    `batch identify` folds this into `plan.json`'s `decisions_sha256`, and
    `batch apply` recomputes it over the file on disk to check the two still
    agree, both by calling here rather than each reading `job.decisions` on
    its own.
    """
    return hashlib.sha256(job.decisions.read_bytes()).hexdigest() if job.decisions.is_file() else None


def _plan_albums(job: Job) -> list[dict]:
    try:
        doc = job_module.read_json(job.plan)
    except FileNotFoundError:
        return []
    return doc.get("albums", [])


def _applied_map(job: Job) -> dict[str, str]:
    """`{source: destination}` for every `applied.jsonl` line this job actually wrote."""
    return {line["source"]: line["destination"]
           for line in job_module.read_log(job) if line.get("outcome") == "applied"}


def _follow(key: str, applied_map: dict[str, str]) -> str:
    """`key`, followed source to destination through `applied_map` until nothing moves it further.

    `seen` guards against a cycle that should never exist (an album cannot
    apply back to its own earlier path) rather than looping forever if one
    somehow did.
    """
    seen: set[str] = set()
    while key in applied_map and key not in seen:
        seen.add(key)
        key = applied_map[key]
    return key


def _known_albums(albums: list[dict], applied_map: dict[str, str]) -> set[str]:
    """Every album key this job "has": a current `plan.json` source, or one `applied.jsonl` moved."""
    return {entry["source"] for entry in albums} | set(applied_map)


def _is_edits_shape(edits) -> bool:
    """Whether `edits` is `{"<position>": {"<field>": [<value>, ...]}}` all the way down."""
    if not isinstance(edits, dict):
        return False
    for fields in edits.values():
        if not isinstance(fields, dict):
            return False
        if not all(isinstance(values, list) for values in fields.values()):
            return False
    return True


def read(job: Job) -> dict | None:
    """`job.decisions`, validated against `job.plan`, or `None` for no file at all.

    Raises `DecisionsRejected` naming every offence when the file does not
    fit; the caller (`batch identify`, `batch apply`) writes nothing at all
    when that happens.
    """
    if not job.decisions.is_file():
        return None

    try:
        doc = json.loads(job.decisions.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DecisionsRejected(f"decisions.json is not valid JSON: {exc}") from exc

    albums = _plan_albums(job)
    applied_map = _applied_map(job)
    known = _known_albums(albums, applied_map)
    by_source = {entry["source"]: entry for entry in albums}

    offences: list[str] = []
    job_id = doc.get("job")
    if job_id != job.id:
        offences.append(f"decisions.json is for job {job_id!r}, not this job ({job.id!r})")

    given_albums = doc.get("albums") or {}

    by_identity: dict[str, list[str]] = {}
    for key in given_albums:
        if key in known:
            by_identity.setdefault(_follow(key, applied_map), []).append(key)
    for keys in by_identity.values():
        if len(keys) > 1:
            offences.append(f"{sorted(keys)!r} all name the same album")

    for key, decision in given_albums.items():
        if key not in known:
            offences.append(f"{key!r} is not an album this job has planned")
            continue
        action = decision.get("action") if isinstance(decision, dict) else None
        if action not in _ACTIONS:
            offences.append(f"{key!r}: not a recognised action: {action!r}")
            continue
        if action == "repoint":
            try:
                release_ref(decision.get("release", ""))
            except ValueError as exc:
                offences.append(str(exc))
        elif action == "accept":
            if not decision.get("release_id"):
                offences.append(f"{key!r}: an accept needs a release_id")
            game = decision.get("game")
            entry = by_source.get(key) or by_source.get(_follow(key, applied_map)) or {}
            if game is not None and game not in _GAME_CHOICES:
                offences.append(f"{key!r}: not a recognised game choice: {game!r}")
            elif game is None and entry.get("game_choice"):
                offences.append(
                    f"{key!r}: a Soundtrack-type or game album must say "
                    f"{VIDEO_GAME_MUSIC!r} or {NOT_GAME_MUSIC!r}"
                )
            edits = decision.get("edits")
            if edits is not None and not _is_edits_shape(edits):
                offences.append(f"{key!r}: edits must be positions of fields of lists, not {edits!r}")
                continue
            positions = set(entry.get("fields") or {})
            for position, fields in (edits or {}).items():
                if position not in positions:
                    offences.append(f"{key!r}: {position!r} is not a position this album has")
                    continue
                for field in fields:
                    if field not in _OFFERED_FIELDS:
                        offences.append(f"{key!r}: {field!r} is not a field the page offers")

    if offences:
        raise DecisionsRejected("; ".join(offences))

    return doc
