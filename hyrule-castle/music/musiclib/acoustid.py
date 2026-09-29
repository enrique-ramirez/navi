"""The AcoustID fallback: fingerprinting locally, looking up on AcoustID.

Without `fpcalc` on `PATH` or `ACOUSTID_API_KEY` set, an album cannot be
identified this way at all, and `unavailable` names why before anything is
attempted. No more than 3 requests a second, and every lookup response
cached like a MusicBrainz one. A file's fingerprint is cached too, keyed by
its resolved path together with its size and mtime, so a file rewritten in
place (a re-rip, a retag) is fingerprinted again instead of answering for
audio that is no longer there.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote

from musiclib import mb
from musiclib.cache import Cache

_BASE = "https://api.acoustid.org/v2/lookup"
_MIN_INTERVAL = 1 / 3
_MIN_SCORE = 0.5


class AcoustIDError(Exception):
    """AcoustID answered with an error, or `fpcalc` failed to run."""


def unavailable(
    env: Mapping[str, str] = os.environ,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Why AcoustID identification cannot run here, or `None` if it can.

    `fpcalc` is checked first: with neither in place, that is the more basic
    thing missing, and the one line worth telling the caller.
    """
    if which("fpcalc") is None:
        return "fpcalc not installed"
    if not env.get("ACOUSTID_API_KEY", "").strip():
        return "ACOUSTID_API_KEY not set"
    return None


class AcoustID:
    """Fingerprints a file with `fpcalc` and looks up releases on AcoustID."""

    def __init__(
        self,
        cache: Cache,
        key: str,
        transport: mb.Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        fpcalc: str = "fpcalc",
    ) -> None:
        self.cache = cache
        self.key = key
        # Same shape and default as musiclib.mb, so tests need only fake one.
        self.transport = transport or mb.default_transport
        self.fpcalc = fpcalc
        self._throttle = mb.Throttle(clock, sleep)

    def fingerprint(self, path: Path) -> tuple[int, str]:
        """`path`'s duration and fingerprint, from the cache if its size and mtime still match.

        Keyed on the resolved path, not the one given: two different-looking
        paths to the same file must not fingerprint it twice, and two calls
        with an unresolved and a resolved path for the same file must agree.
        `fpcalc` itself is still run on `path` exactly as given, since that
        is what the caller meant fpcalc to see.
        """
        path = Path(path)
        info = path.stat()
        cache_url = f"fpcalc:{path.resolve()}?size={info.st_size}&mtime_ns={info.st_mtime_ns}"

        def run() -> bytes:
            # A list of arguments, never a shell string: album paths carry
            # spaces, brackets and apostrophes that a shell would need
            # escaping for.
            result = subprocess.run(
                [self.fpcalc, "-json", str(path)], capture_output=True, text=True
            )
            if result.returncode != 0:
                raise AcoustIDError(f"fpcalc failed on {path}: {result.stderr.strip()}")
            data = json.loads(result.stdout)
            return json.dumps({"duration": round(data["duration"]), "fingerprint": data["fingerprint"]}).encode()

        data = json.loads(self.cache.fetch(cache_url, run))
        return data["duration"], data["fingerprint"]

    def lookup(self, duration: int, fingerprint: str) -> list[str]:
        """Release MBIDs of the best result for `duration`/`fingerprint`, sorted.

        The cache key drops `client`: it is a secret that gets rotated, and
        neither rotating it nor the cache directory itself should carry it.
        """
        enc_fp = quote(fingerprint, safe="")
        tail = f"duration={duration}&fingerprint={enc_fp}&meta=recordings+releaseids"
        cache_url = f"{_BASE}?{tail}"
        request_url = f"{_BASE}?client={quote(self.key, safe='')}&{tail}"

        def fetch() -> bytes:
            self._throttle.hold(_MIN_INTERVAL)
            status, body = self.transport(request_url, {"User-Agent": mb.USER_AGENT})
            # `cache_url` names the request without exposing `client`: the
            # key is a secret that gets rotated, and it must never land in a
            # run's output or a stored reason by way of this message.
            if status != 200:
                raise AcoustIDError(f"acoustid: {cache_url} -> {status}")
            if json.loads(body).get("status") != "ok":
                raise AcoustIDError(f"acoustid: {body!r}")
            return body

        body = self.cache.fetch(cache_url, fetch)
        return _best_releases(json.loads(body))


def _best_releases(data: dict) -> list[str]:
    scored = [r for r in data.get("results", []) if r.get("recordings")]
    if not scored:
        return []
    top = max(r.get("score", 0) for r in scored)
    if top < _MIN_SCORE:
        return []
    releases = {
        release["id"]
        for result in scored
        if result.get("score", 0) == top
        for recording in result["recordings"]
        for release in recording.get("releases", [])
    }
    return sorted(releases)
