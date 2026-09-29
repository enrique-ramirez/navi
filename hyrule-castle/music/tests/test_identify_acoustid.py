"""The AcoustID fallback: when it cannot run, and what it asks for when it can.

Without `fpcalc` or `ACOUSTID_API_KEY` the album is `unidentified` with the
reason. `identify` turns the reason into the album status; the cases here
hold the reason strings themselves.

No more than 3 requests a second, and every response cached so that a warm
cache makes no request.

Nothing here runs the real `fpcalc` or touches the network. `fpcalc` is a
shell script on a temporary PATH that prints a recorded answer, and the
transport is a fake on a clock that only moves when the client sleeps.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import traceback
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import musiclib
from musiclib import acoustid, mb
from musiclib.cache import Cache

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acoustid"
FPCALC = json.loads((FIXTURES / "fpcalc.json").read_text())
LOOKUP = (FIXTURES / "lookup.json").read_bytes()

KEY = "k3yF0rTest5"
DURATION = 262
FINGERPRINT = FPCALC["fingerprint"]


class FakeClock:
    """A monotonic clock that moves only when somebody sleeps on it."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []
        self.reads = 0

    def __call__(self) -> float:
        # A client that polls the clock until the gap has passed, instead of
        # sleeping, would spin here forever, because this clock stands still.
        # Fail it rather than hang the suite.
        self.reads += 1
        if self.reads > 1_000:
            raise AssertionError("the client polled the clock instead of sleeping")
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError(f"sleep length must be non-negative: {seconds}")
        self.sleeps.append(seconds)
        self.now += seconds


class Request(NamedTuple):
    url: str
    headers: dict[str, str]
    started: float


class FakeTransport:
    """Answers from a script, in order, and records every request."""

    def __init__(self, clock: FakeClock, *answers: tuple[int, bytes]) -> None:
        self.clock = clock
        self.answers = list(answers)
        self.requests: list[Request] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(Request(url, dict(headers), self.clock.now))
        if not self.answers:
            raise AssertionError(f"unexpected request: {url}")
        return self.answers.pop(0)


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def installed(name: str) -> str | None:
    return "/usr/bin/fpcalc" if name == "fpcalc" else None


def missing(name: str) -> str | None:
    return None


class Unavailable(unittest.TestCase):
    def test_no_fpcalc_is_the_reason(self) -> None:
        self.assertEqual(
            acoustid.unavailable(env={"ACOUSTID_API_KEY": KEY}, which=missing),
            "fpcalc not installed",
        )

    def test_no_key_is_the_reason(self) -> None:
        self.assertEqual(acoustid.unavailable(env={}, which=installed), "ACOUSTID_API_KEY not set")

    def test_an_empty_key_counts_as_no_key(self) -> None:
        # `ACOUSTID_API_KEY=` in a .env file sets the variable to "", and
        # sending "" to AcoustID fails every lookup instead of saying why.
        self.assertEqual(
            acoustid.unavailable(env={"ACOUSTID_API_KEY": ""}, which=installed),
            "ACOUSTID_API_KEY not set",
        )

    def test_a_whitespace_key_counts_as_no_key(self) -> None:
        # A stray space after `=` in a .env file is the same mistake.
        self.assertEqual(
            acoustid.unavailable(env={"ACOUSTID_API_KEY": " \t"}, which=installed),
            "ACOUSTID_API_KEY not set",
        )

    def test_with_neither_the_missing_fpcalc_is_named(self) -> None:
        self.assertEqual(acoustid.unavailable(env={}, which=missing), "fpcalc not installed")

    def test_with_both_there_is_nothing_in_the_way(self) -> None:
        self.assertIsNone(acoustid.unavailable(env={"ACOUSTID_API_KEY": KEY}, which=installed))

    def test_the_default_looks_for_fpcalc_on_the_real_path(self) -> None:
        # End to end: an empty PATH has no fpcalc, and one holding an
        # executable called fpcalc does.
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as bin_dir:
            stub = Path(bin_dir) / "fpcalc"
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
            env = {"ACOUSTID_API_KEY": KEY}
            with mock.patch.dict(os.environ, {"PATH": empty}):
                self.assertEqual(acoustid.unavailable(env=env), "fpcalc not installed")
            with mock.patch.dict(os.environ, {"PATH": bin_dir}):
                self.assertIsNone(acoustid.unavailable(env=env))


class ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cache_dir = self.root / "cache"
        self.cache_dir.mkdir()
        self.clock = FakeClock()

    def client(self, *answers: tuple[int, bytes], key: str = KEY):
        transport = FakeTransport(self.clock, *answers)
        client = acoustid.AcoustID(
            Cache(self.cache_dir),
            key,
            transport=transport,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        return client, transport


class Fingerprint(ClientTestCase):
    def setUp(self) -> None:
        super().setUp()
        # fpcalc on a PATH of its own: it logs its arguments one per line,
        # adds a line to calls.log each time it runs, and prints whatever
        # answer.json holds at the time.
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.answer = self.root / "answer.json"
        self.answer.write_text(json.dumps(FPCALC))
        self.args = self.root / "args.log"
        self.calls_log = self.root / "calls.log"
        stub = bin_dir / "fpcalc"
        stub.write_text(
            "#!/bin/sh\n"
            f"echo run >> '{self.calls_log}'\n"
            f"printf '%s\\n' \"$@\" >> '{self.args}'\n"
            f"cat '{self.answer}'\n"
        )
        stub.chmod(0o755)
        patch = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patch.start()
        self.addCleanup(patch.stop)
        # An album path as the library has them: spaces, brackets and an
        # apostrophe, which a command built as one shell string gets wrong.
        self.track = self.root / "(1994) The Downward Spiral" / "01 - Mr. Self Destruct's Piggy.flac"
        self.track.parent.mkdir()
        self.track.write_bytes(b"not really audio")

    def test_fpcalc_is_asked_for_json_about_that_one_file(self) -> None:
        self.assertEqual(shutil.which("fpcalc"), str(self.root / "bin" / "fpcalc"))
        client, _ = self.client()
        client.fingerprint(self.track)
        args = self.args.read_text().splitlines()
        self.assertIn("-json", args)
        self.assertIn(str(self.track), args)

    def test_the_duration_and_fingerprint_come_back_as_fpcalc_printed_them(self) -> None:
        # fpcalc prints the duration in fractional seconds, and AcoustID
        # takes whole seconds. 262.2 is 262 however it is rounded.
        client, _ = self.client()
        self.assertEqual(client.fingerprint(self.track), (DURATION, FINGERPRINT))

    def test_the_duration_is_rounded_to_the_nearest_second(self) -> None:
        # 262.6 is 263 rounded and 262 truncated.
        self.answer.write_text(json.dumps({"duration": 262.6, "fingerprint": FINGERPRINT}))
        client, _ = self.client()
        self.assertEqual(client.fingerprint(self.track), (263, FINGERPRINT))

    def test_fpcalc_failing_is_an_acoustid_error(self) -> None:
        # fpcalc exits non-zero on a file it cannot decode. Reading its empty
        # stdout as JSON instead would surface as a ValueError nobody catches.
        stub = self.root / "bin" / "fpcalc"
        stub.write_text("#!/bin/sh\necho 'ERROR: Could not open the input file' >&2\nexit 2\n")
        client, _ = self.client()
        with self.assertRaises(acoustid.AcoustIDError):
            client.fingerprint(self.track)

    def fpcalc_calls(self) -> int:
        return len(self.calls_log.read_text().splitlines()) if self.calls_log.exists() else 0

    def test_a_second_run_over_the_unchanged_file_does_not_run_fpcalc_again(self) -> None:
        # A new client over the same cache directory is the next run of
        # batch identify, picking up where an interrupted one stopped.
        # fpcalc now answering differently shows which answer was used.
        first, _ = self.client()
        self.assertEqual(first.fingerprint(self.track), (DURATION, FINGERPRINT))
        self.answer.write_text(json.dumps({"duration": 180.4, "fingerprint": "AQADchanged"}))
        second, transport = self.client()
        self.assertEqual(second.fingerprint(self.track), (DURATION, FINGERPRINT))
        self.assertEqual(self.fpcalc_calls(), 1)
        self.assertEqual(transport.requests, [])

    def test_a_file_with_a_new_mtime_is_fingerprinted_again(self) -> None:
        # A re-rip or a retag in place keeps the path. A cached fingerprint
        # would then look up a recording the file no longer is.
        client, _ = self.client()
        client.fingerprint(self.track)
        self.answer.write_text(json.dumps({"duration": 180.4, "fingerprint": "AQADchanged"}))
        # Set, not slept for: a filesystem with a coarse clock can give two
        # writes a second apart the same mtime.
        before = self.track.stat()
        os.utime(self.track, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        self.assertEqual(client.fingerprint(self.track), (180, "AQADchanged"))
        self.assertEqual(self.fpcalc_calls(), 2)

    def test_a_file_with_a_new_size_and_the_same_mtime_is_fingerprinted_again(self) -> None:
        # A copy that keeps timestamps, rsync -t or cp -p, changes the
        # content and leaves the mtime where it was.
        client, _ = self.client()
        client.fingerprint(self.track)
        self.answer.write_text(json.dumps({"duration": 180.4, "fingerprint": "AQADchanged"}))
        before = self.track.stat()
        self.track.write_bytes(b"not really audio, and longer now")
        os.utime(self.track, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(client.fingerprint(self.track), (180, "AQADchanged"))
        self.assertEqual(self.fpcalc_calls(), 2)

    def test_two_files_of_the_same_size_and_mtime_are_fingerprinted_once_each(self) -> None:
        # Tracks copied from one rip can share both, so the path has to be
        # part of what a fingerprint is stored under.
        other = self.track.with_name("02 - Piggy.flac")
        other.write_bytes(self.track.read_bytes())
        stat_ = self.track.stat()
        os.utime(other, ns=(stat_.st_atime_ns, stat_.st_mtime_ns))
        client, _ = self.client()
        client.fingerprint(self.track)
        self.answer.write_text(json.dumps({"duration": 180.4, "fingerprint": "AQADchanged"}))
        self.assertEqual(client.fingerprint(other), (180, "AQADchanged"))
        self.assertEqual(self.fpcalc_calls(), 2)

    def test_a_failing_fpcalc_leaves_nothing_cached_and_the_next_call_runs_it_again(self) -> None:
        # A file fpcalc could not decode this time is asked about again next
        # time, not answered from a stored failure.
        stub = self.root / "bin" / "fpcalc"
        working = stub.read_text()
        stub.write_text(f"#!/bin/sh\necho run >> '{self.calls_log}'\n"
                        "echo 'ERROR: Could not open the input file' >&2\nexit 2\n")
        client, _ = self.client()
        with self.assertRaises(acoustid.AcoustIDError):
            client.fingerprint(self.track)
        stub.write_text(working)
        self.assertEqual(client.fingerprint(self.track), (DURATION, FINGERPRINT))
        self.assertEqual(self.fpcalc_calls(), 2)


class Lookup(ClientTestCase):
    def test_a_lookup_sends_the_key_duration_and_fingerprint_and_asks_for_recordings_with_release_ids(self) -> None:
        # `releaseids` is what puts the release MBIDs in the answer, so the
        # fallback never has to ask MusicBrainz about each recording.
        # AcoustID reads `meta` as words separated by spaces, which arrive
        # as `+` or `%20`; either decodes the same here.
        client, transport = self.client((200, LOOKUP))
        client.lookup(DURATION, FINGERPRINT)
        [request] = transport.requests
        url = urlsplit(request.url)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "api.acoustid.org", "/v2/lookup"))
        sent = query(request.url)
        meta = sent.pop("meta", "")
        self.assertEqual(sent, {"client": KEY, "duration": str(DURATION), "fingerprint": FINGERPRINT})
        self.assertEqual(sorted(meta.split()), ["recordings", "releaseids"])

    def test_it_identifies_itself_as_musiclib(self) -> None:
        # The seam sends the same User-Agent as the MusicBrainz client.
        # Header names are case-insensitive, so only the value is held.
        client, transport = self.client((200, LOOKUP))
        client.lookup(DURATION, FINGERPRINT)
        [request] = transport.requests
        agents = [v for k, v in request.headers.items() if k.lower() == "user-agent"]
        self.assertEqual(len(agents), 1)
        self.assertIn(f"musiclib/{musiclib.__version__}", agents[0])
        self.assertIn("hello@enrique-ramirez.com", agents[0])

    # What `lookup` hands back is between it and identify. Which releases a
    # track contributes (criterion 15) is held further down, through
    # identify, so it holds wherever the builder puts the rule.

    def test_an_error_in_a_200_body_is_an_acoustid_error(self) -> None:
        client, _ = self.client((200, b'{"status": "error", "error": {"code": 3, "message": "invalid fingerprint"}}'))
        with self.assertRaises(acoustid.AcoustIDError):
            client.lookup(DURATION, FINGERPRINT)

    def test_an_error_status_raises_and_is_not_cached(self) -> None:
        # 400 is what AcoustID answers for a bad key. Caching it would keep
        # failing after the key is fixed.
        client, _ = self.client((400, b'{"status": "error", "error": {"code": 4, "message": "invalid API key"}}'))
        with self.assertRaises(acoustid.AcoustIDError):
            client.lookup(DURATION, FINGERPRINT)
        later, transport = self.client((200, LOOKUP))
        later.lookup(DURATION, FINGERPRINT)
        self.assertEqual(len(transport.requests), 1)


    def test_an_acoustid_error_never_carries_the_key(self) -> None:
        # The message lands in the run's output and the album's reason, and
        # the request URL it would name holds `client=<key>`. The whole
        # formatted exception is checked, chained causes included, since
        # that is what a traceback on the terminal shows.
        answers = {
            "bad key": (400, b'{"status": "error", "error": {"code": 4, "message": "invalid API key"}}'),
            "server error": (500, b"<html>500 Internal Server Error</html>"),
            "error in a 200": (200, b'{"status": "error", "error": {"code": 3, "message": "invalid fingerprint"}}'),
        }
        for name, answer in answers.items():
            with self.subTest(name):
                client, _ = self.client(answer)
                with self.assertRaises(acoustid.AcoustIDError) as raised:
                    client.lookup(DURATION, FINGERPRINT)
                shown = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(KEY, shown)

class RateLimit(ClientTestCase):
    def test_no_more_than_three_requests_a_second(self) -> None:
        client, transport = self.client(*[(200, LOOKUP)] * 4)
        for duration in (100, 101, 102, 103):
            client.lookup(duration, FINGERPRINT)
        starts = [r.started for r in transport.requests]
        self.assertEqual(len(starts), 4)
        # A third of a second is not exact in floating point, so a client
        # that waits exactly 1/3 s can land a hair under it.
        for earlier, later in zip(starts, starts[1:]):
            self.assertGreaterEqual(later - earlier, 1 / 3 - 1e-9)
        # And four requests never fit in one second, whatever the rounding.
        self.assertGreaterEqual(starts[3] - starts[0], 1.0 - 1e-9)


class Cached(ClientTestCase):
    def test_a_warm_cache_answers_without_a_request_or_a_wait(self) -> None:
        cold, _ = self.client((200, LOOKUP))
        answer = cold.lookup(DURATION, FINGERPRINT)
        self.assertTrue(answer)
        self.clock = FakeClock()
        warm, transport = self.client()
        self.assertEqual(warm.lookup(DURATION, FINGERPRINT), answer)
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_a_new_key_still_finds_what_the_old_one_cached(self) -> None:
        # The key is a secret and gets rotated. Neither should cost the
        # whole cache.
        cold, _ = self.client((200, LOOKUP))
        answer = cold.lookup(DURATION, FINGERPRINT)
        self.assertTrue(answer)
        warm, transport = self.client(key="aN0therKey")
        self.assertEqual(warm.lookup(DURATION, FINGERPRINT), answer)
        self.assertEqual(transport.requests, [])

    def test_the_key_never_appears_in_the_cache_directory(self) -> None:
        # Filenames and contents both: the cache directory is not a secret.
        client, _ = self.client((200, LOOKUP))
        client.lookup(DURATION, FINGERPRINT)
        stored = list(self.cache_dir.rglob("*"))
        self.assertNotEqual(stored, [])
        for path in stored:
            with self.subTest(path=path.name):
                self.assertNotIn(KEY, str(path.relative_to(self.cache_dir)))
                if path.is_file():
                    self.assertNotIn(KEY.encode(), path.read_bytes())

    def test_a_different_fingerprint_or_duration_is_a_different_lookup(self) -> None:
        # Dropping `client` from the cache key must drop only that.
        cold, _ = self.client((200, LOOKUP))
        cold.lookup(DURATION, FINGERPRINT)
        empty = (200, b'{"status": "ok", "results": []}')
        other, transport = self.client(empty, empty)
        other.lookup(DURATION, FINGERPRINT + "x")
        other.lookup(DURATION + 1, FINGERPRINT)
        self.assertEqual(len(transport.requests), 2)


# --- identify falling back to fingerprints (003 criteria 2 and 15) ----------


# The Downward Spiral's first ten tracks as files: title tag and seconds.
TITLES = [
    ("Mr. Self Destruct", 270), ("Piggy", 264), ("Heresy", 234), ("March of the Pigs", 178),
    ("Closer", 373), ("Ruiner", 298), ("The Becoming", 331), ("I Do Not Want This", 341),
    ("Big Man with a Gun", 96), ("A Warm Place", 202),
]


def best(*releases: str, score: float = 0.9) -> tuple[float, list[list[str]]]:
    """One AcoustID result at `score`: a single recording, released on `releases`."""
    return score, [list(releases)]


class Lookups:
    """AcoustID answering by track number: `fpcalc` below fingerprints `03. Heresy.flac` as `FP-03. Heresy.flac`.

    `answers` maps a track number to its results, each `(score, recordings)`
    with every recording given as the release MBIDs it is on, listed in the
    order given. A track not in it is a fingerprint nobody has linked yet.
    Release IDs come back only when the request asks for `releaseids`, as
    on AcoustID, so a client that forgets to ask gets none.
    """

    def __init__(self, answers: dict[int, list[tuple[float, list[list[str]]]]]) -> None:
        self.answers = answers
        self.requests: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        sent = query(url)
        with_releases = "releaseids" in sent.get("meta", "").split()
        number = int(sent["fingerprint"].removeprefix("FP-")[:2])
        results = []
        for n, (score, recordings) in enumerate(self.answers.get(number, [])):
            listed = []
            for m, releases in enumerate(recordings):
                recording: dict = {"id": f"c{number:02d}{n}{m}0000-0000-4000-8000-000000000000"}
                if with_releases:
                    recording["releases"] = [{"id": r} for r in releases]
                listed.append(recording)
            results.append({"id": f"result-{number}-{n}", "score": score, "recordings": listed})
        return 200, json.dumps({"status": "ok", "results": results}).encode()


class IdentifyByFingerprint(unittest.TestCase):
    """What identify does when the search finds nothing with the files' track counts.

    MusicBrainz is the fake server from tests.test_identify. It is imported
    here rather than at the top because it imports musiclib.identify, and
    the client cases above do not need that to exist.
    """

    def setUp(self) -> None:
        from tests import test_identify as fakes
        from musiclib.identify import identify

        self.fakes = fakes
        self.mbid = fakes.mbid
        self._identify = identify
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.album(3)
        # fpcalc logs the file it was asked about and names the fingerprint
        # after it, so each file can be looked up as something different.
        self.fpcalc_log = self.root / "fpcalc.log"
        self.fpcalc = self.root / "bin" / "fpcalc"
        self.fpcalc.parent.mkdir()
        self.fpcalc.write_text(
            "#!/bin/sh\n"
            "for last; do :; done\n"
            f"printf '%s\\n' \"$last\" >> '{self.fpcalc_log}'\n"
            "printf '{\"duration\": 200.4, \"fingerprint\": \"FP-%s\"}\\n' \"$(basename \"$last\")\"\n"
        )
        self.fpcalc.chmod(0o755)

    def album(self, count: int) -> None:
        """The first `count` of TITLES as the album under test, on disk as a scanned album is."""
        folder = self.root / "N" / "Nine Inch Nails" / "(1994) The Downward Spiral"
        self.unit = self.fakes.unit(folder, [
            self.fakes.vorbis(folder, f"{n:02d}. {title}.flac", length, tracknumber=str(n), title=title,
                              album="The Downward Spiral", albumartist="Nine Inch Nails", artist="Nine Inch Nails")
            for n, (title, length) in enumerate(TITLES[:count], start=1)
        ])
        # The client stats a file before it fingerprints it.
        folder.mkdir(parents=True, exist_ok=True)
        for track in self.unit.tracks:
            Path(track.path).touch()

    def release(self, key: str, tracks=None, **fields) -> dict:
        """A one-medium release as MusicBrainz has it, by default exactly the album's files."""
        return self.fakes.titled_json(self.mbid(key), tracks or TITLES[:len(self.unit.tracks)], **fields)

    def which(self, name: str) -> str | None:
        return str(self.fpcalc) if name == "fpcalc" else None

    def identify(self, server, answers: dict | None = None, *,
                 env: dict[str, str] | None = None, which=None, with_acoustid: bool = True):
        lookups = Lookups(answers or {})
        acoustid_clock = FakeClock()
        (self.root / "acoustid-cache").mkdir(exist_ok=True)
        (self.root / "mb-cache").mkdir(exist_ok=True)
        client = acoustid.AcoustID(Cache(self.root / "acoustid-cache"), KEY, transport=lookups, clock=acoustid_clock,
                                   sleep=acoustid_clock.sleep, fpcalc=str(self.fpcalc))
        mb_clock = self.fakes.FakeClock()
        musicbrainz = mb.MusicBrainz(Cache(self.root / "mb-cache"), transport=server,
                                     clock=mb_clock, sleep=mb_clock.sleep)
        result = self._identify(
            self.unit, musicbrainz, acoustid=client if with_acoustid else None,
            env={"ACOUSTID_API_KEY": KEY} if env is None else env, which=which or self.which,
        )
        return result, lookups

    def fpcalc_ran(self) -> bool:
        return self.fpcalc_log.exists()

    def test_without_fpcalc_or_a_key_the_album_is_unidentified_with_the_reason(self) -> None:
        for env, which, reason in (({"ACOUSTID_API_KEY": KEY}, missing, "fpcalc not installed"),
                                   ({}, self.which, "ACOUSTID_API_KEY not set")):
            with self.subTest(reason):
                server = self.fakes.Server(search=self.fakes.search_json())
                result, lookups = self.identify(server, env=env, which=which)
                self.assertEqual((result.status, result.reason), ("unidentified", reason))
                self.assertEqual(lookups.requests, [])
                self.assertFalse(self.fpcalc_ran())

    def test_without_an_acoustid_client_the_album_is_unidentified_with_no_match(self) -> None:
        server = self.fakes.Server(search=self.fakes.search_json())
        result, _ = self.identify(server, with_acoustid=False)
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))

    def test_a_count_match_in_the_search_means_no_fingerprinting(self) -> None:
        # Track 1 20 s off is `review`, and still a count match: the owner
        # picks from the search, and AcoustID is not asked.
        close = self.release("a1", [("Mr. Self Destruct", 290), *TITLES[1:3]])
        server = self.fakes.Server(search=self.fakes.search_json(close), releases=(close,))
        result, lookups = self.identify(server, {n: [best(self.mbid("a1"))] for n in (1, 2, 3)})
        self.assertEqual(result.status, "review")
        self.assertEqual(lookups.requests, [])
        self.assertFalse(self.fpcalc_ran())

    def test_a_fingerprint_match_that_fits_is_auto(self) -> None:
        # The search found the album only with the wrong track count. The
        # fingerprints find a release every file fits. 001 held every
        # fingerprint match for a person; criterion 2 lets one that fits
        # through, as it would from a search.
        short = self.release("b1", TITLES[:2])
        exact = self.release("a1")
        server = self.fakes.Server(search=self.fakes.search_json(short), releases=(exact,))
        result, _ = self.identify(server, {n: [best(self.mbid("a1"))] for n in (1, 2, 3)})
        self.assertEqual(result.status, "auto")
        self.assertEqual([(c.release_id, c.release) for c in result.candidates[:1]], [(self.mbid("a1"), exact)])

    def test_a_fingerprint_match_whose_track_3_title_differs_is_review(self) -> None:
        # Every length is exact, so only the title check can hold it.
        other = self.release("a1", [*TITLES[:2], ("Hurt", 234)])
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(other,))
        result, _ = self.identify(server, {n: [best(self.mbid("a1"))] for n in (1, 2, 3)})
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates], [self.mbid("a1")])

    def test_a_fitting_fingerprint_match_on_a_soundtrack_is_still_held(self) -> None:
        # Criterion 2 lets a fingerprint match be `auto`, and the soundtrack
        # hold still runs after it: nothing on the files says game, so the
        # owner has to choose (003 criterion 57).
        exact = self.release("a1")
        server = self.fakes.Server(
            search=self.fakes.search_json(), releases=(exact,),
            release_groups=(self.fakes.release_group_json(secondary_types=("Soundtrack",)),),
        )
        result, _ = self.identify(server, {n: [best(self.mbid("a1"))] for n in (1, 2, 3)})
        self.assertEqual((result.status, result.reason), ("review", "soundtrack choice"))

    def test_release_ids_come_from_acoustid_and_no_recording_is_looked_up_on_musicbrainz(self) -> None:
        # One MusicBrainz request per recording was a request a second per
        # track on a long album. The release is still fetched, which shows
        # the path ran and found it through AcoustID alone.
        exact = self.release("a1")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact,))
        self.identify(server, {n: [best(self.mbid("a1"))] for n in (1, 2, 3)})
        self.assertEqual([u for u in server.urls if "/recording" in urlsplit(u).path], [])
        self.assertEqual(server.fetched(), [self.mbid("a1")])

    def test_the_musicbrainz_client_no_longer_looks_up_a_recordings_releases(self) -> None:
        self.assertFalse(hasattr(mb.MusicBrainz, "recording_releases"))

    def test_a_best_result_under_0_5_contributes_no_release(self) -> None:
        # a1 fits every file. Track 1's best result puts it there at 0.9;
        # tracks 2 and 3 have it only at 0.4 and, lower still, 0.3. Counted,
        # a1 would be on all three tracks; ignored, it is on one in three.
        exact = self.release("a1")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact,))
        weak = [best(self.mbid("a1"), score=0.3), best(self.mbid("a1"), score=0.4)]
        result, _ = self.identify(server, {1: [best(self.mbid("a1"))], 2: weak, 3: weak})
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))
        self.assertEqual(server.fetched(), [])

    def test_a_best_result_of_exactly_0_5_counts(self) -> None:
        # "At least 0.5". With track 2 counted a1 is on two tracks of three,
        # over 60%; without it, one of three.
        exact = self.release("a1")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact,))
        result, _ = self.identify(server, {1: [best(self.mbid("a1"))], 2: [best(self.mbid("a1"), score=0.5)]})
        self.assertEqual(server.fetched(), [self.mbid("a1")])
        self.assertEqual(result.status, "auto")

    def test_only_the_best_result_of_each_track_counts_not_the_others_above_0_5(self) -> None:
        # b2 is on every track at 0.8, a strong result that is still not the
        # best, and is listed first so taking the first result gets it too.
        exact = self.release("a1")
        other = self.release("b2")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact, other))
        answer = [best(self.mbid("b2"), score=0.8), best(self.mbid("a1"), score=0.9)]
        result, _ = self.identify(server, {n: answer for n in (1, 2, 3)})
        self.assertEqual(server.fetched(), [self.mbid("a1")])
        self.assertEqual(result.status, "auto")

    def test_of_ten_tracks_a_release_on_seven_is_fetched_and_one_on_six_is_not(self) -> None:
        # Criterion 15's example. Tracks 8 to 10 have no result at all and
        # still count in the ten: out of the seven tracks that answered, b2
        # would be on six, well over 60%. Six of ten is 60% exactly, which
        # is not more than 60%.
        self.album(10)
        exact = self.release("a1")
        other = self.release("b2")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact, other))
        answers = {1: [best(self.mbid("a1"))]}
        answers.update({n: [best(self.mbid("a1"), self.mbid("b2"))] for n in range(2, 8)})
        result, _ = self.identify(server, answers)
        self.assertEqual(server.fetched(), [self.mbid("a1")])
        self.assertEqual(result.status, "auto")

    def test_a_release_on_two_recordings_of_one_track_counts_once_for_that_track(self) -> None:
        # AcoustID often links one fingerprint to several recordings of the
        # same song, all on the same release. Counted per recording, a1
        # would be on two of three tracks from track 1 alone.
        exact = self.release("a1")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact,))
        twice = (0.9, [[self.mbid("a1")], [self.mbid("a1")]])
        result, _ = self.identify(server, {1: [twice]})
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))
        self.assertEqual(server.fetched(), [])

    def test_no_release_on_more_than_60_percent_of_the_tracks_leaves_the_album_unidentified_with_no_match(self) -> None:
        exact = self.release("a1")
        other = self.release("b2")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(exact, other))
        result, lookups = self.identify(server, {1: [best(self.mbid("a1"))], 2: [best(self.mbid("b2"))]})
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))
        self.assertEqual(server.fetched(), [])
        self.assertNotEqual(lookups.requests, [])

    def test_no_result_for_any_track_leaves_the_album_unidentified_with_no_match(self) -> None:
        server = self.fakes.Server(search=self.fakes.search_json())
        result, lookups = self.identify(server, {})
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))
        self.assertEqual(result.candidates, [])
        self.assertNotEqual(lookups.requests, [])

    def test_releases_are_proposed_once_each_and_ranked_as_a_search_ranks_them(self) -> None:
        # Nothing fits, so the ranking is all a person sees. Every track's
        # best result lists all four, in an order that is neither the rank
        # nor MBID order. c3 fails one pair, on its title. b2 and a1 fail two
        # each: b2 on titles with exact lengths, a1 on lengths 16 s off. 0f
        # is a track short.
        releases = [
            self.release("b2", [("Mr. Self Destruct", 270), ("Closer", 264), ("March of the Pigs", 234)]),
            self.release("0f", TITLES[:2]),
            self.release("c3", [("Mr. Self Destruct", 284), ("Piggy", 278), ("March of the Pigs", 248)]),
            self.release("a1", [("Mr. Self Destruct", 286), ("Piggy", 280), ("Heresy", 234)]),
        ]
        server = self.fakes.Server(search=self.fakes.search_json(), releases=tuple(releases))
        result, _ = self.identify(server, {n: [best(*(r["id"] for r in releases))] for n in (1, 2, 3)})
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates],
                         [self.mbid("c3"), self.mbid("b2"), self.mbid("a1"), self.mbid("0f")])

    def test_a_fitting_release_with_no_track_lengths_is_not_ranked_last_for_it(self) -> None:
        # Both fit, on the same date. b2 has no lengths at all, so there is
        # nothing to compare and its difference is 0, as on the search path.
        # a1 is 2 s off on track 2. Ranked as the worst possible difference,
        # b2's missing lengths put it behind a1, and so does MBID order.
        untimed = self.release("b2", [(title, None) for title, _ in TITLES[:3]])
        timed = self.release("a1", [TITLES[0], ("Piggy", 266), TITLES[2]])
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(untimed, timed))
        on = best(self.mbid("a1"), self.mbid("b2"))
        result, _ = self.identify(server, {n: [on] for n in (1, 2, 3)})
        self.assertEqual(result.status, "auto")
        self.assertEqual([(c.release_id, c.duration_diff) for c in result.candidates],
                         [(self.mbid("b2"), 0.0), (self.mbid("a1"), 2.0)])

    def test_among_fingerprint_matches_that_fit_the_official_one_is_chosen_over_older_ones(self) -> None:
        # Criterion 6 on this path. The Bootleg and the Promotion are older
        # and rank higher, so oldest-first or rank-first each pick one of them.
        bootleg = self.release("a1", date="1993-05-01", status="Bootleg")
        promotion = self.release("b2", [("Mr. Self Destruct", 270.5), *TITLES[1:3]],
                                 date="1993-02-01", status="Promotion")
        official = self.release("c3", [("Mr. Self Destruct", 271), *TITLES[1:3]], date="1994-03-08")
        server = self.fakes.Server(search=self.fakes.search_json(), releases=(bootleg, promotion, official))
        on = best(self.mbid("a1"), self.mbid("b2"), self.mbid("c3"))
        result, _ = self.identify(server, {n: [on] for n in (1, 2, 3)})
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.candidates[0].release_id, self.mbid("c3"))


if __name__ == "__main__":
    unittest.main()
