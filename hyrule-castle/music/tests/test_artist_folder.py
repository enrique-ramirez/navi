"""The artist folder and the artist tags are the credited name, romanized.

The folder is built from the name the release credits, joined by the
credit's join phrases, as `ALBUMARTIST` holds it, and not from the artist's
current MusicBrainz name. A name not in the Latin script is replaced by the
artist's primary alias with locale `en`, artist by artist, in the folder and
in both artist tags. The sort fields stay as MusicBrainz gives them.

Everything goes through `plan_album` against `test_check`'s fake MusicBrainz
and Cover Art Archive, which here also answers artist lookups. Aliases are
only on the artist lookup, never on the release, as on the real service.
An album with an owner's edit is planned by `batch identify`'s `plan_entry`
instead, the edit remembered against the release and the release pasted as
a repoint, so the edit reaches the plan with whatever `plan_entry` hands
`lay_edits` alongside it.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from musiclib import caa, mb
from musiclib.batch.identify import Clients, plan_entry, rebuild
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
    The release group lookup answers with the release's own group, so an
    edit that rebuilds the album folder keeps a prefix like `[EP]`.
    """

    def __init__(self, release: dict, artists: list[dict]) -> None:
        super().__init__(release, {**_release_group(), **release["release-group"]}, front=True)
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
        track, laid over the plan by `plan_entry`. With an edit, the plan
        `batch apply` rebuilds from the entry is left in `self.rebuilt`, and
        the digest the entry carries in `self.planned_digest`.
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
        if edit is None:
            return _plan_album(unit, release, client, art, status="auto")
        clients = Clients(mb=client, caa=art, acoustid=None)
        memory = {"edits": {release["id"]: {position_key(p): dict(edit) for p in pair(unit, release)}}}
        entry, plan = plan_entry(unit, root, clients, memory, {"action": "repoint", "release": release["id"]}, False)
        self.rebuilt = rebuild(unit, root, clients, entry["inputs"])
        self.planned_digest = entry["plan_digest"]
        return plan

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


class TheCreditedName(_ArtistPlanning):
    """Criterion 51: the folder is the name on the credit, as the album artist tag is."""

    def test_red_and_blue_credited_to_stefani_goes_under_stefani_as_its_tags_say(self):
        plan = self.plan_credit(
            credit(("Stefani", "", GAGA)), [GAGA], title="Red and Blue", date="2006",
            **{"release-group": {"id": builders.RELEASE_GROUP_ID, "title": "Red and Blue",
                                 "first-release-date": "2006", "primary-type": "EP",
                                 "secondary-types": []}})
        self.assertPlanned(plan, "S/Stefani/(2006) [EP] Red and Blue",
                           artist="Stefani", albumartist="Stefani", artistsort="Lady Gaga")

    def test_two_artists_are_each_named_as_credited_joined_by_the_credits_join_phrase(self):
        # Only the first artist is credited under another name, so a folder
        # built from the artists' own names shows as `Lady Gaga feat. ...`.
        plan = self.plan_credit(
            credit(("Stefani", " feat. ", GAGA), ("Beyoncé", "", BEYONCE)), [GAGA, BEYONCE])
        self.assertPlanned(plan, "S/Stefani feat. Beyoncé/(2010) Disintegration",
                           artist="Stefani feat. Beyoncé", albumartist="Stefani feat. Beyoncé",
                           artistsort="Lady Gaga feat. Beyoncé")

    def test_the_article_rule_reads_the_credited_name_against_the_sort_name(self):
        # The sort name moves the article of the band's own name. Credited
        # with the article, the folder takes the sort name; credited
        # without, the credit has no article to move.
        cases = {
            "Die Toten Hosen": "T/Toten Hosen, Die/(2010) Disintegration",
            "Toten Hosen": "T/Toten Hosen/(2010) Disintegration",
        }
        for credited, destination in cases.items():
            with self.subTest(credited):
                plan = self.plan_credit(credit((credited, "", HOSEN)), [HOSEN])
                self.assertPlanned(plan, destination,
                                   artist=credited, albumartist=credited, artistsort="Toten Hosen, Die")

    def test_a_credited_name_starting_with_a_dot_takes_an_underscore_and_the_hash_letter(self):
        # Criterion 21 on the credited name: credited without the dot,
        # the folder has no dot to replace either.
        special = artist("1a0b0c0d-0000-4000-8000-0000000000c8", ".38 Special", ".38 Special")
        cases = {".38 Special": "#/_38 Special/(2010) Disintegration", "38 Special": "#/38 Special/(2010) Disintegration"}
        for credited, destination in cases.items():
            with self.subTest(credited):
                plan = self.plan_credit(credit((credited, "", special)), [special])
                self.assertPlanned(plan, destination,
                                   artist=credited, albumartist=credited, artistsort=".38 Special")

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

    def test_billie_eilish_credited_in_katakana_goes_under_what_her_tags_say(self):
        # The katakana credit becomes her English alias where she has one,
        # and stays where she has none, in the tags and in the folder: her
        # own name, which is Latin, names neither.
        cases = {
            "with an English alias": (artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie",
                                             aliases=(("Billie Eilish", "en", True),)),
                                      "Billie Eilish", "B/Billie Eilish"),
            "without one": (artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie"),
                            BILLIE_KATAKANA, f"#/{BILLIE_KATAKANA}"),
        }
        for case, (billie, tag, folder) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(credit((BILLIE_KATAKANA, "", billie)), [billie])
                self.assertPlanned(plan, f"{folder}/(2010) Disintegration",
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


STROKES = artist("1a0b0c0d-0000-4000-8000-0000000000ca", "The Strokes", "Strokes, The")
HOSEN = artist("1a0b0c0d-0000-4000-8000-0000000000c7", "Die Toten Hosen", "Toten Hosen, Die")


class AnOwnersEditThatMovesTheAlbum(_ArtistPlanning):
    """After an owner's edit, the folder takes the sort name the files will carry.

    An edit to `albumartistsort` alone builds the folder from the credited
    name, as `ALBUMARTIST` holds it, and reads the edited sort name by the
    article rule. An edit to `albumartist` builds it from what the owner typed.
    """

    def test_an_edit_to_anything_but_the_album_artist_keeps_the_credited_name(self):
        # The sort name is edited to one that moves no article, so the
        # folder has no reason to take it either way.
        cases = {
            "albumartistsort": ({"albumartistsort": ["Germanotta, Stefani"]}, "S/Stefani/(2006) [EP] Red and Blue"),
            "album": ({"album": ["Red & Blue"]}, "S/Stefani/(2006) [EP] Red & Blue"),
            "date": ({"date": ["2007"]}, "S/Stefani/(2007) [EP] Red and Blue"),
        }
        for field, (edit, destination) in cases.items():
            with self.subTest(field):
                plan = self.plan_credit(credit(("Stefani", "", GAGA)), [GAGA], edit=edit, **RED_AND_BLUE)
                self.assertEqual((plan.destination, plan.problems), (destination, []))
                self.assertEqual(plan.files[0].target["albumartist"], ["Stefani"])

    def test_a_sort_edit_is_read_by_the_article_rule_against_the_credited_name(self):
        # `Gaga, Lady` moves no word of `Stefani`, so it has nothing to move.
        # The last case is the one only a rebuilt folder passes: MusicBrainz
        # does not move the article there, so the plan starts under `T/`
        # and only the owner's sort name sends it to `S/`.
        strokes_unmoved = artist(STROKES["id"], "The Strokes", "The Strokes")
        cases = {
            "Red and Blue, sort edited to Gaga, Lady": (
                credit(("Stefani", "", GAGA)), GAGA, "Gaga, Lady", "S/Stefani/(2006) [EP] Red and Blue",
                RED_AND_BLUE),
            "The Strokes, sort edited to The Strokes": (
                credit(("The Strokes", "", STROKES)), STROKES, "The Strokes", "T/The Strokes/(2010) Disintegration",
                {}),
            "The Strokes, sort edited to Strokes, The": (
                credit(("The Strokes", "", STROKES)), STROKES, "Strokes, The", "S/Strokes, The/(2010) Disintegration",
                {}),
            "The Strokes sorted by MusicBrainz as written, sort edited to Strokes, The": (
                credit(("The Strokes", "", strokes_unmoved)), strokes_unmoved, "Strokes, The",
                "S/Strokes, The/(2010) Disintegration", {}),
        }
        for case, (release_credit, the_artist, sort_name, destination, changes) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(release_credit, [the_artist], edit={"albumartistsort": [sort_name]}, **changes)
                self.assertEqual((plan.destination, plan.problems), (destination, []))
                self.assertEqual({str(Path(f.destination).parent) for f in plan.files}, {destination})
                self.assertEqual(plan.files[0].target["albumartistsort"], [sort_name])

    def test_a_sort_edit_builds_the_folder_from_the_credited_name_not_the_artists_own(self):
        # Credited without the article, so the article rule read against
        # `ALBUMARTIST` gives `T/Toten Hosen`. The band's own name would
        # give `D/Die Toten Hosen`.
        plan = self.plan_credit(credit(("Toten Hosen", "", HOSEN)), [HOSEN],
                                edit={"albumartistsort": ["Die Toten Hosen"]})
        self.assertEqual((plan.destination, plan.problems), ("T/Toten Hosen/(2010) Disintegration", []))
        self.assertEqual(plan.files[0].target["albumartist"], ["Toten Hosen"])

    def test_a_sort_edit_keeps_the_folder_the_album_artist_tag_names_whatever_the_sort(self):
        # The folder is rebuilt from what `ALBUMARTIST` holds, and in both
        # cases the artist's own name is something else. The katakana
        # credit has no English alias to take, so the tag and the folder
        # keep the katakana. The other credit is Latin, so both keep it,
        # though his own name would give way to his English alias.
        billie = artist(BILLIE_ID, "Billie Eilish", "Eilish, Billie")
        cases = {
            "katakana credit with no English alias": (
                credit((BILLIE_KATAKANA, "", billie)), [billie], f"#/{BILLIE_KATAKANA}/(2010) Disintegration"),
            "Latin credit of an artist with an English alias": (
                credit(("Uematsu", "", UEMATSU)), [UEMATSU], "U/Uematsu/(2010) Disintegration"),
        }
        for case, (release_credit, artists, destination) in cases.items():
            for sort_name in ("Owner, Sort", "Eilish, Billie", "Billie Eilish", "Uematsu, Nobuo"):
                with self.subTest(case, sort=sort_name):
                    plan = self.plan_credit(release_credit, artists, edit={"albumartistsort": [sort_name]})
                    self.assertEqual((plan.destination, plan.problems), (destination, []))

    def test_an_edit_to_the_album_artist_builds_the_folder_from_what_the_owner_typed(self):
        plan = self.plan_credit(credit(("Stefani", "", GAGA)), [GAGA], edit={"albumartist": ["Stefani Germanotta"]},
                                **RED_AND_BLUE)
        self.assertEqual((plan.destination, plan.problems), ("S/Stefani Germanotta/(2006) [EP] Red and Blue", []))
        self.assertEqual({str(Path(f.destination).parent) for f in plan.files}, {plan.destination})

    def test_an_album_artist_edit_takes_the_sort_name_the_files_will_carry(self):
        # With `albumartist` alone the files keep MusicBrainz's sort name,
        # which moves the typed name's article. With both edited, the
        # owner's sort name decides, and the typed name wins over the band's own.
        cases = {
            "album artist alone": (
                {"albumartist": ["Die Toten Hosen"]}, "T/Toten Hosen, Die/(2010) Disintegration"),
            "album artist and sort name": (
                {"albumartist": ["Die Toten Hosen"], "albumartistsort": ["Die Toten Hosen"]},
                "D/Die Toten Hosen/(2010) Disintegration"),
            "a typed name that is not hers, with its article moved": (
                {"albumartist": ["Die Hosen"], "albumartistsort": ["Hosen, Die"]}, "H/Hosen, Die/(2010) Disintegration"),
        }
        for case, (edit, destination) in cases.items():
            with self.subTest(case):
                plan = self.plan_credit(credit(("Toten Hosen", "", HOSEN)), [HOSEN], edit=edit)
                self.assertEqual((plan.destination, plan.problems), (destination, []))

    def test_batch_apply_rebuilds_the_folder_a_sort_edit_planned(self):
        # `batch apply` rebuilds the plan from the entry's inputs and writes
        # only when its digest matches. A folder that `plan_entry` rebuilds
        # and `rebuild` does not makes every sort-edited album stale.
        plan = self.plan_credit(credit(("The Strokes", "", STROKES)), [STROKES],
                                edit={"albumartistsort": ["The Strokes"]})
        self.assertEqual(plan.destination, "T/The Strokes/(2010) Disintegration")
        self.assertEqual(self.rebuilt.destination, plan.destination)
        self.assertEqual(hashlib.sha256(self.rebuilt.to_json()).hexdigest(), self.planned_digest)
