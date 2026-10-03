"""The write log: one line for each thing agitha changes on disk, on stderr and so in the journal.

A line is `write <action> <target> <key>=<value> ...`, and `write <action>
<target> failed: <reason>` where the change did not land. The server's own
request lines start with the caller's address, so `^write ` finds these
alone. A line names paths, counts and tag names, never a tag's value.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

WRITES = logging.getLogger("agitha.writes")
# With no handler at all a failure would go to logging's last resort, which prints.
WRITES.addHandler(logging.NullHandler())


def configure() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    WRITES.addHandler(handler)
    WRITES.setLevel(logging.INFO)
    WRITES.propagate = False


def _one_line(value: Any) -> str:
    return " ".join(str(value).splitlines())


def write(action: str, target: Any, /, **detail: Any) -> None:
    words = [f"{key}={_one_line(value)}" for key, value in detail.items() if value is not None]
    WRITES.info(" ".join(["write", action, _one_line(target), *words]))


def failed(action: str, target: Any, reason: Any) -> None:
    WRITES.warning(" ".join(["write", action, _one_line(target), "failed:", _one_line(reason)]))
