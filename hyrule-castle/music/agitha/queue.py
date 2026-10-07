"""One musiclib process at a time, for every album of every drop, and the routes that feed it.

`Queue` keeps its work in memory. What survives a restart is `album.json`,
which `state.read` reconciles with the disk.
"""

from __future__ import annotations

import queue as fifo
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from . import albums, approve, archives, drops, log, state

if TYPE_CHECKING:
    from .server import Config, Handler

STDERR_LINES = 20
WHILE = {"identify": "identifying", "apply": "applying"}
RETRYABLE = ("identify failed", "identify interrupted")


def added_stamp(record: dict[str, Any] | None) -> str | None:
    """The drop's upload start as the box's local `YYYY-MM-DDTHH:MM`, the `ADDED` of every file it imports.

    `started` is written local and naive; one with an offset is turned into
    local time first. None where the record has no time that reads.
    """
    try:
        started = datetime.fromisoformat((record or {})["started"])
    except (KeyError, TypeError, ValueError):
        return None
    if started.tzinfo is not None:
        started = started.astimezone().replace(tzinfo=None)
    return started.strftime("%Y-%m-%dT%H:%M")


class _Job(NamedTuple):
    #: The drop of an album's `identify` or `apply`; `None` for a hand edit of a library album.
    drop: str | None
    #: The album's number in its drop, or its library path.
    key: str
    call: Callable[[], None]
    #: Told of an exception `call` lets out, so one failure does not end the worker.
    on_error: Callable[[Exception], None]


class Queue:
    """FIFO of jobs, worked off by one daemon thread that starts with the first `enqueue`.

    A job is `identify` or `apply` of an album of a drop, or, for a hand edit
    of the library, a function run in this process. That one is busy by the
    album's library path, so the worker is the only writer of a library folder.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._work: fifo.Queue[_Job] = fifo.Queue()
        self._lock = threading.Lock()
        self._busy: set[tuple[str, str]] = set()
        self._busy_library: set[str] = set()
        self._thread: threading.Thread | None = None

    def _start(self) -> None:
        """Starts the worker once; the caller holds the lock."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="agitha-queue", daemon=True)
            self._thread.start()

    def enqueue(self, drop: str, n: str, command: str) -> bool:
        """Queues `command` (`identify` or `apply`) for the album; False where it is already queued or running."""
        with self._lock:
            if (drop, n) in self._busy:
                return False
            self._busy.add((drop, n))
            self._work.put(_Job(drop, n, partial(self._run, drop, n, command),
                                partial(self._fail, drop, n, command)))
            self._start()
        return True

    def enqueue_library(self, calls: list[tuple[str, Callable[[], None]]]) -> bool:
        """Queues each `(library path, function)` in order; False, with none queued, where one path is busy.

        A function ends in its own way: an exception it lets out goes to stderr.
        """
        with self._lock:
            if any(path in self._busy_library for path, _call in calls):
                return False
            for path, call in calls:
                self._busy_library.add(path)
                self._work.put(_Job(None, path, call, partial(_report, path)))
            self._start()
        return True

    def busy(self, drop: str, n: str) -> bool:
        """Queued or running."""
        return (drop, n) in self._busy

    def busy_library(self, path: str) -> bool:
        """Whether a save of the library album at `path` is queued or running."""
        return path in self._busy_library

    def busy_drop(self, drop: str) -> bool:
        with self._lock:
            return any(d == drop for d, _ in self._busy)

    def _loop(self) -> None:
        while True:
            job = self._work.get()
            try:
                job.call()
            except Exception as exc:
                job.on_error(exc)
            finally:
                with self._lock:
                    if job.drop is None:
                        self._busy_library.discard(job.key)
                    else:
                        self._busy.discard((job.drop, job.key))

    def _fail(self, drop: str, n: str, command: str, exc: Exception) -> None:
        text = f"{type(exc).__name__}: {exc}"
        log.failed(command, f"{drop}/{n}", text)
        folder = self.config.inbox / drop / n
        job = self.config.jobs / f"agitha-{drop}-{n}"
        # `write_album` would recreate a folder that landing removed, so a landed album is left as it is.
        if not folder.is_dir() or (job / "landed.json").exists():
            return
        try:
            if command == "identify" and state.plan_entry(self.config, drop, n) is not None:
                drops.write_album(folder, state="ready", stderr="", error=text)
            else:
                drops.write_album(folder, state=f"{command} failed", stderr=text, error=text)
        except Exception:
            pass

    def _command(self, drop: str, n: str, command: str) -> list[str]:
        config = self.config
        job = str(config.jobs / f"agitha-{drop}-{n}")
        if command == "identify":
            # A match is an album the library already has; it keeps each file's own time.
            matched = drops.replaces_of(drops.read_album(config.inbox / drop / n)) is not None
            added = None if matched else added_stamp(drops.read_record(config.inbox / drop))
            return [config.musiclib, "batch", "identify", str(config.inbox / drop / n), "--job", job,
                    "--drop-unreadable", *(["--added", added] if added else [])]
        return [config.musiclib, "batch", "apply", "--job", job,
                "--extras", str(config.extras), "--live-root", str(config.library)]

    def _run(self, drop: str, n: str, command: str) -> None:
        folder = self.config.inbox / drop / n
        drops.write_album(folder, state=WHILE[command])
        try:
            done = subprocess.run(self._command(drop, n, command), capture_output=True, text=True, errors="replace")
            code, stderr = done.returncode, done.stderr
        except OSError as exc:
            code, stderr = 127, str(exc)
        tail = "\n".join(stderr.splitlines()[-STDERR_LINES:])
        if command == "apply":
            if code == 0:
                # `land` writes the outcome; the album stays `applying` until it has.
                drops.write_album(folder, stderr="", error=None)
                approve.land(self.config, drop, n)
            else:
                drops.write_album(folder, state="apply failed", stderr=tail, error=f"apply exited with status {code}")
                log.failed("apply", f"{drop}/{n}", f"apply exited with status {code}")
        elif state.plan_entry(self.config, drop, n) is not None:
            # A refused decision leaves the earlier plan in place and says why on the album.
            drops.write_album(folder, state="ready", stderr="", error=tail if code else None)
            if code:
                log.failed("identify", f"{drop}/{n}", f"identify exited with status {code}; the earlier plan stays")
            else:
                log.write("identify", f"{drop}/{n}", state="ready")
        else:
            error = f"identify exited with status {code}" if code else "identify left no album in its plan"
            drops.write_album(folder, state="identify failed", stderr=tail, error=error)
            log.failed("identify", f"{drop}/{n}", error)


def _report(path: str, exc: Exception) -> None:
    print(f"agitha: the save of {path} ended with {type(exc).__name__}: {exc}", file=sys.stderr)


def _known(config: Config, drop: str) -> Path | None:
    """The folder of a drop that has a `drop.json`, or None."""
    folder = drops.drop_dir(config, drop)
    return folder if folder is not None and drops.read_record(folder) is not None else None


def _extract_archives(folder: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    """Opens every archive item in place; returns one refusal for each item an archive turned away."""
    refused: list[dict[str, Any]] = []
    for item in record["items"]:
        if item["kind"] != "archive":
            continue
        root = folder / "raw" / item["name"]
        for entry in item["files"]:
            try:
                archives.extract(root / entry["path"], root)
            except archives.ArchiveRefused as refusal:
                refused.append({"item": item["name"], "reason": refusal.reason, "entry": refusal.entry})
                shutil.rmtree(root, ignore_errors=True)
                break
    return refused


def _stage(folder: Path, record: dict[str, Any]) -> list[str]:
    """Extracts, stages and records each album; returns the album numbers to identify."""
    refused = _extract_archives(folder, record)
    turned_away = {r["item"] for r in refused}
    staging = albums.stage(folder)
    for one in staging.albums:
        drops.write_album(folder / one.n, n=one.n, name=one.name, item=one.item, state="queued", stderr="",
                          error=None)
    record["ignored"] = [asdict(i) for i in staging.ignored if i.item not in turned_away]
    record["refused"] = refused
    record["error"] = None
    drops.write_record(folder, record)
    return [one.n for one in staging.albums]


def done(request: Handler, match: re.Match[str], config: Config) -> None:
    """The page has sent every file: extract, find the albums, and queue identify for each."""
    drop = match.group(1)
    folder = _known(config, drop)
    record = drops.read_record(folder) if folder else None
    if folder is None or record is None:
        request.fail(404, "No such drop.")
        return
    with request.server.finishing:
        record = drops.read_record(folder) or record
        if record.get("done"):
            request.fail(409, "The drop is already finished.")
            return
        listed = sum(len({f["path"] for f in item["files"]}) for item in record["items"])
        received = (drops.read_drop(config, drop) or {"received": {"files": 0, "bytes": 0}})["received"]
        if received["files"] < listed:
            request.fail(409, f"The drop has {received['files']} of its {listed} files.")
            return
        record["done"] = True
        drops.write_record(folder, record)
        log.write("finish-upload", drop, files=received["files"], bytes=received["bytes"])
    request.server.uploading.discard(drop)

    server = request.server
    server.extracting.add(drop)
    try:
        staged = _stage(folder, record)
    except Exception as exc:
        # `raw/` is still there, so the drop lists as `incomplete`; the sentence tells the owner why.
        record["error"] = f"{type(exc).__name__}: {exc}"
        drops.write_record(folder, record)
        log.failed("stage-drop", drop, record["error"])
        request.fail(500, record["error"])
        return
    finally:
        server.extracting.discard(drop)
    log.write("stage-drop", drop, albums=",".join(staged), refused=len(record["refused"]))
    for n in staged:
        server.queue.enqueue(drop, n, "identify")
    request.send_json(202, state.drop(config, drop, server.queue, server.uploading_now(), server.extracting))


def retry(request: Handler, match: re.Match[str], config: Config) -> None:
    _identify_again(request, match, config, RETRYABLE, "retried", "retry")


def reidentify(request: Handler, match: re.Match[str], config: Config) -> None:
    """Identify a ready album again under its own decision, or none, so a changed engine or MusicBrainz shows.

    An album whose apply failed is identified again the same way: a plan
    apply refused as changed is replaced by one made now.
    """
    _identify_again(request, match, config, ("ready", "apply failed"), "identified again", "reidentify")


def _identify_again(request: Handler, match: re.Match[str], config: Config,
                    allowed: tuple[str, ...], verb: str, why: str) -> None:
    drop, n = match.group(1), match.group(2)
    queue = request.server.queue
    found = state.album(config, drop, n, queue) if _known(config, drop) is not None else None
    if found is None:
        request.fail(404, "No such album.")
    elif found["state"] not in allowed or found["busy"]:
        request.fail(409, f"An album that is {found['state']} cannot be {verb}.")
    elif "reidentify" not in found["actions"] and found["state"] == "ready":
        request.fail(409, "This match found no release; discard it.")
    else:
        drops.write_album(config.inbox / drop / n, name=found["name"], state="queued", stderr="", error=None)
        queue.enqueue(drop, n, "identify")
        log.write("queue-identify", f"{drop}/{n}", why=why)
        request.send_json(202, {"state": "queued"})
