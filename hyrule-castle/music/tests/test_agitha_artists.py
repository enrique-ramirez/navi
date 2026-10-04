"""The per-artist tags and the search that names an artist: `Artists`, `Album artists`, `GET /api/artists`.

A credit such as `Future & Marshmello` does not say whether it is one act or
two. The files say it in a tag of one value per artist, which the pages show
under a readable name and the owner fills by typing a name. The search asks
MusicBrainz for the artists of that name through `Config.mb_transport`, here
a canned one that keeps every URL it was asked for.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from agitha import editor
from agitha.server import Config, make_server
from musiclib import mapping, residue
from tests.test_agitha_order import neighbour, no_waiting

MARSHMELLO = {"id": "c0c5b0b9-0000-4000-8000-0000000000a1", "name": "Marshmello", "sort-name": "Marshmello",
              "type": "Person", "country": "US", "disambiguation": "US electronic music producer and DJ"}
#: An artist as the search lists one with nothing but its name known.
BARE = {"id": "c0c5b0b9-0000-4000-8000-0000000000a2", "name": "Marshmellow Overcoat"}


class CannedSearch:
    """A MusicBrainz that answers every artist search with `artists`, or with the status `fault`."""

    def __init__(self, *artists: dict[str, Any]) -> None:
        self.artists = list(artists)
        self.requests: list[str] = []
        self.fault: int | None = None

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        if self.fault is not None:
            return self.fault, b"<html><body>Service Temporarily Unavailable</body></html>"
        if urlsplit(url).path.rstrip("/") != "/ws/2/artist":
            return 404, b'{"error": "Not Found"}'
        return 200, json.dumps({"artists": self.artists}).encode("utf-8")


class TheTagsOfEachArtist(unittest.TestCase):
    def test_artists_and_album_artists_have_a_readable_name_in_every_format(self) -> None:
        self.assertEqual(mapping.READABLE["Artists"], {
            "id3": "TXXX:ARTISTS", "vorbis": "artists", "mp4": "----:com.apple.iTunes:ARTISTS", "asf": "WM/ARTISTS"})
        self.assertEqual(mapping.READABLE["Album artists"], {
            "id3": "TXXX:ALBUMARTISTS", "vorbis": "albumartists", "mp4": "----:com.apple.iTunes:ALBUMARTISTS",
            "asf": "WM/ALBUMARTISTS"})

    def test_a_hand_edit_may_name_them_and_reaches_each_formats_own_key(self) -> None:
        for name, row in (("Artists", mapping.READABLE["Artists"]), ("Album artists", mapping.READABLE["Album artists"])):
            for family, key in row.items():
                with self.subTest(name=name, family=family):
                    self.assertEqual(editor._resolve(name, family), (key, None))

    def test_the_engine_keeps_them_as_tags_and_not_as_residue(self) -> None:
        for family in ("id3", "vorbis", "mp4", "asf"):
            with self.subTest(family):
                tags = {mapping.READABLE["Artists"][family]: ["Future", "Marshmello"],
                        mapping.READABLE["Album artists"][family]: ["Future", "Marshmello"]}
                kept, removed = residue.strip(family, tags)
                self.assertEqual((kept, removed), (tags, []))


class SearchingForAnArtist(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        no_waiting(self)
        folders = neighbour.make_folders(root)
        shelf = root / "shelf"
        shelf.mkdir()
        self.mb = CannedSearch(MARSHMELLO, BARE)
        config = Config(inbox=folders["inbox"], jobs=folders["jobs"], library=shelf, extras=folders["extras"],
                        musiclib=str(neighbour.STUB), static=folders["static"], port=0, host="127.0.0.1",
                        mb_transport=self.mb)
        self.server = make_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    def search(self, name: str) -> list[dict[str, Any]]:
        url = f"http://127.0.0.1:{self.server.server_address[1]}/api/artists?q={quote(name)}"
        with urllib.request.urlopen(url, timeout=10) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)["artists"]

    def test_answers_each_artist_musicbrainz_finds_with_what_tells_it_apart(self) -> None:
        self.assertEqual(self.search("marshm"), [
            {"id": MARSHMELLO["id"], "name": "Marshmello", "disambiguation": "US electronic music producer and DJ",
             "type": "Person", "country": "US"},
            {"id": BARE["id"], "name": "Marshmellow Overcoat", "disambiguation": "", "type": "", "country": ""},
        ])
        asked = parse_qs(urlsplit(self.mb.requests[-1]).query)["query"]
        self.assertEqual(asked, ["artist:(marshm)"])

    def test_asks_musicbrainz_once_for_a_name_already_searched(self) -> None:
        self.search("marshmello")
        self.search("marshmello")
        self.assertEqual(len(self.mb.requests), 1)

    def test_does_not_search_for_a_name_of_one_letter(self) -> None:
        self.assertEqual(self.search("m"), [])
        self.assertEqual(self.mb.requests, [])

    def test_answers_no_artist_where_musicbrainz_does_not_answer(self) -> None:
        self.mb.fault = 503
        self.assertEqual(self.search("marshmello"), [])


if __name__ == "__main__":
    unittest.main()
