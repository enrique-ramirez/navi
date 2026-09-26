"""A release the owner names, by URL or MBID.

The owner pastes whatever the browser shows. A release page in any of its
tabs is the release; a release group or a recording is a different thing
with an MBID of the same shape, and planning against it would be wrong, so
it is refused by value.
"""

from __future__ import annotations

import unittest

from musiclib.identify import chosen, release_ref
from tests.test_identify import IdentifyTestCase as _Base
from tests.test_identify import Server, release_json, unit

MBID = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"


class ReleaseRef(unittest.TestCase):
    def test_a_release_url_or_a_bare_mbid_gives_the_mbid(self) -> None:
        accepted = [
            f"https://musicbrainz.org/release/{MBID}",
            f"http://musicbrainz.org/release/{MBID}",
            f"https://beta.musicbrainz.org/release/{MBID}",
            f"https://musicbrainz.org/release/{MBID}/",
            f"https://musicbrainz.org/release/{MBID}/cover-art",
            f"https://musicbrainz.org/release/{MBID}?tab=discids",
            MBID,
            f"  {MBID}\n",
            MBID.upper(),
        ]
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(release_ref(value), MBID)

    def test_anything_else_is_refused_by_value(self) -> None:
        refused = [
            f"https://musicbrainz.org/release-group/{MBID}",
            f"https://musicbrainz.org/recording/{MBID}",
            f"https://musicbrainz.org/artist/{MBID}",
            MBID[:-1],
            MBID + "0",
            MBID.replace("-", ""),
            "The Downward Spiral",
            "",
        ]
        for value in refused:
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    release_ref(value)
                # Named, so the owner sees which paste was wrong.
                self.assertIn(value, str(raised.exception))


class Chosen(_Base):
    def test_the_chosen_release_is_fetched_and_is_the_only_candidate_for_review(self) -> None:
        # Review even when it fits: the owner picked it, and the plan built
        # against it still gets looked at before it is written.
        release = release_json(MBID, [[200, 180]])
        server = Server(releases=(release,))
        client = self.client(server)
        result = chosen(unit(self.album, self.tagged([200, 180], release_id=None)), client,
                        f"https://musicbrainz.org/release/{MBID}")
        self.assertEqual(result.status, "review")
        self.assertEqual([(c.release_id, c.release) for c in result.candidates], [(MBID, release)])
        self.assertEqual(server.fetched(), [MBID])
        self.assertEqual(server.searches(), [])

    def test_a_refused_value_asks_musicbrainz_nothing(self) -> None:
        server = Server()
        value = f"https://musicbrainz.org/release-group/{MBID}"
        with self.assertRaises(ValueError) as raised:
            chosen(unit(self.album, self.tagged([200])), self.client(server), value)
        self.assertIn(value, str(raised.exception))
        self.assertEqual(server.urls, [])


if __name__ == "__main__":
    unittest.main()
