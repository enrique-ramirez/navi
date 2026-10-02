"""agitha's batch: a draft over more than one album, previewed and saved by the routes the album page uses.

There is no batch route. `POST /api/library/preview` answers one entry per
album the draft's tracks name, and an album the batch leaves out says why in
`skip`. `POST /api/library/save` writes the albums that change, one after
another, as one job with an entry per album.

The server, the drafts and the faults are `tests.test_agitha_save`'s: each
case has its own folders and its own server over `builders.library`. A batch
draft is the drafts `EditorCase.draft` builds for each album, joined: every
edit names its tracks in all of them. The albums go in the draft in an order
that is not their folder order, so an answer that sorted them shows.

The artist is Sonata Arctica. `ecliptica`, `silence` and `winterheart` carry
`power metal`; `stones` and `fullmoon` do not. `silence` and `fullmoon` are
MP3, the rest FLAC, so one readable name is written under two keys. `fullmoon`
has no MusicBrainz id and its tracks carry `heavy metal` alone.

`BatchCase.lay_drop_album` lays by hand what a match leaves in the inbox.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote

from musiclib import files, tagwrite
from tests import builders
from tests import test_agitha_editor as editor_tests
from tests import test_agitha_library_cover as cover_tests
from tests import test_agitha_save as save_tests

shelf_tests = save_tests.shelf_tests
edit = editor_tests.edit
held = save_tests.held

NOTHING = "nothing to change"
IN_REVIEW = "open in review"
CHANGED = "changed since this page loaded"
ON_ITS_PAGE = "is edited on the album's page"
NOTHING_TO_SAVE = "nothing to save"
ONE_FORMAT = editor_tests.ONE_FORMAT

#: Every Sonata Arctica album of the fixture, in neither folder order nor title order.
SONATA = ("stones", "ecliptica", "winterheart", "silence", "fullmoon")
#: On MusicBrainz's list, and on no track of the fixture.
FOLK = "folk metal"
#: The keys of one album of a preview, as the page's fixture has them.
KEYS = sorted(json.loads(editor_tests.CONTRACT.read_text(encoding="utf-8"))["albums"][0])

#: The tags only the album's page edits: readable name, the FLAC's key, the MP3's key, a value to set.
PAGE_TAGS = (
    ("Title", "title", "TIT2", ["Replica"]),
    ("Artist", "artist", "TPE1", ["The Band"]),
    ("Album artist", "albumartist", "TPE2", ["The Band"]),
    ("Artist sort order", "artistsort", "TSOP", ["Band, The"]),
    ("Album artist sort order", "albumartistsort", "TSO2", ["Band, The"]),
    ("Album", "album", "TALB", ["Reckoning Night"]),
    ("Date", "date", "TDRC", ["2004-10-06"]),
    ("Original release date", "originaldate", "TDOR", ["2004-10-06"]),
    ("Track number", "tracknumber", "TRCK", ["7"]),
    ("Disc number", "discnumber", "TPOS", ["2"]),
    ("Disc subtitle", "discsubtitle", "TSST", ["The Demos"]),
)


def over(one: dict[str, Any], **tracks: tuple[str, ...] | None) -> dict[str, Any]:
    """The edit `one` over the tracks given for each album handle, `None` for all of them, and over no other album."""
    return {**one, "tracks": tracks}


def genre_key(track: str) -> str:
    """The key `held` reads a track's genres under."""
    return "TCON" if track.endswith(".mp3") else "genre"


def with_genres(was: dict[str, Any], track: str, genres: list[str]) -> dict[str, Any]:
    """`held` of a track as it was, holding `genres` and everything else as before."""
    return {**was, "tags": {**was["tags"], genre_key(track): genres}}


class BatchCase(save_tests.SaveCase):
    """`SaveCase` with a draft over several albums, a preview read per album, and a job settled album by album."""

    changes = editor_tests.EditorCase.changes

    def setUp(self) -> None:
        super().setUp()
        # Runs before the folders go: a save the server should have refused may still be writing into them.
        self.addCleanup(self.wait_for_the_worker)

    def wait_for_the_worker(self) -> None:
        deadline = time.monotonic() + save_tests.DEADLINE
        while time.monotonic() < deadline:
            pages = [self.fetch(shelf_tests.address(self.path(name))) for name in SONATA]
            if not any(page.status == 200 and json.loads(page.body).get("job") for page in pages):
                return
            time.sleep(0.05)

    def batch(self, names: tuple[str, ...], *edits: dict[str, Any]) -> dict[str, Any]:
        """A draft of `edits` over the fixture albums `names`, in that order, as an artist page would send it.

        An edit made by `edit()` with no tracks names every track of every
        album. One narrowed by `over` names the tracks given for each album.
        """
        drafts = []
        for name in names:
            mine = [{**one, "tracks": one["tracks"].get(name, ())} if isinstance(one["tracks"], dict) else one
                    for one in edits]
            drafts.append(self.draft(self.path(name), *mine))
        return {
            "tracks": [track for draft in drafts for track in draft["tracks"]],
            "edits": [{**one, "tracks": [ref for draft in drafts for ref in draft["edits"][index]["tracks"]]}
                      for index, one in enumerate(drafts[0]["edits"])],
            "swaps": [], "cover": None, "batch": True,
        }

    def previewed(self, draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """The albums a preview of `draft` answers, by path: one for each album it names, in the draft's order."""
        got = self.post(editor_tests.PREVIEW, draft)
        self.assertEqual(got.status, 200, f"POST {editor_tests.PREVIEW} answered {got.status}: {got.body[:300]!r}")
        self.assertEqual(got.headers["Content-Type"], "application/json; charset=utf-8")
        albums = json.loads(got.body)["albums"]
        self.assertEqual([album["path"] for album in albums],
                         list(dict.fromkeys(track["album"] for track in draft["tracks"])))
        for album in albums:
            self.assertEqual(sorted(album), KEYS, album["path"])
        return {album["path"]: album for album in albums}

    def outcome(self, albums: dict[str, dict[str, Any]]) -> dict[str, tuple[Any, Any]]:
        """`{path: (skip, {track: {key: (before, after)}})}`. An album left out lists no track."""
        out = {}
        for path, album in albums.items():
            if album["skip"] is not None:
                self.assertEqual(album["tracks"], [], f"{path} is skipped and still lists tracks")
            out[path] = (album["skip"], self.changes(album))
        return out

    def assert_nothing_moves(self, albums: dict[str, dict[str, Any]]) -> None:
        for path, album in albums.items():
            self.assertEqual(album["new_path"], path)
            self.assertEqual([track["new_path"] for track in album["tracks"]],
                             [track["path"] for track in album["tracks"]], path)

    def adding(self, name: str, genre: str, *, to: tuple[str, ...] | None = None) -> dict[str, dict[str, Any]]:
        """The changes of a preview that adds `genre` after the genres the fixture gave each track of `name`."""
        was = list(self.library.albums[name].genres)
        return {track: {"Genre": (was, [*was, genre])} for track in to or self.tracks(name)}

    def files_of(self, *names: str, only: dict[str, tuple[str, ...]] | None = None) -> list[str]:
        """The track files of the albums `names` as `on_disk` names them."""
        return sorted(f"shelf/{self.path(name)}/{track}" for name in names
                      for track in (only or {}).get(name, self.tracks(name)))

    def genres(self, name: str) -> list[list[str] | None]:
        """What each track of the album holds as its genres now, in track order."""
        return [held(self.shelf / self.path(name) / track)["tags"].get(genre_key(track))
                for track in self.tracks(name)]

    def settle_all(self, job: str) -> list[dict[str, Any]]:
        """The job's albums once each reads `done` or `failed`, having checked the states each went through."""
        seen: dict[str, list[str]] = {}
        listed: list[str] | None = None
        deadline = time.monotonic() + save_tests.DEADLINE
        while True:
            albums = self.answer(f"/api/library/jobs/{quote(job, safe='')}")["albums"]
            paths = [album["path"] for album in albums]
            self.assertEqual(paths, listed or paths)
            listed = paths
            for album in albums:
                self.assertIn(album["state"], save_tests.ORDER)
                if album["state"] != "failed":
                    self.assertIsNone(album["error"], album)
                states = seen.setdefault(album["path"], [])
                if states[-1:] != [album["state"]]:
                    states.append(album["state"])
            if all(album["state"] in ("done", "failed") for album in albums):
                break
            if time.monotonic() > deadline:
                self.fail(f"the job did not settle in {save_tests.DEADLINE} s; its albums went through {seen}")
            time.sleep(0.02)
        for path, states in seen.items():
            self.assertEqual(states, sorted(set(states), key=save_tests.ORDER.index), f"{path}: states out of order")
        return albums

    def applied(self, draft: dict[str, Any]) -> list[dict[str, Any]]:
        """Saves `draft` and waits for every album of its job. Checks what every batch promises; returns the albums."""
        remembered = self.memory_files()
        job = self.accepted(draft)
        albums = self.settle_all(job)
        self.assertEqual(self.memory_files(), remembered, "a memory file changed")
        if all(album["state"] == "done" for album in albums):
            self.assertFalse((self.config.jobs / "library-edits" / job).exists(), "the work folder is still there")
            self.assertEqual(self.copies_in_jobs(), [], "the jobs folder still holds a copy of an album")
        return albums

    def done(self, *names: str) -> list[dict[str, Any]]:
        """The albums of a job in which each of `names` landed where it was."""
        return [{"path": self.path(name), "new_path": self.path(name), "state": "done", "error": None}
                for name in names]

    def lay_drop_album(self, name: str, drop: str, replaces: str | None) -> Path:
        """One album in the inbox as a finished drop of one folder, a copy of the library's `name`. Returns `<drop>/01`.

        With `replaces`, it is what a match leaves: `inbox/<drop>/drop.json`
        (`started`, `items`, `done`), `inbox/<drop>/01/album.json` (`n`,
        `name`, `item`, `state: "ready"`, `stderr`, `error` and `replaces`,
        the library-relative path), and a copy of the library's folder at
        `inbox/<drop>/01/drop/album/<folder name>/`. No job folder is laid.
        Without `replaces`, `album.json` has no such key: an upload.
        """
        entry = self.library.albums[name]
        folder = self.config.inbox / drop
        staged = folder / "01" / "drop" / "album" / entry.folder.name
        shutil.copytree(entry.folder, staged)
        listed = [{"path": path.relative_to(staged).as_posix(), "size": path.stat().st_size}
                  for path in sorted(staged.rglob("*")) if path.is_file()]
        (folder / "drop.json").write_text(json.dumps({
            "started": "2026-10-02T10:15:00", "done": True,
            "items": [{"name": entry.folder.name, "kind": "folder", "files": listed}],
        }), encoding="utf-8")
        record = {"n": "01", "name": entry.folder.name, "item": entry.folder.name, "state": "ready",
                  "stderr": "", "error": None}
        if replaces is not None:
            record["replaces"] = replaces
        (folder / "01" / "album.json").write_text(json.dumps(record), encoding="utf-8")
        shown = next(one for one in self.answer("/api/drops") if one["id"] == drop)
        self.assertEqual([album["n"] for album in shown["albums"]], ["01"])
        return folder / "01"

    def lay_open_match(self, name: str) -> str:
        """A match open for `name`, beside an upload of another album that replaces nothing. Returns the match's id."""
        self.lay_drop_album("fullmoon", "20261002-090000", None)
        self.lay_drop_album(name, "20261002-101500", self.path(name))
        return "20261002-101500"

    @contextlib.contextmanager
    def failing_writes(self, name: str) -> Iterator[list[str]]:
        """Every `tagwrite.write` into a copy of the album `name` fails to verify. Yields the files it was asked for."""
        real = tagwrite.write
        inside = f"/{self.path(name)}/"
        refused: list[str] = []

        def write(track: files.Track, *args: Any, **kwargs: Any) -> files.Track:
            if inside in os.path.realpath(track.path).replace(os.sep, "/"):
                refused.append(Path(track.path).name)
                raise tagwrite.VerifyError(f"{track.path}: write did not verify (injected by the test)")
            return real(track, *args, **kwargs)

        with mock.patch.object(tagwrite, "write", write):
            yield refused


class PreviewsABatch(BatchCase):
    """Every album the selection touches, with the tracks that change or the reason it is left out."""

    def test_an_add_over_the_artist_lists_the_tracks_that_lack_the_genre_and_skips_the_albums_that_carry_it(
            self) -> None:
        # Two albums lack the genre and change, three carry it and are skipped. `fullmoon` breaks rules as it
        # stands (no MusicBrainz id), and a rule an album already breaks does not leave it out.
        draft = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        before = self.on_disk()
        with editor_tests.nobody_else_asked() as asked:
            albums = self.previewed(draft)
        self.assertEqual(self.outcome(albums), {
            self.path("stones"): (None, self.adding("stones", "power metal")),
            self.path("ecliptica"): (NOTHING, {}),
            self.path("winterheart"): (NOTHING, {}),
            self.path("silence"): (NOTHING, {}),
            self.path("fullmoon"): (None, self.adding("fullmoon", "power metal")),
        })
        self.assert_nothing_moves(albums)
        for path, album in albums.items():
            with self.subTest(album=path):
                self.assertEqual({key: album[key] for key in ("cover", "problems", "refused")},
                                 {"cover": None, "problems": [], "refused": []})
        self.assertEqual(asked, [])
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])

    def test_a_remove_of_a_genre_no_track_carries_lists_no_track_and_skips_every_album(self) -> None:
        albums = self.previewed(self.batch(SONATA, edit(remove={"Genre": ["pop"]})))
        self.assertEqual(self.outcome(albums), {self.path(name): (NOTHING, {}) for name in SONATA})

    def test_each_edit_changes_the_tracks_it_names_in_each_album_and_no_other(self) -> None:
        # The first edit names one track of `stones` and all of `fullmoon`, the second `fullmoon` alone.
        first = self.tracks("stones")[0]
        draft = self.batch(("stones", "fullmoon"),
                           over(edit(add={"Genre": [FOLK]}), stones=(first,), fullmoon=None),
                           over(edit(set={"Composer": ["Tony Kakko"]}), fullmoon=None))
        self.assertEqual(self.outcome(self.previewed(draft)), {
            self.path("stones"): (None, self.adding("stones", FOLK, to=(first,))),
            self.path("fullmoon"): (None, {track: {**changes, "Composer": (None, ["Tony Kakko"])}
                                           for track, changes in self.adding("fullmoon", FOLK).items()}),
        })


class LeavesToTheAlbumsPageWhatNamesOrMoves(BatchCase):
    """Over more than one album, a tag that names a track or an album or moves a file is refused by name.

    Each draft also adds a genre no track carries. That change is planned
    beside the refusal, in both albums, and nothing else is.
    """

    #: One FLAC album and one MP3 album.
    PAIR = ("ecliptica", "silence")

    def good(self) -> dict[str, tuple[Any, Any]]:
        return {self.path(name): (None, self.adding(name, FOLK)) for name in self.PAIR}

    def test_each_such_tag_is_refused_under_its_readable_name_and_the_rest_of_the_draft_is_planned(self) -> None:
        cases: list[tuple[str, str, list[str] | None]] = [(name, "set", value) for name, _, _, value in PAGE_TAGS]
        cases += [("Date", "set", None), ("Artist", "add", ["Timo Kotipelto"]), ("Title", "remove", ["My Land"]),
                  ("Track number", "remove", ["1"])]
        for name, how, values in cases:
            with self.subTest(key=name, how=how, values=values):
                changes: dict[str, Any] = {"set": {}, "add": {"Genre": [FOLK]}, "remove": {}}
                changes[how][name] = values
                albums = self.previewed(self.batch(self.PAIR, edit(**changes)))
                self.assertEqual({path: album["refused"] for path, album in albums.items()},
                                 {self.path(one): [{"key": name, "reason": ON_ITS_PAGE}] for one in self.PAIR})
                self.assertEqual(self.outcome(albums), self.good())
                # A number set on every track, or one title for all, is no problem where it is not planned.
                self.assertEqual({path: album["problems"] for path, album in albums.items()},
                                 {self.path(one): [] for one in self.PAIR})
                self.assert_nothing_moves(albums)

    def test_each_such_tag_is_refused_under_each_formats_own_key(self) -> None:
        flac, mp3 = (self.path(name) for name in self.PAIR)
        # A Vorbis name has no case, so the FLAC's key is sent in capitals for half of them.
        cases = [(name, own.upper() if index % 2 else own, flac, mp3)
                 for index, (name, own, _, _) in enumerate(PAGE_TAGS)]
        cases += [(name, own, mp3, flac) for name, _, own, _ in PAGE_TAGS]
        values = {name: value for name, _, _, value in PAGE_TAGS}
        for name, key, holder, other in cases:
            with self.subTest(key=key):
                albums = self.previewed(self.batch(self.PAIR, edit(set={key: values[name]}, add={"Genre": [FOLK]})))
                refused = albums[holder]["refused"]
                self.assertEqual([entry["reason"] for entry in refused], [ON_ITS_PAGE], refused)
                # As for a MusicBrainz id, the answer may name the key as sent or by its readable name.
                self.assertIn(refused[0]["key"], (key, name))
                # The album of the other format may list the key as refused too. It plans nothing for it.
                self.assertEqual([entry["reason"] for entry in albums[other]["refused"]
                                  if entry["reason"] != ON_ITS_PAGE], [])
                self.assertEqual(self.outcome(albums), self.good())
                self.assert_nothing_moves(albums)

    def test_applying_a_batch_that_names_a_title_writes_the_rest_of_it_and_renames_no_file(self) -> None:
        first = self.tracks("stones")[0]
        only = {"stones": (first,)}
        draft = self.batch(("stones", "fullmoon"),
                           over(edit(set={"Title": ["Replica"]}), stones=(first,), fullmoon=None),
                           over(edit(add={"Genre": ["power metal"]}), stones=(first,), fullmoon=None))
        before = self.on_disk()
        was = {name: self.holds(self.path(name), self.tracks(name)) for name in ("stones", "fullmoon")}

        self.assertEqual(self.applied(draft), self.done("stones", "fullmoon"))

        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", "fullmoon", only=only))
        for name, tracks in (("stones", (first,)), ("fullmoon", self.tracks("fullmoon"))):
            now = self.holds(self.path(name), tracks)
            for track in tracks:
                with self.subTest(album=name, track=track):
                    genres = [*self.library.albums[name].genres, "power metal"]
                    self.assertEqual(now[track], with_genres(was[name][track], track, genres))

    def test_a_batch_of_nothing_but_a_title_is_refused_and_writes_nothing(self) -> None:
        # Nothing of it is planned, so there is nothing to save.
        self.refused(self.batch(("stones", "fullmoon"), edit(set={"Title": ["Replica"]})))

    def turned_down(self, draft: dict[str, Any], word: str) -> None:
        """A preview and a save of `draft` are each a 400 whose sentence has `word`, and nothing is written."""
        before = self.on_disk()
        for route in (editor_tests.PREVIEW, save_tests.SAVE):
            with self.subTest(route=route):
                got = self.post(route, draft)
                self.assertEqual(got.status, 400, got.body[:300])
                body = json.loads(got.body)
                self.assertEqual(list(body), ["error"])
                self.assertIn(word, body["error"].lower())
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])

    def test_a_swap_in_a_draft_over_two_albums_is_refused_by_name_and_writes_nothing(self) -> None:
        draft = self.batch(("stones", "fullmoon"), edit(add={"Genre": [FOLK]}))
        # Without the swap the draft is one the preview plans, so the 400 is the swap's.
        self.previewed(draft)
        draft["swaps"] = [list(self.tracks("stones"))]
        self.turned_down(draft, "swap")

    def test_a_swap_in_a_batch_over_one_album_is_refused_by_name_and_writes_nothing(self) -> None:
        # The artist page sends `batch: true` for a selection inside one album too. A swap renames files,
        # which is the album page's to do, however few albums the batch names.
        draft = self.batch(("stones",), edit(add={"Genre": [FOLK]}))
        self.previewed(draft)
        draft["swaps"] = [list(self.tracks("stones"))]
        self.turned_down(draft, "swap")

    def test_a_cover_in_a_draft_over_two_albums_is_refused_by_name_and_writes_nothing(self) -> None:
        draft = self.batch(("stones", "fullmoon"), edit(add={"Genre": [FOLK]}))
        uploaded = cover_tests.put(self.port, cover_tests.image(900, 900), "image/png")
        self.assertEqual(uploaded.status, 200, uploaded.body[:300])
        draft["cover"] = json.loads(uploaded.body)["cover"]
        self.turned_down(draft, "cover")


class SkipsAnAlbumTheChangeWouldBreak(BatchCase):
    """An album the change would push into breaking a rule is left out with the rule; the others go on."""

    def bares_fullmoon(self) -> dict[str, Any]:
        """Remove `heavy metal` over the artist: `fullmoon` carries nothing else, two albums keep another genre."""
        return self.batch(SONATA, edit(remove={"Genre": ["heavy metal"]}))

    def test_a_remove_that_leaves_a_track_bare_skips_its_album_with_the_rule_and_plans_the_others(self) -> None:
        fullmoon = self.path("fullmoon")
        # The sentence is the one the album's own page gives the problem: the rule, a colon, the detail.
        alone = self.post(editor_tests.PREVIEW, self.draft(fullmoon, edit(remove={"Genre": ["heavy metal"]})))
        self.assertEqual(alone.status, 200, alone.body[:300])
        spelt = [f"{problem['rule']}: {problem['detail']}"
                 for problem in json.loads(alone.body)["albums"][0]["problems"]]
        self.assertNotEqual(spelt, [], "the album's own preview names no rule, so the batch has none to give")

        found = self.outcome(self.previewed(self.bares_fullmoon()))

        skip, changes = found.pop(fullmoon)
        self.assertEqual(changes, {})
        self.assertIn(skip, spelt)
        self.assertTrue(skip.startswith("no genre: "), skip)
        self.assertTrue(any(track in skip for track in self.tracks("fullmoon")), skip)
        self.assertEqual(found, {
            self.path("stones"): (None, {track: {"Genre": (["heavy metal", "hard rock"], ["hard rock"])}
                                         for track in self.tracks("stones")}),
            self.path("ecliptica"): (None, {track: {"Genre": (["power metal", "heavy metal"], ["power metal"])}
                                            for track in self.tracks("ecliptica")}),
            self.path("winterheart"): (NOTHING, {}),
            self.path("silence"): (NOTHING, {}),
        })

    def test_applying_it_lands_the_others_and_leaves_the_skipped_album_as_it_was_and_free_to_edit(self) -> None:
        draft = self.bares_fullmoon()
        before = self.on_disk()

        self.assertEqual(self.applied(draft), self.done("stones", "ecliptica"))

        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", "ecliptica"))
        self.assertEqual(self.genres("stones"), [["hard rock"]] * 2)
        self.assertEqual(self.genres("ecliptica"), [["power metal"]] * 3)
        self.assertIsNone(self.job_of(self.path("fullmoon")))
        self.saved(self.path("fullmoon"), edit(set={"Composer": ["Tony Kakko"]}))


class SkipsAnAlbumOpenInReview(BatchCase):
    def test_an_album_with_a_match_open_is_skipped_until_the_match_is_discarded(self) -> None:
        drop = self.lay_open_match("stones")
        draft = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        # The upload beside the match is a copy of `fullmoon` and replaces nothing: `fullmoon` is planned.
        self.assertEqual(self.outcome(self.previewed(draft)), {
            self.path("stones"): (IN_REVIEW, {}),
            self.path("ecliptica"): (NOTHING, {}),
            self.path("winterheart"): (NOTHING, {}),
            self.path("silence"): (NOTHING, {}),
            self.path("fullmoon"): (None, self.adding("fullmoon", "power metal")),
        })

        discarded = self.fetch(f"/api/drops/{drop}/albums/01/discard", method="POST")
        self.assertEqual(discarded.status, 200, discarded.body[:300])
        self.assertFalse((self.config.inbox / drop / "01").exists())

        self.assertEqual(self.outcome(self.previewed(draft))[self.path("stones")],
                         (None, self.adding("stones", "power metal")))

    def test_applying_a_batch_writes_the_others_and_leaves_the_album_open_in_review_as_it_was(self) -> None:
        self.lay_open_match("stones")
        draft = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        before = self.on_disk()

        self.assertEqual(self.applied(draft), self.done("fullmoon"))

        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("fullmoon"))
        self.assertEqual(self.genres("fullmoon"), [["heavy metal", "power metal"]] * 2)


class SkipsAnAlbumThatChanged(BatchCase):
    NAMES = ("stones", "ecliptica", "winterheart", "fullmoon")

    def loaded(self) -> dict[str, Any]:
        """A draft adding a genre no track carries, so every album would change."""
        return self.batch(self.NAMES, edit(add={"Genre": [FOLK]}))

    def retag(self, name: str) -> None:
        """Somebody's tagger rewrites the genres of the album's second track after the page loaded."""
        builders.write_tags(self.shelf / self.path(name) / self.tracks(name)[1], {"GENRE": ["hard rock"]})

    def rate(self, name: str, draft: dict[str, Any]) -> None:
        """A player stores a rating in the album's first track after the page loaded. The genres stay as shown."""
        track = self.tracks(name)[0]
        builders.write_tags(self.shelf / self.path(name) / track, {"RATING": "5"})
        stat = (self.shelf / self.path(name) / track).stat()
        loaded = next(one["loaded"] for one in draft["tracks"]
                      if (one["album"], one["path"]) == (self.path(name), track))
        self.assertNotEqual({"size": stat.st_size, "mtime": stat.st_mtime}, loaded,
                            "the file reads as it did when the page loaded, so nothing is being tested")

    def test_an_album_that_lost_a_drafted_track_is_skipped_as_changed_and_the_others_are_planned(self) -> None:
        draft = self.loaded()
        (self.shelf / self.path("ecliptica") / self.tracks("ecliptica")[1]).unlink()
        self.assertEqual(self.outcome(self.previewed(draft)), {
            self.path("stones"): (None, self.adding("stones", FOLK)),
            self.path("ecliptica"): (CHANGED, {}),
            self.path("winterheart"): (None, self.adding("winterheart", FOLK)),
            self.path("fullmoon"): (None, self.adding("fullmoon", FOLK)),
        })

    def test_an_album_whose_drafted_tag_changed_is_skipped_and_one_that_only_gained_a_rating_is_planned(self) -> None:
        draft = self.loaded()
        self.retag("stones")
        self.rate("winterheart", draft)
        self.assertEqual(self.outcome(self.previewed(draft)), {
            self.path("stones"): (CHANGED, {}),
            self.path("ecliptica"): (None, self.adding("ecliptica", FOLK)),
            self.path("winterheart"): (None, self.adding("winterheart", FOLK)),
            self.path("fullmoon"): (None, self.adding("fullmoon", FOLK)),
        })

    def test_applying_a_batch_writes_the_albums_as_loaded_keeps_the_rating_and_leaves_the_changed_ones(self) -> None:
        draft = self.loaded()
        self.retag("stones")
        (self.shelf / self.path("ecliptica") / self.tracks("ecliptica")[1]).unlink()
        self.rate("winterheart", draft)
        before = self.on_disk()

        self.assertEqual(self.applied(draft), self.done("winterheart", "fullmoon"))

        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("winterheart", "fullmoon"))
        self.assertEqual(self.genres("winterheart"), [["power metal", "symphonic metal", FOLK]] * 2)
        self.assertEqual(self.genres("fullmoon"), [["heavy metal", FOLK]] * 2)
        rated = held(self.shelf / self.path("winterheart") / self.tracks("winterheart")[0])
        self.assertEqual(rated["tags"]["rating"], ["5"])


class AppliesABatch(BatchCase):
    """Each album is written and landed as a save lands one, one at a time, with nothing remembered."""

    THREE = ("stones", "ecliptica", "fullmoon")

    def test_an_apply_writes_the_draft_into_the_albums_that_change_and_nothing_else_anywhere(self) -> None:
        # Where no memory file exists none may appear: every apply checks that, in `applied`. Here both
        # are there, each in its engine's own shape, with something remembered for the release `stones` carries.
        release = self.library.albums["stones"].release_id
        (self.config.jobs.parent / "memory.json").write_text(
            json.dumps({"version": 1, "releases": {release: {"edits": []}}}) + "\n", encoding="utf-8")
        (self.config.jobs / "agitha-memory.json").write_text(
            json.dumps({"edits": {release: {"1-1": {"genre": ["hard rock"]}}}}), encoding="utf-8")
        self.assertNotIn(None, self.memory_files().values())
        self.assertIsNotNone(self.library.albums["stones"].release_id)
        self.assertIsNone(self.library.albums["fullmoon"].release_id)
        draft = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        before = self.on_disk()
        was = {name: self.holds(self.path(name), self.tracks(name)) for name in ("stones", "fullmoon")}
        # The rating, the added date and the POPM frame must survive the write.
        self.assertEqual(was["stones"][self.tracks("stones")[0]]["tags"]["rating"], ["4"])
        self.assertEqual(was["stones"][self.tracks("stones")[1]]["tags"]["added"], ["2026-09-01T18:30"])
        self.assertIn("POPM:no@email", was["fullmoon"][self.tracks("fullmoon")[0]]["tags"])

        with save_tests.no_way_out() as asked:
            albums = self.applied(draft)

        # The two that change, in the draft's order, which is not their folder order. The three skipped are in no job.
        self.assertEqual(albums, self.done("stones", "fullmoon"))
        # No path changed and no file came or went: the files that differ are the tracks written, and `memory.json`,
        # the covers and the three skipped albums are the bytes they were.
        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", "fullmoon"))
        for name in ("stones", "fullmoon"):
            now = self.holds(self.path(name), self.tracks(name))
            for track in self.tracks(name):
                with self.subTest(album=name, track=track):
                    genres = [*self.library.albums[name].genres, "power metal"]
                    self.assertEqual(now[track], with_genres(was[name][track], track, genres))
        self.assertEqual(asked, [])

    def test_each_album_is_written_only_once_the_one_before_it_is_done_and_the_job_says_so_as_it_goes(self) -> None:
        paths = [self.path(name) for name in self.THREE]
        draft = self.batch(self.THREE, edit(add={"Genre": [FOLK]}))
        real = tagwrite.write
        known = threading.Event()
        job: list[str] = []
        #: At each write: the album written into, and every album's state as the job route gave it then.
        watched: list[tuple[str | None, list[str]]] = []

        def write(track: files.Track, *args: Any, **kwargs: Any) -> files.Track:
            # The worker may reach its first write before the test has read the job's id.
            known.wait(save_tests.DEADLINE)
            if job:
                where = os.path.realpath(track.path).replace(os.sep, "/")
                album = next((path for path in paths if f"/{path}/" in where), None)
                answer = json.loads(self.fetch(f"/api/library/jobs/{quote(job[0], safe='')}").body)
                watched.append((album, [one["state"] for one in answer["albums"]]))
            return real(track, *args, **kwargs)

        with mock.patch.object(tagwrite, "write", write):
            try:
                job.append(self.accepted(draft))
            finally:
                known.set()
            albums = self.settle_all(job[0])

        self.assertEqual(albums, self.done(*self.THREE))
        expected = []
        for index, name in enumerate(self.THREE):
            states = ["done"] * index + ["writing"] + ["waiting"] * (len(self.THREE) - index - 1)
            expected += [(paths[index], states)] * len(self.tracks(name))
        self.assertEqual(watched, expected)

    def test_each_album_of_a_running_batch_carries_the_job_on_its_page_and_a_skipped_one_carries_none(self) -> None:
        draft = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        with self.held_mid_write(draft) as job:
            self.assertEqual(self.job_of(self.path("stones")), {"id": job, "state": "writing"})
            self.assertEqual(self.job_of(self.path("fullmoon")), {"id": job, "state": "waiting"})
            self.assertIsNone(self.job_of(self.path("ecliptica")))
        self.assertEqual(self.settle_all(job), self.done("stones", "fullmoon"))
        for name in ("stones", "fullmoon"):
            self.assertIsNone(self.job_of(self.path(name)), name)

    def test_a_write_that_fails_in_one_album_leaves_it_as_it_was_and_the_others_land(self) -> None:
        draft = self.batch(self.THREE, edit(add={"Genre": [FOLK]}))
        before = self.on_disk()

        with self.failing_writes("ecliptica") as refused:
            albums = self.applied(draft)

        self.assertNotEqual(refused, [], "no file of the album was written with `tagwrite.write`, so nothing failed")
        self.assertEqual([(album["path"], album["state"]) for album in albums],
                         [(self.path("stones"), "done"), (self.path("ecliptica"), "failed"),
                          (self.path("fullmoon"), "done")])
        self.assertEqual([album["error"] for album in albums if album["state"] == "done"], [None, None])
        reason = albums[1]["error"]
        self.assertIsInstance(reason, str)
        self.assertNotEqual(reason.strip(), "", "the failed album gave no reason")
        self.assertEqual([album["new_path"] for album in albums], [album["path"] for album in albums])
        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", "fullmoon"))
        self.assertEqual(self.copies_in_jobs(), [], "the jobs folder still holds a copy of an album")
        self.assertIsNone(self.job_of(self.path("ecliptica")), "the album's page still carries the failed job")

        # The draft is still on the page. Applied again, it lands the album that failed and leaves the two that
        # landed: they are no longer what the page loaded, and they carry the genre once.
        self.assertEqual(self.applied(draft), self.done("ecliptica"))
        self.assertEqual(self.genres("ecliptica"), [["power metal", "heavy metal", FOLK]] * 3)
        self.assertEqual(self.genres("stones"), [["heavy metal", "hard rock", FOLK]] * 2)
        self.assertEqual(self.genres("fullmoon"), [["heavy metal", FOLK]] * 2)

    def test_a_swap_that_does_not_verify_in_one_album_puts_it_back_and_the_album_after_it_lands(self) -> None:
        # The failure comes with the album's old folder set aside in the job's work folder, which the next album uses.
        draft = self.batch(self.THREE, edit(add={"Genre": [FOLK]}))
        before = self.on_disk()
        swap = save_tests.Swap(self, self.path("ecliptica"), 4, spoil=self.tracks("ecliptica")[0])

        with swap.patched():
            albums = self.applied(draft)

        self.assertNotEqual(swap.broke, [], save_tests.NEVER[4])
        self.assertEqual([(album["path"], album["state"]) for album in albums],
                         [(self.path("stones"), "done"), (self.path("ecliptica"), "failed"),
                          (self.path("fullmoon"), "done")])
        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", "fullmoon"))
        self.assertEqual(self.genres("fullmoon"), [["heavy metal", FOLK]] * 2)

    def test_a_batch_in_which_every_album_is_skipped_is_refused_as_nothing_to_save(self) -> None:
        cases = {
            "nothing would change in any": self.batch(SONATA, edit(remove={"Genre": ["pop"]})),
            # `fullmoon` would be left bare and `silence` does not carry the genre.
            "a rule and nothing to change": self.batch(("fullmoon", "silence"),
                                                       edit(remove={"Genre": ["heavy metal"]})),
        }
        for name, draft in cases.items():
            with self.subTest(name):
                self.assertEqual(self.refused(draft), NOTHING_TO_SAVE)

    def test_a_second_batch_naming_an_album_the_first_still_holds_is_refused_whole_and_queues_nothing(self) -> None:
        first = self.batch(SONATA, edit(add={"Genre": ["power metal"]}))
        # `fullmoon` waits behind `stones` in the first batch. `ecliptica` is in no job, and would be free alone.
        second = self.batch(("ecliptica", "fullmoon"), edit(add={"Genre": [FOLK]}))
        alone = self.draft(self.path("fullmoon"), edit(set={"Composer": ["Tony Kakko"]}))
        with self.held_mid_write(first) as job:
            for name, draft in (("a batch", second), ("the album's own save", alone)):
                with self.subTest(name):
                    got = self.send(draft)
                    self.assertEqual(got.status, 409, got.body[:300])
                    self.assertEqual(json.loads(got.body), {"error": save_tests.BEING_SAVED})
            # A save queued for `ecliptica` would be its job now.
            self.assertIsNone(self.job_of(self.path("ecliptica")))
        self.assertEqual(self.settle_all(job), self.done("stones", "fullmoon"))
        self.assertIsNone(self.job_of(self.path("ecliptica")))
        self.assertIsNone(self.job_of(self.path("fullmoon")))
        self.assertEqual(self.genres("ecliptica"), [["power metal", "heavy metal"]] * 3)
        self.assertEqual(self.genres("fullmoon"), [["heavy metal", "power metal"]] * 2)
        composers = [held(self.shelf / self.path("fullmoon") / track)["tags"].get("TCOM")
                     for track in self.tracks("fullmoon")]
        self.assertEqual(composers, [None, None])


class TakesBatchFromTheFlag(BatchCase):
    """A draft is a batch where it says `batch: true`, however many albums it names.

    The artist page sends `true` for a selection inside one album too. Such
    a draft is planned as any batch is: the album is planned or left out with
    a `skip`, the tags only the album's page edits are refused, and Save
    answers `nothing to save` where the one album does not change.
    """

    def both_routes(self, draft: dict[str, Any]) -> list[tuple[str, save_tests.neighbour.Answer]]:
        """The preview's and the save's answer to `draft`. A save that was taken is over before this returns."""
        found = []
        for route in (editor_tests.PREVIEW, save_tests.SAVE):
            got = self.post(route, draft)
            if got.status == 202:
                self.settle_all(json.loads(got.body)["job"])
            found.append((route, got))
        return found

    def test_one_album_that_would_not_change_is_skipped_with_nothing_to_change_and_save_has_nothing_to_save(
            self) -> None:
        first = self.tracks("ecliptica")[0]
        cases = {
            "every track of the album": self.batch(("ecliptica",), edit(remove={"Genre": ["pop"]})),
            "a selection inside it": self.batch(("ecliptica",), over(edit(remove={"Genre": ["pop"]}),
                                                                     ecliptica=(first,))),
        }
        for name, draft in cases.items():
            with self.subTest(name):
                self.assertEqual(self.outcome(self.previewed(draft)), {self.path("ecliptica"): (NOTHING, {})})
                self.assertEqual(self.refused(draft), NOTHING_TO_SAVE)

    def test_one_album_is_left_out_with_the_reason_a_batch_gives_and_save_has_nothing_to_save(self) -> None:
        # Sent from the album's own page each of these is refused whole, with another sentence. In a
        # batch the album is skipped, and with no other album to write there is nothing to save.
        bare = self.batch(("fullmoon",), edit(remove={"Genre": ["heavy metal"]}))
        gone = self.batch(("ecliptica",), edit(add={"Genre": [FOLK]}))
        (self.shelf / self.path("ecliptica") / self.tracks("ecliptica")[1]).unlink()
        self.lay_open_match("stones")
        matched = self.batch(("stones",), edit(add={"Genre": [FOLK]}))
        # The rule's sentence goes on to name a track, as `SkipsAnAlbumTheChangeWouldBreak` reads it.
        for name, draft, reason in (("fullmoon", bare, "no genre: "), ("ecliptica", gone, CHANGED),
                                    ("stones", matched, IN_REVIEW)):
            with self.subTest(album=name):
                skip, changes = self.outcome(self.previewed(draft))[self.path(name)]
                self.assertEqual(changes, {})
                self.assertEqual((skip or "")[:len(reason)] if reason.endswith(": ") else skip, reason)
                self.assertEqual(self.refused(draft), NOTHING_TO_SAVE)

    def test_a_title_over_one_album_is_refused_as_the_albums_pages_and_nothing_is_planned(self) -> None:
        middle = self.tracks("ecliptica")[1]
        draft = self.batch(("ecliptica",), over(edit(set={"Title": ["Replica"]}), ecliptica=(middle,)))
        albums = self.previewed(draft)
        self.assertEqual(albums[self.path("ecliptica")]["refused"], [{"key": "Title", "reason": ON_ITS_PAGE}])
        self.assertEqual(self.outcome(albums), {self.path("ecliptica"): (NOTHING, {})})
        self.assertEqual(albums[self.path("ecliptica")]["problems"], [])
        self.assert_nothing_moves(albums)
        self.assertEqual(self.refused(draft), NOTHING_TO_SAVE)

    def test_an_add_over_one_album_lists_the_tracks_it_changes_and_save_lands_it_as_a_job(self) -> None:
        first = self.tracks("stones")[0]
        draft = self.batch(("stones",), over(edit(add={"Genre": ["power metal"]}), stones=(first,)))
        self.assertEqual(self.outcome(self.previewed(draft)),
                         {self.path("stones"): (None, self.adding("stones", "power metal", to=(first,)))})
        before = self.on_disk()

        self.assertEqual(self.applied(draft), self.done("stones"))

        self.assertEqual(self.differing(before, self.on_disk()), self.files_of("stones", only={"stones": (first,)}))
        self.assertEqual(self.genres("stones"),
                         [["heavy metal", "hard rock", "power metal"], ["heavy metal", "hard rock"]])

    def test_a_draft_that_says_it_is_no_batch_and_names_two_albums_is_400_and_writes_nothing(self) -> None:
        draft = self.batch(("stones", "fullmoon"), edit(add={"Genre": [FOLK]}))
        # As a batch the server plans it, so the 400 below is for the flag and nothing else.
        self.assertEqual(sorted(self.previewed(draft)), sorted(self.path(name) for name in ("stones", "fullmoon")))
        draft["batch"] = False
        before = self.on_disk()
        for route, got in self.both_routes(draft):
            with self.subTest(route=route):
                self.assertEqual(got.status, 400, got.body[:300])
                self.assertEqual(list(json.loads(got.body)), ["error"])
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])

    def test_a_draft_that_does_not_say_whether_it_is_a_batch_is_400_naming_the_flag_and_writes_nothing(self) -> None:
        whole = self.batch(("stones",), edit(add={"Genre": [FOLK]}))
        self.assertEqual(sorted(self.previewed(whole)), [self.path("stones")])
        without = {key: value for key, value in whole.items() if key != "batch"}
        # A word is not a yes or a no: `"false"` read as true would make a batch of the album page's draft.
        cases = {"no flag": without, "null": {**without, "batch": None}, "a word": {**without, "batch": "false"}}
        before = self.on_disk()
        for name, draft in cases.items():
            for route, got in self.both_routes(draft):
                with self.subTest(name, route=route):
                    self.assertEqual(got.status, 400, got.body[:300])
                    body = json.loads(got.body)
                    self.assertEqual(list(body), ["error"])
                    self.assertIn("batch", body["error"].lower())
        self.assert_as_it_was(before)
        self.assertEqual(self.copies_in_jobs(), [])

    def test_a_key_with_no_readable_name_over_an_mp3_album_and_a_flac_album_is_refused_in_both(self) -> None:
        # One edit whose tracks are of two formats, each format in an album of its own. Planned
        # album by album, `TXXX:MOOD` would reach the FLAC album as `txxx:mood`.
        pair = ("ecliptica", "silence")
        albums = self.previewed(self.batch(pair, edit(set={"TXXX:MOOD": ["calm"]}, add={"Genre": [FOLK]})))
        self.assertEqual({path: album["refused"] for path, album in albums.items()},
                         {self.path(name): [{"key": "TXXX:MOOD", "reason": ONE_FORMAT}] for name in pair})
        self.assertEqual(self.outcome(albums), {self.path(name): (None, self.adding(name, FOLK)) for name in pair})


if __name__ == "__main__":
    unittest.main()
