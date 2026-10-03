"""agitha's library, pruned: which folders read as empty, and `DELETE` of an artist or an album folder that is.

Each test has its own server over its own library at `<tmp>/shelf`, as
`tests.test_agitha_save` does, since a removal changes it.
"""

from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote

from agitha.server import Config, make_server
from tests import builders
from tests import test_agitha_library as shelf_tests
from tests import test_agitha_server as neighbour

MONO = "M/MONO (Jap)"
MOGWAI = "M/Mogwai"
#: The one artist under `N`, with nothing in it.
NEUROSIS = "N/Neurosis"
BARE = "M/Mogwai/(1997) Young Team"
FULL = "M/Mogwai/(1999) Come On Die Young"


class RemoveCase(shelf_tests.LibraryCase):
    @classmethod
    def setUpClass(cls) -> None:
        pass

    @classmethod
    def tearDownClass(cls) -> None:
        pass

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.folders = neighbour.make_folders(self.root)
        self.shelf = self.root / "shelf"
        for path in (MONO, NEUROSIS, BARE):
            (self.shelf / path).mkdir(parents=True)
        album = builders.library_album(self.shelf, letter="M", artist="Mogwai", date="1999-03-29",
                                       album="Come On Die Young", discs=(("Punk Rock:",),))
        self.assertEqual(album, self.shelf / FULL)
        # What a path that leaves the root would reach.
        self.outside = self.root / "outside"
        (self.outside / "Q" / "Quiet Artist").mkdir(parents=True)
        (self.shelf / "Q").symlink_to(self.outside / "Q", target_is_directory=True)
        (self.shelf / "M" / "Linked").symlink_to(self.shelf / MONO, target_is_directory=True)
        config = Config(
            inbox=self.folders["inbox"], jobs=self.folders["jobs"], library=self.shelf,
            extras=self.folders["extras"], musiclib=str(neighbour.STUB), static=self.folders["static"],
            port=0, host="127.0.0.1",
        )
        self.server = make_server(config)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    def on_disk(self) -> dict[str, bytes | None]:
        return builders.tree(self.root)

    def delete(self, path: str) -> tuple[int, Any]:
        got = self.fetch(shelf_tests.address(path), method="DELETE")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        return got.status, json.loads(got.body)

    def refused(self, path: str, status: int, sentence: str) -> None:
        before = self.on_disk()
        self.assertEqual(self.delete(path), (status, {"error": sentence}))
        self.assertEqual(self.on_disk(), before)


class SaysWhichFoldersAreEmpty(RemoveCase):
    def test_a_letter_marks_the_artist_folders_that_hold_nothing(self) -> None:
        self.assertEqual(self.answer(shelf_tests.address("M"))["artists"],
                         [{"name": "MONO (Jap)", "empty": True}, {"name": "Mogwai", "empty": False}])

    def test_an_artist_marks_the_album_folders_that_hold_nothing(self) -> None:
        albums = self.answer(shelf_tests.address(MOGWAI))["albums"]
        self.assertEqual([(album["path"], album["empty"]) for album in albums], [(BARE, True), (FULL, False)])

    def test_a_folder_that_holds_only_a_hidden_file_or_only_an_empty_folder_is_not_empty(self) -> None:
        (self.shelf / MONO / ".DS_Store").write_bytes(b"")
        (self.shelf / BARE / "CD1").mkdir()
        self.assertEqual(self.answer(shelf_tests.address("M"))["artists"][0], {"name": "MONO (Jap)", "empty": False})
        albums = self.answer(shelf_tests.address(MOGWAI))["albums"]
        self.assertEqual([(album["path"], album["empty"]) for album in albums], [(BARE, False), (FULL, False)])


class RemovesAnEmptyFolder(RemoveCase):
    def test_an_empty_artist_folder_goes_and_its_letter_stays_with_the_artists_left(self) -> None:
        self.assertEqual(self.delete(MONO), (200, {"removed": [MONO]}))
        self.assertFalse((self.shelf / MONO).exists())
        self.assertEqual([artist["name"] for artist in self.answer(shelf_tests.address("M"))["artists"]], ["Mogwai"])

    def test_an_empty_album_folder_goes_and_its_artist_stays(self) -> None:
        self.assertEqual(self.delete(BARE), (200, {"removed": [BARE]}))
        self.assertFalse((self.shelf / BARE).exists())
        self.assertTrue((self.shelf / FULL / "01. Punk Rock:.flac").is_file())

    def test_an_artist_left_empty_by_its_last_album_stays_until_it_is_removed_itself(self) -> None:
        (self.shelf / MONO / "(2001) Under the Pipal Tree").mkdir()
        self.assertEqual(self.delete(f"{MONO}/(2001) Under the Pipal Tree"),
                         (200, {"removed": [f"{MONO}/(2001) Under the Pipal Tree"]}))
        self.assertEqual(list((self.shelf / MONO).iterdir()), [])

    def test_the_letter_folder_goes_with_its_last_artist(self) -> None:
        self.assertEqual(self.delete(NEUROSIS), (200, {"removed": [NEUROSIS, "N"]}))
        self.assertFalse((self.shelf / "N").exists())
        self.assertNotIn("N", self.answer(shelf_tests.address())["letters"])

    def test_a_letter_that_holds_a_stray_file_stays_when_its_last_artist_goes(self) -> None:
        (self.shelf / "N" / "notes.txt").write_text("not an artist\n")
        self.assertEqual(self.delete(NEUROSIS), (200, {"removed": [NEUROSIS]}))
        self.assertEqual([path.name for path in (self.shelf / "N").iterdir()], ["notes.txt"])

    def test_a_removal_sent_with_a_body_closes_the_connection(self) -> None:
        # Nobody reads the body, and on a kept connection it would be taken for the start of the next request.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        connection.request("DELETE", shelf_tests.address(MONO), body=b'{"sure": true}')
        first = connection.getresponse()
        self.assertEqual((first.status, json.loads(first.read())), (200, {"removed": [MONO]}))
        self.assertEqual(first.headers["Connection"], "close")


class RefusesAFolderThatHoldsSomething(RemoveCase):
    def test_an_album_with_a_track_and_the_artist_that_holds_it_are_409_and_stay(self) -> None:
        self.refused(FULL, 409, f"not empty: {FULL}")
        self.refused(MOGWAI, 409, f"not empty: {MOGWAI}")

    def test_a_folder_with_a_stray_hidden_file_is_409_and_keeps_it(self) -> None:
        (self.shelf / MONO / ".DS_Store").write_bytes(b"")
        self.refused(MONO, 409, f"not empty: {MONO}")
        (self.shelf / BARE / ".hidden").write_bytes(b"")
        self.refused(BARE, 409, f"not empty: {BARE}")

    def test_a_folder_with_an_empty_folder_inside_is_409_and_keeps_it(self) -> None:
        (self.shelf / MONO / "(2001) Under the Pipal Tree").mkdir()
        self.refused(MONO, 409, f"not empty: {MONO}")
        (self.shelf / BARE / "CD1").mkdir()
        self.refused(BARE, 409, f"not empty: {BARE}")


class RefusesWhatIsNotAFolderOfTheLibrary(RemoveCase):
    def gone(self, address: str) -> None:
        before = self.on_disk()
        got = self.fetch(address, method="DELETE")
        self.assertEqual(got.status, 404, got.body[:300])
        self.assertEqual(self.on_disk(), before)

    def test_a_folder_that_is_not_there_is_404(self) -> None:
        self.refused("M/Nobody", 404, "No such folder.")
        self.refused(f"{MOGWAI}/(2001) Rock Action", 404, "No such folder.")

    def test_a_path_that_climbs_with_dots_plain_or_encoded_is_404_and_removes_nothing(self) -> None:
        for address in ("/api/library/M/..", "/api/library/M/%2E%2E", "/api/library/M/../../outside/Q",
                        "/api/library/M/MONO%20(Jap)/..", "/api/library/M/..%2F..%2Foutside%2FQ/Quiet%20Artist",
                        "/api/library/M/%2E%2E/%2E%2E/outside/Q/Quiet%20Artist"):
            with self.subTest(address=address):
                self.gone(address)

    def test_a_folder_outside_the_root_reached_by_a_link_or_an_absolute_name_is_404_and_stays(self) -> None:
        outside = self.outside / "Q" / "Quiet Artist"
        for address in (shelf_tests.address("Q/Quiet Artist"),
                        f"/api/library/M/{quote(str(outside), safe='')}",
                        f"/api/library/M{quote(str(outside))}"):
            with self.subTest(address=address):
                self.gone(address)
        self.assertTrue(outside.is_dir())

    def test_a_link_to_an_empty_folder_of_the_library_is_404_and_both_stay(self) -> None:
        self.refused("M/Linked", 404, "No such folder.")

    def test_a_letter_folder_has_no_address_to_remove_it_by(self) -> None:
        (self.shelf / "E").mkdir()
        self.refused("E", 404, "No such API path.")


class LogsEachFolderItRemoves(RemoveCase):
    def test_a_removed_artist_and_the_letter_that_went_with_it_are_a_line_each(self) -> None:
        with self.assertLogs("agitha.writes") as logged:
            self.delete(NEUROSIS)
        self.assertEqual(logged.output, [f"INFO:agitha.writes:write remove-folder {NEUROSIS}",
                                         "INFO:agitha.writes:write remove-folder N"])

    def test_a_refused_removal_logs_nothing(self) -> None:
        with self.assertNoLogs("agitha.writes"):
            self.delete(MOGWAI)


if __name__ == "__main__":
    unittest.main()
