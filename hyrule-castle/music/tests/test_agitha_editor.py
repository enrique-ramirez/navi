"""agitha's editor, previewed: `POST /api/library/preview` turns a draft into each track's tags before and after.

The server runs on a thread over temporary folders and is spoken to over
HTTP, as `tests.test_agitha_library` does, and its `LibraryCase` is the server
here too. A draft is built the way the page builds one: the album is fetched,
each track's `loaded` and `seen` are what that answer showed, and the changes
are a list of edits, each over the tracks it names.

A preview plans and writes nothing, so what a readable name does to an MP3 and
a FLAC shows here only as each file's own values in `before`. The bytes on
disk after a save are `POST /api/library/save`'s to show.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import socket
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests import builders
from tests import test_agitha_library as shelf

PREVIEW = "/api/library/preview"
CONTRACT = builders.FIXTURES / "agitha" / "library" / "preview.json"

#: Three tracks whose genres differ: two values, one value, two values. The first two carry a composer.
UNEVEN = "O/Opeth/(2001) Blackwater Park"
LEPER, BLEAK, HARVEST = "01. The Leper Affinity.flac", "02. Bleak.flac", "03. Harvest.flac"
#: Three tracks, the last with no genre and no artist: an album that breaks two rules before any draft.
GAPPED = "O/Opeth/(1998) My Arms, Your Hearse"
APRIL, WHEN, MADRIGAL = "01. April Ethereal.flac", "02. When.flac", "03. Madrigal.flac"

#: Three tracks, the first two both numbered 1: an album that breaks the one-number rule before any draft.
DOUBLED = "O/Opeth/(1999) Still Life"
MOOR, BENIGHTED, MELINDA = "01. The Moor.flac", "02. Benighted.flac", "03. Face of Melinda.flac"
#: Two discs of two tracks and one: the second track of the first disc is the album's only number 2.
LOPSIDED = "O/Opeth/(2005) Ghost Reveries"
HOUNDS, ATONEMENT = "CD1/02. The Baying of the Hounds.flac", "CD2/01. Atonement.flac"

COMPOSER = "Mikael Akerfeldt"
#: Not on MusicBrainz's list, and not one of the two custom genres.
OFF_LIST = "nu-grunge-core"

NOT_AN_ID = "is a MusicBrainz ID"
ADDED = "is the time the album was added"
A_RATING = "is a rating"
ONE_FORMAT = "is one format's own key; edit one format at a time"


def lay_albums(root: Path) -> None:
    """Four albums `builders.library` does not hold: its own carry one set of genres per album and break few rules."""
    uneven = builders.library_album(root, letter="O", artist="Opeth", date="2001-03-12", album="Blackwater Park",
                                    discs=(("The Leper Affinity", "Bleak", "Harvest"),))
    # In no case the sorted order, so an answer that sorted the values shows.
    builders.write_tags(uneven / LEPER, {"GENRE": ["progressive metal", "death metal"], "COMPOSER": COMPOSER})
    builders.write_tags(uneven / BLEAK, {"GENRE": ["death metal"], "COMPOSER": COMPOSER})
    builders.write_tags(uneven / HARVEST, {"GENRE": ["progressive metal", "jazz"]})

    gapped = builders.library_album(root, letter="O", artist="Opeth", date="1998-08-18",
                                    album="My Arms, Your Hearse", discs=(("April Ethereal", "When", "Madrigal"),))
    builders.write_tags(gapped / APRIL, {"GENRE": ["death metal"]})
    builders.write_tags(gapped / WHEN, {"GENRE": ["death metal", "progressive metal"]})
    builders.delete_tags(gapped / MADRIGAL, ["GENRE", "ARTIST"])

    doubled = builders.library_album(root, letter="O", artist="Opeth", date="1999-10-18", album="Still Life",
                                     discs=(("The Moor", "Benighted", "Face of Melinda"),))
    builders.write_tags(doubled / BENIGHTED, {"TRACKNUMBER": "1"})

    builders.library_album(root, letter="O", artist="Opeth", date="2005-08-29", album="Ghost Reveries",
                           discs=(("Ghost of Perdition", "The Baying of the Hounds"), ("Atonement",)))


def edit(tracks: tuple[str, ...] | None = None, *, set: dict[str, Any] | None = None,
         add: dict[str, list[str]] | None = None, remove: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """One edit of a draft, for `EditorCase.draft`: over `tracks` (album-relative), or every track of the album."""
    return {"tracks": tracks, "set": set or {}, "add": add or {}, "remove": remove or {}}


def post(port: int, path: str, body: Any) -> shelf.neighbour.Answer:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("POST", path, body=json.dumps(body).encode("utf-8"),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return shelf.neighbour.Answer(response.status, response.headers, response.read())
    finally:
        connection.close()


class EditorCase(shelf.LibraryCase):
    """A server over `builders.library` and `lay_albums`. A preview writes nothing, so no case lays its own."""

    library: builders.Library
    #: `builders.tree` of every folder the server was given, as laid.
    laid: dict[str, bytes | None]
    #: When each file of the library was last written, as laid.
    times: dict[Path, int]

    @classmethod
    def lay(cls, root: Path) -> None:
        cls.library = builders.library(root)
        lay_albums(root)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Taken before the first preview: what one preview leaves behind is there for every later one.
        cls.laid = builders.tree(cls.root)
        cls.times = {path: path.stat().st_mtime_ns for path in sorted(cls.shelf.rglob("*")) if path.is_file()}

    def tracks(self, name: str) -> tuple[str, ...]:
        return self.library.albums[name].tracks

    def path(self, name: str) -> str:
        return self.library.albums[name].path

    def draft(self, album: str, *edits: dict[str, Any]) -> dict[str, Any]:
        """A draft of `edits` (each made by `edit`) over `album`, with what the album's page shows for each track."""
        view = self.answer(shelf.address(album))
        held = [track["path"] for track in view["tracks"]]
        keys: dict[str, list[str]] = {}
        sent = []
        for one in edits:
            named = held if one["tracks"] is None else list(one["tracks"])
            self.assertEqual([path for path in named if path not in held], [], "the album does not hold those tracks")
            for path in named:
                keys.setdefault(path, []).extend([*one["set"], *one["add"], *one["remove"]])
            sent.append({**one, "tracks": [{"album": album, "path": path} for path in named]})
        tracks = []
        for track in view["tracks"]:
            if track["path"] not in keys:
                continue
            names = view["names"][track["family"]]
            seen = {}
            for key in keys[track["path"]]:
                # A readable name is looked up under the file's own key; any other key is the file's own.
                raw = next((real for real, readable in names.items() if readable == key), key)
                seen[key] = track["tags"].get(raw)
            tracks.append({"album": album, "path": track["path"], "loaded": track["loaded"], "seen": seen})
        # The album page's draft: `batch` is false there, and true from the artist page (`BatchCase.batch`).
        return {"tracks": tracks, "edits": sent, "swaps": [], "cover": None, "batch": False}

    def preview(self, draft: dict[str, Any]) -> dict[str, Any]:
        """The one album a preview of `draft` answers; anything but a 200 fails, showing what came back."""
        got = post(self.port, PREVIEW, draft)
        self.assertEqual(got.status, 200, f"POST {PREVIEW} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        albums = json.loads(got.body)["albums"]
        self.assertEqual([album["path"] for album in albums], [draft["tracks"][0]["album"]])
        return albums[0]

    def changes(self, album: dict[str, Any]) -> dict[str, dict[str, tuple[Any, Any]]]:
        """`{track path: {key: (before, after)}}` of a previewed album. A track or a key listed twice fails."""
        out: dict[str, dict[str, tuple[Any, Any]]] = {}
        for track in album["tracks"]:
            keys = [change["key"] for change in track["changes"]]
            self.assertEqual(len(keys), len({*keys}), f"{track['path']} lists a key twice: {keys}")
            self.assertNotIn(track["path"], out)
            out[track["path"]] = {change["key"]: (change["before"], change["after"]) for change in track["changes"]}
        return out


@contextlib.contextmanager
def nobody_else_asked() -> Iterator[list[str]]:
    """Refuses every name lookup but this machine's while it runs, and yields the hosts that were asked for.

    The server is a thread of this process, so a lookup it makes is seen here.
    """
    asked: list[str] = []
    real = socket.getaddrinfo

    def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in (None, "", "127.0.0.1", "localhost"):
            asked.append(str(host))
            raise OSError(f"a test refused the lookup of {host!r}")
        return real(host, *args, **kwargs)

    with mock.patch.object(socket, "getaddrinfo", lookup):
        yield asked


class PlansADraft(EditorCase):
    def test_a_set_replaces_the_values_on_each_selected_track_and_no_other(self) -> None:
        first, middle, last = self.tracks("ecliptica")
        was, now = ["power metal", "heavy metal"], ["symphonic metal", "folk metal"]
        album = self.preview(self.draft(self.path("ecliptica"), edit((first, last), set={"Genre": now})))
        # `middle` holds the same genres and would change too, had the draft named it.
        self.assertEqual(self.changes(album), {first: {"Genre": (was, now)}, last: {"Genre": (was, now)}})
        self.assertEqual([track["path"] for track in album["tracks"]], [first, last])
        self.assertNotIn(middle, self.changes(album))

    def test_a_track_that_already_holds_what_the_draft_sets_is_not_listed(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(set={"Genre": ["death metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Genre": (["progressive metal", "death metal"], ["death metal"])},
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["death metal"])},
        })

    def test_an_add_goes_after_the_values_a_track_has_and_leaves_the_tracks_that_carry_it(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(add={"Genre": ["death metal"]})))
        self.assertEqual(self.changes(album), {
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["progressive metal", "jazz", "death metal"])},
        })

    def test_an_add_of_two_values_gives_each_track_only_the_ones_it_lacks(self) -> None:
        # Two tracks carry the first value already: adding both lists whole would double it there.
        album = self.preview(self.draft(UNEVEN, edit(add={"Genre": ["death metal", "doom metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Genre": (["progressive metal", "death metal"], ["progressive metal", "death metal", "doom metal"])},
            BLEAK: {"Genre": (["death metal"], ["death metal", "doom metal"])},
            HARVEST: {"Genre": (["progressive metal", "jazz"],
                                ["progressive metal", "jazz", "death metal", "doom metal"])},
        })

    def test_an_add_to_a_track_with_no_such_tag_makes_the_tag(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(add={"Composer": ["Peter Lindgren"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Composer": ([COMPOSER], [COMPOSER, "Peter Lindgren"])},
            BLEAK: {"Composer": ([COMPOSER], [COMPOSER, "Peter Lindgren"])},
            HARVEST: {"Composer": (None, ["Peter Lindgren"])},
        })

    def test_a_remove_takes_that_one_value_and_leaves_the_tracks_that_lack_it(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(remove={"Genre": ["progressive metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Genre": (["progressive metal", "death metal"], ["death metal"])},
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["jazz"])},
        })

    def test_a_null_removes_the_tag_from_the_tracks_that_hold_it(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(set={"Composer": None})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Composer": ([COMPOSER], None)},
            BLEAK: {"Composer": ([COMPOSER], None)},
        })

    def test_a_tag_no_track_holds_is_added_by_its_readable_name(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(set={"Conductor": ["Steven Wilson"]})))
        self.assertEqual(self.changes(album),
                         {track: {"Conductor": (None, ["Steven Wilson"])} for track in (LEPER, BLEAK, HARVEST)})

    def test_a_tag_with_no_readable_name_is_added_by_the_formats_own_key(self) -> None:
        for name, key in (("silence", "TXXX:RIPPER"), ("ecliptica", "ripper")):
            with self.subTest(album=name):
                album = self.preview(self.draft(self.path(name), edit(set={key: ["EAC 0.99"]})))
                self.assertEqual(self.changes(album),
                                 {track: {key: (None, ["EAC 0.99"])} for track in self.tracks(name)})

    def test_a_formats_own_key_that_has_a_readable_name_is_answered_by_that_name(self) -> None:
        album = self.preview(self.draft(self.path("silence"), edit(set={"TCOM": ["Tony Kakko"]})))
        self.assertEqual(self.changes(album),
                         {track: {"Composer": (None, ["Tony Kakko"])} for track in self.tracks("silence")})

    def test_a_formats_own_key_changes_the_files_of_that_format_and_no_other_in_a_mixed_album(self) -> None:
        first, mp3, last = self.tracks("discovery")
        was = ["house", "electronic"]
        for key, reached in (("TCON", (mp3,)), ("genre", (first, last))):
            with self.subTest(key=key):
                album = self.preview(self.draft(self.path("discovery"), edit(set={key: ["disco"]})))
                self.assertEqual(self.changes(album), {track: {"Genre": (was, ["disco"])} for track in reached})
                # To the other format the key is not one it can hold, and that is no refusal: it was never meant for it.
                self.assertEqual(album["refused"], [])

    def test_one_readable_name_reaches_the_mp3_and_the_flacs_of_one_album(self) -> None:
        # `before` is read from `TCON` in the MP3 and `genre` in the FLACs: a name
        # resolved for one format alone would show the other as holding no genre.
        was = ["house", "electronic"]
        album = self.preview(self.draft(self.path("discovery"),
                                        edit(set={"Genre": ["disco"], "Composer": ["Daft Punk"]})))
        self.assertEqual(self.changes(album), {
            track: {"Genre": (was, ["disco"]), "Composer": (None, ["Daft Punk"])}
            for track in self.tracks("discovery")
        })

    def test_a_draft_names_two_keys_and_the_rated_track_changes_in_those_two_alone(self) -> None:
        # The first track carries a rating, `ADDED`, six ids and a picture. None of them is in the draft.
        first = self.tracks("ecliptica")[0]
        album = self.preview(self.draft(self.path("ecliptica"), edit((first,), set={"Composer": ["Tony Kakko"]},
                                                                     remove={"Genre": ["heavy metal"]})))
        self.assertEqual(self.changes(album), {first: {
            "Composer": (None, ["Tony Kakko"]),
            "Genre": (["power metal", "heavy metal"], ["power metal"]),
        }})

    def test_an_album_with_no_musicbrainz_ids_is_planned_and_no_other_machine_is_asked(self) -> None:
        now = ["power metal", "heavy metal"]
        draft = self.draft(self.path("fullmoon"), edit(set={"Genre": now}))
        with nobody_else_asked() as asked:
            album = self.preview(draft)
        self.assertEqual(asked, [])
        self.assertEqual(self.changes(album),
                         {track: {"Genre": (["heavy metal"], now)} for track in self.tracks("fullmoon")})

    def test_a_draft_of_tags_that_move_no_file_answers_every_path_as_it_is(self) -> None:
        album = self.preview(self.draft(self.path("fragile"), edit(set={"Genre": ["industrial rock"]})))
        self.assertEqual((album["path"], album["new_path"]), (self.path("fragile"),) * 2)
        self.assertEqual([(track["path"], track["new_path"]) for track in album["tracks"]],
                         [(track, track) for track in self.tracks("fragile")])
        self.assertEqual({key: album[key] for key in ("cover", "skip", "problems", "refused")},
                         {"cover": None, "skip": None, "problems": [], "refused": []})

    def test_the_answer_has_the_keys_of_preview_json(self) -> None:
        if not CONTRACT.is_file():
            self.fail(f"the contract fixture {CONTRACT} is not there")
        want = json.loads(CONTRACT.read_text(encoding="utf-8"))["albums"][0]
        # A draft that fills every list: a change, a refused key and a rule it breaks.
        got = self.preview(self.draft(UNEVEN, edit(set={"MusicBrainz release id": [builders.MBID]},
                                                   remove={"Genre": ["death metal"]})))
        self.assertEqual(sorted(got), sorted(want))
        for name, inner in (("tracks", None), ("problems", None), ("refused", None), ("tracks", "changes")):
            mine, theirs = got[name][0], want["tracks" if inner else name][0]
            if inner:
                mine, theirs = mine[inner][0], theirs[inner][0]
            with self.subTest(part=inner or name):
                self.assertEqual(sorted(mine), sorted(theirs))

    def test_a_preview_leaves_every_file_as_it_was(self) -> None:
        drafts = [
            self.draft(UNEVEN, edit(set={"Genre": ["jazz"], "Composer": None}, add={"Conductor": ["Steven Wilson"]}),
                       edit((BLEAK,), remove={"Genre": ["jazz"]})),
            self.draft(self.path("discovery"), edit(set={"Genre": ["disco"]})),
            self.draft(self.path("silence"), edit(set={"POPM:no@email": None, "Genre": [OFF_LIST]})),
        ]
        for draft in drafts:
            self.preview(draft)
        now = builders.tree(self.root)
        self.assertEqual(sorted(now), sorted(self.laid))
        self.assertEqual(now, self.laid)
        # The times as well: a file written again with the bytes it had would
        # read as changed to the page that loaded it.
        self.assertEqual({path: path.stat().st_mtime_ns for path in self.times}, self.times)


class AppliesTheEditsInOrder(EditorCase):
    """The draft is a list of edits. Each lands on the tracks it names, in the order the list has them."""

    def test_two_edits_over_different_tracks_each_land_on_their_own_tracks_alone(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit((LEPER,), set={"Composer": ["Peter Lindgren"]}),
                                        edit((HARVEST,), set={"Composer": ["Martin Lopez"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Composer": ([COMPOSER], ["Peter Lindgren"])},
            HARVEST: {"Composer": (None, ["Martin Lopez"])},
        })

    def test_two_edits_of_different_keys_over_overlapping_tracks_each_keep_to_their_tracks(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit((LEPER, BLEAK), set={"Composer": None}),
                                        edit((BLEAK, HARVEST), add={"Genre": ["doom metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Composer": ([COMPOSER], None)},
            BLEAK: {"Composer": ([COMPOSER], None), "Genre": (["death metal"], ["death metal", "doom metal"])},
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["progressive metal", "jazz", "doom metal"])},
        })

    def test_a_set_and_then_an_add_on_one_track_and_key_answer_one_change_from_the_files_values(self) -> None:
        # The other way round the add finds `death metal` already there, and the set leaves `jazz` alone.
        album = self.preview(self.draft(UNEVEN, edit(set={"Genre": ["jazz"]}),
                                        edit((LEPER,), add={"Genre": ["death metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Genre": (["progressive metal", "death metal"], ["jazz", "death metal"])},
            BLEAK: {"Genre": (["death metal"], ["jazz"])},
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["jazz"])},
        })

    def test_an_add_and_then_a_set_end_on_what_the_set_says(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit((LEPER,), add={"Genre": ["doom metal"]}),
                                        edit((LEPER,), set={"Genre": ["jazz"]})))
        self.assertEqual(self.changes(album), {LEPER: {"Genre": (["progressive metal", "death metal"], ["jazz"])}})

    def test_a_track_two_edits_leave_as_the_file_is_is_not_listed(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(add={"Genre": ["doom metal"]}),
                                        edit((LEPER, BLEAK), remove={"Genre": ["doom metal"]})))
        self.assertEqual(self.changes(album), {
            HARVEST: {"Genre": (["progressive metal", "jazz"], ["progressive metal", "jazz", "doom metal"])},
        })

    def test_an_edit_naming_a_track_the_draft_does_not_list_is_400(self) -> None:
        draft = self.draft(UNEVEN, edit((LEPER, BLEAK), set={"Composer": ["Peter Lindgren"]}))
        # With the track listed it is a draft the server plans, so the 400 below is for the missing track and nothing else.
        self.assertEqual(sorted(self.changes(self.preview(draft))), [LEPER, BLEAK])
        draft["tracks"] = [track for track in draft["tracks"] if track["path"] != BLEAK]
        got = post(self.port, PREVIEW, draft)
        self.assertEqual(got.status, 400, got.body[:300])
        self.assertEqual(list(json.loads(got.body)), ["error"])


class RefusesKeysByName(EditorCase):
    """A key the owner may not touch comes back in `refused` with the rule's reason, and is not planned.

    Each draft also sets a composer, which no fixture track carries. The
    preview answers 200 with that change beside the refusal.
    """

    GOOD = {"Composer": ["Tony Kakko"]}

    def refuses(self, name: str, how: str, key: str, values: list[str] | None, reason: str,
                answered_as: tuple[str, ...] = ()) -> None:
        """A draft doing `how` (`set`, `add`, `remove`) to `key` is refused for `reason` and plans the composer alone."""
        edits: dict[str, dict[str, Any]] = {"set": dict(self.GOOD), "add": {}, "remove": {}}
        edits[how][key] = values
        album = self.preview(self.draft(self.path(name), edit(**edits)))
        self.assertEqual([entry["reason"] for entry in album["refused"]], [reason], album["refused"])
        self.assertIn(album["refused"][0]["key"], answered_as or (key,))
        self.assertEqual(self.changes(album),
                         {track: {"Composer": (None, ["Tony Kakko"])} for track in self.tracks(name)})

    def test_a_musicbrainz_id_is_refused_under_its_readable_name_once_for_an_album_of_two_formats(self) -> None:
        release = self.library.albums["discovery"].release_id
        cases = [
            ("discovery", "set", "MusicBrainz release id", [builders.MBID]),
            ("discovery", "set", "MusicBrainz recording id", None),
            ("ecliptica", "remove", "MusicBrainz artist id", [builders.SONATA_ARCTICA_ID]),
            ("silence", "add", "MusicBrainz album artist id", [builders.MBID]),
            ("discovery", "remove", "MusicBrainz release id", [release]),
        ]
        for name, how, key, values in cases:
            with self.subTest(album=name, how=how, key=key):
                self.refuses(name, how, key, values, NOT_AN_ID)

    def test_a_musicbrainz_id_is_refused_under_the_formats_own_key(self) -> None:
        # The answer may name the key as sent or by its readable name.
        cases = [
            ("ecliptica", "set", "musicbrainz_albumid", [builders.MBID], "MusicBrainz release id"),
            ("ecliptica", "set", "musicbrainz_trackid", None, "MusicBrainz recording id"),
            ("silence", "set", "UFID:http://musicbrainz.org", None, "MusicBrainz recording id"),
            ("silence", "remove", "TXXX:MusicBrainz Album Id", [builders.MBID], "MusicBrainz release id"),
            # The album carries no id at all, and the key is refused all the same.
            ("fullmoon", "set", "TXXX:MusicBrainz Artist Id", [builders.MBID], "MusicBrainz artist id"),
        ]
        for name, how, key, values, readable in cases:
            with self.subTest(album=name, how=how, key=key):
                self.refuses(name, how, key, values, NOT_AN_ID, answered_as=(key, readable))

    def test_a_rating_is_refused_whether_the_draft_sets_it_or_removes_it(self) -> None:
        cases = [
            ("ecliptica", "set", "rating", ["5"]),
            ("ecliptica", "set", "rating", None),
            ("ecliptica", "remove", "rating", ["4"]),
            ("silence", "set", "POPM:no@email", None),
            ("silence", "set", "POPM:Windows Media Player 9 Series", ["255"]),
        ]
        for name, how, key, values in cases:
            with self.subTest(album=name, how=how, key=key, values=values):
                self.refuses(name, how, key, values, A_RATING)

    def test_the_time_the_album_was_added_is_refused_under_its_readable_name_and_each_formats_own_key(self) -> None:
        cases = [
            ("ecliptica", "set", "Added", ["2020-01-01T00:00"]),
            ("ecliptica", "set", "Added", None),
            ("discovery", "set", "Added", ["2020-01-01T00:00"]),
            ("silence", "set", "TXXX:ADDED", None),
            ("silence", "add", "TXXX:ADDED", ["2020-01-01T00:00"]),
            ("ecliptica", "set", "added", ["2020-01-01T00:00"]),
            ("ecliptica", "remove", "added", ["2026-09-02T18:30"]),
            # No track of this album carries the time, and it may not be given one by hand.
            ("fullmoon", "set", "Added", ["2020-01-01T00:00"]),
        ]
        for name, how, key, values in cases:
            with self.subTest(album=name, how=how, key=key, values=values):
                self.refuses(name, how, key, values, ADDED)

    def test_a_picture_is_refused_as_binary(self) -> None:
        cases = [
            ("silence", "set", "APIC:picture 1", None, "is a binary frame"),
            ("silence", "set", "APIC:", ["cover"], "is a binary frame"),
            ("ecliptica", "set", "metadata_block_picture", ["AAAA"], "is a binary tag"),
        ]
        for name, how, key, values, reason in cases:
            with self.subTest(album=name, key=key):
                self.refuses(name, how, key, values, reason)

    def test_a_key_the_format_cannot_hold_is_refused(self) -> None:
        cases = [
            # A link frame and a frame with no such id: neither is text the engine writes.
            ("silence", "set", "WOAR", ["https://example.org"], "is not a text frame this engine can write"),
            ("silence", "set", "ripper", ["EAC 0.99"], "is not a text frame this engine can write"),
            ("ecliptica", "set", "bad=key", ["EAC 0.99"], "is not a Vorbis field name"),
        ]
        for name, how, key, values, reason in cases:
            with self.subTest(album=name, key=key):
                self.refuses(name, how, key, values, reason)

    def test_a_genre_off_the_list_is_refused_by_its_name_and_no_genre_is_planned(self) -> None:
        cases = [
            # The first value is on the list. The key is refused whole: half a genre edit is not what was asked.
            ("ecliptica", "set", "Genre", ["power metal", OFF_LIST]),
            ("ecliptica", "add", "Genre", [OFF_LIST]),
            ("discovery", "set", "Genre", [OFF_LIST]),
        ]
        for name, how, key, values in cases:
            with self.subTest(album=name, how=how):
                edits: dict[str, dict[str, Any]] = {"set": dict(self.GOOD), "add": {}, "remove": {}}
                edits[how][key] = values
                album = self.preview(self.draft(self.path(name), edit(**edits)))
                self.assertEqual([entry["key"] for entry in album["refused"]], ["Genre"])
                self.assertIn(OFF_LIST, album["refused"][0]["reason"])
                self.assertEqual(self.changes(album),
                                 {track: {"Composer": (None, ["Tony Kakko"])} for track in self.tracks(name)})

    def test_a_genre_off_the_list_is_refused_under_the_formats_own_key_too(self) -> None:
        for name, key in (("silence", "TCON"), ("ecliptica", "genre")):
            with self.subTest(album=name):
                album = self.preview(self.draft(self.path(name), edit(set={key: [OFF_LIST]})))
                self.assertEqual(len(album["refused"]), 1, album["refused"])
                self.assertIn(album["refused"][0]["key"], (key, "Genre"))
                self.assertIn(OFF_LIST, album["refused"][0]["reason"])
                self.assertEqual(album["tracks"], [])

    def test_the_two_custom_genres_are_planned_like_any_on_the_list(self) -> None:
        now = ["video game music", "soundtrack"]
        album = self.preview(self.draft(self.path("ecliptica"), edit(set={"Genre": now})))
        self.assertEqual(album["refused"], [])
        self.assertEqual(self.changes(album), {track: {"Genre": (["power metal", "heavy metal"], now)}
                                               for track in self.tracks("ecliptica")})


class KeepsAKeyWithNoReadableNameToOneFormat(EditorCase):
    """A key no format's table gives a readable name is one format's own, and an edit over two formats may not carry it.

    `discovery` is a FLAC, an MP3 and a FLAC. `TXXX:MOOD` is an MP3's key and
    `mood` a FLAC's, and neither has a readable name. Sent over all three
    tracks, the first would be planned into the FLACs as `txxx:mood`.
    """

    def test_such_a_key_in_an_edit_over_an_mp3_and_a_flac_is_refused_by_name_and_planned_on_neither(self) -> None:
        tracks = self.tracks("discovery")
        for how, key in (("set", "TXXX:MOOD"), ("set", "mood"), ("add", "MOOD")):
            with self.subTest(how=how, key=key):
                changes: dict[str, dict[str, Any]] = {"set": {"Composer": ["Daft Punk"]}, "add": {}, "remove": {}}
                changes[how][key] = ["calm"]
                album = self.preview(self.draft(self.path("discovery"), edit(**changes)))
                # Once, under the key as sent: the page shows the sentence beside the row the owner typed.
                self.assertEqual(album["refused"], [{"key": key, "reason": ONE_FORMAT}])
                # The composer shows the draft was planned. The key is on no track, of either format.
                self.assertEqual(self.changes(album), {track: {"Composer": (None, ["Daft Punk"])} for track in tracks})

    def test_such_a_key_in_an_edit_over_the_tracks_of_one_format_of_that_album_is_planned(self) -> None:
        flac, mp3, other = self.tracks("discovery")
        vorbis, id3 = edit((flac, other), set={"mood": ["calm"]}), edit((mp3,), set={"TXXX:MOOD": ["calm"]})
        cases = {
            "the two FLACs": ((vorbis,), {flac: {"mood": (None, ["calm"])}, other: {"mood": (None, ["calm"])}}),
            "the MP3": ((id3,), {mp3: {"TXXX:MOOD": (None, ["calm"])}}),
            # The rule counts the formats of one edit's tracks, and not those of the album or of the draft.
            "each format in an edit of its own": ((vorbis, id3), {flac: {"mood": (None, ["calm"])},
                                                                  mp3: {"TXXX:MOOD": (None, ["calm"])},
                                                                  other: {"mood": (None, ["calm"])}}),
        }
        for name, (edits, planned) in cases.items():
            with self.subTest(name):
                album = self.preview(self.draft(self.path("discovery"), *edits))
                self.assertEqual(album["refused"], [])
                self.assertEqual(self.changes(album), planned)


class NamesTheRulesADraftBreaks(EditorCase):
    """`problems` holds the rules the draft newly breaks, each naming the track by its path."""

    def rules(self, album: dict[str, Any]) -> list[str]:
        return [problem["rule"] for problem in album["problems"]]

    def named(self, album: dict[str, Any], *tracks: str) -> list[str]:
        """Which of `tracks` some problem of `album` names in its detail."""
        return [track for track in tracks if any(track in problem["detail"] for problem in album["problems"])]

    def test_removing_a_tracks_only_genre_names_the_rule_and_that_track(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit(remove={"Genre": ["death metal"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Genre": (["progressive metal", "death metal"], ["progressive metal"])},
            BLEAK: {"Genre": (["death metal"], None)},
        })
        self.assertEqual(self.rules(album), ["no genre"])
        self.assertEqual(self.named(album, LEPER, BLEAK, HARVEST), [BLEAK])

    def test_a_track_that_had_no_genre_before_the_draft_is_not_named(self) -> None:
        # The draft selects the genreless track as well, and changes nothing on it.
        album = self.preview(self.draft(GAPPED, edit(remove={"Genre": ["death metal"]})))
        self.assertEqual(self.changes(album), {
            APRIL: {"Genre": (["death metal"], None)},
            WHEN: {"Genre": (["death metal", "progressive metal"], ["progressive metal"])},
        })
        self.assertEqual(self.rules(album), ["no genre"])
        self.assertEqual(self.named(album, APRIL, WHEN, MADRIGAL), [APRIL])

    def test_a_required_tag_removed_from_one_track_is_named_though_another_track_already_lacks_it(self) -> None:
        # The engine's detail for a missing artist is the same text on every track,
        # so the new one is lost where problems are compared by their text alone.
        album = self.preview(self.draft(GAPPED, edit((APRIL,), set={"Artist": None})))
        self.assertEqual(self.changes(album), {APRIL: {"Artist": (["Opeth"], None)}})
        self.assertEqual(self.rules(album), ["required field"])
        self.assertEqual(self.named(album, APRIL, WHEN, MADRIGAL), [APRIL])

    def test_a_doubled_space_names_each_track_the_draft_gives_it_to(self) -> None:
        album = self.preview(self.draft(UNEVEN, edit((LEPER, HARVEST), set={"Composer": ["Mikael  Akerfeldt"]})))
        self.assertEqual(self.changes(album), {
            LEPER: {"Composer": ([COMPOSER], ["Mikael  Akerfeldt"])},
            HARVEST: {"Composer": (None, ["Mikael  Akerfeldt"])},
        })
        self.assertEqual(self.rules(album), ["whitespace", "whitespace"])
        self.assertEqual(self.named(album, LEPER, BLEAK, HARVEST), [LEPER, HARVEST])

    def test_a_track_given_a_number_another_track_of_its_disc_holds_names_the_rule_and_that_track(self) -> None:
        # The titles differ, so the two file names do not collide: the rule is all that says it.
        album = self.preview(self.draft(UNEVEN, edit((BLEAK,), set={"Track number": ["1"]})))
        self.assertEqual(self.changes(album), {BLEAK: {"Track number": (["2"], ["1"])}})
        self.assertEqual({*self.rules(album)}, {"track number"})
        named = self.named(album, LEPER, BLEAK, HARVEST)
        # The track that held the number first may be named too.
        self.assertIn(BLEAK, named)
        self.assertNotIn(HARVEST, named)

    def test_a_number_a_track_of_another_disc_holds_breaks_nothing(self) -> None:
        # Before the draft no other track is a 2, on either disc: a rule that forgot
        # the disc would see the number shared for the first time. `fragile` cannot
        # show it, both of its discs already count 1, 2.
        album = self.preview(self.draft(LOPSIDED, edit((ATONEMENT,), set={"Track number": ["2"]})))
        self.assertEqual(self.changes(album), {ATONEMENT: {"Track number": (["1"], ["2"])}})
        self.assertNotIn("track number", self.rules(album))
        self.assertEqual(self.named(album, HOUNDS), [])

    def test_a_number_given_to_two_tracks_of_one_disc_in_a_two_disc_album_names_the_rule(self) -> None:
        # The first disc holds no 3, and the draft puts two on the second.
        first, second = self.tracks("fragile")[2], self.tracks("fragile")[3]
        self.assertEqual((first[:4], second[:4]), ("CD2/", "CD2/"))
        album = self.preview(self.draft(self.path("fragile"), edit((first, second), set={"Track number": ["3"]})))
        self.assertIn("track number", self.rules(album))
        numbered = [problem["detail"] for problem in album["problems"] if problem["rule"] == "track number"]
        self.assertTrue(any(first in detail or second in detail for detail in numbered), numbered)

    def test_two_tracks_that_shared_a_number_before_the_draft_do_not_block_it(self) -> None:
        album = self.preview(self.draft(DOUBLED, edit(set={"Composer": [COMPOSER]})))
        self.assertEqual(sorted(self.changes(album)), [MOOR, BENIGHTED, MELINDA])
        self.assertEqual(album["problems"], [])

    def test_a_third_track_given_the_number_two_already_share_is_named_and_they_are_not(self) -> None:
        album = self.preview(self.draft(DOUBLED, edit((MELINDA,), set={"Track number": ["1"]})))
        self.assertEqual({*self.rules(album)}, {"track number"})
        self.assertEqual(self.named(album, MOOR, BENIGHTED, MELINDA), [MELINDA])

    def test_a_track_in_a_disc_folder_is_named_with_the_folder(self) -> None:
        # The engine names a track by its file name alone. Two discs can each hold an `01`.
        track = self.tracks("fragile")[2]
        self.assertEqual(track, "CD2/01. The Way Out Is Through.flac")
        album = self.preview(self.draft(self.path("fragile"), edit((track,), set={"Genre": None})))
        self.assertEqual(self.changes(album), {track: {"Genre": (["industrial rock", "electronic"], None)}})
        self.assertEqual(self.rules(album), ["no genre"])
        self.assertIn(track, album["problems"][0]["detail"])

    def test_a_genre_one_edit_removes_and_a_later_edit_sets_breaks_nothing(self) -> None:
        # The rules judge the album as the whole draft leaves it, not as it stands between two edits.
        album = self.preview(self.draft(UNEVEN, edit((BLEAK,), set={"Genre": None}),
                                        edit((BLEAK,), set={"Genre": ["doom metal"]})))
        self.assertEqual(self.changes(album), {BLEAK: {"Genre": (["death metal"], ["doom metal"])}})
        self.assertEqual(album["problems"], [])

    def test_a_draft_that_leaves_the_broken_rules_alone_has_no_problems(self) -> None:
        cases = [
            # No genre and no artist on the last track.
            (GAPPED, (APRIL, WHEN, MADRIGAL), {"Composer": ["Mikael Akerfeldt"]}),
            # No MusicBrainz id on any track, and a rating the rules do not know.
            (self.path("fullmoon"), self.tracks("fullmoon"), {"Composer": ["Tony Kakko"]}),
            # A file beside the tracks that no reader opens.
            (self.path("images"), self.tracks("images"), {"Composer": ["John Petrucci"]}),
        ]
        for path, tracks, composer in cases:
            with self.subTest(album=path):
                album = self.preview(self.draft(path, edit(set=composer)))
                self.assertEqual(sorted(self.changes(album)), sorted(tracks))
                self.assertEqual(album["problems"], [])


class RefusesAPathOutsideTheLibrary(shelf.LibraryCase):
    """A draft naming a path that leaves the library is a 404 that read nothing.

    A missing route is a 404 too, so each case first shows that the route
    plans a draft over the album inside. The outside album's genre is in no
    request, so a body that carries it was read from the file.
    """

    INSIDE = "S/Real Artist/(2000) Real"
    OTHER = "S/Real Artist/(2001) Other"
    TRACK = "01. Inside.flac"
    QUIET = "01. Quiet Song.flac"
    MARK = b"SECRET GENRE"

    outside: Path
    secret: Path

    @classmethod
    def lay(cls, root: Path) -> None:
        builders.library_album(root, letter="S", artist="Real Artist", date="2000-01-01", album="Real",
                               discs=(("Inside",),))
        builders.library_album(root, letter="S", artist="Real Artist", date="2001-01-01", album="Other",
                               discs=(("Elsewhere",),))
        cls.outside = cls.root / "outside"
        cls.secret = builders.library_album(cls.outside, letter="Q", artist="Quiet Artist", date="2000-01-01",
                                            album="Secret", discs=(("Quiet Song",),))
        builders.write_tags(cls.secret / cls.QUIET, {"GENRE": [cls.MARK.decode()]})
        (root / "Q").symlink_to(cls.outside / "Q", target_is_directory=True)
        (root / "S" / "Linked Artist").symlink_to(cls.secret.parent, target_is_directory=True)
        (root / "S" / "Real Artist" / "(2000) Linked").symlink_to(cls.secret, target_is_directory=True)
        (root / cls.INSIDE / "02. Linked.flac").symlink_to(cls.secret / cls.QUIET)

    def naming(self, album: str, track: str, real: Path, seen: list[str] | None = None) -> dict[str, Any]:
        """One track of a draft, `loaded` as the file at `real` is.

        No page could have shown a track outside the library, so `seen` is empty there.
        """
        stat = real.stat()
        return {"album": album, "path": track, "loaded": {"size": stat.st_size, "mtime": stat.st_mtime},
                "seen": {"Genre": seen}}

    def inside(self) -> dict[str, Any]:
        return self.naming(self.INSIDE, self.TRACK, self.shelf / self.INSIDE / self.TRACK,
                           ["industrial rock", "electronic"])

    def send(self, *tracks: dict[str, Any], batch: bool) -> shelf.neighbour.Answer:
        """A preview of one edit, a genre set on every one of `tracks`, sent as a batch or as the album page's draft."""
        named = [{"album": track["album"], "path": track["path"]} for track in tracks]
        return post(self.port, PREVIEW, {
            "tracks": list(tracks), "swaps": [], "cover": None, "batch": batch,
            "edits": [{"tracks": named, "set": {"Genre": ["jazz"]}, "add": {}, "remove": {}}],
        })

    def setUp(self) -> None:
        got = self.send(self.inside(), batch=False)
        self.assertEqual(got.status, 200, f"POST {PREVIEW} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual([track["path"] for track in json.loads(got.body)["albums"][0]["tracks"]], [self.TRACK])

    def refused(self, places: list[tuple[str, str]]) -> None:
        """Each `(album, track)` is a 404 with nothing of the outside file in it, alone and beside a track inside.

        Alone it is sent as each page sends a draft. Beside a track inside
        it names two albums wherever the album is not `INSIDE`, which the
        album page's draft may not: that one is turned down as malformed
        before any path is looked at. So the pair goes as a batch.
        """
        real = self.secret / self.QUIET
        for album, track in places:
            for beside, batch in (((), False), ((), True), ((self.inside(),), True)):
                with self.subTest(album=album, track=track, beside_a_track_inside=bool(beside), batch=batch):
                    got = self.send(*beside, self.naming(album, track, real), batch=batch)
                    self.assertEqual(got.status, 404, got.body[:300])
                    self.assertNotIn(self.MARK, got.body)

    def test_an_album_that_climbs_with_dots_is_404(self) -> None:
        self.refused([
            ("..", "outside/Q/Quiet Artist/(2000) Secret/" + self.QUIET),
            ("../outside/Q/Quiet Artist/(2000) Secret", self.QUIET),
            ("S/../../outside/Q/Quiet Artist/(2000) Secret", self.QUIET),
            (f"{self.INSIDE}/../../../../outside/Q/Quiet Artist/(2000) Secret", self.QUIET),
        ])

    def test_an_absolute_album_is_404(self) -> None:
        self.refused([
            (str(self.secret), self.QUIET),
            # Joined to the root as written, an absolute part replaces the root.
            (f"S/Real Artist/{self.secret}", self.QUIET),
        ])

    def test_an_album_reached_through_a_symlink_out_of_the_library_is_404(self) -> None:
        self.refused([
            ("Q/Quiet Artist/(2000) Secret", self.QUIET),
            ("S/Linked Artist/(2000) Secret", self.QUIET),
            ("S/Real Artist/(2000) Linked", self.QUIET),
        ])

    def test_a_track_that_leaves_its_album_by_dots_an_absolute_path_or_a_symlink_is_404(self) -> None:
        self.refused([
            (self.INSIDE, "../../../../outside/Q/Quiet Artist/(2000) Secret/" + self.QUIET),
            (self.INSIDE, str(self.secret / self.QUIET)),
            (self.INSIDE, "02. Linked.flac"),
        ])

    def test_a_track_that_climbs_into_another_album_of_the_library_is_404(self) -> None:
        # Still under the root, and not a track of the album the draft says it is in.
        real = self.shelf / self.OTHER / "01. Elsewhere.flac"
        self.assertTrue(real.is_file())
        for batch in (False, True):
            with self.subTest(batch=batch):
                got = self.send(self.naming(self.INSIDE, "../(2001) Other/01. Elsewhere.flac", real,
                                            ["industrial rock", "electronic"]), batch=batch)
                self.assertEqual(got.status, 404, got.body[:300])


if __name__ == "__main__":
    unittest.main()
