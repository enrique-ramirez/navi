"""The artist folder is the artist's own name, the artist tags the credited one, both romanized.

The folder is built from each credited artist's current MusicBrainz name,
joined by the credit's join phrases, and not from the name the release
credits them under. `ARTIST` and `ALBUMARTIST` keep the credited name. A
name not in the Latin script is replaced by the artist's primary alias with
locale `en`, artist by artist, in the folder and in both artist tags. The
sort fields stay as MusicBrainz gives them.

Everything goes through `plan_album` against `test_check`'s fake MusicBrainz
and Cover Art Archive, which here also answers artist lookups. Aliases are
only on the artist lookup, never on the release, as on the real service.
An owner's edit is laid over that plan by `batch.memory.lay_edits`, the way
`batch identify` lays one.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from musiclib import caa, mb
from musiclib.batch.memory import lay_edits
from musiclib.cache import Cache
from musiclib.units import pair, position_key
from tests import builders
from tests.test_check import _Planning, _plan_album, _release, _release_group, _rip, _Services

TITLES = ["Plainsong", "Pictures of You"]
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"


def artist(artist_id: str, name: str, sort_name: str,
           aliases: tuple[tuple[str, str | None, bool], ...] = ()) -> dict:
    """An artist as the artist lookup returns it, with `(name, locale, primary)` aliases.

    Each alias carries a sort name of its own that differs from the
    artist's, so a sort field taken from the alias shows.
    """
    return {
        "id": artist_id, "name": name, "sort-name": sort_name, "genres": [],
        "aliases": [{"name": alias, "sort-name": f"{alias} (alias)", "type": "Artist name",
                     "locale": locale, "primary": primary}
                    for alias, locale, primary in aliases],
    }


def credit(*parts: tuple[str, str, dict]) -> list[dict]:
    """An artist credit from `(credited name, join phrase, artist)` parts, as a release lookup gives it."""
    return [{"name": credited, "joinphrase": join,
             "artist": {"id": a["id"], "name": a["name"], "sort-name": a["sort-name"]}}
            for credited, join, a in parts]


GAGA = artist("1a0b0c0d-0000-4000-8000-0000000000c1", "Lady Gaga", "Lady Gaga")
BEYONCE = artist("1a0b0c0d-0000-4000-8000-0000000000c2", "Beyoncé", "Beyoncé")
UEMATSU = artist("1a0b0c0d-0000-4000-8000-0000000000c3", "植松伸夫", "Uematsu, Nobuo",
                 aliases=(("うえまつのぶお", "ja", False),
                          ("Nobuo Uematsu", "en", True)))
NOMURA = artist("1a0b0c0d-0000-4000-8000-0000000000c4", "野村玲子", "Nomura, Reiko",
                aliases=(("Reiko Nomura", "en", True),))
OBLOMOV = artist("1a0b0c0d-0000-4000-8000-0000000000c5", "Вася Обломов",
                 "Обломов, Вася",
                 aliases=(("Василий Васильевич "
                           "Гончаров", "ru", True),))
BILLIE_ID = "1a0b0c0d-0000-4000-8000-0000000000c6"
BILLIE_KATAKANA = "ビリー・アイリッシュ"

UEMATSU_JA = UEMATSU["name"]
NOMURA_JA = NOMURA["name"]
OBLOMOV_RU = OBLOMOV["name"]


class _WithArtists(_Services):
    """`test_check._Services`, answering the artist lookup as well, from `artists` by MBID.

    An artist not in `artists` is a 404, the same as any other unknown URL.
    """

    def __init__(self, release: dict, artists: list[dict]) -> None:
        super().__init__(release, _release_group(), front=True)
        self.artists = {a["id"]: a for a in artists}

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org" and path.startswith("/ws/2/artist/"):
            found = self.artists.get(path.rsplit("/", 1)[1])
            if found is None:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps(found).encode()
        return super().__call__(url, headers)


class _ArtistPlanning(_Planning):
    def plan_credit(self, release_credit: list[dict], artists: list[dict], *,
                    track_credits: dict[int, list[dict]] | None = None, edit: dict[str, list[str]] | None = None,
                    **changes):
        """The stock two-track rip planned against a release credited to `release_credit`.

        Every track carries the release's credit unless `track_credits` gives
        one of its own, by 0-based track index. `artists` is what the artist
        lookup knows. `edit` is an owner's edit of those fields on every
        track, laid over the plan.
        """
        root = self.library()
        album = _rip(root, TITLES)
        release = _release(TITLES, credit=release_credit, **changes)
        for index, track_credit in (track_credits or {}).items():
            release["media"][0]["tracks"][index]["artist-credit"] = track_credit
        services = _WithArtists(release, artists)
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=services)
        unit = self.unit(root, album)
        plan = _plan_album(unit, release, client, art, status="auto")
        if edit is None:
            return plan
        pairs = pair(unit, release)
        family_by_source = {Path(t.path).relative_to(root).as_posix(): t.family for t in unit.tracks}
        return lay_edits(plan, {position_key(p): dict(edit) for p in pairs}, release, release["release-group"],
                         pairs, family_by_source, unit)

    def assertPlanned(self, plan, destination: str, artist: str | list[str], albumartist: str,
                      artistsort: str, albumartistsort: str | None = None):
        """No problems, the album goes to `destination`, and every track carries these artist tags.

        `artist` is one value for every track, or a list of one per track.
        """
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(str(plan.destination), destination)
        artists = artist if isinstance(artist, list) else [artist] * len(plan.files)
        self.assertEqual(len(plan.files), len(TITLES))
        for file_plan, expected_artist in zip(plan.files, artists):
            target = file_plan.target
            self.assertEqual(target["artist"], [expected_artist], file_plan.source)
            self.assertEqual(target["albumartist"], [albumartist], file_plan.source)
            self.assertEqual(target["albumartistsort"], [albumartistsort or artistsort], file_plan.source)
        self.assertEqual(plan.files[0].target["artistsort"], [artistsort])


class TheArtistsOwnName(_ArtistPlanning):
    """Criterion 51: the folder is the artist's current name, the tags the name on the credit."""

    def test_red_and_blue_credited_to_stefani_goes_under_lady_gaga_and_its_tags_say_stefani(self):
        plan = self.plan_credit(
            credit(("Stefani", "", GAGA)), [GAGA], title="Red and Blue", date="2006",
            **{"release-group": {"id": builders.RELEASE_GROUP_ID, "title": "Red and Blue",
                                 "first-release-date": "2006", "primary-type": "EP",
                                 "secondary-types": []}})
        self.assertPlanned(plan, "L/Lady Gaga/(2006) [EP] Red and Blue",
                           artist="Stefani", albumartist="Stefani", artistsort="Lady Gaga")

    def test_two_artists_are_each_named_by_their_own_name_joined_by_the_credits_join_phrase(self):
        # Only the first artist is credited under another name, so a folder
        # built from the credited names shows as `Stefani feat. ...`.
        plan = self.plan_credit(
            credit(("Stefani", " feat. ", GAGA), ("Beyoncé", "", BEYONCE)), [GAGA, BEYONCE])
        self.assertPlanned(plan, "L/Lady Gaga feat. Beyoncé/(2010) Disintegration",
                           artist="Stefani feat. Beyoncé", albumartist="Stefani feat. Beyoncé",
                           artistsort="Lady Gaga feat. Beyoncé")

    def test_the_article_rule_reads_the_artists_own_name_and_sort_name(self):
        # Credited without the article: only the artist's own name,
        # `Die Toten Hosen`, is its sort name with the article moved.
        hosen = artist("1a0b0c0d-0000-4000-8000-0000000000c7", "Die Toten Hosen", "Toten Hosen, Die")
        plan = self.plan_credit(credit(("Toten Hosen", "", hosen)), [hosen])
        self.assertPlanned(plan, "T/Toten Hosen, Die/(2010) Disintegration",
                           artist="Toten Hosen", albumartist="Toten Hosen", artistsort="Toten Hosen, Die")

    def test_an_own_name_starting_with_a_dot_takes_an_underscore_and_the_hash_letter(self):
        # Criterion 21 on the artist's own name: credited without the dot,
        # the folder still takes the underscore, and the tag keeps the credit.
        special = artist("1a0b0c0d-0000-4000-8000-0000000000c8", ".38 Special", ".38 Special")
        plan = self.plan_credit(credit(("38 Special", "", special)), [special])
        self.assertPlanned(plan, "#/_38 Special/(2010) Disintegration",
                           artist="38 Special", albumartist="38 Special", artistsort=".38 Special")

    def test_a_compilation_stays_under_various_artists_and_its_tracks_keep_their_own_artist(self):
        # The tracks' artist is replaced by its English alias like any other
        # credit; only the album is Various Artists.
        various = artist(VARIOUS_ARTISTS, "Various Artists", "Various Artists")
        plan = self.plan_credit(
            credit(("Various Artists", "", various)), [various, UEMATSU],
            track_credits={0: credit((UEMATSU_JA, "", UEMATSU)), 1: credit((UEMATSU_JA, "", UEMATSU))})
        self.assertPlanned(plan, "V/Various Artists/(2010) Disintegration",
                           artist="Nobuo Uematsu", albumartist="Various Artists",
                           artistsort="Uematsu, Nobuo", albumartistsort="Various Artists")


class AnEnglishAliasForANameNotInLatin(_ArtistPlanning):
    """Criterion 52: a name not in the Latin script gives way to the artist's primary `en` alias."""

    def test_uematsu_goes_under_nobuo_uematsu_with_that_artist_and_album_artist_and_his_sort_name(self):
        plan = self.plan_credit(credit((UEMATSU_JA, "", UEMATSU)), [UEMATSU])
        self.assertPlanned(plan, "N/Nobuo Uematsu/(2010) Disintegration",
                           artist="Nobuo Uematsu", albumartist="Nobuo Uematsu", artistsort="Uematsu, Nobuo")

    def test_vasya_oblomov_with_no_english_alias_stays_as_written(self):
        # He has a primary alias, in `ru`: only `en` counts.
        plan = self.plan_credit(credit((OBLOMOV_RU, "", OBLOMOV)), [OBLOMOV])
        self.assertPlanned(plan, f"#/{OBLOMOV_RU}/(2010) Disintegration",
                           artist=OBLOMOV_RU, albumartist=OBLOMOV_RU, artistsort=OBLOMOV["sort-name"])

    def test_billie_eilish_credited_in_katakana_goes_under_her_own_name(self):
        # Her own name is Latin, so the folder is that by criterion 51
        # whatever her aliases. The katakana credit becomes her English
        # alias where she has one, and stays where she has none.
        cases = {
            "with an English alias": (artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie",
                                             aliases=(("Billie Eilish", "en", True),)), "Billie Eilish"),
            "without one": (artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie"), BILLIE_KATAKANA),
        }
        for case, (billie, tag) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(credit((BILLIE_KATAKANA, "", billie)), [billie])
                self.assertPlanned(plan, "B/Billie Eilish/(2010) Disintegration",
                                   artist=tag, albumartist=tag, artistsort="Eilish, Billie")

    def test_two_artists_are_replaced_one_by_one_and_the_join_phrase_is_kept(self):
        cases = {
            "both have an English alias": (
                [UEMATSU, NOMURA], "Nobuo Uematsu & Reiko Nomura"),
            # All or nothing would leave both in Japanese, or fail on the one.
            "only the first has one": (
                [UEMATSU, artist(NOMURA["id"], NOMURA_JA, "Nomura, Reiko")], f"Nobuo Uematsu & {NOMURA_JA}"),
        }
        for case, (artists, joined) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(credit((UEMATSU_JA, " & ", artists[0]), (NOMURA_JA, "", artists[1])),
                                        artists)
                self.assertPlanned(plan, f"N/{joined}/(2010) Disintegration",
                                   artist=joined, albumartist=joined, artistsort="Uematsu, Nobuo & Nomura, Reiko")

    def test_a_track_credited_apart_from_the_album_takes_its_own_artists_english_alias(self):
        plan = self.plan_credit(credit((UEMATSU_JA, "", UEMATSU)), [UEMATSU, NOMURA],
                                track_credits={1: credit((NOMURA_JA, "", NOMURA))})
        self.assertPlanned(plan, "N/Nobuo Uematsu/(2010) Disintegration",
                           artist=["Nobuo Uematsu", "Reiko Nomura"], albumartist="Nobuo Uematsu",
                           artistsort="Uematsu, Nobuo")
        self.assertEqual(plan.files[1].target["artistsort"], ["Nomura, Reiko"])

    def test_an_alias_that_is_not_primary_or_not_exactly_en_is_not_used(self):
        cases = {
            "locale en_US": (("Nobuo Uematsu", "en_US", True),),
            "en but not primary": (("Nobuo Uematsu", "en", False),),
            "no locale": (("Nobuo Uematsu", None, True),),
        }
        for case, aliases in cases.items():
            with self.subTest(case):
                uematsu = artist(UEMATSU["id"], UEMATSU_JA, "Uematsu, Nobuo", aliases=aliases)
                plan = self.plan_credit(credit((UEMATSU_JA, "", uematsu)), [uematsu])
                self.assertPlanned(plan, f"#/{UEMATSU_JA}/(2010) Disintegration",
                                   artist=UEMATSU_JA, albumartist=UEMATSU_JA, artistsort="Uematsu, Nobuo")

    def test_a_latin_name_is_never_replaced_even_with_an_english_alias(self):
        # A letter is Latin by its Unicode name, so `Ø` and `å` are Latin
        # where a check for plain ASCII would call them foreign. Digits and
        # punctuation are not letters and do not count either way.
        cases = {
            "Øystein Sevåg": ("O/Øystein Sevåg", "Oystein Sevag"),
            "Sunn O)))": ("S/Sunn O)))", "Sunn O"),
        }
        for name, (folder, alias) in cases.items():
            with self.subTest(name):
                latin = artist("1a0b0c0d-0000-4000-8000-0000000000c9", name, name,
                               aliases=((alias, "en", True),))
                plan = self.plan_credit(credit((name, "", latin)), [latin])
                self.assertPlanned(plan, f"{folder}/(2010) Disintegration",
                                   artist=name, albumartist=name, artistsort=name)

    def test_an_artist_lookup_that_answers_404_leaves_the_names_as_musicbrainz_gives_them(self):
        plan = self.plan_credit(credit((UEMATSU_JA, "", UEMATSU)), [])
        self.assertPlanned(plan, f"#/{UEMATSU_JA}/(2010) Disintegration",
                           artist=UEMATSU_JA, albumartist=UEMATSU_JA, artistsort="Uematsu, Nobuo")


#: *Red and Blue* as criterion 51 gives it: an EP credited to `Stefani`.
RED_AND_BLUE = {"title": "Red and Blue", "date": "2006",
                "release-group": {"id": builders.RELEASE_GROUP_ID, "title": "Red and Blue",
                                  "first-release-date": "2006", "primary-type": "EP", "secondary-types": []}}


class AnOwnersEditThatMovesTheAlbum(_ArtistPlanning):
    """Criteria 51 and 52 after an owner's edit: the artist folder follows the artist, not the tag.

    The artist tags hold the credited name, so an edit that rebuilds the
    folder off `ALBUMARTIST` files the album under that name instead. Only
    an edit to `albumartist` itself says the owner wants another folder.
    """

    def test_an_edit_to_anything_but_the_album_artist_keeps_the_artists_own_name(self):
        # The sort name is edited to one that moves no article, so the
        # folder has no reason to take it either way.
        cases = {
            "albumartistsort": ({"albumartistsort": ["Germanotta, Stefani"]}, "L/Lady Gaga/(2006) [EP] Red and Blue"),
            "album": ({"album": ["Red & Blue"]}, "L/Lady Gaga/(2006) [EP] Red & Blue"),
            "date": ({"date": ["2007"]}, "L/Lady Gaga/(2007) [EP] Red and Blue"),
        }
        for field, (edit, destination) in cases.items():
            with self.subTest(field):
                plan = self.plan_credit(credit(("Stefani", "", GAGA)), [GAGA], edit=edit, **RED_AND_BLUE)
                self.assertEqual((plan.destination, plan.problems), (destination, []))
                self.assertEqual(plan.files[0].target["albumartist"], ["Stefani"])

    def test_an_edit_to_the_sort_name_keeps_the_folder_a_name_not_in_latin_was_given(self):
        # Two ways the folder and `ALBUMARTIST` part under criterion 52. Her
        # own name is Latin and the katakana credit has no English alias to
        # take, so the tag keeps the katakana. His own name gives way to
        # his English alias, and the credit is Latin, so the tag keeps it.
        billie = artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie")
        cases = {
            "katakana credit with no English alias": (
                credit((BILLIE_KATAKANA, "", billie)), [billie], "B/Billie Eilish/(2010) Disintegration"),
            "Latin credit of an artist with an English alias": (
                credit(("Uematsu", "", UEMATSU)), [UEMATSU], "N/Nobuo Uematsu/(2010) Disintegration"),
        }
        for case, (release_credit, artists, destination) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(release_credit, artists, edit={"albumartistsort": ["Owner, Sort"]})
                self.assertEqual((plan.destination, plan.problems), (destination, []))

    def test_an_edit_to_the_album_artist_builds_the_folder_from_what_the_owner_typed(self):
        plan = self.plan_credit(credit(("Stefani", "", GAGA)), [GAGA], edit={"albumartist": ["Stefani Germanotta"]},
                                **RED_AND_BLUE)
        self.assertEqual((plan.destination, plan.problems), ("S/Stefani Germanotta/(2006) [EP] Red and Blue", []))
        self.assertEqual({str(Path(f.destination).parent) for f in plan.files}, {plan.destination})
