"""CLI entry point: python3 -m musiclib."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musiclib import check


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="musiclib")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="report library violations")
    check_parser.add_argument("root", metavar="ROOT")

    args = parser.parse_args(argv)

    if args.command == "check":
        return _check(args.root)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
