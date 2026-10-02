"""Suggestions on the review page: what the planned artist's library albums say about a planned album.

`GET /api/drops/<drop>/albums/<n>` answers `suggestions`, a list of

- `{kind: "genre", genre, albums, of, artist}`
- `{kind: "soundtrack", genre, albums, of, artist}`
- `{kind: "spelling", artist, lands_in, folders: [{path, name}]}`

The server runs on a thread over temporary folders and is spoken to over
HTTP, as `tests.test_agitha_server` does. Each case lays a drop the way
agitha leaves one after identify: the staged tracks under
`inbox/<drop>/<n>/drop/album/`, and a `plan.json` written by hand in the job
folder, shaped as `tests/fixtures/agitha/soundtrack-choice/plan.json` is. The
planned album artist ids are in each file's planned tags and nowhere else, as
identify writes them.

The library is `builders.library` plus `lay_extras`. Nothing here asserts the
order of the list: each case reads the suggestions of one kind, or the whole
list where the case leaves room for one suggestion only.
"""

from __future__ import annotations

import builtins
import http.client
import itertools
import json
import os
import shutil
import tempfile
import threading
import unicodedata
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from agitha.server import Config, make_server
from tests import builders
from tests import test_agitha_server as neighbour

VIDEO_GAME_MUSIC = "video game music"
SOUNDTRACK = "soundtrack"

#: Stand-in MusicBrainz artist ids of the folders `lay_extras` adds, and of a plan no folder carries.
KONDO_ID = "5c0a0000-0000-4000-8000-0000000000b1"
ZIMMER_ID = "5c0a0000-0000-4000-8000-0000000000b2"
MAGO_ID = "5c0a0000-0000-4000-8000-0000000000b3"

SONATA = "S/Sonata Arctica"
KONDO = "K/Koji Kondo"
MAGO = "M/Mägo de Oz"

AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".wma")
_DROPS = itertools.count(1)


def nfc(value: Any) -> Any:
    """`value` with every string composed, so a filesystem that hands back decomposed names compares equal."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [nfc(item) for item in value]
    if isinstance(value, dict):
        return {key: nfc(item) for key, item in value.items()}
    return value


def lay_album(shelf: Path, artist_path: str, date: str, album: str, titles: tuple[str, ...],
              genres: tuple[str, ...], ids: tuple[str, ...] = (), first_only: tuple[str, ...] = ()) -> Path:
    """A FLAC album under `artist_path` whose tracks carry `genres`; `first_only` go on the first track alone.

    With no `ids` the tracks carry no MusicBrainz id at all.
    """
    letter, artist = artist_path.split("/")
    folder = builders.library_album(shelf, letter=letter, artist=artist, date=date, album=album, discs=(titles,))
    for number, title in enumerate(titles, start=1):
        path = folder / f"{number:02d}. {title}.flac"
        fields = {"genre": [*genres, *(first_only if number == 1 else ())]}
        if ids:
            fields.update({"artist id": list(ids), "album artist id": list(ids)})
        else:
            builders.delete_tags(path, [builders.picard_key("flac", field) for field in builders.ID_FIELDS])
        builders.write_tags(path, builders.picard_tags("flac", fields))
    return folder


def lay_extras(shelf: Path) -> None:
    """The artists these cases need beyond `builders.library`.

    Koji Kondo: `video game music` on two albums of three, `soundtrack` on the
    third, `ambient` on one, and `classical` on every track of two and on one
    track only of `Majora's Mask`. Hans Zimmer: one album, `soundtrack`. Mägo
    de Oz: two albums with no MusicBrainz id, `folk metal` on both and `heavy
    metal` on one. The Cure: one album, in the folder its sort name makes.
    """
    lay_album(shelf, KONDO, "1998-12-18", "Ocarina of Time", ("Title Theme", "Kokiri Forest"),
              (VIDEO_GAME_MUSIC, "classical", "ambient"), (KONDO_ID,))
    lay_album(shelf, KONDO, "2000-06-23", "Majora's Mask", ("Clock Town", "Termina Field"),
              (VIDEO_GAME_MUSIC,), (KONDO_ID,), first_only=("classical",))
    lay_album(shelf, KONDO, "1986-07-20", "Film Themes", ("Opening", "Ending"),
              (SOUNDTRACK, "classical"), (KONDO_ID,))
    lay_album(shelf, "Z/Hans Zimmer", "2010-07-13", "Inception", ("Half Remembered Dream", "Time"),
              (SOUNDTRACK,), (ZIMMER_ID,))
    lay_album(shelf, MAGO, "1998-11-02", "La leyenda de la Mancha", ("En un lugar", "El santo grial"),
              ("folk metal", "heavy metal"))
    lay_album(shelf, MAGO, "2000-05-15", "Finisterra", ("Satania", "Fiesta pagana"), ("folk metal",))
    lay_album(shelf, "C/Cure, The", "1989-05-02", "Disintegration", ("Plainsong", "Lullaby"),
              ("gothic rock",), (builders.CURE_ID,))


def planned(lands_in: str, artist: str, ids: tuple[str, ...], genres: tuple[str, ...], *,
            album: str = "A New One", waits: bool = False, game: str | None = None) -> dict[str, Any]:
    """The plan entry of a two-track MP3 album by `artist`, landing in the artist folder `lands_in`.

    `ids` are the planned album artist ids, `genres` the planned genres of
    every track. `waits` is the plan identify leaves for a Soundtrack-type
    release nobody has chosen for; `game` is the owner's choice once made.

    The planned tags carry no release group id: with one, the view's own
    duplicate check reads the tracks of the artist folder, and the cache
    cases could not tell those reads from the suggestions'.
    """
    source = f"drop/album/{album}"
    destination = f"{lands_in}/(2004) {album}"
    release_id = "5c0a0000-0000-4000-8000-0000000000d1"
    fields, files = {}, []
    for number, title in enumerate(("One", "Two"), start=1):
        neutral = {"album": [album], "albumartist": [artist], "albumartistsort": [artist], "artist": [artist],
                   "artistsort": [artist], "date": ["2004-10-06"], "genre": list(genres), "title": [title]}
        after = {builders.picard_key("mp3", field): values for field, values in neutral.items()}
        after.update({"TRCK": [f"{number}/2"], "TPOS": ["1/1"], builders.picard_key("mp3", "release id"): [release_id]})
        if ids:
            after[builders.picard_key("mp3", "artist id")] = list(ids)
            after[builders.picard_key("mp3", "album artist id")] = list(ids)
        fields[f"1-{number}"] = neutral
        files.append({
            "source": f"{source}/{number:02d} {title.lower()}.mp3",
            "destination": f"{destination}/{number:02d}. {title}.mp3",
            "position": f"1-{number}",
            "before": {"TIT2": [title.lower()], "TPE1": [artist]},
            "after": after,
        })
    held = waits and game is None
    return {
        "source": source, "state": "held" if held else "auto", "status": "review" if held else "certain",
        "holds": [{"kind": "status", "detail": "review: soundtrack choice"}] if held else [],
        "decision": None, "release_id": release_id, "destination": destination,
        "game": game, "game_choice": waits or game is not None,
        "candidates": [], "files": files, "fields": fields, "images": {}, "residue": [], "deletions": [],
        "extras": [], "kept": [], "strays": [], "changes": [], "owner_edits": {}, "plan_digest": "0" * 64,
        "inputs": {"release_id": release_id, "chosen": False, "status": "review" if held else "certain",
                   "composer": True, "edits": {}, "owner_input": {"soundtracks": {release_id: game} if game else {}}},
    }


def genre_counts(found: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """`{genre: (albums, of)}` of the `genre` suggestions in `found`."""
    return {one["genre"]: (one["albums"], one["of"]) for one in found if one["kind"] == "genre"}


def of_kind(found: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in found if one["kind"] == kind]


@contextmanager
def audio_opened(shelf: Path) -> Iterator[list[str]]:
    """The audio files under `shelf` opened while the block runs, as library-relative paths.

    Every reader ends at `open` (mutagen's and `pathlib`'s both look the name
    up when they call), so this sees a read whichever function the server
    reads through.
    """
    real = builtins.open
    root = os.path.realpath(shelf)
    seen: list[str] = []

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, bytes, os.PathLike)):
            path = os.path.realpath(os.fsdecode(file))
            if path.startswith(root + os.sep) and path.lower().endswith(AUDIO):
                seen.append(Path(path).relative_to(root).as_posix())
        return real(file, *args, **kwargs)

    with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
        yield seen


class Box:
    """A server over temporary folders whose library is `<tmp>/shelf`: the fixture library and `lay_extras`."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.folders = neighbour.make_folders(self.root)
        self.shelf = self.root / "shelf"
        self.library = builders.library(self.shelf)
        lay_extras(self.shelf)
        self.config = Config(
            inbox=self.folders["inbox"], jobs=self.folders["jobs"], library=self.shelf,
            extras=self.folders["extras"], musiclib=str(neighbour.STUB), static=self.folders["static"],
            port=0, host="127.0.0.1",
        )
        self.server = make_server(self.config)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)
        shutil.rmtree(self.root)

    def lay_drop(self, entry: dict[str, Any] | None, replaces: str | None = None) -> str:
        """A drop holding one staged album and, with an `entry`, its plan; returns the address of its view.

        `replaces` makes it a match of the library album at that path, as
        `album.json` records one.
        """
        drop, n = f"20261002-{next(_DROPS):06d}", "01"
        name = entry["source"].rsplit("/", 1)[1] if entry else "Not Identified Yet"
        staged = self.folders["inbox"] / drop / n / "drop" / "album" / name
        staged.mkdir(parents=True)
        for number, title in enumerate(("one", "two"), start=1):
            path = staged / f"{number:02d} {title}.mp3"
            shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
            builders.write_tags(path, {"TIT2": title, "TPE1": "Somebody"}, v2_version=4)
        record = {"name": name} if replaces is None else {"name": name, "replaces": replaces}
        (self.folders["inbox"] / drop / n / "album.json").write_text(json.dumps(record), encoding="utf-8")
        if entry is not None:
            job = self.folders["jobs"] / f"agitha-{drop}-{n}"
            job.mkdir()
            plan = {"job": job.name, "root": str(self.folders["inbox"] / drop / n), "albums": [entry]}
            (job / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return f"/api/drops/{drop}/albums/{n}"


class SuggestCase(unittest.TestCase):
    """What every case shares: a `Box`, and the album view read over HTTP."""

    box: Box
    maxDiff = None

    def view(self, address: str) -> dict[str, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.box.port, timeout=30)
        try:
            connection.request("GET", address)
            response = connection.getresponse()
            status, body = response.status, response.read()
        finally:
            connection.close()
        self.assertEqual(status, 200, f"GET {address} answered {status}: {body[:300]!r}")
        return json.loads(body)

    def suggestions(self, address: str) -> list[dict[str, Any]]:
        view = self.view(address)
        self.assertTrue("suggestions" in view, "the album view carries no `suggestions`")
        return nfc(view["suggestions"])

    def suggested(self, entry: dict[str, Any] | None, replaces: str | None = None) -> list[dict[str, Any]]:
        """The suggestions for a drop planned as `entry`."""
        return self.suggestions(self.box.lay_drop(entry, replaces))


class ShelfCase(SuggestCase):
    """One library for the class, read and never written."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.box = Box()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.box.close()


def sonata(genres: tuple[str, ...] = ("heavy metal",), album: str = "Reckoning Night") -> dict[str, Any]:
    return planned(SONATA, "Sonata Arctica", (builders.SONATA_ARCTICA_ID,), genres, album=album)


def babasonicos(genres: tuple[str, ...], lands_in: str = "B/Babasónicos") -> dict[str, Any]:
    return planned(lands_in, lands_in.split("/")[1], (builders.BABASONICOS_ID,), genres, album="Infame")


def kondo(genres: tuple[str, ...] = ("electronic",), **more: Any) -> dict[str, Any]:
    return planned(KONDO, "Koji Kondo", (KONDO_ID,), genres, album="Wind Waker", **more)


class CountsTheArtistsAlbums(ShelfCase):
    def test_a_genre_the_plan_lacks_is_suggested_with_how_many_of_the_artists_albums_carry_it(self) -> None:
        # Five album folders: `fullmoon` has no MusicBrainz id and counts, or this would read 3 of 4.
        # Albums, not tracks: `power metal` is on 7 of the folder's 11 tracks.
        # `heavy metal` is on 3 of the 5 as well, and the plan has it already.
        self.assertEqual(self.suggested(sonata()), [
            {"kind": "genre", "genre": "power metal", "albums": 3, "of": 5, "artist": "Sonata Arctica"},
        ])

    def test_the_album_a_match_replaces_is_left_out_of_the_count(self) -> None:
        stones = self.box.library.albums["stones"]
        # The match lands under another folder name, so only `replaces` says which album it is.
        entry = sonata(album="Stones Grow Her Name, Again")
        self.assertEqual(genre_counts(self.suggested(entry, replaces=stones.path)), {"power metal": (3, 4)})

    def test_a_genre_on_exactly_half_of_the_albums_is_suggested(self) -> None:
        found = self.suggested(babasonicos(("alternative rock",)))
        self.assertEqual(genre_counts(found), {"rock": (1, 2), "electronic": (1, 2)})

    def test_a_genre_on_one_album_of_three_is_not_suggested(self) -> None:
        counts = genre_counts(self.suggested(kondo()))
        # `classical` shows the artist was found: without it nothing at all would pass for nothing below half.
        self.assertIn("classical", counts)
        self.assertNotIn("ambient", counts)

    def test_an_album_counts_for_a_genre_only_where_every_track_carries_it(self) -> None:
        # `Majora's Mask` has `classical` on its first track alone.
        self.assertEqual(genre_counts(self.suggested(kondo()))["classical"], (2, 3))

    def test_an_artist_with_one_library_album_counts(self) -> None:
        # Both ids of `lulu`, the other way round: the ids are compared as a set.
        ids = (builders.METALLICA_ID, builders.LOU_REED_ID)
        found = self.suggested(planned("L/Lou Reed & Metallica", "Lou Reed & Metallica", ids, ("noise rock",)))
        self.assertEqual(genre_counts(found), {"heavy metal": (1, 1), "experimental rock": (1, 1)})

    def test_the_artist_is_named_as_the_plan_tags_it_where_its_folder_is_called_otherwise(self) -> None:
        entry = planned("C/Cure, The", "The Cure", (builders.CURE_ID,), ("post-punk",), album="Wish")
        self.assertEqual(self.suggested(entry), [
            {"kind": "genre", "genre": "gothic rock", "albums": 1, "of": 1, "artist": "The Cure"},
        ])

    def test_an_album_with_no_plan_yet_has_no_suggestions(self) -> None:
        self.assertEqual(self.suggested(None), [])


class SuggestsOnlyGenresTheEditorTakes(SuggestCase):
    """A genre the library carries and the editor refuses is not offered: Add would put the album on hold.

    The library is the owner's and older than the genre list, so it holds
    names the list spells otherwise. The class has its own library, as the
    shared one carries no such name.
    """

    MOGWAI = "M/Mogwai"
    MOGWAI_ID = "5c0a0000-0000-4000-8000-0000000000b4"
    #: `post-rock` is on MusicBrainz's list. Neither spelling here is.
    OFF_LIST = ("Post Rock", "Post-Rock")

    @classmethod
    def setUpClass(cls) -> None:
        cls.box = Box()
        cls.addClassCleanup(cls.box.close)
        # Both names on every track of both albums, beside one that is on the list.
        lay_album(cls.box.shelf, cls.MOGWAI, "1997-10-21", "Young Team", ("Yes! I Am a Long Way from Home", "Tracy"),
                  (*cls.OFF_LIST, "rock"), (cls.MOGWAI_ID,))
        lay_album(cls.box.shelf, cls.MOGWAI, "1999-03-29", "Come On Die Young", ("Punk Rock", "Cody"),
                  (*cls.OFF_LIST, "rock"), (cls.MOGWAI_ID,))

    def test_a_genre_off_the_official_list_on_every_album_of_the_artist_is_not_suggested(self) -> None:
        official = (neighbour.MUSIC / "musiclib" / "mb-genres.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("rock", official)
        self.assertEqual([name for name in self.OFF_LIST if name in official], [])
        entry = planned(self.MOGWAI, "Mogwai", (self.MOGWAI_ID,), ("ambient",), album="Rock Action")
        # `rock` shows the artist's albums were found and counted: 2 of 2, as the two off the list would be.
        self.assertEqual(self.suggested(entry), [
            {"kind": "genre", "genre": "rock", "albums": 2, "of": 2, "artist": "Mogwai"},
        ])


class MatchesTheArtistFolder(ShelfCase):
    def test_a_plan_with_one_of_an_albums_two_album_artist_ids_does_not_match_its_folder(self) -> None:
        # `lulu` carries `heavy metal` and this plan lacks it: a match would suggest it, 1 of 1.
        # Landing under the folder's own name leaves the ids as the only thing that tells the two apart.
        for lands_in in ("L/Lou Reed", "L/Lou Reed & Metallica"):
            with self.subTest(lands_in=lands_in):
                entry = planned(lands_in, "Lou Reed", (builders.LOU_REED_ID,), ("glam rock",))
                self.assertEqual(self.suggested(entry), [])

    def test_a_plan_with_an_id_more_than_the_albums_carry_does_not_match_their_folder(self) -> None:
        ids = (builders.SONATA_ARCTICA_ID, builders.METALLICA_ID)
        for lands_in in ("S/Sonata Arctica & Metallica", SONATA):
            with self.subTest(lands_in=lands_in):
                entry = planned(lands_in, "Sonata Arctica & Metallica", ids, ("thrash metal",))
                self.assertEqual(self.suggested(entry), [])

    def test_the_same_id_under_a_folder_spelled_with_another_accent_is_the_same_artist(self) -> None:
        # `jessico` in `B/Babasónicos` and `miami` in `B/Babasonicos`, both `alternative rock`.
        # 1 of 1 would be the planned folder alone; 2 of 3 would count the namesake in `B/Babasonicós`.
        found = self.suggested(babasonicos(("rock", "electronic")))
        self.assertEqual(genre_counts(found), {"alternative rock": (2, 2)})

    def test_a_folder_of_the_same_folded_name_whose_album_carries_another_id_is_not_counted(self) -> None:
        # The namesake's own plan: the two Babasónicos folders fold to its name and carry another id.
        entry = planned("B/Babasonicós", "Babasonicós", (builders.BABASONICOS_NAMESAKE_ID,), ("pop",), album="Tres")
        self.assertEqual(self.suggested(entry), [
            {"kind": "genre", "genre": "rock", "albums": 1, "of": 1, "artist": "Babasonicós"},
        ])

    def test_a_folder_whose_albums_carry_no_id_matches_by_its_name_with_accents_folded(self) -> None:
        found = self.suggested(planned("M/Mago de Oz", "Mago de Oz", (MAGO_ID,), ("heavy metal",)))
        self.assertEqual(genre_counts(found), {"folk metal": (2, 2)})

    def test_a_plan_with_no_id_matches_a_folder_with_none_by_its_name_with_case_folded(self) -> None:
        # The planned folder is no folder yet, so it can differ by case alone on any filesystem.
        found = self.suggested(planned("M/MÄGO DE OZ", "MÄGO DE OZ", (), ("heavy metal",)))
        self.assertEqual(genre_counts(found), {"folk metal": (2, 2)})


class WarnsAboutTheSpelling(ShelfCase):
    def test_a_matching_folder_spelled_otherwise_is_named_with_where_the_album_would_land(self) -> None:
        found = self.suggested(babasonicos(("rock", "electronic")))
        # `B/Babasónicos` is the plan's own folder and `B/Babasonicós` another artist: neither is named.
        self.assertEqual(of_kind(found, "spelling"), [{
            "kind": "spelling", "artist": "Babasónicos", "lands_in": "B/Babasónicos",
            "folders": [{"path": "B/Babasonicos", "name": "Babasonicos"}],
        }])

    def test_every_matching_folder_is_offered_where_several_are_spelled_otherwise(self) -> None:
        found = of_kind(self.suggested(babasonicos(("rock",), lands_in="B/Babasonícos")), "spelling")
        self.assertEqual(len(found), 1, found)
        self.assertEqual((found[0]["artist"], found[0]["lands_in"]), ("Babasonícos", "B/Babasonícos"))
        self.assertEqual(sorted(found[0]["folders"], key=lambda folder: folder["path"]), [
            {"path": "B/Babasonicos", "name": "Babasonicos"},
            {"path": "B/Babasónicos", "name": "Babasónicos"},
        ])

    def test_a_folder_spelled_with_other_capitals_is_named_as_the_library_has_it(self) -> None:
        # Where the filesystem ignores case, `M/MÄGO DE OZ` opens the library's folder. It is still another name.
        found = self.suggested(planned("M/MÄGO DE OZ", "MÄGO DE OZ", (MAGO_ID,), ("heavy metal",)))
        self.assertEqual(of_kind(found, "spelling"), [{
            "kind": "spelling", "artist": "MÄGO DE OZ", "lands_in": "M/MÄGO DE OZ",
            "folders": [{"path": MAGO, "name": "Mägo de Oz"}],
        }])


class SuggestsTheOtherSoundtrackGenre(ShelfCase):
    KONDO_GAMES = {"kind": "soundtrack", "genre": VIDEO_GAME_MUSIC, "albums": 2, "of": 3, "artist": "Koji Kondo"}

    def test_a_plan_waiting_for_the_choice_is_told_what_the_artists_albums_carry_and_stays_waiting(self) -> None:
        address = self.box.lay_drop(kondo(waits=True))
        drop, n = address.split("/")[3], address.split("/")[5]
        job = self.box.folders["jobs"] / f"agitha-{drop}-{n}"
        plan_before = (job / "plan.json").read_bytes()

        view = self.view(address)

        self.assertTrue("suggestions" in view, "the album view carries no `suggestions`")
        # `soundtrack` is on one album of three, so only the one genre is suggested.
        self.assertEqual(of_kind(view["suggestions"], "soundtrack"), [self.KONDO_GAMES])
        self.assertIsNone(view["preview"]["game"])
        self.assertEqual(view["preview"]["holds"], [{"kind": "status", "detail": "review: soundtrack choice"}])
        self.assertIsNone(view["decision"])
        self.assertEqual((job / "plan.json").read_bytes(), plan_before)
        self.assertFalse((job / "decisions.json").exists(), "a decision was written for the owner")

    def test_a_plan_that_sets_soundtrack_is_told_the_artists_albums_carry_video_game_music(self) -> None:
        found = self.suggested(kondo((SOUNDTRACK, "electronic"), game=SOUNDTRACK))
        self.assertEqual(of_kind(found, "soundtrack"), [self.KONDO_GAMES])

    def test_a_plan_that_sets_video_game_music_is_told_the_artists_albums_carry_soundtrack(self) -> None:
        # Set by the release's own tags, with no choice asked of the owner.
        entry = planned("Z/Hans Zimmer", "Hans Zimmer", (ZIMMER_ID,), (VIDEO_GAME_MUSIC, "electronic"))
        self.assertEqual(of_kind(self.suggested(entry), "soundtrack"), [
            {"kind": "soundtrack", "genre": SOUNDTRACK, "albums": 1, "of": 1, "artist": "Hans Zimmer"},
        ])

    def test_the_other_genre_on_fewer_than_half_of_the_albums_is_not_suggested(self) -> None:
        # The owner chose `video game music`, which two albums of three carry; `soundtrack` is on one.
        found = self.suggested(kondo((VIDEO_GAME_MUSIC, "electronic"), game=VIDEO_GAME_MUSIC))
        self.assertIn("classical", genre_counts(found))
        self.assertEqual(of_kind(found, "soundtrack"), [])

    def test_a_plan_that_neither_waits_nor_sets_one_gets_no_soundtrack_suggestion(self) -> None:
        found = self.suggested(kondo())
        self.assertIn("classical", genre_counts(found))
        self.assertEqual(of_kind(found, "soundtrack"), [])


class ReadsAnAlbumOnceUntilItChanges(SuggestCase):
    """Each case writes into its library or reads it cold, so each has its own."""

    def setUp(self) -> None:
        self.box = Box()
        self.addCleanup(self.box.close)
        self.address = self.box.lay_drop(sonata())

    def read(self, address: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
        """The suggestions, and the library's audio files opened to answer."""
        with audio_opened(self.box.shelf) as opened:
            found = self.suggestions(address or self.address)
        return found, opened

    def test_a_second_read_with_nothing_changed_opens_no_audio_file_and_answers_the_same(self) -> None:
        # Babasónicos as well: its answer depends on the ids each album carries, where Sonata Arctica's does not.
        other = self.box.lay_drop(babasonicos(("rock", "electronic")))
        first, cold = self.read()
        first_other, _cold = self.read(other)
        # The first read has to open the artist's tracks; none seen here would mean the spy sees nothing.
        self.assertTrue(any(path.startswith(SONATA + "/") for path in cold), cold)

        second, warm = self.read()
        second_other, warm_other = self.read(other)

        self.assertEqual(warm + warm_other, [])
        self.assertEqual((second, second_other), (first, first_other))

    def test_one_track_with_a_new_mtime_has_its_album_read_again_and_no_other(self) -> None:
        self.read()
        ecliptica = self.box.library.albums["ecliptica"]
        touched = ecliptica.folder / ecliptica.tracks[1]
        was = touched.stat()
        os.utime(touched, ns=(was.st_atime_ns, was.st_mtime_ns + 10_000_000_000))

        _found, opened = self.read()

        self.assertIn(f"{ecliptica.path}/{ecliptica.tracks[1]}", opened)
        self.assertEqual({path.rsplit("/", 1)[0] for path in opened}, {ecliptica.path})

    def test_a_track_rewritten_since_the_last_read_changes_the_count(self) -> None:
        self.assertEqual(genre_counts(self.suggestions(self.address)), {"power metal": (3, 5)})
        silence = self.box.library.albums["silence"]
        # `power metal` is the album's only genre. The new value has the same length, so the file's size
        # does not give the change away.
        builders.write_tags(silence.folder / silence.tracks[0], {"TCON": "speed metal"}, v2_version=4)

        self.assertEqual(genre_counts(self.suggestions(self.address)), {})


if __name__ == "__main__":
    unittest.main()
