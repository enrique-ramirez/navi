"""The response cache, and what a warm one saves.

Every MusicBrainz, AcoustID and Cover Art Archive response goes through
`Cache.fetch(url, get)`. `get` stands in for the network here: a warm cache
must never call it, and `refresh` must call it once per URL and keep what it
returns.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musiclib.cache import Cache

URL = "https://musicbrainz.org/ws/2/release/3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d?inc=labels&fmt=json"


class Network:
    """A `get` that answers with a fixed body and counts how often it was asked."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1
        return self.body


def offline() -> bytes:
    raise AssertionError("the cache went to the network")


class CacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.directory = self.root / "cache"
        self.directory.mkdir()


class WarmCache(CacheTestCase):
    def test_a_second_run_over_the_same_directory_makes_no_request(self) -> None:
        # A new Cache, as a second plan in a new process would make: nothing
        # in memory carries over, only the directory.
        Cache(self.directory).fetch(URL, Network(b'{"id": 1}'))
        self.assertEqual(Cache(self.directory).fetch(URL, offline), b'{"id": 1}')

    def test_the_first_fetch_returns_what_the_network_said(self) -> None:
        network = Network(b'{"id": 1}')
        self.assertEqual(Cache(self.directory).fetch(URL, network), b'{"id": 1}')
        self.assertEqual(network.calls, 1)

    def test_bodies_come_back_byte_for_byte(self) -> None:
        # Cover Art Archive bodies are JPEGs, and a cache that decodes or
        # normalises line endings breaks both the image and the promise that
        # the same cached responses give byte-identical output.
        body = bytes(range(256)) + b"\r\n\n\r"
        Cache(self.directory).fetch(URL, Network(body))
        self.assertEqual(Cache(self.directory).fetch(URL, offline), body)

    def test_an_empty_body_is_still_a_stored_response(self) -> None:
        Cache(self.directory).fetch(URL, Network(b""))
        self.assertEqual(Cache(self.directory).fetch(URL, offline), b"")

    def test_urls_that_differ_anywhere_are_stored_apart(self) -> None:
        # Each pair is easy to collapse into one filename: by query string,
        # by replacing "/" with "_", by case on a case-insensitive disk (the
        # MacBook's APFS is one), and by truncating a long search URL to fit
        # a filename.
        long_query = "https://musicbrainz.org/ws/2/release/?query=" + "a" * 400
        pairs = [
            (URL, URL.replace("inc=labels", "inc=genres")),
            ("https://musicbrainz.org/ws/2/a/b", "https://musicbrainz.org/ws/2/a_b"),
            (
                "https://musicbrainz.org/ws/2/release/?query=Hotel",
                "https://musicbrainz.org/ws/2/release/?query=hotel",
            ),
            (long_query + "1", long_query + "2"),
        ]
        for first, second in pairs:
            with self.subTest(first=first[:60], second=second[:60]):
                Cache(self.directory).fetch(first, Network(b"first"))
                Cache(self.directory).fetch(second, Network(b"second"))
                self.assertEqual(Cache(self.directory).fetch(first, offline), b"first")
                self.assertEqual(Cache(self.directory).fetch(second, offline), b"second")

    def test_responses_live_in_the_directory_the_caller_named(self) -> None:
        Cache(self.directory).fetch(URL, Network(b"body"))
        self.assertNotEqual(list(self.directory.iterdir()), [])
        self.assertEqual([p.name for p in self.root.iterdir()], ["cache"])
        # A different directory is a different cache, so it starts cold.
        other = self.root / "other"
        other.mkdir()
        network = Network(b"body")
        Cache(other).fetch(URL, network)
        self.assertEqual(network.calls, 1)

    def test_a_failed_fetch_leaves_nothing_behind(self) -> None:
        # How a MusicBrainz 503 stays out of the cache: the client's `get`
        # raises, and the next run must ask again rather than find a stored
        # failure.
        def broken() -> bytes:
            raise ConnectionError("503")

        with self.assertRaises(ConnectionError):
            Cache(self.directory).fetch(URL, broken)
        network = Network(b"body")
        self.assertEqual(Cache(self.directory).fetch(URL, network), b"body")
        self.assertEqual(network.calls, 1)


class Refresh(CacheTestCase):
    def test_refresh_fetches_again_and_replaces_the_stored_copy(self) -> None:
        Cache(self.directory).fetch(URL, Network(b"old"))
        network = Network(b"new")
        self.assertEqual(Cache(self.directory, refresh=True).fetch(URL, network), b"new")
        self.assertEqual(network.calls, 1)
        self.assertEqual(Cache(self.directory).fetch(URL, offline), b"new")

    def test_refresh_fetches_each_url_once_per_run(self) -> None:
        # A plan asks for the same release more than once. Refreshing means
        # "not what an earlier run stored", not "every call goes out", which
        # would double the requests against a 1-per-second limit.
        cache = Cache(self.directory, refresh=True)
        network = Network(b"new")
        cache.fetch(URL, network)
        self.assertEqual(cache.fetch(URL, offline), b"new")
        self.assertEqual(network.calls, 1)

    def test_refresh_on_a_cold_url_fetches_and_stores_it(self) -> None:
        network = Network(b"body")
        Cache(self.directory, refresh=True).fetch(URL, network)
        self.assertEqual(network.calls, 1)
        self.assertEqual(Cache(self.directory).fetch(URL, offline), b"body")


if __name__ == "__main__":
    unittest.main()
