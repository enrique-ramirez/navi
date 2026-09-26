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

# lookup.json in score order, ties broken by MBID. The file lists them in an
# order that neither sorting the MBIDs nor keeping the file's order produces,
# so only ranking by score gets this.
RANKED = [
    "c3e9d4f6-2a7b-4c8d-8e1f-2a3b4c5d6e7f",  # 0.97, the smaller MBID of the pair
    "f9e8d7c6-0000-4000-8000-000000000002",  # 0.97
    "d4f0e5a7-3b8c-4d9e-9f2a-3b4c5d6e7f80",  # 0.63
    "a0c1e2f3-0000-4000-8000-000000000001",  # 0.41
]


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
        # fpcalc on a PATH of its own: it logs its arguments one per line and
        # prints whatever answer.json holds at the time it runs.
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.answer = self.root / "answer.json"
        self.answer.write_text(json.dumps(FPCALC))
        self.args = self.root / "args.log"
        stub = bin_dir / "fpcalc"
        stub.write_text(
            "#!/bin/sh\n"
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

    def test_fingerprinting_is_local_and_never_cached(self) -> None:
        # The file on disk can change between two runs, and a stored
        # fingerprint would then look up a recording the file no longer is.
        client, transport = self.client()
        client.fingerprint(self.track)
        self.answer.write_text(json.dumps({"duration": 180.4, "fingerprint": "AQADchanged"}))
        self.assertEqual(client.fingerprint(self.track), (180, "AQADchanged"))
        self.assertEqual(transport.requests, [])
        self.assertEqual(list(self.cache_dir.iterdir()), [])


class Lookup(ClientTestCase):
    def test_a_lookup_sends_the_key_duration_and_fingerprint_and_asks_for_recordings(self) -> None:
        client, transport = self.client((200, LOOKUP))
        client.lookup(DURATION, FINGERPRINT)
        [request] = transport.requests
        url = urlsplit(request.url)
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "api.acoustid.org", "/v2/lookup"))
        self.assertEqual(
            query(request.url),
            {"client": KEY, "duration": str(DURATION), "fingerprint": FINGERPRINT, "meta": "recordings"},
        )

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

    def test_recordings_come_back_best_score_first_ties_by_mbid(self) -> None:
        # A result with no recordings (AcoustID has fingerprints nobody has
        # linked yet) contributes nothing.
        client, _ = self.client((200, LOOKUP))
        self.assertEqual(client.lookup(DURATION, FINGERPRINT), RANKED)

    def test_a_recording_under_two_results_comes_back_once_at_its_better_score(self) -> None:
        # The file lists the weaker result first, so keeping the first
        # occurrence puts the recording below one it outscores.
        twice = json.dumps({"status": "ok", "results": [
            {"id": "r1", "score": 0.5, "recordings": [{"id": "b0000000-0000-4000-8000-000000000001"}]},
            {"id": "r2", "score": 0.7, "recordings": [{"id": "a0000000-0000-4000-8000-000000000002"}]},
            {"id": "r3", "score": 0.9, "recordings": [{"id": "b0000000-0000-4000-8000-000000000001"}]},
        ]}).encode()
        client, _ = self.client((200, twice))
        self.assertEqual(
            client.lookup(DURATION, FINGERPRINT),
            ["b0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002"],
        )

    def test_an_error_in_a_200_body_is_an_acoustid_error(self) -> None:
        client, _ = self.client((200, b'{"status": "error", "error": {"code": 3, "message": "invalid fingerprint"}}'))
        with self.assertRaises(acoustid.AcoustIDError):
            client.lookup(DURATION, FINGERPRINT)

    def test_no_results_is_an_empty_list(self) -> None:
        client, _ = self.client((200, b'{"status": "ok", "results": []}'))
        self.assertEqual(client.lookup(DURATION, FINGERPRINT), [])

    def test_an_error_status_raises_and_is_not_cached(self) -> None:
        # 400 is what AcoustID answers for a bad key. Caching it would keep
        # failing after the key is fixed.
        client, _ = self.client((400, b'{"status": "error", "error": {"code": 4, "message": "invalid API key"}}'))
        with self.assertRaises(acoustid.AcoustIDError):
            client.lookup(DURATION, FINGERPRINT)
        later, transport = self.client((200, LOOKUP))
        self.assertEqual(later.lookup(DURATION, FINGERPRINT), RANKED)
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
        cold.lookup(DURATION, FINGERPRINT)
        self.clock = FakeClock()
        warm, transport = self.client()
        self.assertEqual(warm.lookup(DURATION, FINGERPRINT), RANKED)
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_a_new_key_still_finds_what_the_old_one_cached(self) -> None:
        # The key is a secret and gets rotated. Neither should cost the
        # whole cache.
        cold, _ = self.client((200, LOOKUP))
        cold.lookup(DURATION, FINGERPRINT)
        warm, transport = self.client(key="aN0therKey")
        self.assertEqual(warm.lookup(DURATION, FINGERPRINT), RANKED)
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
        self.assertEqual(other.lookup(DURATION, FINGERPRINT + "x"), [])
        self.assertEqual(other.lookup(DURATION + 1, FINGERPRINT), [])
        self.assertEqual(len(transport.requests), 2)


# --- identify falling back to fingerprints (criteria 4 and 5) ---------------


class Lookups:
    """AcoustID answering by file: `fpcalc` below fingerprints a file as `FP-<its name>`.

    `recordings` maps a file name to the recording MBIDs AcoustID knows it
    as. A file not in it is a fingerprint nobody has linked yet.
    """

    def __init__(self, recordings: dict[str, list[str]]) -> None:
        self.recordings = recordings
        self.requests: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        name = query(url)["fingerprint"].removeprefix("FP-")
        results = [{"id": f"result-{n}", "score": 0.9, "recordings": [{"id": r}]}
                   for n, r in enumerate(self.recordings.get(name, []))]
        return 200, json.dumps({"status": "ok", "results": results}).encode()


class IdentifyByFingerprint(unittest.TestCase):
    """What identify does when the search finds nothing with the files' track counts.

    MusicBrainz is the fake server from tests.test_identify, which also says
    which releases each recording appears on. It is imported here rather
    than at the top because it imports musiclib.identify, and the client
    cases above do not need that to exist.
    """

    FILES = [200, 180, 240]

    def setUp(self) -> None:
        from tests import test_identify as fakes
        from musiclib.identify import identify

        self.fakes = fakes
        self._identify = identify
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        album = self.root / "N" / "Nine Inch Nails" / "(1994) The Downward Spiral"
        self.unit = fakes.unit(album, [
            fakes.vorbis(album, f"0{n}. Track {n}.flac", length, tracknumber=str(n),
                         album="The Downward Spiral", albumartist="Nine Inch Nails")
            for n, length in enumerate(self.FILES, start=1)
        ])
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

    def which(self, name: str) -> str | None:
        return str(self.fpcalc) if name == "fpcalc" else None

    def identify(self, server, recordings: dict[str, list[str]] | None = None, *,
                 env: dict[str, str] | None = None, which=None, with_acoustid: bool = True):
        lookups = Lookups(recordings or {})
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
        # 4 s off is `review`, and still a count match: the owner picks
        # from the search, and AcoustID is not asked.
        mbid = self.fakes.mbid
        close = self.fakes.release_json(mbid("a1"), [[204, 180, 240]])
        server = self.fakes.Server(search=self.fakes.search_json(close), releases=(close,),
                                   recordings={mbid("91"): [mbid("a1")]})
        result, lookups = self.identify(server, {"01. Track 1.flac": [mbid("91")]})
        self.assertEqual(result.status, "review")
        self.assertEqual(lookups.requests, [])
        self.assertFalse(self.fpcalc_ran())

    def test_a_fingerprint_match_is_review_even_when_it_fits_exactly(self) -> None:
        # The search found the album only with the wrong track count. The
        # fingerprints find a release every file fits within 3 s, alone,
        # which from a search would be `auto`.
        mbid = self.fakes.mbid
        short = self.fakes.release_json(mbid("b1"), [[200, 180]])
        exact = self.fakes.release_json(mbid("a1"), [self.FILES])
        server = self.fakes.Server(search=self.fakes.search_json(short), releases=(exact,),
                                   recordings={mbid(f"9{n}"): [mbid("a1")] for n in (1, 2, 3)})
        result, _ = self.identify(server, {f"0{n}. Track {n}.flac": [mbid(f"9{n}")] for n in (1, 2, 3)})
        self.assertEqual(result.status, "review")
        self.assertEqual([(c.release_id, c.release) for c in result.candidates[:1]], [(mbid("a1"), exact)])

    def test_releases_from_every_track_are_proposed_once_each_ranked_as_a_search_is(self) -> None:
        # Files are 200, 180 and 240 s. Track 1 is recording A, on e1, d4 and
        # c2. Track 2 is recording B, on c2, f3 and 03. Track 3 is unknown.
        # f3 is reachable only from track 2, and c2 from both. The ranking
        # differs from the order the releases were found in, and from MBID
        # order, and d4 and e1 tie on duration so only the MBID orders them.
        mbid = self.fakes.mbid
        releases = {
            "e1": [[200, 180, 241]],  # counts match, 1 s off in all
            "d4": [[201, 180, 240]],  # counts match, 1 s off in all
            "c2": [[200, 180, 244]],  # counts match, 4 s off
            "f3": [[200, 180, 240]],  # counts match exactly
            "03": [[200, 180]],       # counts differ
        }
        server = self.fakes.Server(
            search=self.fakes.search_json(),
            releases=tuple(self.fakes.release_json(mbid(k), v) for k, v in releases.items()),
            recordings={mbid("9a"): [mbid("e1"), mbid("d4"), mbid("c2")],
                        mbid("9b"): [mbid("c2"), mbid("f3"), mbid("03")]},
        )
        result, _ = self.identify(server, {"01. Track 1.flac": [mbid("9a")], "02. Track 2.flac": [mbid("9b")]})
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates],
                         [mbid("f3"), mbid("d4"), mbid("e1"), mbid("c2"), mbid("03")])

    def test_no_recording_found_leaves_the_album_unidentified_with_no_match(self) -> None:
        server = self.fakes.Server(search=self.fakes.search_json())
        result, lookups = self.identify(server, {})
        self.assertEqual((result.status, result.reason), ("unidentified", "no match"))
        self.assertEqual(result.candidates, [])
        self.assertNotEqual(lookups.requests, [])


if __name__ == "__main__":
    unittest.main()
