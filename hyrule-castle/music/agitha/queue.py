"""One musiclib process at a time, for every album of every drop, and the routes that feed it.

`Queue` keeps its work in memory. What survives a restart is `album.json`,
which `state.read` reconciles with the disk.
"""

from __future__ import annotations

import queue as fifo
import re
import shutil
import subprocess
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import albums, approve, archives, drops, state

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


class Queue:
    """FIFO of `(drop, n, command)`, worked off by one daemon thread that starts with the first `enqueue`."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._work: fifo.Queue[tuple[str, str, str]] = fifo.Queue()
        self._lock = threading.Lock()
        self._busy: set[tuple[str, str]] = set()
        self._running: tuple[str, str] | None = None
        self._thread: threading.Thread | None = None

    def enqueue(self, drop: str, n: str, command: str) -> bool:
        """Queues `command` (`identify` or `apply`) for the album; False where it is already queued or running."""
        with self._lock:
            if (drop, n) in self._busy:
                return False
            self._busy.add((drop, n))
            self._work.put((drop, n, command))
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="agitha-queue", daemon=True)
                self._thread.start()
        return True

    def running(self, drop: str, n: str) -> bool:
        return self._running == (drop, n)

    def busy(self, drop: str, n: str) -> bool:
        """Queued or running."""
        return (drop, n) in self._busy

    def busy_drop(self, drop: str) -> bool:
        with self._lock:
            return any(d == drop for d, _ in self._busy)

    def _loop(self) -> None:
        while True:
            drop, n, command = self._work.get()
            self._running = (drop, n)
            try:
                self._run(drop, n, command)
            except Exception as exc:
                # One album's failure must not end the worker: the albums behind it would stay busy for good.
                self._fail(drop, n, command, exc)
            finally:
                self._running = None
                with self._lock:
                    self._busy.discard((drop, n))

    def _fail(self, drop: str, n: str, command: str, exc: Exception) -> None:
        text = f"{type(exc).__name__}: {exc}"
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
            added = added_stamp(drops.read_record(config.inbox / drop))
            return [config.musiclib, "batch", "identify", str(config.inbox / drop / n), "--job", job,
                    *(["--added", added] if added else [])]
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
        elif state.plan_entry(self.config, drop, n) is not None:
            # A refused decision leaves the earlier plan in place and says why on the album.
            drops.write_album(folder, state="ready", stderr="", error=tail if code else None)
        else:
            error = f"identify exited with status {code}" if code else "identify left no album in its plan"
            drops.write_album(folder, state="identify failed", stderr=tail, error=error)


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
        received = (drops.read_drop(config, drop) or {"received": {"files": 0}})["received"]["files"]
        if received < listed:
            request.fail(409, f"The drop has {received} of its {listed} files.")
            return
        record["done"] = True
        drops.write_record(folder, record)
    request.server.uploading.discard(drop)

    server = request.server
    server.extracting.add(drop)
    try:
        staged = _stage(folder, record)
    except Exception as exc:
        # `raw/` is still there, so the drop lists as `incomplete`; the sentence tells the owner why.
        record["error"] = f"{type(exc).__name__}: {exc}"
        drops.write_record(folder, record)
        request.fail(500, record["error"])
        return
    finally:
        server.extracting.discard(drop)
    for n in staged:
        server.queue.enqueue(drop, n, "identify")
    request.send_json(202, state.drop(config, drop, server.queue, server.uploading_now(), server.extracting))


def retry(request: Handler, match: re.Match[str], config: Config) -> None:
    _identify_again(request, match, config, RETRYABLE, "retried")


def reidentify(request: Handler, match: re.Match[str], config: Config) -> None:
    """Identify a ready album again under its own decision, or none, so a changed engine or MusicBrainz shows."""
    _identify_again(request, match, config, ("ready",), "identified again")


def _identify_again(request: Handler, match: re.Match[str], config: Config,
                    allowed: tuple[str, ...], verb: str) -> None:
    drop, n = match.group(1), match.group(2)
    queue = request.server.queue
    found = state.album(config, drop, n, queue) if _known(config, drop) is not None else None
    if found is None:
        request.fail(404, "No such album.")
    elif found["state"] not in allowed or found["busy"]:
        request.fail(409, f"An album that is {found['state']} cannot be {verb}.")
    else:
        drops.write_album(config.inbox / drop / n, name=found["name"], state="queued", stderr="", error=None)
        queue.enqueue(drop, n, "identify")
        request.send_json(202, {"state": "queued"})
