"""Soundtrack-type albums: held for the owner's choice, and the choice remembered per release.

Spec 003 criteria 57 to 61. A release group's Soundtrack secondary type says
nothing about whether the music is a game's or a film's, so it adds no genre
and holds the album with the reason `soundtrack choice`. A game tag on the
release group, `video game music` on the files or an incoming game genre
settles it as `video game music`. `soundtrack` on the files settles nothing,
because job `t1` wrote it from the type alone.

The owner picks one of three per album: `video game music` or `soundtrack`,
put first in the genres, or `neither`, which adds nothing. `not game music`
from before the amendment reads as `soundtrack`. An applied choice is kept in
`memory.json` under `soundtracks`, keyed by release MBID, and settles that
release in every later job. The old composer memory is neither read nor
written, and what it holds stays in the file.

Three levels. The hold is read off `identify.identify`, with
`tests.test_identify`'s fake MusicBrainz. The genres are read off
`plan.plan_album`, with `tests.test_check`'s. The choice runs through two
real batch jobs the way `tests.test_memory` runs an edit: rips on disk,
`batch identify`, a `decisions.json` written by hand, identify again to fold
it in, `batch apply`, then a second job over an untouched copy of the same
rips with the same memory. A release the owner accepts or pastes over the
engine's pick is planned by `identify.chosen`, and is read off a job the
same way, and off `chosen` itself.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from musiclib import files
from musiclib.identify import chosen
from tests import builders
from tests.test_batch_apply import Library
from tests.test_batch_identify import Services, album, mbid, no_throttle, release, run_identify
from tests.test_check import CURE, _Planning, _release, _release_group, _rip
from tests.test_identify import (
    RELEASE_ID_KEY, TAGGED, IdentifyTestCase, Server, release_group_json, release_json, search_json, unit,
)
from tests.test_identify import mbid as identify_mbid
from tests.test_memory import entries, key_of
from tests.test_review_page import albums, parse

VGM = "video game music"
SOUNDTRACK = "soundtrack"
NEITHER = "neither"
LEGACY = "not game music"
CHOICES = {VGM, SOUNDTRACK, NEITHER}
SOUNDTRACK_CHOICE = "soundtrack choice"
HELD_FOR_A_CHOICE = ("review", SOUNDTRACK_CHOICE)

GENRE_KEY = {"mp3": "TCON", "flac": "genre", "ogg": "genre", "m4a": "\xa9gen"}
# `release_json` credits Nine Inch Nails, under this MBID.
NIN_ID = identify_mbid("8")


class TheHold(IdentifyTestCase):
    """What holds a Soundtrack-type album at `review` and what lets it through.

    Every album here would be `certain` or `auto` without the hold. The
    files carry the credited artist, so the artist check passes and only
    the hold decides.
    """

    FILES = [200, 180, 240]

    def soundtrack(self, tags: tuple[tuple[str, int], ...] = ()) -> dict:
        return release_group_json(secondary_types=("Soundtrack",), tags=tags)

    def auto(self, group: dict, **file_tags) -> tuple:
        """A search that finds one release matching the files exactly, in `group`."""
        found = release_json(mbid(1, 1), [self.FILES])
        server = Server(search=search_json(found), releases=(found,), release_groups=(group,))
        return unit(self.album, self.tagged(self.FILES, release_id=None, **file_tags)), server

    def test_a_soundtrack_type_album_found_by_search_is_held_for_a_soundtrack_choice(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        result = self.identify(the_unit, server)
        self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)

    def test_a_tagged_soundtrack_type_album_is_held_even_when_soundtrack_is_its_second_type(self) -> None:
        # MusicBrainz gives a live score as `Live, Soundtrack`. Reading only
        # the first secondary type lets it through as certain.
        group = release_group_json(secondary_types=("Live", "Soundtrack"))
        server = Server(releases=(release_json(TAGGED, [self.FILES]),), release_groups=(group,))
        result = self.identify(unit(self.album, self.tagged(self.FILES)), server)
        self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)

    def test_soundtrack_on_the_files_does_not_settle_it(self) -> None:
        # Job t1 wrote `soundtrack` onto every Soundtrack-type album from the
        # type alone, so the files saying it is the engine's old guess. On
        # every file, and on one file that is not the first, both stay held.
        with self.subTest("every file"):
            the_unit, server = self.auto(self.soundtrack(), genre=["Orchestral", "Soundtrack"])
            result = self.identify(the_unit, server)
            self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)
        with self.subTest("the last file"):
            self.forget()
            the_unit, server = self.auto(self.soundtrack())
            the_unit.tracks[2] = dataclasses.replace(
                the_unit.tracks[2], tags={**the_unit.tracks[2].tags, "genre": ["soundtrack"]})
            result = self.identify(the_unit, server)
            self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)

    def test_a_game_tag_on_the_release_group_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack(tags=(("orchestral", 4), ("VGM", 2))))
        self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_video_game_music_on_any_one_file_settles_it(self) -> None:
        # A laundered rip can carry the genre on one file and not the rest.
        # The second and the last are both tried, so neither "the first two"
        # nor "the last one" passes.
        for carrier in (1, 2):
            with self.subTest(track=carrier + 1):
                self.forget()
                the_unit, server = self.auto(self.soundtrack())
                the_unit.tracks[carrier] = dataclasses.replace(
                    the_unit.tracks[carrier], tags={**the_unit.tracks[carrier].tags, "genre": ["Video Game Music"]})
                self.assertNotIn("genre", the_unit.tracks[0].tags)
                self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_video_game_music_is_read_under_each_formats_own_genre_tag(self) -> None:
        # From real files, so the genre key is whatever `files.read` gives
        # back: TCON, genre and ©gen. Tagged with the release, so settled
        # means certain.
        for ext in ("mp3", "flac", "ogg", "m4a"):
            with self.subTest(ext=ext):
                folder = self.root / ext
                folder.mkdir()
                tracks = []
                for number in (1, 2):
                    path = builders.copy_fixture(folder, ext, f"0{number}. Track {number}")
                    builders.write_tags(path, {RELEASE_ID_KEY[ext]: TAGGED, GENRE_KEY[ext]: "Video Game Music"})
                    tracks.append(dataclasses.replace(files.read(path), length=200.0))
                server = Server(releases=(release_json(TAGGED, [[200, 200]]),), release_groups=(self.soundtrack(),))
                self.assertEqual(self.identify(unit(folder, tracks), server).status, "certain")

    def test_an_incoming_game_genre_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        self.assertEqual(self.identify(the_unit, server, incoming="Video Game").status, "auto")

    def test_a_composer_remembered_either_way_does_not_settle_it(self) -> None:
        # The composer memory is not read any more. Each value it could hold
        # used to let this album through.
        for remembered in (VGM, LEGACY):
            with self.subTest(remembered=remembered):
                self.forget()
                the_unit, server = self.auto(self.soundtrack())
                result = self.identify(the_unit, server, owner_input={"composers": {NIN_ID: remembered}})
                self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)

    def test_the_hold_reads_the_edition_chosen_rather_than_the_top_candidate(self) -> None:
        # The top candidate is a plain album and the 1994 edition behind it
        # is a Soundtrack. The oldest edition is the one chosen, so the hold
        # reads its release group, and it stays first.
        top = release_json(mbid(1, 1), [self.FILES], date="2004-11-23")
        oldest = release_json(mbid(1, 2), [[200.5, 180, 240]], date="1994-03-08")
        oldest["release-group"] = {**oldest["release-group"], "id": mbid(2, 2)}
        group = release_group_json(mbid(2, 2), secondary_types=("Soundtrack",))
        server = Server(search=search_json(top, oldest), releases=(top, oldest), release_groups=(group,))
        result = self.identify(unit(self.album, self.tagged(self.FILES, release_id=None)), server)
        self.assertEqual((result.status, result.reason), HELD_FOR_A_CHOICE)
        self.assertEqual([c.release_id for c in result.candidates], [mbid(1, 2), mbid(1, 1)])

    def test_soundtrack_on_the_files_of_an_album_that_is_not_soundtrack_type_holds_nothing(self) -> None:
        the_unit, server = self.auto(release_group_json(), genre=["Soundtrack"])
        self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_a_soundtrack_type_release_the_owner_names_is_held_for_a_choice_until_something_settles_it(self) -> None:
        # `chosen` plans a release the owner accepted or pasted over the
        # engine's pick. It is always `review`, and without the hold that
        # `review` carries no reason, so nothing asks the owner to choose.
        # The files that settle it and a group that is not Soundtrack-type
        # both stay unheld, so a `chosen` that holds everything fails too.
        cases = (
            ("unsettled", self.soundtrack(), {}, SOUNDTRACK_CHOICE),
            ("video game music on the files", self.soundtrack(), {"genre": ["Video Game Music"]}, None),
            ("not Soundtrack-type", release_group_json(), {}, None),
        )
        for name, group, file_tags, held_for in cases:
            with self.subTest(name):
                self.forget()
                server = Server(releases=(release_json(TAGGED, [self.FILES]),), release_groups=(group,))
                the_unit = unit(self.album, self.tagged(self.FILES, release_id=None, **file_tags))
                result = chosen(the_unit, self.client(server), TAGGED)
                self.assertEqual(result.status, "review")
                if held_for is None:
                    self.assertNotEqual(result.reason, SOUNDTRACK_CHOICE)
                else:
                    self.assertEqual(result.reason, held_for)


TITLES = ["Plainsong", "Pictures of You"]


def soundtrack_group(tags: tuple[str, ...] = (), genre_counts: dict[str, int] | None = None) -> dict:
    """`_release_group`'s group, Soundtrack-type. `genre_counts` of `{}` is a group with no genres."""
    group = _release_group(genre_counts)
    group["secondary-types"] = ["Soundtrack"]
    group["tags"] = [{"name": name, "count": 1} for name in tags]
    return group


class TheGenres(_Planning):
    """The genres `plan_album` gives every track, for each way an album is settled or not.

    The stock release group's only genre is `gothic rock`, so anything
    ahead of it is the custom genre.
    """

    def genres(self, group: dict, file_genres: tuple[str, ...] = (), **kwargs) -> list[list[str]]:
        root = self.library()
        folder = _rip(root, TITLES, genre=file_genres)
        plan = self.plan(self.unit(root, folder), _release(TITLES), group, status="auto", **kwargs)
        return [file_plan.target.get("genre") for file_plan in plan.files]

    def test_the_soundtrack_type_alone_adds_no_soundtrack(self) -> None:
        self.assertEqual(self.genres(soundtrack_group()), [["gothic rock"]] * 2)

    def test_a_game_tag_puts_video_game_music_first(self) -> None:
        self.assertEqual(self.genres(soundtrack_group(tags=("vgm",))), [[VGM, "gothic rock"]] * 2)

    def test_video_game_music_on_the_files_puts_it_first(self) -> None:
        self.assertEqual(self.genres(soundtrack_group(), ("Video Game Music",)), [[VGM, "gothic rock"]] * 2)

    def test_an_incoming_game_genre_puts_video_game_music_first(self) -> None:
        self.assertEqual(self.genres(soundtrack_group(), incoming="Video Game"), [[VGM, "gothic rock"]] * 2)

    def test_a_composer_remembered_as_video_game_music_adds_nothing(self) -> None:
        # The composer memory is not read. The Cure is the album's single
        # credited artist, so the old engine read this entry and wrote it.
        owner = {"composers": {CURE[0]["artist"]["id"]: VGM}}
        self.assertEqual(self.genres(soundtrack_group(), owner_input=owner), [["gothic rock"]] * 2)

    def test_soundtrack_on_the_files_of_an_album_that_is_not_soundtrack_type_stays_first(self) -> None:
        self.assertEqual(self.genres(_release_group(), ("Soundtrack",)), [[SOUNDTRACK, "gothic rock"]] * 2)

    def test_soundtrack_on_the_files_of_a_soundtrack_type_album_waiting_on_a_choice_is_not_planned(self) -> None:
        # Job t1 wrote `soundtrack` from the type alone. Read back as the
        # custom genre, it plans the guess the hold is there to question.
        # The second case has no genres on the release group, so the files'
        # other genres stand in for them and `rock` must survive. The two
        # spell it differently, as a rip tagged by hand might.
        cases = (
            ("the group has genres", soundtrack_group(), ("Soundtrack",), [["gothic rock"]] * 2),
            ("the files stand in", soundtrack_group(genre_counts={}), ("soundtrack", "rock"), [["rock"]] * 2),
        )
        for name, group, carried, expected in cases:
            with self.subTest(name):
                self.assertEqual(self.genres(group, carried), expected)

    def test_soundtrack_on_the_files_of_a_soundtrack_type_album_comes_back_only_when_it_is_the_choice(self) -> None:
        # The release group has no genres, so the files stand in for them.
        # `neither` is Help!'s case in criterion 60: it must come out
        # without `soundtrack`, whatever the files say.
        owner = {choice: {"soundtracks": {_release(TITLES)["id"]: choice}} for choice in CHOICES}
        expected = {VGM: [VGM, "rock"], SOUNDTRACK: [SOUNDTRACK, "rock"], NEITHER: ["rock"]}
        for choice in sorted(CHOICES):
            with self.subTest(choice=choice):
                got = self.genres(soundtrack_group(genre_counts={}), ("soundtrack", "rock"), owner_input=owner[choice])
                self.assertEqual(got, [expected[choice]] * 2)


TRACKS = ["One", "Two"]

# Soundtrack-type albums. The first four are decided in job j1, one way each.
GAME = "S/Sakura/Overworld [rip]"
FILM = "F/Fennel/Harbour [rip]"
# Its files carry `soundtrack`, as job t1 left every Soundtrack-type album.
HELP = "B/Beatles/Help! [rip]"
OLD_EXPORT = "L/Larch/Old Score [rip]"
# By GAME's artist, and never decided. Held in both jobs, so a choice
# remembered by artist rather than by release shows here.
SEQUEL = "S/Sakura/Underworld [rip]"
# Its artist has an entry in the composer memory before either job. Never decided.
COMPOSED = "K/Kondo/Ocarina [rip]"

# Not Soundtrack-type, and its files carry `soundtrack`.
SCORED = "N/Nutmeg/Tapes [rip]"

DECIDED = {GAME: VGM, FILM: SOUNDTRACK, HELP: NEITHER, OLD_EXPORT: LEGACY}
SOUNDTRACK_TYPE = (GAME, FILM, HELP, OLD_EXPORT, SEQUEL, COMPOSED)

# The release group's own genre is `rock` (`tests.test_batch_identify`), so
# criterion 58's genres for each choice are these, whole.
GENRES_FOR = {VGM: [VGM, "rock"], SOUNDTRACK: [SOUNDTRACK, "rock"], NEITHER: ["rock"], LEGACY: [SOUNDTRACK, "rock"]}
STORED_AS = {VGM: VGM, SOUNDTRACK: SOUNDTRACK, NEITHER: NEITHER, LEGACY: SOUNDTRACK}


def _release_for(number: int, key: str, soundtrack_type: bool) -> tuple[dict, dict]:
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, TRACKS)
    if soundtrack_type:
        group["secondary-types"] = ["Soundtrack"]
        found["release-group"]["secondary-types"] = ["Soundtrack"]
    return found, group


def soundtrack(number: int, key: str) -> tuple[dict, dict]:
    """A Soundtrack-type release for the rip at `key`, with nothing on it or the files saying game music."""
    return _release_for(number, key, True)


def _catalogue() -> dict[str, tuple[dict, dict]]:
    out = {key: soundtrack(number, key) for number, key in enumerate(SOUNDTRACK_TYPE, start=1)}
    out[SCORED] = _release_for(len(out) + 1, SCORED, False)
    # SEQUEL credits GAME's artist, the same MBID.
    same = out[GAME][0]["artist-credit"]
    out[SEQUEL][0]["artist-credit"] = same
    for track in out[SEQUEL][0]["media"][0]["tracks"]:
        track["artist-credit"] = same
    return out


CATALOGUE = _catalogue()


def release_of(key: str) -> str:
    return CATALOGUE[key][0]["id"]


def artist_of(key: str) -> str:
    return CATALOGUE[key][0]["artist-credit"][0]["artist"]["id"]


#: What `memory.json` holds before job j1: one composer entry of each old
#: value. COMPOSED's is `video game music`, which used to settle it.
COMPOSERS = {artist_of(COMPOSED): VGM, artist_of(FILM): LEGACY}


def genres_of(entry: dict) -> list[list[str]]:
    return [entry["fields"][position].get("genre") for position in ("1-1", "1-2")]


def offered_choices(section) -> list[tuple[str, str]]:
    """The soundtrack radios in one album's section of the page, as sorted `(name, value)` pairs.

    `not game music` is looked for too, so a page still offering the old
    pair shows.
    """
    return sorted((n.attrs.get("name", ""), n.attrs["value"]) for n in section.tags("input")
                  if n.attrs.get("type", "").lower() == "radio" and n.attrs.get("value") in CHOICES | {LEGACY})


def assertOffersTheThreeChoices(case: unittest.TestCase, section) -> None:
    offered = offered_choices(section)
    case.assertEqual(sorted(value for _name, value in offered), sorted(CHOICES))
    # One group per album, so the browser lets the owner pick one.
    case.assertEqual(len({name for name, _value in offered}), 1, offered)


class TheChoiceAcrossJobs(unittest.TestCase):
    """Job `j1` over `<tmp>/library`, decided and applied; then job `j2` over `<tmp>/fresh/library`.

    The rips are made once at `<tmp>/rips` and copied to both libraries, so
    the second job sees what the first job saw before it wrote anything.
    Both jobs use `<tmp>/.musiclib/memory.json`. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)

        rips = base / "rips"
        for key in CATALOGUE:
            folder = album(rips, key, TRACKS, release_id=release_of(key))
            if key in (HELP, SCORED):
                for path in folder.glob("*.flac"):
                    builders.write_tags(path, {key_of("genre"): ["soundtrack"]})

        lib = cls.lib = Library(base)
        lib.root.rmdir()
        shutil.copytree(rips, lib.root)
        lib.catalogue = list(CATALOGUE.values())
        cls.memory = lib.memory
        cls.memory.parent.mkdir(parents=True, exist_ok=True)
        cls.memory.write_text(json.dumps({"edits": {}, "composers": COMPOSERS, "reopened": []}), encoding="utf-8")

        cls.first_run = run_identify(lib.root, lib.job, lib.memory, Services(lib.catalogue))
        cls.planned = lib.entries()
        cls.page = parse((lib.job / "review.html").read_text(encoding="utf-8"))

        decisions = {key: {"action": "accept", "release_id": release_of(key), "edits": {}, "game": game}
                     for key, game in DECIDED.items()}
        decisions.update({SEQUEL: {"action": "skip"}, COMPOSED: {"action": "skip"}})
        lib.decide(decisions)
        cls.decided = lib.entries()
        cls.applied = lib.apply()
        cls.remembered = json.loads(cls.memory.read_text(encoding="utf-8"))

        fresh = base / "fresh" / "library"
        shutil.copytree(rips, fresh)
        j2 = base / ".musiclib" / "jobs" / "j2"
        j2.mkdir(parents=True)
        cls.second_run = run_identify(fresh, j2, cls.memory, Services(lib.catalogue))
        cls.again = entries(j2)

    def assertHeldForAChoice(self, entry: dict) -> None:
        self.assertEqual((entry["state"], entry["holds"]),
                         ("held", [{"kind": "status", "detail": "review: soundtrack choice"}]),
                         entry["source"])

    def written(self, key: str) -> list[list[str]]:
        """The genre on each of `key`'s tracks as j1's apply left them."""
        destination = self.decided[key]["destination"]
        folder = self.lib.root / destination
        self.assertTrue(folder.is_dir(), f"{key}: nothing at {destination}; apply said: {self.applied}")
        return [files.read(p).tags.get(key_of("genre")) for p in sorted(folder.glob("*.flac"))]

    def test_every_soundtrack_type_album_is_held_for_a_choice_before_anything_is_decided(self):
        for key in SOUNDTRACK_TYPE:
            with self.subTest(album=key):
                self.assertHeldForAChoice(self.planned[key])

    def test_an_album_that_is_not_soundtrack_type_keeps_the_soundtrack_on_its_files(self):
        entry = self.planned[SCORED]
        self.assertEqual((entry["state"], entry["holds"]), ("auto", []))
        self.assertEqual(genres_of(entry), [[SOUNDTRACK, "rock"]] * 2)

    def test_the_page_offers_the_three_choices_once_on_each_held_soundtrack_album_and_nowhere_else(self):
        sections = albums(self.page)
        for key in SOUNDTRACK_TYPE:
            with self.subTest(album=key):
                assertOffersTheThreeChoices(self, sections[key])
        self.assertEqual(offered_choices(sections[SCORED]), [])

    def test_each_choice_is_written_with_its_genres_in_the_same_apply(self):
        # Help!'s files carried `soundtrack`. `neither` leaves MusicBrainz's
        # genres and nothing else.
        for key, game in DECIDED.items():
            with self.subTest(album=key, game=game):
                self.assertEqual(self.written(key), [GENRES_FOR[game]] * 2)

    def test_each_applied_choice_is_stored_under_its_release_mbid_and_nothing_else_is(self):
        # An old export's `not game music` is stored as what it meant, so
        # nothing after this amendment ever reads the old value.
        expected = {release_of(key): STORED_AS[game] for key, game in DECIDED.items()}
        self.assertEqual(self.remembered.get("soundtracks"), expected)

    def test_the_composer_memory_is_left_as_it_was_and_nothing_is_added_to_it(self):
        # GAME, FILM and OLD_EXPORT each have a single credited artist, the
        # albums the old engine remembered a choice under.
        self.assertEqual(self.remembered.get("composers"), COMPOSERS)

    def test_a_later_job_finds_each_chosen_release_settled_with_the_genres_it_was_given(self):
        # Help! is the spec's example: unheld and without `soundtrack` in the next job.
        for key, game in DECIDED.items():
            with self.subTest(album=key, game=game):
                entry = self.again[key]
                self.assertEqual(entry["holds"], [], f"identify said: {self.second_run}")
                self.assertEqual(genres_of(entry), [GENRES_FOR[game]] * 2)

    def test_a_choice_settles_only_its_own_release_and_not_another_by_the_same_artist(self):
        self.assertEqual(artist_of(SEQUEL), artist_of(GAME), "the fixture's two albums have different artists")
        self.assertHeldForAChoice(self.again[SEQUEL])

    def test_a_composer_entry_in_memory_json_settles_nothing_in_either_job(self):
        for job, got in (("j1", self.planned), ("j2", self.again)):
            with self.subTest(job=job):
                self.assertHeldForAChoice(got[COMPOSED])


# Each rip is tagged with a plain release, which the engine plans `certain`.
# The decision names a Soundtrack-type release for the same files instead:
# an accept of a release the engine did not put on top, or a paste.
ACCEPTED = "P/Poppy/Lanterns [rip]"
PASTED = "Q/Quince/Harbourside [rip]"
ACCEPTED_WITH_A_CHOICE = "R/Rowan/Meadows [rip]"
# The memory holds a choice for the Soundtrack-type release before the job.
PASTED_REMEMBERED = "S/Sorrel/Ferries [rip]"
ACCEPTED_REMEMBERED = "T/Tansy/Orchards [rip]"

NAMED = (ACCEPTED, PASTED, ACCEPTED_WITH_A_CHOICE, PASTED_REMEMBERED, ACCEPTED_REMEMBERED)
PLAIN = {key: _release_for(number, key, False) for number, key in enumerate(NAMED, start=21)}
SCORE = {key: _release_for(number, key, True) for number, key in enumerate(NAMED, start=31)}


def score_of(key: str) -> str:
    return SCORE[key][0]["id"]


REMEMBERED = {score_of(PASTED_REMEMBERED): SOUNDTRACK, score_of(ACCEPTED_REMEMBERED): NEITHER}


class AReleaseTheOwnerNamed(unittest.TestCase):
    """Job `j1`: identified, then decided once, then the first album accepted again with no `game`.

    Before this amendment the page asked for a choice on any Soundtrack-type
    release, so a release the owner named was asked about too. Now only the
    hold asks, and `identify.chosen` plans these without going through the
    engine's own pick. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        no_throttle(cls)

        lib = Library(Path(tmp.name))
        for key in NAMED:
            album(lib.root, key, TRACKS, release_id=PLAIN[key][0]["id"])
        lib.catalogue = [*PLAIN.values(), *SCORE.values()]
        lib.memory.parent.mkdir(parents=True, exist_ok=True)
        lib.memory.write_text(json.dumps({"edits": {}, "soundtracks": REMEMBERED, "reopened": []}),
                              encoding="utf-8")

        lib.identify()
        before = lib.entries()
        for key in NAMED:
            # The fixture, not the promise: the engine's own pick is the
            # plain release and nothing holds it.
            if (before[key]["release_id"], before[key]["holds"]) != (PLAIN[key][0]["id"], []):
                raise AssertionError(f"{key}: the engine did not plan the plain release unheld: {before[key]}")

        def accept(key: str, game: str | None = None) -> dict:
            return {"action": "accept", "release_id": score_of(key), "edits": {}, "game": game}

        lib.decide({
            ACCEPTED: accept(ACCEPTED),
            PASTED: {"action": "repoint", "release": score_of(PASTED)},
            ACCEPTED_WITH_A_CHOICE: accept(ACCEPTED_WITH_A_CHOICE, VGM),
            PASTED_REMEMBERED: {"action": "repoint", "release": score_of(PASTED_REMEMBERED)},
            ACCEPTED_REMEMBERED: accept(ACCEPTED_REMEMBERED),
        })
        cls.decided = lib.entries()
        cls.page = albums(parse((lib.job / "review.html").read_text(encoding="utf-8")))

        (lib.job / "decisions.json").write_text(
            json.dumps({"job": "j1", "albums": {ACCEPTED: accept(ACCEPTED)}}), encoding="utf-8")
        cls.accepted_again = run_identify(lib.root, lib.job, lib.memory, Services(lib.catalogue))

    def status_holds(self, key: str) -> list[str]:
        return [hold["detail"] for hold in self.decided[key]["holds"] if hold["kind"] == "status"]

    def test_a_soundtrack_type_release_accepted_over_the_engines_pick_is_held_for_a_choice(self):
        entry = self.decided[ACCEPTED]
        self.assertEqual(entry["release_id"], score_of(ACCEPTED))
        self.assertEqual(self.status_holds(ACCEPTED), ["review: soundtrack choice"])
        self.assertEqual((entry["state"], entry["game_choice"]), ("held", True))
        assertOffersTheThreeChoices(self, self.page[ACCEPTED])

    def test_a_soundtrack_type_release_pasted_over_the_engines_pick_is_held_for_a_choice(self):
        entry = self.decided[PASTED]
        self.assertEqual(entry["release_id"], score_of(PASTED))
        self.assertEqual(self.status_holds(PASTED), ["review: soundtrack choice"])
        self.assertEqual(entry["game_choice"], True)
        assertOffersTheThreeChoices(self, self.page[PASTED])

    def test_accepting_that_release_again_with_no_game_is_refused(self):
        # What the hold is for: without it, this accept goes through and
        # the album is applied with no choice ever made.
        code, _out, err = self.accepted_again
        self.assertEqual(code, 1, err)
        self.assertIn(ACCEPTED, err)
        self.assertIn("Soundtrack-type", err)

    def test_a_named_release_with_a_choice_given_or_remembered_is_not_held_for_one_and_has_its_genres(self):
        # The release group's own genre is `rock`. The two remembered ones
        # are read from the memory alone: neither decision says `game`.
        for key, game in ((ACCEPTED_WITH_A_CHOICE, VGM), (PASTED_REMEMBERED, SOUNDTRACK),
                          (ACCEPTED_REMEMBERED, NEITHER)):
            with self.subTest(album=key, game=game):
                entry = self.decided[key]
                self.assertEqual(entry["release_id"], score_of(key))
                self.assertNotIn("review: soundtrack choice", self.status_holds(key))
                self.assertEqual(genres_of(entry), [GENRES_FOR[game]] * 2)


# Found by search, and credited to somebody other than the files' artist, so
# held `review: artist does not agree` (criterion 47) before the soundtrack
# hold is ever looked at.
DISOWNED = "O/Oak/Borrowed Score [rip]"
DISOWNED_CHOSEN = "O/Olive/Lent Score [rip]"
DISOWNED_REMEMBERED = "O/Osier/Loaned Score [rip]"
# Tagged with a release four minutes off the files, so held `review` for the
# failing pairs, with no reason.
LOOSE = "L/Linden/Slack Score [rip]"
LOOSE_CHOSEN = "L/Lupin/Loose Score [rip]"
LOOSE_REMEMBERED = "L/Lilac/Baggy Score [rip]"

UNDECIDED = (DISOWNED, LOOSE)
CHOSEN = {DISOWNED_CHOSEN: VGM, LOOSE_CHOSEN: NEITHER}
REMEMBERED_BEFORE = {DISOWNED_REMEMBERED: VGM, LOOSE_REMEMBERED: SOUNDTRACK}
SEARCHED = (DISOWNED, DISOWNED_CHOSEN, DISOWNED_REMEMBERED)


def held_as(key: str) -> str:
    """The `status` hold `key` has whatever its soundtrack: its artist's, or its failing pairs'."""
    return "review: artist does not agree" if key in SEARCHED else "review"


def _held_elsewhere() -> dict[str, tuple[dict, dict]]:
    out = {}
    for number, key in enumerate((*SEARCHED, LOOSE, LOOSE_CHOSEN, LOOSE_REMEMBERED), start=61):
        title = key.split("/")[2].split(" [")[0]
        credited = "Somebody Else" if key in SEARCHED else key.split("/")[1]
        found, group = release(number, credited, title, TRACKS, exact=key in SEARCHED)
        group["secondary-types"] = ["Soundtrack"]
        found["release-group"]["secondary-types"] = ["Soundtrack"]
        out[key] = (found, group)
    return out


HELD_ELSEWHERE = _held_elsewhere()


def held_elsewhere_release(key: str) -> str:
    return HELD_ELSEWHERE[key][0]["id"]


class _SearchingServices(Services):
    """`Services`, with a search that finds each of `SEARCHED` by its title, and artist lookups with no aliases."""

    def __init__(self, catalogue: list[tuple[dict, dict]]) -> None:
        super().__init__(catalogue)
        self.artists = {part["artist"]["id"]: part["artist"] for found, _group in catalogue
                        for part in found["artist-credit"]}

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org" and path == "/ws/2/release":
            self.answered.append(url)
            query = unquote(parts.query).casefold()
            for key in SEARCHED:
                if key.split("/")[2].split(" [")[0].casefold() in query:
                    return 200, json.dumps(search_json(HELD_ELSEWHERE[key][0])).encode()
            return 200, b'{"releases": [], "count": 0}'
        if parts.netloc == "musicbrainz.org" and path.startswith("/ws/2/artist/"):
            self.answered.append(url)
            artist = self.artists.get(path.removeprefix("/ws/2/artist/"))
            if artist is None:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps({**artist, "aliases": [], "genres": []}).encode()
        return super().__call__(url, headers)


class ASoundtrackHeldForSomethingElse(unittest.TestCase):
    """Soundtrack-type albums already held `review` for their artist or their pairs, across two jobs.

    Criterion 58 asks for the three choices on every unsettled
    Soundtrack-type album, and criterion 57 holds it until one settles it.
    The engine stops at the first `review`, so an album held for its artist
    or a failing pair never reaches the soundtrack hold, and nothing asked
    about the soundtrack before an accept wrote it.

    Job `j1` is identified once, then given an accept with no `game` for
    each undecided album, which identify must refuse. Then it is decided
    and applied, and job `j2` runs over an untouched copy of the rips with
    the memory `j1` left. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)

        rips = base / "rips"
        for key in HELD_ELSEWHERE:
            album(rips, key, TRACKS, release_id=None if key in SEARCHED else held_elsewhere_release(key))

        lib = cls.lib = Library(base)
        lib.root.rmdir()
        shutil.copytree(rips, lib.root)
        catalogue = list(HELD_ELSEWHERE.values())
        lib.memory.parent.mkdir(parents=True, exist_ok=True)
        lib.memory.write_text(json.dumps({
            "edits": {}, "reopened": [],
            "soundtracks": {held_elsewhere_release(key): game for key, game in REMEMBERED_BEFORE.items()},
        }), encoding="utf-8")

        def identify(root: Path, job: Path) -> tuple[int, str, str]:
            return run_identify(root, job, lib.memory, _SearchingServices(catalogue))

        def decide(albums_: dict) -> tuple[int, str, str]:
            (lib.job / "decisions.json").write_text(json.dumps({"job": "j1", "albums": albums_}), encoding="utf-8")
            return identify(lib.root, lib.job)

        def accept(key: str, game: str | None = None) -> dict:
            return {"action": "accept", "release_id": held_elsewhere_release(key), "edits": {}, "game": game}

        cls.first_run = identify(lib.root, lib.job)
        cls.planned = lib.entries()
        cls.page = albums(parse((lib.job / "review.html").read_text(encoding="utf-8")))

        cls.refused = decide({key: accept(key) for key in UNDECIDED})

        decisions = {key: accept(key, game) for key, game in CHOSEN.items()}
        decisions.update({key: accept(key) for key in REMEMBERED_BEFORE})
        decisions.update({key: {"action": "skip"} for key in UNDECIDED})
        cls.decided_run = decide(decisions)
        cls.decided = lib.entries()
        cls.applied = lib.apply()

        fresh = base / "fresh" / "library"
        shutil.copytree(rips, fresh)
        j2 = base / ".musiclib" / "jobs" / "j2"
        j2.mkdir(parents=True)
        cls.second_run = identify(fresh, j2)
        cls.again = entries(j2)
        cls.page_again = albums(parse((j2 / "review.html").read_text(encoding="utf-8")))

    def written(self, key: str) -> list[list[str]]:
        """The genre on each of `key`'s tracks as j1's apply left them."""
        destination = self.decided[key]["destination"]
        folder = self.lib.root / destination
        self.assertTrue(folder.is_dir(), f"{key}: nothing at {destination}; apply said: {self.applied}")
        return [files.read(p).tags.get(key_of("genre")) for p in sorted(folder.glob("*.flac"))]

    def test_an_unsettled_album_held_for_its_artist_or_its_pairs_keeps_that_hold_and_is_offered_the_three_choices(self):
        # Both jobs: skipping it in j1 settles nothing. Only the choice is
        # added, so the hold it had stays with its own reason.
        for job, planned, page in (("j1", self.planned, self.page), ("j2", self.again, self.page_again)):
            for key in UNDECIDED:
                with self.subTest(job=job, album=key):
                    entry = planned[key]
                    self.assertEqual(entry["release_id"], held_elsewhere_release(key), entry)
                    self.assertIn({"kind": "status", "detail": held_as(key)}, entry["holds"])
                    assertOffersTheThreeChoices(self, page[key])

    def test_accepting_an_unsettled_album_held_for_its_artist_or_its_pairs_with_no_game_is_refused(self):
        # Let through, the album is written with no choice ever made and
        # with none of the genres the choice would have put first.
        code, _out, err = self.refused
        self.assertEqual(code, 1, err)
        self.assertIn("Soundtrack-type", err)
        for key in UNDECIDED:
            with self.subTest(album=key):
                self.assertIn(key, err)

    def test_a_choice_given_or_remembered_is_written_with_its_genres_and_offered_no_choice_in_a_later_job(self):
        # The release group's own genre is `rock`. The remembered ones were
        # accepted with no `game`, so the memory alone settles them, in j1
        # as much as in j2. Each is still held for its artist or its pairs
        # in j2, since nothing about those changed.
        code, _out, err = self.decided_run
        self.assertEqual(code, 0, err)
        for key, game in {**CHOSEN, **REMEMBERED_BEFORE}.items():
            with self.subTest(album=key, game=game):
                self.assertEqual(self.written(key), [GENRES_FOR[game]] * 2)
                self.assertEqual(genres_of(self.again[key]), [GENRES_FOR[game]] * 2)
                self.assertEqual(offered_choices(self.page_again[key]), [])
                self.assertIn({"kind": "status", "detail": held_as(key)}, self.again[key]["holds"])
        for key in REMEMBERED_BEFORE:
            with self.subTest(job="j1", album=key):
                self.assertEqual(offered_choices(self.page[key]), [])


if __name__ == "__main__":
    unittest.main()
