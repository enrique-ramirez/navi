"""Game-music detection, from spec 001 criteria 39 and 40 as 003 criteria 57 to 61 amend them.

Each `video game music` rule is shown firing with every other input
neutral, so a rule that only works alongside another one fails here.
`custom_genre` takes neither the album's artist nor the owner's input, so
nothing here can show the old composer memory decides nothing; that is in
`tests.test_soundtracks`, with what holds a Soundtrack-type release group
for the owner's choice and the choice itself. The type adds no genre here.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from musiclib import genres, mb
from musiclib.cache import Cache

VGM = "video game music"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
# Made up. Only Various Artists' MBID means anything to the engine.
UEMATSU = "3ff72a59-f6f0-4e7f-a0e6-2c5d4b6f0e3a"
MITSUDA = "0f4b1c2d-8e3a-4b5c-9d6e-7a8b9c0d1e2f"
RELEASE_GROUP_MBID = "c3b1f0a2-6d4e-4f8a-9b7c-2e1d0a3b4c5f"


def credit(*artists: tuple[str, str]) -> dict:
    """A release whose `artist-credit` names each (MBID, name) in turn."""
    return {
        "artist-credit": [
            {
                "name": name,
                "joinphrase": " & " if i < len(artists) - 1 else "",
                "artist": {"id": mbid, "name": name, "sort-name": name},
            }
            for i, (mbid, name) in enumerate(artists)
        ]
    }


def group(tags: tuple[str, ...] = (), secondary: tuple[str, ...] = (), genre_names: tuple[str, ...] = ()) -> dict:
    return {
        "id": RELEASE_GROUP_MBID,
        "primary-type": "Album",
        "secondary-types": list(secondary),
        "tags": [{"name": t, "count": 1} for t in tags],
        "genres": [{"name": g, "count": 1} for g in genre_names],
    }


def custom(
    release_group: dict | None = None,
    file_genres: tuple[str, ...] = (),
    incoming: str | None = None,
) -> str | None:
    """`custom_genre` with every input neutral unless the test says otherwise."""
    return genres.custom_genre(
        release_group if release_group is not None else group(),
        list(file_genres),
        incoming=incoming,
    )


class Composer(unittest.TestCase):
    def test_is_the_album_artist_when_the_credit_is_one_artist(self) -> None:
        self.assertEqual(genres.composer(credit((UEMATSU, "Nobuo Uematsu"))), UEMATSU)

    def test_various_artists_is_no_composer(self) -> None:
        self.assertIsNone(genres.composer(credit((VARIOUS_ARTISTS, "Various Artists"))))

    def test_a_two_artist_credit_is_no_composer(self) -> None:
        self.assertIsNone(genres.composer(credit((UEMATSU, "Nobuo Uematsu"), (MITSUDA, "Yasunori Mitsuda"))))


class EachVideoGameMusicRuleAlone(unittest.TestCase):
    def test_a_game_tag_on_the_release_group(self) -> None:
        for tag in ("video game", "vgm", "game", "game music", "video game music"):
            with self.subTest(tag=tag):
                self.assertEqual(custom(group(tags=("orchestral", tag))), VGM)

    def test_a_game_tag_in_any_case(self) -> None:
        self.assertEqual(custom(group(tags=("VGM",))), VGM)
        self.assertEqual(custom(group(tags=("Video Game",))), VGM)

    def test_the_files_already_carrying_it(self) -> None:
        self.assertEqual(custom(file_genres=("rock", VGM)), VGM)
        self.assertEqual(custom(file_genres=("Video Game Music",)), VGM)

    def test_an_incoming_game_genre(self) -> None:
        for incoming in ("Game", "Video Game", "VGM", "Soundtrack", "vgm", "SOUNDTRACK"):
            with self.subTest(incoming=incoming):
                self.assertEqual(custom(incoming=incoming), VGM)


class NotGameMusic(unittest.TestCase):
    def test_nothing_holds_gives_no_custom_genre(self) -> None:
        self.assertIsNone(custom(group(tags=("rock", "orchestral")), file_genres=("rock",)))

    def test_a_tag_that_only_contains_a_game_name_does_not_fire(self) -> None:
        # Folksonomy tags are free text. `video game soundtrack` and
        # `board game` contain `game`, and matching by substring would
        # turn every film score tagged that way into game music.
        for tag in ("video game soundtrack", "board game", "games", "vgm rips"):
            with self.subTest(tag=tag):
                self.assertIsNone(custom(group(tags=(tag,))))

    def test_a_game_tag_counts_only_with_a_vote_count_above_zero(self) -> None:
        # A folksonomy tag voted down to 0 or below is still returned by
        # MusicBrainz. Reading the name alone turns it into game music.
        for count, expected in ((1, VGM), (0, None), (-1, None)):
            with self.subTest(count=count):
                release_group = group()
                release_group["tags"] = [{"name": "vgm", "count": count}]
                self.assertEqual(custom(release_group), expected)

    def test_a_game_name_among_the_genres_rather_than_the_tags_does_not_fire(self) -> None:
        self.assertIsNone(custom(group(genre_names=("video game music", "game"))))

    def test_an_incoming_genre_outside_the_four_does_not_fire(self) -> None:
        self.assertIsNone(custom(incoming="Rock"))
        self.assertIsNone(custom(incoming="Video Game Soundtrack"))

    def test_a_file_soundtrack_is_not_read_as_an_incoming_one(self) -> None:
        # Incoming `Soundtrack` means game music, but only for an album the
        # caller marked incoming. Here nothing is marked, so the file's own
        # `Soundtrack` is only a soundtrack.
        self.assertEqual(custom(file_genres=("Soundtrack",)), "soundtrack")


class Soundtrack(unittest.TestCase):
    def test_comes_from_the_files(self) -> None:
        self.assertEqual(custom(file_genres=("soundtrack",)), "soundtrack")

    def test_never_comes_from_the_release_group_type_alone(self) -> None:
        # 003 criterion 57. The type says a film or a game, and which one is
        # the owner's to say.
        self.assertIsNone(custom(group(secondary=("Soundtrack",))))
        self.assertIsNone(custom(group(secondary=("Live", "Soundtrack"))))


class VideoGameMusicWins(unittest.TestCase):
    def test_a_game_tag_beats_a_file_soundtrack(self) -> None:
        self.assertEqual(custom(group(tags=("vgm",), secondary=("Soundtrack",)), file_genres=("soundtrack",)), VGM)

    def test_the_files_soundtrack_is_dropped_from_the_genres(self) -> None:
        # MusicBrainz has no genres here, so the file's are kept, all but
        # the soundtrack that video game music replaces.
        self.assertEqual(genres.compose(VGM, [], ["Soundtrack", "rock"]), [VGM, "rock"])


class WarmCache(unittest.TestCase):
    def test_a_warm_cache_holds_the_tags_that_decide_it(self) -> None:
        # The tags come in the release group's one lookup and are cached
        # with it, so a second run offline decides the same way.
        with tempfile.TemporaryDirectory() as tmp:
            requests: list[str] = []

            def online(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
                # Like MusicBrainz, this sends the tags only when the lookup
                # asks for them, so a client that stops asking loses them here.
                requests.append(url)
                included = parse_qs(urlsplit(url).query).get("inc", [""])[0].replace(" ", "+").split("+")
                body = group(tags=("vgm",))
                if "tags" not in included:
                    del body["tags"]
                return 200, json.dumps(body).encode()

            def offline(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
                raise AssertionError(f"a warm cache made a request: {url}")

            def client(transport) -> mb.MusicBrainz:
                return mb.MusicBrainz(Cache(Path(tmp)), transport=transport, clock=lambda: 0.0, sleep=lambda s: None)

            cold = client(online).release_group(RELEASE_GROUP_MBID)
            self.assertEqual(custom(cold), VGM)
            self.assertEqual(len(requests), 1)

            warm = client(offline).release_group(RELEASE_GROUP_MBID)
            self.assertEqual(custom(warm), VGM)


if __name__ == "__main__":
    unittest.main()
