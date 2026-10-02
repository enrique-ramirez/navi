"""Paths follow tags: what `POST /api/library/preview` answers when a draft changes a tag a path part is made from.

The server runs on a thread over temporary folders and is spoken to over
HTTP, with the helpers of `tests.test_agitha_library`. A preview plans and
writes nothing, so every case here reads the answer and then checks that the
library and the extras folder hold what they held before the request. The
landing of a move is `tests.test_agitha_save`'s.

Every expected name is written out by hand from `docs/music-library.md`
*Layout*. None is computed with `musiclib.names`, which would only say the
server calls it.
"""

from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any

from tests import builders
from tests import test_agitha_library as shelf_tests

PREVIEW = "/api/library/preview"
TAKEN = "already in the library"

SONATA = "S/Sonata Arctica"
#: Its files are named 01, 02, 03 and tagged 3, 2, 1.
SHUFFLED = "O/Opeth/(1998) My Arms, Your Hearse"
#: Its folder holds more than its album tag, which is `Blackwater Park`.
LEGACY = "O/Opeth/(2001) Blackwater Park - Legacy Edition"
#: An album folder of the name `ecliptica` would take under `The Strokes`.
STROKES = "S/Strokes, The/(1999) Ecliptica"
#: One medium of a hundred tracks, so its files carry three digits.
HUNDRED = "M/Merzbow/(2000) Merzbox Sampler"

#: Sixty words of five bytes and four characters each: 359 bytes, past any name.
LONG = " ".join(["añil"] * 60)


def lay(shelf: Path) -> builders.Library:
    """`builders.library` and the four albums these cases need beyond it."""
    library = builders.library(shelf)
    shuffled = builders.library_album(shelf, letter="O", artist="Opeth", date="1998-08-18",
                                      album="My Arms, Your Hearse", discs=(("April Ethereal", "When", "Madrigal"),))
    builders.write_tags(shuffled / "01. April Ethereal.flac", {"TRACKNUMBER": "3"})
    builders.write_tags(shuffled / "03. Madrigal.flac", {"TRACKNUMBER": "1"})
    builders.library_album(shelf, letter="O", artist="Opeth", date="2001-03-12", album="Blackwater Park",
                           folder="(2001) Blackwater Park - Legacy Edition", discs=(("The Leper Affinity", "Bleak"),))
    builders.library_album(shelf, letter="S", artist="Strokes, The", date="1999-01-01", album="Ecliptica",
                           discs=(("Soma",),))
    builders.library_album(shelf, letter="M", artist="Merzbow", date="2000-01-01", album="Merzbox Sampler",
                           discs=(tuple(f"Part {number}" for number in range(1, 101)),))
    return library


class PathsCase(shelf_tests.LibraryCase):
    """A server over the fixture library, asked for previews and never for a save."""

    library: builders.Library

    @classmethod
    def lay(cls, shelf: Path) -> None:
        cls.library = lay(shelf)

    def path(self, handle: str) -> str:
        return self.library.albums[handle].path

    def on_disk(self) -> dict[str, bytes | None]:
        return {f"{name}/{rel}": held for name in ("shelf", "extras")
                for rel, held in builders.tree(self.root / name).items()}

    def post(self, body: object) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("POST", PREVIEW, body=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def preview(self, path: str, change: dict[str, list[str]], tracks: tuple[str, ...] | None = None) -> dict[str, Any]:
        """The preview of the album at `path` for a draft of one edit: `change` set on `tracks`, or on every track."""
        return self.preview_edits(path, (change, tracks))

    def preview_edits(self, path: str, *edits: tuple[dict[str, list[str]], tuple[str, ...] | None]) -> dict[str, Any]:
        """The preview of the album at `path` for a draft of `edits`, each a `(change, tracks)` set in that order.

        The draft is the one the page would send: each track an edit names,
        once, with the size and time the album route answered and the values
        it showed for every key an edit sets on it.
        """
        view = self.answer(shelf_tests.address(path))
        held = [track["path"] for track in view["tracks"]]
        keys: dict[str, list[str]] = {}
        wire = []
        for change, tracks in edits:
            named = held if tracks is None else list(tracks)
            # A track path that names nothing would draft nothing and pass every "nothing moved".
            self.assertEqual([rel for rel in named if rel not in held], [], "the album holds no such track")
            for rel in named:
                keys.setdefault(rel, []).extend(change)
            wire.append({"tracks": [{"album": path, "path": rel} for rel in named],
                         "set": change, "add": {}, "remove": {}})
        drafted = []
        for track in view["tracks"]:
            if track["path"] in keys:
                raw = {name: key for key, name in view["names"][track["family"]].items()}
                drafted.append({"album": path, "path": track["path"], "loaded": track["loaded"],
                                "seen": {key: track["tags"].get(raw[key]) for key in keys[track["path"]]}})
        draft = {"tracks": drafted, "edits": wire, "swaps": [], "cover": None, "batch": False}

        before = self.on_disk()
        status, body = self.post(draft)
        after = self.on_disk()
        self.assertEqual(status, 200, f"POST {PREVIEW} answered {status}: {body[:300]!r}")
        # Names only: the bytes of a library make a diff nobody reads.
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name, 0) != after.get(name, 0))
        self.assertEqual(changed, [], "a preview changed these on disk")
        albums = json.loads(body)["albums"]
        self.assertEqual([album["path"] for album in albums], [path])
        return albums[0]

    def renames(self, album: dict[str, Any]) -> dict[str, str]:
        """Each listed track's new path by its path."""
        return {track["path"]: track["new_path"] for track in album["tracks"]}

    def taken(self, album: dict[str, Any]) -> list[str]:
        """The paths the preview says are already in the library. Problems of other rules are not these cases'."""
        return [problem["detail"] for problem in album["problems"] if problem["rule"] == TAKEN]

    def assert_moves_nothing(self, album: dict[str, Any]) -> None:
        self.assertEqual(album["new_path"], album["path"])
        self.assertEqual([track for track in album["tracks"] if track["new_path"] != track["path"]], [])
        self.assertEqual(self.taken(album), [])


class RenamesTheFile(PathsCase):
    def test_a_changed_title_renames_that_file_and_nothing_else(self) -> None:
        path = self.path("ecliptica")
        album = self.preview(path, {"Title": ["Replica"]}, tracks=("02. My Land.flac",))
        self.assertEqual(album["new_path"], path)
        # The other two tracks do not change, so they are not listed at all.
        self.assertEqual(self.renames(album), {"02. My Land.flac": "02. Replica.flac"})
        self.assertIn({"key": "Title", "before": ["My Land"], "after": ["Replica"]}, album["tracks"][0]["changes"])
        self.assertEqual(self.taken(album), [])

    def test_two_edits_that_each_retitle_one_track_rename_both_files_and_nothing_else(self) -> None:
        path = self.path("ecliptica")
        album = self.preview_edits(path, ({"Title": ["Replica"]}, ("01. Blank File.flac",)),
                                   ({"Title": ["Kingdom for a Heart"]}, ("03. 8th Commandment.flac",)))
        self.assertEqual(album["new_path"], path)
        self.assertEqual(self.renames(album), {"01. Blank File.flac": "01. Replica.flac",
                                               "03. 8th Commandment.flac": "03. Kingdom for a Heart.flac"})
        self.assertEqual(self.taken(album), [])

    def test_one_title_on_a_flac_and_an_mp3_leaves_each_its_own_number_and_extension(self) -> None:
        album = self.preview(self.path("discovery"), {"Title": ["Interlude"]})
        self.assertEqual(self.renames(album), {
            "01. One More Time.flac": "01. Interlude.flac",
            "02. Aerodynamic.mp3": "02. Interlude.mp3",
            "03. Digital Love.flac": "03. Interlude.flac",
        })

    def test_a_changed_track_number_renumbers_that_file_and_keeps_its_title(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Track number": ["7"]}, tracks=("01. Blank File.flac",))
        self.assertEqual(self.renames(album), {"01. Blank File.flac": "07. Blank File.flac"})
        self.assertEqual(album["new_path"], album["path"])

    def test_an_mp3s_track_number_is_the_number_before_the_slash(self) -> None:
        # An MP3 holds `1/2` in one frame. The file name takes the 4 of `4/9`, as the album route's `number` does.
        album = self.preview(self.path("silence"), {"Track number": ["4/9"]}, tracks=("01. Weballergy.mp3",))
        self.assertEqual(self.renames(album), {"01. Weballergy.mp3": "04. Weballergy.mp3"})

    def test_a_file_on_a_medium_of_a_hundred_tracks_keeps_three_digits(self) -> None:
        album = self.preview(HUNDRED, {"Title": ["Seventh"]}, tracks=("007. Part 7.flac",))
        self.assertEqual(self.renames(album), {"007. Part 7.flac": "007. Seventh.flac"})

    def test_a_changed_disc_number_moves_the_file_to_that_cd_folder_under_the_name_it_had(self) -> None:
        album = self.preview(self.path("fragile"), {"Disc number": ["2"]},
                             tracks=("CD1/02. The Day the World Went Away.flac",))
        self.assertEqual(self.renames(album),
                         {"CD1/02. The Day the World Went Away.flac": "CD2/02. The Day the World Went Away.flac"})
        self.assertEqual(album["new_path"], album["path"])
        # `CD2` holds an `02.` of another title. Two files, two names.
        self.assertEqual(self.taken(album), [])

    def test_the_characters_windows_cannot_hold_are_written_as_the_table_says(self) -> None:
        table = {
            "Wish: Live": "02. Wish - Live.flac",
            "Re:Load": "02. Re-Load.flac",
            "AC/DC": "02. AC-DC.flac",
            "Back\\Slash": "02. Back-Slash.flac",
            "Why? *Not* <Now> A|B": "02. Why Not Now AB.flac",
            '"Heroes"': "02. ''Heroes''.flac",
            # The full stops go before the extension is put on, or the name would end `Etc....flac`.
            "Etc...": "02. Etc.flac",
        }
        for title, name in table.items():
            with self.subTest(title=title):
                album = self.preview(self.path("ecliptica"), {"Title": [title]}, tracks=("02. My Land.flac",))
                self.assertEqual(self.renames(album), {"02. My Land.flac": name})
                # The tag keeps the title as typed. Only the name loses the characters.
                self.assertIn({"key": "Title", "before": ["My Land"], "after": [title]}, album["tracks"][0]["changes"])

    def test_a_title_too_long_for_a_name_is_cut_at_the_last_whole_word_that_fits_255_bytes(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Title": [LONG]}, tracks=("02. My Land.flac",))
        # 4 bytes of number, 40 words (239 bytes), 6 of mark and 5 of extension: 254. A 41st word would make 260.
        # Counted in characters the title would keep 49 words and the name would be 304 bytes.
        name = "02. " + " ".join(["añil"] * 40) + " [...].flac"
        self.assertEqual(len(name.encode()), 254)
        self.assertEqual(self.renames(album), {"02. My Land.flac": name})


class RenamesTheAlbumFolder(PathsCase):
    def test_a_changed_year_renames_the_folder_and_no_file(self) -> None:
        path = self.path("ecliptica")
        album = self.preview(path, {"Date": ["2008-05-01"]})
        self.assertEqual(album["new_path"], f"{SONATA}/(2008) Ecliptica")
        self.assertEqual(self.renames(album), {rel: rel for rel in self.library.albums["ecliptica"].tracks})
        for track in album["tracks"]:
            self.assertIn({"key": "Date", "before": ["1999-11-22"], "after": ["2008-05-01"]}, track["changes"])
        self.assertEqual(self.taken(album), [])

    def test_a_date_changed_within_its_year_moves_nothing(self) -> None:
        album = self.preview(self.path("broken"), {"Date": ["1992-12-01"]})
        self.assert_moves_nothing(album)
        # The tag still changes: the folder staying is not the draft being dropped.
        self.assertEqual(sorted(self.renames(album)), sorted(self.library.albums["broken"].tracks))

    def test_a_changed_year_keeps_the_ep_prefix_and_the_edition_suffix(self) -> None:
        album = self.preview(self.path("broken"), {"Date": ["1994-09-22"]})
        self.assertEqual(album["new_path"], "N/Nine Inch Nails/(1994) [EP] Broken [Japanese edition]")

    def test_a_changed_album_title_renames_the_folder_between_its_prefix_and_its_suffix(self) -> None:
        album = self.preview(self.path("broken"), {"Album": ["Fixed"]})
        self.assertEqual(album["new_path"], "N/Nine Inch Nails/(1992) [EP] Fixed [Japanese edition]")
        self.assertEqual(self.renames(album), {rel: rel for rel in self.library.albums["broken"].tracks})

    def test_a_changed_album_title_keeps_the_year_and_loses_the_characters_windows_cannot_hold(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Album": ["Ecliptica: Revisited?"]})
        self.assertEqual(album["new_path"], f"{SONATA}/(1999) Ecliptica - Revisited")

    def test_an_album_title_too_long_for_a_name_is_cut_before_the_edition_suffix(self) -> None:
        album = self.preview(self.path("broken"), {"Album": [LONG]})
        # 12 bytes of year and prefix, 36 words (215 bytes), 6 of mark, 19 of suffix: 252. A 37th word would make 258.
        name = "(1992) [EP] " + " ".join(["añil"] * 36) + " [...] [Japanese edition]"
        self.assertEqual(len(name.encode()), 252)
        self.assertEqual(album["new_path"], f"N/Nine Inch Nails/{name}")


class MovesTheAlbumUnderItsArtist(PathsCase):
    def test_a_changed_album_artist_moves_the_album_under_the_new_letter_and_artist_folder(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Album artist": ["The Band"]})
        self.assertEqual(album["new_path"], "B/Band, The/(1999) Ecliptica")
        self.assertEqual(self.renames(album), {rel: rel for rel in self.library.albums["ecliptica"].tracks})
        self.assertEqual(self.taken(album), [])

    def test_the_artist_folder_and_its_letter_follow_the_layout(self) -> None:
        folders = {
            # The fallback list of leading articles, and the letter of what is left.
            "Los Ángeles Azules": "A/Ángeles Azules, Los",
            "Die Toten Hosen": "T/Toten Hosen, Die",
            "A Perfect Circle": "P/Perfect Circle, A",
            "L'Impératrice": "I/Impératrice, L'",
            # A person is not turned round, and a word that only starts like an article is not one.
            "Joaquín Sabina": "J/Joaquín Sabina",
            "Theatre of Tragedy": "T/Theatre of Tragedy",
            "Øystein Sevåg": "O/Øystein Sevåg",
            "Вася Обломов": "#/Вася Обломов",
            "2Pac": "#/2Pac",
            ".38 Special": "#/_38 Special",
            "-M-": "#/_M-",
            "AC/DC": "A/AC-DC",
            "Therapy?": "T/Therapy",
        }
        for artist, folder in folders.items():
            with self.subTest(artist=artist):
                album = self.preview(self.path("ecliptica"), {"Album artist": [artist]})
                self.assertEqual(album["new_path"], f"{folder}/(1999) Ecliptica")

    def test_an_artist_folder_that_exists_takes_the_album_in(self) -> None:
        album = self.preview(self.path("lulu"), {"Album artist": ["Sonata Arctica"]})
        self.assertEqual(album["new_path"], f"{SONATA}/(2011) Lulu")
        # The artist folder is there and the album folder is not. Only the second is a collision.
        self.assertEqual(self.taken(album), [])


class LeavesThePartsNoChangedTagNames(PathsCase):
    def test_an_artist_folder_spelt_unlike_its_tag_stays_when_a_title_changes(self) -> None:
        # The tag says `Babasónicos` and the folder `Babasonicos`. A rebuild from the tags would move the album.
        path = self.path("miami")
        album = self.preview(path, {"Title": ["Sin favor"]}, tracks=("01. Desfachatados.mp3",))
        self.assertEqual(album["new_path"], path)
        self.assertEqual(self.renames(album), {"01. Desfachatados.mp3": "01. Sin favor.mp3"})

    def test_an_artist_folder_spelt_unlike_its_tag_stays_when_the_year_changes(self) -> None:
        album = self.preview(self.path("miami"), {"Date": ["2005-01-01"]})
        self.assertEqual(album["new_path"], "B/Babasonicos/(2005) Miami")

    def test_an_album_folder_spelt_unlike_its_tag_stays_when_a_title_changes(self) -> None:
        album = self.preview(LEGACY, {"Title": ["Harvest"]}, tracks=("02. Bleak.flac",))
        self.assertEqual(album["new_path"], LEGACY)
        self.assertEqual(self.renames(album), {"02. Bleak.flac": "02. Harvest.flac"})

    def test_an_album_folder_spelt_unlike_its_tag_goes_as_it_is_under_a_new_artist(self) -> None:
        album = self.preview(LEGACY, {"Album artist": ["The Band"]})
        self.assertEqual(album["new_path"], "B/Band, The/(2001) Blackwater Park - Legacy Edition")

    def test_an_ep_folder_with_an_edition_goes_as_it_is_under_a_new_artist(self) -> None:
        album = self.preview(self.path("broken"), {"Album artist": ["The Band"]})
        self.assertEqual(album["new_path"], "B/Band, The/(1992) [EP] Broken [Japanese edition]")

    def test_files_numbered_unlike_their_tags_stay_when_the_year_or_the_artist_changes(self) -> None:
        # `01. April Ethereal.flac` is tagged track 3. Neither draft names its number or its title.
        files = ["01. April Ethereal.flac", "02. When.flac", "03. Madrigal.flac"]
        for change, folder in (({"Date": ["2000-01-01"]}, "O/Opeth/(2000) My Arms, Your Hearse"),
                               ({"Album artist": ["The Band"]}, "B/Band, The/(1998) My Arms, Your Hearse")):
            with self.subTest(change=change):
                album = self.preview(SHUFFLED, change)
                self.assertEqual(album["new_path"], folder)
                self.assertEqual(self.renames(album), {rel: rel for rel in files})

    def test_a_file_stays_in_its_cd_folder_when_its_title_changes(self) -> None:
        album = self.preview(self.path("fragile"), {"Title": ["Pilgrimage"]}, tracks=("CD2/02. Into the Void.flac",))
        self.assertEqual(self.renames(album), {"CD2/02. Into the Void.flac": "CD2/02. Pilgrimage.flac"})


class NamesWhatIsAlreadyInTheLibrary(PathsCase):
    def test_a_new_folder_that_is_another_album_is_named_by_its_library_path(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Date": ["2001-06-21"], "Album": ["Silence"]})
        self.assertEqual(album["new_path"], self.path("silence"))
        self.assertEqual(self.taken(album), [f"{SONATA}/(2001) Silence"])

    def test_a_new_artist_who_holds_a_folder_of_that_name_is_a_collision_too(self) -> None:
        album = self.preview(self.path("ecliptica"), {"Album artist": ["The Strokes"]})
        self.assertEqual(self.taken(album), [STROKES])

    def test_a_folder_renamed_in_case_alone_is_this_album_and_not_a_collision(self) -> None:
        # On the MacBook `(1999) ecliptica` exists: it is this album under another case. On the box it does not.
        album = self.preview(self.path("ecliptica"), {"Album": ["ecliptica"]})
        self.assertEqual(album["new_path"], f"{SONATA}/(1999) ecliptica")
        self.assertEqual(self.taken(album), [])

    def test_a_track_taking_the_name_of_one_the_draft_leaves_alone_is_named_by_the_path_both_would_hold(self) -> None:
        path = self.path("ecliptica")
        album = self.preview(path, {"Track number": ["1"], "Title": ["Blank File"]}, tracks=("02. My Land.flac",))
        self.assertEqual(set(self.taken(album)), {f"{path}/01. Blank File.flac"})

    def test_two_drafted_tracks_taking_one_name_are_named_by_the_path_both_would_hold(self) -> None:
        path = self.path("ecliptica")
        album = self.preview(path, {"Track number": ["5"], "Title": ["Same"]},
                             tracks=("01. Blank File.flac", "02. My Land.flac"))
        self.assertEqual(set(self.taken(album)), {f"{path}/05. Same.flac"})

    def test_a_track_moved_to_a_disc_where_its_name_is_held_is_named_with_the_cd_folder(self) -> None:
        path = self.path("fragile")
        album = self.preview(path, {"Disc number": ["2"], "Title": ["The Way Out Is Through"]},
                             tracks=("CD1/01. Somewhat Damaged.flac",))
        self.assertEqual(set(self.taken(album)), {f"{path}/CD2/01. The Way Out Is Through.flac"})

    def test_one_number_and_title_on_a_flac_and_an_mp3_are_two_file_names(self) -> None:
        album = self.preview(self.path("discovery"), {"Track number": ["5"], "Title": ["Same"]},
                             tracks=("01. One More Time.flac", "02. Aerodynamic.mp3"))
        self.assertEqual(self.renames(album), {"01. One More Time.flac": "05. Same.flac",
                                               "02. Aerodynamic.mp3": "05. Same.mp3"})
        self.assertEqual(self.taken(album), [])

    def test_two_tracks_that_trade_names_each_take_the_others_and_neither_is_a_collision(self) -> None:
        # Each new name is a file on disk now, held by the other track. After the draft each name has one track.
        album = self.preview_edits(self.path("ecliptica"),
                                   ({"Track number": ["2"], "Title": ["My Land"]}, ("01. Blank File.flac",)),
                                   ({"Track number": ["1"], "Title": ["Blank File"]}, ("02. My Land.flac",)))
        self.assertEqual(self.renames(album), {"01. Blank File.flac": "02. My Land.flac",
                                               "02. My Land.flac": "01. Blank File.flac"})
        self.assertEqual(self.taken(album), [])

    def test_a_name_two_tracks_share_after_one_edit_and_not_after_the_next_is_not_a_collision(self) -> None:
        # The first edit alone would put both under `05. Same.flac`. The names that count are the last ones.
        album = self.preview_edits(self.path("ecliptica"),
                                   ({"Track number": ["5"], "Title": ["Same"]},
                                    ("01. Blank File.flac", "02. My Land.flac")),
                                   ({"Title": ["Other"]}, ("02. My Land.flac",)))
        self.assertEqual(self.renames(album), {"01. Blank File.flac": "05. Same.flac",
                                               "02. My Land.flac": "05. Other.flac"})
        self.assertEqual(self.taken(album), [])
