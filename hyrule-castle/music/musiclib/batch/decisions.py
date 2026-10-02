"""Reading `decisions.json`: refused whole when it does not fit the job.

A file for another job, one naming an album the job does not have, two keys
that lead to the same album, an unknown action, a repoint the engine's own
`release_ref` refuses, a `game` value outside the three the page offers
(`not game music` from before reads as `soundtrack`), an `accept` with no
`release_id`, an `accept` whose `edits` is not an object of objects of lists,
an edit to a field the page never offers or at a position the album does
not have, a `strays` answer for a path that is not a stray, a name the stray
rules refuse or one that two strays or a kept file would share, an owner
`cover` that is not a relative path inside the job, or JSON that does not
parse: any of these refuses the file entire, naming every offence found
rather than only the first, so the owner does not re-export once per
problem.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from mutagen.id3 import Frames, PairedTextFrame, TextFrame

from musiclib import files, mapping, strays as strays_module, tagwrite
from musiclib.batch import job as job_module
from musiclib.batch.job import Job
from musiclib.batch.memory import NOT_GAME_MUSIC
from musiclib.genres import NEITHER, SOUNDTRACK, VIDEO_GAME_MUSIC
from musiclib.identify import release_ref

_ACTIONS = {"accept", "repoint", "skip"}
_GAME_CHOICES = {VIDEO_GAME_MUSIC, SOUNDTRACK, NEITHER, NOT_GAME_MUSIC}

#: MusicBrainz identifiers, never offered as an editable field on the page:
#: every other `mapping.PICARD` key is a neutral field an `accept` may edit.
ID_FIELDS = {"release id", "release group id", "recording id", "release track id",
             "artist id", "album artist id"}
_OFFERED_FIELDS = set(mapping.PICARD) - ID_FIELDS

#: Raw keys of each family that hold a rating besides what `tagwrite.is_rating_key`
#: knows, and those that hold a picture. Compared case-folded.
_RATINGS = {"mp4": {"----:com.apple.itunes:rating", "----:com.apple.itunes:fmps_rating", "rate"},
            "asf": {"wm/shareduserrating", "fmps_rating"}}
_BINARY = {"vorbis": {"metadata_block_picture"}, "mp4": {"covr"}, "asf": {"wm/picture"}}
_ID3_BINARY = {"APIC", "GEOB", "PRIV"}
_ID3_KEYED = ("TXXX", "COMM", "USLT")

#: MP4 atoms whose value is a number, a flag or a pair rather than text, so
#: no list of strings writes them.
_MP4_NOT_TEXT = {"tmpo", "cpil", "rtng", "stik", "gnre", "trkn", "disk", "pgap", "hdvd", "shwm", "pcst",
                 "plID", "cnID", "atID", "geID", "cmID", "sfID", "akID"}


class DecisionsRejected(Exception):
    """`decisions.json` does not fit this job. Its message names every offence, not only the first."""


def decisions_sha256(job: Job) -> str | None:
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


def applied_map(job: Job) -> dict[str, str]:
    """`{source: destination}` for every `applied.jsonl` line this job actually wrote."""
    return {line["source"]: line["destination"]
           for line in job_module.read_log(job) if line.get("outcome") == "applied"}


def follow_moves(key: str, applied: dict[str, str]) -> str:
    """`key`, followed source to destination through `applied` (from `applied_map`) until nothing moves it further.

    `seen` guards against a cycle that should never exist (an album cannot
    apply back to its own earlier path) rather than looping forever if one
    somehow did.
    """
    seen: set[str] = set()
    while key in applied and key not in seen:
        seen.add(key)
        key = applied[key]
    return key


def _known_albums(albums: list[dict], applied: dict[str, str]) -> set[str]:
    """Every album key this job "has": a current `plan.json` source, or one `applied.jsonl` moved."""
    return {entry["source"] for entry in albums} | set(applied)


def _is_edits_shape(edits) -> bool:
    """Whether `edits` is `{"<position>": {"<field or raw key>": [<value>, ...] | null}}` all the way down."""
    if not isinstance(edits, dict):
        return False
    for fields in edits.values():
        if not isinstance(fields, dict):
            return False
        if not all(values is None or isinstance(values, list) for values in fields.values()):
            return False
    return True


def _is_id3_text_frame(key: str) -> bool:
    """Whether `key` is a bare text frame `tagwrite` builds from a list of values."""
    frame = Frames.get(key)
    return (frame is not None and issubclass(frame, TextFrame) and not issubclass(frame, PairedTextFrame)
            and key != "TXXX")


def raw_key_offence(family: str, key: str) -> str | None:
    """Why an owner may not set or remove `key`, a raw key of `family`, or `None`.

    Names are compared case-folded: a Vorbis field name has no case, and an
    ID or rating spelled another way is still one.
    """
    folded = key.casefold()
    for field in ID_FIELDS:
        if (real := mapping.PICARD[field].get(family)) and real.casefold() == folded:
            return "is a MusicBrainz ID"
    if tagwrite.is_rating_key(family, folded if family == "vorbis" else key) or folded in _RATINGS.get(family, ()):
        return "is a rating"
    if family == "id3":
        frame_id = key.split(":", 1)[0]
        if frame_id in _ID3_BINARY:
            return "is a binary frame"
        if ":" in key and frame_id in _ID3_KEYED or _is_id3_text_frame(key):
            return None
        return "is not a text frame this engine can write"
    if folded in _BINARY.get(family, ()):
        return "is a binary tag"
    if family == "vorbis" and not (key and key.isascii() and all(" " <= c <= "}" and c != "=" for c in key)):
        return "is not a Vorbis field name"
    if family == "mp4" and not key.startswith("----:"):
        if len(key) != 4:
            return "is neither four characters nor a ----: atom"
        if key in _MP4_NOT_TEXT:
            return "is not a text atom"
    return None


def _cover_offence(job: Job, cover) -> str | None:
    """Why `cover` cannot name an image inside the job, or `None`. Whether the file exists is not asked."""
    if not isinstance(cover, str):
        return f"cover must be a path inside the job, not {cover!r}"
    path = PurePosixPath(cover)
    if not cover or path.is_absolute() or ".." in path.parts:
        return f"cover {cover!r} must be a relative path inside the job, without '..'"
    if not (job.path / cover).resolve().is_relative_to(job.path.resolve()):
        return f"cover {cover!r} leads outside the job"
    return None


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
    applied = applied_map(job)
    known = _known_albums(albums, applied)
    by_source = {entry["source"]: entry for entry in albums}

    offences: list[str] = []
    job_id = doc.get("job")
    if job_id != job.id:
        offences.append(f"decisions.json is for job {job_id!r}, not this job ({job.id!r})")

    given_albums = doc.get("albums") or {}

    by_identity: dict[str, list[str]] = {}
    for key in given_albums:
        if key in known:
            by_identity.setdefault(follow_moves(key, applied), []).append(key)
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
            if decision.get("cover") is not None and (offence := _cover_offence(job, decision["cover"])):
                offences.append(f"{key!r}: {offence}")
            game = decision.get("game")
            entry = by_source.get(key) or by_source.get(follow_moves(key, applied)) or {}
            if game is not None and game not in _GAME_CHOICES:
                offences.append(f"{key!r}: not a recognised game choice: {game!r}")
            if decision.get("strays") is not None:
                offences += [f"{key!r}: {offence}" for offence in strays_module.answer_offences(entry, decision["strays"])]
            edits = decision.get("edits")
            if edits is not None and not _is_edits_shape(edits):
                offences.append(f"{key!r}: edits must be positions of fields of lists, not {edits!r}")
                continue
            positions = set(entry.get("fields") or {})
            families = {planned.get("position"):
                        files.FAMILY_BY_EXTENSION.get(PurePosixPath(planned.get("source", "")).suffix.lower())
                        for planned in entry.get("files") or []}
            for position, fields in (edits or {}).items():
                if position not in positions:
                    offences.append(f"{key!r}: {position!r} is not a position this album has")
                    continue
                for field in fields:
                    if field in _OFFERED_FIELDS:
                        continue
                    if field in ID_FIELDS or not (family := families.get(position)):
                        offences.append(f"{key!r}: {field!r} is not a field the page offers")
                    elif offence := raw_key_offence(family, field):
                        offences.append(f"{key!r}: {position!r}: {field!r} {offence}")

    if offences:
        raise DecisionsRejected("; ".join(offences))

    return doc
