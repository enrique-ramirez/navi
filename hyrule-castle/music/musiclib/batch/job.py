"""One job directory: its fixed layout, and the canonical JSON every file in it uses.

A job is `/srv/music/.musiclib/jobs/<id>/`, holding the engine's warm cache
and everything the batch has written about the run. `write_json` is the one
place every batch module writes JSON, so `plan.json`, `decisions.json`,
`memory.json` and `applied.jsonl`'s per-line objects are all byte-identical
across two runs of the same inputs.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Job:
    """One job directory and the fixed paths under it."""

    path: Path

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def cache(self) -> Path:
        return self.path / "cache"

    @property
    def plan(self) -> Path:
        return self.path / "plan.json"

    @property
    def review(self) -> Path:
        return self.path / "review.html"

    @property
    def decisions(self) -> Path:
        return self.path / "decisions.json"

    @property
    def applied(self) -> Path:
        return self.path / "applied.jsonl"


def default_memory(job: Job) -> Path:
    return job.path.resolve().parent.parent / "memory.json"


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_bytes(path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_json(path, doc) -> None:
    data = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
    write_bytes(path, data)


#: ASCII whitespace only, for spotting a blank line in `read_log`. `str.strip()`
#: with no argument also strips U+2028, U+2029 and U+0085, which `append_log`
#: can put in the middle of a JSON string as an ordinary character, not as a
#: line break: stripping on the wider set could call a line blank when it is
#: JSON that merely starts or ends with one of those characters.
_ASCII_WHITESPACE = " \t\n\r\v\f"


def read_log(job: Job) -> list[dict]:
    """`applied.jsonl`, one dict per line, oldest first. No file is no lines.

    Split on `"\\n"` alone, the character `append_log` ends each line with.
    `str.splitlines()` also breaks on U+2028, U+2029 and U+0085, any of
    which a tag value can hold, and a split there cuts a JSON string in two.
    """
    if not job.applied.is_file():
        return []
    text = job.applied.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n")
            if line.strip(_ASCII_WHITESPACE)]


def append_log(job: Job, entry: dict) -> None:
    """One canonical line, appended and flushed as it happens.

    Opened and closed for this one line rather than held open across the
    run: `batch.apply` and `batch.rollback` both write this file over a run
    that can take hours, and a line left sitting in a held-open handle's
    buffer is invisible to anything reading `applied.jsonl` in the meantime.
    """
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"
    with open(job.applied, "a", encoding="utf-8") as handle:
        handle.write(line)
