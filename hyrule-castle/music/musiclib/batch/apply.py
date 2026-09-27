"""`musiclib batch apply --job DIR`: write the auto and accepted albums, one at a time.

Everything to write is already decided by `batch identify`: an album
applies when its `plan.json` entry is `state == "auto"` and the owner did
not skip it, or the owner's `decisions.json` accepted it. Nothing else in
the library moves.

Every album's decision - `accept`, `repoint`, `skip`, or none at all - comes
from its own `plan.json` entry (`decision`), never read from `decisions.json`
again here: identify already folded that file in, and `entry` is the plan
the page showed for it. Apply still reads `decisions.json` itself, for two
things only: refusing the run if it no longer fits this job the same way
identify would, and refusing it if its bytes differ from the ones the last
identify folded in (a file exported after that identify ran, or removed
since) - `plan.json`'s own `decisions_sha256` is what that second check is
for.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from musiclib.batch import decisions
from musiclib.batch import identify
from musiclib.batch import job as job_module
from musiclib.batch import memory as memory_module
from musiclib.batch.job import Job
from musiclib.units import units as list_units
from musiclib.write import AlbumFailed, FoobarRunning, _guard_foobar, write_album


def _applicable(entry: dict) -> bool:
    """Every album in the auto state that the owner did not skip, plus whatever the owner accepted."""
    action = entry.get("decision")
    if entry["state"] == "auto" and action != "skip":
        return True
    return action == "accept"


def run(job: Job, memory_path: Path, *, limit: int | None = None,
       extras_root: Path = Path("/srv/music/extras"), live_root: Path = Path("/srv/music/library"),
       systemctl: str = "systemctl", transport=None, out=sys.stdout, err=sys.stderr) -> int:
    try:
        decisions.read(job)
    except decisions.DecisionsRejected as exc:
        # Refused whole, the same as identify: nothing is written.
        print(str(exc), file=err)
        return 1

    try:
        plan_doc = job_module.read_json(job.plan)
    except FileNotFoundError:
        print(f"{job.plan} does not exist; run `musiclib batch identify` first", file=err)
        return 1
    root = Path(plan_doc["root"])
    live_root = Path(live_root)
    extras_root = Path(extras_root)

    on_disk_sha256 = decisions._decisions_sha256(job)
    if on_disk_sha256 != plan_doc.get("decisions_sha256"):
        print(f"{job.decisions} does not match the decisions the last "
              "`musiclib batch identify` folded in; run it again first", file=err)
        return 1

    try:
        _guard_foobar(root, live_root, systemctl)
    except FoobarRunning as exc:
        print(str(exc), file=err)
        return 1

    memory_doc = memory_module.load(memory_path)

    already_applied = {line["source"] for line in job_module.read_log(job) if line["outcome"] == "applied"}
    # Every album the owner said yes to, whether or not apply ever gets to
    # try it: an accept identify could not plan at all must still be
    # reported, not read as nothing to do.
    accepted = {entry["source"] for entry in plan_doc["albums"] if entry.get("decision") == "accept"}

    candidates = []
    for entry in plan_doc["albums"]:
        key = entry["source"]
        if key in already_applied:
            continue
        if _applicable(entry):
            candidates.append(entry)
    # `--limit` leaves the rest for a later run, not failed: an accept among
    # them is waiting, so the backstop below must not count it as unwritten.
    limited_out = {entry["source"] for entry in candidates[limit:]} if limit is not None else set()
    if limit is not None:
        candidates = candidates[:limit]

    ok = True
    written: set[str] = set()
    reported: set[str] = set()

    def fail(key: str, message: str) -> None:
        nonlocal ok
        print(f"{key}: {message}", file=err)
        ok = False
        reported.add(key)

    if candidates:
        built_clients = identify.clients(job, transport=transport)
        units_by_rel = {unit.rel: unit for unit in list_units(root)}

        for entry in candidates:
            key = entry["source"]
            action = entry.get("decision")

            if action == "accept" and any(hold["kind"] == "decision" for hold in entry["holds"]):
                # `identify` already found this accept's plan cannot be
                # written (a problem or a collision) and held it for that
                # reason; apply must not try it.
                fail(key, "accepted but its plan cannot be written; not applied")
                continue

            inputs = entry.get("inputs")
            unit = units_by_rel.get(key)
            if inputs is None or unit is None:
                fail(key, "no plan to apply")
                continue

            try:
                plan = identify.rebuild(unit, root, built_clients, inputs)
            except Exception as exc:
                fail(key, f"could not rebuild its plan: {exc}")
                continue

            if hashlib.sha256(plan.to_json()).hexdigest() != entry.get("plan_digest"):
                # The album changed on disk since identify looked at it - the
                # plan nobody reviewed must never be written.
                fail(key, "its plan has changed since identify; refused")
                continue

            try:
                record = write_album(plan, extras_root, live_root=live_root, systemctl=systemctl)
            except AlbumFailed as exc:
                job_module.append_log(job, {"source": key, "destination": entry["destination"],
                                            "outcome": "failed", "error": str(exc), "record": exc.record})
                fail(key, str(exc))
                continue
            except Exception as exc:
                # `write_album` refused before touching anything (a collision,
                # a stale file it caught on its own, foobar started mid-run):
                # no record exists, so no line is written.
                fail(key, str(exc))
                continue

            job_module.append_log(job, {"source": key, "destination": entry["destination"],
                                        "outcome": "applied", "error": None, "record": record})
            written.add(key)

            # The memory, so a later job or a re-run of this one plans the same
            # thing without asking again: only an accept can carry a new edit
            # or genre choice, and only an applied accept ever takes an album
            # off the reopened list - an auto write is not the correction the
            # owner reopened it for, however welcome.
            changed = False
            if action == "accept":
                memory_module.remember(memory_doc, entry)
                if key in memory_doc.get("reopened", []):
                    memory_doc["reopened"] = [k for k in memory_doc["reopened"] if k != key]
                changed = True
            if changed:
                memory_module.save(memory_path, memory_doc)

    for key in sorted(accepted - already_applied - written - reported - limited_out):
        # Catches an accept `candidates` never carried at all: every branch
        # inside the loop above already reports the ones it did carry.
        # `limited_out` is the one exclusion that is not a failure: `--limit`
        # left it for a later run on purpose.
        fail(key, "accepted but not applied")

    return 0 if ok else 1
