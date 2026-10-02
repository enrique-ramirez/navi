"""agitha's track order: a draft that swaps two tracks, and `GET .../<album>/order`, which flags two that look swapped.

The server runs on a thread over temporary folders and is spoken to over
HTTP. A swap is a draft like any other, so its cases are
`tests.test_agitha_save`'s `SaveCase` with a `swaps` pair in the draft: the
preview answers both tracks, the save lands them, and the disk is read after.

Every file of `builders.library` is one tone, a second long. Two files have to
sound different for a swap to show, and run different lengths for the order
check to have something to compare, so `lay_album` lays FLACs that each carry
audio no other file has (`own_audio`) and the length the test gives them
(`run_for`). Only a FLAC can be given a length that way.

MusicBrainz is a canned transport handed to the server as
`Config.mb_transport`. It answers a release by its id and keeps every URL it
was asked for, so a case counts requests. The real network is shut for every
case (`tests.test_agitha_save.no_way_out`): a server that does not take the
transport fails, and asks nobody.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import threading
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlsplit

from mutagen.flac import FLAC
from mutagen.id3 import ID3, POPM

from agitha.server import Config, make_server
from musiclib import files, mb
from tests import builders
from tests import test_agitha_editor as editor_tests
from tests import test_agitha_library as shelf_tests
from tests import test_agitha_save as save_tests

address = shelf_tests.address
edit = editor_tests.edit
neighbour = shelf_tests.neighbour

PREVIEW = editor_tests.PREVIEW
CONTRACT = builders.FIXTURES / "agitha" / "library"

NO_RELEASE = "Track order not checked: no MusicBrainz release"
NO_FIT = "Track order not checked: the files do not fit the release's track list"
NO_ANSWER = "Track order not checked: MusicBrainz did not answer"
#: What the server says of an address it has no route for. A refusal has to be another sentence.
NO_ROUTE = "No such API path."

#: A second artist on one track, so its artist ids are two values.
GUEST_ID = "7d0e0000-0000-4000-8000-0000000000a9"

#: One disc of six. Each track is `(title, seconds the file runs)`. The titles
#: do not sort in track order, 01 and 02 run 3 s apart, and 05 and 06 are the
#: lengths 5:02 and 3:41.
DEAL = "K/Katatonia/(2001) Last Fair Deal Gone Down"
DEAL_ID = "7d0e0000-0000-4000-8000-0000000000b1"
DEAL_DISCS = ((("Dispossession", 200), ("Chrome", 203), ("Teargas", 311), ("Clean Today", 187),
               ("Sweet Nurse", 302), ("Passing Bird", 221)),)
ONE, TWO, THREE, FOUR, FIVE, SIX = (f"{number:02d}. {title}.flac"
                                    for number, (title, _runs) in enumerate(DEAL_DISCS[0], start=1))

#: Two discs, of three and of two. The last track of the first disc runs 2 s: within 3 s of no length at all.
VIVA = "K/Katatonia/(2003) Viva Emptiness"
VIVA_ID = "7d0e0000-0000-4000-8000-0000000000b2"
VIVA_DISCS = ((("Ghost of the Sun", 250), ("Sleeper", 302), ("Inside the Fall", 2)),
              (("Criminals", 221), ("A Premonition", 199)))
CRIMINALS, PREMONITION = "CD2/01. Criminals.flac", "CD2/02. A Premonition.flac"

Discs = tuple[tuple[tuple[str, int], ...], ...]


def run_for(path: Path, seconds: int) -> None:
    """Makes a FLAC say it runs `seconds`. Only the stream's header changes: the audio is still the fixture's second."""
    audio = FLAC(path)
    audio.info.total_samples = audio.info.sample_rate * seconds
    audio.save()


def own_audio(path: Path, n: int) -> None:
    """Gives a file audio no other file has, for `n` from 1 to 255, by changing one byte near its end.

    `musiclib.files.audio_fingerprint` hashes the bytes after the tags. No
    reader here decodes them.
    """
    data = bytearray(path.read_bytes())
    data[-8] = (data[-8] + n) % 256
    path.write_bytes(bytes(data))


def lay_album(shelf: Path, path: str, release_id: str, discs: Discs) -> tuple[str, ...]:
    """A FLAC album at the library-relative `path`; returns its tracks' album-relative paths in order.

    Every track carries the release id, a recording id and a track id of its
    own, its own audio and the length `discs` gives it.
    """
    letter, artist, folder = path.split("/")
    base = builders.library_album(shelf, letter=letter, artist=artist, album=folder[7:], date=f"{folder[1:5]}-01-01",
                                  discs=tuple(tuple(title for title, _runs in disc) for disc in discs))
    tracks = []
    for disc, titles in enumerate(discs, start=1):
        for number, (title, runs) in enumerate(titles, start=1):
            rel = (f"CD{disc}/" if len(discs) > 1 else "") + f"{number:02d}. {title}.flac"
            builders.write_tags(base / rel, {
                "MUSICBRAINZ_ALBUMID": release_id,
                "MUSICBRAINZ_TRACKID": f"7d0e0000-0000-4000-8000-{release_id[-2:]}00{disc:02d}{number:02d}00c1",
                "MUSICBRAINZ_RELEASETRACKID": f"7d0e0000-0000-4000-8000-{release_id[-2:]}00{disc:02d}{number:02d}00c2",
            })
            run_for(base / rel, runs)
            own_audio(base / rel, disc * 16 + number)
            tracks.append(rel)
    return tuple(tracks)


def release(release_id: str, discs: Discs, wants: dict[tuple[int, int], int | None] | None = None) -> dict[str, Any]:
    """A ws/2 release with the media and track counts of `discs`.

    Each position has the length its file runs, but for `wants`: `{(disc,
    number): seconds}`, or `None` for a position MusicBrainz has no length for.
    """
    media = []
    for disc, titles in enumerate(discs, start=1):
        medium = builders.mb_medium(disc, [title for title, _runs in titles])
        for number, (track, (_title, runs)) in enumerate(zip(medium["tracks"], titles, strict=True), start=1):
            seconds = (wants or {}).get((disc, number), runs)
            track["length"] = None if seconds is None else seconds * 1000
            track["recording"]["length"] = track["length"]
        media.append(medium)
    return builders.mb_release(id=release_id, media=media)


def flag(a: str, b: str, a_runs: int, a_wants: int, b_runs: int, b_wants: int) -> dict[str, Any]:
    return {"a": a, "b": b, "a_runs": a_runs, "a_wants": a_wants, "b_runs": b_runs, "b_wants": b_wants}


class CannedMusicBrainz:
    """MusicBrainz as a transport: a release it was given is a 200, anything else a 404. Keeps every URL asked for.

    `fault` makes every request fail until it is `None` again: an exception
    is raised, as the network does, and a status is answered with no body
    worth reading, as MusicBrainz does when it is busy.
    """

    def __init__(self, *releases: dict[str, Any]) -> None:
        self.releases = {found["id"]: found for found in releases}
        self.requests: list[str] = []
        self.fault: Exception | int | None = None

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        if isinstance(self.fault, Exception):
            raise self.fault
        if self.fault is not None:
            return self.fault, b"<html><body>Service Temporarily Unavailable</body></html>"
        parts = urlsplit(url)
        kind, _, ident = parts.path.removeprefix("/ws/2/").partition("/")
        found = self.releases.get(ident) if parts.netloc == "musicbrainz.org" and kind == "release" else None
        if found is None:
            return 404, b'{"error": "Not Found"}'
        return 200, json.dumps(found).encode("utf-8")


def takes_a_transport() -> bool:
    return "mb_transport" in {field.name for field in dataclasses.fields(Config)}


def config_over(folders: dict[str, Path], shelf: Path, transport: CannedMusicBrainz) -> Config:
    """A `Config` over `folders` whose library is `shelf` and whose MusicBrainz is `transport`.

    A `Config` with no `mb_transport` field is built without one, so a case
    still runs and fails on what the server answers.
    """
    settings: dict[str, Any] = dict(
        inbox=folders["inbox"], jobs=folders["jobs"], library=shelf, extras=folders["extras"],
        musiclib=str(neighbour.STUB), static=folders["static"], port=0, host="127.0.0.1")
    if takes_a_transport():
        settings["mb_transport"] = transport
    return Config(**settings)


def no_waiting(case: Any) -> None:
    """Drops the engine client's second between requests and its waits before a retry, for the rest of `case`.

    A canned transport needs no rate limit, and five attempts at a
    MusicBrainz that is down would otherwise take thirty seconds.
    """
    cleanup = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    for name, value in (("_MIN_INTERVAL", 0.0), ("_BACKOFF", [0.0, 0.0, 0.0, 0.0])):
        patcher = mock.patch.object(mb, name, value)
        patcher.start()
        cleanup(patcher.stop)


GAINS = ("track gain", "track peak", "album gain", "album peak")
PLAYED = ("first played", "last played", "play count")


def _raw(name: str) -> str:
    return name.upper().replace(" ", "_")


def place(path: Path) -> dict[str, Any]:
    """What a file says of its place in the album and of the song there: what a swap moves."""
    if path.suffix == ".flac":
        tags = FLAC(path)

        def values(key: str) -> list[str]:
            return list(tags.get(key) or [])

        return {
            "disc": int(values("discnumber")[0].split("/")[0]), "number": int(values("tracknumber")[0].split("/")[0]),
            "title": values("title"), "artist": values("artist"), "artist sort": values("artistsort"),
            "composer": values("composer"), "lyrics": values("lyrics"),
            "recording id": values("musicbrainz_trackid"), "track id": values("musicbrainz_releasetrackid"),
            "artist ids": values("musicbrainz_artistid"),
        }
    id3 = ID3(path)

    def text(key: str) -> list[str]:
        return [str(value) for value in id3[key].text] if key in id3 else []

    return {
        "disc": int(text("TPOS")[0].split("/")[0]), "number": int(text("TRCK")[0].split("/")[0]),
        "title": text("TIT2"), "artist": text("TPE1"), "artist sort": text("TSOP"),
        "composer": text("TCOM"), "lyrics": [frame.text for frame in id3.getall("USLT")],
        "recording id": [frame.data.decode("ascii") for frame in id3.getall("UFID:http://musicbrainz.org")],
        "track id": text("TXXX:MusicBrainz Release Track Id"), "artist ids": text("TXXX:MusicBrainz Artist Id"),
    }


def sound(path: Path) -> dict[str, Any]:
    """The audio of a file and what a swap keeps with it: the rating, the ReplayGain values, the play history."""
    read = files.read(str(path))
    if path.suffix == ".flac":
        tags = FLAC(path)

        def values(key: str) -> list[str]:
            return list(tags.get(key) or [])

        rating: list[Any] = values("rating")
        gains = {name: values(f"replaygain_{_raw(name)}") for name in GAINS}
        played = {name: values(_raw(name)) for name in PLAYED}
    else:
        id3 = ID3(path)

        def values(key: str) -> list[str]:
            return [str(value) for value in id3[key].text] if key in id3 else []

        rating = [(frame.email, frame.rating) for frame in id3.getall("POPM")]
        gains = {name: values(f"TXXX:REPLAYGAIN_{_raw(name)}") for name in GAINS}
        played = {name: values(f"TXXX:{_raw(name)}") for name in PLAYED}
    return {"audio": files.audio_fingerprint(read), "kind": path.suffix, "runs": round(read.length),
            "rating": rating, "gains": gains, "played": played}


def listened(stars: int, gain: str, peak: str, count: int, last: str) -> dict[str, str]:
    """What listening leaves in a FLAC: a rating, the four ReplayGain values and the play history."""
    return {
        "RATING": str(stars),
        "REPLAYGAIN_TRACK_GAIN": f"{gain} dB", "REPLAYGAIN_TRACK_PEAK": peak,
        # An album's tracks share these two. Here they differ, so a value that changed files shows.
        "REPLAYGAIN_ALBUM_GAIN": f"-{count}.50 dB", "REPLAYGAIN_ALBUM_PEAK": f"0.9{count:02d}000",
        "FIRST_PLAYED": "2011-07-19 20:01:44", "LAST_PLAYED": last, "PLAY_COUNT": str(count),
    }


#: What the two swapped tracks of `DEAL` hold, by readable name: 05's value, then 06's. 06 has no lyrics.
SWAPPED_FIELDS: dict[str, tuple[list[str] | None, list[str] | None]] = {
    "Track number": (["5"], ["6"]),
    "Title": (["Sweet Nurse"], ["Passing Bird"]),
    "Artist": (["Katatonia"], ["Katatonia feat. Mikael Åkerfeldt"]),
    "Artist sort order": (["Katatonia"], ["Katatonia feat. Åkerfeldt, Mikael"]),
    "Composer": (["Anders Nyström"], ["Jonas Renkse"]),
    "Lyrics": (["A sweet nurse\nis all I need"], None),
    "MusicBrainz recording id": (["7d0e0000-0000-4000-8000-b100010500c1"], ["7d0e0000-0000-4000-8000-b100010600c1"]),
    "MusicBrainz track id": (["7d0e0000-0000-4000-8000-b100010500c2"], ["7d0e0000-0000-4000-8000-b100010600c2"]),
    "MusicBrainz artist id": ([builders.MBID], [builders.MBID, GUEST_ID]),
}


def dress_the_pair(folder: Path) -> None:
    """Gives 05 and 06 of `DEAL` a value of their own for every tag a swap moves and every tag it keeps."""
    builders.write_tags(folder / FIVE, {
        "ARTISTSORT": "Katatonia", "COMPOSER": "Anders Nyström", "LYRICS": "A sweet nurse\nis all I need",
        **listened(5, "-7.31", "0.988312", 12, "2026-08-30 23:10:02"),
    })
    builders.write_tags(folder / SIX, {
        "ARTIST": "Katatonia feat. Mikael Åkerfeldt", "ARTISTSORT": "Katatonia feat. Åkerfeldt, Mikael",
        "COMPOSER": "Jonas Renkse", "MUSICBRAINZ_ARTISTID": [builders.MBID, GUEST_ID],
        **listened(2, "-4.02", "0.871100", 3, "2019-04-02 21:14:03"),
    })


Held = tuple[dict[str, Any], dict[str, Any]]


class SwapCase(save_tests.SaveCase):
    """`SaveCase`, with `DEAL` laid beside `builders.library` and a draft that swaps two tracks."""

    preview = editor_tests.EditorCase.preview
    changes = editor_tests.EditorCase.changes

    def setUp(self) -> None:
        super().setUp()
        lay_album(self.shelf, DEAL, DEAL_ID, DEAL_DISCS)
        dress_the_pair(self.shelf / DEAL)
        no_waiting(self)
        #: Every address another machine was asked for. `SaveCase` builds a `Config` with the real transport.
        self.outside = self.enterContext(save_tests.no_way_out())
        self.addCleanup(self.assert_nobody_was_asked)

    def assert_nobody_was_asked(self) -> None:
        self.assertEqual(self.outside, [], "the server asked another machine")

    def swap(self, album: str, *pair: str, lists: tuple[str, ...] | None = None) -> dict[str, Any]:
        """A draft whose one change is `pair` in `swaps`. It lists the pair's tracks, or `lists`, as the page loaded them."""
        draft = self.draft(album, edit(tuple(dict.fromkeys(pair)) if lists is None else lists))
        self.assertEqual([track["seen"] for track in draft["tracks"]], [{}] * len(draft["tracks"]))
        return {**draft, "edits": [], "swaps": [list(pair)]}

    def held(self, album: str, tracks: tuple[str, ...]) -> dict[str, Held]:
        return {track: (place(self.shelf / album / track), sound(self.shelf / album / track)) for track in tracks}

    def assert_they_differ(self, was: dict[str, Held], but: tuple[str, ...] = ()) -> None:
        """Every value of the two tracks differs, bar the names in `but`: a swap that left one alone would show."""
        (place_a, sound_a), (place_b, sound_b) = was.values()
        same = [name for held_a, held_b in ((place_a, place_b), (sound_a, sound_b)) for name in held_a
                if held_a[name] == held_b[name]]
        self.assertEqual(sorted(same), sorted(but), "the two tracks hold one value here, so a swap would not show")

    def assert_swapped(self, album: str, was: dict[str, Held], now: dict[str, str]) -> None:
        """`now` maps each old path to the file that has its place now: that place's tags over the other's audio."""
        (one, at_one), (other, at_other) = now.items()
        for old, new, came_from in ((one, at_one, other), (other, at_other, one)):
            with self.subTest(file=new, holds="the tags of its place"):
                self.assertEqual(place(self.shelf / album / new), was[old][0])
            with self.subTest(file=new, holds="the other's audio and what stays with it"):
                self.assertEqual(sound(self.shelf / album / new), was[came_from][1])


class SwapsTwoTracks(SwapCase):
    def test_a_swap_previews_as_both_tracks_each_taking_the_others_tags_and_file_name(self) -> None:
        album = self.preview(self.swap(DEAL, FIVE, SIX))
        self.assertEqual(self.changes(album), {
            FIVE: {name: (five, six) for name, (five, six) in SWAPPED_FIELDS.items()},
            SIX: {name: (six, five) for name, (five, six) in SWAPPED_FIELDS.items()},
        })
        self.assertEqual({track["path"]: track["new_path"] for track in album["tracks"]}, {FIVE: SIX, SIX: FIVE})
        # Each file takes a name the other holds now. That is the swap, and no collision.
        self.assertEqual((album["new_path"], album["problems"], album["refused"], album["skip"]), (DEAL, [], [], None))

    def test_a_saved_swap_leaves_each_place_with_its_tags_and_the_other_tracks_audio(self) -> None:
        folder = self.shelf / DEAL
        was = self.held(DEAL, (FIVE, SIX))
        self.assert_they_differ(was, but=("disc", "kind"))
        rest = {name: data for name, data in builders.tree(folder).items() if name not in (FIVE, SIX)}

        self.land(self.swap(DEAL, FIVE, SIX))

        self.assert_swapped(DEAL, was, {FIVE: FIVE, SIX: SIX})
        self.assertEqual({name: data for name, data in builders.tree(folder).items() if name not in (FIVE, SIX)}, rest)

    def test_a_swap_across_discs_moves_each_audio_into_the_other_discs_folder(self) -> None:
        album = self.path("fragile")
        first, last = "CD1/01. Somewhat Damaged.flac", "CD2/02. Into the Void.flac"
        self.assertEqual((self.tracks("fragile")[0], self.tracks("fragile")[3]), (first, last))
        own_audio(self.shelf / album / first, 1)
        own_audio(self.shelf / album / last, 2)
        was = self.held(album, (first, last))
        self.assertEqual((was[first][0]["disc"], was[last][0]["disc"]), (1, 2))
        self.assertNotEqual(was[first][1]["audio"], was[last][1]["audio"])
        # The album's one rating is on the first track, and goes to the second disc with its audio.
        self.assertEqual((was[first][1]["rating"], was[last][1]["rating"]), (["4"], []))
        names = sorted(builders.tree(self.shelf / album))

        draft = self.swap(album, first, last)
        previewed = self.preview(draft)
        self.assertEqual({track["path"]: track["new_path"] for track in previewed["tracks"]},
                         {first: last, last: first})
        self.assertEqual(self.changes(previewed)[first].get("Disc number"), (["1"], ["2"]))
        self.land(draft)

        self.assert_swapped(album, was, {first: first, last: last})
        self.assertEqual(sorted(builders.tree(self.shelf / album)), names)

    def test_a_swap_between_a_flac_and_an_mp3_leaves_each_audio_its_extension_and_each_tag_on_that_formats_key(
            self) -> None:
        album = self.path("discovery")
        folder = self.shelf / album
        flac, mp3 = "01. One More Time.flac", "02. Aerodynamic.mp3"
        self.assertEqual(self.tracks("discovery")[:2], (flac, mp3))
        builders.write_tags(folder / flac, {
            "ARTIST": "Daft Punk feat. Romanthony", "ARTISTSORT": "Daft Punk feat. Romanthony",
            # Two composers and two artist ids: each has to reach the MP3 as two values, and not as one joined.
            "COMPOSER": ["Thomas Bangalter", "Guy-Manuel de Homem-Christo"],
            "MUSICBRAINZ_ARTISTID": [builders.DAFT_PUNK_ID, GUEST_ID],
            "LYRICS": "One more time\nWe're gonna celebrate",
            **{key: value for key, value in listened(4, "-9.80", "1.000000", 31, "2026-09-12 08:45:10").items()
               if key != "RATING"},
        })
        builders.write_tags(folder / mp3, {
            "TSOP": "Punk, Daft", "TCOM": "Thomas Bangalter",
            "POPM": POPM(email="Windows Media Player 9 Series", rating=64, count=0),
            **{f"TXXX:{key}": value
               for key, value in listened(2, "-6.20", "0.954000", 7, "2024-01-05 17:30:00").items() if key != "RATING"},
        }, v2_version=4)
        was = self.held(album, (flac, mp3))
        self.assert_they_differ(was, but=("disc", "runs"))
        # The MP3 has no lyrics, and the FLAC's rating is the one `builders.library` gave it.
        self.assertEqual((was[mp3][0]["lyrics"], was[flac][1]["rating"]), ([], ["4"]))
        names = sorted(builders.tree(folder))
        first_mp3, second_flac = "01. One More Time.mp3", "02. Aerodynamic.flac"

        draft = self.swap(album, flac, mp3)
        previewed = self.preview(draft)
        self.assertEqual({track["path"]: track["new_path"] for track in previewed["tracks"]},
                         {flac: second_flac, mp3: first_mp3})
        self.land(draft)

        self.assertEqual(sorted(builders.tree(folder)),
                         sorted({flac: second_flac, mp3: first_mp3}.get(name, name) for name in names))
        self.assert_swapped(album, was, {flac: first_mp3, mp3: second_flac})

    def test_a_pair_that_is_not_two_different_tracks_of_the_album_is_refused_and_nothing_is_written(self) -> None:
        # The server takes a swap at all: without this, a server that ignores `swaps` refuses every case below.
        self.assertEqual(sorted(self.changes(self.preview(self.swap(DEAL, FIVE, SIX)))), [FIVE, SIX])
        cases: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
            "one track named twice": ((FIVE, FIVE), (FIVE,)),
            "one track alone": ((FIVE,), (FIVE,)),
            "three tracks": ((FOUR, FIVE, SIX), (FOUR, FIVE, SIX)),
            "a file of the album that is no track": ((FIVE, "cover.jpg"), (FIVE,)),
            "a track the album does not hold": ((FIVE, "07. Nowhere.flac"), (FIVE,)),
        }
        before = self.on_disk()
        for name, (pair, lists) in cases.items():
            draft = self.swap(DEAL, *pair, lists=lists)
            for route in (PREVIEW, save_tests.SAVE):
                with self.subTest(pair=name, route=route):
                    got = editor_tests.post(self.port, route, draft)
                    self.assertTrue(400 <= got.status < 500, f"POST {route} answered {got.status}: {got.body[:300]!r}")
                    sentence = json.loads(got.body)["error"]
                    self.assertIsInstance(sentence, str)
                    self.assertNotEqual(sentence, NO_ROUTE)
                    self.assert_as_it_was(before)
                    self.assertEqual(self.copies_in_jobs(), [])

    def test_once_a_flagged_pair_is_swapped_the_order_reads_clean_and_asks_musicbrainz_nothing_more(self) -> None:
        canned = CannedMusicBrainz(release(DEAL_ID, DEAL_DISCS, {(1, 5): 221, (1, 6): 302}))
        self.stop()
        self.config = config_over(self.folders, self.shelf, canned)
        self.start()
        self.assertEqual(self.answer(address(DEAL, "/order")),
                         {"checked": True, "flags": [flag(FIVE, SIX, 302, 221, 221, 302)]})
        asked = list(canned.requests)
        self.assertNotEqual(asked, [], "the canned MusicBrainz was never asked")

        self.land(self.swap(DEAL, FIVE, SIX))

        # 05 now runs 3:41 and 06 runs 5:02, as the release has them. An answer kept from before would still flag.
        self.assertEqual(self.answer(address(DEAL, "/order")), {"checked": True, "flags": []})
        self.assertEqual(canned.requests, asked, "the order was checked again by asking MusicBrainz again")


class OrderCase(shelf_tests.LibraryCase):
    """One library for the class, read and never written. Each case opens its own server, folders and MusicBrainz."""

    library: builders.Library
    mb: CannedMusicBrainz
    config: Config

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.root)
        cls.shelf = cls.root / "shelf"
        cls.library = builders.library(cls.shelf)
        lay_album(cls.shelf, DEAL, DEAL_ID, DEAL_DISCS)
        lay_album(cls.shelf, VIVA, VIVA_ID, VIVA_DISCS)
        no_waiting(cls)

    # `ServerCase` stops the one server of a class. Here each case stops its own.
    @classmethod
    def tearDownClass(cls) -> None:
        pass

    def setUp(self) -> None:
        self.server: Any = None
        #: Every address another machine was asked for. The canned MusicBrainz is not one.
        self.outside = self.enterContext(save_tests.no_way_out())
        self.addCleanup(self.stop)

    def open(self, *releases: dict[str, Any]) -> CannedMusicBrainz:
        """A server with folders of its own, where nothing is cached yet, and `releases` as all MusicBrainz has."""
        self.stop()
        root = Path(tempfile.mkdtemp())
        # Runs after the server stopped: cleanups run last one first.
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(self.stop)
        self.mb = CannedMusicBrainz(*releases)
        self.config = config_over(neighbour.make_folders(root), self.shelf, self.mb)
        self.start()
        return self.mb

    def start(self) -> None:
        self.server = make_server(self.config)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(10)
            self.server = None

    def order(self, album: str) -> dict[str, Any]:
        body = self.answer(address(album, "/order"))
        self.assertEqual(self.outside, [], "the server went to the network, past the canned MusicBrainz")
        return body

    def flags(self, album: str) -> list[dict[str, Any]]:
        """The flags of an order that was checked, by their first track: the order of two flags is not promised."""
        body = self.order(album)
        self.assertEqual(sorted(body), ["checked", "flags"], body)
        self.assertIs(body["checked"], True)
        return sorted(body["flags"], key=lambda found: found["a"])

    def assert_asked(self, transport: CannedMusicBrainz, release_id: str) -> None:
        hint = "" if takes_a_transport() else " (`Config` has no `mb_transport` to hand it over)"
        self.assertNotEqual(transport.requests, [], "the canned MusicBrainz was never asked" + hint)
        self.assertEqual([url for url in transport.requests if release_id not in url], [],
                         "MusicBrainz was asked for more than the album's release")


class FlagsTwoTracksThatLookSwapped(OrderCase):
    def test_two_tracks_that_each_run_the_others_length_are_flagged_with_the_four_lengths_and_no_other(self) -> None:
        canned = self.open(release(DEAL_ID, DEAL_DISCS, {(1, 5): 221, (1, 6): 302}))
        before = builders.tree(self.shelf / DEAL)
        body = self.order(DEAL)
        self.assertEqual(body, {"checked": True, "flags": [flag(FIVE, SIX, 302, 221, 221, 302)]})
        self.assert_asked(canned, DEAL_ID)
        contract = json.loads((CONTRACT / "order.json").read_text(encoding="utf-8"))
        self.assertEqual((sorted(body), sorted(body["flags"][0])), (sorted(contract), sorted(contract["flags"][0])))
        # A flag is an offer. The files are as they were, and nothing was put beside them.
        after = builders.tree(self.shelf / DEAL)
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name, 0) != after.get(name, 0))
        self.assertEqual(changed, [], "checking the order changed these in the album's folder")

    def test_lengths_that_fit_their_own_positions_flag_nothing(self) -> None:
        releases = {
            "each as its file runs": release(DEAL_ID, DEAL_DISCS),
            "each 3 s off its file, up or down": release(DEAL_ID, DEAL_DISCS, {
                (1, 1): 203, (1, 2): 200, (1, 3): 308, (1, 4): 190, (1, 5): 299, (1, 6): 224}),
        }
        for name, found in releases.items():
            with self.subTest(release=name):
                canned = self.open(found)
                self.assertEqual(self.order(DEAL), {"checked": True, "flags": []})
                self.assert_asked(canned, DEAL_ID)

    def test_a_pair_is_flagged_only_where_each_is_more_than_3_s_off_its_own_and_within_3_s_of_the_others(self) -> None:
        # 01 runs 200 and 02 runs 203; 05 runs 302 and 06 runs 221.
        cases: dict[str, tuple[dict[tuple[int, int], int], list[dict[str, Any]]]] = {
            "each exactly 3 s off its own": ({(1, 1): 203, (1, 2): 200}, []),
            "each 4 s off its own and 1 s from the other's": (
                {(1, 1): 204, (1, 2): 199}, [flag(ONE, TWO, 200, 204, 203, 199)]),
            "one of the two 4 s off its own, the other as it runs": ({(1, 1): 204, (1, 2): 203}, []),
            "each exactly 3 s from the other's": ({(1, 5): 224, (1, 6): 299}, [flag(FIVE, SIX, 302, 224, 221, 299)]),
            "each 4 s from the other's": ({(1, 5): 225, (1, 6): 298}, []),
        }
        for name, (wants, expected) in cases.items():
            with self.subTest(lengths=name):
                self.open(release(DEAL_ID, DEAL_DISCS, wants))
                self.assertEqual(self.flags(DEAL), expected)

    def test_two_pairs_on_one_disc_are_each_flagged(self) -> None:
        self.open(release(DEAL_ID, DEAL_DISCS, {(1, 3): 187, (1, 4): 311, (1, 5): 221, (1, 6): 302}))
        self.assertEqual(self.flags(DEAL), [flag(THREE, FOUR, 311, 187, 187, 311), flag(FIVE, SIX, 302, 221, 221, 302)])

    def test_a_pair_across_two_discs_is_not_flagged_and_a_pair_on_the_second_disc_is(self) -> None:
        cases: dict[str, tuple[dict[tuple[int, int], int], list[dict[str, Any]]]] = {
            # A track of disc 1 and one of disc 2 each run what the other's position has.
            "across the two discs": ({(1, 2): 221, (2, 1): 302}, []),
            "both on the second disc": ({(2, 1): 199, (2, 2): 221}, [flag(CRIMINALS, PREMONITION, 221, 199, 199, 221)]),
        }
        for name, (wants, expected) in cases.items():
            with self.subTest(pair=name):
                canned = self.open(release(VIVA_ID, VIVA_DISCS, wants))
                self.assertEqual(self.flags(VIVA), expected)
                self.assert_asked(canned, VIVA_ID)

    def test_three_tracks_rotated_are_not_flagged(self) -> None:
        # 04 runs what 05's position has, 05 what 06's has, 06 what 04's has.
        self.open(release(DEAL_ID, DEAL_DISCS, {(1, 4): 221, (1, 5): 187, (1, 6): 302}))
        self.assertEqual(self.flags(DEAL), [])

    def test_a_position_musicbrainz_gives_no_length_is_left_out_and_the_rest_is_compared(self) -> None:
        # 06 runs 3:41 where MusicBrainz has 5:02, and 05, which runs 5:02, has no length to be held against.
        self.open(release(DEAL_ID, DEAL_DISCS, {(1, 3): 187, (1, 4): 311, (1, 5): None, (1, 6): 302}))
        self.assertEqual(self.flags(DEAL), [flag(THREE, FOUR, 311, 187, 187, 311)])
        # A length that is absent is not a length of nothing: disc 1's 2 s track runs within 3 s of zero, and
        # MusicBrainz has 4:10 for it, which is what the first track runs.
        self.open(release(VIVA_ID, VIVA_DISCS, {(1, 1): None, (1, 3): 250}))
        self.assertEqual(self.flags(VIVA), [])

    def test_a_track_with_no_length_of_its_own_is_compared_by_its_recordings_length(self) -> None:
        found = release(DEAL_ID, DEAL_DISCS, {(1, 5): 221, (1, 6): 302})
        for track in found["media"][0]["tracks"][4:]:
            track["length"] = None
        self.open(found)
        self.assertEqual(self.flags(DEAL), [flag(FIVE, SIX, 302, 221, 221, 302)])


class AsksMusicBrainzOnce(OrderCase):
    def test_opening_the_album_again_asks_musicbrainz_nothing_on_this_server_or_the_next_one(self) -> None:
        canned = self.open(release(DEAL_ID, DEAL_DISCS, {(1, 5): 221, (1, 6): 302}))
        first = self.order(DEAL)
        self.assertEqual(first["flags"], [flag(FIVE, SIX, 302, 221, 221, 302)])
        self.assert_asked(canned, DEAL_ID)
        asked = list(canned.requests)

        self.assertEqual(self.order(DEAL), first)
        self.assertEqual(canned.requests, asked, "the second call asked MusicBrainz again")

        self.stop()
        self.start()
        self.assertEqual(self.order(DEAL), first)
        self.assertEqual(canned.requests, asked, "a new server over the same folders asked MusicBrainz again")

    def test_the_albums_own_answer_asks_musicbrainz_nothing(self) -> None:
        canned = self.open(release(DEAL_ID, DEAL_DISCS))
        self.assertEqual(self.answer(address(DEAL))["release_id"], DEAL_ID)
        self.assertEqual(canned.requests, [])
        self.assertEqual(self.outside, [])
        # The same server does ask once the order is asked for, so the silence above was the album route's.
        self.order(DEAL)
        self.assert_asked(canned, DEAL_ID)


class SaysWhyTheOrderWasNotChecked(OrderCase):
    def test_an_album_with_no_release_id_says_so_and_asks_musicbrainz_nothing(self) -> None:
        canned = self.open(release(DEAL_ID, DEAL_DISCS))
        entry = self.library.albums["fullmoon"]
        self.assertIsNone(entry.release_id)
        body = self.order(entry.path)
        self.assertEqual(body, {"checked": False, "reason": NO_RELEASE, "retry": False})
        self.assertEqual(body, json.loads((CONTRACT / "order-unchecked.json").read_text(encoding="utf-8")))
        self.assertEqual(canned.requests, [])

    def test_files_that_do_not_fit_the_releases_track_counts_say_so_and_are_not_asked_about_twice(self) -> None:
        # Five tracks on the release, six files in the folder.
        canned = self.open(release(DEAL_ID, (DEAL_DISCS[0][:5],)))
        unchecked = {"checked": False, "reason": NO_FIT, "retry": False}
        self.assertEqual(self.order(DEAL), unchecked)
        self.assert_asked(canned, DEAL_ID)
        asked = list(canned.requests)
        self.assertEqual(self.order(DEAL), unchecked)
        self.assertEqual(canned.requests, asked, "the second call asked MusicBrainz again")

    def test_a_musicbrainz_that_does_not_answer_says_so_offers_a_retry_and_is_asked_again_next_time(self) -> None:
        faults: dict[str, Exception | int] = {
            "the network fails": urllib.error.URLError("[Errno 8] nodename nor servname provided, or not known"),
            "MusicBrainz answers 503": 503,
        }
        for name, fault in faults.items():
            with self.subTest(fault=name):
                canned = self.open(release(DEAL_ID, DEAL_DISCS, {(1, 5): 221, (1, 6): 302}))
                canned.fault = fault
                unanswered = {"checked": False, "reason": NO_ANSWER, "retry": True}
                self.assertEqual(self.order(DEAL), unanswered)
                self.assert_asked(canned, DEAL_ID)
                asked = len(canned.requests)

                # How many times one call tries is the client's. That the next call tries at all is the promise.
                self.assertEqual(self.order(DEAL), unanswered)
                self.assertGreater(len(canned.requests), asked, "a failure was kept, and Check again asked nobody")

                canned.fault = None
                self.assertEqual(self.flags(DEAL), [flag(FIVE, SIX, 302, 221, 221, 302)])
