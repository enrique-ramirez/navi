"""The MusicBrainz client: what it asks for, how often, and what a 503 does.

MusicBrainz blocks clients that send no proper
User-Agent or that start more than one request a second, so both are checked
on every request the client makes, retries included.

Nothing here touches the network or sleeps. The transport is a fake that
records each request with the time it started, and the clock only moves when
the client sleeps, so a gap between two starts is exactly the wait the client
chose.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import musiclib
from musiclib import mb
from musiclib.cache import Cache

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mb"
RELEASE = (FIXTURES / "release.json").read_bytes()
RELEASE_GROUP = (FIXTURES / "release-group.json").read_bytes()
SEARCH = (FIXTURES / "search-releases.json").read_bytes()

RELEASE_MBID = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"
RELEASE_GROUP_MBID = "5e2a7c1d-4b3f-4e8a-9c6d-1f0b2a3c4d5e"

UNAVAILABLE = (503, b"<html><body>503 Service Temporarily Unavailable</body></html>")


class FakeClock:
    """A monotonic clock that moves only when somebody sleeps on it."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []
        self.reads = 0

    def __call__(self) -> float:
        # A client that polls the clock until a second has passed, instead of
        # sleeping, would spin here forever, because this clock stands still.
        # Fail it rather than hang the suite.
        self.reads += 1
        if self.reads > 1_000:
            raise AssertionError("the client polled the clock instead of sleeping")
        return self.now

    def sleep(self, seconds: float) -> None:
        # time.sleep refuses a negative wait, and so does this.
        if seconds < 0:
            raise ValueError(f"sleep length must be non-negative: {seconds}")
        self.sleeps.append(seconds)
        self.now += seconds


class Request(NamedTuple):
    url: str
    headers: dict[str, str]
    started: float


class FakeTransport:
    """Answers from a script, in order, and records every request.

    A request past the end of the script is a request the test did not
    expect, so it fails loudly rather than answering.
    """

    def __init__(self, clock: FakeClock, *answers: tuple[int, bytes]) -> None:
        self.clock = clock
        self.answers = list(answers)
        self.requests: list[Request] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(Request(url, dict(headers), self.clock.now))
        if not self.answers:
            raise AssertionError(f"unexpected request: {url}")
        return self.answers.pop(0)

    def starts(self) -> list[float]:
        return [r.started for r in self.requests]


def gaps(starts: list[float]) -> list[float]:
    return [later - earlier for earlier, later in zip(starts, starts[1:])]


def user_agent(request: Request) -> str | None:
    # HTTP header names are case-insensitive, and urllib rewrites them to
    # "User-agent" anyway, so the spelling is not the promise.
    for name, value in request.headers.items():
        if name.lower() == "user-agent":
            return value
    return None


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def inc(url: str) -> set[str]:
    # "+" joins inc values; parse_qs has already turned a literal one into a
    # space, and an encoded %2B into "+".
    return set(re.split(r"[+ ]", query(url)["inc"]))


class ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache_dir = Path(tmp.name)
        self.clock = FakeClock()

    def client(self, *answers: tuple[int, bytes], refresh: bool = False):
        transport = FakeTransport(self.clock, *answers)
        client = mb.MusicBrainz(
            Cache(self.cache_dir, refresh=refresh),
            transport=transport,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        return client, transport


class Lookups(ClientTestCase):
    def test_a_release_lookup_brings_credits_labels_tracks_and_its_release_group(self) -> None:
        client, transport = self.client((200, RELEASE))
        self.assertEqual(client.release(RELEASE_MBID), json.loads(RELEASE))
        [request] = transport.requests
        url = urlsplit(request.url)
        self.assertEqual((url.scheme, url.netloc), ("https", "musicbrainz.org"))
        self.assertEqual(url.path, f"/ws/2/release/{RELEASE_MBID}")
        self.assertEqual(query(request.url)["fmt"], "json")
        # What the later mapping reads from the release: credits, labels,
        # tracks and media for matching, and the release group whose genres
        # get composed.
        included = inc(request.url)
        self.assertLessEqual(
            {"artist-credits", "labels", "recordings", "release-groups", "media"}, included
        )
        # Genres come from the release group. Asking for them here as well
        # without tags would split one lookup in two.
        self.assertEqual("genres" in included, "tags" in included)

    def test_release_group_genres_and_folksonomy_tags_come_from_one_lookup(self) -> None:
        # Tags are not a second request, so they cost no extra
        # second against the rate limit and are cached with the genres.
        client, transport = self.client((200, RELEASE_GROUP))
        self.assertEqual(client.release_group(RELEASE_GROUP_MBID), json.loads(RELEASE_GROUP))
        [request] = transport.requests
        self.assertEqual(urlsplit(request.url).path, f"/ws/2/release-group/{RELEASE_GROUP_MBID}")
        self.assertEqual(query(request.url)["fmt"], "json")
        self.assertLessEqual({"genres", "tags"}, inc(request.url))

    def test_a_search_asks_by_title_artist_and_track_count(self) -> None:
        # Lucene escaping is the client's
        # business, so backslashes are dropped and case is ignored before
        # looking for each value under its field.
        client, transport = self.client((200, SEARCH))
        result = client.search_releases("The Downward Spiral", "Nine Inch Nails", 14)
        self.assertEqual(result, json.loads(SEARCH))
        [request] = transport.requests
        self.assertEqual(urlsplit(request.url).path.rstrip("/"), "/ws/2/release")
        self.assertEqual(query(request.url)["fmt"], "json")
        lucene = query(request.url)["query"].replace("\\", "").lower()
        self.assertRegex(lucene, r'\brelease:[\s("]*the downward spiral')
        self.assertRegex(lucene, r'\bartist:[\s("]*nine inch nails')
        self.assertRegex(lucene, r'\btracks:[\s("]*14\b')


class UserAgent(ClientTestCase):
    def test_the_user_agent_names_the_tool_its_version_and_a_contact(self) -> None:
        self.assertIn(f"musiclib/{musiclib.__version__}", mb.USER_AGENT)
        self.assertIn("hello@enrique-ramirez.com", mb.USER_AGENT)

    def test_every_request_carries_it_retries_included(self) -> None:
        client, transport = self.client(
            (200, RELEASE),
            (200, RELEASE_GROUP),
            UNAVAILABLE,
            (200, SEARCH),
        )
        client.release(RELEASE_MBID)
        client.release_group(RELEASE_GROUP_MBID)
        client.search_releases("The Downward Spiral", "Nine Inch Nails", 14)
        self.assertEqual(len(transport.requests), 4)
        for request in transport.requests:
            with self.subTest(url=request.url):
                self.assertEqual(user_agent(request), mb.USER_AGENT)


class RateLimit(ClientTestCase):
    def test_no_two_requests_start_less_than_a_second_apart(self) -> None:
        client, transport = self.client((200, RELEASE), (200, RELEASE_GROUP), (200, SEARCH))
        client.release(RELEASE_MBID)
        client.release_group(RELEASE_GROUP_MBID)
        client.search_releases("The Downward Spiral", "Nine Inch Nails", 14)
        self.assertEqual(len(transport.requests), 3)
        for gap in gaps(transport.starts()):
            self.assertGreaterEqual(gap, 1.0)

    def test_a_cache_hit_neither_requests_nor_waits(self) -> None:
        # The hit comes straight after a request, which is exactly when a
        # client that waits before looking in the cache would sleep a second.
        client, transport = self.client((200, RELEASE))
        client.release(RELEASE_MBID)
        waited = list(self.clock.sleeps)
        self.assertEqual(client.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(self.clock.sleeps, waited)


class Unavailable(ClientTestCase):
    def test_five_503s_give_up_as_musicbrainz_unavailable(self) -> None:
        client, transport = self.client(*[UNAVAILABLE] * 5)
        with self.assertRaises(mb.MusicBrainzUnavailable) as raised:
            client.release(RELEASE_MBID)
        # identify turns this into the album's "unidentified: ..." reason.
        self.assertEqual(str(raised.exception), "musicbrainz unavailable")
        self.assertEqual(len(transport.requests), 5)

    def test_each_retry_waits_longer_than_the_last(self) -> None:
        client, transport = self.client(*[UNAVAILABLE] * 5)
        with self.assertRaises(mb.MusicBrainzUnavailable):
            client.release(RELEASE_MBID)
        # Measured as MusicBrainz sees it, start to start, so the one-second
        # floor still holds between retries and a backoff that the floor
        # swallows (0.5 s, then 1 s) does not count as growing.
        waits = gaps(transport.starts())
        self.assertEqual(len(waits), 4)
        self.assertGreaterEqual(waits[0], 1.0)
        for shorter, longer in zip(waits, waits[1:]):
            self.assertGreater(longer, shorter)

    def test_a_503_then_an_answer_returns_the_answer_and_caches_it(self) -> None:
        client, transport = self.client(UNAVAILABLE, UNAVAILABLE, (200, RELEASE))
        self.assertEqual(client.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(len(transport.requests), 3)
        warm, offline = self.client()
        self.assertEqual(warm.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(offline.requests, [])

    def test_a_503_is_never_cached(self) -> None:
        # Otherwise one bad minute on MusicBrainz's side would leave the album
        # unidentified on every run until somebody passed refresh.
        client, _ = self.client(*[UNAVAILABLE] * 5)
        with self.assertRaises(mb.MusicBrainzUnavailable):
            client.release(RELEASE_MBID)
        later, transport = self.client((200, RELEASE))
        self.assertEqual(later.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(len(transport.requests), 1)

    def test_another_error_status_is_an_error_but_not_unavailable(self) -> None:
        # A 404 is a wrong MBID, a different story for the album from a
        # MusicBrainz outage.
        client, _ = self.client((404, b'{"error": "Not Found"}'))
        with self.assertRaises(mb.MusicBrainzError) as raised:
            client.release(RELEASE_MBID)
        self.assertNotIsInstance(raised.exception, mb.MusicBrainzUnavailable)


class FlakyTransport(FakeTransport):
    """A `FakeTransport` whose script may hold an exception, raised in place of an answer."""

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        answer = super().__call__(url, headers)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class NetworkTrouble(ClientTestCase):
    """What the network does on a bad day is retried the way a 503 is.

    A connection refused, a timeout, a connection dropped mid-answer and a
    proxy's 502 or 504 all say MusicBrainz could not be reached this time,
    which is what a 503 says. None of them is a verdict on the release.
    """

    def flaky(self, *answers):
        transport = FlakyTransport(self.clock, *answers)
        client = mb.MusicBrainz(
            Cache(self.cache_dir), transport=transport, clock=self.clock, sleep=self.clock.sleep
        )
        return client, transport

    def test_five_failures_of_any_kind_give_up_as_musicbrainz_unavailable(self) -> None:
        kinds = {
            "connection refused": lambda: urllib.error.URLError(ConnectionRefusedError(61, "refused")),
            "timeout": lambda: TimeoutError("timed out"),
            "connection reset": lambda: ConnectionResetError(54, "reset by peer"),
            "502": lambda: (502, b"<html>502 Bad Gateway</html>"),
            "504": lambda: (504, b"<html>504 Gateway Time-out</html>"),
        }
        for kind, failure in kinds.items():
            with self.subTest(kind):
                client, transport = self.flaky(*[failure() for _ in range(5)])
                with self.assertRaises(mb.MusicBrainzUnavailable):
                    client.release(RELEASE_MBID)
                self.assertEqual(len(transport.requests), 5)

    def test_mixed_failures_share_one_budget_and_the_same_growing_waits(self) -> None:
        # Four different failures, then the answer: every one counts as an
        # attempt, and each wait is longer than the one before, measured
        # start to start as for a 503.
        client, transport = self.flaky(
            urllib.error.URLError("nodename nor servname provided"),
            (502, b"bad gateway"),
            TimeoutError("timed out"),
            (504, b"gateway timeout"),
            (200, RELEASE),
        )
        self.assertEqual(client.release(RELEASE_MBID), json.loads(RELEASE))
        waits = gaps(transport.starts())
        self.assertEqual(len(waits), 4)
        self.assertGreaterEqual(waits[0], 1.0)
        for shorter, longer in zip(waits, waits[1:]):
            self.assertGreater(longer, shorter)

    def test_a_sixth_attempt_is_never_made_after_mixed_failures(self) -> None:
        # The script holds an answer after the fifth failure. A client that
        # keeps a separate count per kind reaches it and returns the release.
        client, transport = self.flaky(
            urllib.error.URLError("refused"), (502, b""), TimeoutError(), (504, b""),
            UNAVAILABLE, (200, RELEASE),
        )
        with self.assertRaises(mb.MusicBrainzUnavailable):
            client.release(RELEASE_MBID)
        self.assertEqual(len(transport.requests), 5)


class NotFound(ClientTestCase):
    def test_a_404_is_remembered_so_a_warm_run_asks_nothing(self) -> None:
        # Every response is cached, and "no such release" is a
        # response. A release ID MusicBrainz does not know would otherwise
        # cost a request and a second of rate limit on every warm run.
        cold, _ = self.client((404, b'{"error": "Not Found"}'))
        with self.assertRaises(mb.MusicBrainzError):
            cold.release(RELEASE_MBID)

        self.clock = FakeClock()
        warm, transport = self.client()
        with self.assertRaises(mb.MusicBrainzError) as raised:
            warm.release(RELEASE_MBID)
        self.assertNotIsInstance(raised.exception, mb.MusicBrainzUnavailable)
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_refresh_asks_again_about_a_remembered_404(self) -> None:
        # The release may have been added since. Refresh is how to find out.
        cold, _ = self.client((404, b'{"error": "Not Found"}'))
        with self.assertRaises(mb.MusicBrainzError):
            cold.release(RELEASE_MBID)
        refreshed, transport = self.client((200, RELEASE), refresh=True)
        self.assertEqual(refreshed.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(len(transport.requests), 1)


class Cached(ClientTestCase):
    def test_a_warm_cache_answers_every_lookup_without_a_request(self) -> None:
        # A new client over the same directory,
        # with a transport that fails on any call. The release group's tags
        # hold to this as well.
        cold, _ = self.client((200, RELEASE), (200, RELEASE_GROUP), (200, SEARCH))
        cold.release(RELEASE_MBID)
        cold.release_group(RELEASE_GROUP_MBID)
        cold.search_releases("The Downward Spiral", "Nine Inch Nails", 14)

        self.clock = FakeClock()
        warm, transport = self.client()
        self.assertEqual(warm.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(warm.release_group(RELEASE_GROUP_MBID), json.loads(RELEASE_GROUP))
        self.assertEqual(
            warm.search_releases("The Downward Spiral", "Nine Inch Nails", 14), json.loads(SEARCH)
        )
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.clock.sleeps, [])

    def test_refresh_asks_again_and_keeps_the_new_answer(self) -> None:
        stale = json.dumps({"id": RELEASE_MBID, "title": "stale"}).encode()
        first, _ = self.client((200, stale))
        first.release(RELEASE_MBID)

        refreshed, transport = self.client((200, RELEASE), refresh=True)
        self.assertEqual(refreshed.release(RELEASE_MBID), json.loads(RELEASE))
        self.assertEqual(len(transport.requests), 1)

        warm, _ = self.client()
        self.assertEqual(warm.release(RELEASE_MBID), json.loads(RELEASE))


if __name__ == "__main__":
    unittest.main()
