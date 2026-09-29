"""What an album looked like before any job wrote it, read from the `applied.jsonl` of every job beside `DIR`.

An `applied` line's `tags` hold each track's tags just before that write,
keyed by where the track went, and its `moves` say where it came from. A track
two jobs moved is followed back through both, newest job first, so the tags
that come out are the oldest write's record and not a job's own output.

Jobs are ordered oldest first by the modification time of their
`applied.jsonl`, ties broken by directory name. Every path is relative to the
library root, as the records hold them.
"""

from __future__ import annotations

from bisect import bisect_left
from pathlib import Path

from musiclib import mapping
from musiclib.batch import job as job_module
from musiclib.batch.job import Job

_RELEASE_ID_KEYS = frozenset(key for key in mapping.PICARD["release id"].values() if key)
_UNDONE_OUTCOMES = ("moves undone", "rolled back")


def _release_ids(tags: dict) -> set[str]:
    ids: set[str] = set()
    for key in _RELEASE_ID_KEYS:
        value = tags.get(key)
        if isinstance(value, str):
            value = [value]
        ids.update(item for item in value or [] if item)
    return ids


class History:
    def __init__(self, lines: list[dict]):
        """`lines`: every `applied.jsonl` line of every job, oldest first.

        Everything a lookup needs is indexed here by path or folder, as
        ascending line positions, so a lookup walks the move chain with a
        bisect per step and never scans the lines.
        """
        self._lines = [line for line in lines if line.get("outcome") in ("applied", *_UNDONE_OUTCOMES)]
        self._applied = [line for line in self._lines if line["outcome"] == "applied"]

        # original_tags: positions of the applied lines that hold a path in
        # `tags` or move it in as a library destination, and each line's
        # first library source for a destination.
        self._touching: dict[str, list[int]] = {}
        self._library_source: list[dict[str, str]] = []
        # original_source: positions of the applied lines by destination.
        self._by_destination: dict[str, list[int]] = {}
        # created: positions of the applied lines that delete a path or move
        # it away, and each line's first move by source.
        self._leaving: dict[str, list[int]] = {}
        self._first_move: list[dict[str, tuple[str, str]]] = []
        for index, line in enumerate(self._applied):
            record = line["record"]
            self._by_destination.setdefault(line["destination"], []).append(index)
            sources: dict[str, str] = {}
            first_move: dict[str, tuple[str, str]] = {}
            touched = set(record["tags"])
            leaving = set(record["deleted"])
            for source, destination, kind in record["moves"]:
                if kind == "library":
                    sources.setdefault(destination, source)
                    touched.add(destination)
                first_move.setdefault(source, (destination, kind))
                leaving.add(source)
            self._library_source.append(sources)
            self._first_move.append(first_move)
            for path in touched:
                self._touching.setdefault(path, []).append(index)
            for path in leaving:
                self._leaving.setdefault(path, []).append(index)

        # job_written: the newest line, of any applied or undone kind, that
        # names an album as its destination (or as its source, if undone).
        self._newest: dict[str, str] = {}
        for line in self._lines:
            self._newest[line["destination"]] = line["outcome"]
            if line["outcome"] in _UNDONE_OUTCOMES:
                self._newest[line["source"]] = line["outcome"]

        self._created: dict[str, list[str]] = {}
        seen: set[str] = set()
        for index, line in enumerate(self._applied):
            for path in line["record"]["created"]:
                current = self._follow_forward(path, index + 1)
                if current is not None and current not in seen:
                    seen.add(current)
                    self._created.setdefault(str(Path(current).parent), []).append(current)

    def original_tags(self, current_file: str) -> dict | None:
        """The tags `current_file` had before the oldest job wrote it, or `None` where no job did."""
        path, found, bound = current_file, None, len(self._applied)
        while True:
            positions = self._touching.get(path, ())
            at = bisect_left(positions, bound)
            if not at:
                return found
            bound = positions[at - 1]
            tags = self._applied[bound]["record"]["tags"]
            if path in tags:
                found = tags[path]
            path = self._library_source[bound].get(path, path)

    def original_source(self, album: str) -> str | None:
        """The folder `album` was in before the oldest job that applied it, or `None` where no job did."""
        folder, found, bound = album, None, len(self._applied)
        while True:
            positions = self._by_destination.get(folder, ())
            at = bisect_left(positions, bound)
            if not at:
                return found
            bound = positions[at - 1]
            folder = found = self._applied[bound]["source"]

    def created(self, album: str) -> list[str]:
        """The images jobs created in `album`, each once at its current path, none a later job deleted or sent to extras."""
        return list(self._created.get(album, ()))

    def _follow_forward(self, path: str, start: int) -> str | None:
        while True:
            positions = self._leaving.get(path, ())
            at = bisect_left(positions, start)
            if at == len(positions):
                return path
            index = positions[at]
            if path in self._applied[index]["record"]["deleted"]:
                return None
            path, kind = self._first_move[index][path]
            if kind != "library":
                return None
            start = index + 1

    def job_written(self, album: str, release_ids: dict[str, str | None]) -> bool:
        """Whether a job put the one release ID that every file of `album` now carries there.

        `release_ids` maps each current track path to its release ID, or
        `None` where it has none.
        """
        if self.original_source(album) is None or self._newest.get(album) in _UNDONE_OUTCOMES:
            return False
        current = set(release_ids.values())
        if len(current) != 1 or None in current:
            return False
        (release_id,) = current
        for path in release_ids:
            original = self.original_tags(path)
            if original is not None and release_id not in _release_ids(original):
                return True
        return False


def load(jobs_parent: Path) -> History:
    """The history of every job directory under `jobs_parent`."""
    jobs = [Job(path) for path in Path(jobs_parent).iterdir() if path.is_dir()]
    jobs = [job for job in jobs if job.applied.is_file()]
    jobs.sort(key=lambda job: (job.applied.stat().st_mtime, job.path.name))
    return History([line for job in jobs for line in job_module.read_log(job)])
