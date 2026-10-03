"""Delete album: `POST /api/library/delete` removes a library album folder for good, with its extras.

The artist and letter folders it leaves empty go too. An album being saved or
open in review is refused, and so is a path that is not an album folder of
the library. `memory.json` is never touched.
"""

from __future__ import annotations

import json
import unittest

from tests import test_agitha_matches as match_tests
from tests import test_agitha_save as save_tests

DELETE = "/api/library/delete"


class DeleteCase(match_tests.MatchCase):
    def remove(self, path: object) -> save_tests.neighbour.Answer:
        return self.post(DELETE, {"path": path})

    def refused(self, path: object, status: int, sentence: str) -> None:
        """Deleting `path` is answered `status` and `sentence`, and nothing on disk changed."""
        before = self.on_disk()
        self.assertEqual(self.turned_down(self.remove(path), status), sentence)
        self.assert_as_it_was(before)


class DeletesAnAlbum(DeleteCase):
    def test_the_album_folder_goes_with_every_file_in_it_and_the_artists_other_albums_stay(self) -> None:
        path = self.path("ecliptica")
        others = {name: data for name, data in self.shelved().items() if not name.startswith(path)}

        got = self.remove(path)

        self.assertEqual((got.status, json.loads(got.body)), (200, {"deleted": path, "note": None}))
        self.assertFalse((self.shelf / path).exists())
        self.assertEqual(self.shelved(), others)
        albums = [album["path"] for album in self.answer(match_tests.address("S/Sonata Arctica"))["albums"]]
        self.assertNotIn(path, albums)
        self.assertIn(self.path("silence"), albums)

    def test_an_artists_last_album_takes_the_artist_and_letter_folders_with_it(self) -> None:
        path = self.path("lulu")
        self.assertEqual(self.remove(path).status, 200)
        self.assertFalse((self.shelf / "L").exists())

    def test_a_letter_with_other_artists_stays_when_one_artist_goes(self) -> None:
        path = self.path("discovery")
        self.assertEqual(self.remove(path).status, 200)
        self.assertFalse((self.shelf / "D" / "Daft Punk").exists())
        self.assertTrue((self.shelf / self.path("images")).is_dir())

    def test_the_albums_extras_go_with_it_and_another_albums_stay(self) -> None:
        path, kept = self.path("ecliptica"), self.path("silence")
        extras = self.folders["extras"]
        for album in (path, kept):
            (extras / album).mkdir(parents=True)
            (extras / album / "video.mkv").write_bytes(b"not really a video")

        self.assertEqual(self.remove(path).status, 200)

        self.assertFalse((extras / path).exists())
        self.assertTrue((extras / kept / "video.mkv").is_file())

    def test_the_engines_memory_is_as_it_was(self) -> None:
        before = self.memory_files()
        self.assertEqual(self.remove(self.path("ecliptica")).status, 200)
        self.assertEqual(self.memory_files(), before)


class RefusesWhatItMustNotDelete(DeleteCase):
    def test_an_album_open_in_review_is_refused_and_its_match_and_folder_stay(self) -> None:
        path = self.path("ecliptica")
        self.ready(self.match(path))
        self.refused(path, 409, match_tests.OPEN_IN_REVIEW)

    def test_an_album_being_saved_is_refused_and_the_save_goes_on(self) -> None:
        path = self.path("ecliptica")
        with self.held_mid_write(self.draft(path, match_tests.edit(set={"Genre": save_tests.NEW_GENRES}))) as job:
            self.assertEqual(self.turned_down(self.remove(path)), save_tests.BEING_SAVED)
            self.assertTrue((self.shelf / path).is_dir())
        self.assertEqual(self.settle(job)["state"], "done")
        self.assertTrue((self.shelf / path).is_dir())

    def test_a_path_that_is_no_album_of_the_library_is_404(self) -> None:
        for path in ("S/Sonata Arctica", "S", "S/Sonata Arctica/(1999) Nothing", "../shelf/S/Sonata Arctica/x",
                     "/etc/passwd/x/y"):
            with self.subTest(path=path):
                self.refused(path, 404, "No such folder.")

    def test_a_body_without_a_path_is_400(self) -> None:
        self.refused(None, 400, 'The body must be an object with the "path" of a library album.')


class LogsTheDeletion(DeleteCase):
    def test_a_deleted_album_is_one_line_with_its_file_count(self) -> None:
        path = self.path("ecliptica")
        files = sum(1 for entry in (self.shelf / path).rglob("*") if entry.is_file())
        with self.assertLogs("agitha.writes") as logged:
            self.remove(path)
        self.assertEqual(len(logged.output), 1)
        self.assertTrue(logged.output[0].startswith(f"INFO:agitha.writes:write delete-album {path} files={files} bytes="))

    def test_a_refused_deletion_logs_nothing(self) -> None:
        with self.assertNoLogs("agitha.writes"):
            self.remove("S/Sonata Arctica")


if __name__ == "__main__":
    unittest.main()
