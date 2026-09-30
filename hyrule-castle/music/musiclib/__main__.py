"""CLI entry point: python3 -m musiclib."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musiclib import check
from musiclib.batch.job import Job, default_memory


def _positive_int(value: str) -> int:
    """`--limit`'s argparse type: a positive integer, nothing else.

    `--limit` ends up in a list slice (`candidates[:limit]`): 0 would
    silently apply nothing, and a negative number would count from the end
    instead of being rejected. Both are the owner's mistake to be told
    about, not a run that quietly does less than they asked.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--limit must be a positive integer, not {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"--limit must be a positive integer, not {value!r}")
    return parsed


def _check(root: str) -> int:
    path = Path(root)
    if not path.is_dir():
        # A typo in ROOT must not read as "a library with no violations" (an
        # empty check) nor crash: it is its own kind of failure, on stderr,
        # naming the root that was not there.
        print(f"musiclib check: {root}: not a directory", file=sys.stderr)
        return 2
    violations = check.check(path)
    for violation in sorted(violations):
        print(f"{violation.album}: {violation.rule} - {violation.detail}")
    return 1 if violations else 0


def _batch_identify(args: argparse.Namespace) -> int:
    from musiclib.batch.identify import run

    job = Job(Path(args.job))
    memory = Path(args.memory) if args.memory else default_memory(job)
    rejudge = Path(args.rejudge) if args.rejudge else None
    return run(Path(args.root), job, memory, list(args.reopen or []), rejudge=rejudge, composer=not args.no_composer)


def _batch_apply(args: argparse.Namespace) -> int:
    from musiclib.batch.apply import run

    job = Job(Path(args.job))
    memory = Path(args.memory) if args.memory else default_memory(job)
    return run(job, memory, limit=args.limit, extras_root=Path(args.extras),
               live_root=Path(args.live_root), systemctl=args.systemctl)


def _batch_rollback(args: argparse.Namespace) -> int:
    from musiclib.batch.rollback import run

    return run(Job(Path(args.job)), extras_root=Path(args.extras),
              live_root=Path(args.live_root), systemctl=args.systemctl)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="musiclib")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="report library violations")
    check_parser.add_argument("root", metavar="ROOT")

    batch_parser = subparsers.add_parser("batch", help="the 2b batch over the whole library")
    batch_subparsers = batch_parser.add_subparsers(dest="batch_command", required=True)

    identify_parser = batch_subparsers.add_parser("identify", help="plan every album under ROOT into a job")
    identify_parser.add_argument("root", metavar="ROOT")
    identify_parser.add_argument("--job", required=True, metavar="DIR")
    identify_parser.add_argument("--memory", metavar="PATH")
    identify_parser.add_argument("--reopen", action="append", default=[], metavar="PATH")
    identify_parser.add_argument("--rejudge", metavar="ORIGINAL",
                                 help="judge the albums a job tagged again from their original tags and covers under ORIGINAL")
    identify_parser.add_argument("--no-composer", action="store_true",
                                 help="make no work relationship lookup and leave every file's composer tags as they are")

    apply_parser = batch_subparsers.add_parser("apply", help="write the auto-apply and accepted albums")
    apply_parser.add_argument("--job", required=True, metavar="DIR")
    apply_parser.add_argument("--limit", type=_positive_int, default=None, metavar="N")
    apply_parser.add_argument("--memory", metavar="PATH")
    apply_parser.add_argument("--extras", default="/srv/music/extras", metavar="PATH")
    apply_parser.add_argument("--live-root", default="/srv/music/library", metavar="PATH")
    apply_parser.add_argument("--systemctl", default="systemctl", metavar="CMD")

    rollback_parser = batch_subparsers.add_parser("rollback", help="undo the job's applied writes")
    rollback_parser.add_argument("--job", required=True, metavar="DIR")
    rollback_parser.add_argument("--extras", default="/srv/music/extras", metavar="PATH")
    rollback_parser.add_argument("--live-root", default="/srv/music/library", metavar="PATH")
    rollback_parser.add_argument("--systemctl", default="systemctl", metavar="CMD")

    args = parser.parse_args(argv)

    if args.command == "check":
        return _check(args.root)

    if args.command == "batch":
        if args.batch_command == "identify":
            return _batch_identify(args)
        if args.batch_command == "apply":
            return _batch_apply(args)
        if args.batch_command == "rollback":
            return _batch_rollback(args)
        parser.error(f"unknown batch command: {args.batch_command}")
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
