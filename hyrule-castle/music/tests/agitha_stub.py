#!/usr/bin/env python3
"""A stand-in for `musiclib batch identify` and `batch apply` that answers from a fake MusicBrainz.

The server's tests point it at this with `--musiclib tests/agitha_stub.py`.
It takes the real command's words and runs the real engine over the fake
transport of `tests.test_batch_identify`, so a job it leaves is one the
engine would write.

Environment:
  AGITHA_STUB_FAIL=identify|apply  that command prints a known failure to stderr and exits 1
  AGITHA_STUB_SLEEP=SECONDS        wait before running
  AGITHA_STUB_CATALOGUE=PATH       JSON list of [release, release_group] pairs the fake answers from
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Run from any cwd: `musiclib` and `tests` sit in the folder above this file's.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_CATALOGUE = Path(__file__).resolve().parent / "fixtures" / "agitha" / "catalogue.json"
FAIL_LINES = 24


def _fail(command: str) -> int:
    print(f"agitha stub: {command} failed on purpose", file=sys.stderr)
    for n in range(1, FAIL_LINES + 1):
        print(f"agitha stub: line {n}", file=sys.stderr)
    return 1


def _services():
    from musiclib import mb
    from tests.test_batch_identify import Services

    # The fake needs no rate limit, and the client would otherwise sleep a second per request.
    mb._MIN_INTERVAL = 0.0
    path = Path(os.environ.get("AGITHA_STUB_CATALOGUE") or DEFAULT_CATALOGUE)
    catalogue = [(pair[0], pair[1]) for pair in json.loads(path.read_text(encoding="utf-8"))]
    return Services(catalogue)


def _identify(args: argparse.Namespace) -> int:
    from musiclib.batch.identify import run
    from musiclib.batch.job import Job

    job = Job(Path(args.job))
    memory = Path(args.memory) if args.memory else job.path.resolve().parent / "agitha-memory.json"
    return run(Path(args.root), job, memory, list(args.reopen or []), transport=_services(),
               env={}, which=lambda _name: None, composer=not args.no_composer, added=args.added,
               drop_unreadable=args.drop_unreadable)


def _apply(args: argparse.Namespace) -> int:
    from musiclib.batch.apply import run
    from musiclib.batch.job import Job

    job = Job(Path(args.job))
    memory = Path(args.memory) if args.memory else job.path.resolve().parent / "agitha-memory.json"
    options = {}
    if args.systemctl:
        options["systemctl"] = args.systemctl
    # The guard asks systemctl only for a root under `live_root`, and an inbox root never is.
    return run(job, memory, extras_root=Path(args.extras), live_root=Path(args.live_root),
               transport=_services(), **options)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agitha_stub.py")
    commands = parser.add_subparsers(dest="command", required=True)
    batch = commands.add_parser("batch").add_subparsers(dest="batch_command", required=True)

    identify = batch.add_parser("identify")
    identify.add_argument("root")
    identify.add_argument("--job", required=True)
    identify.add_argument("--memory")
    identify.add_argument("--reopen", action="append", default=[])
    identify.add_argument("--no-composer", action="store_true")
    identify.add_argument("--added")
    identify.add_argument("--drop-unreadable", action="store_true")

    apply = batch.add_parser("apply")
    apply.add_argument("--job", required=True)
    apply.add_argument("--memory")
    apply.add_argument("--extras", default="/srv/music/extras")
    apply.add_argument("--live-root", default="/srv/music/library")
    apply.add_argument("--systemctl")

    args = parser.parse_args(argv)
    name = args.batch_command
    if os.environ.get("AGITHA_STUB_FAIL") == name:
        return _fail(name)
    if os.environ.get("AGITHA_STUB_SLEEP"):
        time.sleep(float(os.environ["AGITHA_STUB_SLEEP"]))
    return _identify(args) if name == "identify" else _apply(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
