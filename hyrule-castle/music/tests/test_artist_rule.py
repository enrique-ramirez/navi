"""Whether the files' artist agrees with the release's credit, and what that makes the album.

On the search and fingerprint paths an album that fits is `auto` only when
its artist agrees with the chosen release's credit, and otherwise `review`
with the reason `artist does not agree`. The files' artist is the album
artist tag, else the artist tag, whichever value most files carry. It agrees
with the credit as joined, a credited name, an artist's own name or sort
name, or an alias of type Artist name or Legal name, for any credited artist.
Search hints never count. A tagged release ID is not judged on artist.

Everything goes through `identify` against the fake MusicBrainz server of
`tests.test_identify`, which here also answers artist lookups: aliases are
only on the artist, never on the release. Every release fits its files
exactly, so the artist is the only thing that can hold an album back.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from musiclib import acoustid, caa, mb
from musiclib.cache import Cache
from musiclib.units import Unit
from tests import test_artist_folder as folder, test_check
from tests.test_identify import (
    TAGGED, IdentifyTestCase, Server, mbid, search_json, titled_json, unit, vorbis,
)

ARTIST_PATH = "/ws/2/artist/"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"

SONGS = [("Prelude", 180.0), ("Opening - Bombing Mission", 237.0), ("Mako Reactor", 201.0)]
SINGLE = [("Single", 204.0)]


def artist_json(artist_id: str, name: str, sort_name: str,
                aliases: tuple[tuple[str, str, str | None, bool], ...] = ()) -> dict:
    """An artist as `mb.artist` returns it, with `(name, type, locale, primary)` aliases."""
    return {
        "id": artist_id, "name": name, "sort-name": sort_name, "genres": [],
        "aliases": [{"name": alias, "sort-name": alias, "type": kind, "locale": locale, "primary": primary}
                    for alias, kind, locale, primary in aliases],
    }


def credit(*parts: tuple[str, str, dict]) -> list[dict]:
    """A release's artist credit from `(credited name, join phrase, artist)` parts.

    The release carries the artist's name and sort name, as a release lookup
    does, and never its aliases, which only the artist lookup has.
    """
    return [{"name": credited, "joinphrase": join,
             "artist": {"id": artist["id"], "name": artist["name"], "sort-name": artist["sort-name"]}}
            for credited, join, artist in parts]


def credited_release(release_id: str, credited: list[dict], songs=SONGS, date: str = "1997-01-31") -> dict:
    release = titled_json(release_id, songs, date=date)
    release["artist-credit"] = credited
    return release


UEMATSU = artist_json(mbid("e1"), "植松伸夫", "Uematsu, Nobuo", (
    ("Nobuo Uematsu", "Artist name", "en", True),
    # What somebody searching for his music might type. It is not his name.
    ("Final Fantasy", "Search hint", None, False),
))
LADY_GAGA = artist_json(mbid("e2"), "Lady Gaga", "Lady Gaga", (("Stefani Germanotta", "Legal name", None, False),))
ROTH = artist_json(mbid("e3"), "Arnie Roth", "Roth, Arnie")
ANA_MENA = artist_json(mbid("e4"), "Ana Mena", "Mena, Ana")
DELLAFUENTE = artist_json(mbid("e5"), "Dellafuente", "Dellafuente")
SAME_K = artist_json(mbid("e6"), "Same K", "Same K")
FAR_FROM_ALASKA = artist_json(mbid("e7"), "Far from Alaska", "Far from Alaska")
EMINEM = artist_json(mbid("e8"), "Eminem", "Eminem")
PEARL_JAM = artist_json(mbid("e9"), "Pearl Jam", "Pearl Jam")
NIN = artist_json(mbid("ea"), "Nine Inch Nails", "Nine Inch Nails")
REZNOR = artist_json(mbid("eb"), "Trent Reznor", "Reznor, Trent")
MELLENCAMP = artist_json(mbid("ec"), "John Mellencamp", "Mellencamp, John")
VARIOUS = artist_json(VARIOUS_ARTISTS, "Various Artists", "Various Artists")
ARTISTS = (UEMATSU, LADY_GAGA, ROTH, ANA_MENA, DELLAFUENTE, SAME_K, FAR_FROM_ALASKA, EMINEM, PEARL_JAM,
           NIN, REZNOR, MELLENCAMP, VARIOUS)


class ArtistServer(Server):
    """The fake MusicBrainz server, answering artist lookups from `ARTISTS` as well.

    An artist it does not know is a 404, as MusicBrainz answers.
    """

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        path = urlsplit(url).path
        if self.unavailable or not path.startswith(ARTIST_PATH):
            return super().__call__(url, headers)
        self.urls.append(url)
        found = {a["id"]: a for a in ARTISTS}.get(path[len(ARTIST_PATH):])
        if found is None:
            return 404, b'{"error": "Not Found"}'
        return 200, json.dumps(found).encode()

    def artist_lookups(self) -> list[str]:
        return [urlsplit(u).path[len(ARTIST_PATH):] for u in self.urls if urlsplit(u).path.startswith(ARTIST_PATH)]


Tag = str | list[str | None] | None


class ArtistTestCase(IdentifyTestCase):
    def files(self, *, albumartist: Tag = None, artist: Tag = None, songs=SONGS,
              release_id: str | None = None) -> Unit:
        """FLAC files titled and timed as `songs`, each fitting its track exactly.

        `albumartist` and `artist` are one value for every file, a list of one
        per file, or `None` to leave the tag off.
        """
        def per_file(value: Tag) -> list[str | None]:
            return value if isinstance(value, list) else [value] * len(songs)

        tracks = []
        for number, ((title, seconds), album_artist, track_artist) in enumerate(
                zip(songs, per_file(albumartist), per_file(artist)), start=1):
            tags = {"tracknumber": str(number), "title": title, "album": "Final Fantasy VII"}
            if album_artist is not None:
                tags["albumartist"] = album_artist
            if track_artist is not None:
                tags["artist"] = track_artist
            if release_id is not None:
                tags["musicbrainz_albumid"] = release_id
            tracks.append(vorbis(self.album, f"{number:02d}. {title}.flac", seconds, **tags))
        return unit(self.album, tracks)

    def searched(self, files: Unit, *releases: dict) -> tuple:
        server = ArtistServer(search=search_json(*releases), releases=releases)
        return self.identify(files, server), server

    def assertDoesNotAgree(self, result, release_id: str) -> None:
        self.assertEqual((result.status, result.reason), ("review", "artist does not agree"))
        self.assertEqual([c.release_id for c in result.candidates], [release_id])

    def assertAuto(self, result, release_id: str) -> None:
        self.assertEqual((result.status, result.reason), ("auto", None))
        self.assertEqual(result.candidates[0].release_id, release_id)


# --- criterion 47: the files' artist against the credit -----------------------


class DoesNotAgree(ArtistTestCase):
    def test_the_three_singles_whose_artist_is_nowhere_in_the_credit_are_review(self) -> None:
        # Each fits its release exactly, by title and length. A single has
        # one track, so the pairs alone matched it to any song of the same
        # name and length by anybody.
        for files_artist, credited in (
            ("Agrupación Cariño", credit(("Ana Mena", " & ", ANA_MENA), ("Dellafuente", "", DELLAFUENTE))),
            ("Disclosure", credit(("Same K", "", SAME_K),)),
            ("Down With Webster", credit(("Far from Alaska", "", FAR_FROM_ALASKA),)),
        ):
            with self.subTest(files_artist):
                self.forget()
                release = credited_release(mbid("a1"), credited, SINGLE)
                result, _ = self.searched(self.files(albumartist=files_artist, artist=files_artist, songs=SINGLE),
                                          release)
                self.assertDoesNotAgree(result, mbid("a1"))

    def test_another_composer_does_not_agree_with_a_credit_in_japanese(self) -> None:
        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        result, _ = self.searched(self.files(albumartist="Toshiyuki Mori", artist="Toshiyuki Mori"), release)
        self.assertDoesNotAgree(result, mbid("a1"))

    def test_a_search_hint_alias_does_not_agree(self) -> None:
        # MusicBrainz lists `Final Fantasy` on 植松伸夫 for people searching
        # for the games' music. Files tagged with a game's name are not
        # tagged with his.
        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        result, _ = self.searched(self.files(albumartist="Final Fantasy", artist="Final Fantasy"), release)
        self.assertDoesNotAgree(result, mbid("a1"))

    def test_a_one_letter_artist_does_not_agree_by_being_inside_a_longer_name(self) -> None:
        # Criterion 54 holds for artists as well as titles: `m` is inside
        # `eminem`, and nothing else about them is alike.
        release = credited_release(mbid("a1"), credit(("Eminem", "", EMINEM),))
        result, _ = self.searched(self.files(albumartist="M", artist="M"), release)
        self.assertDoesNotAgree(result, mbid("a1"))


class Agrees(ArtistTestCase):
    def test_an_english_artist_name_alias_agrees_with_a_credit_in_japanese(self) -> None:
        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        result, _ = self.searched(self.files(albumartist="Nobuo Uematsu", artist="Nobuo Uematsu"), release)
        self.assertAuto(result, mbid("a1"))

    def test_the_artists_own_name_agrees_where_the_release_credits_them_under_another(self) -> None:
        # Red and Blue credits Lady Gaga as `Stefani`. Her sort name is her
        # name as well, so John Cougar's early records are here too: his sort
        # name `Mellencamp, John` is too far from his name to agree with it.
        for files_artist, credited in (("Lady Gaga", credit(("Stefani", "", LADY_GAGA),)),
                                       ("John Mellencamp", credit(("John Cougar", "", MELLENCAMP),))):
            with self.subTest(files_artist):
                self.forget()
                release = credited_release(mbid("a1"), credited)
                result, _ = self.searched(self.files(albumartist=files_artist, artist=files_artist), release)
                self.assertAuto(result, mbid("a1"))

    def test_the_credited_name_agrees_where_the_artist_is_known_by_another(self) -> None:
        # Files tagged as the release credits them: John Cougar was John
        # Mellencamp's name on his early records, and is neither his name,
        # his sort name nor an alias.
        release = credited_release(mbid("a1"), credit(("John Cougar", "", MELLENCAMP),))
        result, _ = self.searched(self.files(albumartist="John Cougar", artist="John Cougar"), release)
        self.assertAuto(result, mbid("a1"))

    def test_a_legal_name_alias_agrees(self) -> None:
        release = credited_release(mbid("a1"), credit(("Lady Gaga", "", LADY_GAGA),))
        result, _ = self.searched(self.files(albumartist="Stefani Germanotta", artist="Stefani Germanotta"), release)
        self.assertAuto(result, mbid("a1"))

    def test_the_sort_name_agrees(self) -> None:
        # Family name first, as Japanese names are written. It is too far
        # from `Nobuo Uematsu` to agree with the alias, so only the sort
        # name `Uematsu, Nobuo` can make it agree.
        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        result, _ = self.searched(self.files(albumartist="Uematsu Nobuo", artist="Uematsu Nobuo"), release)
        self.assertAuto(result, mbid("a1"))

    def test_any_artist_in_a_shared_credit_agrees_by_name_or_by_alias(self) -> None:
        # The second artist, never the first, so reading only the first
        # artist of a credit, or looking up only the first, is caught.
        for files_artist, credited in (
            ("Dellafuente", credit(("Ana Mena", " & ", ANA_MENA), ("Dellafuente", "", DELLAFUENTE))),
            ("Nobuo Uematsu", credit(("Arnie Roth", " & ", ROTH), ("植松伸夫", "", UEMATSU))),
        ):
            with self.subTest(files_artist):
                self.forget()
                release = credited_release(mbid("a1"), credited)
                result, _ = self.searched(self.files(albumartist=files_artist, artist=files_artist), release)
                self.assertAuto(result, mbid("a1"))

    def test_aliases_come_from_one_artist_lookup_and_never_from_the_release_lookup(self) -> None:
        # Criterion 53. Two editions credit the same artist, so the artist is
        # needed twice and asked for once. The release lookup is the one
        # every warm cache already holds, so it must not start asking for
        # aliases.
        first = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        second = credited_release(mbid("b2"), credit(("植松伸夫", "", UEMATSU),))
        result, server = self.searched(self.files(albumartist="Nobuo Uematsu", artist="Nobuo Uematsu"),
                                       first, second)
        self.assertEqual(result.status, "auto")
        self.assertEqual(server.artist_lookups(), [UEMATSU["id"]])
        release_incs = [parse_qs(urlsplit(u).query).get("inc", [""])[0] for u in server.urls
                        if urlsplit(u).path.startswith("/ws/2/release/") and "query=" not in u]
        self.assertEqual(len(release_incs), 2)
        self.assertFalse(any("aliases" in inc for inc in release_incs), release_incs)


class WhichArtistTheFilesHave(ArtistTestCase):
    def test_the_album_artist_tag_is_the_files_artist_before_the_track_artist(self) -> None:
        release = credited_release(mbid("a1"), credit(("Pearl Jam", "", PEARL_JAM),))
        for albumartist, artist, status in (("Pearl Jam", "Eddie Vedder", "auto"),
                                            ("Eddie Vedder", "Pearl Jam", "review")):
            with self.subTest(albumartist=albumartist, artist=artist):
                self.forget()
                result, _ = self.searched(self.files(albumartist=albumartist, artist=artist), release)
                self.assertEqual(result.status, status)

    def test_without_an_album_artist_tag_the_track_artist_is_the_files_artist(self) -> None:
        release = credited_release(mbid("a1"), credit(("Pearl Jam", "", PEARL_JAM),))
        result, _ = self.searched(self.files(artist="Pearl Jam"), release)
        self.assertAuto(result, mbid("a1"))

    def test_the_artist_most_files_carry_is_the_files_artist_wherever_the_odd_one_is(self) -> None:
        # The odd file first, since the search reads the first file's artist,
        # and then the odd one out as the majority, so that any one file
        # agreeing is not enough.
        release = credited_release(mbid("a1"), credit(("Pearl Jam", "", PEARL_JAM),))
        for artists, status in ((["Temple of the Dog", "Pearl Jam", "Pearl Jam"], "auto"),
                                (["Pearl Jam", "Temple of the Dog", "Temple of the Dog"], "review")):
            with self.subTest(artists=artists):
                self.forget()
                result, _ = self.searched(self.files(albumartist=artists, artist=artists), release)
                self.assertEqual(result.status, status)


# --- criterion 48: Various Artists, and files with no artist at all ------------


class VariousArtists(ArtistTestCase):
    def various(self) -> dict:
        return credited_release(mbid("a1"), credit(("Various Artists", "", VARIOUS),))

    def test_files_whose_album_artist_is_various_artists_agree(self) -> None:
        files = self.files(albumartist="Various Artists", artist=["Nine Inch Nails", "Marilyn Manson", "Coil"])
        result, _ = self.searched(files, self.various())
        self.assertAuto(result, mbid("a1"))

    def test_files_with_no_album_artist_and_track_artists_that_differ_agree(self) -> None:
        # Two files of three by one artist: the value most files carry is
        # Nine Inch Nails, which is not Various Artists by name.
        files = self.files(artist=["Nine Inch Nails", "Marilyn Manson", "Nine Inch Nails"])
        result, _ = self.searched(files, self.various())
        self.assertAuto(result, mbid("a1"))

    def test_files_by_one_artist_do_not_agree_with_various_artists(self) -> None:
        result, _ = self.searched(self.files(artist="Nine Inch Nails"), self.various())
        self.assertDoesNotAgree(result, mbid("a1"))


class NoArtistTags(ArtistTestCase):
    def test_files_with_no_artist_or_album_artist_tag_are_review_with_no_reason(self) -> None:
        # Nothing on the files to agree or disagree with, so `artist does not
        # agree` would tell the owner something untrue. Various Artists is
        # here too: files with no album artist agree with it when their track
        # artists differ, and files with no track artist do not differ.
        for name, credited in (("one artist", credit(("Nine Inch Nails", "", NIN),)),
                               ("Various Artists", credit(("Various Artists", "", VARIOUS),))):
            with self.subTest(name):
                self.forget()
                result, _ = self.searched(self.files(), credited_release(mbid("a1"), credited))
                self.assertEqual((result.status, result.reason), ("review", None))
                self.assertEqual([c.release_id for c in result.candidates], [mbid("a1")])


# --- criterion 49: the tagged path ----------------------------------------------


class TaggedReleaseId(ArtistTestCase):
    def test_a_tagged_release_id_is_certain_whatever_the_files_artist(self) -> None:
        release = credited_release(TAGGED, credit(("植松伸夫", "", UEMATSU),))
        files = self.files(albumartist="Toshiyuki Mori", artist="Toshiyuki Mori", release_id=TAGGED)
        server = ArtistServer(releases=(release,))
        result = self.identify(files, server)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertEqual(server.searches(), [])


# --- criterion 47 on the fingerprint path ---------------------------------------


class Fingerprint(ArtistTestCase):
    def test_a_fitting_fingerprint_match_whose_artist_does_not_agree_is_review(self) -> None:
        # The search lists nothing, so the fingerprints decide. Every file
        # fingerprints to a1, which fits them all.
        from tests.test_identify_acoustid import KEY, FakeClock, Lookups, best

        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        files = self.files(albumartist="Toshiyuki Mori", artist="Toshiyuki Mori")
        for track in files.tracks:
            Path(track.path).parent.mkdir(parents=True, exist_ok=True)
            Path(track.path).touch()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            fpcalc = bin_dir / "fpcalc"
            # Names each fingerprint after its file, `FP-01. Prelude.flac`,
            # which is how `Lookups` tells the tracks apart.
            fpcalc.write_text("#!/bin/sh\nfor last; do :; done\n"
                              "printf '{\"duration\": 200.4, \"fingerprint\": \"FP-%s\"}\\n' \"$(basename \"$last\")\"\n")
            fpcalc.chmod(0o755)
            (bin_dir / "acoustid-cache").mkdir()
            clock = FakeClock()
            client = acoustid.AcoustID(Cache(bin_dir / "acoustid-cache"), KEY,
                                       transport=Lookups({n: [best(mbid("a1"))] for n in (1, 2, 3)}),
                                       clock=clock, sleep=clock.sleep, fpcalc=str(fpcalc))
            server = ArtistServer(search=search_json(), releases=(release,))
            result = identify_with(self, files, server, client, str(fpcalc))
        self.assertDoesNotAgree(result, mbid("a1"))


def identify_with(case: IdentifyTestCase, files: Unit, server: Server, client, fpcalc: str):
    from musiclib.identify import identify

    return identify(files, case.client(server), acoustid=client, env={"ACOUSTID_API_KEY": "key"},
                    which=lambda name: fpcalc if name == "fpcalc" else None)


# --- criterion 50: ranking ------------------------------------------------------


class Ranking(ArtistTestCase):
    def test_an_agreeing_artist_ranks_after_fewer_failing_pairs_and_before_a_smaller_length_difference(self) -> None:
        # None fits, so the order is the rank alone. a1 fails one pair and is
        # 2 s off, by an artist who does not agree. b2 fails one pair and is
        # 6 s off, by the files' artist. c3 fails two, by the files' artist,
        # and is not off at all. Without the artist, a1 would lead; with the
        # artist before the failing pairs, c3 would pass a1.
        files = self.files(albumartist="Nine Inch Nails", artist="Nine Inch Nails")
        nin, reznor = credit(("Nine Inch Nails", "", NIN)), credit(("Trent Reznor", "", REZNOR))
        disagreeing = credited_release(mbid("a1"), reznor, [("Prelude", 182.0), ("Heresy", 237.0), ("Mako Reactor", 201.0)])
        agreeing = credited_release(mbid("b2"), nin, [("Prelude", 186.0), ("Heresy", 237.0), ("Mako Reactor", 201.0)])
        worse = credited_release(mbid("c3"), nin, [("Prelude", 180.0), ("Heresy", 237.0), ("Closer", 201.0)])
        result, _ = self.searched(files, worse, disagreeing, agreeing)
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1"), mbid("c3")])

    def test_of_two_fitting_editions_on_one_date_the_one_whose_artist_agrees_is_chosen_and_auto(self) -> None:
        # Same status and date, so the rank chooses. a1 is closer in length
        # and first by MBID, and credited to somebody else.
        files = self.files(albumartist="Nine Inch Nails", artist="Nine Inch Nails")
        closer = credited_release(mbid("a1"), credit(("Trent Reznor", "", REZNOR)),
                                  [("Prelude", 180.0), ("Opening - Bombing Mission", 237.0), ("Mako Reactor", 201.0)])
        agreeing = credited_release(mbid("b2"), credit(("Nine Inch Nails", "", NIN)),
                                    [("Prelude", 184.0), ("Opening - Bombing Mission", 237.0), ("Mako Reactor", 201.0)])
        result, _ = self.searched(files, closer, agreeing)
        self.assertAuto(result, mbid("b2"))
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])


# --- MusicBrainz down while the artist is looked up ------------------------------


UNAVAILABLE = (503, b"<html>503 Service Temporarily Unavailable</html>")


class DownForArtists(ArtistServer):
    """Answers everything as `ArtistServer` does, except every artist lookup, which is a 503."""

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if urlsplit(url).path.startswith(ARTIST_PATH):
            self.urls.append(url)
            return UNAVAILABLE
        return super().__call__(url, headers)


class ArtistLookupUnavailable(ArtistTestCase):
    def test_musicbrainz_down_for_the_artist_lookup_leaves_the_album_unidentified(self) -> None:
        # Only an alias makes `Nobuo Uematsu` agree with `植松伸夫`. Judged
        # without the aliases, a lookup that never answered would send an
        # album that agrees to review as if it did not.
        release = credited_release(mbid("a1"), credit(("植松伸夫", "", UEMATSU),))
        server = DownForArtists(search=search_json(release), releases=(release,))
        result = self.identify(self.files(albumartist="Nobuo Uematsu", artist="Nobuo Uematsu"), server)
        self.assertEqual((result.status, result.reason), ("unidentified", "musicbrainz unavailable"))
        self.assertNotEqual(server.artist_lookups(), [])


class _DownForArtistsWhilePlanning(folder._WithArtists):
    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if urlsplit(url).path.startswith(ARTIST_PATH):
            return UNAVAILABLE
        return super().__call__(url, headers)


class PlanningWhileArtistLookupUnavailable(folder._ArtistPlanning):
    def test_musicbrainz_down_for_the_artist_lookup_while_planning_is_raised_not_planned_around(self) -> None:
        # A name in Japanese needs the English alias for the folder and the
        # artist tags. Planned without it, the album would be filed under
        # `#/植松伸夫` for good.
        root = self.library()
        album = test_check._rip(root, folder.TITLES)
        release = test_check._release(folder.TITLES, credit=folder.credit(("植松伸夫", "", folder.UEMATSU)))
        services = _DownForArtistsWhilePlanning(release, [folder.UEMATSU])
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        with self.assertRaises(mb.MusicBrainzUnavailable):
            test_check._plan_album(self.unit(root, album), release, client, art, status="auto")
