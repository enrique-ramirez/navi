"""agitha's library, read: the letters, a letter's artists, an artist's albums, one album, and the genre list.

The server runs on a thread over temporary folders and is spoken to over
HTTP, as `tests.test_agitha_server` does. The library root is a folder called
`shelf`, with an empty `library` beside it: the root is whatever `--library`
names, and an answer that assumed the other folder would come back empty.

`TheLibraryFixture` checks `builders.library` itself. Other test files
build on that fixture, and none of them would notice a case it silently lacks.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import unicodedata
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import mutagen
from PIL import Image

from agitha.server import Config, make_server
from tests import builders
from tests import test_agitha_server as neighbour

GENRES_FILE = neighbour.MUSIC / "musiclib" / "mb-genres.txt"
CONTRACT = builders.FIXTURES / "agitha" / "library"

SONATA = "S/Sonata Arctica"
PIANO = "#/植松伸夫/(1994) Piano Collections - Final Fantasy IV"
BARE = "O/Opeth/(2001) Blackwater Park"
SHUFFLED = "O/Opeth/(1998) My Arms, Your Hearse"

#: The raw key of a field in each family, as a track's `tags` spells it.
GENRE = {"id3": "TCON", "vorbis": "genre"}
TITLE = {"id3": "TIT2", "vorbis": "title"}


def address(path: str = "", tail: str = "") -> str:
    """The API address of a library-relative `path`, each segment quoted, then `tail` as written."""
    return "/api/library" + (f"/{quote(path)}" if path else "") + tail


def nfc(name: str) -> str:
    """`name` composed, so a filesystem that hands back decomposed names compares equal."""
    return unicodedata.normalize("NFC", name)


def lay_extras(shelf: Path) -> None:
    """What these cases need beyond `builders.library`: more folders to order, and albums the fixture does not hold."""
    # Made out of name order, so an answer in the order the folders were made is not in name order.
    for name in ("Symphony X", "Sabaton", "Slayer", "Saxon"):
        (shelf / "S" / name).mkdir()
    (shelf / "E").mkdir()
    # Neither is a letter folder: one is not a letter, the other is not a folder.
    (shelf / "lost+found").mkdir()
    (shelf / "Z").write_bytes(b"a file, not a letter folder\n")
    (shelf / "S" / "notes.txt").write_text("not an artist\n")
    (shelf / SONATA / "notes.txt").write_text("not an album\n")

    piano = builders.library_album(shelf, letter="#", artist="植松伸夫", date="1994-06-01",
                                   album="Piano Collections - Final Fantasy IV", discs=(("Prelude", "Theme of Love"),))
    (piano / "cover.jpg").write_bytes(builders.two_tone(600, 837))

    bare = builders.library_album(shelf, letter="O", artist="Opeth", date="2001-03-12", album="Blackwater Park",
                                  discs=(("The Leper Affinity", "Bleak"),))
    (bare / "cover.jpg").unlink()

    shuffled = builders.library_album(shelf, letter="O", artist="Opeth", date="1998-08-18",
                                      album="My Arms, Your Hearse", discs=(("April Ethereal", "When", "Madrigal"),))
    builders.write_tags(shuffled / "01. April Ethereal.flac", {"TRACKNUMBER": "3"})
    builders.write_tags(shuffled / "03. Madrigal.flac", {"TRACKNUMBER": "1"})


class LibraryCase(neighbour.ServerCase):
    """A server whose `--library` is `<tmp>/shelf`, laid by `lay` before the server starts."""

    shelf: Path

    @classmethod
    def lay(cls, shelf: Path) -> None:
        shelf.mkdir()

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        cls.folders = neighbour.make_folders(cls.root)
        # A decoy under the name the box uses. No answer may show it.
        (cls.folders["library"] / "X" / "Decoy").mkdir(parents=True)
        cls.shelf = cls.root / "shelf"
        cls.lay(cls.shelf)
        config = Config(
            inbox=cls.folders["inbox"], jobs=cls.folders["jobs"], library=cls.shelf,
            extras=cls.folders["extras"], musiclib=str(neighbour.STUB), static=cls.folders["static"],
            port=0, host="127.0.0.1",
        )
        cls.server = make_server(config)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    def answer(self, path: str) -> Any:
        """The JSON body of a 200 from `path`; anything else fails, showing what came back."""
        got = self.fetch(path)
        self.assertEqual(got.status, 200, f"GET {path} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        return json.loads(got.body)


class ShelfCase(LibraryCase):
    """The whole fixture library plus `lay_extras`, read and never written."""

    library: builders.Library

    @classmethod
    def lay(cls, shelf: Path) -> None:
        cls.library = builders.library(shelf)
        lay_extras(shelf)

    def album(self, name: str) -> tuple[builders.LibraryEntry, dict[str, Any]]:
        entry = self.library.albums[name]
        return entry, self.answer(address(entry.path))


class AnswersTheFolders(ShelfCase):
    def test_the_root_names_itself_and_lists_the_letters_that_exist_a_to_z_then_hash(self) -> None:
        body = self.answer(address())
        self.assertIs(body["readable"], True)
        self.assertEqual(Path(body["root"]).resolve(), self.shelf.resolve())
        # `#` sorts before every letter, and the page wants it last. `lost+found`,
        # the file `Z` and the decoy's `X` are not letter folders of this root.
        self.assertEqual(body["letters"], ["B", "D", "E", "L", "N", "O", "S", "#"])

    def test_a_letter_answers_its_artist_folders_in_name_order(self) -> None:
        body = self.answer(address("S"))
        self.assertEqual([artist["name"] for artist in body["artists"]],
                         ["Sabaton", "Saxon", "Slayer", "Sonata Arctica", "Symphony X"])

    def test_folders_that_differ_by_an_accent_are_each_an_artist(self) -> None:
        body = self.answer(address("B"))
        self.assertEqual(sorted(nfc(artist["name"]) for artist in body["artists"]),
                         sorted(["Babasonicos", "Babasónicos", "Babasonicós"]))
        for name in ("Babasonicos", "Babasónicos", "Babasonicós"):
            with self.subTest(artist=name):
                albums = self.answer(address(f"B/{name}"))["albums"]
                self.assertEqual([nfc(album["path"]) for album in albums],
                                 [entry.path for entry in self.library.under(f"B/{name}")])

    def test_an_artist_answers_its_album_folders_in_name_order_by_library_relative_path(self) -> None:
        body = self.answer(address(SONATA))
        names = ["(1997) FullMoon", "(1999) Ecliptica", "(2001) Silence", "(2003) Winterheart's Guild",
                 "(2012) Stones Grow Her Name"]
        self.assertEqual([album["name"] for album in body["albums"]], names)
        self.assertEqual([album["path"] for album in body["albums"]], [f"{SONATA}/{name}" for name in names])

    def test_an_empty_letter_and_an_empty_artist_answer_empty_lists(self) -> None:
        self.assertEqual(self.answer(address("E")), {"artists": []})
        # The panel reads `names` whatever the folder holds, so an artist with no albums still carries it.
        names = self.album("ecliptica")[1]["names"]
        self.assertEqual(self.answer(address("S/Sabaton")), {"albums": [], "names": names})

    def test_the_hash_letter_opens_to_an_artist_and_an_album_named_in_japanese(self) -> None:
        self.assertEqual(self.answer(address("#")), {"artists": [{"name": "植松伸夫"}]})
        self.assertEqual([album["path"] for album in self.answer(address("#/植松伸夫"))["albums"]], [PIANO])
        self.assertEqual(self.answer(address(PIANO))["path"], PIANO)


class ShowsAnAlbum(ShelfCase):
    def test_a_two_disc_album_answers_its_tracks_in_disc_then_track_order(self) -> None:
        entry, body = self.album("fragile")
        self.assertEqual(body["path"], entry.path)
        self.assertEqual([track["path"] for track in body["tracks"]], list(entry.tracks))
        self.assertEqual([(track["disc"], track["number"]) for track in body["tracks"]],
                         [(1, 1), (1, 2), (2, 1), (2, 2)])

    def test_tracks_come_in_the_order_of_the_numbers_they_carry_where_the_file_names_disagree(self) -> None:
        # The files are named 01, 02, 03 and tagged 3, 2, 1. Path order would answer them as named.
        body = self.answer(address(SHUFFLED))
        self.assertEqual([(track["number"], track["path"]) for track in body["tracks"]],
                         [(1, "03. Madrigal.flac"), (2, "02. When.flac"), (3, "01. April Ethereal.flac")])

    def test_each_track_carries_the_tags_its_file_holds_now(self) -> None:
        entry, body = self.album("discovery")
        titles = ["One More Time", "Aerodynamic", "Digital Love"]
        self.assertEqual([track["family"] for track in body["tracks"]], ["vorbis", "id3", "vorbis"])
        for track, title in zip(body["tracks"], titles, strict=True):
            with self.subTest(track=track["path"]):
                self.assertEqual(track["tags"][TITLE[track["family"]]], [title])
                self.assertEqual(track["tags"][GENRE[track["family"]]], list(entry.genres))
        flac, mp3 = body["tracks"][0], body["tracks"][1]
        self.assertEqual(flac["tags"]["artist"], ["Daft Punk"])
        self.assertEqual(flac["tags"]["musicbrainz_albumid"], [entry.release_id])
        self.assertEqual(flac["tags"]["rating"], ["4"])
        self.assertEqual(mp3["tags"]["TPE1"], ["Daft Punk"])
        self.assertEqual(mp3["tags"]["TXXX:MusicBrainz Album Id"], [entry.release_id])

    def test_an_embedded_picture_shows_as_its_kind_and_size_rather_than_its_bytes(self) -> None:
        entry, body = self.album("silence")
        track = body["tracks"][0]
        picture = mutagen.File(entry.folder / entry.tracks[0]).tags.getall("APIC")[0]
        self.assertEqual(track["tags"][picture.HashKey], [f"APIC ({len(picture.data)} bytes)"])

    def test_each_track_carries_the_facts_of_its_audio_and_the_size_and_time_it_was_loaded_at(self) -> None:
        entry, body = self.album("discovery")
        facts = [{key: track[key] for key in ("format", "lossless", "sample_rate", "bit_depth", "channels")}
                 for track in body["tracks"]]
        flac = {"format": "FLAC", "lossless": True, "sample_rate": 8000, "bit_depth": 16, "channels": 1}
        mp3 = {"format": "MP3", "lossless": False, "sample_rate": 8000, "bit_depth": None, "channels": 1}
        self.assertEqual(facts, [flac, mp3, flac])
        self.assertEqual([round(track["length"], 3) for track in body["tracks"]], [1.0, 1.152, 1.0])
        for track, rel in zip(body["tracks"], entry.tracks, strict=True):
            with self.subTest(track=rel):
                on_disk = (entry.folder / rel).stat()
                self.assertEqual(track["size"], on_disk.st_size)
                self.assertGreater(track["bitrate"], 0)
                # Seconds as the float `stat` gives, fraction and all: whole seconds cannot tell two
                # saves in one second apart, and nanoseconds are past what a browser's number holds.
                self.assertEqual(track["loaded"], {"size": on_disk.st_size, "mtime": on_disk.st_mtime})

    def test_a_tracks_audio_url_is_its_place_in_the_library_and_serves_the_files_bytes(self) -> None:
        # An apostrophe in the album and a disc folder in the path: both have to survive the URL.
        for name in ("winterheart", "fragile", "broken"):
            entry, body = self.album(name)
            for track, rel in zip(body["tracks"], entry.tracks, strict=True):
                with self.subTest(track=f"{entry.path}/{rel}"):
                    self.assertEqual(unquote(track["audio_url"]), f"/api/library/{entry.path}/audio/{rel}")
                    got = self.fetch(track["audio_url"])
                    self.assertEqual(got.status, 200)
                    self.assertTrue(got.headers["Content-Type"].startswith("audio/"), got.headers["Content-Type"])
                    self.assertEqual(got.body, (entry.folder / rel).read_bytes())

    def test_the_cover_is_cover_jpg_with_its_pixel_size_and_passes_the_cover_test(self) -> None:
        entry, body = self.album("ecliptica")
        cover = body["cover"]
        self.assertEqual({key: cover[key] for key in ("width", "height", "passes", "problem")},
                         {"width": 1500, "height": 1500, "passes": True, "problem": None})
        got = self.fetch(cover["url"])
        self.assertEqual(got.status, 200)
        self.assertTrue(got.headers["Content-Type"].startswith("image/jpeg"), got.headers["Content-Type"])
        # `front.jpg` and the tracks' embedded picture sit beside it, each with other bytes.
        self.assertEqual(got.body, (entry.folder / "cover.jpg").read_bytes())

    def test_a_cover_that_fails_the_cover_test_says_how(self) -> None:
        cover = self.answer(address(PIANO))["cover"]
        self.assertEqual({key: cover[key] for key in ("width", "height", "passes", "problem")},
                         {"width": 600, "height": 837, "passes": False,
                          "problem": "The cover is its width and height differ by more than 10 %."})

    def test_an_album_with_no_cover_jpg_has_no_cover_though_its_tracks_embed_one(self) -> None:
        body = self.answer(address(BARE))
        self.assertIsNone(body["cover"])
        self.assertEqual(len(body["tracks"]), 2)

    def test_a_file_whose_tags_cannot_be_read_is_listed_by_its_path_and_the_rest_is_shown(self) -> None:
        entry, body = self.album("images")
        self.assertEqual(body["unreadable"], ["03. Take the Time.flac"])
        self.assertEqual([track["path"] for track in body["tracks"]], list(entry.tracks))
        self.assertEqual(self.album("ecliptica")[1]["unreadable"], [])

    def test_the_release_id_is_the_one_the_tracks_carry_and_null_where_they_carry_none(self) -> None:
        entry, body = self.album("ecliptica")
        self.assertEqual(body["release_id"], entry.release_id)
        self.assertIsNone(self.album("fullmoon")[1]["release_id"])

    def test_an_album_nobody_is_matching_or_saving_has_no_match_and_no_job(self) -> None:
        _entry, body = self.album("ecliptica")
        self.assertIsNone(body["match"])
        self.assertIsNone(body["job"])

    def test_the_names_give_one_readable_name_to_the_same_field_of_an_mp3_and_a_flac(self) -> None:
        names = self.album("discovery")[1]["names"]
        self.assertEqual((names["id3"]["TIT2"], names["vorbis"]["title"]), ("Title", "Title"))
        self.assertEqual((names["id3"]["TCON"], names["vorbis"]["genre"]), ("Genre", "Genre"))


class ShowsAnArtist(ShelfCase):
    def track(self, name: str) -> dict[str, Any]:
        """The first track of the fixture album `name`, as the artist's answer carries it."""
        entry = self.library.albums[name]
        albums = {album["path"]: album for album in self.answer(address(SONATA))["albums"]}
        return albums[entry.path]["tracks"][0]

    def test_every_album_comes_with_every_track_and_its_tags(self) -> None:
        albums = self.answer(address(SONATA))["albums"]
        entries = self.library.under(SONATA)
        self.assertEqual([album["path"] for album in albums], [entry.path for entry in entries])
        for album, entry in zip(albums, entries, strict=True):
            with self.subTest(album=entry.path):
                self.assertEqual([track["path"] for track in album["tracks"]], list(entry.tracks))
                for track in album["tracks"]:
                    self.assertEqual(track["tags"][GENRE[track["family"]]], list(entry.genres))

    def test_an_album_summary_has_its_folder_name_year_title_and_cover(self) -> None:
        albums = {album["name"]: album for album in self.answer(address(SONATA))["albums"]}
        ecliptica = albums["(1999) Ecliptica"]
        self.assertEqual((ecliptica["year"], ecliptica["title"]), ("1999", "Ecliptica"))
        self.assertIsNone(ecliptica["match"])
        got = self.fetch(ecliptica["cover_url"])
        self.assertEqual(got.status, 200)
        self.assertEqual(got.body, (self.library.albums["ecliptica"].folder / "cover.jpg").read_bytes())

    def test_an_album_with_no_cover_jpg_has_no_cover_url(self) -> None:
        albums = {album["path"]: album for album in self.answer(address("O/Opeth"))["albums"]}
        self.assertIsNone(albums[BARE]["cover_url"])
        self.assertIsNotNone(albums[SHUFFLED]["cover_url"])

    def test_an_albums_tracks_are_the_ones_its_own_page_answers(self) -> None:
        for album in self.answer(address(SONATA))["albums"]:
            with self.subTest(album=album["path"]):
                self.assertEqual(album["tracks"], self.answer(address(album["path"]))["tracks"])

    def test_the_names_are_the_ones_an_albums_own_page_answers(self) -> None:
        # One panel shows over an album and over an artist, so a key reads the same on both.
        # What the album's `names` must hold is the album case's to say; here only that the two agree.
        self.assertEqual(self.answer(address(SONATA)).get("names"), self.album("silence")[1]["names"])

    def test_an_mp3_track_is_marked_with_its_ids_its_rating_and_its_picture_and_not_its_genre_or_title(self) -> None:
        track = self.track("silence")
        self.assertEqual(track["family"], "id3")
        refused = {
            "TXXX:MusicBrainz Album Id", "TXXX:MusicBrainz Release Group Id", "TXXX:MusicBrainz Artist Id",
            "TXXX:MusicBrainz Album Artist Id", "TXXX:MusicBrainz Release Track Id", "UFID:http://musicbrainz.org",
            "POPM:no@email", "APIC:picture 1",
        }
        # Every one is a key of this file, so a missing one is a key the panel would let the owner edit.
        self.assertLessEqual(refused, set(track["tags"]))
        self.assertEqual(refused - set(track["readonly"]), set())
        self.assertEqual({"TCON", "TIT2", "TPE2", "TALB"} & set(track["readonly"]), set())

    def test_a_flac_track_is_marked_with_its_ids_and_its_rating_and_not_its_genre_or_title(self) -> None:
        track = self.track("ecliptica")
        self.assertEqual(track["family"], "vorbis")
        refused = {
            "musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_trackid",
            "musicbrainz_releasetrackid", "musicbrainz_artistid", "musicbrainz_albumartistid", "rating",
        }
        self.assertLessEqual(refused, set(track["tags"]))
        self.assertEqual(refused - set(track["readonly"]), set())
        self.assertEqual({"genre", "title", "albumartist", "album"} & set(track["readonly"]), set())

    def test_a_track_with_no_ids_is_still_marked_with_its_rating_and_its_picture(self) -> None:
        track = self.track("fullmoon")
        self.assertEqual({"POPM:no@email", "APIC:picture 1"} - set(track["readonly"]), set())
        self.assertEqual({"TCON", "TIT2"} & set(track["readonly"]), set())

    def test_a_track_that_carries_the_added_time_is_marked_with_its_key_and_one_without_lists_none(self) -> None:
        # The review page locks the added time, so the library's panel does too.
        for name, key in (("silence", "TXXX:ADDED"), ("ecliptica", "added")):
            with self.subTest(album=name):
                track = self.track(name)
                self.assertIn(key, track["tags"])
                self.assertIn(key, track["readonly"])
        bare = self.track("fullmoon")
        self.assertEqual([key for key in bare["tags"] if "added" in key.casefold()], [])
        self.assertEqual([key for key in bare["readonly"] if "added" in key.casefold()], [])



class KeepsToTheContract(ShelfCase):
    """The answers carry the keys the page's fixtures carry, no more and no fewer.

    The JSON files belong to the page: its tests read them as what the
    server answers, so a key on one side alone is a page that works against a
    fixture and not against the server.
    """

    def contract(self, name: str) -> Any:
        path = CONTRACT / name
        if not path.is_file():
            self.fail(f"the contract fixture {path} is not there")
        return json.loads(path.read_text(encoding="utf-8"))

    def same_keys(self, got: dict[str, Any], want: dict[str, Any], what: str) -> None:
        self.assertEqual(sorted(got), sorted(want), what)

    def test_the_root_answer_has_the_keys_of_root_json(self) -> None:
        self.same_keys(self.answer(address()), self.contract("root.json"), "the root")

    def test_the_letter_answer_has_the_keys_of_letter_json(self) -> None:
        want, got = self.contract("letter.json"), self.answer(address("S"))
        self.same_keys(got, want, "a letter")
        for artist in got["artists"]:
            self.same_keys(artist, want["artists"][0], "an artist of a letter")

    def test_the_artist_answer_has_the_keys_of_artist_json(self) -> None:
        want, got = self.contract("artist.json"), self.answer(address(SONATA))
        self.same_keys(got, want, "an artist")
        want_album = want["albums"][0]
        want_track = want_album["tracks"][0]
        for album in got["albums"]:
            self.same_keys(album, want_album, f"the summary of {album.get('path')}")
            # MP3 and FLAC tracks both: the keys may not depend on the format.
            for track in album["tracks"]:
                self.same_keys(track, want_track, f"the track {track.get('path')}")
                self.same_keys(track["loaded"], want_track["loaded"], "a track's loaded")

    def test_the_album_answer_has_the_keys_of_album_json(self) -> None:
        want = self.contract("album.json")
        for name in ("images", "discovery", "fullmoon"):
            with self.subTest(album=name):
                got = self.answer(address(self.library.albums[name].path))
                self.same_keys(got, want, "an album")
                self.same_keys(got["cover"], want["cover"], "the cover")
                for track in got["tracks"]:
                    self.same_keys(track, want["tracks"][0], f"the track {track.get('path')}")
                    self.same_keys(track["loaded"], want["tracks"][0]["loaded"], "a track's loaded")

    def test_the_genres_answer_has_the_keys_of_genres_json(self) -> None:
        self.same_keys(self.answer("/api/genres"), self.contract("genres.json"), "the genres")


class RefusesWhatIsOutsideTheRoot(LibraryCase):
    """A path that leaves the root is a 404 that read nothing.

    A missing route is a 404 too, so each case first shows that the same
    route answers a path inside the root.
    """

    INSIDE = "S/Real Artist/(2000) Real"
    #: The outside album's only title: in its file name, its tags and so its bytes.
    MARK = b"SECRET TITLE"

    @classmethod
    def lay(cls, shelf: Path) -> None:
        builders.library_album(shelf, letter="S", artist="Real Artist", date="2000-01-01", album="Real",
                               discs=(("Inside",),))
        cls.outside = cls.root / "outside"
        cls.secret = builders.library_album(cls.outside, letter="Q", artist="Quiet Artist", date="2000-01-01",
                                            album="Secret", discs=((cls.MARK.decode(),),))
        (shelf / "Q").symlink_to(cls.outside / "Q", target_is_directory=True)
        (shelf / "S" / "Linked Artist").symlink_to(cls.secret.parent, target_is_directory=True)
        (shelf / "S" / "Real Artist" / "(2000) Linked").symlink_to(cls.secret, target_is_directory=True)
        (shelf / cls.INSIDE / "02. Linked.flac").symlink_to(cls.secret / f"01. {cls.MARK.decode()}.flac")

    def setUp(self) -> None:
        # Without these every refusal below would pass against a server with no library routes at all.
        self.assertEqual(self.answer(address("S"))["artists"][0].keys(), {"name"})
        self.assertEqual(self.answer(address(self.INSIDE))["path"], self.INSIDE)
        self.assertEqual(self.fetch(address(self.INSIDE, "/audio/01.%20Inside.flac")).status, 200)
        self.assertEqual(self.fetch(address(self.INSIDE, "/cover")).status, 200)

    def refused(self, paths: list[str]) -> None:
        for path in paths:
            with self.subTest(path=path):
                got = self.fetch(path)
                self.assertEqual(got.status, 404, got.body[:300])
                self.assertNotIn(self.MARK, got.body)

    def test_a_path_that_climbs_with_dots_plain_or_encoded_is_404(self) -> None:
        secret_file = f"outside/Q/Quiet%20Artist/%282000%29%20Secret/01.%20{quote(self.MARK.decode())}.flac"
        self.refused([
            "/api/library/..",
            "/api/library/%2E%2E",
            "/api/library/S/../../outside/Q",
            "/api/library/S/%2E%2E/%2E%2E/outside/Q",
            "/api/library/S/%2e%2e/%2e%2e/outside/Q/Quiet%20Artist",
            "/api/library/S/..%2F..%2Foutside%2FQ%2FQuiet%20Artist/%282000%29%20Secret",
            "/api/library/S/Real%20Artist/../../../outside/Q/Quiet%20Artist/%282000%29%20Secret",
            address(self.INSIDE, f"/audio/../../../../{secret_file}"),
            address(self.INSIDE, f"/audio/%2E%2E/%2E%2E/%2E%2E/%2E%2E/{secret_file}"),
            address(self.INSIDE, "/audio/../../../../outside/Q/Quiet%20Artist/%282000%29%20Secret/cover.jpg"),
        ])

    def test_an_absolute_path_in_any_place_of_the_address_is_404(self) -> None:
        # Joined to the root as written, an absolute segment replaces the root.
        letter, artist, album = self.outside / "Q", self.secret.parent, self.secret
        track = album / f"01. {self.MARK.decode()}.flac"
        self.refused([
            f"/api/library/{quote(str(letter), safe='')}",
            f"/api/library/{quote(str(letter))}",
            f"/api/library/S/{quote(str(artist), safe='')}",
            f"/api/library/S/Real%20Artist/{quote(str(album), safe='')}",
            f"/api/library/S/Real%20Artist{quote(str(album))}",
            address(self.INSIDE, f"/audio/{quote(str(track), safe='')}"),
            address(self.INSIDE, f"/audio/{quote(str(track))}"),
            address(self.INSIDE, f"/audio{quote(str(track))}"),
        ])

    def test_a_symlink_that_leads_out_of_the_root_is_404_as_a_letter_an_artist_an_album_or_a_track(self) -> None:
        self.refused([
            address("Q"),
            address("Q/Quiet Artist"),
            address("Q/Quiet Artist/(2000) Secret"),
            address("S/Linked Artist"),
            address("S/Linked Artist/(2000) Secret"),
            address("S/Linked Artist/(2000) Secret", "/cover"),
            address("S/Real Artist/(2000) Linked"),
            address("S/Real Artist/(2000) Linked", f"/audio/01.%20{quote(self.MARK.decode())}.flac"),
            address(self.INSIDE, "/audio/02.%20Linked.flac"),
        ])


class SaysTheRootIsMissing(LibraryCase):
    @classmethod
    def lay(cls, shelf: Path) -> None:
        """Nothing: `--library` names a folder that is not there."""

    def test_a_missing_root_is_named_as_unreadable_with_no_letters(self) -> None:
        body = self.answer(address())
        self.assertIs(body["readable"], False)
        self.assertEqual(body["letters"], [])
        self.assertEqual(Path(body["root"]).resolve(), self.shelf.resolve())


@unittest.skipIf(os.geteuid() == 0, "root reads a folder whatever its mode")
class SaysTheRootIsUnreadable(LibraryCase):
    @classmethod
    def lay(cls, shelf: Path) -> None:
        (shelf / "S" / "Sonata Arctica").mkdir(parents=True)
        shelf.chmod(0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shelf.chmod(0o755)
        super().tearDownClass()

    def test_a_root_that_cannot_be_listed_is_named_as_unreadable_with_no_letters(self) -> None:
        body = self.answer(address())
        self.assertIs(body["readable"], False)
        self.assertEqual(body["letters"], [])
        self.assertEqual(Path(body["root"]).resolve(), self.shelf.resolve())


class ListsTheGenres(LibraryCase):
    def test_the_list_is_every_line_of_the_official_file_and_the_two_custom_genres_and_nothing_else(self) -> None:
        official = GENRES_FILE.read_text(encoding="utf-8").splitlines()
        self.assertIn("power metal", official)
        genres = self.answer("/api/genres")["genres"]
        self.assertEqual(set(genres) ^ ({*official, "soundtrack", "video game music"}), set())
        # Neither custom genre is on the official list, so a doubled name is a bug and not an overlap.
        self.assertEqual(len(genres), len(set(genres)))

    def test_the_list_is_sorted(self) -> None:
        # Only the one-word names in plain letters are compared: every way of
        # sorting text agrees on those.
        genres = self.answer("/api/genres")["genres"]
        plain = [genre for genre in genres if re.fullmatch(r"[a-z]+", genre)]
        self.assertGreater(len(plain), 300)
        self.assertEqual(plain, sorted(plain))


def _tag(path: Path, field: str) -> list[str]:
    """The values of a `builders.PICARD_KEYS` field as the file holds them, whatever the format; `[]` where absent."""
    ext = path.suffix.lstrip(".")
    key = builders.picard_key(ext, field)
    for found, values in builders.read_tags(path).items():
        if found.casefold() == key.casefold():
            return [values.decode("ascii")] if isinstance(values, bytes) else [str(value) for value in values]
    return []


def _folded(name: str) -> str:
    """`name` without its accents and without case."""
    return "".join(c for c in unicodedata.normalize("NFD", name) if not unicodedata.combining(c)).casefold()


def _tones(data: bytes) -> int:
    """How many grey levels an 8 by 8 thumbnail of the picture has; 1 for a flat picture."""
    with Image.open(io.BytesIO(data)) as image:
        return len(set(image.convert("L").resize((8, 8)).tobytes()))


def _embedded(path: Path) -> list[bytes]:
    found = mutagen.File(path)
    if path.suffix == ".flac":
        return [picture.data for picture in found.pictures]
    return [frame.data for frame in found.tags.getall("APIC")]


class TheLibraryFixture(unittest.TestCase):
    """`builders.library` holds each case its docstring names, on disk as described."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.library = builders.library(Path(cls.tmp.name) / "shelf")
        cls.albums = cls.library.albums

    def tracks(self, name: str) -> list[Path]:
        entry = self.albums[name]
        return [entry.folder / rel for rel in entry.tracks]

    def test_every_handle_is_an_album_folder_three_deep_holding_the_tracks_it_names(self) -> None:
        on_disk = sorted(nfc(path.relative_to(self.library.root).as_posix())
                         for path in self.library.root.glob("*/*/*") if path.is_dir())
        self.assertEqual(on_disk, sorted(entry.path for entry in self.albums.values()))
        for name, entry in self.albums.items():
            with self.subTest(album=name):
                self.assertEqual(entry.folder, self.library.root / entry.path)
                audio = sorted(path.relative_to(entry.folder).as_posix() for path in entry.folder.rglob("*")
                               if path.suffix in (".mp3", ".flac"))
                self.assertEqual(audio, sorted(entry.tracks + entry.unreadable))
                for path in self.tracks(name):
                    self.assertEqual(_tag(path, "genre"), list(entry.genres))
                    self.assertEqual(_tag(path, "release id"), [entry.release_id] if entry.release_id else [])
                    self.assertEqual(_tag(path, "album artist id"), list(entry.artist_ids))

    def test_no_two_folders_differ_by_case_alone(self) -> None:
        # The MacBook's filesystem folds case: two such folders would be one, and a later test would pass on the box only.
        folders = {entry.path.rsplit("/", depth)[0] for entry in self.albums.values() for depth in (0, 1)}
        self.assertEqual(len({folder.casefold() for folder in folders}), len(folders))

    def test_one_artist_has_four_albums_with_ids_and_three_of_them_carry_power_metal(self) -> None:
        with_ids = [entry for entry in self.library.under(SONATA) if entry.release_id]
        self.assertEqual(len(with_ids), 4)
        self.assertEqual({entry.artist_ids for entry in with_ids}, {(builders.SONATA_ARCTICA_ID,)})
        self.assertEqual(len({entry.release_id for entry in with_ids}), 4)
        carrying = self.library.carrying("power metal")
        self.assertEqual([entry.path for entry in carrying],
                         [f"{SONATA}/(1999) Ecliptica", f"{SONATA}/(2001) Silence",
                          f"{SONATA}/(2003) Winterheart's Guild"])
        self.assertTrue(set(carrying) <= set(with_ids))

    def test_that_artists_folder_holds_a_fifth_album_with_no_musicbrainz_id_in_any_tag(self) -> None:
        entry = self.albums["fullmoon"]
        self.assertEqual(entry.path, f"{SONATA}/(1997) FullMoon")
        self.assertEqual((entry.release_id, entry.artist_ids), (None, ()))
        for path in self.tracks("fullmoon"):
            keys = [key for key in builders.read_tags(path) if "musicbrainz" in key.casefold()]
            self.assertEqual(keys, [], path.name)
            self.assertEqual(_tag(path, "title"), [path.stem.split(". ", 1)[1]])

    def test_one_artist_id_sits_under_two_folders_that_differ_by_an_accent(self) -> None:
        plain, accented = self.albums["miami"], self.albums["jessico"]
        self.assertEqual(plain.path.split("/")[:2], ["B", "Babasonicos"])
        self.assertEqual(accented.path.split("/")[:2], ["B", "Babasónicos"])
        self.assertEqual(plain.artist_ids, (builders.BABASONICOS_ID,))
        self.assertEqual(accented.artist_ids, (builders.BABASONICOS_ID,))
        self.assertEqual(sorted(nfc(path.name) for path in (self.library.root / "B").iterdir()),
                         ["Babasonicos", "Babasonicós", "Babasónicos"])

    def test_a_third_folder_folds_to_the_same_name_and_its_album_carries_another_id(self) -> None:
        namesake = self.albums["namesake"]
        folders = {self.albums[name].path.split("/")[1] for name in ("miami", "jessico", "namesake")}
        self.assertEqual(len(folders), 3)
        self.assertEqual({_folded(folder) for folder in folders}, {"babasonicos"})
        self.assertEqual(namesake.artist_ids, (builders.BABASONICOS_NAMESAKE_ID,))
        self.assertNotEqual(builders.BABASONICOS_NAMESAKE_ID, builders.BABASONICOS_ID)

    def test_one_albums_album_artist_tag_holds_two_ids(self) -> None:
        for path in self.tracks("lulu"):
            self.assertEqual(_tag(path, "album artist id"), [builders.LOU_REED_ID, builders.METALLICA_ID])

    def test_one_album_has_two_discs_in_cd_folders(self) -> None:
        self.assertEqual(self.albums["fragile"].tracks,
                         ("CD1/01. Somewhat Damaged.flac", "CD1/02. The Day the World Went Away.flac",
                          "CD2/01. The Way Out Is Through.flac", "CD2/02. Into the Void.flac"))
        self.assertEqual([builders.read_tags(path)["DISCNUMBER"] for path in self.tracks("fragile")],
                         [["1"], ["1"], ["2"], ["2"]])

    def test_one_album_mixes_mp3_and_flac_and_both_kinds_are_tagged(self) -> None:
        paths = self.tracks("discovery")
        self.assertEqual([path.suffix for path in paths], [".flac", ".mp3", ".flac"])
        self.assertEqual([_tag(path, "title") for path in paths],
                         [["One More Time"], ["Aerodynamic"], ["Digital Love"]])
        self.assertEqual([type(mutagen.File(path)).__name__ for path in paths], ["FLAC", "MP3", "FLAC"])

    def test_one_folder_has_the_ep_prefix_and_an_edition_suffix(self) -> None:
        self.assertEqual(self.albums["broken"].folder.name, "(1992) [EP] Broken [Japanese edition]")

    def test_one_file_is_named_like_a_track_and_cannot_be_read(self) -> None:
        entry = self.albums["images"]
        self.assertEqual(entry.unreadable, ("03. Take the Time.flac",))
        with self.assertRaises(mutagen.MutagenError):
            mutagen.File(entry.folder / entry.unreadable[0])
        self.assertEqual([name for name, other in self.albums.items() if other.unreadable], ["images"])

    def test_every_album_has_three_pictures_beside_its_tracks_and_no_two_are_alike(self) -> None:
        seen: set[bytes] = set()
        for name, entry in self.albums.items():
            with self.subTest(album=name):
                pictures = [(entry.folder / f"{side}.jpg").read_bytes() for side in ("cover", "front", "back")]
                with Image.open(io.BytesIO(pictures[0])) as cover:
                    self.assertEqual(cover.size, entry.cover)
                # A flat picture hides picture logic: every flat picture has the same average hash.
                self.assertEqual([_tones(data) > 1 for data in pictures], [True, True, True])
                self.assertEqual(len(set(pictures)), 3)
                self.assertNotIn(pictures[0], seen)
                seen.add(pictures[0])

    def test_every_track_embeds_its_albums_cover_at_1200_px(self) -> None:
        for name in self.albums:
            for path in self.tracks(name):
                with self.subTest(track=path.name):
                    embedded = _embedded(path)
                    self.assertEqual(len(embedded), 1)
                    with Image.open(io.BytesIO(embedded[0])) as image:
                        self.assertEqual(image.size, (1200, 1200))
                    self.assertGreater(_tones(embedded[0]), 1)
                    self.assertNotEqual(embedded[0], (self.albums[name].folder / "cover.jpg").read_bytes())

    def test_the_first_track_of_every_album_is_rated_and_no_other(self) -> None:
        for name in self.albums:
            with self.subTest(album=name):
                rated = []
                for path in self.tracks(name):
                    tags = {key.casefold(): value for key, value in builders.read_tags(path).items()}
                    rated.append("rating" in tags or "popm:no@email" in tags)
                self.assertEqual(rated, [True] + [False] * (len(rated) - 1))

    def test_every_track_of_an_album_with_ids_carries_added_and_the_album_without_carries_none(self) -> None:
        for name, entry in self.albums.items():
            for path in self.tracks(name):
                with self.subTest(track=f"{name}/{path.name}"):
                    tags = {key.casefold(): value for key, value in builders.read_tags(path).items()}
                    added = tags.get("txxx:added") or tags.get("added")
                    if entry.release_id:
                        self.assertRegex(added[0], r"^2026-09-\d\dT18:30$")
                    else:
                        self.assertIsNone(added)


if __name__ == "__main__":
    unittest.main()
